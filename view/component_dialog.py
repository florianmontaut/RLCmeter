# view/component_dialog.py
"""
Fiche d'un composant : type, technologie, fabricant, référence, code Fay, valeur nominale,
conditions de mesure, commentaire. Tous les champs peuvent rester vides.

À l'ajout d'une mesure à la librairie, la fenêtre propose aussi de la rattacher à un
composant déjà présent (nouvelle condition de mesure, autre échantillon).
"""
from PyQt6 import QtCore, QtGui, QtWidgets

from model import component as cmp
from view.main_window import ICON

UNSET = "(non renseigné)"


class ComponentDialog(QtWidgets.QDialog):

    def __init__(self, component: cmp.Component, technologies=(), manufacturers=(),
                 targets=None, parent=None):
        """
        technologies, manufacturers : valeurs déjà utilisées dans la librairie (proposées)
        targets : composants auxquels la mesure peut être rattachée (None : édition simple)
        """
        super().__init__(parent)
        self.setWindowIcon(QtGui.QIcon(str(ICON)))
        self.setWindowTitle("Ajouter à la librairie" if targets is not None
                            else "Fiche du composant")
        self.setMinimumWidth(520)
        self._known_technologies = list(technologies)
        self._targets = list(targets or [])
        layout = QtWidgets.QVBoxLayout(self)

        # destination : nouveau composant, ou mesure d'un composant existant
        self.newButton = QtWidgets.QRadioButton("Nouveau composant")
        self.existingButton = QtWidgets.QRadioButton("Nouvelle mesure du composant :")
        self.targetCombo = QtWidgets.QComboBox()
        for target in self._targets:
            details = " — ".join(v for v in (target.manufacturer, target.fay_code,
                                             target.nominal_text()) if v)
            self.targetCombo.addItem(f"{target.name} ({details})" if details else target.name)
        self.newButton.setChecked(True)
        if targets is not None:
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.existingButton)
            row.addWidget(self.targetCombo, 1)
            layout.addWidget(self.newButton)
            layout.addLayout(row)
            self.existingButton.setEnabled(bool(self._targets))
            self.targetCombo.setEnabled(False)
            self.existingButton.toggled.connect(self._on_destination_changed)

        # fiche
        self.form = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(self.form)
        form.setContentsMargins(0, 6, 0, 0)
        self.nameEdit = QtWidgets.QLineEdit(component.name)
        self.kindCombo = QtWidgets.QComboBox()
        self.kindCombo.addItems([UNSET, *cmp.KINDS])
        self.technologyCombo = QtWidgets.QComboBox()
        self.technologyCombo.setEditable(True)
        self.manufacturerCombo = QtWidgets.QComboBox()
        self.manufacturerCombo.setEditable(True)
        self.manufacturerCombo.addItems(["", *manufacturers])
        self.manufacturerCombo.setCurrentText(component.manufacturer)
        self.partEdit = QtWidgets.QLineEdit(component.part_number)
        self.fayEdit = QtWidgets.QLineEdit(component.fay_code)
        self.nominalEdit = QtWidgets.QLineEdit()
        self.nominalEdit.setPlaceholderText("ex : 10u, 4.7 µH, 100nF")
        self.conditionsEdit = QtWidgets.QLineEdit(component.conditions)
        self.conditionsEdit.setPlaceholderText("niveau d'oscillateur, montage, compensation...")
        self.commentEdit = QtWidgets.QPlainTextEdit(component.comment)
        self.commentEdit.setFixedHeight(70)
        measured = component.measured_text()
        self.measuredLabel = QtWidgets.QLabel(
            f"Valeur du modèle de référence : {measured}" if measured else "")
        self.measuredLabel.setEnabled(False)

        form.addRow("Nom", self.nameEdit)
        form.addRow("Type", self.kindCombo)
        form.addRow("Technologie", self.technologyCombo)
        form.addRow("Fabricant", self.manufacturerCombo)
        form.addRow("Référence fabricant", self.partEdit)
        form.addRow("Code Fay", self.fayEdit)
        form.addRow("Valeur nominale", self.nominalEdit)
        form.addRow("", self.measuredLabel)
        form.addRow("Conditions de mesure", self.conditionsEdit)
        form.addRow("Commentaire", self.commentEdit)
        layout.addWidget(self.form)

        self.errorLabel = QtWidgets.QLabel()
        self.errorLabel.setStyleSheet("color: #C62828;")
        self.errorLabel.setWordWrap(True)
        layout.addWidget(self.errorLabel)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                             | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # type : celui de la fiche, sinon celui déduit de la mesure
        kind = component.kind or component.detect_kind()
        self.kindCombo.setCurrentText(kind if kind in cmp.KINDS else UNSET)
        self._fill_technologies()
        self.technologyCombo.setCurrentText(component.technology)
        self.kindCombo.currentTextChanged.connect(self._fill_technologies)
        self.nominalEdit.setText(cmp.format_value(component.nominal,
                                                  cmp.UNITS.get(kind, "")))

    # ------------------------------------------------------------------ saisie
    def kind(self) -> str:
        text = self.kindCombo.currentText()
        return text if text in cmp.KINDS else ""

    def _fill_technologies(self, *_):
        """Technologies proposées : celles de la librairie, puis les usuelles du type."""
        current = self.technologyCombo.currentText()
        proposals = list(self._known_technologies)
        for name in cmp.TECHNOLOGIES.get(self.kind(), ()):
            if name.casefold() not in {p.casefold() for p in proposals}:
                proposals.append(name)
        self.technologyCombo.clear()
        self.technologyCombo.addItems(["", *proposals])
        self.technologyCombo.setCurrentText(current)

    def _on_destination_changed(self, existing: bool):
        self.targetCombo.setEnabled(existing)
        self.form.setEnabled(not existing)

    def target(self) -> cmp.Component | None:
        """Composant existant choisi comme destination ; None pour un nouveau composant."""
        if self.existingButton.isChecked() and self._targets:
            return self._targets[self.targetCombo.currentIndex()]
        return None

    def values(self) -> dict:
        """Champs de la fiche (attribut -> valeur), valeur nominale convertie."""
        return {
            "name": self.nameEdit.text().strip(),
            "kind": self.kind(),
            "technology": self.technologyCombo.currentText().strip(),
            "manufacturer": self.manufacturerCombo.currentText().strip(),
            "part_number": self.partEdit.text().strip(),
            "fay_code": self.fayEdit.text().strip(),
            "nominal": cmp.parse_value(self.nominalEdit.text()),
            "conditions": self.conditionsEdit.text().strip(),
            "comment": self.commentEdit.toPlainText().strip(),
        }

    def accept(self):
        if self.target() is None:
            try:
                values = self.values()
            except cmp.ValueFormatError as error:
                self.errorLabel.setText(str(error))
                return
            if not values["name"]:
                self.errorLabel.setText("Le nom est le seul champ obligatoire.")
                return
        super().accept()
