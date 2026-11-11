# model/library.py
"""
Répertoire de composants : un fichier .json par composant (model/component.py), lus dans
le répertoire et ses sous-répertoires. Deux répertoires sont utilisés :

    - la librairie : les composants caractérisés, avec leur fiche ;
    - les brouillons : chaque nouvelle mesure y est enregistrée aussitôt, pour ne jamais
      la perdre, en attendant d'être ajoutée à la librairie.
"""
from __future__ import annotations

import json
import pathlib
import re

from model.component import Component

IGNORED_FOLDERS = {"__pycache__"}


class LibraryError(Exception):
    pass


def read_component(path) -> Component:
    """Composant d'un fichier .json ; LibraryError si ce n'en est pas un."""
    path = pathlib.Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LibraryError(f"{path.name} : fichier illisible ({error})") from error
    try:
        component = Component.from_dict(data)
    except (ValueError, KeyError, TypeError) as error:
        raise LibraryError(f"{path.name} : {error}") from error
    component.path = str(path)
    return component


def file_name(component: Component) -> str:
    slug = re.sub(r"[^A-Za-z0-9_\-]+", "_", component.name).strip("_") or "composant"
    return f"{slug}_{component.id[:8]}.json"


def save_component(component: Component, folder=None) -> None:
    """
    Enregistre le composant dans son répertoire (ou folder s'il n'a pas encore de
    fichier) ; son fichier suit son nom. LibraryError si l'écriture est impossible
    (répertoire en lecture seule...).
    """
    target = pathlib.Path(component.path).parent if component.path else pathlib.Path(folder)
    path = target / file_name(component)
    try:
        target.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(component.to_dict(), indent=1), encoding="utf-8")
        if component.path and pathlib.Path(component.path) != path:
            pathlib.Path(component.path).unlink(missing_ok=True)
    except OSError as error:
        raise LibraryError(f"Enregistrement impossible dans {target} : {error}") from error
    component.path = str(path)


def save_copy(component: Component, path) -> None:
    """Copie du composant (mesures et modèles compris) dans un autre fichier."""
    try:
        pathlib.Path(path).write_text(json.dumps(component.to_dict(), indent=1),
                                      encoding="utf-8")
    except OSError as error:
        raise LibraryError(f"Enregistrement impossible : {error}") from error


class Library:

    def __init__(self, folder):
        self.folder = pathlib.Path(folder)
        self.components: list[Component] = []
        # fichiers illisibles au chargement : (nom du fichier, erreur)
        self.errors: list[tuple[str, str]] = []

    # ------------------------------------------------------------------ lecture
    def load(self) -> None:
        """Lit tous les composants du répertoire et de ses sous-répertoires."""
        self.components, self.errors = [], []
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass                            # répertoire en lecture seule ou absent
        if not self.folder.is_dir():
            return
        for path in sorted(self.folder.rglob("*.json")):
            if self._ignored(path.parent):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                self.errors.append((path.name, str(error)))
                continue
            if not isinstance(data, dict) or "RLCmeter" not in str(data.get("format", "")):
                continue                    # autre fichier .json : pas un composant
            try:
                component = Component.from_dict(data)
            except (ValueError, KeyError, TypeError) as error:
                self.errors.append((path.name, str(error)))
                continue
            component.path = str(path)
            self.components.append(component)
        self.components.sort(key=lambda c: c.created)

    def _ignored(self, folder: pathlib.Path) -> bool:
        parts = folder.relative_to(self.folder).parts
        return any(p.startswith(".") or p in IGNORED_FOLDERS for p in parts)

    # ------------------------------------------------------------------ accès
    def component(self, component_id: str) -> Component | None:
        return next((c for c in self.components if c.id == component_id), None)

    def contains(self, component: Component) -> bool:
        return any(c is component for c in self.components)

    def values(self, attribute: str) -> list[str]:
        """Valeurs distinctes d'un champ de la fiche (propositions de saisie, filtres)."""
        found = {str(getattr(c, attribute) or "").strip() for c in self.components}
        return sorted(found - {""}, key=str.casefold)

    def unique_name(self, name: str) -> str:
        """Nom libre dans le répertoire : « nom », « nom (2) », « nom (3) »..."""
        name = name.strip() or "mesure"
        used = {c.name for c in self.components}
        if name not in used:
            return name
        n = 2
        while f"{name} ({n})" in used:
            n += 1
        return f"{name} ({n})"

    # ------------------------------------------------------------------ écriture
    def add(self, component: Component, subfolder: str = "") -> None:
        """Ajoute un composant et l'enregistre (dans un sous-répertoire au besoin)."""
        component.path = None
        save_component(component, self.folder / subfolder)
        self.components.append(component)

    def discard(self, component: Component, path=None) -> None:
        """
        Oublie un composant parti dans un autre répertoire et supprime son ancien fichier
        (path) ; un fichier impossible à supprimer est simplement laissé en place.
        """
        self.components = [c for c in self.components if c is not component]
        if path:
            try:
                pathlib.Path(path).unlink(missing_ok=True)
            except OSError:
                pass

    def remove(self, component: Component) -> None:
        """Retire le composant et supprime son fichier."""
        if component.path:
            try:
                pathlib.Path(component.path).unlink(missing_ok=True)
            except OSError as error:
                raise LibraryError(f"Suppression impossible : {error}") from error
        self.components = [c for c in self.components if c is not component]
