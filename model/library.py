# model/library.py
"""
Librairie des captures : un répertoire et ses sous-répertoires, un fichier .json par
capture (avec ses modèles). Des captures situées ailleurs peuvent aussi être ouvertes
(Fichier > Ouvrir) : elles restent enregistrées dans leur propre fichier.
"""
from __future__ import annotations

import json
import pathlib
import re

from model.capture import Capture

FORMAT_PREFIX = "RLCmeter capture"
IGNORED_FOLDERS = {"__pycache__"}


class LibraryError(Exception):
    pass


def read_capture(path) -> Capture:
    """Capture d'un fichier .json ; LibraryError si ce n'en est pas une."""
    path = pathlib.Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LibraryError(f"{path.name} : fichier illisible ({error})") from error
    if not isinstance(data, dict) or not str(data.get("format", "")).startswith(FORMAT_PREFIX):
        raise LibraryError(f"{path.name} : ce n'est pas une capture RLCmeter")
    try:
        capture = Capture.from_dict(data)
    except (ValueError, KeyError, TypeError) as error:
        raise LibraryError(f"{path.name} : capture invalide ({error})") from error
    capture.path = str(path)
    return capture


def file_name(capture: Capture) -> str:
    slug = re.sub(r"[^A-Za-z0-9_\-]+", "_", capture.name).strip("_") or "capture"
    return f"{slug}_{capture.id[:8]}.json"


class Library:

    def __init__(self, folder):
        self.folder = pathlib.Path(folder)
        self.captures: list[Capture] = []
        # fichiers illisibles au chargement : (nom du fichier, erreur)
        self.errors: list[tuple[str, str]] = []

    # ------------------------------------------------------------------ lecture
    def load(self) -> None:
        """Lit toutes les captures du répertoire et de ses sous-répertoires."""
        self.folder.mkdir(parents=True, exist_ok=True)
        self.captures, self.errors = [], []
        for path in sorted(self.folder.rglob("*.json")):
            if self._ignored(path.parent):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                self.errors.append((path.name, str(error)))
                continue
            if not isinstance(data, dict) or not str(data.get("format", "")).startswith(
                    FORMAT_PREFIX):
                continue                    # autre fichier .json : pas une capture
            try:
                capture = Capture.from_dict(data)
            except (ValueError, KeyError, TypeError) as error:
                self.errors.append((path.name, str(error)))
                continue
            capture.path = str(path)
            self.captures.append(capture)
        self.captures.sort(key=lambda c: c.date)

    def _ignored(self, folder: pathlib.Path) -> bool:
        parts = folder.relative_to(self.folder).parts
        return any(p.startswith(".") or p in IGNORED_FOLDERS for p in parts)

    def subfolders(self) -> list[str]:
        """Sous-répertoires de la librairie (chemins relatifs « a/b »), vides compris."""
        if not self.folder.is_dir():
            return []
        return sorted(p.relative_to(self.folder).as_posix()
                      for p in self.folder.rglob("*") if p.is_dir() and not self._ignored(p))

    def relative_folder(self, capture: Capture) -> str | None:
        """
        Sous-répertoire de la capture dans la librairie (« » à la racine) ; None pour une
        capture ouverte en dehors de la librairie.
        """
        if not capture.path:
            return ""
        try:
            relative = pathlib.Path(capture.path).resolve().parent.relative_to(
                                                                    self.folder.resolve())
        except ValueError:
            return None
        return "" if relative.as_posix() == "." else relative.as_posix()

    def open_file(self, path) -> Capture:
        """
        Ouvre un fichier de capture. S'il est déjà chargé (même fichier ou même capture),
        la capture existante est renvoyée.
        """
        target = pathlib.Path(path).resolve()
        for capture in self.captures:
            if capture.path and pathlib.Path(capture.path).resolve() == target:
                return capture
        capture = read_capture(target)
        existing = self.capture(capture.id)
        if existing is not None:
            return existing
        self.captures.append(capture)
        return capture

    # ------------------------------------------------------------------ accès
    def capture(self, capture_id: str) -> Capture | None:
        return next((c for c in self.captures if c.id == capture_id), None)

    def names(self) -> set[str]:
        return {c.name for c in self.captures}

    def unique_name(self, name: str) -> str:
        """Nom libre dans la librairie : « nom », « nom (2) », « nom (3) »..."""
        name = name.strip() or "capture"
        used = self.names()
        if name not in used:
            return name
        n = 2
        while f"{name} ({n})" in used:
            n += 1
        return f"{name} ({n})"

    # ------------------------------------------------------------------ écriture
    def add(self, capture: Capture, subfolder: str = "") -> None:
        """Nouvelle capture, enregistrée dans un sous-répertoire de la librairie."""
        capture.path = str(self.folder / subfolder / file_name(capture))
        self.captures.append(capture)
        self.save(capture)

    def save(self, capture: Capture) -> None:
        """Enregistre la capture dans son répertoire ; son fichier suit son nom."""
        folder = pathlib.Path(capture.path).parent if capture.path else self.folder
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / file_name(capture)
        path.write_text(json.dumps(capture.to_dict(), indent=1), encoding="utf-8")
        if capture.path and pathlib.Path(capture.path) != path:
            pathlib.Path(capture.path).unlink(missing_ok=True)
        capture.path = str(path)

    @staticmethod
    def save_copy(capture: Capture, path) -> None:
        """Copie de la capture (et de ses modèles) dans un autre fichier."""
        pathlib.Path(path).write_text(json.dumps(capture.to_dict(), indent=1),
                                      encoding="utf-8")

    def remove(self, capture: Capture) -> None:
        if capture.path:
            pathlib.Path(capture.path).unlink(missing_ok=True)
        self.captures = [c for c in self.captures if c is not capture]
