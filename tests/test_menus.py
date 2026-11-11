"""Barre de menus : fichiers, options, création de filtre, aide ; librairie en dossiers."""
import numpy as np
import pytest
from PyQt6 import QtCore, QtWidgets

from controller.main_controller import EXTERNAL, REF_ROLE, MainController
from instrument.hp4194a import SimulatedInstrument
from model import fit
from model.capture import Capture
from model.library import Library, LibraryError, read_capture
from view.main_window import MainWindow

F = np.geomspace(100, 3e6, 100)
Z = fit.impedance("Foster", F, [0.05, 8e-6, 2.0, 1e-6], 1, 0)


@pytest.fixture(scope="session")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def make(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulatedInstrument, "MAX_DURATION", 0.0)
    controller = MainController(MainWindow(), tmp_path / "library", tmp_path / "settings.json")
    controller.errors = []
    monkeypatch.setattr(controller, "_error", controller.errors.append)
    monkeypatch.setattr(controller, "_confirm", lambda text: True)
    return controller


def tree_labels(ctrl, parent=None, depth=0):
    parent = parent or ctrl.tree_model.invisibleRootItem()
    labels = []
    for row in range(parent.rowCount()):
        item = parent.child(row)
        labels.append("  " * depth + item.text())
        labels += tree_labels(ctrl, item, depth + 1)
    return labels


def select(ctrl, ref):
    def walk(parent):
        for row in range(parent.rowCount()):
            item = parent.child(row)
            if tuple(item.data(REF_ROLE)) == ref:
                return item
            found = walk(item)
            if found is not None:
                return found
    item = walk(ctrl.tree_model.invisibleRootItem())
    ctrl.view.tree.setCurrentIndex(item.index())


def measure(ctrl):
    ctrl.toggle_measure()
    loop = QtCore.QEventLoop()
    ctrl._worker.finished.connect(loop.quit)
    QtCore.QTimer.singleShot(10000, loop.quit)
    loop.exec()
    QtWidgets.QApplication.processEvents()


# --------------------------------------------------------------------------- librairie
def test_library_scans_subfolders(tmp_path):
    library = Library(tmp_path)
    library.add(Capture("racine", F, Z))
    library.add(Capture("self 1", F, Z), "selfs/serie A")
    (tmp_path / "vide").mkdir()
    (tmp_path / "selfs" / "notes.json").write_text('{"autre": 1}', encoding="utf-8")

    reloaded = Library(tmp_path)
    reloaded.load()
    assert sorted(c.name for c in reloaded.captures) == ["racine", "self 1"]
    assert reloaded.errors == []                        # notes.json : ignoré sans erreur
    assert reloaded.subfolders() == ["selfs", "selfs/serie A", "vide"]
    by_name = {c.name: reloaded.relative_folder(c) for c in reloaded.captures}
    assert by_name == {"racine": "", "self 1": "selfs/serie A"}


def test_saving_keeps_a_capture_in_its_folder(tmp_path):
    library = Library(tmp_path)
    capture = Capture("a", F, Z)
    library.add(capture, "sub")
    capture.name = "b"
    library.save(capture)
    assert [p.parent.name for p in tmp_path.rglob("*.json")] == ["sub"]


def test_read_capture_rejects_other_files(tmp_path):
    other = tmp_path / "x.json"
    other.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(LibraryError):
        read_capture(other)
    with pytest.raises(LibraryError):
        read_capture(tmp_path / "absent.json")


# --------------------------------------------------------------------------- arborescence
def test_tree_shows_folders_and_measures_go_to_the_selected_one(app, tmp_path, monkeypatch):
    library = Library(tmp_path / "library")
    library.add(Capture("self 1", F, Z), "selfs")
    (tmp_path / "library" / "capas").mkdir()
    ctrl = make(tmp_path, monkeypatch)
    assert tree_labels(ctrl) == ["capas", "selfs", "  self 1"]

    select(ctrl, ("folder", "capas", None))
    assert ctrl.selected() == (None, None) and ctrl.target_folder() == "capas"
    measure(ctrl)
    assert tree_labels(ctrl) == ["capas", "  mesure", "selfs", "  self 1"]
    assert len(list((tmp_path / "library" / "capas").glob("*.json"))) == 1
    # la sélection est sur la nouvelle capture : la suivante va dans le même dossier
    assert ctrl.target_folder() == "capas"
    ctrl.delete_selected()
    assert tree_labels(ctrl) == ["capas", "selfs", "  self 1"]


# --------------------------------------------------------------------------- menu Fichier
def test_menus_exist(app, tmp_path, monkeypatch):
    ctrl = make(tmp_path, monkeypatch)
    titles = [a.text() for a in ctrl.view.menuBar().actions()]
    assert titles == ["Fichier", "Utilitaires", "Aide"]
    assert ctrl.view.actionOpen in ctrl.view.menuFile.actions()
    assert ctrl.view.actionSaveAs in ctrl.view.menuFile.actions()
    assert ctrl.view.actionQuit in ctrl.view.menuFile.actions()
    assert ctrl.view.menuTools.actions() == [ctrl.view.actionOptions, ctrl.view.actionFilter]
    assert ctrl.view.actionTutorial in ctrl.view.menuHelp.actions()


def test_open_and_save_as(app, tmp_path, monkeypatch):
    ctrl = make(tmp_path, monkeypatch)
    outside = tmp_path / "ailleurs"
    outside.mkdir()
    Library(outside).add(Capture("externe", F, Z))
    path = next(outside.glob("*.json"))
    bad = outside / "bad.txt.json"
    bad.write_text("{", encoding="utf-8")

    monkeypatch.setattr(ctrl, "_ask_open_paths", lambda *a: [str(path), str(bad)])
    ctrl.open_files()
    assert tree_labels(ctrl) == [EXTERNAL, "  externe"]
    assert ctrl.selected()[0].name == "externe"
    assert len(ctrl.errors) == 1 and "bad.txt.json" in ctrl.errors[0]
    ctrl.open_files()                                   # déjà ouverte : pas de doublon
    assert len(ctrl.library.captures) == 1

    # une capture externe reste enregistrée dans son fichier d'origine
    ctrl.add_model()
    assert read_capture(next(outside.glob("externe*.json"))).models[0].fitted
    assert not list((tmp_path / "library").glob("*.json"))

    select(ctrl, ("capture", ctrl.library.captures[0].id, None))
    copy = tmp_path / "copie.json"
    monkeypatch.setattr(ctrl, "_ask_save_path", lambda *a: str(copy))
    ctrl.save_capture_as()
    assert read_capture(copy).name == "externe" and len(read_capture(copy).models) == 1


def test_quit_closes_the_window(app, tmp_path, monkeypatch):
    ctrl = make(tmp_path, monkeypatch)
    ctrl.view.show()
    ctrl.view.actionQuit.trigger()
    assert not ctrl.view.isVisible()
    assert (tmp_path / "settings.json").exists()


# --------------------------------------------------------------------------- options
def test_options_change_the_library_folder(app, tmp_path, monkeypatch):
    other = tmp_path / "autre librairie"
    Library(other).add(Capture("capa", F, Z), "condensateurs")
    ctrl = make(tmp_path, monkeypatch)
    measure(ctrl)
    assert tree_labels(ctrl) == ["mesure"]

    dialog = ctrl.open_options()
    assert dialog.tabWidget.tabText(0) == "Modèles"
    assert dialog.getOptions()["library_dir"] == str(tmp_path / "library")
    root = dialog.parameter_roots["Modèles"]
    root.child("Répertoire des mesures et modèles").setValue(str(other))
    root.child("Nouveau modèle", "Type pour une inductance").setValue("Cauer")
    root.child("Nouveau modèle", "Ordre automatique").setValue(False)
    dialog.accept()

    assert tree_labels(ctrl) == ["condensateurs", "  capa"]
    assert ctrl.options["default_kind"] == "Cauer"
    select(ctrl, ("capture", ctrl.library.captures[0].id, None))
    ctrl.add_model()
    model = ctrl.selected()[1]
    assert model.kind == "Cauer" and model.auto_order is False and model.name == "Cauer 1"

    # au démarrage suivant, le répertoire choisi est scruté
    ctrl.view.close()
    again = make(tmp_path, monkeypatch)
    assert again.library.folder == other
    assert tree_labels(again)[:2] == ["condensateurs", "  capa"]


def test_cancelled_options_change_nothing(app, tmp_path, monkeypatch):
    ctrl = make(tmp_path, monkeypatch)
    dialog = ctrl.open_options()
    dialog.parameter_roots["Modèles"].child("Nouveau modèle", "Type pour une inductance").setValue("Cauer")
    dialog.reject()
    assert ctrl.options["default_kind"] == "Foster"


# --------------------------------------------------------------------------- filtre
def test_filter_window(app, tmp_path, monkeypatch):
    ctrl = make(tmp_path, monkeypatch)
    ctrl.open_filter()
    fc = ctrl.filter_ctrl
    # librairie vide : composants idéaux, filtre T L-C-L par défaut
    branches = fc.params.child("Composants").children()
    assert [b.name() for b in branches] == ["Z1 (série)", "Z2 (parallèle)", "Z3 (série)"]
    assert [b["Composant"] for b in branches] == ["L idéale", "C idéale", "L idéale"]
    assert branches[1].child("Valeur").opts["suffix"] == "F"
    assert fc.response is not None and fc.response.cutoff() is not None
    assert len(fc.view.plot_gain.listDataItems()) == 1
    names = [p.name() for p in fc.params.child("Résultats").children()]
    assert names[0] == "Bande calculée" and "Coupure à −3 dB" in names

    # une mesure et son modèle deviennent des composants disponibles
    measure(ctrl)
    ctrl.add_model()
    choices = fc.params.child("Composants", "Z1 (série)", "Composant").opts["limits"]
    assert "Mesure : mesure" in choices and "Modèle : mesure / Foster 1" in choices
    branch = fc.params.child("Composants", "Z1 (série)")
    branch.child("Composant").setValue("Mesure : mesure")
    assert not branch.child("Valeur").opts["visible"]
    assert fc.response.f[0] == pytest.approx(100.0)
    assert fc.response.f[-1] == pytest.approx(ctrl.library.captures[0].f[-1])

    # changement de topologie : les branches sont reconstruites
    fc.params.child("Topologie").setValue("Pi (parallèle, série, parallèle)")
    assert [b.name() for b in fc.params.child("Composants").children()] == [
        "Z1 (parallèle)", "Z2 (série)", "Z3 (parallèle)"]
    assert fc.response is not None

    # capture supprimée alors qu'elle est utilisée : le filtre retombe sur un composant idéal
    fc.params.child("Composants", "Z2 (série)", "Composant").setValue("Mesure : mesure")
    select(ctrl, ("capture", ctrl.library.captures[0].id, None))
    ctrl.delete_selected()
    assert fc.params.child("Composants", "Z2 (série)")["Composant"] == "L idéale"
    assert fc.response is not None


def test_filter_reports_missing_common_band(app, tmp_path, monkeypatch):
    library = Library(tmp_path / "library")
    library.add(Capture("bas", [1e2, 1e3], [1j, 2j]))
    library.add(Capture("haut", [1e5, 1e6], [1j, 2j]))
    ctrl = make(tmp_path, monkeypatch)
    ctrl.open_filter()
    fc = ctrl.filter_ctrl
    fc.params.child("Topologie").setValue("L (série, parallèle)")
    fc.params.child("Composants", "Z1 (série)", "Composant").setValue("Mesure : bas")
    fc.params.child("Composants", "Z2 (parallèle)", "Composant").setValue("Mesure : haut")
    assert fc.response is None
    assert "bande de fréquence commune" in fc.view.message.text()
    assert fc.view.plot_gain.listDataItems() == []


# --------------------------------------------------------------------------- aide
def test_tutorial(app, tmp_path, monkeypatch):
    ctrl = make(tmp_path, monkeypatch)
    browser = ctrl.show_tutorial()
    text = browser.toPlainText()
    assert "Faire une mesure" in text and "Créer un filtre" in text
