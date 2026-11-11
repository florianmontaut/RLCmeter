# ressources/app_settings.py
"""Schéma des options de RLCmeter (Utilitaires > Options), voir options_panel.py."""
from model import fit


def schema(default_library: str) -> dict:
    return {
        "Modèles": {
            "type": "group",
            "children": {
                "Répertoire des mesures et modèles": {
                    "type": "file",
                    "fileMode": "Directory",
                    "default": default_library,
                    "key": "library_dir",
                },
                "Nouveau modèle": {
                    "type": "group",
                    "children": {
                        # un condensateur mesuré reçoit toujours le modèle « Condensateur »
                        "Type pour une inductance": {
                            "type": "list",
                            "limits": list(fit.INDUCTOR_KINDS),
                            "default": "Foster",
                            "key": "default_kind",
                        },
                        "Ordre automatique": {
                            "type": "bool",
                            "default": True,
                            "key": "default_auto_order",
                        },
                        "Capacité parallèle (inductance)": {
                            "type": "bool",
                            "default": True,
                            "key": "default_parallel_cap",
                        },
                    },
                },
            },
        },
    }
