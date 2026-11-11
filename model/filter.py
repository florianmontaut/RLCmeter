# model/filter.py
"""
Filtre passif en échelle (L, T, Pi) construit à partir de composants mesurés, de modèles
ajustés ou de composants idéaux, entre une source Rs et une charge RL.

Chaque branche est soit en série sur la ligne, soit en parallèle vers la masse. Le filtre
est calculé par produit de matrices chaîne (ABCD) :

    série Z :     [[1, Z], [0, 1]]          parallèle Z : [[1, 0], [1/Z, 1]]

Grandeurs calculées :
    gain d'insertion  = tension sur la charge avec le filtre / sans le filtre
                      = (Rs + RL) / (A.RL + B + C.Rs.RL + D.Rs)
    impédance d'entrée du filtre chargé = (A.RL + B) / (C.RL + D)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from model import fit

SERIES, SHUNT = "série", "parallèle"

# topologie -> position de chaque branche, de la source vers la charge
TOPOLOGIES = {
    "L (série, parallèle)":             (SERIES, SHUNT),
    "T (série, parallèle, série)":      (SERIES, SHUNT, SERIES),
    "Pi (parallèle, série, parallèle)": (SHUNT, SERIES, SHUNT),
}

IDEAL_UNITS = {"R": "Ω", "L": "H", "C": "F"}
DEFAULT_BAND = (100.0, 40e6)
POINTS = 500


class FilterError(Exception):
    pass


# --------------------------------------------------------------------------- composants
@dataclass
class Component:
    """Un composant du filtre : impedance(f) et bande de fréquence où il est connu."""
    label: str

    def band(self) -> tuple[float, float] | None:
        return None                         # connu à toute fréquence

    def impedance(self, f: np.ndarray) -> np.ndarray:
        raise NotImplementedError


@dataclass
class Ideal(Component):
    kind: str = "R"                         # "R", "L" ou "C"
    value: float = 1.0

    def impedance(self, f):
        w = 2.0 * np.pi * np.asarray(f, dtype=float)
        if self.kind == "R":
            return np.full(w.shape, self.value, dtype=complex)
        if self.kind == "L":
            return 1j * w * self.value
        if self.kind == "C":
            return 1.0 / (1j * w * self.value)
        raise FilterError(f"Composant idéal inconnu : {self.kind}")


@dataclass
class Measured(Component):
    """Mesure d'une capture, interpolée en log(f) (parties réelle et imaginaire)."""
    f: np.ndarray = None
    z: np.ndarray = None

    def band(self):
        return float(self.f[0]), float(self.f[-1])

    def impedance(self, f):
        x, xp = np.log(np.asarray(f, dtype=float)), np.log(self.f)
        return np.interp(x, xp, self.z.real) + 1j * np.interp(x, xp, self.z.imag)


@dataclass
class Modelled(Component):
    """Modèle ajusté (model/fit.py), valable dans la bande de son fit."""
    kind: str = "Foster"
    params: tuple = ()
    nr: int = 1
    nc: int = 0
    f_min: float = 0.0
    f_max: float = 0.0

    def band(self):
        return self.f_min, self.f_max

    def impedance(self, f):
        return fit.impedance(self.kind, f, self.params, self.nr, self.nc)


# --------------------------------------------------------------------------- calcul
@dataclass
class FilterResponse:
    f: np.ndarray
    gain: np.ndarray            # gain d'insertion complexe
    z_in: np.ndarray            # impédance d'entrée du filtre chargé

    @property
    def gain_db(self) -> np.ndarray:
        return 20.0 * np.log10(np.maximum(np.abs(self.gain), 1e-300))

    @property
    def phase_deg(self) -> np.ndarray:
        return np.degrees(np.unwrap(np.angle(self.gain)))

    def gain_db_at(self, frequency: float) -> float | None:
        """Gain (dB) à une fréquence, interpolé ; None hors de la bande calculée."""
        if not self.f[0] <= frequency <= self.f[-1]:
            return None
        return float(np.interp(np.log(frequency), np.log(self.f), self.gain_db))

    def cutoff(self, drop_db: float = 3.0) -> float | None:
        """
        Première fréquence où le gain passe à drop_db sous le gain en bas de bande
        (coupure d'un passe-bas) ; None si le gain ne descend pas jusque-là.
        """
        g = self.gain_db
        below = np.nonzero(g <= g[0] - drop_db)[0]
        if below.size == 0 or below[0] == 0:
            return None
        i = below[0]
        t = (g[0] - drop_db - g[i - 1]) / (g[i] - g[i - 1])
        return float(np.exp(np.log(self.f[i - 1]) + t * (np.log(self.f[i]) - np.log(self.f[i - 1]))))

    def minimum(self) -> tuple[float, float]:
        """(fréquence, gain en dB) de l'atténuation maximale."""
        i = int(np.argmin(self.gain_db))
        return float(self.f[i]), float(self.gain_db[i])

    def peak(self) -> tuple[float, float]:
        """(fréquence, gain en dB) du gain maximal (résonance si > 0 dB)."""
        i = int(np.argmax(self.gain_db))
        return float(self.f[i]), float(self.gain_db[i])


def common_band(components) -> tuple[float, float]:
    """Bande où tous les composants sont connus."""
    low, high = None, None
    for component in components:
        band = component.band()
        if band is None:
            continue
        low = band[0] if low is None else max(low, band[0])
        high = band[1] if high is None else min(high, band[1])
    if low is None:
        return DEFAULT_BAND
    if high <= low:
        raise FilterError("Les composants n'ont aucune bande de fréquence commune.")
    return low, high


def response(topology: str, components, rs: float = 50.0, rl: float = 50.0,
             f=None) -> FilterResponse:
    """Réponse du filtre ; f par défaut : 500 points en log sur la bande commune."""
    if topology not in TOPOLOGIES:
        raise FilterError(f"Topologie inconnue : {topology}")
    positions = TOPOLOGIES[topology]
    components = list(components)
    if len(components) != len(positions):
        raise FilterError(f"{topology} : {len(positions)} composants attendus, "
                          f"{len(components)} donnés.")
    if rl <= 0 or rs < 0:
        raise FilterError("Rs doit être positive ou nulle, RL strictement positive.")
    if f is None:
        low, high = common_band(components)
        f = np.geomspace(low, high, POINTS)
    f = np.asarray(f, dtype=float)

    # matrice chaîne de la source vers la charge
    a = np.ones(f.shape, dtype=complex)
    b = np.zeros(f.shape, dtype=complex)
    c = np.zeros(f.shape, dtype=complex)
    d = np.ones(f.shape, dtype=complex)
    with np.errstate(divide="ignore", invalid="ignore"):
        for position, component in zip(positions, components):
            z = component.impedance(f)
            if position == SERIES:
                a, b, c, d = a, a * z + b, c, c * z + d
            else:
                y = 1.0 / z
                a, b, c, d = a + b * y, b, c + d * y, d
        gain = (rs + rl) / (a * rl + b + c * rs * rl + d * rs)
        z_in = (a * rl + b) / (c * rl + d)
    return FilterResponse(f, gain, z_in)
