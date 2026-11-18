"""The variant registry must round-trip through ordinary KiCad project settings."""

import json

import pytest


def test_create_lists_native_entry_preserving_project(tmp_path):

    from commands.variant_registry import create_variant, list_variants, registered_names

    path = tmp_path / "board.kicad_pro"
    path.write_text(json.dumps({"schematic": {"other": 3}, "board": {"layers": []}}))
    args = {"projectPath": str(path)}
    assert list_variants(args)["variants"] == []
    item = {"name": "Lite", "description": "Без датчика"}
    result = create_variant({**args, **item})
    assert result["success"], result
    assert list_variants(args)["variants"] == [item]
    assert registered_names(str(path)) == ["Lite"]
    assert json.loads(path.read_bytes()) == {
        "schematic": {"other": 3, "variants": [item]},
        "board": {"layers": []},
    }


@pytest.mark.parametrize(
    "entry",
    [
        {"name": "lItE"},
        {"name": "  "},
        {"name": "< Default >"},
        {"name": " Lite"},
        {"name": "A\nB"},
        {"name": None},
        {"name": "X", "description": []},
    ],
)
def test_refuse_invalid_entry_without_writing(tmp_path, entry):
    from commands.variant_registry import create_variant

    path = tmp_path / "board.kicad_pro"
    before = b'{"schematic":{"variants":[{"name":"Lite"}]}}'
    path.write_bytes(before)
    result = create_variant({"projectPath": str(path), **entry})
    assert not result["success"] and result["error"]
    assert path.read_bytes() == before


def test_board_save_does_not_revert_variants(tmp_path):
    from utils.project_settings_guard import preserve_project_settings

    path = tmp_path / "board.kicad_pro"
    registry = [{"name": "Lite"}]
    path.write_text(json.dumps({"schematic": {"variants": registry, "other": 1}}))
    with preserve_project_settings(str(path.with_suffix(".kicad_pcb"))):
        path.write_text('{"schematic":{"variants":[],"other":2}}')
    assert json.loads(path.read_bytes())["schematic"] == {"variants": registry, "other": 2}
