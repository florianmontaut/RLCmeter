# model/fit.py
"""
Ajustement d'un modèle d'inductance (Foster ou Cauer) sur une impédance mesurée.
Reprise de la macro VBA FitFosterRL (elle-même portée de MATLAB), avec scipy.

Vecteur de paramètres x = [R0, L0, R1, L1, ..., R_NR, L_NR, (Rp, Cp)]

    Foster : Zs = R0 + jwL0 + somme_k (Rk // jwLk)
    Cauer  : Zs = R0 + jwL0 + E1,  E_k = jwLk // (Rk + E_k+1),  E_NR+1 = 0
    Avec la branche parallèle (NC = 1) : Z = Zs // Rp // Cp

Les deux modèles sont identiques pour NR = 1.

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

KINDS = ("Foster", "Cauer")
NR_MIN, NR_MAX = 1, 3
MIN_POINTS = 8

# bornes des paramètres (min, max)
BOUNDS = {"R": (1e-9, 1e9), "L": (1e-15, 1e3), "Rp": (1e-3, 1e9), "Cp": (1e-16, 1e-6)}


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


# --------------------------------------------------------------------------- modèles
def param_names(nr: int, nc: int) -> list[tuple[str, str]]:
    """(nom, unité) de chaque paramètre du vecteur x."""
    names = [("R0", "Ω"), ("L0", "H")]
    for k in range(1, nr + 1):
        names += [(f"R{k}", "Ω"), (f"L{k}", "H")]
    if nc:
        names += [("Rp", "Ω"), ("Cp", "F")]
    return names


def _param_bounds(nr: int, nc: int) -> np.ndarray:
    kinds = ["R", "L"] * (1 + nr) + (["Rp", "Cp"] if nc else [])
    return np.array([BOUNDS[k] for k in kinds], dtype=float)


def _series(kind: str, w: np.ndarray, x, nr: int) -> np.ndarray:
    jw = 1j * w
    z = x[0] + jw * x[1]
    cells = [(x[2 + 2 * k], x[3 + 2 * k]) for k in range(nr)]
    if kind == "Foster":
        for r, l in cells:
            z = z + (jw * l * r) / (r + jw * l)
    elif kind == "Cauer":
        ladder = np.zeros_like(jw)
        for r, l in reversed(cells):
            branch = r + ladder
            ladder = (jw * l * branch) / (jw * l + branch)
        z = z + ladder
    else:
        raise FitError(f"Type de modèle inconnu : {kind}")
    return z


def impedance(kind: str, f, x, nr: int, nc: int) -> np.ndarray:
    """Impédance complexe du modèle aux fréquences f (Hz)."""
    w = 2.0 * np.pi * np.asarray(f, dtype=float)
    x = np.asarray(x, dtype=float)
    zs = _series(kind, w, x, nr)
    if not nc:
        return zs
    rp, cp = x[2 + 2 * nr], x[3 + 2 * nr]
    return 1.0 / (1.0 / zs + 1.0 / rp + 1j * w * cp)


# --------------------------------------------------------------------------- initialisation
def estimate_srf(f: np.ndarray, z: np.ndarray) -> float:
    """
    Fréquence de résonance propre : là où la phase passe d'inductive à capacitive.
    Sans passage dans la bande, elle est supposée au-delà (3 x f max).
    """
    x = z.imag
    crossings = np.nonzero((x[:-1] > 0) & (x[1:] <= 0))[0]
    if crossings.size == 0:
        return 3.0 * float(f[-1])
    i = crossings[0]
    # interpolation en log(f) entre les deux points encadrant X = 0
    t = x[i] / (x[i] - x[i + 1])
    return float(np.exp(np.log(f[i]) + t * (np.log(f[i + 1]) - np.log(f[i]))))


def initial_guess(f: np.ndarray, z: np.ndarray, nr: int, nc: int) -> np.ndarray:
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
    return np.asarray(x0, dtype=float)


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
    bounds = _param_bounds(nr, nc)
    lo, hi = np.log(bounds[:, 0]), np.log(bounds[:, 1])

    def residuals(p):
        dz = (impedance(kind, f, np.exp(p), nr, nc) - z) / scale
        return np.concatenate([dz.real, dz.imag])

    x0 = np.clip(initial_guess(f, z, nr, nc), bounds[:, 0] * 1.001, bounds[:, 1] * 0.999)
    sol = least_squares(residuals, np.log(x0), bounds=(lo, hi), method="trf",
                        max_nfev=400 * x0.size)
    x = np.exp(sol.x)
    res = residuals(sol.x)
    ssr = float(np.sum(res ** 2))
    n_obs = res.size
    aic = n_obs * np.log(max(ssr, 1e-300) / n_obs) + 2.0 * x.size
    rel_err = float(np.mean(np.abs(impedance(kind, f, x, nr, nc) - z) / scale))
    return FitResult(kind, nr, nc, x, rel_err, float(aic))


def fit(f, z, kind: str = "Foster", nr: int = 1, parallel_cap: bool = True,
        f_min: float = 0.0, f_max: float = 0.0) -> FitResult:
    """Fit d'ordre imposé (nr cellules R-L, avec ou sans branche Rp // Cp)."""
    if not NR_MIN <= nr <= NR_MAX:
        raise FitError(f"Ordre hors limites : NR = {nr} (de {NR_MIN} à {NR_MAX}).")
    f, z = _select_band(f, z, f_min, f_max)
    return _fit_band(f, z, kind, nr, 1 if parallel_cap else 0)


def fit_auto(f, z, kind: str = "Foster", parallel_cap: bool = True,
             f_min: float = 0.0, f_max: float = 0.0) -> FitResult:
    """Fit pour NR = 1 à 3 ; le meilleur critère AIC est retenu."""
    f, z = _select_band(f, z, f_min, f_max)
    nc = 1 if parallel_cap else 0
    results = [_fit_band(f, z, kind, nr, nc) for nr in range(NR_MIN, NR_MAX + 1)]
    return min(results, key=lambda r: r.aic)


def run(model, f, z) -> FitResult:
    """Ajuste un ModelFit (model/capture.py) sur les données et y écrit le résultat."""
    kwargs = dict(kind=model.kind, parallel_cap=model.parallel_cap,
                  f_min=model.f_min, f_max=model.f_max)
    result = fit_auto(f, z, **kwargs) if model.auto_order else fit(f, z, nr=model.nr, **kwargs)
    model.nr, model.nc = result.nr, result.nc
    model.params = [float(v) for v in result.params]
    model.rel_err, model.aic = result.rel_err, result.aic
    return result
