# controller/main_controller.py
"""
Relie la librairie (captures et modèles), l'arborescence, les graphes et les paramètres.
    - mesure : AcquisitionWorker -> nouvelle capture dans la librairie ;
    - fit : ModelFit attaché à la capture, recalculé à chaque changement de réglage ;
    - affichage : les captures et modèles cochés, dans le mode choisi (Ls-Rs...).
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
import pyqtgraph as pg
from pyqtgraph.parametertree import Parameter
from PyQt6 import QtCore, QtGui, QtWidgets

from controller.acquisition import AcquisitionWorker
from instrument import hp4194a
from instrument.hp4194a import InstrumentError, SweepSettings, open_instrument
from model import fit, spice
from model.capture import DISPLAY_MODES, Capture, ModelFit
from model.library import Library
from ressources import theme
from view.main_window import MainWindow

# rôle de l'arbre : ("capture", id capture, None) ou ("model", id capture, id modèle)
REF_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1

COLORS = ("#0B6BCB", "#D9480F", "#2B8A3E", "#9C36B5", "#C2255C", "#0C8599", "#E67700",
          "#5C7CFA")

FREQ = dict(type="float", siPrefix=True, suffix="Hz", dec=True, step=0.5, decimals=6)


class MainController(QtCore.QObject):

    def __init__(self, view: MainWindow, library_folder, settings_path=None):
        super().__init__()
        self.view = view
        self.library = Library(library_folder)
        self.settings_path = pathlib.Path(settings_path) if settings_path else None
        self._worker = None
        self._rebuilding = False            # arbre en reconstruction : itemChanged ignoré
        self._selection_param = None        # paramètres de l'élément sélectionné
        self._model_group = None            # groupe « Réglages » du modèle affiché
        self._updating_model = False

        self.tree_model = QtGui.QStandardItemModel()
        view.tree.setModel(self.tree_model)
        view.displayCombo.addItems(list(DISPLAY_MODES))

        # plage de fréquence du fit, réglable à la souris (abscisses en log10 de f)
        self.region = pg.LinearRegionItem(movable=True)
        self.region.setZValue(-10)
        self.region.sigRegionChangeFinished.connect(self._on_region_moved)

        self._init_acquisition_params()
        self._load_settings()
        self._connect()

        self.library.load()
        self._rebuild_tree()
        self._apply_theme()
        if self.library.errors:
            names = ", ".join(name for name, _ in self.library.errors)
            self._status(f"Fichiers illisibles ignorés : {names}")

    # ------------------------------------------------------------------ initialisation
    def _init_acquisition_params(self):
        self.acq = Parameter.create(name="Acquisition", type="group", children=[
            dict(name="Liaison", type="list", limits=list(hp4194a.LINKS),
                 value=hp4194a.LINK_SIMULATION),
            dict(name="Adresse GPIB", type="int", value=17, limits=(0, 30)),
            dict(name="Appareil", type="str", value="", readonly=True),
            dict(name="Nom de la capture", type="str", value="mesure"),
            dict(name="Points", type="int", value=400,
                 limits=(hp4194a.POINTS_MIN, hp4194a.POINTS_MAX)),
            dict(name="Fréquence start", value=100.0,
                 limits=(hp4194a.F_MIN, hp4194a.F_MAX), **FREQ),
            dict(name="Fréquence stop", value=3e6,
                 limits=(hp4194a.F_MIN, hp4194a.F_MAX), **FREQ),
            dict(name="Balayage log", type="bool", value=True),
            dict(name="Temps d'intégration", type="list",
                 limits=list(hp4194a.INTEGRATION_TIMES), value="1ms"),
            dict(name="Fin de balayage", type="list", limits=list(hp4194a.WAIT_MODES),
                 value=hp4194a.WAIT_ESTIMATED),
            dict(name="Durée estimée", type="str", value="", readonly=True),
        ])
        self.view.acquisitionTree.setParameters(self.acq, showTop=True)
        self.acq.sigTreeStateChanged.connect(self._update_duration)
        self._update_duration()

    def _connect(self):
        v = self.view
        v.actionTestLink.triggered.connect(self.test_link)
        v.actionMeasure.triggered.connect(self.toggle_measure)
        v.actionFit.triggered.connect(self.add_model)
        v.actionExportSubckt.triggered.connect(self.export_subckt)
        v.actionExportCsv.triggered.connect(self.export_csv)
        v.actionDelete.triggered.connect(self.delete_selected)
        v.actionDark.toggled.connect(self._apply_theme)
        v.displayCombo.currentTextChanged.connect(self._refresh_graph)
        v.tree.selectionModel().currentChanged.connect(self._on_selection_changed)
        self.tree_model.itemChanged.connect(self._on_item_changed)
        v.closing.connect(self._on_closing)

    # ------------------------------------------------------------------ réglages
    def _load_settings(self):
        if self.settings_path is None or not self.settings_path.exists():
            return
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except ValueError:
            return                              # fichier abîmé : valeurs par défaut
        for name, value in data.get("acquisition", {}).items():
            if name in self.acq.names and not self.acq.child(name).readonly():
                try:
                    self.acq.child(name).setValue(value)
                except Exception:
                    pass                        # valeur d'une ancienne version
        if data.get("display") in DISPLAY_MODES:
            self.view.displayCombo.setCurrentText(data["display"])
        self.view.actionDark.setChecked(bool(data.get("dark", False)))

    def _save_settings(self):
        if self.settings_path is None:
            return
        data = {"acquisition": {p.name(): p.value() for p in self.acq.children()
                                if not p.readonly()},
                "display": self.view.displayCombo.currentText(),
                "dark": self.view.actionDark.isChecked()}
        self.settings_path.write_text(json.dumps(data, indent=1, ensure_ascii=False),
                                      encoding="utf-8")

    def _apply_theme(self, *_):
        theme.apply(QtWidgets.QApplication.instance(), self.view.actionDark.isChecked())
        self.view.apply_graph_theme()
        brush = QtGui.QColor(theme.colors()["accent"])
        brush.setAlpha(30)
        self.region.setBrush(brush)
        self._rebuild_tree(keep_selection=True)     # icônes de l'arbre à la bonne teinte

    # ------------------------------------------------------------------ messages
    def _status(self, text: str, timeout: int = 8000):
        self.view.statusBar().showMessage(text, timeout)

    def _error(self, text: str):
        QtWidgets.QMessageBox.warning(self.view, "RLCmeter", text)

    def _confirm(self, text: str) -> bool:
        buttons = QtWidgets.QMessageBox.StandardButton
        return QtWidgets.QMessageBox.question(self.view, "RLCmeter", text,
                                              buttons.Yes | buttons.No,
                                              buttons.No) == buttons.Yes

    def _ask_save_path(self, title: str, name: str, file_filter: str) -> str:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self.view, title, name, file_filter)
        return path

    # ------------------------------------------------------------------ acquisition
    def sweep_settings(self) -> SweepSettings:
        a = self.acq
        return SweepSettings(start=float(a["Fréquence start"]), stop=float(a["Fréquence stop"]),
                             points=int(a["Points"]), log=bool(a["Balayage log"]),
                             integration=a["Temps d'intégration"],
                             wait_mode=a["Fin de balayage"])

    def _update_duration(self, *_):
        try:
            seconds = self.sweep_settings().estimated_duration()
        except KeyError:
            return
        minutes, rest = divmod(round(seconds), 60)
        text = f"{minutes} min {rest:02d} s" if minutes else f"{seconds:.0f} s"
        with self.acq.treeChangeBlocker():
            self.acq.child("Durée estimée").setValue(text)

    def test_link(self):
        """Ouvre la liaison, lit l'identification de l'appareil, referme."""
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            with open_instrument(self.acq["Liaison"], self.acq["Adresse GPIB"]) as instrument:
                identity = instrument.identify()
        except InstrumentError as error:
            identity = None
            message = str(error)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        with self.acq.treeChangeBlocker():
            self.acq.child("Appareil").setValue(identity or "ERREUR")
        if identity is None:
            self._error(message)
        else:
            self._status(f"Liaison OK : {identity}")

    @property
    def measuring(self) -> bool:
        return self._worker is not None

    def toggle_measure(self):
        """Lance un balayage, ou annule celui en cours."""
        if self.measuring:
            self._worker.cancel()
            self._status("Annulation de la mesure...")
            return
        settings = self.sweep_settings()
        try:
            settings.validate()
        except InstrumentError as error:
            self._error(str(error))
            return
        self._worker = AcquisitionWorker(self.acq["Liaison"], self.acq["Adresse GPIB"],
                                         settings, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_measure_done)
        self._worker.failed.connect(self._on_measure_failed)
        self._worker.cancelled.connect(lambda: self._status("Mesure annulée."))
        self._worker.finished.connect(self._on_worker_finished)
        self._set_measuring(True)
        self._status(f"Mesure en cours ({self.acq['Durée estimée']})...", 0)
        self._worker.start()

    def _set_measuring(self, running: bool):
        v = self.view
        v.actionMeasure.setText("Annuler" if running else "Mesurer")
        v.actionMeasure.setIcon(theme.icon("stop" if running else "play"))
        v.actionTestLink.setEnabled(not running)
        v.progress.setValue(0)
        v.progress.setVisible(running)

    def _on_progress(self, fraction: float):
        self.view.progress.setValue(int(100 * fraction))

    def _on_worker_finished(self):
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        self._set_measuring(False)

    def _on_measure_failed(self, message: str):
        self._status("Mesure en échec.")
        self._error(message)

    def _on_measure_done(self, f, z, identity: str):
        settings = self._worker.settings if self._worker else self.sweep_settings()
        capture = Capture(name=self.library.unique_name(self.acq["Nom de la capture"]),
                          f=f, z=z, settings=settings.to_dict(), instrument=identity,
                          color=COLORS[len(self.library.captures) % len(COLORS)])
        self.library.add(capture)
        with self.acq.treeChangeBlocker():
            self.acq.child("Appareil").setValue(identity)
        self._rebuild_tree(select=("capture", capture.id, None))
        self._status(f"Capture « {capture.name} » enregistrée ({capture.f.size} points).")

    # ------------------------------------------------------------------ arborescence
    def _rebuild_tree(self, select=None, keep_selection=False):
        if keep_selection:
            select = self.selected_ref()
        self._rebuilding = True
        try:
            self.tree_model.clear()
            target = None
            for capture in self.library.captures:
                item = self._make_item(capture.name, capture.visible, "signal_raw",
                                       capture.color, ("capture", capture.id, None))
                self.tree_model.appendRow(item)
                if select == item.data(REF_ROLE):
                    target = item
                for model in capture.models:
                    child = self._make_item(model.name, model.visible, "signal_modified",
                                            capture.color, ("model", capture.id, model.id))
                    item.appendRow(child)
                    if select == child.data(REF_ROLE):
                        target = child
        finally:
            self._rebuilding = False
        self.view.tree.expandAll()
        if target is not None:
            self.view.tree.setCurrentIndex(target.index())
        else:
            self._on_selection_changed()

    @staticmethod
    def _make_item(name, visible, icon_name, color, ref) -> QtGui.QStandardItem:
        item = QtGui.QStandardItem(theme.icon(icon_name, tint=color), name)
        item.setCheckable(True)
        item.setCheckState(QtCore.Qt.CheckState.Checked if visible
                           else QtCore.Qt.CheckState.Unchecked)
        item.setData(ref, REF_ROLE)
        return item

    def selected_ref(self):
        index = self.view.tree.currentIndex()
        return index.data(REF_ROLE) if index.isValid() else None

    def selected(self) -> tuple[Capture | None, ModelFit | None]:
        """(capture, modèle) sélectionnés ; modèle None si une capture est sélectionnée."""
        return self._resolve(self.selected_ref())

    def _resolve(self, ref) -> tuple[Capture | None, ModelFit | None]:
        if not ref:
            return None, None
        capture = self.library.capture(ref[1])
        if capture is None:
            return None, None
        return capture, (capture.model(ref[2]) if ref[2] else None)

    def _on_item_changed(self, item: QtGui.QStandardItem):
        """Case cochée (affichage) ou nom modifié dans l'arbre."""
        if self._rebuilding:
            return
        capture, model = self._resolve(item.data(REF_ROLE))
        if capture is None:
            return
        target = model if model is not None else capture
        target.visible = item.checkState() == QtCore.Qt.CheckState.Checked
        name = item.text().strip()
        if name and name != target.name:
            target.name = self.library.unique_name(name) if model is None else name
        if item.text() != target.name:          # nom vide ou déjà pris
            self._rebuilding = True
            item.setText(target.name)
            self._rebuilding = False
        self.library.save(capture)
        self._refresh_graph()

    def _on_selection_changed(self, *_):
        self._show_selection_params()
        self._refresh_graph()

    # ------------------------------------------------------------------ paramètres
    def _show_selection_params(self):
        self._model_group = None
        capture, model = self.selected()
        if capture is None:
            self._selection_param = None
            self.view.selectionTree.clear()
            return
        if model is None:
            param = self._capture_params(capture)
        else:
            param = self._model_params(capture, model)
        self._selection_param = param
        self.view.selectionTree.setParameters(param, showTop=True)

    def _capture_params(self, capture: Capture) -> Parameter:
        s = capture.settings
        info = [("Date", capture.date.replace("T", " ")),
                ("Appareil", capture.instrument),
                ("Points", str(capture.f.size)),
                ("Plage", f"{pg.siFormat(capture.f[0], suffix='Hz')} à "
                          f"{pg.siFormat(capture.f[-1], suffix='Hz')}"),
                ("Balayage", "log" if s.get("log") else "linéaire"),
                ("Intégration", str(s.get("integration", "")))]
        param = Parameter.create(name=f"Capture : {capture.name}", type="group", children=[
            dict(name="Couleur", type="color", value=capture.color),
            *[dict(name=name, type="str", value=value, readonly=True) for name, value in info]])

        def on_color(_, value):
            capture.color = QtGui.QColor(value).name()
            self.library.save(capture)
            self._rebuild_tree(keep_selection=True)

        param.child("Couleur").sigValueChanged.connect(on_color)
        return param

    def _model_params(self, capture: Capture, model: ModelFit) -> Parameter:
        limits = (float(capture.f[0]), float(capture.f[-1]))
        param = Parameter.create(name=f"Modèle : {model.name}", type="group", children=[
            dict(name="Réglages", type="group", children=[
                dict(name="Type", type="list", limits=list(fit.KINDS), value=model.kind),
                dict(name="Fréquence min", value=model.f_min, limits=limits, **FREQ),
                dict(name="Fréquence max", value=model.f_max, limits=limits, **FREQ),
                dict(name="Ordre automatique", type="bool", value=model.auto_order),
                dict(name="Cellules R-L", type="int", value=model.nr,
                     limits=(fit.NR_MIN, fit.NR_MAX), enabled=not model.auto_order),
                dict(name="Capacité parallèle", type="bool", value=model.parallel_cap),
            ]),
            dict(name="Résultat", type="group", children=self._result_children(model)),
        ])
        self._model_group = param.child("Réglages")
        self._model_group.sigTreeStateChanged.connect(
            lambda *_: self._on_model_settings_changed(capture, model))
        return param

    @staticmethod
    def _result_children(model: ModelFit) -> list[dict]:
        if not model.fitted:
            return [dict(name="État", type="str", value="non ajusté", readonly=True)]
        children = [dict(name="Erreur relative moyenne", type="str", readonly=True,
                         value=f"{100 * model.rel_err:.3f} %"),
                    dict(name="Ordre retenu", type="str", readonly=True,
                         value=f"{model.nr} cellule(s) R-L"
                               + (", avec Rp // Cp" if model.nc else ""))]
        for (name, unit), value in zip(fit.param_names(model.nr, model.nc), model.params):
            children.append(dict(name=name, type="float", value=value, siPrefix=True,
                                 suffix=unit, decimals=5, readonly=True))
        return children

    def _on_model_settings_changed(self, capture: Capture, model: ModelFit):
        if self._updating_model:            # changement fait ci-dessous, pas par l'utilisateur
            return
        self._updating_model = True
        try:
            self._apply_model_settings(capture, model)
        finally:
            self._updating_model = False

    def _apply_model_settings(self, capture: Capture, model: ModelFit):
        g = self._model_group
        f_min, f_max = sorted((float(g["Fréquence min"]), float(g["Fréquence max"])))
        model.kind = g["Type"]
        model.f_min, model.f_max = f_min, f_max
        model.auto_order = bool(g["Ordre automatique"])
        model.parallel_cap = bool(g["Capacité parallèle"])
        if not model.auto_order:
            model.nr = int(g["Cellules R-L"])
        self._run_fit(capture, model)
        # mise à jour sur place (sans reconstruire l'arbre des paramètres en cours d'édition)
        with g.treeChangeBlocker():
            g.child("Cellules R-L").setOpts(enabled=not model.auto_order)
            g.child("Cellules R-L").setValue(model.nr)
        result = self._selection_param.child("Résultat")
        result.clearChildren()
        result.addChildren(self._result_children(model))
        self.library.save(capture)
        self._refresh_graph()

    def _run_fit(self, capture: Capture, model: ModelFit) -> bool:
        try:
            fit.run(model, capture.f, capture.z)
        except fit.FitError as error:
            model.params, model.rel_err, model.aic = [], None, None
            self._status(f"Fit impossible : {error}")
            return False
        self._status(f"{model.name} : erreur relative moyenne {100 * model.rel_err:.3f} %")
        return True

    # ------------------------------------------------------------------ actions
    def add_model(self):
        """Nouveau modèle sur la capture sélectionnée, ajusté sur toute sa bande."""
        capture, _ = self.selected()
        if capture is None:
            self._error("Sélectionnez d'abord une capture.")
            return
        model = ModelFit(f_min=float(capture.f[0]), f_max=float(capture.f[-1]))
        names = {m.name for m in capture.models}
        n = 1
        while f"{model.kind} {n}" in names:
            n += 1
        model.name = f"{model.kind} {n}"
        self._run_fit(capture, model)
        capture.models.append(model)
        self.library.save(capture)
        self._rebuild_tree(select=("model", capture.id, model.id))

    def delete_selected(self):
        capture, model = self.selected()
        if capture is None:
            return
        if model is not None:
            if not self._confirm(f"Supprimer le modèle « {model.name} » ?"):
                return
            capture.models.remove(model)
            self.library.save(capture)
            self._rebuild_tree(select=("capture", capture.id, None))
            return
        if not self._confirm(f"Supprimer la capture « {capture.name} » et ses modèles ?\n"
                             "Son fichier est supprimé de la librairie."):
            return
        self.library.remove(capture)
        self._rebuild_tree()

    def export_subckt(self):
        capture, model = self.selected()
        if model is None or not model.fitted:
            self._error("Sélectionnez d'abord un modèle ajusté.")
            return
        name = spice.subckt_name(f"{capture.name}_{model.name}")
        path = self._ask_save_path("Exporter le modèle", f"{name}.lib",
                                   "Librairie SPICE (*.lib *.sub *.cir)")
        if not path:
            return
        comment = (f"{model.kind}, {capture.name}, {model.f_min:g} Hz - {model.f_max:g} Hz, "
                   f"erreur relative moyenne {100 * model.rel_err:.3f} %")
        text = spice.subckt(name, model.kind, model.params, model.nr, model.nc, comment)
        pathlib.Path(path).write_text(text, encoding="utf-8")
        self._status(f"Modèle exporté : {path}")

    def export_csv(self):
        capture, _ = self.selected()
        if capture is None:
            self._error("Sélectionnez d'abord une capture.")
            return
        path = self._ask_save_path("Exporter la capture",
                                   f"{spice.subckt_name(capture.name)}.csv", "CSV (*.csv)")
        if not path:
            return
        capture.to_csv(path)
        self._status(f"Capture exportée : {path}")

    # ------------------------------------------------------------------ graphes
    def _refresh_graph(self, *_):
        v = self.view
        mode = v.displayCombo.currentText()
        if mode not in DISPLAY_MODES:
            return
        selected_capture, selected_model = self.selected()
        plots = (v.plot_top, v.plot_bottom)
        for plot, quantity in zip(plots, DISPLAY_MODES[mode]):
            plot.clear()
            plot.setLogMode(x=True, y=quantity.log)
            # échelle log : valeurs en clair (pas de préfixe commun à des décades entières)
            plot.getAxis("left").enableAutoSIPrefix(not quantity.log)
            plot.setLabel("left", quantity.name, units=quantity.unit)

        for capture in self.library.captures:
            color = QtGui.QColor(capture.color)
            if capture.visible:
                width = 3 if capture is selected_capture else 2
                for plot, quantity in zip(plots, DISPLAY_MODES[mode]):
                    plot.plot(capture.f, self._plottable(capture.quantity(quantity), quantity),
                              pen=pg.mkPen(color, width=width), connect="finite",
                              name=capture.name if plot is v.plot_top else None)
            for model in capture.models:
                if not (model.visible and model.fitted):
                    continue
                band = (capture.f >= model.f_min) & (capture.f <= model.f_max)
                f = capture.f[band]
                if f.size == 0:
                    continue
                z = fit.impedance(model.kind, f, model.params, model.nr, model.nc)
                pen = pg.mkPen(color.lighter(150) if theme.colors() is theme.DARK
                               else color.darker(140),
                               width=2,
                               style=QtCore.Qt.PenStyle.DashLine)
                for plot, quantity in zip(plots, DISPLAY_MODES[mode]):
                    plot.plot(f, self._plottable(quantity.compute(f, z), quantity), pen=pen,
                              connect="finite",
                              name=f"{capture.name} / {model.name}"
                                   if plot is v.plot_top else None)

        if selected_model is not None:
            self.region.blockSignals(True)
            self.region.setRegion((np.log10(selected_model.f_min),
                                   np.log10(selected_model.f_max)))
            self.region.blockSignals(False)
            v.plot_top.addItem(self.region, ignoreBounds=True)

    @staticmethod
    def _plottable(values: np.ndarray, quantity) -> np.ndarray:
        """Échelle log : les valeurs négatives ou nulles sont des trous dans la courbe."""
        if not quantity.log:
            return values
        return np.where(values > 0, values, np.nan)

    def _on_region_moved(self):
        """Plage du fit déplacée à la souris : reportée dans les réglages (qui relancent le fit)."""
        if self._model_group is None:
            return
        low, high = (10.0 ** v for v in self.region.getRegion())
        lo_lim, hi_lim = self._model_group.child("Fréquence min").opts["limits"]
        low, high = max(low, lo_lim), min(high, hi_lim)
        if high <= low:
            return
        with self._model_group.treeChangeBlocker():
            self._model_group.child("Fréquence min").setValue(low)
            self._model_group.child("Fréquence max").setValue(high)

    # ------------------------------------------------------------------ fermeture
    def _on_closing(self):
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(5000)
        self._save_settings()
