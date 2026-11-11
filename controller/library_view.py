# controller/library_view.py
"""
Tableau de la librairie : colonnes, tri et filtrage multicritère.

Le modèle Qt contient une ligne par composant, avec ses mesures et leurs modèles en
lignes enfants. Le filtre ne porte que sur les composants : une ligne enfant suit
toujours son composant.
"""
from PyQt6 import QtCore

# rôle : ("component", id composant, None, None), ("capture", id composant, id capture,
# None) ou ("model", id composant, id capture, id modèle), sur la colonne 0
REF_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1
SORT_ROLE = QtCore.Qt.ItemDataRole.UserRole + 2     # clé de tri (nombre ou texte)
SEARCH_ROLE = QtCore.Qt.ItemDataRole.UserRole + 3   # texte cherché hors colonnes

COLUMNS = ("Nom", "Type", "Technologie", "Fabricant", "Code Fay", "Valeur", "Mesures", "Date")
COL_NAME, COL_KIND, COL_TECHNOLOGY, COL_MANUFACTURER, COL_FAY, COL_VALUE, COL_COUNT, \
    COL_DATE = range(len(COLUMNS))

UNSET = "(non renseigné)"


class LibraryFilterProxy(QtCore.QSortFilterProxyModel):
    """Recherche plein texte (tous les mots doivent être trouvés) et filtres par colonne."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._words = []
        self._filters = {}              # colonne -> valeur exigée (UNSET : champ vide)
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)

    def set_search(self, text: str) -> None:
        self._words = text.casefold().split()
        self.invalidateFilter()

    def set_column_filter(self, column: int, value: str | None) -> None:
        if value is None:
            self._filters.pop(column, None)
        else:
            self._filters[column] = value
        self.invalidateFilter()

    def clear_filters(self) -> None:
        self._words, self._filters = [], {}
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        while parent.isValid():         # ligne enfant : décision de son composant
            row, parent = parent.row(), parent.parent()
        model = self.sourceModel()
        texts = [str(model.index(row, c).data() or "") for c in range(model.columnCount())]
        for column, wanted in self._filters.items():
            if wanted == UNSET:
                if texts[column]:
                    return False
            elif texts[column] != wanted:
                return False
        if not self._words:
            return True
        extra = str(model.index(row, 0).data(SEARCH_ROLE) or "")
        haystack = " ".join(texts + [extra]).casefold()
        return all(word in haystack for word in self._words)

    def lessThan(self, left, right):
        a, b = left.data(SORT_ROLE), right.data(SORT_ROLE)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a < b
        return str(a if a is not None else "").casefold() < str(
            b if b is not None else "").casefold()
