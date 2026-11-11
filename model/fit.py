# model/fit.py
"""
Ajustement d'un modèle de composant sur une impédance mesurée.

Inductances (reprise de la macro VBA FitFosterRL, elle-même portée de MATLAB) :
    x = [R0, L0, R1, L1, ..., R_NR, L_NR, (Rp, Cp)]
    Foster : Zs = R0 + jwL0 + somme_k (Rk // jwLk)
    Cauer  : Zs = R0 + jwL0 + E1,  E_k = jwLk // (Rk + E_k+1),  E_NR+1 = 0
    Option parallèle (NC = 1) : Z = Zs // Rp // Cp
    Les deux modèles sont identiques pour NR = 1.

Condensateurs (dual du Foster : branches R-C série en parallèle sur C0) :
    x = [ESR, ESL, C0, R1, C1, ..., R_NR, C_NR, (Rf)]
    Z = ESR + jw.ESL + 1 / ( jw.C0 + somme_k 1/(Rk + 1/(jw.Ck)) + 1/Rf )
    NR = 0 : simple RLC série. Chaque branche Rk-Ck traduit une relaxation du
    diélectrique (capacité et pertes qui varient avec la fréquence).
    Option parallèle (NC = 1) : résistance de fuite Rf sur C0.

Dans tous les cas NR est l'ordre du modèle et NC (0 ou 1) l'option parallèle.

Différences avec la macro VBA :
    - paramètres ajustés en logarithme (toujours positifs) par moindres carrés bornés, à
      la place du Nelder-Mead avec écrêtage ;
    - une seule branche Rp // Cp : deux branches en parallèle sont strictement
      équivalentes à une seule (Rp1 // Rp2, Cp1 + Cp2), la seconde n'apportait rien ;
    - le critère AIC est calculé sur les résidus relatifs, ceux que le fit minimise.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

FOSTER, CAUER, CAPACITOR = "Foster", "Cauer", "Condensateur"
INDUCTOR_KINDS = (FOSTER, CAUER)
KINDS = (FOSTER, CAUER, CAPACITOR)
MIN_POINTS = 8
AIC_MARGIN = 10.0           # gain d'AIC exigé pour retenir un ordre supérieur

# bornes des paramètres (min, max)
BOUNDS = {
    # inductances
    "R": (1e-9, 1e9), "L": (1e-15, 1e3), "Rp": (1e-3, 1e9), "Cp": (1e-16, 1e-6),
    # condensateurs
    "ESR": (1e-6, 1e4), "ESL": (1e-12, 1e-3), "C": (1e-15, 10.0),
    "Rk": (1e-6, 1e9), "Rf": (1.0, 1e12),
}


class FitError(Exception):
    """Fit impossible (trop peu de points, type de modèle inconnu...)."""


@dataclass
class FitResult:
    kind: str
    nr: int
    nc: int
    params: np.ndarray
    rel_err: float          # moyenne de |Zmod - Z| / |Z|
    aic: float


# --------------------------------------------------------------------------- description
def check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise FitError(f"Type de modèle inconnu : {kind}")


def order_range(kind: str) -> tuple[int, int]:
    """Ordres possibles : cellules R-L d'une inductance, branches R-C d'un condensateur."""
    check_kind(kind)
    return (0, 2) if kind == CAPACITOR else (1, 3)


def order_label(kind: str) -> str:
    return "Branches R-C" if kind == CAPACITOR else "Cellules R-L"


def parallel_label(kind: str) -> str:
    return "Résistance de fuite" if kind == CAPACITOR else "Capacité parallèle"


def describe_order(kind: str, nr: int, nc: int) -> str:
    if kind == CAPACITOR:
        text = "RLC série" if nr == 0 else f"RLC série + {nr} branche(s) R-C"
        return text + (", avec résistance de fuite" if nc else "")
    return f"{nr} cellule(s) R-L" + (", avec Rp // Cp" if nc else "")


def _layout(kind: str, nr: int, nc: int) -> list[tuple[str, str, str]]:
    """(nom, unité, clé des bornes) de chaque paramètre du vecteur x."""
    check_kind(kind)
    if kind == CAPACITOR:
        layout = [("ESR", "Ω", "ESR"), ("ESL", "H", "ESL"), ("C0", "F", "C")]
        for k in range(1, nr + 1):
            layout += [(f"R{k}", "Ω", "Rk"), (f"C{k}", "F", "C")]
        if nc:
            layout.append(("Rf", "Ω", "Rf"))
        return layout
    layout = [("R0", "Ω", "R"), ("L0", "H", "L")]
    for k in range(1, nr + 1):
        layout += [(f"R{k}", "Ω", "R"), (f"L{k}", "H", "L")]
    if nc:
        layout += [("Rp", "Ω", "Rp"), ("Cp", "F", "Cp")]
    return layout


def param_names(kind: str, nr: int, nc: int) -> list[tuple[str, str]]:
    """(nom, unité) de chaque paramètre du vecteur x."""
    return [(name, unit) for name, unit, _ in _layout(kind, nr, nc)]


def _param_bounds(kind: str, nr: int, nc: int) -> np.ndarray:
    return np.array([BOUNDS[key] for _, _, key in _layout(kind, nr, nc)], dtype=float)


def is_capacitive(f, z) -> bool:
    """Le composant mesuré est-il un condensateur ? (réactance négative en bas de bande)"""
    z = np.asarray(z, dtype=complex)[np.argsort(np.asarray(f, dtype=float))]
    low = z[:max(z.size // 3, 1)]
    return bool(low.size and np.median(low.imag) < 0)


# --------------------------------------------------------------------------- modèles
def _inductor(kind: str, w: np.ndarray, x, nr: int, nc: int) -> np.ndarray:
    jw = 1j * w
    z = x[0] + jw * x[1]
    cells = [(x[2 + 2 * k], x[3 + 2 * k]) for k in range(nr)]
    if kind == FOSTER:
        for r, l in cells:
            z = z + (jw * l * r) / (r + jw * l)
    else:
        ladder = np.zeros_like(jw)
        for r, l in reversed(cells):
            branch = r + ladder
            ladder = (jw * l * branch) / (jw * l + branch)
        z = z + ladder
    if not nc:
        return z
    rp, cp = x[2 + 2 * nr], x[3 + 2 * nr]
    return 1.0 / (1.0 / z + 1.0 / rp + jw * cp)


def _capacitor(w: np.ndarray, x, nr: int, nc: int) -> np.ndarray:
    jw = 1j * w
    y = jw * x[2]
    for k in range(nr):
        r, c = x[3 + 2 * k], x[4 + 2 * k]
        y = y + (jw * c) / (1.0 + jw * r * c)       # branche Rk en série avec Ck
    if nc:
        y = y + 1.0 / x[3 + 2 * nr]
    return x[0] + jw * x[1] + 1.0 / y


def impedance(kind: str, f, x, nr: int, nc: int) -> np.ndarray:
    """Impédance complexe du modèle aux fréquences f (Hz)."""
    check_kind(kind)
    w = 2.0 * np.pi * np.asarray(f, dtype=float)
    x = np.asarray(x, dtype=float)
    if kind == CAPACITOR:
        return _capacitor(w, x, nr, nc)
    return _inductor(kind, w, x, nr, nc)


# --------------------------------------------------------------------------- résonance
def _crossing(f: np.ndarray, x: np.ndarray, rising: bool) -> float | None:
    """Première fréquence où la réactance change de signe (interpolée en log f)."""
    if rising:
        hits = np.nonzero((x[:-1] < 0) & (x[1:] >= 0))[0]
    else:
        hits = np.nonzero((x[:-1] > 0) & (x[1:] <= 0))[0]
    if hits.size == 0:
        return None
    i = hits[0]
    t = x[i] / (x[i] - x[i + 1])
    return float(np.exp(np.log(f[i]) + t * (np.log(f[i + 1]) - np.log(f[i]))))


def estimate_srf(f: np.ndarray, z: np.ndarray) -> float:
    """
    Résonance propre d'une inductance : là où la phase passe d'inductive à capacitive.
    Sans passage dans la bande, elle est supposée au-delà (3 x f max).
    """
    return _crossing(f, z.imag, rising=False) or 3.0 * float(f[-1])


def capacitor_srf(f: np.ndarray, z: np.ndarray) -> float | None:
    """Résonance série d'un condensateur (capacitif -> inductif) ; None hors bande."""
    return _crossing(f, z.imag, rising=True)


# --------------------------------------------------------------------------- initialisation
def _inductor_guesses(f, z, kind, nr, nc) -> list[np.ndarray]:
    w = 2.0 * np.pi * f
    r0 = max(float(np.percentile(z.real, 5)), 1e-6)
    f_srf = estimate_srf(f, z)
    # inductance : médiane de X/w sur la partie inductive, sous la résonance
    inductive = (z.imag > 0) & (f < 0.5 * f_srf)
    if not inductive.any():
        inductive = z.imag > 0
    l0 = float(np.median(z.imag[inductive] / w[inductive])) if inductive.any() else 1e-9
    l0 = max(l0, 1e-12)

    # cellules R-L : fréquences de coupure réparties en log dans la bande
    w_lo, w_hi = w[0] * 5.0, max(w[-1] / 5.0, w[0] * 10.0)
    w0s = np.logspace(np.log10(w_lo), np.log10(w_hi), nr)
    rks = np.logspace(np.log10(max(r0 * 0.3, 1e-6)), np.log10(max(r0 * 5.0, 5e-6)), nr)
    x0 = [r0, l0]
    for rk, w0 in zip(rks, w0s):
        x0 += [rk, max(rk / w0, 1e-12)]
    if nc:
        cp = 1.0 / ((2.0 * np.pi * f_srf) ** 2 * l0)
        x0 += [1e6, float(np.clip(cp, 1e-13, 1e-7))]
    return [np.asarray(x0, dtype=float)]


def _capacitor_guesses(f, z, nr, nc) -> list[np.ndarray]:
    w = 2.0 * np.pi * f
    f_srf = capacitor_srf(f, z)
    f_res = f_srf or 3.0 * float(f[-1])
    # capacité : médiane de -1/(wX) sur la partie capacitive, loin sous la résonance
    capacitive = (z.imag < 0) & (f < 0.3 * f_res)
    if not capacitive.any():
        capacitive = z.imag < 0
    c0 = float(np.median(-1.0 / (w[capacitive] * z.imag[capacitive]))) \
        if capacitive.any() else 1e-9
    c0 = float(np.clip(c0, 1e-14, 1.0))
    # ESR : partie réelle à la résonance (là où elle domine), sinon son minimum
    positive = z.real[z.real > 0]
    esr = float(np.interp(np.log(f_res), np.log(f), z.real)) if f_srf else \
        (float(positive.min()) if positive.size else 1e-2)
    esr = float(np.clip(esr, 1e-5, 1e3))
    esl = float(np.clip(1.0 / ((2.0 * np.pi * f_res) ** 2 * c0), 1e-11, 1e-4))

    # branches R-C : relaxations réparties en log entre le bas de bande et la résonance,
    # plusieurs points de départ (part de la capacité portée par les branches)
    f_lo = float(f[0]) * 3.0
    f_hi = max(min(f_res, float(f[-1])) / 3.0, f_lo * 3.0)
    guesses = []
    for share in ((0.3, 0.1) if nr else (0.0,)):
        x0 = [esr, esl, c0 * (1.0 - share) if nr else c0]
        for fk in np.geomspace(f_lo, f_hi, nr):
            ck = max(c0 * share / max(nr, 1), 1e-14)
            x0 += [1.0 / (2.0 * np.pi * fk * ck), ck]
        if nc:
            x0.append(1e3 / (w[0] * c0))        # fuite : 1000 fois |X| en bas de bande
        guesses.append(np.asarray(x0, dtype=float))
    return guesses


def initial_guesses(f, z, kind: str, nr: int, nc: int) -> list[np.ndarray]:
    """Points de départ du fit (plusieurs pour un condensateur à branches R-C)."""
    if kind == CAPACITOR:
        return _capacitor_guesses(f, z, nr, nc)
    return _inductor_guesses(f, z, kind, nr, nc)


# --------------------------------------------------------------------------- fit
def _select_band(f, z, f_min, f_max):
    f = np.asarray(f, dtype=float)
    z = np.asarray(z, dtype=complex)
    keep = np.isfinite(f) & np.isfinite(z.real) & np.isfinite(z.imag) & (f > 0)
    if f_min:
        keep &= f >= f_min
    if f_max:
        keep &= f <= f_max
    f, z = f[keep], z[keep]
    if f.size < MIN_POINTS:
        raise FitError(f"Trop peu de points valides dans la bande ({f.size} < {MIN_POINTS}).")
    order = np.argsort(f)
    return f[order], z[order]


def _fit_band(f: np.ndarray, z: np.ndarray, kind: str, nr: int, nc: int) -> FitResult:
    scale = np.maximum(np.abs(z), 1e-6)
    bounds = _param_bounds(kind, nr, nc)
    lo, hi = np.log(bounds[:, 0]), np.log(bounds[:, 1])

    def residuals(p):
        dz = (impedance(kind, f, np.exp(p), nr, nc) - z) / scale
        return np.concatenate([dz.real, dz.imag])

    best = None
    for x0 in initial_guesses(f, z, kind, nr, nc):
        x0 = np.clip(x0, bounds[:, 0] * 1.001, bounds[:, 1] * 0.999)
        sol = least_squares(residuals, np.log(x0), bounds=(lo, hi), method="trf",
                            max_nfev=400 * x0.size)
        if best is None or sol.cost < best.cost:
            best = sol
    x = np.exp(best.x)
    res = residuals(best.x)
    ssr = float(np.sum(res ** 2))
    n_obs = res.size
    aic = n_obs * np.log(max(ssr, 1e-300) / n_obs) + 2.0 * x.size
    rel_err = float(np.mean(np.abs(impedance(kind, f, x, nr, nc) - z) / scale))
    return FitResult(kind, nr, nc, x, rel_err, float(aic))


def fit(f, z, kind: str = FOSTER, nr: int = 1, parallel_cap: bool = True,
        f_min: float = 0.0, f_max: float = 0.0) -> FitResult:
    """Fit d'ordre imposé (nr cellules ou branches, avec ou sans option parallèle)."""
    low, high = order_range(kind)
    if not low <= nr <= high:
        raise FitError(f"Ordre hors limites pour {kind} : {nr} (de {low} à {high}).")
    f, z = _select_band(f, z, f_min, f_max)
    return _fit_band(f, z, kind, nr, 1 if parallel_cap else 0)


def fit_auto(f, z, kind: str = FOSTER, parallel_cap: bool = True,
             f_min: float = 0.0, f_max: float = 0.0) -> FitResult:
    """
    Fit pour chaque ordre possible. L'ordre le plus simple dont le critère AIC est à
    moins de AIC_MARGIN du meilleur est retenu : un ordre supérieur doit apporter un
    gain net, pas seulement suivre le bruit de mesure.
    """
    low, high = order_range(kind)
    f, z = _select_band(f, z, f_min, f_max)
    nc = 1 if parallel_cap else 0
    results = [_fit_band(f, z, kind, nr, nc) for nr in range(low, high + 1)]
    best = min(r.aic for r in results)
    return next(r for r in results if r.aic <= best + AIC_MARGIN)


def run(model, f, z) -> FitResult:
    """Ajuste un ModelFit (model/capture.py) sur les données et y écrit le résultat."""
    low, high = order_range(model.kind)
    model.nr = int(min(max(model.nr, low), high))
    kwargs = dict(kind=model.kind, parallel_cap=model.parallel_cap,
                  f_min=model.f_min, f_max=model.f_max)
    result = fit_auto(f, z, **kwargs) if model.auto_order else fit(f, z, nr=model.nr, **kwargs)
    model.nr, model.nc = result.nr, result.nc
    model.params = [float(v) for v in result.params]
    model.rel_err, model.aic = result.rel_err, result.aic
    return result
