import numpy as np
import pytest

from model import filter as flt
from model import fit

L_TOPO = "L (série, parallèle)"
T_TOPO = "T (série, parallèle, série)"
PI_TOPO = "Pi (parallèle, série, parallèle)"


def ideal(kind, value):
    return flt.Ideal(kind, kind, value)


def test_rc_low_pass():
    # R = 1 kOhm, C = 159.155 nF : coupure à 1 kHz ; source idéale, charge négligeable
    f = np.array([10.0, 1e3, 1e5])
    r = flt.response(L_TOPO, [ideal("R", 1e3), ideal("C", 159.155e-9)], rs=0.0, rl=1e12, f=f)
    assert np.abs(r.gain) == pytest.approx([1.0, 1 / np.sqrt(2), 0.01], rel=1e-3)
    assert r.phase_deg[1] == pytest.approx(-45.0, abs=0.01)


def test_cutoff_and_key_figures():
    r = flt.response(L_TOPO, [ideal("R", 1e3), ideal("C", 159.155e-9)], rs=0.0, rl=1e12)
    assert r.f[0] == pytest.approx(100.0) and r.f[-1] == pytest.approx(40e6)
    assert r.cutoff() == pytest.approx(1e3, rel=0.01)
    assert r.gain_db_at(1e5) == pytest.approx(-40.0, abs=0.05)
    assert r.gain_db_at(1.0) is None
    assert r.minimum()[0] == pytest.approx(40e6)
    assert r.peak()[1] == pytest.approx(0.0, abs=0.05)


def test_insertion_gain_is_referenced_to_the_unfiltered_load():
    # résistance série de 50 ohms entre source et charge de 50 ohms : 100/150
    r = flt.response(L_TOPO, [ideal("R", 50.0), ideal("R", 1e15)], rs=50.0, rl=50.0,
                     f=np.array([1e3]))
    assert np.abs(r.gain[0]) == pytest.approx(100.0 / 150.0, rel=1e-6)
    assert r.z_in[0].real == pytest.approx(100.0, rel=1e-6)


def test_t_filter_matches_nodal_analysis():
    f = np.geomspace(1e3, 1e7, 50)
    w = 2 * np.pi * f
    l1, c, l2, rs, rl = 10e-6, 100e-9, 22e-6, 50.0, 75.0
    r = flt.response(T_TOPO, [ideal("L", l1), ideal("C", c), ideal("L", l2)], rs, rl, f)
    # nœud central : diviseur entre (Rs + jwL1) et Zc // (jwL2 + RL)
    za, zc, zb = rs + 1j * w * l1, 1 / (1j * w * c), 1j * w * l2 + rl
    zp = zc * zb / (zc + zb)
    v_load = zp / (za + zp) * rl / zb
    assert r.gain == pytest.approx(v_load / (rl / (rs + rl)), rel=1e-9)


def test_pi_filter_is_a_low_pass():
    r = flt.response(PI_TOPO, [ideal("C", 100e-9), ideal("L", 10e-6), ideal("C", 100e-9)])
    assert r.gain_db[0] == pytest.approx(0.0, abs=0.1)
    assert r.gain_db[-1] < -80


def test_measured_and_modelled_components_agree():
    f = np.geomspace(100, 3e6, 400)
    x = [0.05, 8e-6, 2.0, 1e-6]
    z = fit.impedance("Foster", f, x, 1, 0)
    measured = flt.Measured("mesure", f, z)
    modelled = flt.Modelled("modèle", "Foster", tuple(x), 1, 0, 1e3, 1e6)
    cap = ideal("C", 1e-6)
    a = flt.response(T_TOPO, [measured, cap, measured])
    b = flt.response(T_TOPO, [modelled, cap, modelled], f=a.f)
    assert (a.f[0], a.f[-1]) == pytest.approx((100, 3e6))
    assert a.gain_db == pytest.approx(b.gain_db, abs=0.02)
    # bande commune : celle du modèle, plus étroite
    c = flt.response(T_TOPO, [measured, cap, modelled])
    assert (c.f[0], c.f[-1]) == pytest.approx((1e3, 1e6))


def test_errors():
    with pytest.raises(flt.FilterError):
        flt.response(T_TOPO, [ideal("L", 1e-6)])                    # composants manquants
    with pytest.raises(flt.FilterError):
        flt.response("Z", [])
    low = flt.Measured("a", np.array([1e2, 1e3]), np.array([1j, 2j]))
    high = flt.Measured("b", np.array([1e5, 1e6]), np.array([1j, 2j]))
    with pytest.raises(flt.FilterError):
        flt.response(L_TOPO, [low, high])                           # pas de bande commune
