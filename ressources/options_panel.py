# ressources/options_panel.py
"""
Fenêtre d'options générée à partir d'un schéma (un onglet par groupe de premier niveau).
Reprise de GLviewer : OptionsPannel (ressources/custom_dialogs.py) et ses trois fonctions
utilitaires (ressources/custom_struct_functions.py), sans autre dépendance.

Schéma :
    {"Nom de l'onglet": {"type": "group", "children": {
        "Nom affiché": {"type": "bool", "default": True, "key": "cle_logique"}, ...}}}
getOptions() renvoie un dictionnaire plat {cle_logique: valeur}.
"""
import pathlib

import pyqtgraph.parametertree as ptree
from PyQt6 import QtGui
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QGridLayout, QTabWidget, QWidget
from PyQt6.uic import loadUi

PATH = pathlib.Path(__file__).parent


def schema_defaults(schema: dict) -> dict:
    """{key: default} de toutes les options d'un schéma (groupes imbriqués compris)."""
    defaults = {}
    for spec in schema.values():
        if spec.get("type") == "group":
            defaults.update(schema_defaults(spec.get("children", {})))
        elif "key" in spec and "default" in spec:
            defaults[spec["key"]] = spec["default"]
    return defaults


def generate_opts_dict(schema: dict) -> dict:
    """(chemin : tuple ou str) -> clé logique."""
    opts_dict = {}

    def recurse(node, path=()):
        for name, spec in node.items():
            current = path + (name,)
            if "key" in spec:
                opts_dict[current[0] if len(current) == 1 else current] = spec["key"]
            if spec.get("type") == "group":
                recurse(spec.get("children", {}), current)

    recurse(schema)
    return opts_dict


def extract_parameter_values(param_root, opts_dict) -> dict:
    extracted = {}

    def recurse(param, path=()):
        for child in param.children():
            new_path = path + (child.name(),)
            if child.hasChildren():
                recurse(child, new_path)
            else:
                key = new_path if len(new_path) > 1 else new_path[0]
                if key in opts_dict:
                    extracted[opts_dict[key]] = child.value()

    recurse(param_root)
    return extracted


def apply_options_to_parameters(param_root, opts_dict, saved_options) -> None:
    """Injecte saved_options dans le ParameterTree en utilisant opts_dict."""

    def recurse(param, path=()):
        for child in param.children():
            new_path = path + (child.name(),)
            if child.hasChildren():
                recurse(child, new_path)
            else:
                key = new_path if len(new_path) > 1 else new_path[0]
                if key in opts_dict and opts_dict[key] in saved_options:
                    child.setValue(saved_options[opts_dict[key]])

    recurse(param_root)


class OptionsPannel(QDialog):
    """Fenêtre d'options générée automatiquement à partir du schéma (un onglet par groupe)."""

    def __init__(self, schema, saved_options=None, parent=None):
        super().__init__(parent)
        self.setWindowIcon(QtGui.QIcon(str(PATH / "icons" / "icon.ico")))
        loadUi(PATH / "custom_options.ui", self)
        self.setWindowTitle("Options")
        self.saved_options = saved_options or {}
        self.schema = schema
        self.tabWidget: QTabWidget

        self.parameter_roots = {}     # onglet -> Parameter
        self.opts_dicts = {}          # onglet -> opts_dict
        self._build_tabs()
        self._restore_saved_options()
        self.buttonBox: QDialogButtonBox
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

    def _restore_saved_options(self):
        for setting, param_root in self.parameter_roots.items():
            apply_options_to_parameters(param_root, self.opts_dicts[setting],
                                        self.saved_options)

    def _build_tabs(self):
        for setting_name, setting_schema in self.schema.items():
            tab = QWidget()
            layout = QGridLayout(tab)
            layout.setContentsMargins(5, 5, 5, 5)
            tree_widget = ptree.ParameterTree(parent=tab)
            tree_widget.setHeaderHidden(True)
            tree_widget.setIndentation(20)
            layout.addWidget(tree_widget, 0, 0, 1, 1)
            children = setting_schema.get("children", {})
            param_root = self.build_parameter_group(setting_name, children)
            tree_widget.setParameters(param_root, showTop=False)
            self.parameter_roots[setting_name] = param_root
            self.opts_dicts[setting_name] = generate_opts_dict(children)
            self.tabWidget.addTab(tab, setting_name)

    def getOptions(self) -> dict:
        """Dictionnaire plat {clé logique: valeur}."""
        result = {}
        for setting, param_root in self.parameter_roots.items():
            result.update(extract_parameter_values(param_root, self.opts_dicts[setting]))
        return result

    def build_parameter_group(self, name, schema):
        children = []
        for pname, spec in schema.items():
            if spec["type"] == "group":
                group = self.build_parameter_group(pname, spec.get("children", {}))
                group.setOpts(expanded=spec.get("expanded", True))
                children.append(group)
                continue
            param = {"name": pname}
            if spec.get("default") is not None:
                param["value"] = spec["default"]
            param.update({k: v for k, v in spec.items() if k != "key"})
            children.append(ptree.Parameter.create(**param))
        return ptree.Parameter.create(name=name, type="group", children=children)
