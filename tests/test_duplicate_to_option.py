import pytest

from archicad_toolkit import ArchicadError, TapirClient
from archicad_toolkit.cli import main
from archicad_toolkit.commands.duplicate_to_option import duplicate_to_option
from fake_archicad import FakeArchicad

OPTION_PROP = {("Design Options", "Option"): "prop-option"}


def make_fake(**kwargs):
    kwargs.setdefault("elements", ["wall-1", "wall-2", "slab-1"])
    kwargs.setdefault("selected", ["wall-1", "wall-2"])
    kwargs.setdefault("properties", OPTION_PROP)
    return FakeArchicad(**kwargs)


def test_copies_selection_and_tags_copies():
    fake = make_fake()
    result = duplicate_to_option(TapirClient(fake), "Option B")

    assert result.source_guids == ["wall-1", "wall-2"]
    assert result.copy_guids == ["copy-1", "copy-2"]
    assert result.warnings == []
    assert fake.values == {
        ("copy-1", "prop-option"): "Option B",
        ("copy-2", "prop-option"): "Option B",
    }
    assert fake.positions == {"copy-1": (0.0, 0.0, 0.0), "copy-2": (0.0, 0.0, 0.0)}


def test_offset_and_tag_originals():
    fake = make_fake()
    result = duplicate_to_option(
        TapirClient(fake), "Option B", offset=(10.0, 0.0, 0.0), tag_originals="Option A"
    )
    assert result.tagged_originals == "Option A"
    assert fake.positions["copy-1"] == (10.0, 0.0, 0.0)
    assert fake.values[("wall-1", "prop-option")] == "Option A"
    assert fake.values[("copy-1", "prop-option")] == "Option B"


def test_empty_selection_changes_nothing():
    fake = make_fake(selected=[])
    with pytest.raises(ArchicadError, match="Nothing is selected"):
        duplicate_to_option(TapirClient(fake), "Option B")
    assert "Tapir.MoveElements" not in fake.commands()


def test_missing_property_fails_before_copying():
    fake = make_fake(properties={})
    with pytest.raises(ArchicadError, match="not found"):
        duplicate_to_option(TapirClient(fake), "Option B")
    assert "Tapir.MoveElements" not in fake.commands()
    assert fake.elements == ["wall-1", "wall-2", "slab-1"]


def test_blank_option_name_rejected():
    with pytest.raises(ValueError):
        duplicate_to_option(TapirClient(make_fake()), "   ")


def test_warns_when_copy_count_differs():
    fake = make_fake()
    original = fake._tapir_MoveElements

    def copy_only_first(params):
        params = {"elementsWithMoveVectors": params["elementsWithMoveVectors"][:1]}
        return original(params)

    fake._tapir_MoveElements = copy_only_first
    result = duplicate_to_option(TapirClient(fake), "Option B")
    assert result.copy_guids == ["copy-1"]
    assert "Selected 2 elements but found 1" in result.warnings[0]


def test_cli_reports_result(capsys):
    fake = make_fake()
    code = main(["duplicate-to-option", "Option B", "--tag-originals", "Option A"],
                client=TapirClient(fake))
    assert code == 0
    assert "Created 2 element(s) in option 'Option B'" in capsys.readouterr().out


def test_cli_returns_error_code(capsys):
    code = main(["duplicate-to-option", "Option B"], client=TapirClient(make_fake(selected=[])))
    assert code == 1
    assert "Nothing is selected" in capsys.readouterr().err
