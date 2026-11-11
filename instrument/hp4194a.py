# instrument/hp4194a.py
"""
Pilote de l'analyseur d'impédance HP 4194A (GPIB, commandes HP-IB), repris de la macro
Excel RLCmeter_extractorV4 (docs/vba/Module1.bas), et un instrument simulé pour
travailler sans l'appareil.

La mesure est toujours faite en R-X (IMP2) : la capture est stockée en impédance complexe
et les autres grandeurs en sont déduites (voir model/capture.py).

Changements par rapport à la macro :
    - le temps d'intégration et la fonction de mesure sont envoyés AVANT le déclenchement
      du balayage (la macro les envoyait après) ;
    - attente de fin de balayage au choix : durée estimée (comportement de la macro, valeur
      par défaut) ou octet d'état de l'appareil (plus rapide, À VALIDER sur l'appareil).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, asdict

import numpy as np

INTEGRATION_TIMES = ("500µs", "1ms", "100ms")
# commande ITM et durée par point retenue par la macro (50 x 0.5 ms, 1 ms, 11 ms)
_ITM = {"500µs": 1, "1ms": 2, "100ms": 3}
_SECONDS_PER_POINT = {"500µs": 0.025, "1ms": 0.05, "100ms": 0.55}

WAIT_ESTIMATED = "Durée estimée"
WAIT_STATUS = "Octet d'état"
WAIT_MODES = (WAIT_ESTIMATED, WAIT_STATUS)

LINK_SIMULATION = "Simulation"
LINK_GPIB = "GPIB"
LINKS = (LINK_SIMULATION, LINK_GPIB)

F_MIN, F_MAX = 100.0, 40e6          # plage de l'appareil en mesure d'impédance
POINTS_MIN, POINTS_MAX = 2, 401

# octet d'état du 4194A : bit 0 = fin de mesure / de balayage (à confirmer sur l'appareil)
STATUS_SWEEP_END = 0x01


class InstrumentError(Exception):
    pass


class Cancelled(Exception):
    """Mesure annulée par l'utilisateur."""


@dataclass
class SweepSettings:
    start: float = 100.0
    stop: float = 3e6
    points: int = 400
    log: bool = True
    integration: str = "1ms"
    wait_mode: str = WAIT_ESTIMATED

    def validate(self) -> None:
        if self.integration not in _ITM:
            raise InstrumentError(f"Temps d'intégration inconnu : {self.integration}")
        if not POINTS_MIN <= self.points <= POINTS_MAX:
            raise InstrumentError(f"Nombre de points hors limites ({POINTS_MIN} à "
                                  f"{POINTS_MAX}) : {self.points}")
        if not F_MIN <= self.start < self.stop <= F_MAX:
            raise InstrumentError(f"Plage de fréquence invalide : {self.start:g} Hz à "
                                  f"{self.stop:g} Hz (appareil : {F_MIN:g} Hz à {F_MAX:g} Hz)")

    def estimated_duration(self) -> float:
        """Durée du balayage en secondes (formule de la macro)."""
        return self.points * _SECONDS_PER_POINT[self.integration]

    def to_dict(self) -> dict:
        return asdict(self)


def _number(value: float) -> str:
    """Nombre au format attendu par l'appareil (point décimal, pas d'espace)."""
    return f"{value:.10g}"


def parse_values(text: str) -> np.ndarray:
    """Réponse à X?, A? ou B? : valeurs séparées par des virgules."""
    fields = [v for v in text.replace("\r", "").replace("\n", "").split(",") if v.strip()]
    try:
        return np.array([float(v) for v in fields], dtype=float)
    except ValueError as error:
        raise InstrumentError(f"Réponse illisible de l'appareil : {text[:60]!r}") from error


def _wait(duration: float, progress, cancel, done=None) -> None:
    """Attend duration secondes, ou moins si done() devient vrai ; annulable."""
    start = time.monotonic()
    while True:
        elapsed = time.monotonic() - start
        if cancel is not None and cancel():
            raise Cancelled()
        if progress is not None:
            progress(min(elapsed / duration, 1.0) if duration > 0 else 1.0)
        if elapsed >= duration or (done is not None and done()):
            return
        time.sleep(min(0.1, max(duration - elapsed, 0.0)))


# --------------------------------------------------------------------------- appareil réel
class HP4194A:
    """HP 4194A via VISA (Keysight IO Libraries, interface 82357B)."""

    TIMEOUT_MS = 30000

    def __init__(self, address: int = 17, board: int = 0):
        self.resource = f"GPIB{board}::{int(address)}::INSTR"
        self._rm = None
        self._inst = None

    # -- liaison
    def open(self) -> None:
        try:
            import pyvisa
        except ImportError as error:
            raise InstrumentError("Le paquet pyvisa n'est pas installé.") from error
        try:
            self._rm = pyvisa.ResourceManager()
            self._inst = self._rm.open_resource(self.resource)
            self._inst.timeout = self.TIMEOUT_MS
            # comme la macro (VISA-COM) : pas de caractère de fin à l'écriture (EOI seul),
            # fin de lecture sur LF
            self._inst.write_termination = ""
            self._inst.read_termination = "\n"
        except Exception as error:
            self.close()
            raise InstrumentError(f"Ouverture de {self.resource} impossible : {error}") \
                from error

    def close(self) -> None:
        """Rend la main à la face avant (GTL) et ferme la liaison."""
        if self._inst is not None:
            try:
                from pyvisa import constants
                self._inst.control_ren(constants.RENLineOperation.address_gtl)
            except Exception:
                pass            # retour en local non critique
            try:
                self._inst.close()
            except Exception:
                pass
        if self._rm is not None:
            try:
                self._rm.close()
            except Exception:
                pass
        self._inst = self._rm = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()

    def _write(self, command: str) -> None:
        try:
            self._inst.write(command)
        except Exception as error:
            raise InstrumentError(f"Envoi de « {command} » impossible : {error}") from error

    def _query(self, command: str) -> str:
        try:
            return self._inst.query(command).strip()
        except Exception as error:
            raise InstrumentError(f"Pas de réponse à « {command} » : {error}") from error

    # -- commandes
    def identify(self) -> str:
        """Le 4194A ne connaît pas *IDN? : la révision du firmware sert de test."""
        return f"HP 4194A, REV {self._query('REV?')}"

    def configure(self, settings: SweepSettings) -> None:
        settings.validate()
        for command in ("FNC1",                                     # fonction impédance
                        "SWT2" if settings.log else "SWT1",         # balayage log / linéaire
                        f"NOP={int(settings.points)}",
                        f"START={_number(settings.start)}",
                        f"STOP={_number(settings.stop)}",
                        f"ITM{_ITM[settings.integration]}",         # temps d'intégration
                        "IMP2"):                                    # R-X
            self._write(command)

    def _sweep_done(self) -> bool:
        try:
            return bool(self._inst.read_stb() & STATUS_SWEEP_END)
        except Exception:
            return False

    def measure(self, settings: SweepSettings, progress=None, cancel=None):
        """
        Configure l'appareil, lance un balayage et renvoie (f, z).
            progress : callable(fraction 0..1), cancel : callable() -> bool
        """
        self.configure(settings)
        if settings.wait_mode == WAIT_STATUS:
            self._sweep_done()                  # lecture : efface un état antérieur
        self._write("SWTRG")
        self._write("TRIG")
        duration = settings.estimated_duration()
        done = self._sweep_done if settings.wait_mode == WAIT_STATUS else None
        _wait(duration, progress, cancel, done)
        f = parse_values(self._query("X?"))
        r = parse_values(self._query("A?"))
        x = parse_values(self._query("B?"))
        if not (f.size == r.size == x.size) or f.size == 0:
            raise InstrumentError(f"Données incohérentes : {f.size} fréquences, {r.size} "
                                  f"valeurs R, {x.size} valeurs X.")
        return f, r + 1j * x


# --------------------------------------------------------------------------- simulation
class SimulatedInstrument:
    """
    Faux 4194A : renvoie l'impédance d'une inductance à pertes (modèle de Foster à deux
    cellules, résonance propre vers 7 MHz) avec un peu de bruit de mesure.
    """
    PARAMS = [0.05, 8e-6, 0.4, 1.5e-6, 6.0, 0.6e-6, 40e3, 50e-12]
    NR, NC = 2, 1
    NOISE = 0.003
    MAX_DURATION = 1.5          # la simulation ne fait pas attendre un vrai balayage

    def __init__(self, seed=None):
        self._rng = np.random.default_rng(seed)

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def identify(self) -> str:
        return "HP 4194A simulé"

    def measure(self, settings: SweepSettings, progress=None, cancel=None):
        from model.fit import impedance
        settings.validate()
        _wait(min(settings.estimated_duration(), self.MAX_DURATION), progress, cancel)
        if settings.log:
            f = np.geomspace(settings.start, settings.stop, settings.points)
        else:
            f = np.linspace(settings.start, settings.stop, settings.points)
        z = impedance("Foster", f, self.PARAMS, self.NR, self.NC)
        noise = self._rng.normal(0, self.NOISE, f.size) + 1j * self._rng.normal(
                                                                0, self.NOISE, f.size)
        return f, z * (1 + noise)


def open_instrument(link: str, address: int = 17):
    """Instrument (non encore ouvert) pour le type de liaison choisi."""
    if link == LINK_SIMULATION:
        return SimulatedInstrument()
    if link == LINK_GPIB:
        return HP4194A(address)
    raise InstrumentError(f"Type de liaison inconnu : {link}")
