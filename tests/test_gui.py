"""Parcours de l'interface sans écran, avec l'instrument simulé."""
import numpy as np
import pytest
from PyQt6 import QtCore, QtWidgets

from controller.main_controller import MainController
from instrument.hp4194a import SimulatedInstrument
from view.main_window import MainWindow


@pytest.fixture(scope="session")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def ctrl(app, tmp_path, monkeypatch):
    monkeypatch.setattr(SimulatedInstrument, "MAX_DURATION", 0.0)
    window = MainWindow()
    controller = MainController(window, tmp_path / "library", tmp_path / "settings.json")
    controller.errors = []
    monkeypatch.setattr(controller, "_error", controller.errors.append)
    monkeypatch.setattr(controller, "_confirm", lambda text: True)
    controller.acq.child("Fréquence stop").setValue(30e6)
    controller.acq.child("Points").setValue(200)
    yield controller
    window.close()


def measure(ctrl):
    ctrl.toggle_measure()
    loop = QtCore.QEventLoop()
    ctrl._worker.finished.connect(loop.quit)
    QtCore.QTimer.singleShot(10000, loop.quit)
    loop.exec()
    QtWidgets.QApplication.processEvents()


def curves(plot):
    return [item for item in plot.listDataItems()]


def test_measure_creates_a_capture_and_plots_it(ctrl, tmp_path):
    measure(ctrl)
    assert ctrl.errors == []
    assert not ctrl.measuring
    assert len(ctrl.library.captures) == 1
    capture, model = ctrl.selected()
    assert capture.name == "mesure" and model is None and capture.f.size == 200
    assert len(list((tmp_path / "library").glob("*.json"))) == 1
    assert len(curves(ctrl.view.plot_top)) == 1 and len(curves(ctrl.view.plot_bottom)) == 1
    measure(ctrl)
    assert [c.name for c in ctrl.library.captures] == ["mesure", "mesure (2)"]


def test_fit_workflow(ctrl, tmp_path, monkeypatch):
    measure(ctrl)
    ctrl.add_model()
    capture, model = ctrl.selected()
    assert model is not None and model.fitted and model.name == "Foster 1"
    assert model.rel_err < 0.02
    # courbe mesurée + courbe du modèle, et plage du fit sur le graphe du haut
    assert len(curves(ctrl.view.plot_top)) == 2
    assert ctrl.region in ctrl.view.plot_top.items

    # changement de réglage : le fit est relancé et le résultat affiché suit
    group = ctrl._model_group
    group.child("Ordre automatique").setValue(False)
    group.child("Ordre").setValue(1)
    group.child("Branche parallèle").setValue(False)
    assert (model.auto_order, model.nr, model.nc) == (False, 1, 0)
    assert len(model.params) == 4
    names = [p.name() for p in ctrl._selection_param.child("Résultat").children()]
    assert names[-4:] == ["R0", "L0", "R1", "L1"]

    group.child("Type").setValue("Cauer")
    assert model.kind == "Cauer" and model.fitted

    # plage déplacée à la souris
    ctrl.region.setRegion((3.0, 5.0))
    ctrl.region.sigRegionChangeFinished.emit(ctrl.region)
    assert model.f_min == pytest.approx(1e3) and model.f_max == pytest.approx(1e5)

    # export LTspice
    target = tmp_path / "model.lib"
    monkeypatch.setattr(ctrl, "_ask_save_path", lambda *a: str(target))
    ctrl.export_subckt()
    assert target.read_text(encoding="utf-8").count(".subckt") == 1

    # le modèle est enregistré avec la capture
    other = MainController(MainWindow(), tmp_path / "library")
    assert other.library.captures[0].models[0].kind == "Cauer"


def test_display_modes_and_visibility(ctrl):
    measure(ctrl)
    for mode in ("|Z|-Theta", "Cs-Rs", "Ls-Rs"):
        ctrl.view.displayCombo.setCurrentText(mode)
        assert len(curves(ctrl.view.plot_top)) == 1
        x, y = curves(ctrl.view.plot_top)[0].getData()
        assert np.isfinite(y).any()
    item = ctrl.tree_model.item(0)
    item.setCheckState(QtCore.Qt.CheckState.Unchecked)
    assert not ctrl.library.captures[0].visible
    assert curves(ctrl.view.plot_top) == []


def test_rename_export_and_delete(ctrl, tmp_path, monkeypatch):
    measure(ctrl)
    ctrl.tree_model.item(0).setText("bobine A")
    capture = ctrl.library.captures[0]
    assert capture.name == "bobine A"
    assert [p.name for p in (tmp_path / "library").glob("*.json")][0].startswith("bobine_A")

    target = tmp_path / "capture.csv"
    monkeypatch.setattr(ctrl, "_ask_save_path", lambda *a: str(target))
    ctrl.export_csv()
    assert target.read_text(encoding="utf-8").splitlines()[0].startswith("f (Hz);R (Ohm)")

    ctrl.add_model()
    ctrl.delete_selected()                      # le modèle
    assert capture.models == [] and ctrl.selected() == (capture, None)
    ctrl.delete_selected()                      # la capture
    assert ctrl.library.captures == [] and not list((tmp_path / "library").glob("*.json"))


def test_link_test_and_invalid_settings(ctrl):
    ctrl.test_link()
    assert ctrl.acq["Appareil"] == "HP 4194A simulé" and ctrl.errors == []
    ctrl.acq.child("Fréquence start").setValue(20e6)
    ctrl.acq.child("Fréquence stop").setValue(1e6)
    ctrl.toggle_measure()
    assert not ctrl.measuring and len(ctrl.errors) == 1


def test_settings_are_restored(ctrl, tmp_path):
    ctrl.acq.child("Adresse GPIB").setValue(5)
    ctrl.view.displayCombo.setCurrentText("Cs-Rs")
    ctrl.view.close()
    other = MainController(MainWindow(), tmp_path / "library", tmp_path / "settings.json")
    assert other.acq["Adresse GPIB"] == 5
    assert other.view.displayCombo.currentText() == "Cs-Rs"
