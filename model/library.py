# model/library.py
"""Librairie des captures : un dossier, un fichier .json par capture (avec ses modèles)."""
from __future__ import annotations

import json
import pathlib
import re

from model.capture import Capture


class Library:

    def __init__(self, folder):
        self.folder = pathlib.Path(folder)
        self.captures: list[Capture] = []
        # fichiers illisibles au chargement : (nom du fichier, erreur)
        self.errors: list[tuple[str, str]] = []

    def load(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.captures, self.errors = [], []
        for path in sorted(self.folder.glob("*.json")):
            try:
                capture = Capture.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, KeyError, TypeError) as error:
                self.errors.append((path.name, str(error)))
                continue
            capture.path = str(path)
            self.captures.append(capture)
        self.captures.sort(key=lambda c: c.date)

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

    def add(self, capture: Capture) -> None:
        self.captures.append(capture)
        self.save(capture)

    def save(self, capture: Capture) -> None:
        """Enregistre la capture ; son fichier suit son nom (renommage)."""
        self.folder.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^A-Za-z0-9_\-]+", "_", capture.name).strip("_") or "capture"
        path = self.folder / f"{slug}_{capture.id[:8]}.json"
        path.write_text(json.dumps(capture.to_dict(), indent=1), encoding="utf-8")
        if capture.path and pathlib.Path(capture.path) != path:
            pathlib.Path(capture.path).unlink(missing_ok=True)
        capture.path = str(path)

    def remove(self, capture: Capture) -> None:
        if capture.path:
            pathlib.Path(capture.path).unlink(missing_ok=True)
        self.captures = [c for c in self.captures if c is not capture]
