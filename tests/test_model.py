import numpy as np
import pytest

from instrument import hp4194a
from instrument.hp4194a import SimulatedInstrument, SweepSettings
from model import fit, spice
from model.capture import ABS_Z, CS, LS, RS, THETA, Capture, ModelFit
from model.library import Library

F = np.geomspace(100, 3e6, 200)


# --------------------------------------------------------------------------- grandeurs
def test_quantities_of_a_series_rl():
    f = np.array([1e3, 1e4])
    z = 2.0 + 1j * 2 * np.pi * f * 1e-3
    capture = Capture("rl", f, z)
    assert capture.quantity(LS) == pytest.approx([1e-3, 1e-3])
    assert capture.quantity(RS) == pytest.approx([2.0, 2.0])
    assert capture.quantity(ABS_Z) == pytest.approx(np.abs(z))
    assert capture.quantity(THETA) == pytest.approx(np.degrees(np.arctan2(z.imag, z.real)))


def test_cs_of_a_series_rc():
    f = np.array([1e3, 1e4])
    z = 5.0 - 1j / (2 * np.pi * f * 1e-9)
    assert Capture("rc", f, z).quantity(CS) == pytest.approx([1e-9, 1e-9])


def test_capture_is_sorted_by_frequency():
    capture = Capture("c", [3.0, 1.0, 2.0], [3j, 1j, 2j])
    assert capture.f.tolist() == [1.0, 2.0, 3.0]
    assert capture.z.imag.tolist() == [1.0, 2.0, 3.0]


# --------------------------------------------------------------------------- modèles
def test_foster_and_cauer_are_identical_at_first_order():
    x = [0.1, 1e-5, 3.0, 2e-6, 1e5, 2e-11]
    assert fit.impedance("Foster", F, x, 1, 1) == pytest.approx(
           fit.impedance("Cauer", F, x, 1, 1))


def test_model_limits():
    x = [0.1, 1e-5, 3.0, 2e-6]
    # basse fréquence : R0 ; haute fréquence : R0 + R1 en série avec L0
    assert fit.impedance("Foster", [1e-3], x, 1, 0)[0].real == pytest.approx(0.1, rel=1e-6)
    z_hf = fit.impedance("Foster", [1e12], x, 1, 0)[0]
    assert z_hf.real == pytest.approx(3.1, rel=1e-3)
    assert z_hf.imag == pytest.approx(2 * np.pi * 1e12 * 1e-5, rel=1e-6)


@pytest.mark.parametrize("kind", fit.INDUCTOR_KINDS)
def test_fit_recovers_a_known_model(kind):
    truth = [0.05, 8e-6, 0.4, 1.5e-6, 6.0, 0.6e-6]
    z = fit.impedance(kind, F, truth, 2, 0)
    result = fit.fit(F, z, kind=kind, nr=2, parallel_cap=False)
    assert result.rel_err < 1e-4
    assert fit.impedance(kind, F, result.params, 2, 0) == pytest.approx(z, rel=1e-3)


def test_fit_with_parallel_capacitance_finds_the_resonance():
    f = np.geomspace(100, 30e6, 300)
    truth = [0.05, 8e-6, 2.0, 1e-6, 40e3, 50e-12]
    z = fit.impedance("Foster", f, truth, 1, 1)
    result = fit.fit(f, z, nr=1, parallel_cap=True)
    assert result.rel_err < 1e-3
    assert result.params[-1] == pytest.approx(50e-12, rel=0.02)     # Cp
    assert result.params[1] == pytest.approx(8e-6, rel=0.02)        # L0


def test_auto_order_prefers_the_simplest_sufficient_model():
    rng = np.random.default_rng(1)
    z = fit.impedance("Foster", F, [0.05, 8e-6, 2.0, 1e-6], 1, 0)
    z = z * (1 + rng.normal(0, 0.002, F.size) + 1j * rng.normal(0, 0.002, F.size))
    result = fit.fit_auto(F, z, parallel_cap=False)
    assert result.nr == 1
    assert result.rel_err < 0.01


def test_fit_respects_the_frequency_band():
    z = fit.impedance("Foster", F, [0.05, 8e-6, 2.0, 1e-6], 1, 0)
    with pytest.raises(fit.FitError):
        fit.fit(F, z, f_min=1e3, f_max=1.1e3)                       # trop peu de points


def test_run_writes_the_result_in_the_model():
    z = fit.impedance("Foster", F, [0.05, 8e-6, 2.0, 1e-6], 1, 0)
    model = ModelFit(auto_order=False, nr=1, parallel_cap=False)
    fit.run(model, F, z)
    assert model.fitted and len(model.params) == 4 and model.nc == 0
    assert model.rel_err < 1e-4


# --------------------------------------------------------------------------- spice
def test_subckt_foster():
    text = spice.subckt("Bobine n°1", "Foster", [0.1, 1e-5, 3, 2e-6, 1e5, 2e-11], 1, 1)
    lines = text.splitlines()
    assert lines[0] == ".subckt Bobine_n_1 1 2"
    assert "L0 a n1 1e-05 Rser=0" in lines
    assert "R1 n1 2 3" in lines and "L1 n1 2 2e-06 Rser=0" in lines
    assert "Cp 1 2 2e-11" in lines
    assert lines[-1] == ".ends Bobine_n_1"


def test_subckt_cauer_ladder():
    lines = spice.subckt("m", "Cauer", [0.1, 1e-5, 3, 2e-6, 5, 1e-6], 2, 0).splitlines()
    assert "L1 n1 2 2e-06 Rser=0" in lines and "R1 n1 n2 3" in lines
    assert "L2 n2 2 1e-06 Rser=0" in lines and "R2 n2 2 5" in lines


# --------------------------------------------------------------------------- librairie
def test_library_round_trip(tmp_path):
    library = Library(tmp_path)
    library.load()
    capture = Capture("essai 1", F, fit.impedance("Foster", F, [0.05, 8e-6, 2.0, 1e-6], 1, 0),
                      settings={"points": 200})
    capture.models.append(ModelFit(kind="Cauer", nr=2, params=[1.0, 2.0], name="m1"))
    library.add(capture)

    reloaded = Library(tmp_path)
    reloaded.load()
    assert len(reloaded.captures) == 1
    copy = reloaded.captures[0]
    assert copy.name == "essai 1" and copy.id == capture.id
    assert copy.z == pytest.approx(capture.z)
    assert copy.models[0].kind == "Cauer" and copy.models[0].params == [1.0, 2.0]


def test_library_rename_and_remove(tmp_path):
    library = Library(tmp_path)
    capture = Capture("a", [1.0, 2.0], [1j, 2j])
    library.add(capture)
    capture.name = "b"
    library.save(capture)
    assert len(list(tmp_path.glob("*.json"))) == 1          # ancien fichier retiré
    assert library.unique_name("b") == "b (2)"
    library.remove(capture)
    assert not list(tmp_path.glob("*.json")) and not library.captures


def test_library_reports_unreadable_files(tmp_path):
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    library = Library(tmp_path)
    library.load()
    assert library.captures == [] and library.errors[0][0] == "bad.json"


# --------------------------------------------------------------------------- instrument
def test_parse_values():
    assert hp4194a.parse_values("1.0E+02, 2.5E+03,-3\r\n").tolist() == [100.0, 2500.0, -3.0]
    with pytest.raises(hp4194a.InstrumentError):
        hp4194a.parse_values("1.0,abc")


def test_settings_validation():
    SweepSettings().validate()
    for bad in (dict(points=500), dict(start=10.0), dict(start=1e6, stop=1e5),
                dict(integration="10s")):
        with pytest.raises(hp4194a.InstrumentError):
            SweepSettings(**bad).validate()
    assert SweepSettings(points=400, integration="100ms").estimated_duration() == \
        pytest.approx(220.0)


def test_simulated_measurement_can_be_fitted():
    SimulatedInstrument.MAX_DURATION = 0.0
    with SimulatedInstrument(seed=0) as instrument:
        f, z = instrument.measure(SweepSettings(start=100, stop=30e6, points=300))
    assert f.size == 300 and f[0] == pytest.approx(100) and f[-1] == pytest.approx(30e6)
    result = fit.fit_auto(f, z)
    assert result.rel_err < 0.02


def test_measurement_can_be_cancelled():
    SimulatedInstrument.MAX_DURATION = 5.0
    with pytest.raises(hp4194a.Cancelled):
        SimulatedInstrument().measure(SweepSettings(), cancel=lambda: True)
    SimulatedInstrument.MAX_DURATION = 0.0


class FakeVisa:
    """Session VISA factice : enregistre les commandes, répond aux requêtes."""

    def __init__(self):
        self.sent = []

    def write(self, command):
        self.sent.append(command)

    def query(self, command):
        self.sent.append(command)
        return {"X?": "100,1000\r", "A?": "1.5,2.5\r", "B?": "10,20\r", "REV?": "8733\r"}[command]

    def read_stb(self):
        return 1


def test_driver_command_sequence():
    driver = hp4194a.HP4194A(address=17)
    assert driver.resource == "GPIB0::17::INSTR"
    driver._inst = FakeVisa()
    assert driver.identify() == "HP 4194A, REV 8733"
    settings = SweepSettings(start=100, stop=3e6, points=2, log=True, integration="500µs",
                             wait_mode=hp4194a.WAIT_STATUS)
    f, z = driver.measure(settings)
    sent = driver._inst.sent[1:]
    assert sent == ["FNC1", "SWT2", "NOP=2", "START=100", "STOP=3000000", "ITM1", "IMP2",
                    "SWTRG", "TRIG", "X?", "A?", "B?"]
    assert f.tolist() == [100.0, 1000.0]
    assert z.tolist() == [1.5 + 10j, 2.5 + 20j]
