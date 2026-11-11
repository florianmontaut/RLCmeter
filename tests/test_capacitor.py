"""Modèle de condensateur : RLC série + branches R-C en parallèle sur C0."""
import numpy as np
import pytest
from PyQt6 import QtCore, QtWidgets

from controller.main_controller import MainController
from instrument import hp4194a
from instrument.hp4194a import SimulatedInstrument, SweepSettings
from model import filter as flt
from model import fit, spice
from view.main_window import MainWindow

CAP = fit.CAPACITOR
F = np.geomspace(100, 40e6, 400)


def noisy(z, seed=0, level=0.003):
    rng = np.random.default_rng(seed)
    return z * (1 + rng.normal(0, level, z.size) + 1j * rng.normal(0, level, z.size))


# --------------------------------------------------------------------------- modèle
def test_series_rlc_impedance():
    esr, esl, c = 0.01, 20e-9, 1e-6
    w = 2 * np.pi * F
    expected = esr + 1j * w * esl + 1 / (1j * w * c)
    assert fit.impedance(CAP, F, [esr, esl, c], 0, 0) == pytest.approx(expected)
    # à la résonance série, il ne reste que l'ESR
    f_res = 1 / (2 * np.pi * np.sqrt(esl * c))
    assert fit.impedance(CAP, [f_res], [esr, esl, c], 0, 0)[0] == pytest.approx(esr, abs=1e-9)


def test_rc_branch_makes_the_capacitance_drop_with_frequency():
    x = [0.0, 0.0, 80e-6, 0.5, 20e-6]              # relaxation à 16 kHz
    z = fit.impedance(CAP, [10.0, 10e6], x, 1, 0)
    w = 2 * np.pi * np.array([10.0, 10e6])
    assert -1 / (w * z.imag) == pytest.approx([100e-6, 80e-6], rel=1e-3)


def test_leakage_resistance_dominates_at_low_frequency():
    z = fit.impedance(CAP, [1e-6], [0.01, 1e-9, 1e-6, 1e6], 0, 1)[0]
    assert z.real == pytest.approx(1e6, rel=1e-3)


def test_description_helpers():
    assert fit.order_range(CAP) == (0, 2) and fit.order_range("Foster") == (1, 3)
    assert [n for n, _ in fit.param_names(CAP, 1, 1)] == ["ESR", "ESL", "C0", "R1", "C1", "Rf"]
    assert [n for n, _ in fit.param_names("Cauer", 1, 1)] == ["R0", "L0", "R1", "L1", "Rp", "Cp"]
    assert fit.describe_order(CAP, 0, 0) == "RLC série"
    assert fit.order_label(CAP) == "Branches R-C"
    assert fit.parallel_label(CAP) == "Résistance de fuite"
    with pytest.raises(fit.FitError):
        fit.order_range("Varistance")


def test_capacitor_detection():
    cap = fit.impedance(CAP, F, [0.01, 20e-9, 1e-6], 0, 0)
    coil = fit.impedance("Foster", F, [0.05, 8e-6, 2.0, 1e-6, 4e4, 5e-11], 1, 1)
    assert fit.is_capacitive(F, cap) and not fit.is_capacitive(F, coil)
    assert fit.capacitor_srf(F, cap) == pytest.approx(1 / (2 * np.pi * np.sqrt(20e-9 * 1e-6)),
                                                      rel=0.01)
    assert fit.capacitor_srf(F[:100], cap[:100]) is None        # résonance hors bande


# --------------------------------------------------------------------------- fit
@pytest.mark.parametrize("name, truth", [
    ("polypropylène 1 µF", [0.008, 18e-9, 1e-6]),
    ("C0G 100 nF",         [0.015, 2.5e-9, 100e-9]),
    ("électrochimique",    [0.06, 15e-9, 80e-6, 0.5, 20e-6]),
    ("deux relaxations",   [0.03, 12e-9, 300e-6, 0.2, 100e-6, 3.0, 60e-6]),
])
def test_fit_recovers_capacitors_and_their_order(name, truth):
    nr = (len(truth) - 3) // 2
    z = noisy(fit.impedance(CAP, F, truth, nr, 0))
    result = fit.fit_auto(F, z, kind=CAP, parallel_cap=False)
    assert result.nr == nr, name
    assert result.rel_err < 0.006
    assert result.params[:3] == pytest.approx(truth[:3], rel=0.03)      # ESR, ESL, C0
    # branches : comparées triées par capacité (leur ordre n'est pas imposé)
    found = sorted(zip(result.params[4::2], result.params[3::2]))
    expected = sorted(zip(truth[4::2], truth[3::2]))
    assert np.array(found) == pytest.approx(np.array(expected), rel=0.05)


def test_fixed_order_and_limits():
    z = fit.impedance(CAP, F, [0.06, 15e-9, 80e-6, 0.5, 20e-6], 1, 0)
    assert fit.fit(F, z, kind=CAP, nr=0, parallel_cap=False).rel_err > 0.02    # trop simple
    assert fit.fit(F, z, kind=CAP, nr=1, parallel_cap=False).rel_err < 1e-4
    with pytest.raises(fit.FitError):
        fit.fit(F, z, kind=CAP, nr=3)
    with pytest.raises(fit.FitError):
        fit.fit(F, z, kind="Foster", nr=0)


def test_leakage_is_found_when_visible():
    f = np.geomspace(100, 10e6, 300)
    z = fit.impedance(CAP, f, [0.5, 30e-9, 10e-9, 2e5], 0, 1)        # fuite de 200 kOhm
    result = fit.fit(f, z, kind=CAP, nr=0, parallel_cap=True)
    assert result.rel_err < 1e-3
    assert result.params[-1] == pytest.approx(2e5, rel=0.01)


# --------------------------------------------------------------------------- spice, filtre
def test_subckt_capacitor():
    lines = spice.subckt("C elec", CAP, [0.06, 15e-9, 80e-6, 0.5, 20e-6, 1e6], 1, 1).splitlines()
    assert lines == [".subckt C_elec 1 2", "Resr 1 a 0.06", "Lesl a b 1.5e-08 Rser=0",
                     "C0 b 2 8e-05", "R1 b c1 0.5", "C1 c1 2 2e-05", "Rf b 2 1e+06",
                     ".ends C_elec"]


def test_capacitor_model_in_a_filter():
    x = (0.01, 20e-9, 1e-6)
    cap = flt.Modelled("C", CAP, x, 0, 0, 100.0, 40e6)
    coil = flt.Ideal("L", "L", 10e-6)
    r = flt.response("L (série, parallèle)", [coil, cap], rs=1.0, rl=1e6)
    # atténuation maximale à la résonance série du condensateur, limitée par son ESR
    f_res = 1 / (2 * np.pi * np.sqrt(20e-9 * 1e-6))
    assert r.minimum()[0] == pytest.approx(f_res, rel=0.02)
    assert r.gain_db[-1] > r.minimum()[1] + 20          # remontée au-delà (ESL)


# --------------------------------------------------------------------------- simulateur
def test_simulated_capacitor():
    instrument = hp4194a.open_instrument(hp4194a.LINK_SIMULATION_CAPACITOR)
    instrument.MAX_DURATION = 0.0
    f, z = instrument.measure(SweepSettings(start=100, stop=40e6, points=300))
    assert fit.is_capacitive(f, z)
    result = fit.fit_auto(f, z, kind=CAP, parallel_cap=False)
    assert result.nr == 1 and result.params[2] == pytest.approx(80e-6, rel=0.03)


# --------------------------------------------------------------------------- interface
@pytest.fixture(scope="session")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def measure(ctrl, link):
    ctrl.acq.child("Liaison").setValue(link)
    ctrl.toggle_measure()
    loop = QtCore.QEventLoop()
    ctrl._worker.finished.connect(loop.quit)
    QtCore.QTimer.singleShot(10000, loop.quit)
    loop.exec()
    QtWidgets.QApplication.processEvents()


def test_capacitor_workflow_in_the_interface(app, tmp_path, monkeypatch):
    monkeypatch.setattr(SimulatedInstrument, "MAX_DURATION", 0.0)
    ctrl = MainController(MainWindow(), tmp_path / "library", tmp_path / "settings.json")
    ctrl.errors = []
    monkeypatch.setattr(ctrl, "_error", ctrl.errors.append)
    ctrl.acq.child("Fréquence stop").setValue(40e6)

    # une mesure capacitive reçoit d'office le modèle « Condensateur », sans fuite
    measure(ctrl, hp4194a.LINK_SIMULATION_CAPACITOR)
    ctrl.add_model()
    capture, model = ctrl.selected()
    assert (model.kind, model.name, model.parallel_cap) == (CAP, "Condensateur 1", False)
    assert model.fitted and model.nr == 1 and model.rel_err < 0.01

    group = ctrl._model_group
    assert group.child("Ordre").opts["title"] == "Branches R-C"
    assert group.child("Ordre").opts["limits"] == (0, 2)
    assert group.child("Branche parallèle").opts["title"] == "Résistance de fuite"
    names = [p.name() for p in ctrl._selection_param.child("Résultat").children()]
    assert names[2:] == ["ESR", "ESL", "C0", "R1", "C1", "Résonance série"]
    assert "hors" not in ctrl._selection_param.child("Résultat", "Résonance série").value()

    # ordre imposé à 0 : simple RLC
    group.child("Ordre automatique").setValue(False)
    group.child("Ordre").setValue(0)
    assert model.nr == 0 and len(model.params) == 3

    # plage réduite sous la résonance : l'ESL est signalée peu fiable
    group.child("Fréquence max").setValue(10e3)
    assert "ESL peu fiable" in ctrl._selection_param.child("Résultat",
                                                           "Résonance série").value()

    # passage à un modèle d'inductance : libellés, limites et ordre suivent
    group.child("Type").setValue("Foster")
    assert model.kind == "Foster" and model.nr == 1
    assert group.child("Ordre").opts["title"] == "Cellules R-L"
    assert group.child("Ordre").opts["limits"] == (1, 3)
    assert group.child("Branche parallèle").opts["title"] == "Capacité parallèle"
    group.child("Type").setValue(CAP)
    assert model.kind == CAP and model.fitted

    # export LTspice
    target = tmp_path / "c.lib"
    monkeypatch.setattr(ctrl, "_ask_save_path", lambda *a: str(target))
    ctrl.export_subckt()
    assert "Lesl a b" in target.read_text(encoding="utf-8")

    # une inductance garde le type choisi dans les options
    measure(ctrl, hp4194a.LINK_SIMULATION)
    ctrl.add_model()
    assert ctrl.selected()[1].kind == "Foster"
    assert ctrl.errors == []
