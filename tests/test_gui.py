"""Parcours de l'interface sans écran : mesure, session, fit, affichage, exports."""
import numpy as np
import pytest
from PyQt6 import QtCore

from helpers import (dispose, curves, find_item, library_names, make_controller, measure,
                     session_labels)
from controller.main_controller import MainController
from instrument import hp4194a
from model import fit
from model import library as lib
from view.main_window import MainWindow

UNCHECKED = QtCore.Qt.CheckState.Unchecked


@pytest.fixture
def ctrl(tmp_path, monkeypatch):
    controller = make_controller(tmp_path, monkeypatch)
    yield controller
    dispose(controller)


# --------------------------------------------------------------------------- mesure
def test_measure_goes_to_the_session_and_is_saved_as_a_draft(ctrl, tmp_path):
    measure(ctrl)
    assert ctrl.errors == [] and not ctrl.measuring
    component, capture, model = ctrl.selected()
    assert capture.name == "mesure" and component.name == "mesure" and model is None
    assert capture.f.size == 200
    assert session_labels(ctrl) == ["mesure"] and library_names(ctrl) == []
    # enregistrée aussitôt, hors de la librairie
    assert len(list((tmp_path / "brouillons").glob("*.json"))) == 1
    assert not list((tmp_path / "library").glob("*.json"))
    assert len(curves(ctrl.view.plot_top)) == 1 and len(curves(ctrl.view.plot_bottom)) == 1
    measure(ctrl)
    assert session_labels(ctrl) == ["mesure", "mesure (2)"]


def test_previous_drafts_are_kept_but_hidden_by_default(ctrl, tmp_path, monkeypatch):
    measure(ctrl)
    ctrl.view.close()
    again = make_controller(tmp_path, monkeypatch)
    assert session_labels(again) == []                  # nouvelle session : vide
    assert len(again.drafts.components) == 1            # mais le brouillon est toujours là
    again.view.actionShowDrafts.setChecked(True)
    assert session_labels(again) == ["mesure"]
    again.select(("capture", again.drafts.components[0].id,
                  again.drafts.components[0].captures[0].id, None))
    again.add_model()
    assert again.selected()[2].fitted
    again.view.actionShowDrafts.setChecked(False)
    assert session_labels(again) == []


def test_link_test_and_invalid_settings(ctrl):
    ctrl.test_link()
    assert ctrl.acq["Appareil"] == "HP 4194A simulé" and ctrl.errors == []
    ctrl.acq.child("Fréquence start").setValue(20e6)
    ctrl.acq.child("Fréquence stop").setValue(1e6)
    ctrl.toggle_measure()
    assert not ctrl.measuring and len(ctrl.errors) == 1


# --------------------------------------------------------------------------- fit
def test_fit_workflow(ctrl, tmp_path, monkeypatch):
    measure(ctrl)
    ctrl.add_model()
    component, capture, model = ctrl.selected()
    assert model is not None and model.fitted and model.name == "Foster 1"
    assert model.rel_err < 0.02
    assert session_labels(ctrl) == ["mesure", "  Foster 1"]
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
    assert names[2:6] == ["R0", "L0", "R1", "L1"] and names[-1] == "Ajusté le"

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

    # le modèle est enregistré avec sa mesure, dans le brouillon
    saved = lib.read_component(component.path)
    assert saved.captures[0].models[0].kind == "Cauer"


def test_capacitor_workflow(ctrl, tmp_path, monkeypatch):
    ctrl.acq.child("Fréquence stop").setValue(40e6)
    # une mesure capacitive reçoit d'office le modèle « Condensateur », sans fuite
    measure(ctrl, hp4194a.LINK_SIMULATION_CAPACITOR)
    ctrl.add_model()
    component, capture, model = ctrl.selected()
    assert (model.kind, model.name, model.parallel_cap) == (fit.CAPACITOR, "Condensateur 1",
                                                            False)
    assert model.fitted and model.nr == 1 and model.rel_err < 0.01

    group = ctrl._model_group
    assert group.child("Ordre").opts["title"] == "Branches R-C"
    assert group.child("Ordre").opts["limits"] == (0, 2)
    assert group.child("Branche parallèle").opts["title"] == "Résistance de fuite"
    names = [p.name() for p in ctrl._selection_param.child("Résultat").children()]
    assert names[2:8] == ["ESR", "ESL", "C0", "R1", "C1", "Résonance série"]

    group.child("Ordre automatique").setValue(False)
    group.child("Ordre").setValue(0)
    assert model.nr == 0 and len(model.params) == 3
    group.child("Fréquence max").setValue(10e3)
    assert "ESL peu fiable" in ctrl._selection_param.child("Résultat",
                                                           "Résonance série").value()

    # passage à un modèle d'inductance : libellés, limites et ordre suivent
    group.child("Type").setValue("Foster")
    assert model.kind == "Foster" and model.nr == 1
    assert group.child("Ordre").opts["title"] == "Cellules R-L"
    assert group.child("Ordre").opts["limits"] == (1, 3)
    group.child("Type").setValue(fit.CAPACITOR)

    target = tmp_path / "c.lib"
    monkeypatch.setattr(ctrl, "_ask_save_path", lambda *a: str(target))
    ctrl.export_subckt()
    assert "Lesl a b" in target.read_text(encoding="utf-8")

    measure(ctrl, hp4194a.LINK_SIMULATION)
    ctrl.add_model()
    assert ctrl.selected()[2].kind == "Foster" and ctrl.errors == []


# --------------------------------------------------------------------------- affichage
def test_display_modes_and_visibility(ctrl):
    measure(ctrl)
    for mode in ("|Z|-Theta", "Cs-Rs", "Ls-Rs"):
        ctrl.view.displayCombo.setCurrentText(mode)
        assert len(curves(ctrl.view.plot_top)) == 1
        x, y = curves(ctrl.view.plot_top)[0].getData()
        assert np.isfinite(y).any()
    measure(ctrl)                               # deuxième mesure, sélectionnée
    assert len(curves(ctrl.view.plot_top)) == 2
    component = ctrl.session[0]
    item = find_item(ctrl, ("capture", component.id, component.captures[0].id, None))
    item.setCheckState(UNCHECKED)
    assert not component.captures[0].visible
    assert len(curves(ctrl.view.plot_top)) == 1
    # la mesure sélectionnée reste tracée même décochée
    second = ctrl.session[1]
    find_item(ctrl, ("capture", second.id, second.captures[0].id, None)).setCheckState(
        UNCHECKED)
    assert len(curves(ctrl.view.plot_top)) == 1


def test_rename_export_and_delete(ctrl, tmp_path, monkeypatch):
    measure(ctrl)
    ctrl.session_model.item(0).setText("bobine A")
    component, capture, _ = ctrl.selected()
    assert capture.name == "bobine A" and component.name == "bobine A"
    names = [p.name for p in (tmp_path / "brouillons").glob("*.json")]
    assert len(names) == 1 and names[0].startswith("bobine_A")

    target = tmp_path / "capture.csv"
    monkeypatch.setattr(ctrl, "_ask_save_path", lambda *a: str(target))
    ctrl.export_csv()
    assert target.read_text(encoding="utf-8").splitlines()[0].startswith("f (Hz);R (Ohm)")

    ctrl.add_model()
    ctrl.delete_selected()                      # le modèle
    assert capture.models == [] and ctrl.selected() == (component, capture, None)
    ctrl.delete_selected()                      # la mesure, donc le brouillon entier
    assert ctrl.session == [] and session_labels(ctrl) == []
    assert not list((tmp_path / "brouillons").glob("*.json"))


def test_settings_are_restored(ctrl, tmp_path):
    ctrl.acq.child("Adresse GPIB").setValue(5)
    ctrl.view.displayCombo.setCurrentText("Cs-Rs")
    ctrl.view.close()
    other = MainController(MainWindow(), tmp_path / "library", tmp_path / "settings.json")
    assert other.acq["Adresse GPIB"] == 5
    assert other.view.displayCombo.currentText() == "Cs-Rs"
