# controller/main_controller.py
"""
Relie les composants (mesures et modèles), les deux vues de gauche, les graphes et les
paramètres.

    - Session (en haut) : les mesures faites depuis l'ouverture. Chacune est enregistrée
      aussitôt dans le répertoire des brouillons, sous forme d'un composant à fiche vide.
    - Librairie (en bas) : les composants caractérisés, triables et filtrables. Une mesure
      de la session y entre par « Ajouter à la librairie », qui demande sa fiche.
    - Fit : ModelFit attaché à sa mesure, recalculé à chaque changement de réglage.
    - Graphes : les mesures cochées et l'élément sélectionné, dans le mode choisi.
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
import pyqtgraph as pg
from pyqtgraph.parametertree import Parameter
from PyQt6 import QtCore, QtGui, QtWidgets

from controller import library_view as lv
from controller.acquisition import AcquisitionWorker
from controller.library_view import REF_ROLE, SEARCH_ROLE, SORT_ROLE
from instrument import hp4194a
from instrument.hp4194a import InstrumentError, SweepSettings, open_instrument
from model import component as cmp
from model import fit, spice
from model import library as lib
from model.capture import DISPLAY_MODES, Capture, ModelFit
from model.component import Component
from model.library import Library, LibraryError
from ressources import app_settings, options_panel, theme
from version import VERSION
from view.component_dialog import ComponentDialog
from view.main_window import MainWindow

ROOT = pathlib.Path(__file__).resolve().parent.parent

COLORS = ("#0B6BCB", "#D9480F", "#2B8A3E", "#9C36B5", "#C2255C", "#0C8599", "#E67700",
          "#5C7CFA")

FREQ = dict(type="float", siPrefix=True, suffix="Hz", dec=True, step=0.5, decimals=6)

SESSION, LIBRARY = "session", "library"
CHECKED, UNCHECKED = QtCore.Qt.CheckState.Checked, QtCore.Qt.CheckState.Unchecked


class MainController(QtCore.QObject):

    def __init__(self, view: MainWindow, library_folder, settings_path=None,
                 drafts_folder=None):
        super().__init__()
        self.view = view
        self.settings_path = pathlib.Path(settings_path) if settings_path else None
        library_folder = pathlib.Path(library_folder)
        drafts_folder = pathlib.Path(drafts_folder) if drafts_folder \
            else library_folder.parent / "brouillons"
        # options (Utilitaires > Options) : valeurs par défaut du schéma, puis settings.json
        self.schema = app_settings.schema(str(library_folder), str(drafts_folder))
        self.options = options_panel.schema_defaults(self.schema)
        self.library = Library(library_folder)
        self.drafts = Library(drafts_folder)
        self.session: list[Component] = []  # mesures de la session et fichiers ouverts
        self.filter_ctrl = None             # fenêtre « Création de filtre » (à la demande)
        self._dialogs = []                  # fenêtres ouvertes (options, tutoriel)
        self._worker = None
        self._rebuilding = False            # vues en reconstruction : signaux ignorés
        self._active = SESSION              # vue qui porte la sélection
        self._selection_param = None        # paramètres de l'élément sélectionné
        self._model_group = None            # groupe « Réglages » du modèle affiché
        self._updating_model = False
        self._closed = False                # fenêtre fermée : plus aucune mise à jour

        # modèles Qt possédés par leur vue : détruits avec elle, dans le bon ordre, à la
        # fermeture (sans propriétaire, Python les détruisait au hasard : plantage en sortie)
        self.session_model = QtGui.QStandardItemModel(view.tree)
        view.tree.setModel(self.session_model)
        self.library_model = QtGui.QStandardItemModel(view.libraryTree)
        self.library_model.setHorizontalHeaderLabels(list(lv.COLUMNS))
        self.proxy = lv.LibraryFilterProxy(view.libraryTree)
        self.proxy.setSourceModel(self.library_model)
        view.libraryTree.setModel(self.proxy)
        view.libraryTree.sortByColumn(lv.COL_NAME, QtCore.Qt.SortOrder.AscendingOrder)
        for column, width in ((lv.COL_NAME, 150), (lv.COL_KIND, 88), (lv.COL_TECHNOLOGY, 100),
                              (lv.COL_MANUFACTURER, 76), (lv.COL_FAY, 76), (lv.COL_VALUE, 70),
                              (lv.COL_COUNT, 58)):
            view.libraryTree.setColumnWidth(column, width)
        view.displayCombo.addItems(list(DISPLAY_MODES))

        # plage de fréquence du fit, réglable à la souris (abscisses en log10 de f)
        self.region = pg.LinearRegionItem(movable=True)
        self.region.setZValue(-10)
        self.region.sigRegionChangeFinished.connect(self._on_region_moved)

        self._init_acquisition_params()
        self._load_settings()
        self._connect()

        self._load_folders()
        self._rebuild()
        self._apply_theme()
        self._report_load_errors()

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
        v.actionOpen.triggered.connect(self.open_files)
        v.actionSaveAs.triggered.connect(self.save_component_as)
        v.actionQuit.triggered.connect(v.close)
        v.actionAddToLibrary.triggered.connect(self.add_to_library)
        v.actionEditComponent.triggered.connect(self.edit_component)
        v.actionShowDrafts.toggled.connect(self._on_show_drafts_toggled)
        v.actionOptions.triggered.connect(self.open_options)
        v.actionFilter.triggered.connect(self.open_filter)
        v.actionTutorial.triggered.connect(self.show_tutorial)
        v.actionAbout.triggered.connect(self.show_about)
        v.displayCombo.currentTextChanged.connect(self._refresh_graph)
        # méthodes du contrôleur, pas des lambdas : Qt les déconnecte à sa destruction
        # (une lambda restait appelée pendant la fermeture, sur des objets déjà détruits)
        v.tree.selectionModel().currentChanged.connect(self._on_session_current)
        v.libraryTree.selectionModel().currentChanged.connect(self._on_library_current)
        v.libraryTree.doubleClicked.connect(self._on_library_double_click)
        self.session_model.itemChanged.connect(self._on_item_changed)
        self.library_model.itemChanged.connect(self._on_item_changed)
        v.searchEdit.textChanged.connect(self._on_filters_changed)
        for combo in (v.kindFilter, v.technologyFilter, v.manufacturerFilter):
            combo.currentIndexChanged.connect(self._on_filters_changed)
        v.closing.connect(self._on_closing)

    def _load_folders(self):
        """Lit la librairie et les brouillons des répertoires choisis dans les options."""
        self.library = Library(self.options["library_dir"])
        self.library.load()
        self.drafts = Library(self.options["drafts_dir"])
        self.drafts.load()
        # les fichiers ouverts à la main restent dans la session
        self.session = [c for c in self.session
                        if not self.drafts.contains(c) and not self.library.contains(c)
                        and c.path and pathlib.Path(c.path).exists()]

    def _report_load_errors(self):
        errors = self.library.errors + self.drafts.errors
        if errors:
            names = ", ".join(name for name, _ in errors)
            self._status(f"Fichiers illisibles ignorés : {names}")

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
        self.options.update({k: v for k, v in data.get("options", {}).items()
                             if k in self.options})
        if data.get("display") in DISPLAY_MODES:
            self.view.displayCombo.setCurrentText(data["display"])
        self.view.actionDark.setChecked(bool(data.get("dark", False)))

    def _save_settings(self):
        if self.settings_path is None:
            return
        data = {"acquisition": {p.name(): p.value() for p in self.acq.children()
                                if not p.readonly()},
                "options": self.options,
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
        self._rebuild(keep_selection=True)      # icônes des vues à la bonne teinte
        if self.filter_ctrl is not None:
            self.filter_ctrl.view.apply_graph_theme()
            self.filter_ctrl.compute()

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

    def _ask_open_paths(self, title: str, file_filter: str) -> list[str]:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self.view, title, str(self.library.folder), file_filter)
        return paths

    def _ask_save_path(self, title: str, name: str, file_filter: str) -> str:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self.view, title, name, file_filter)
        return path

    def _ask_component(self, component: Component, targets=None):
        """
        Fiche du composant. Renvoie (champs, composant de destination) ou None si
        l'utilisateur annule ; la destination n'est proposée qu'à l'ajout (targets).
        """
        dialog = ComponentDialog(component, self.library.values("technology"),
                                 self.library.values("manufacturer"), targets, self.view)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        target = dialog.target()
        return (None if target is not None else dialog.values()), target

    def _save(self, component: Component) -> bool:
        """Enregistre le composant ; un échec (répertoire en lecture seule) est signalé."""
        try:
            lib.save_component(component, self.drafts.folder)
        except LibraryError as error:
            self._status(str(error), 15000)
            return False
        return True

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
        """Nouvelle mesure : enregistrée aussitôt en brouillon, affichée dans la session."""
        settings = self._worker.settings if self._worker else self.sweep_settings()
        capture = Capture(name=self.drafts.unique_name(self.acq["Nom de la capture"]),
                          f=f, z=z, settings=settings.to_dict(), instrument=identity,
                          color=COLORS[len(self.drafts.components) % len(COLORS)])
        component = Component.from_capture(capture)
        try:
            self.drafts.add(component)
        except LibraryError as error:
            # mesure gardée en mémoire : rien n'est perdu tant que le logiciel reste ouvert
            self._error(f"La mesure n'a pas pu être enregistrée.\n{error}")
        self.session.append(component)
        with self.acq.treeChangeBlocker():
            self.acq.child("Appareil").setValue(identity)
        self._rebuild(select=("capture", component.id, capture.id, None))
        self._status(f"Mesure « {capture.name} » enregistrée en brouillon "
                     f"({capture.f.size} points).")

    # ------------------------------------------------------------------ composants
    def session_components(self) -> list[Component]:
        """Composants de la vue Session (avec les anciens brouillons si demandé)."""
        if not self.view.actionShowDrafts.isChecked():
            return list(self.session)
        shown = list(self.drafts.components)
        shown += [c for c in self.session if not self.drafts.contains(c)]
        return shown

    def _on_show_drafts_toggled(self, *_):
        self._rebuild(keep_selection=True)

    def all_components(self) -> list[Component]:
        """Tous les composants connus : session, brouillons affichés et librairie."""
        return self.session_components() + list(self.library.components)

    def find_component(self, component_id: str) -> Component | None:
        return next((c for c in self.all_components() if c.id == component_id), None)

    def in_library(self, component: Component) -> bool:
        return self.library.contains(component)

    # ------------------------------------------------------------------ vues de gauche
    def _rebuild(self, select=None, keep_selection=False):
        """Reconstruit les vues Session et Librairie, puis rétablit la sélection."""
        if keep_selection:
            select = self.selected_ref()
        expanded = self._expanded_components()
        self._rebuilding = True
        try:
            self._fill_session()
            self._fill_library()
            self._fill_filter_choices()
        finally:
            self._rebuilding = False
        self.view.tree.expandAll()
        self._restore_expanded(expanded)
        self._update_count()
        if not (select and self.select(select)):
            self._clear_selection()
        if self.filter_ctrl is not None:
            self.filter_ctrl.refresh_sources()

    def _make_item(self, name, icon_name, color, ref, checked=None, editable=True):
        item = QtGui.QStandardItem(theme.icon(icon_name, tint=color), name)
        item.setEditable(editable)
        item.setData(ref, REF_ROLE)
        item.setData(name, SORT_ROLE)
        if checked is not None:
            item.setCheckable(True)
            item.setCheckState(CHECKED if checked else UNCHECKED)
        return item

    def _capture_rows(self, component: Component, capture: Capture, label: str,
                      editable: bool = True) -> QtGui.QStandardItem:
        """Élément d'une mesure, avec ses modèles en enfants."""
        item = self._make_item(label, "signal_raw", capture.color,
                               ("capture", component.id, capture.id, None),
                               checked=capture.visible, editable=editable)
        for model in capture.models:
            reference = component.is_reference(capture, model)
            item.appendRow(self._row(self._make_item(
                model.name, "signal_reference" if reference else "signal_modified",
                capture.color, ("model", component.id, capture.id, model.id),
                checked=model.visible), {lv.COL_KIND: model.kind}))
        return item

    @staticmethod
    def _cell(text: str = "", sort_key=None) -> QtGui.QStandardItem:
        cell = QtGui.QStandardItem(text)
        cell.setEditable(False)
        cell.setData(text if sort_key is None else sort_key, SORT_ROLE)
        return cell

    def _row(self, first: QtGui.QStandardItem, cells: dict | None = None) -> list:
        """Ligne du tableau de la librairie : première colonne, puis cellules de texte."""
        cells = cells or {}
        return [first] + [self._cell(cells.get(column, ""))
                          for column in range(1, len(lv.COLUMNS))]

    def _fill_session(self):
        self.session_model.removeRows(0, self.session_model.rowCount())
        for component in self.session_components():
            # brouillon ordinaire : une mesure, qui donne son nom au composant
            plain = len(component.captures) == 1                 and component.name == component.captures[0].name
            for capture in component.captures:
                label = capture.name if plain else f"{component.name} / {capture.name}"
                self.session_model.appendRow(
                    self._capture_rows(component, capture, label, editable=plain))

    def _fill_library(self):
        model = self.library_model
        model.removeRows(0, model.rowCount())
        for component in self.library.components:
            first = self._make_item(component.name, "file", None,
                                    ("component", component.id, None, None), editable=False)
            first.setData(" ".join((component.part_number, component.comment,
                                    component.conditions)), SEARCH_ROLE)
            # valeur : la nominale, sinon celle du modèle de référence (marquée ≈)
            value = component.nominal if component.nominal is not None \
                else component.measured_value()
            text = component.nominal_text() or (
                f"≈ {component.measured_text()}" if component.measured_text() else "")
            row = [first,
                   self._cell(component.kind),
                   self._cell(component.technology),
                   self._cell(component.manufacturer),
                   self._cell(component.fay_code),
                   self._cell(text, value if value is not None else float("inf")),
                   self._cell(str(len(component.captures)), len(component.captures)),
                   self._cell(component.last_date()[:10], component.last_date())]
            for capture in component.captures:
                first.appendRow(self._row(
                    self._capture_rows(component, capture, capture.name),
                    {lv.COL_DATE: capture.date[:10]}))
            model.appendRow(row)

    def _fill_filter_choices(self):
        """Valeurs proposées dans les filtres de la librairie (choix courant conservé)."""
        v = self.view
        for combo, first, values in (
                (v.kindFilter, "Tous les types", list(cmp.KINDS)),
                (v.technologyFilter, "Toutes les technologies",
                 self.library.values("technology")),
                (v.manufacturerFilter, "Tous les fabricants",
                 self.library.values("manufacturer"))):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems([first, *values, lv.UNSET])
            index = combo.findText(current)
            combo.setCurrentIndex(index if index > 0 else 0)
            combo.blockSignals(False)
        self._apply_filters()

    def _apply_filters(self):
        v = self.view
        self.proxy.set_search(v.searchEdit.text())
        for combo, column in ((v.kindFilter, lv.COL_KIND),
                              (v.technologyFilter, lv.COL_TECHNOLOGY),
                              (v.manufacturerFilter, lv.COL_MANUFACTURER)):
            self.proxy.set_column_filter(
                column, combo.currentText() if combo.currentIndex() > 0 else None)

    def _on_filters_changed(self, *_):
        if self._rebuilding:
            return
        self._apply_filters()
        self._update_count()

    def clear_filters(self):
        v = self.view
        v.searchEdit.clear()
        for combo in (v.kindFilter, v.technologyFilter, v.manufacturerFilter):
            combo.setCurrentIndex(0)

    def _update_count(self):
        shown, total = self.proxy.rowCount(), len(self.library.components)
        text = f"{total} composant(s)" if shown == total \
            else f"{shown} composant(s) sur {total}"
        self.view.libraryCount.setText(text)

    def _expanded_components(self) -> set[str]:
        """Composants dépliés dans la librairie (rétablis après reconstruction)."""
        expanded = set()
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 0)
            if self.view.libraryTree.isExpanded(index):
                expanded.add(index.data(REF_ROLE)[1])
        return expanded

    def _restore_expanded(self, expanded: set[str]):
        tree = self.view.libraryTree
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 0)
            if index.data(REF_ROLE)[1] in expanded:
                tree.expand(index)
                for child in range(self.proxy.rowCount(index)):
                    tree.expand(self.proxy.index(child, 0, index))

    # ------------------------------------------------------------------ sélection
    @staticmethod
    def _find_item(model: QtGui.QStandardItemModel, ref) -> QtGui.QStandardItem | None:
        def walk(parent):
            for row in range(parent.rowCount()):
                item = parent.child(row, 0)
                if tuple(item.data(REF_ROLE)) == tuple(ref):
                    return item
                found = walk(item)
                if found is not None:
                    return found
            return None
        return walk(model.invisibleRootItem())

    def select(self, ref) -> bool:
        """Sélectionne un élément dans la vue qui le contient. False s'il est introuvable."""
        item = self._find_item(self.session_model, ref)
        if item is not None:
            self.view.tree.setCurrentIndex(item.index())
            return True
        item = self._find_item(self.library_model, ref)
        if item is None:
            return False
        index = self.proxy.mapFromSource(item.index())
        if not index.isValid():             # masqué par un filtre
            self.clear_filters()
            index = self.proxy.mapFromSource(item.index())
        tree = self.view.libraryTree
        parent = index.parent()
        while parent.isValid():
            tree.expand(parent)
            parent = parent.parent()
        tree.setCurrentIndex(index)
        tree.scrollTo(index)
        return True

    def _clear_selection(self):
        self._rebuilding = True
        try:
            self.view.tree.setCurrentIndex(QtCore.QModelIndex())
            self.view.libraryTree.setCurrentIndex(QtCore.QModelIndex())
        finally:
            self._rebuilding = False
        self._on_selection_changed()

    def _on_session_current(self, current: QtCore.QModelIndex, _previous=None):
        self._on_current_changed(SESSION, current)

    def _on_library_current(self, current: QtCore.QModelIndex, _previous=None):
        self._on_current_changed(LIBRARY, current)

    def _on_current_changed(self, source: str, current: QtCore.QModelIndex):
        """Une seule sélection pour les deux vues : la dernière cliquée."""
        if self._rebuilding or self._closed or not current.isValid():
            return
        self._active = source
        other = self.view.libraryTree if source == SESSION else self.view.tree
        self._rebuilding = True
        try:
            other.setCurrentIndex(QtCore.QModelIndex())
            other.clearSelection()
        finally:
            self._rebuilding = False
        self._on_selection_changed()

    def selected_ref(self):
        tree = self.view.tree if self._active == SESSION else self.view.libraryTree
        index = tree.currentIndex()
        if not index.isValid():
            return None
        ref = index.siblingAtColumn(0).data(REF_ROLE)
        return tuple(ref) if ref else None

    def _resolve(self, ref) -> tuple[Component | None, Capture | None, ModelFit | None]:
        if not ref:
            return None, None, None
        component = self.find_component(ref[1])
        if component is None:
            return None, None, None
        capture = component.capture(ref[2]) if ref[2] else None
        model = capture.model(ref[3]) if capture is not None and ref[3] else None
        return component, capture, model

    def selected(self) -> tuple[Component | None, Capture | None, ModelFit | None]:
        """(composant, mesure, modèle) sélectionnés ; None pour les niveaux non atteints."""
        return self._resolve(self.selected_ref())

    def selected_capture(self) -> tuple[Component | None, Capture | None]:
        """Mesure visée par une action : celle sélectionnée, ou l'unique d'un composant."""
        component, capture, _ = self.selected()
        if component is not None and capture is None and len(component.captures) == 1:
            capture = component.captures[0]
        return component, capture

    def _on_item_changed(self, item: QtGui.QStandardItem):
        """Case cochée (affichage) ou nom modifié dans une vue."""
        if self._rebuilding or self._closed or item.column() != 0:
            return
        component, capture, model = self._resolve(item.data(REF_ROLE))
        if capture is None:
            return
        target = model if model is not None else capture
        target.visible = item.checkState() == CHECKED
        name = item.text().strip()
        renamed = bool(name) and name != target.name and item.isEditable()
        if renamed:
            target.name = name
            # brouillon à une seule mesure : le composant porte le nom de sa mesure
            if model is None and not self.in_library(component) \
                    and len(component.captures) == 1:
                component.name = name
            self._save(component)
        if item.isEditable() and item.text() != target.name:      # nom vide refusé
            self._rebuilding = True
            item.setText(target.name)
            self._rebuilding = False
        self._refresh_graph()
        if renamed and self.filter_ctrl is not None:
            self.filter_ctrl.refresh_sources()

    def _on_selection_changed(self, *_):
        self._show_selection_params()
        self._refresh_graph()
        component, capture, _model = self.selected()
        v = self.view
        v.actionAddToLibrary.setEnabled(component is not None
                                        and not self.in_library(component))
        v.actionEditComponent.setEnabled(component is not None)

    def _on_library_double_click(self, index: QtCore.QModelIndex):
        ref = index.siblingAtColumn(0).data(REF_ROLE)
        if ref and ref[0] == "component":
            self.edit_component()

    # ------------------------------------------------------------------ paramètres
    def _show_selection_params(self):
        self._model_group = None
        component, capture, model = self.selected()
        if component is None:
            self._selection_param = None
            self.view.selectionTree.clear()
            return
        if model is not None:
            param = self._model_params(component, capture, model)
        elif capture is not None:
            param = self._capture_params(component, capture)
        else:
            param = self._component_params(component)
        self._selection_param = param
        self.view.selectionTree.setParameters(param, showTop=True)

    def _component_params(self, component: Component) -> Parameter:
        values = {"name": component.name, "kind": component.kind,
                  "technology": component.technology,
                  "manufacturer": component.manufacturer,
                  "part_number": component.part_number, "fay_code": component.fay_code,
                  "nominal": component.nominal_text(), "conditions": component.conditions,
                  "comment": component.comment}
        children = [dict(name=label, type="str", value=values[key] or "", readonly=True)
                    for key, label in cmp.FIELDS]
        found = component.reference_model()
        reference = f"{found[0].name} / {found[1].name}" if found else "aucun"
        children += [
            dict(name="Valeur du modèle", type="str", readonly=True,
                 value=component.measured_text()),
            dict(name="Modèle de référence", type="str", value=reference, readonly=True),
            dict(name="Mesures", type="str", value=str(len(component.captures)),
                 readonly=True),
            dict(name="Modifier la fiche...", type="action"),
        ]
        param = Parameter.create(name=f"Composant : {component.name}", type="group",
                                 children=children)
        param.child("Modifier la fiche...").sigActivated.connect(
            lambda *_: QtCore.QTimer.singleShot(0, self.edit_component))
        return param

    def _capture_params(self, component: Component, capture: Capture) -> Parameter:
        s = capture.settings
        info = [("Composant", component.name),
                ("Date", capture.date.replace("T", " ")),
                ("Appareil", capture.instrument),
                ("Points", str(capture.f.size)),
                ("Plage", f"{pg.siFormat(capture.f[0], suffix='Hz')} à "
                          f"{pg.siFormat(capture.f[-1], suffix='Hz')}"),
                ("Balayage", "log" if s.get("log") else "linéaire"),
                ("Intégration", str(s.get("integration", "")))]
        param = Parameter.create(name=f"Mesure : {capture.name}", type="group", children=[
            dict(name="Couleur", type="color", value=capture.color),
            *[dict(name=name, type="str", value=value, readonly=True) for name, value in info]])

        def on_color(_, value):
            capture.color = QtGui.QColor(value).name()
            self._save(component)
            self._rebuild(keep_selection=True)

        param.child("Couleur").sigValueChanged.connect(on_color)
        return param

    def _model_params(self, component: Component, capture: Capture,
                      model: ModelFit) -> Parameter:
        limits = (float(capture.f[0]), float(capture.f[-1]))
        param = Parameter.create(name=f"Modèle : {model.name}", type="group", children=[
            dict(name="Modèle de référence", type="bool",
                 value=component.is_reference(capture, model),
                 tip="Modèle proposé par défaut quand le composant est réutilisé"),
            dict(name="Réglages", type="group", children=[
                dict(name="Type", type="list", limits=list(fit.KINDS), value=model.kind),
                dict(name="Fréquence min", value=model.f_min, limits=limits, **FREQ),
                dict(name="Fréquence max", value=model.f_max, limits=limits, **FREQ),
                dict(name="Ordre automatique", type="bool", value=model.auto_order),
                # titres selon le type : cellules R-L / branches R-C, capacité / fuite
                dict(name="Ordre", title=fit.order_label(model.kind), type="int",
                     value=model.nr, limits=fit.order_range(model.kind),
                     enabled=not model.auto_order),
                dict(name="Branche parallèle", title=fit.parallel_label(model.kind),
                     type="bool", value=model.parallel_cap),
            ]),
            dict(name="Résultat", type="group", children=self._result_children(model)),
        ])
        self._model_group = param.child("Réglages")
        self._model_group.sigTreeStateChanged.connect(
            lambda *_: self._on_model_settings_changed(component, capture, model))

        def on_reference(_, checked):
            component.reference = (capture.id, model.id) if checked else None
            self._save(component)
            # différé : la reconstruction remplace l'arbre de paramètres en cours d'édition
            QtCore.QTimer.singleShot(0, lambda: self._rebuild(keep_selection=True))

        param.child("Modèle de référence").sigValueChanged.connect(on_reference)
        return param

    @staticmethod
    def _result_children(model: ModelFit) -> list[dict]:
        if not model.fitted:
            return [dict(name="État", type="str", value="non ajusté", readonly=True)]
        children = [dict(name="Erreur relative moyenne", type="str", readonly=True,
                         value=f"{100 * model.rel_err:.3f} %"),
                    dict(name="Ordre retenu", type="str", readonly=True,
                         value=fit.describe_order(model.kind, model.nr, model.nc))]
        names = fit.param_names(model.kind, model.nr, model.nc)
        for (name, unit), value in zip(names, model.params):
            children.append(dict(name=name, type="float", value=value, siPrefix=True,
                                 suffix=unit, decimals=5, readonly=True))
        if model.kind == fit.CAPACITOR:
            # résonance série du modèle ; hors de la bande du fit, l'ESL n'est pas mesurée
            f_res = 1.0 / (2.0 * np.pi * np.sqrt(model.params[1] * model.params[2]))
            note = "" if model.f_min <= f_res <= model.f_max else \
                " (hors de la plage du fit : ESL peu fiable)"
            children.append(dict(name="Résonance série", type="str", readonly=True,
                                 value=pg.siFormat(f_res, precision=4, suffix="Hz") + note))
        if model.date:
            children.append(dict(name="Ajusté le", type="str", readonly=True,
                                 value=f"{model.date.replace('T', ' ')} (v{model.version})"))
        return children

    def _on_model_settings_changed(self, component, capture, model):
        if self._updating_model:            # changement fait ci-dessous, pas par l'utilisateur
            return
        self._updating_model = True
        try:
            self._apply_model_settings(component, capture, model)
        finally:
            self._updating_model = False

    def _apply_model_settings(self, component: Component, capture: Capture,
                              model: ModelFit):
        g = self._model_group
        f_min, f_max = sorted((float(g["Fréquence min"]), float(g["Fréquence max"])))
        kind_changed = g["Type"] != model.kind
        model.kind = g["Type"]
        model.f_min, model.f_max = f_min, f_max
        model.auto_order = bool(g["Ordre automatique"])
        model.parallel_cap = bool(g["Branche parallèle"])
        if not model.auto_order:
            low, high = fit.order_range(model.kind)
            model.nr = int(min(max(g["Ordre"], low), high))
        self._run_fit(capture, model)
        # mise à jour sur place (sans reconstruire l'arbre des paramètres en cours d'édition)
        with g.treeChangeBlocker():
            order = g.child("Ordre")
            if kind_changed:
                order.setOpts(title=fit.order_label(model.kind))
                order.setLimits(fit.order_range(model.kind))
                g.child("Branche parallèle").setOpts(title=fit.parallel_label(model.kind))
            order.setOpts(enabled=not model.auto_order)
            order.setValue(model.nr)
        result = self._selection_param.child("Résultat")
        result.clearChildren()
        result.addChildren(self._result_children(model))
        self._save(component)
        self._refresh_graph()
        if self.filter_ctrl is not None:
            self.filter_ctrl.refresh_sources()

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
        """Nouveau modèle sur la mesure sélectionnée, ajusté sur toute sa bande."""
        component, capture = self.selected_capture()
        if capture is None:
            self._error("Sélectionnez d'abord une mesure.")
            return
        if fit.is_capacitive(capture.f, capture.z):
            # condensateur : résistance de fuite décochée par défaut
            kind, parallel = fit.CAPACITOR, False
        else:
            kind = self.options["default_kind"]
            parallel = bool(self.options["default_parallel_cap"])
        model = ModelFit(kind=kind, parallel_cap=parallel,
                         auto_order=bool(self.options["default_auto_order"]),
                         f_min=float(capture.f[0]), f_max=float(capture.f[-1]))
        names = {m.name for m in capture.models}
        n = 1
        while f"{model.kind} {n}" in names:
            n += 1
        model.name = f"{model.kind} {n}"
        self._run_fit(capture, model)
        capture.models.append(model)
        self._save(component)
        self._rebuild(select=("model", component.id, capture.id, model.id))

    def add_to_library(self):
        """
        Range le composant de la session sélectionné dans la librairie, après saisie de
        sa fiche : comme nouveau composant, ou comme mesure d'un composant existant.
        """
        component, capture, _ = self.selected()
        if component is None or self.in_library(component):
            self._error("Sélectionnez d'abord une mesure de la session.")
            return
        answer = self._ask_component(component, targets=list(self.library.components))
        if answer is None:
            return
        values, target = answer
        was_draft = self.drafts.contains(component)
        source_path = component.path
        try:
            if target is None:
                for key, value in values.items():
                    setattr(component, key, value)
                self.library.add(component)
                destination = component
            else:
                target.captures.extend(component.captures)
                lib.save_component(target)
                destination = target
        except LibraryError as error:
            component.path = source_path        # rien n'a bougé : le brouillon reste
            if target is not None:
                del target.captures[-len(component.captures):]
            self._error(str(error))
            return
        # le brouillon a rejoint la librairie : son fichier n'a plus lieu d'être
        # (un fichier ouvert à la main, lui, est laissé à sa place)
        if was_draft:
            self.drafts.discard(component, source_path)
        self.session = [c for c in self.session if c is not component]
        shown = capture or destination.captures[-1]
        shown.visible = True
        self.clear_filters()
        self._rebuild(select=("capture", destination.id, shown.id, None))
        self._status(f"« {destination.name} » : ajouté à la librairie.")

    def edit_component(self):
        """Modifie la fiche du composant sélectionné."""
        component, _, _ = self.selected()
        if component is None:
            return
        answer = self._ask_component(component)
        if answer is None:
            return
        values, _ = answer
        for key, value in values.items():
            setattr(component, key, value)
        # brouillon à une seule mesure : la mesure suit le nom du composant
        if not self.in_library(component) and len(component.captures) == 1:
            component.captures[0].name = component.name
        self._save(component)
        self._rebuild(keep_selection=True)

    def delete_selected(self):
        component, capture, model = self.selected()
        if component is None:
            return
        if model is not None:
            if not self._confirm(f"Supprimer le modèle « {model.name} » ?"):
                return
            capture.models.remove(model)
            if component.reference and component.reference[1] == model.id:
                component.reference = None
            self._save(component)
            self._rebuild(select=("capture", component.id, capture.id, None))
            return
        if capture is not None and len(component.captures) > 1:
            if not self._confirm(f"Supprimer la mesure « {capture.name} » et ses modèles ?"):
                return
            component.captures.remove(capture)
            if component.reference and component.reference[0] == capture.id:
                component.reference = None
            self._save(component)
            self._rebuild(select=("component", component.id, None, None))
            return
        self._delete_component(component)

    def _delete_component(self, component: Component):
        stored = self.library if self.in_library(component) else \
            self.drafts if self.drafts.contains(component) else None
        if stored is None:
            # fichier ouvert à la main : retiré de la session, son fichier reste en place
            self.session = [c for c in self.session if c is not component]
            self._rebuild()
            return
        where = "de la librairie" if stored is self.library else "des brouillons"
        if not self._confirm(f"Supprimer « {component.name} », ses mesures et ses modèles ?\n"
                             f"Son fichier est supprimé {where}."):
            return
        try:
            stored.remove(component)
        except LibraryError as error:
            self._error(str(error))
            return
        self.session = [c for c in self.session if c is not component]
        self._rebuild()

    def export_subckt(self):
        """Modèle sélectionné, ou modèle de référence du composant sélectionné."""
        component, capture, model = self.selected()
        if component is not None and model is None:
            found = component.reference_model() if capture is None else None
            if found is not None:
                capture, model = found
        if model is None or not model.fitted:
            self._error("Sélectionnez d'abord un modèle ajusté.")
            return
        name = spice.subckt_name(f"{component.name}_{model.name}")
        path = self._ask_save_path("Exporter le modèle", f"{name}.lib",
                                   "Librairie SPICE (*.lib *.sub *.cir)")
        if not path:
            return
        details = ", ".join(v for v in (component.manufacturer, component.part_number,
                                        component.fay_code) if v)
        comment = (f"{model.kind}, {component.name}" + (f" ({details})" if details else "")
                   + f", mesure {capture.name} du {capture.date[:10]}, "
                   f"{model.f_min:g} Hz - {model.f_max:g} Hz, "
                   f"erreur relative moyenne {100 * model.rel_err:.3f} %")
        text = spice.subckt(name, model.kind, model.params, model.nr, model.nc, comment)
        pathlib.Path(path).write_text(text, encoding="utf-8")
        self._status(f"Modèle exporté : {path}")

    def export_csv(self):
        _, capture = self.selected_capture()
        if capture is None:
            self._error("Sélectionnez d'abord une mesure.")
            return
        path = self._ask_save_path("Exporter la mesure",
                                   f"{spice.subckt_name(capture.name)}.csv", "CSV (*.csv)")
        if not path:
            return
        capture.to_csv(path)
        self._status(f"Mesure exportée : {path}")

    # ------------------------------------------------------------------ menu Fichier
    def open_files(self):
        """Ouvre des fichiers de composant (.json) situés hors des répertoires scrutés."""
        paths = self._ask_open_paths("Ouvrir un composant", "Composant RLCmeter (*.json)")
        last, errors = None, []
        for path in paths:
            target = pathlib.Path(path).resolve()
            known = next((c for c in self.all_components() + self.drafts.components
                          if c.path and pathlib.Path(c.path).resolve() == target), None)
            if known is None:
                try:
                    known = lib.read_component(target)
                except LibraryError as error:
                    errors.append(str(error))
                    continue
                known = self.find_component(known.id) or known
            if not self.in_library(known) and not any(c is known for c in self.session):
                self.session.append(known)
            last = known
        if last is not None:
            capture = last.captures[0] if last.captures else None
            if capture is not None:
                capture.visible = True
            self._rebuild(select=("capture", last.id, capture.id, None) if capture
                          else ("component", last.id, None, None))
        if errors:
            self._error("\n".join(errors))

    def save_component_as(self):
        """Copie le composant sélectionné (mesures et modèles compris) dans un fichier."""
        component, _, _ = self.selected()
        if component is None:
            self._error("Sélectionnez d'abord un composant ou une mesure.")
            return
        path = self._ask_save_path("Sauvegarder le composant sous",
                                   f"{spice.subckt_name(component.name)}.json",
                                   "Composant RLCmeter (*.json)")
        if not path:
            return
        try:
            lib.save_copy(component, path)
        except LibraryError as error:
            self._error(str(error))
            return
        self._status(f"Composant copié : {path}")

    # ------------------------------------------------------------------ menu Utilitaires
    def open_options(self):
        dialog = options_panel.OptionsPannel(self.schema, self.options, self.view)
        dialog.accepted.connect(lambda: self.apply_options(dialog.getOptions()))
        self._dialogs.append(dialog)
        dialog.finished.connect(lambda *_: self._dialogs.remove(dialog))
        dialog.show()
        return dialog

    def apply_options(self, options: dict):
        """Nouvelles options ; un changement de répertoire relit librairie et brouillons."""
        options = dict(options)
        for key in ("library_dir", "drafts_dir"):
            if not str(options.get(key) or "").strip():
                options[key] = self.options[key]
        changed = (pathlib.Path(options["library_dir"]) != self.library.folder
                   or pathlib.Path(options["drafts_dir"]) != self.drafts.folder)
        self.options.update(options)
        self._save_settings()
        if changed:
            self._load_folders()
            self._rebuild()
            self._report_load_errors()
            self._status(f"Librairie : {self.library.folder} "
                         f"({len(self.library.components)} composant(s))")

    def open_filter(self):
        if self.filter_ctrl is None:
            from controller.filter_controller import FilterController
            self.filter_ctrl = FilterController(self.all_components, self.view)
        self.filter_ctrl.show()

    # ------------------------------------------------------------------ menu Aide
    def show_tutorial(self):
        browser = QtWidgets.QTextBrowser(self.view)
        browser.setWindowFlag(QtCore.Qt.WindowType.Window)
        browser.setWindowTitle("RLCmeter — tutoriel")
        browser.setMarkdown((ROOT / "docs" / "tutoriel.md").read_text(encoding="utf-8"))
        browser.resize(760, 720)
        browser.show()
        self._dialogs.append(browser)
        return browser

    def show_about(self):
        QtWidgets.QMessageBox.about(
            self.view, "À propos de RLCmeter",
            f"<b>RLCmeter {VERSION}</b><br>Mesure d'impédance avec un HP 4194A (GPIB), "
            "modélisation d'inductances et de condensateurs, estimation de filtres.<br><br>"
            f"Librairie : {self.library.folder}<br>Brouillons : {self.drafts.folder}")

    # ------------------------------------------------------------------ graphes
    def _refresh_graph(self, *_):
        v = self.view
        mode = v.displayCombo.currentText()
        if mode not in DISPLAY_MODES:
            return
        sel_component, sel_capture, sel_model = self.selected()
        plots = (v.plot_top, v.plot_bottom)
        for plot, quantity in zip(plots, DISPLAY_MODES[mode]):
            plot.clear()
            plot.setLogMode(x=True, y=quantity.log)
            # échelle log : valeurs en clair (pas de préfixe commun à des décades entières)
            plot.getAxis("left").enableAutoSIPrefix(not quantity.log)
            plot.setLabel("left", quantity.name, units=quantity.unit)

        for component in self.all_components():
            many = len(component.captures) > 1 or component.name != component.captures[0].name \
                if component.captures else False
            for capture in component.captures:
                # tracées : les mesures cochées, celle sélectionnée, et toutes celles du
                # composant sélectionné
                selected = capture is sel_capture or (component is sel_component
                                                      and sel_capture is None)
                if not (capture.visible or selected):
                    continue
                label = f"{component.name} / {capture.name}" if many else capture.name
                color = QtGui.QColor(capture.color)
                width = 3 if capture is sel_capture else 2
                for plot, quantity in zip(plots, DISPLAY_MODES[mode]):
                    plot.plot(capture.f, self._plottable(capture.quantity(quantity), quantity),
                              pen=pg.mkPen(color, width=width), connect="finite",
                              name=label if plot is v.plot_top else None)
                for model in capture.models:
                    if not (model.fitted and (model.visible or model is sel_model)):
                        continue
                    band = (capture.f >= model.f_min) & (capture.f <= model.f_max)
                    f = capture.f[band]
                    if f.size == 0:
                        continue
                    z = fit.impedance(model.kind, f, model.params, model.nr, model.nc)
                    pen = pg.mkPen(color.lighter(150) if theme.colors() is theme.DARK
                                   else color.darker(140),
                                   width=2, style=QtCore.Qt.PenStyle.DashLine)
                    for plot, quantity in zip(plots, DISPLAY_MODES[mode]):
                        plot.plot(f, self._plottable(quantity.compute(f, z), quantity),
                                  pen=pen, connect="finite",
                                  name=f"{label} / {model.name}"
                                       if plot is v.plot_top else None)

        if sel_model is not None:
            self.region.blockSignals(True)
            self.region.setRegion((np.log10(sel_model.f_min), np.log10(sel_model.f_max)))
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
        self._closed = True
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(5000)
        if self.filter_ctrl is not None:
            self.filter_ctrl.view.close()
        self._save_settings()
