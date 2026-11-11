# controller/filter_controller.py
"""
Création de filtre : choix d'une topologie et d'un composant par branche, calcul de la
réponse (model/filter.py) et affichage.

Composants proposés, pour chaque composant de la librairie et de la session :
    - « ★ nom » : son modèle de référence (le choix par défaut) ;
    - « Mesure : ... » : une de ses mesures, interpolée ;
    - « Modèle : ... » : un de ses autres modèles ajustés ;
puis les composants idéaux R, L et C.
"""
from __future__ import annotations

import pyqtgraph as pg
from pyqtgraph.parametertree import Parameter
from PyQt6 import QtCore

from model import component as cmp
from model import filter as flt
from ressources import theme
from view.filter_window import FilterWindow

IDEAL_LABELS = {"R idéale": "R", "L idéale": "L", "C idéale": "C"}
IDEAL_DEFAULTS = {"R": 50.0, "L": 10e-6, "C": 100e-9}
FREQ = dict(type="float", siPrefix=True, suffix="Hz", dec=True, step=0.5, decimals=6)
OHM = dict(type="float", siPrefix=True, suffix="Ω", dec=True, step=0.5, decimals=6)


class FilterController(QtCore.QObject):

    def __init__(self, get_components, parent_view=None):
        """get_components : callable() -> composants disponibles (librairie et session)."""
        super().__init__()
        self.get_components = get_components
        self.view = FilterWindow(parent_view)
        self.response = None                # dernière réponse calculée (FilterResponse)
        self._sources = {}                  # libellé -> fabrique de Component
        self._kinds = {}
        self._building = False
        self.params = None
        self._build_params()

    def show(self):
        self.refresh_sources()
        self.view.apply_graph_theme()
        self.view.show()
        self.view.raise_()
        self.view.activateWindow()

    # ------------------------------------------------------------------ composants
    def _collect_sources(self) -> dict:
        """Libellé -> fabrique de Component ; None pour un composant idéal."""
        sources = {}
        self._kinds = {}                    # libellé -> type du composant (choix par défaut)

        def add(label, component, factory):
            if label in sources:            # deux composants de même nom
                label = f"{label} [{component.id[:4]}]"
            sources[label] = factory
            self._kinds[label] = component.kind or component.detect_kind()

        def modelled(name, m):
            return lambda: flt.Modelled(name, m.kind, tuple(m.params), m.nr, m.nc,
                                        m.f_min, m.f_max)

        components = sorted(self.get_components(), key=lambda c: c.name.casefold())
        for component in components:
            found = component.reference_model()
            if found is not None:
                add(f"★ {component.name}", component, modelled(component.name, found[1]))
        for component in components:
            single = len(component.captures) == 1
            reference = component.reference_model()
            for capture in component.captures:
                name = component.name if single and component.name == capture.name                     else f"{component.name} / {capture.name}"
                add(f"Mesure : {name}", component,
                    lambda c=capture, n=name: flt.Measured(n, c.f, c.z))
                for model in capture.models:
                    if model.fitted and not (reference and reference[1] is model):
                        add(f"Modèle : {name} / {model.name}", component,
                            modelled(f"{name} / {model.name}", model))
        for label in IDEAL_LABELS:
            sources[label] = None           # construit avec la valeur saisie
        return sources

    def refresh_sources(self):
        """Librairie modifiée : met à jour la liste des composants, garde les choix."""
        self._sources = self._collect_sources()
        if self.params is None:
            return
        self._building = True
        try:
            for branch in self.params.child("Composants").children():
                chooser = branch.child("Composant")
                current = chooser.value()
                chooser.setLimits(list(self._sources))
                if current not in self._sources:
                    chooser.setValue(self._default_source(branch.opts["position"]))
        finally:
            self._building = False
        self._sync_ideal_rows()
        self.compute()

    def _default_source(self, position: str) -> str:
        """
        Par défaut : une inductance en série, un condensateur en parallèle, pris parmi
        les composants disponibles (modèle de référence d'abord), sinon idéaux.
        """
        wanted = cmp.CAPACITOR if position == flt.SHUNT else cmp.INDUCTOR
        fallback = "C idéale" if position == flt.SHUNT else "L idéale"
        return next((label for label in self._sources
                     if self._kinds.get(label) == wanted), fallback)

    # ------------------------------------------------------------------ paramètres
    def _build_params(self):
        self._sources = self._collect_sources()
        self.params = Parameter.create(name="Filtre", type="group", children=[
            dict(name="Topologie", type="list", limits=list(flt.TOPOLOGIES),
                 value="T (série, parallèle, série)"),
            dict(name="Résistance de source", value=50.0, limits=(0.0, 1e9), **OHM),
            dict(name="Résistance de charge", value=50.0, limits=(1e-6, 1e12), **OHM),
            dict(name="Fréquence d'évaluation", value=1e6, limits=(1e-3, 1e12), **FREQ),
            dict(name="Composants", type="group", children=[]),
            dict(name="Résultats", type="group", children=[]),
        ])
        self._build_branches()
        self.view.paramTree.setParameters(self.params, showTop=False)
        self.params.sigTreeStateChanged.connect(self._on_changed)
        self.compute()

    def _build_branches(self):
        group = self.params.child("Composants")
        self._building = True
        try:
            group.clearChildren()
            for n, position in enumerate(flt.TOPOLOGIES[self.params["Topologie"]], start=1):
                group.addChild(dict(
                    name=f"Z{n} ({position})", type="group", position=position, children=[
                        dict(name="Composant", type="list", limits=list(self._sources),
                             value=self._default_source(position)),
                        dict(name="Valeur", type="float", value=1.0, siPrefix=True,
                             dec=True, step=0.5, decimals=6, limits=(1e-15, 1e12)),
                    ]))
        finally:
            self._building = False
        self._sync_ideal_rows(reset=True)

    def _sync_ideal_rows(self, reset: bool = False):
        """Ligne « Valeur » : visible pour un composant idéal, avec la bonne unité."""
        self._building = True
        try:
            for branch in self.params.child("Composants").children():
                kind = IDEAL_LABELS.get(branch["Composant"])
                value = branch.child("Valeur")
                unit = flt.IDEAL_UNITS.get(kind, "")
                if kind and (reset or value.opts.get("suffix") != unit):
                    value.setValue(IDEAL_DEFAULTS[kind])
                value.setOpts(visible=kind is not None, suffix=unit)
        finally:
            self._building = False

    def _on_changed(self, _param, changes):
        if self._building:
            return
        names = {change[0].name() for change in changes if change[1] == "value"}
        if not names:
            return
        if "Topologie" in names:
            self._build_branches()
        elif "Composant" in names:
            self._sync_ideal_rows()
        self.compute()

    # ------------------------------------------------------------------ calcul
    def components(self) -> list:
        result = []
        for branch in self.params.child("Composants").children():
            label = branch["Composant"]
            if label in IDEAL_LABELS:
                kind = IDEAL_LABELS[label]
                result.append(flt.Ideal(f"{kind} = {branch['Valeur']:g}", kind,
                                        float(branch["Valeur"])))
            elif self._sources.get(label) is not None:
                result.append(self._sources[label]())
            else:
                raise flt.FilterError(f"Composant introuvable : {label}")
        return result

    def compute(self):
        if self._building or self.params is None:
            return
        try:
            self.response = flt.response(self.params["Topologie"], self.components(),
                                         rs=float(self.params["Résistance de source"]),
                                         rl=float(self.params["Résistance de charge"]))
        except flt.FilterError as error:
            self.response = None
            self._show_results([("État", str(error))])
            self._plot()
            self.view.message.setText(str(error))
            return
        self.view.message.setText("")
        self._show_results(self._result_rows())
        self._plot()

    def _result_rows(self) -> list[tuple[str, str]]:
        r = self.response
        hz = lambda v: pg.siFormat(v, precision=4, suffix="Hz")
        rows = [("Bande calculée", f"{hz(r.f[0])} à {hz(r.f[-1])}")]
        cutoff = r.cutoff()
        rows.append(("Coupure à −3 dB", hz(cutoff) if cutoff else "non atteinte"))
        f_eval = float(self.params["Fréquence d'évaluation"])
        gain = r.gain_db_at(f_eval)
        rows.append((f"Gain à {hz(f_eval)}",
                     f"{gain:.2f} dB" if gain is not None else "hors bande"))
        f_min, g_min = r.minimum()
        rows.append(("Atténuation maximale", f"{-g_min:.2f} dB à {hz(f_min)}"))
        f_peak, g_peak = r.peak()
        rows.append(("Pic de résonance", f"+{g_peak:.2f} dB à {hz(f_peak)}"
                     if g_peak > 0.1 else "aucun"))
        return rows

    def _show_results(self, rows):
        group = self.params.child("Résultats")
        self._building = True
        try:
            group.clearChildren()
            group.addChildren([dict(name=name, type="str", value=value, readonly=True)
                               for name, value in rows])
        finally:
            self._building = False

    def _plot(self):
        v = self.view
        v.plot_gain.clear()
        v.plot_phase.clear()
        if self.response is None:
            return
        pen = pg.mkPen(theme.colors()["accent"], width=2)
        v.plot_gain.plot(self.response.f, self.response.gain_db, pen=pen)
        v.plot_phase.plot(self.response.f, self.response.phase_deg, pen=pen)
