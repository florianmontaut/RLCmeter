# model/capture.py
"""
Capture : une mesure, c'est-à-dire un balayage en fréquence de l'analyseur, stocké en
impédance complexe Z = R + jX. Les grandeurs affichées (Ls-Rs, |Z|-Theta, Cs-Rs) sont
toutes déduites de Z (modèle série), donc une seule mesure suffit pour tous les
affichages et pour les fits.

ModelFit : un modèle ajusté sur une capture, enregistré avec elle (il ne quitte jamais
les données brutes qui le justifient).

Les captures sont regroupées par composant : voir model/component.py.
"""
from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, field

import numpy as np


# --------------------------------------------------------------------------- grandeurs
def _w(f):
    return 2.0 * np.pi * np.asarray(f, dtype=float)


def _ls(f, z):
    return z.imag / _w(f)


def _cs(f, z):
    # Cs = -1 / (w X) ; X = 0 donne une valeur infinie, affichée comme un trou (nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        cs = -1.0 / (_w(f) * z.imag)
    return np.where(np.isfinite(cs), cs, np.nan)


@dataclass(frozen=True)
class Quantity:
    name: str
    unit: str
    compute: callable           # (f, z) -> ndarray
    log: bool = False           # échelle verticale logarithmique par défaut


LS = Quantity("Ls", "H", _ls)
RS = Quantity("Rs", "Ω", lambda f, z: z.real)
ABS_Z = Quantity("|Z|", "Ω", lambda f, z: np.abs(z), log=True)
THETA = Quantity("Theta", "°", lambda f, z: np.degrees(np.angle(z)))
CS = Quantity("Cs", "F", _cs)

# mode d'affichage -> (grandeur du graphe du haut, grandeur du graphe du bas)
DISPLAY_MODES = {
    "Ls-Rs":      (LS, RS),
    "|Z|-Theta":  (ABS_Z, THETA),
    "Cs-Rs":      (CS, RS),
}


# --------------------------------------------------------------------------- modèle ajusté
@dataclass
class ModelFit:
    """Réglages et résultat d'un fit (voir model/fit.py)."""
    kind: str = "Foster"            # "Foster", "Cauer" ou "Condensateur"
    f_min: float = 0.0
    f_max: float = 0.0
    auto_order: bool = True         # ordre choisi par critère AIC
    nr: int = 1                     # ordre : cellules R-L, ou branches R-C (condensateur)
    # option parallèle : Rp // Cp d'une inductance, résistance de fuite d'un condensateur
    parallel_cap: bool = True
    nc: int = 0                     # 0 ou 1 (résultat)
    params: list = field(default_factory=list)     # vecteur x de model/fit.py
    rel_err: float | None = None    # erreur relative moyenne |Zmod - Z| / |Z|
    aic: float | None = None
    name: str = ""
    visible: bool = True
    # traçabilité : date du dernier fit et version du logiciel qui l'a calculé
    date: str = ""
    version: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def fitted(self) -> bool:
        return len(self.params) > 0

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict) -> "ModelFit":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


# --------------------------------------------------------------------------- capture
@dataclass
class Capture:
    name: str
    f: np.ndarray                   # Hz, croissant
    z: np.ndarray                   # complexe, ohms
    date: str = field(default_factory=lambda: datetime.datetime.now().isoformat(
                                                                    timespec="seconds"))
    settings: dict = field(default_factory=dict)    # réglages du balayage
    instrument: str = ""            # réponse de l'appareil au test de liaison
    models: list = field(default_factory=list)      # ModelFit
    color: str = "#0B6BCB"
    # tracée sur les graphes : état de la session, remis à False à la lecture d'un fichier
    visible: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self):
        f = np.asarray(self.f, dtype=float)
        z = np.asarray(self.z, dtype=complex)
        if f.shape != z.shape or f.ndim != 1:
            raise ValueError("f et z doivent être deux vecteurs de même longueur")
        order = np.argsort(f, kind="stable")
        self.f, self.z = f[order], z[order]

    def quantity(self, q: Quantity) -> np.ndarray:
        return q.compute(self.f, self.z)

    def model(self, model_id: str) -> ModelFit | None:
        return next((m for m in self.models if m.id == model_id), None)

    def to_dict(self) -> dict:
        return {
            "format": "RLCmeter capture v1",
            "id": self.id,
            "name": self.name,
            "date": self.date,
            "instrument": self.instrument,
            "settings": self.settings,
            "color": self.color,
            "visible": self.visible,
            "f": self.f.tolist(),
            "z_re": self.z.real.tolist(),
            "z_im": self.z.imag.tolist(),
            "models": [m.to_dict() for m in self.models],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Capture":
        z = np.asarray(data["z_re"], dtype=float) + 1j * np.asarray(data["z_im"], dtype=float)
        return cls(name=data["name"], f=np.asarray(data["f"], dtype=float), z=z,
                   date=data.get("date", ""), settings=data.get("settings", {}),
                   instrument=data.get("instrument", ""),
                   models=[ModelFit.from_dict(m) for m in data.get("models", [])],
                   color=data.get("color", "#0B6BCB"), visible=data.get("visible", True),
                   id=data.get("id") or uuid.uuid4().hex)

    def to_csv(self, path: str) -> None:
        """Export tableur : fréquence, R, X et les grandeurs dérivées."""
        columns = [("f (Hz)", self.f), ("R (Ohm)", self.z.real), ("X (Ohm)", self.z.imag),
                   ("|Z| (Ohm)", self.quantity(ABS_Z)), ("Theta (deg)", self.quantity(THETA)),
                   ("Ls (H)", self.quantity(LS)), ("Cs (F)", self.quantity(CS))]
        header = ";".join(name for name, _ in columns)
        np.savetxt(path, np.column_stack([values for _, values in columns]),
                   delimiter=";", header=header, comments="", fmt="%.9g")
