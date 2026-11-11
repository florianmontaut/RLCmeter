# model/component.py
"""
Composant : la fiche d'un composant caractérisé, avec ses données brutes.

    Component
      ├─ fiche : type, technologie, fabricant, référence, code Fay, valeur nominale...
      └─ captures (mesures)             une par condition de mesure ou par échantillon
           └─ models (ModelFit)         un ou plusieurs par mesure (ex: un par sous-bande)

Un modèle n'existe jamais sans la mesure qui le justifie. Tous les champs de la fiche
peuvent rester vides (composant dont on ignore le fabricant, le code Fay...).

Fichier : un .json par composant (« RLCmeter component v2 »). Les fichiers de la première
version (« RLCmeter capture v1 », une capture seule) sont relus comme un composant à une
mesure et à la fiche vide.
"""
from __future__ import annotations

import datetime
import re
import uuid
from dataclasses import dataclass, field

from model import fit
from model.capture import Capture, ModelFit

FORMAT = "RLCmeter component v2"
FORMAT_V1_PREFIX = "RLCmeter capture"

INDUCTOR, CAPACITOR = "Inductance", "Condensateur"
KINDS = (INDUCTOR, CAPACITOR)
UNITS = {INDUCTOR: "H", CAPACITOR: "F"}

# technologies proposées à la saisie (liste ouverte : la saisie reste libre)
TECHNOLOGIES = {
    INDUCTOR: ("Ferrite", "Poudre de fer", "Amorphe", "Nanocristallin", "Air"),
    CAPACITOR: ("Polypropylène", "Céramique C0G", "Céramique X7R", "Électrochimique",
                "Polyester", "Tantale"),
}

# champs de la fiche, dans l'ordre d'affichage : (attribut, libellé)
FIELDS = (("name", "Nom"), ("kind", "Type"), ("technology", "Technologie"),
          ("manufacturer", "Fabricant"), ("part_number", "Référence fabricant"),
          ("fay_code", "Code Fay"), ("nominal", "Valeur nominale"),
          ("conditions", "Conditions de mesure"), ("comment", "Commentaire"))

_PREFIXES = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6,
             "m": 1e-3, "": 1.0, "k": 1e3, "M": 1e6, "G": 1e9}
_SI = ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1.0, ""), (1e-3, "m"), (1e-6, "µ"),
       (1e-9, "n"), (1e-12, "p"), (1e-15, "f"))


class ValueFormatError(ValueError):
    """Valeur nominale illisible."""


def parse_value(text: str) -> float | None:
    """
    Valeur saisie : « 10u », « 4,7 µH », « 100nF », « 1e-6 »... None si le texte est vide.
    L'unité (H, F) est facultative et ignorée.
    """
    text = (text or "").strip()
    if not text:
        return None
    match = re.fullmatch(r"([-+]?\d*[.,]?\d+(?:[eE][-+]?\d+)?)\s*([fpnuµμmkMG]?)\s*[HFΩ]?",
                         text)
    if match is None:
        raise ValueFormatError(f"Valeur illisible : « {text} » (exemples : 10u, 4.7 µH, 100nF)")
    value = float(match.group(1).replace(",", ".")) * _PREFIXES[match.group(2)]
    if value <= 0:
        raise ValueFormatError("La valeur doit être positive.")
    return value


def format_value(value: float | None, unit: str = "") -> str:
    """« 4.7 µH », « 100 nF » ; chaîne vide si la valeur est inconnue."""
    if value is None:
        return ""
    for scale, prefix in _SI:
        if abs(value) >= scale * 0.9995:
            return f"{value / scale:.4g} {prefix}{unit}".strip()
    return f"{value:.4g} {unit}".strip()


@dataclass
class Component:
    name: str = ""
    kind: str = ""                  # INDUCTOR, CAPACITOR ou vide
    technology: str = ""
    manufacturer: str = ""
    part_number: str = ""           # référence fabricant
    fay_code: str = ""              # code interne
    nominal: float | None = None    # valeur nominale, en H ou en F
    conditions: str = ""            # niveau d'oscillateur, montage, compensation...
    comment: str = ""
    captures: list = field(default_factory=list)
    # modèle de référence : (id capture, id modèle), proposé par défaut à la réutilisation
    reference: tuple | None = None
    created: str = field(default_factory=lambda: datetime.datetime.now().isoformat(
                                                                    timespec="seconds"))
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    path: str | None = None         # fichier du composant (non enregistré dans le json)

    # ------------------------------------------------------------------ accès
    @property
    def unit(self) -> str:
        return UNITS.get(self.kind, "")

    def capture(self, capture_id: str) -> Capture | None:
        return next((c for c in self.captures if c.id == capture_id), None)

    def models(self):
        """(capture, modèle) de tous les modèles ajustés du composant."""
        return [(c, m) for c in self.captures for m in c.models if m.fitted]

    def reference_model(self) -> tuple[Capture, ModelFit] | None:
        """Modèle de référence ; à défaut de choix, le premier modèle ajusté."""
        if self.reference:
            capture = self.capture(self.reference[0])
            model = capture.model(self.reference[1]) if capture else None
            if model is not None and model.fitted:
                return capture, model
        models = self.models()
        return models[0] if models else None

    def is_reference(self, capture: Capture, model: ModelFit) -> bool:
        found = self.reference_model()
        return found is not None and found[1] is model

    def measured_value(self) -> float | None:
        """Valeur tirée du modèle de référence : L0 d'une inductance, C0 d'un condensateur."""
        found = self.reference_model()
        if found is None:
            return None
        model = found[1]
        return float(model.params[2] if model.kind == fit.CAPACITOR else model.params[1])

    def detect_kind(self) -> str:
        """Type déduit de la première mesure (réactance en bas de bande)."""
        if not self.captures:
            return ""
        first = self.captures[0]
        return CAPACITOR if fit.is_capacitive(first.f, first.z) else INDUCTOR

    def nominal_text(self) -> str:
        return format_value(self.nominal, self.unit)

    def measured_text(self) -> str:
        found = self.reference_model()
        if found is None:
            return ""
        unit = "F" if found[1].kind == fit.CAPACITOR else "H"
        return format_value(self.measured_value(), unit)

    def last_date(self) -> str:
        """Date de la mesure la plus récente (à défaut, création de la fiche)."""
        dates = [c.date for c in self.captures if c.date]
        return max(dates) if dates else self.created

    # ------------------------------------------------------------------ fichier
    def to_dict(self) -> dict:
        return {
            "format": FORMAT,
            "id": self.id,
            "created": self.created,
            "name": self.name,
            "kind": self.kind,
            "technology": self.technology,
            "manufacturer": self.manufacturer,
            "part_number": self.part_number,
            "fay_code": self.fay_code,
            "nominal": self.nominal,
            "conditions": self.conditions,
            "comment": self.comment,
            "reference": list(self.reference) if self.reference else None,
            "measurements": [c.to_dict() for c in self.captures],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Component":
        """Composant d'un fichier v2, ou d'une capture seule de la première version."""
        file_format = str(data.get("format", "")) if isinstance(data, dict) else ""
        if file_format.startswith(FORMAT_V1_PREFIX):
            capture = Capture.from_dict(data)
            component = cls(name=capture.name, captures=[capture], created=capture.date,
                            id=capture.id)
        elif file_format == FORMAT:
            reference = data.get("reference")
            component = cls(
                name=data.get("name", ""), kind=data.get("kind", ""),
                technology=data.get("technology", ""),
                manufacturer=data.get("manufacturer", ""),
                part_number=data.get("part_number", ""), fay_code=data.get("fay_code", ""),
                nominal=data.get("nominal"), conditions=data.get("conditions", ""),
                comment=data.get("comment", ""),
                captures=[Capture.from_dict(c) for c in data.get("measurements", [])],
                reference=tuple(reference) if reference else None,
                created=data.get("created", ""), id=data.get("id") or uuid.uuid4().hex)
        else:
            raise ValueError("ce n'est pas un fichier de composant RLCmeter")
        for capture in component.captures:
            capture.visible = False         # rien n'est tracé à l'ouverture
        return component

    @classmethod
    def from_capture(cls, capture: Capture) -> "Component":
        """Brouillon d'une nouvelle mesure : fiche vide, au nom de la mesure."""
        return cls(name=capture.name, captures=[capture], created=capture.date)
