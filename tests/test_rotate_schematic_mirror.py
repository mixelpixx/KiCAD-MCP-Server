"""
Tests for rotate_schematic_component mirror/rotation fix.

Tests are split into two layers:
 1. WireDragger unit tests — pure sexpdata logic, no KiCAD deps.
 2. Handler integration smoke test — patches SchematicManager away.
"""

import os
import sys
import math
import textwrap
import tempfile
import importlib.util
from unittest.mock import patch, MagicMock

import sexpdata
from sexpdata import Symbol

# ---------------------------------------------------------------------------
# Import WireDragger directly (no pcbnew / kicad_interface needed)
# ---------------------------------------------------------------------------
_wd_spec = importlib.util.spec_from_file_location(
    "wire_dragger",
    os.path.join(os.path.dirname(__file__), "..", "python", "commands", "wire_dragger.py"),
)
_wd_mod = importlib.util.module_from_spec(_wd_spec)

# wire_dragger imports pin_locator lazily inside get_pin_defs.
# We stub only the submodule, not the parent package, so that
# kicad_interface can still import commands.board etc. from disk.
_pin_locator_mock = MagicMock()
sys.modules.setdefault("commands.pin_locator", _pin_locator_mock)

_wd_spec.loader.exec_module(_wd_mod)
WireDragger = _wd_mod.WireDragger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(text: str) -> list:
    return sexpdata.loads(text)


def _dump(data: list) -> str:
    return sexpdata.dumps(data)


def _make_sch(sym_extra: str = "", wires: str = "") -> list:
    """Build a minimal schematic sexpdata with one Q1 symbol."""
    text = textwrap.dedent(f"""\
        (kicad_sch (version 20250114) (generator "test")
          (lib_symbols
            (symbol "Transistor_BJT:MMBT3904"
              (pin passive line (at 0.0 1.0 270) (length 1.27)
                (name "B" (effects (font (size 1.27 1.27))))
                (number "1" (effects (font (size 1.27 1.27))))
              )
              (pin passive line (at -1.0 0.0 0) (length 1.27)
                (name "C" (effects (font (size 1.27 1.27))))
                (number "2" (effects (font (size 1.27 1.27))))
              )
            )
          )
          (symbol (lib_id "Transistor_BJT:MMBT3904")
                  (at 75 105 0)
                  {sym_extra}
                  (property "Reference" "Q1" (at 75 105 0))
                  (property "Value" "MMBT3904" (at 75 105 0))
          )
          {wires}
        )
    """)
    return _parse(text)


# ---------------------------------------------------------------------------
# Tests: update_symbol_rotation_mirror
# ---------------------------------------------------------------------------

def test_update_rotation_sets_angle():
    sch = _make_sch()
    result = WireDragger.update_symbol_rotation_mirror(sch, "Q1", 90.0, None)
    assert result is True
    dumped = _dump(sch)
    # at should now have 90 as the rotation value
    assert "90" in dumped


def test_update_mirror_x_adds_token():
    sch = _make_sch()
    WireDragger.update_symbol_rotation_mirror(sch, "Q1", 0.0, "x")
    dumped = _dump(sch)
    assert "mirror" in dumped
    assert " x" in dumped or "(mirror x)" in dumped


def test_update_mirror_y_adds_token():
    sch = _make_sch()
    WireDragger.update_symbol_rotation_mirror(sch, "Q1", 0.0, "y")
    dumped = _dump(sch)
    assert "mirror" in dumped


def test_update_mirror_none_removes_existing():
    """mirror=None should remove a pre-existing (mirror x) token."""
    sch = _make_sch(sym_extra="(mirror x)")
    WireDragger.update_symbol_rotation_mirror(sch, "Q1", 0.0, None)
    dumped = _dump(sch)
    assert "mirror" not in dumped


def test_update_mirror_replaces_existing():
    """Setting mirror='y' when (mirror x) exists should replace, not duplicate."""
    sch = _make_sch(sym_extra="(mirror x)")
    WireDragger.update_symbol_rotation_mirror(sch, "Q1", 0.0, "y")
    dumped = _dump(sch)
    assert dumped.count("mirror") == 1


def test_update_unknown_reference_returns_false():
    sch = _make_sch()
    result = WireDragger.update_symbol_rotation_mirror(sch, "U99", 0.0, "x")
    assert result is False


# ---------------------------------------------------------------------------
# Tests: compute_pin_positions_for_rotation
# ---------------------------------------------------------------------------

def test_pin_positions_change_on_rotation():
    """Pins at non-zero local offsets should move when the symbol rotates."""
    sch = _make_sch()

    # Provide a real pin_defs via patch so we don't need KiCAD libs
    fake_pins = {
        "1": {"x": 0.0, "y": 1.0},
        "2": {"x": -1.0, "y": 0.0},
    }
    with patch.object(WireDragger, "get_pin_defs", return_value=fake_pins):
        pos = WireDragger.compute_pin_positions_for_rotation(sch, "Q1", 90.0, False, False)

    assert len(pos) == 2
    for pin_num, (old_xy, new_xy) in pos.items():
        # After 90° rotation the positions must differ (pins not at origin)
        assert old_xy != new_xy, f"Pin {pin_num} should have moved"


def test_pin_positions_unchanged_at_same_transform():
    """Same rotation and same mirror → no movement."""
    sch = _make_sch()  # symbol at rotation=0, no mirror

    fake_pins = {"1": {"x": 1.0, "y": 0.0}}
    with patch.object(WireDragger, "get_pin_defs", return_value=fake_pins):
        pos = WireDragger.compute_pin_positions_for_rotation(sch, "Q1", 0.0, False, False)

    for _, (old_xy, new_xy) in pos.items():
        assert old_xy == new_xy


def test_pin_positions_mirror_x_flips_x():
    """mirror_x should negate the local X coordinate before rotation."""
    sch = _make_sch()  # at (75, 105, 0), no mirror

    fake_pins = {"1": {"x": 2.0, "y": 0.0}}
    with patch.object(WireDragger, "get_pin_defs", return_value=fake_pins):
        pos = WireDragger.compute_pin_positions_for_rotation(sch, "Q1", 0.0, True, False)

    _, (old_xy, new_xy) = next(iter(pos.items()))
    # old: pin at local (2, 0), world = (75+2, 105) = (77, 105)
    assert abs(old_xy[0] - 77.0) < 1e-4
    # new: mirror_x → local (-2, 0), world = (75-2, 105) = (73, 105)
    assert abs(new_xy[0] - 73.0) < 1e-4


# ---------------------------------------------------------------------------
# Integration smoke test: handler uses sexpdata, not kicad-skip
# ---------------------------------------------------------------------------

def test_rotate_handler_no_crash(tmp_path):
    """_handle_rotate_schematic_component should succeed without kicad-skip."""
    # Ensure python/ is on sys.path so commands.* imports resolve
    _python_dir = os.path.join(os.path.dirname(__file__), "..", "python")
    if _python_dir not in sys.path:
        sys.path.insert(0, _python_dir)

    # Stub heavy imports before loading kicad_interface
    for modname in ("pcbnew", "skip", "resources", "schemas",
                    "resources.resource_definitions", "schemas.tool_schemas",
                    "annotations"):
        sys.modules.setdefault(modname, MagicMock())
    sys.modules["resources.resource_definitions"].RESOURCE_DEFINITIONS = {}
    sys.modules["resources.resource_definitions"].handle_resource_read = MagicMock()
    sys.modules["schemas.tool_schemas"].TOOL_SCHEMAS = []

    _pcbnew = sys.modules["pcbnew"]
    _pcbnew.__file__ = "/fake/pcbnew.so"
    _pcbnew.GetBuildVersion.return_value = "9.0.0"

    ki_spec = importlib.util.spec_from_file_location(
        "kicad_interface_smoke",
        os.path.join(os.path.dirname(__file__), "..", "python", "kicad_interface.py"),
    )
    ki_mod = importlib.util.module_from_spec(ki_spec)
    ki_spec.loader.exec_module(ki_mod)
    KiCADInterface = ki_mod.KiCADInterface

    # Write a minimal schematic file
    sch_path = str(tmp_path / "test.kicad_sch")
    sch_content = textwrap.dedent("""\
        (kicad_sch (version 20250114) (generator "test")
          (lib_symbols
            (symbol "Device:R"
              (pin passive line (at 0 1.016 270) (length 1.27)
                (name "~" (effects (font (size 1.27 1.27))))
                (number "1" (effects (font (size 1.27 1.27))))
              )
              (pin passive line (at 0 -1.016 90) (length 1.27)
                (name "~" (effects (font (size 1.27 1.27))))
                (number "2" (effects (font (size 1.27 1.27))))
              )
            )
          )
          (symbol (lib_id "Device:R") (at 100 100 0)
            (property "Reference" "R1" (at 100 100 0))
            (property "Value" "10k" (at 100 100 0))
          )
        )
    """)
    with open(sch_path, "w") as f:
        f.write(sch_content)

    iface = KiCADInterface.__new__(KiCADInterface)
    result = iface._handle_rotate_schematic_component({
        "schematicPath": sch_path,
        "reference": "R1",
        "angle": 90,
    })

    assert result["success"] is True
    assert result["angle"] == 90

    # Verify the file was actually updated
    with open(sch_path) as f:
        updated = f.read()
    assert "90" in updated
