"""Composant : fiche, mesures, modèle de référence, format de fichier, répertoires."""
import json

import pytest

from helpers import F, Z_CAP, Z_COIL, component
from model import component as cmp
from model import fit
from model import library as lib
from model.capture import Capture, ModelFit
from model.component import Component
from model.library import Library, LibraryError


def fitted_model(capture, **settings):
    model = ModelFit(f_min=float(capture.f[0]), f_max=float(capture.f[-1]),
                     auto_order=False, parallel_cap=False, **settings)
    fit.run(model, capture.f, capture.z)
    capture.models.append(model)
    return model


# --------------------------------------------------------------------------- valeurs
@pytest.mark.parametrize("text, expected", [
    ("10u", 10e-6), ("4,7 µH", 4.7e-6), ("100nF", 100e-9), ("1e-6", 1e-6), ("2.2 mH", 2.2e-3),
    ("47 pF", 47e-12), ("0.5", 0.5), ("", None), ("   ", None)])
def test_parse_value(text, expected):
    assert cmp.parse_value(text) == (pytest.approx(expected) if expected else None)


@pytest.mark.parametrize("text", ["abc", "10 x", "-3u", "0"])
def test_parse_value_rejects_nonsense(text):
    with pytest.raises(cmp.ValueFormatError):
        cmp.parse_value(text)


def test_format_value():
    assert cmp.format_value(4.7e-6, "H") == "4.7 µH"
    assert cmp.format_value(100e-9, "F") == "100 nF"
    assert cmp.format_value(1e-3, "H") == "1 mH"
    assert cmp.format_value(None, "H") == ""
    assert cmp.parse_value(cmp.format_value(22e-6, "H")) == pytest.approx(22e-6)


# --------------------------------------------------------------------------- composant
def test_empty_card_is_allowed():
    comp = component("inconnu")
    assert (comp.kind, comp.technology, comp.manufacturer, comp.fay_code) == ("", "", "", "")
    assert comp.nominal is None and comp.nominal_text() == "" and comp.measured_text() == ""
    assert comp.reference_model() is None
    assert comp.detect_kind() == cmp.INDUCTOR
    assert component("c", Z_CAP).detect_kind() == cmp.CAPACITOR


def test_reference_model_and_measured_value():
    comp = component("self", kind=cmp.INDUCTOR)
    capture = comp.captures[0]
    low = fitted_model(capture, kind="Foster", nr=1, name="bas")
    high = fitted_model(capture, kind="Cauer", nr=1, name="haut")
    # sans choix : le premier modèle ajusté
    assert comp.reference_model() == (capture, low)
    assert comp.measured_value() == pytest.approx(8e-6, rel=0.01)
    assert comp.measured_text() == "8 µH"
    comp.reference = (capture.id, high.id)
    assert comp.is_reference(capture, high) and not comp.is_reference(capture, low)
    # référence disparue : retour au premier modèle
    capture.models.remove(high)
    assert comp.reference_model() == (capture, low)


def test_capacitor_measured_value_is_c0():
    comp = component("capa", Z_CAP, kind=cmp.CAPACITOR)
    fitted_model(comp.captures[0], kind=fit.CAPACITOR, nr=0)
    assert comp.measured_value() == pytest.approx(1e-6, rel=0.01)
    assert comp.measured_text() == "1 µF"


def test_fit_is_traceable():
    capture = Capture("m", F, Z_COIL)
    model = fitted_model(capture, kind="Foster", nr=1)
    assert model.date[:2] == "20" and model.version


# --------------------------------------------------------------------------- fichier
def test_round_trip_keeps_everything(tmp_path):
    comp = component("Self 10µH", kind=cmp.INDUCTOR, technology="Poudre de fer",
                     manufacturer="Würth", part_number="7443551", fay_code="FAY-0042",
                     nominal=10e-6, conditions="OSC 0.5 V", comment="échantillon 3")
    comp.captures.append(Capture("avec polarisation", F, Z_COIL * 0.9))
    model = fitted_model(comp.captures[1], kind="Foster", nr=1, name="modèle")
    comp.reference = (comp.captures[1].id, model.id)
    library = Library(tmp_path)
    library.add(comp, "selfs")

    reloaded = Library(tmp_path)
    reloaded.load()
    copy = reloaded.components[0]
    for key, _ in cmp.FIELDS:
        assert getattr(copy, key) == getattr(comp, key), key
    assert copy.id == comp.id and len(copy.captures) == 2
    assert copy.captures[1].z == pytest.approx(comp.captures[1].z)
    assert copy.reference_model()[1].name == "modèle"
    assert copy.reference_model()[1].date == model.date
    assert all(not c.visible for c in copy.captures)        # rien n'est tracé à l'ouverture
    assert pathlib_parent(copy.path) == "selfs"


def pathlib_parent(path):
    import pathlib
    return pathlib.Path(path).parent.name


def test_first_version_capture_files_are_read_as_components(tmp_path):
    old = Capture("mesure", F, Z_COIL)
    old.models.append(ModelFit(kind="Foster", params=[1.0, 2.0, 3.0, 4.0], name="Foster 1"))
    data = old.to_dict()
    assert data["format"] == "RLCmeter capture v1"
    (tmp_path / "mesure_abc.json").write_text(json.dumps(data), encoding="utf-8")

    library = Library(tmp_path)
    library.load()
    comp = library.components[0]
    assert comp.name == "mesure" and comp.kind == "" and comp.id == old.id
    assert comp.captures[0].models[0].name == "Foster 1"
    # réenregistré au nouveau format
    lib.save_component(comp)
    saved = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert saved["format"] == cmp.FORMAT and len(saved["measurements"]) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_library_ignores_foreign_files_and_reports_broken_ones(tmp_path):
    (tmp_path / "notes.json").write_text('{"autre": 1}', encoding="utf-8")
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    library = Library(tmp_path)
    library.load()
    assert library.components == [] and [name for name, _ in library.errors] == ["bad.json"]
    with pytest.raises(LibraryError):
        lib.read_component(tmp_path / "notes.json")
    with pytest.raises(LibraryError):
        lib.read_component(tmp_path / "absent.json")


def test_library_values_and_names(tmp_path):
    library = Library(tmp_path)
    library.add(component("a", manufacturer="Vishay"))
    library.add(component("b", manufacturer="wurth"))
    library.add(component("c", manufacturer="Vishay"))
    library.add(component("d"))
    assert library.values("manufacturer") == ["Vishay", "wurth"]
    assert library.unique_name("a") == "a (2)" and library.unique_name("z") == "z"


def test_rename_moves_the_file_and_remove_deletes_it(tmp_path):
    library = Library(tmp_path)
    comp = component("ancien")
    library.add(comp, "sub")
    comp.name = "nouveau"
    lib.save_component(comp)
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 1 and files[0].name.startswith("nouveau") \
        and files[0].parent.name == "sub"
    library.remove(comp)
    assert not list(tmp_path.rglob("*.json")) and library.components == []


def test_read_only_folder_raises_a_clear_error(tmp_path):
    blocker = tmp_path / "fichier"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(LibraryError):
        lib.save_component(component("x"), blocker / "sous-dossier")
