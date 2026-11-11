"""Outils communs aux tests de l'interface (sans écran, instrument simulé)."""
import numpy as np
from PyQt6 import QtCore, QtWidgets

from controller.main_controller import MainController
from controller.library_view import REF_ROLE
from instrument.hp4194a import SimulatedInstrument
from model import fit
from model.capture import Capture
from model.component import Component
from view.main_window import MainWindow

F = np.geomspace(100, 3e6, 100)
Z_COIL = fit.impedance("Foster", F, [0.05, 8e-6, 2.0, 1e-6], 1, 0)
Z_CAP = fit.impedance("Condensateur", F, [0.01, 20e-9, 1e-6], 0, 0)


_app = None


def get_app():
    """Application Qt unique des tests (référence gardée : sinon elle est détruite)."""
    global _app
    if _app is None:
        _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return _app


def make_controller(tmp_path, monkeypatch):
    """Contrôleur sur des répertoires temporaires ; dialogues remplacés."""
    get_app()
    monkeypatch.setattr(SimulatedInstrument, "MAX_DURATION", 0.0)
    ctrl = MainController(MainWindow(), tmp_path / "library", tmp_path / "settings.json",
                          tmp_path / "brouillons")
    ctrl.errors = []
    monkeypatch.setattr(ctrl, "_error", ctrl.errors.append)
    monkeypatch.setattr(ctrl, "_confirm", lambda text: True)
    ctrl.acq.child("Fréquence stop").setValue(30e6)
    ctrl.acq.child("Points").setValue(200)
    return ctrl


def dispose(ctrl):
    """Ferme et détruit les fenêtres d'un contrôleur (sinon elles s'accumulent)."""
    windows = [ctrl.view] + ([ctrl.filter_ctrl.view] if ctrl.filter_ctrl else [])
    ctrl.view.close()
    for window in windows:
        window.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    QtWidgets.QApplication.processEvents()


def measure(ctrl, link=None):
    if link is not None:
        ctrl.acq.child("Liaison").setValue(link)
    ctrl.toggle_measure()
    loop = QtCore.QEventLoop()
    ctrl._worker.finished.connect(loop.quit)
    QtCore.QTimer.singleShot(10000, loop.quit)
    loop.exec()
    QtWidgets.QApplication.processEvents()


def component(name, z=None, **fields):
    """Composant à une mesure, pour remplir une librairie de test."""
    capture = Capture("mesure 1", F, Z_COIL if z is None else z)
    return Component(name=name, captures=[capture], **fields)


def answer(ctrl, monkeypatch, target=None, **fields):
    """Réponse de la fenêtre « fiche du composant » : champs saisis, ou composant cible."""
    def ask(comp, targets=None):
        if target is not None:
            return None, target
        values = {key: getattr(comp, key) for key, _ in
                  (("name", 0), ("kind", 0), ("technology", 0), ("manufacturer", 0),
                   ("part_number", 0), ("fay_code", 0), ("nominal", 0), ("conditions", 0),
                   ("comment", 0))}
        values.update(fields)
        return values, None
    monkeypatch.setattr(ctrl, "_ask_component", ask)


def labels(model, parent=None, depth=0, column=0):
    """Textes d'un modèle Qt en arbre, indentés par niveau."""
    parent = parent or model.invisibleRootItem()
    result = []
    for row in range(parent.rowCount()):
        item = parent.child(row, column)
        result.append("  " * depth + item.text())
        result += labels(model, parent.child(row, 0), depth + 1, column)
    return result


def session_labels(ctrl):
    return labels(ctrl.session_model)


def library_names(ctrl):
    """Noms des composants visibles dans la librairie, dans l'ordre affiché."""
    return [ctrl.proxy.index(row, 0).data() for row in range(ctrl.proxy.rowCount())]


def library_row(ctrl, name):
    """Textes des colonnes d'un composant visible de la librairie."""
    for row in range(ctrl.proxy.rowCount()):
        if ctrl.proxy.index(row, 0).data() == name:
            return [ctrl.proxy.index(row, c).data() for c in range(ctrl.proxy.columnCount())]
    raise AssertionError(f"{name} absent de la librairie affichée")


def curves(plot):
    return list(plot.listDataItems())


def find_item(ctrl, ref):
    return (ctrl._find_item(ctrl.session_model, ref)
            or ctrl._find_item(ctrl.library_model, ref))


__all__ = ["F", "Z_COIL", "Z_CAP", "REF_ROLE", "make_controller", "measure", "component",
           "answer", "labels", "session_labels", "library_names", "library_row", "curves",
           "find_item", "get_app", "dispose"]
