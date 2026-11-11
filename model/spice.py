# model/spice.py
"""Export d'un modèle ajusté en sous-circuit SPICE (.subckt, syntaxe LTspice)."""
import re


def subckt_name(text: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")
    return name or "RLC_model"


def subckt(name: str, kind: str, params, nr: int, nc: int, comment: str = "") -> str:
    """
    Sous-circuit à deux bornes (1, 2) du modèle de model/fit.py.
    Rser=0 : LTspice ajoute sinon 1 mOhm en série à chaque inductance.
    """
    x = list(params)
    lines = [f"* {comment}"] if comment else []
    lines.append(f".subckt {subckt_name(name)} 1 2")
    if kind == "Condensateur":
        # ESR et ESL en série, puis C0 avec ses branches Rk-Ck (et la fuite) en parallèle
        lines.append(f"Resr 1 a {x[0]:.6g}")
        lines.append(f"Lesl a b {x[1]:.6g} Rser=0")
        lines.append(f"C0 b 2 {x[2]:.6g}")
        for k in range(1, nr + 1):
            lines.append(f"R{k} b c{k} {x[1 + 2 * k]:.6g}")
            lines.append(f"C{k} c{k} 2 {x[2 + 2 * k]:.6g}")
        if nc:
            lines.append(f"Rf b 2 {x[3 + 2 * nr]:.6g}")
        lines.append(f".ends {subckt_name(name)}")
        return "\n".join(lines) + "\n"
    lines.append(f"R0 1 a {x[0]:.6g}")
    cells = [(x[2 + 2 * k], x[3 + 2 * k]) for k in range(nr)]

    if kind == "Foster":
        # L0 puis les cellules Rk // Lk en série jusqu'à la borne 2
        nodes = ["a"] + [f"n{k}" for k in range(1, nr + 1)] + ["2"]
        lines.append(f"L0 {nodes[0]} {nodes[1] if nr else '2'} {x[1]:.6g} Rser=0")
        for k, (r, l) in enumerate(cells, start=1):
            n_in, n_out = nodes[k], nodes[k + 1]
            lines.append(f"R{k} {n_in} {n_out} {r:.6g}")
            lines.append(f"L{k} {n_in} {n_out} {l:.6g} Rser=0")
    elif kind == "Cauer":
        # L0 puis l'échelle : Lk vers la borne 2, Rk vers l'étage suivant
        lines.append(f"L0 a n1 {x[1]:.6g} Rser=0")
        for k, (r, l) in enumerate(cells, start=1):
            n_in = f"n{k}"
            n_out = f"n{k + 1}" if k < nr else "2"
            lines.append(f"L{k} {n_in} 2 {l:.6g} Rser=0")
            lines.append(f"R{k} {n_in} {n_out} {r:.6g}")
    else:
        raise ValueError(f"Type de modèle inconnu : {kind}")

    if nc:
        lines.append(f"Rp 1 2 {x[2 + 2 * nr]:.6g}")
        lines.append(f"Cp 1 2 {x[3 + 2 * nr]:.6g}")
    lines.append(f".ends {subckt_name(name)}")
    return "\n".join(lines) + "\n"
