"""Librairie : ajout avec fiche, tableau trié et filtré, modèle de référence, menus."""
import pytest
from PyQt6 import QtCore, QtWidgets

from helpers import (dispose, Z_CAP, answer, component, curves, find_item, get_app, labels,
                     library_names, library_row, make_controller, measure, session_labels)
from controller import library_view as lv
from model import component as cmp
from model import library as lib
from model.capture import Capture
from model.library import Library
from view.component_dialog import UNSET, ComponentDialog

ASC, DESC = QtCore.Qt.SortOrder.AscendingOrder, QtCore.Qt.SortOrder.DescendingOrder


@pytest.fixture
def ctrl(tmp_path, monkeypatch):
    controller = make_controller(tmp_path, monkeypatch)
    yield controller
    dispose(controller)


def fill_library(tmp_path):
    """Cinq composants variés, dont un à la fiche vide."""
    library = Library(tmp_path / "library")
    library.add(component("Self A", kind=cmp.INDUCTOR, technology="Poudre de fer",
                          manufacturer="Würth", fay_code="FAY-001", nominal=10e-6,
                          part_number="7443551100"))
    library.add(component("Self B", kind=cmp.INDUCTOR, technology="Amorphe",
                          manufacturer="Vishay", fay_code="FAY-002", nominal=470e-6))
    library.add(component("Capa film", Z_CAP, kind=cmp.CAPACITOR, technology="Polypropylène",
                          manufacturer="Vishay", fay_code="FAY-010", nominal=1e-6,
                          comment="série MKP"), "condensateurs")
    library.add(component("Capa chimique", Z_CAP, kind=cmp.CAPACITOR,
                          technology="Électrochimique", manufacturer="Würth",
                          nominal=100e-6))
    library.add(component("Inconnu"))


def combo_select(combo, text):
    combo.setCurrentIndex(combo.findText(text))


# --------------------------------------------------------------------------- ajout
def test_add_to_library_with_card(ctrl, tmp_path, monkeypatch):
    measure(ctrl)
    ctrl.add_model()
    assert ctrl.view.actionAddToLibrary.isEnabled()
    answer(ctrl, monkeypatch, name="Self 8µH", kind=cmp.INDUCTOR, technology="Poudre de fer",
           manufacturer="Würth", fay_code="FAY-123", nominal=8.2e-6)
    ctrl.add_to_library()

    assert ctrl.errors == [] and session_labels(ctrl) == [] and ctrl.session == []
    assert library_names(ctrl) == ["Self 8µH"]
    assert library_row(ctrl, "Self 8µH")[1:7] == [cmp.INDUCTOR, "Poudre de fer", "Würth",
                                                 "FAY-123", "8.2 µH", "1"]
    # le fichier a quitté les brouillons pour la librairie
    assert not list((tmp_path / "brouillons").glob("*.json"))
    saved = lib.read_component(next((tmp_path / "library").glob("*.json")))
    assert saved.fay_code == "FAY-123" and saved.captures[0].models[0].fitted
    # la mesure reste sélectionnée et tracée, dans la librairie
    comp, capture, model = ctrl.selected()
    assert comp.name == "Self 8µH" and capture is comp.captures[0] and model is None
    assert labels(ctrl.library_model) == ["Self 8µH", "  mesure", "    Foster 1"]
    assert len(curves(ctrl.view.plot_top)) == 2
    assert not ctrl.view.actionAddToLibrary.isEnabled()         # déjà dans la librairie


def test_card_fields_may_stay_empty(ctrl, monkeypatch):
    measure(ctrl)
    answer(ctrl, monkeypatch)                    # fiche validée telle quelle
    ctrl.add_to_library()
    assert library_row(ctrl, "mesure")[1:6] == ["", "", "", "", ""]
    comp = ctrl.library.components[0]
    assert comp.kind == "" and comp.nominal is None
    # sans valeur nominale, la colonne montre celle du modèle de référence
    ctrl.select(("capture", comp.id, comp.captures[0].id, None))
    ctrl.add_model()
    assert library_row(ctrl, "mesure")[lv.COL_VALUE].startswith("≈ ")


def test_add_as_measurement_of_an_existing_component(ctrl, tmp_path, monkeypatch):
    fill_library(tmp_path)
    ctrl._load_folders()
    ctrl._rebuild()
    target = next(c for c in ctrl.library.components if c.name == "Self A")
    ctrl.acq.child("Nom de la capture").setValue("avec 2 A de polarisation")
    measure(ctrl)
    answer(ctrl, monkeypatch, target=target)
    ctrl.add_to_library()

    assert [c.name for c in target.captures] == ["mesure 1", "avec 2 A de polarisation"]
    assert len(ctrl.library.components) == 5 and ctrl.session == []
    assert not list((tmp_path / "brouillons").glob("*.json"))
    assert library_row(ctrl, "Self A")[lv.COL_COUNT] == "2"
    assert lib.read_component(target.path).captures[1].name == "avec 2 A de polarisation"
    assert ctrl.selected()[1] is target.captures[1]
    # suppression d'une mesure parmi plusieurs : le composant reste
    ctrl.delete_selected()
    assert len(target.captures) == 1 and len(ctrl.library.components) == 5
    assert ctrl.selected() == (target, None, None)


def test_cancelled_card_leaves_the_draft(ctrl, tmp_path, monkeypatch):
    measure(ctrl)
    monkeypatch.setattr(ctrl, "_ask_component", lambda *a, **k: None)
    ctrl.add_to_library()
    assert session_labels(ctrl) == ["mesure"] and library_names(ctrl) == []
    assert len(list((tmp_path / "brouillons").glob("*.json"))) == 1


# --------------------------------------------------------------------------- tableau
def test_library_is_scanned_with_its_subfolders(ctrl, tmp_path):
    fill_library(tmp_path)
    ctrl._load_folders()
    ctrl._rebuild()
    assert library_names(ctrl) == ["Capa chimique", "Capa film", "Inconnu", "Self A", "Self B"]
    assert ctrl.view.libraryCount.text() == "5 composant(s)"
    assert curves(ctrl.view.plot_top) == []             # rien n'est tracé à l'ouverture


def test_search_and_filters_combine(ctrl, tmp_path):
    fill_library(tmp_path)
    ctrl._load_folders()
    ctrl._rebuild()
    v = ctrl.view
    assert [v.kindFilter.itemText(i) for i in range(v.kindFilter.count())] == [
        "Tous les types", cmp.INDUCTOR, cmp.CAPACITOR, lv.UNSET]
    assert [v.manufacturerFilter.itemText(i) for i in range(v.manufacturerFilter.count())] \
        == ["Tous les fabricants", "Vishay", "Würth", lv.UNSET]

    combo_select(v.kindFilter, cmp.CAPACITOR)
    assert library_names(ctrl) == ["Capa chimique", "Capa film"]
    combo_select(v.manufacturerFilter, "Vishay")
    assert library_names(ctrl) == ["Capa film"]
    assert v.libraryCount.text() == "1 composant(s) sur 5"
    combo_select(v.kindFilter, "Tous les types")
    assert library_names(ctrl) == ["Capa film", "Self B"]
    combo_select(v.manufacturerFilter, lv.UNSET)        # fiches à compléter
    assert library_names(ctrl) == ["Inconnu"]
    ctrl.clear_filters()

    for text, expected in (("fay-00", ["Self A", "Self B"]),            # code Fay
                           ("würth self", ["Self A"]),                  # deux mots
                           ("7443551100", ["Self A"]),                  # référence fabricant
                           ("mkp", ["Capa film"]),                      # commentaire
                           ("470", ["Self B"]),                         # valeur
                           ("introuvable", [])):
        v.searchEdit.setText(text)
        assert library_names(ctrl) == expected, text
    v.searchEdit.setText("self")
    combo_select(v.technologyFilter, "Amorphe")
    assert library_names(ctrl) == ["Self B"]


def test_sorting_by_column(ctrl, tmp_path):
    fill_library(tmp_path)
    ctrl._load_folders()
    ctrl._rebuild()
    tree = ctrl.view.libraryTree
    # valeur : tri numérique (10 µH < 470 µH), pas alphabétique ; fiche vide en dernier
    tree.sortByColumn(lv.COL_VALUE, ASC)
    assert library_names(ctrl) == ["Capa film", "Self A", "Capa chimique", "Self B", "Inconnu"]
    tree.sortByColumn(lv.COL_MANUFACTURER, DESC)
    assert library_names(ctrl)[:2] in (["Self A", "Capa chimique"], ["Capa chimique", "Self A"])
    tree.sortByColumn(lv.COL_NAME, DESC)
    assert library_names(ctrl)[0] == "Self B"


def test_selecting_a_component_plots_its_measurements(ctrl, tmp_path):
    fill_library(tmp_path)
    ctrl._load_folders()
    ctrl._rebuild()
    comp = next(c for c in ctrl.library.components if c.name == "Self A")
    assert ctrl.select(("component", comp.id, None, None))
    assert ctrl.selected() == (comp, None, None)
    assert len(curves(ctrl.view.plot_top)) == 1
    names = [p.name() for p in ctrl._selection_param.children()]
    assert names[:3] == ["Nom", "Type", "Technologie"] and "Modifier la fiche..." in names
    assert ctrl._selection_param["Code Fay"] == "FAY-001"
    # un élément masqué par un filtre reste sélectionnable : les filtres sont levés
    ctrl.view.searchEdit.setText("capa")
    assert ctrl.select(("component", comp.id, None, None))
    assert ctrl.view.searchEdit.text() == "" and ctrl.selected()[0] is comp
    # une seule sélection pour les deux vues
    measure(ctrl)
    assert ctrl.selected()[0] is ctrl.session[0]
    assert not ctrl.view.libraryTree.currentIndex().isValid()


# --------------------------------------------------------------------------- fiche
def test_edit_card(ctrl, tmp_path, monkeypatch):
    fill_library(tmp_path)
    ctrl._load_folders()
    ctrl._rebuild()
    comp = next(c for c in ctrl.library.components if c.name == "Inconnu")
    ctrl.select(("component", comp.id, None, None))
    answer(ctrl, monkeypatch, name="Self C", kind=cmp.INDUCTOR, manufacturer="TDK",
           nominal=33e-6)
    ctrl.edit_component()
    assert library_row(ctrl, "Self C")[1:6] == [cmp.INDUCTOR, "", "TDK", "", "33 µH"]
    assert ctrl.selected()[0] is comp
    assert lib.read_component(comp.path).manufacturer == "TDK"
    assert pathlib_name(comp.path).startswith("Self_C")
    assert "TDK" in [ctrl.view.manufacturerFilter.itemText(i)
                     for i in range(ctrl.view.manufacturerFilter.count())]


def pathlib_name(path):
    import pathlib
    return pathlib.Path(path).name


def test_component_dialog(tmp_path):
    get_app()
    comp = component("capa mystère", Z_CAP)
    targets = [component("Self A", manufacturer="Würth", fay_code="FAY-001")]
    dialog = ComponentDialog(comp, ["Polypropylène", "Maison"], ["Vishay", "Würth"], targets)
    # type déduit de la mesure, technologies de la librairie puis usuelles du type
    assert dialog.kindCombo.currentText() == cmp.CAPACITOR
    proposals = [dialog.technologyCombo.itemText(i)
                 for i in range(dialog.technologyCombo.count())]
    assert proposals[:3] == ["", "Polypropylène", "Maison"] and "Électrochimique" in proposals
    assert proposals.count("Polypropylène") == 1
    assert [dialog.manufacturerCombo.itemText(i) for i in range(3)] == ["", "Vishay", "Würth"]

    dialog.nominalEdit.setText("pas un nombre")
    dialog.accept()
    assert dialog.result() == 0 and "illisible" in dialog.errorLabel.text()
    dialog.nominalEdit.setText("4,7 µF")
    dialog.manufacturerCombo.setCurrentText("Kemet")            # saisie libre
    dialog.kindCombo.setCurrentText(UNSET)
    dialog.accept()
    assert dialog.result() == 1 and dialog.target() is None
    values = dialog.values()
    assert values["nominal"] == pytest.approx(4.7e-6)
    assert (values["manufacturer"], values["kind"], values["name"]) == ("Kemet", "",
                                                                        "capa mystère")

    # rattachement à un composant existant : la fiche n'est pas demandée
    other = ComponentDialog(comp, targets=targets)
    other.existingButton.setChecked(True)
    assert not other.form.isEnabled() and other.target() is targets[0]
    other.nominalEdit.setText("n'importe quoi")
    other.accept()
    assert other.result() == 1
    # édition simple : pas de choix de destination
    assert ComponentDialog(comp).target() is None


# --------------------------------------------------------------------------- référence
def test_reference_model(ctrl, monkeypatch):
    measure(ctrl)
    ctrl.add_model()
    ctrl.select(("capture", ctrl.session[0].id, ctrl.session[0].captures[0].id, None))
    ctrl.add_model()
    comp, capture, second = ctrl.selected()
    first = capture.models[0]
    assert comp.is_reference(capture, first)            # par défaut : le premier
    assert not ctrl._selection_param["Modèle de référence"]
    ctrl._selection_param.child("Modèle de référence").setValue(True)
    QtWidgets.QApplication.processEvents()
    assert comp.reference == (capture.id, second.id) and comp.is_reference(capture, second)
    assert lib.read_component(comp.path).reference == (capture.id, second.id)
    assert ctrl.selected()[2] is second                 # sélection conservée
    # supprimer le modèle de référence : retour au premier
    ctrl.delete_selected()
    assert comp.reference is None and comp.is_reference(capture, first)


# --------------------------------------------------------------------------- fichiers
def test_open_external_file_and_save_as(ctrl, tmp_path, monkeypatch):
    outside = tmp_path / "ailleurs"
    Library(outside).add(component("externe"))
    path = next(outside.glob("*.json"))
    bad = outside / "bad.json"
    bad.write_text("{", encoding="utf-8")

    monkeypatch.setattr(ctrl, "_ask_open_paths", lambda *a: [str(path), str(bad)])
    ctrl.open_files()
    assert session_labels(ctrl) == ["externe / mesure 1"]
    assert ctrl.selected()[0].name == "externe"
    assert len(ctrl.errors) == 1 and "bad.json" in ctrl.errors[0]
    ctrl.open_files()                                   # déjà ouvert : pas de doublon
    assert len(ctrl.session) == 1

    # un fichier ouvert à la main reste enregistré là où il est
    ctrl.add_model()
    assert lib.read_component(path).captures[0].models[0].fitted
    assert not list((tmp_path / "brouillons").glob("*.json"))

    copy = tmp_path / "copie.json"
    monkeypatch.setattr(ctrl, "_ask_save_path", lambda *a: str(copy))
    ctrl.save_component_as()
    assert lib.read_component(copy).name == "externe"

    # le retirer de la session ne supprime pas son fichier
    ctrl.select(("capture", ctrl.session[0].id, ctrl.session[0].captures[0].id, None))
    ctrl.delete_selected()
    assert ctrl.session == [] and path.exists()


def test_delete_component_from_library(ctrl, tmp_path):
    fill_library(tmp_path)
    ctrl._load_folders()
    ctrl._rebuild()
    comp = next(c for c in ctrl.library.components if c.name == "Self B")
    ctrl.select(("component", comp.id, None, None))
    ctrl.delete_selected()
    assert "Self B" not in library_names(ctrl) and len(ctrl.library.components) == 4
    assert len(list((tmp_path / "library").rglob("*.json"))) == 4


def test_unwritable_library_is_reported_and_keeps_the_draft(ctrl, tmp_path, monkeypatch):
    measure(ctrl)

    def refuse(comp, folder=None):
        raise lib.LibraryError("Enregistrement impossible : lecture seule")

    monkeypatch.setattr(lib, "save_component", refuse)
    answer(ctrl, monkeypatch, name="x")
    ctrl.add_to_library()
    assert len(ctrl.errors) == 1 and "lecture seule" in ctrl.errors[0]
    assert len(ctrl.session) == 1 and ctrl.library.components == []
    assert len(list((tmp_path / "brouillons").glob("*.json"))) == 1


# --------------------------------------------------------------------------- menus, options
def test_menus(ctrl):
    v = ctrl.view
    assert [a.text() for a in v.menuBar().actions()] == ["Fichier", "Utilitaires", "Aide"]
    for action in (v.actionOpen, v.actionSaveAs, v.actionAddToLibrary, v.actionEditComponent,
                   v.actionShowDrafts, v.actionQuit):
        assert action in v.menuFile.actions()
    assert v.menuTools.actions() == [v.actionOptions, v.actionFilter]
    assert v.actionTutorial in v.menuHelp.actions()
    v.show()
    v.actionQuit.trigger()
    assert not v.isVisible()


def test_options_change_the_folders(ctrl, tmp_path, monkeypatch):
    other = tmp_path / "autre librairie"
    Library(other).add(component("capa", Z_CAP, kind=cmp.CAPACITOR), "condensateurs")
    measure(ctrl)
    dialog = ctrl.open_options()
    assert dialog.tabWidget.tabText(0) == "Modèles"
    options = dialog.getOptions()
    assert options["library_dir"] == str(tmp_path / "library")
    assert options["drafts_dir"] == str(tmp_path / "brouillons")
    root = dialog.parameter_roots["Modèles"]
    root.child("Répertoire de la librairie").setValue(str(other))
    root.child("Nouveau modèle", "Type pour une inductance").setValue("Cauer")
    dialog.accept()

    assert library_names(ctrl) == ["capa"] and ctrl.options["default_kind"] == "Cauer"
    assert session_labels(ctrl) == ["mesure"]           # la session en cours est conservée
    ctrl.view.close()
    again = make_controller(tmp_path, monkeypatch)
    assert again.library.folder == other and library_names(again) == ["capa"]


def test_tutorial(ctrl):
    text = ctrl.show_tutorial().toPlainText()
    assert "Faire une mesure" in text and "librairie" in text.lower()


# --------------------------------------------------------------------------- filtre
def test_filter_uses_library_components_and_reference_models(ctrl, tmp_path, monkeypatch):
    fill_library(tmp_path)
    ctrl._load_folders()
    ctrl._rebuild()
    ctrl.open_filter()
    fc = ctrl.filter_ctrl
    branches = fc.params.child("Composants").children()
    assert [b.name() for b in branches] == ["Z1 (série)", "Z2 (parallèle)", "Z3 (série)"]
    # par défaut : une inductance en série, un condensateur en parallèle
    # (« Inconnu », à la fiche vide, est reconnu comme inductance d'après sa mesure)
    assert [b["Composant"] for b in branches] == ["Mesure : Inconnu / mesure 1",
                                                  "Mesure : Capa chimique / mesure 1",
                                                  "Mesure : Inconnu / mesure 1"]
    assert fc.response is not None and len(fc.view.plot_gain.listDataItems()) == 1

    # un modèle ajusté devient le modèle de référence du composant, proposé en tête
    comp = next(c for c in ctrl.library.components if c.name == "Self A")
    ctrl.select(("capture", comp.id, comp.captures[0].id, None))
    ctrl.add_model()
    choices = fc.params.child("Composants", "Z1 (série)", "Composant").opts["limits"]
    assert choices[0] == "★ Self A" and "Mesure : Self A / mesure 1" in choices
    assert "L idéale" in choices
    branch = fc.params.child("Composants", "Z1 (série)")
    branch.child("Composant").setValue("★ Self A")
    assert not branch.child("Valeur").opts["visible"] and fc.response is not None

    # composant idéal, puis changement de topologie
    branch.child("Composant").setValue("L idéale")
    assert branch.child("Valeur").opts["visible"] and branch.child("Valeur").opts["suffix"] == "H"
    fc.params.child("Topologie").setValue("Pi (parallèle, série, parallèle)")
    assert [b.name() for b in fc.params.child("Composants").children()] == [
        "Z1 (parallèle)", "Z2 (série)", "Z3 (parallèle)"]

    # composant supprimé alors qu'il est utilisé : repli sur un autre composant du même type
    fc.params.child("Composants", "Z2 (série)", "Composant").setValue("★ Self A")
    ctrl.select(("component", comp.id, None, None))
    ctrl.delete_selected()
    assert "Self A" not in fc.params.child("Composants", "Z2 (série)")["Composant"]
    assert fc.response is not None

    # une mesure de la session est aussi disponible
    measure(ctrl)
    choices = fc.params.child("Composants", "Z2 (série)", "Composant").opts["limits"]
    assert "Mesure : mesure" in choices


def test_filter_without_any_component_uses_ideal_parts(ctrl):
    ctrl.open_filter()
    fc = ctrl.filter_ctrl
    assert [b["Composant"] for b in fc.params.child("Composants").children()] == [
        "L idéale", "C idéale", "L idéale"]
    assert fc.response.cutoff() is not None
    names = [p.name() for p in fc.params.child("Résultats").children()]
    assert names[0] == "Bande calculée" and "Coupure à −3 dB" in names


def test_filter_reports_missing_common_band(ctrl, tmp_path):
    library = Library(tmp_path / "library")
    for name, f in (("bas", [1e2, 1e3]), ("haut", [1e5, 1e6])):
        comp = cmp.Component(name=name, captures=[Capture(name, f, [1j, 2j])])
        library.add(comp)
    ctrl._load_folders()
    ctrl._rebuild()
    ctrl.open_filter()
    fc = ctrl.filter_ctrl
    fc.params.child("Topologie").setValue("L (série, parallèle)")
    fc.params.child("Composants", "Z1 (série)", "Composant").setValue("Mesure : bas")
    fc.params.child("Composants", "Z2 (parallèle)", "Composant").setValue("Mesure : haut")
    assert fc.response is None
    assert "bande de fréquence commune" in fc.view.message.text()
