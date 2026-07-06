"""
Tests for loud, diagnosed schematic load failures (SchematicLoadError).

Flat SnapEDA/SamacSys lib symbols (pins directly under the top-level
(symbol "NAME") with no sub-unit) crash kicad-skip's LibSymbol parser.
SchematicManager.load_schematic now raises SchematicLoadError with the
offending symbols named instead of returning None, and every handler
returns {success: false, error: "schematic_load_failed", flatSymbols: [...]}.

Requires the real kicad-skip package (conftest only stubs `skip` when the
real module is missing); the module self-skips under the stub.
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

skip_mod = pytest.importorskip("skip")
if getattr(skip_mod, "__file__", None) is None:
    pytest.skip("real kicad-skip not installed (conftest stub)", allow_module_level=True)

from commands.schematic import (  # noqa: E402
    SchematicLoadError,
    SchematicManager,
    find_flat_lib_symbols,
)

FLAT_SCH = """\
(kicad_sch (version 20250114) (generator "eeschema") (generator_version "9.0")
  (uuid 11111111-2222-3333-4444-555555555555)
  (paper "A4")
  (lib_symbols
    (symbol "FLAT:FLAT_PART" (pin_numbers hide) (in_bom yes) (on_board yes)
      (property "Reference" "U" (at 0 0 0) (effects (font (size 1.27 1.27))))
      (property "Value" "FLAT_PART" (at 0 2 0) (effects (font (size 1.27 1.27))))
      (pin passive line (at 0 0 0) (length 2.54)
        (name "P1" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27))))
      )
      (rectangle (start -2 -2) (end 2 2) (stroke (width 0.254) (type default)) (fill (type background)))
    )
  )
  (symbol (lib_id "FLAT:FLAT_PART") (at 50 50 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid aaaaaaaa-bbbb-cccc-dddd-111111111111)
    (property "Reference" "U1" (at 50 45 0) (effects (font (size 1.27 1.27))))
    (property "Value" "FLAT_PART" (at 50 55 0) (effects (font (size 1.27 1.27))))
  )
  (sheet_instances (path "/" (page "1")))
)
"""

TEMPLATE_SCH = Path(__file__).parent.parent / "python" / "templates" / "empty.kicad_sch"


@pytest.fixture()
def flat_sch(tmp_path):
    p = tmp_path / "flat.kicad_sch"
    p.write_text(FLAT_SCH, encoding="utf-8")
    return p


@pytest.fixture()
def good_sch(tmp_path):
    p = tmp_path / "good.kicad_sch"
    p.write_text(TEMPLATE_SCH.read_text(encoding="utf-8"), encoding="utf-8")
    return p


def _make_iface() -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        return KiCADInterface.__new__(KiCADInterface)


# ---------------------------------------------------------------------------
# Diagnosis + loader contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFlatSymbolDiagnosis:
    def test_find_flat_lib_symbols(self, flat_sch, good_sch):
        assert find_flat_lib_symbols(str(flat_sch)) == ["FLAT:FLAT_PART"]
        assert find_flat_lib_symbols(str(good_sch)) == []

    def test_find_flat_on_unreadable_file_returns_empty(self, tmp_path):
        assert find_flat_lib_symbols(str(tmp_path / "nope.kicad_sch")) == []

    def test_kicad_skip_still_crashes_on_flat(self, flat_sch):
        """Guards the diagnosis: if a future kicad-skip tolerates flat
        symbols, this failure signals the special-casing can be removed."""
        with pytest.raises(Exception):
            skip_mod.Schematic(str(flat_sch))


@pytest.mark.unit
class TestLoadSchematicRaises:
    def test_flat_raises_with_diagnosis(self, flat_sch):
        with pytest.raises(SchematicLoadError) as exc_info:
            SchematicManager.load_schematic(str(flat_sch))
        err = exc_info.value
        assert err.kind == "parse_error"
        assert err.flat_symbols == ["FLAT:FLAT_PART"]
        assert "FLAT:FLAT_PART" in str(err)
        assert "repair_flat_symbols" in str(err)

    def test_missing_file_raises_not_found(self, tmp_path):
        with pytest.raises(SchematicLoadError) as exc_info:
            SchematicManager.load_schematic(str(tmp_path / "missing.kicad_sch"))
        assert exc_info.value.kind == "not_found"
        assert "not found" in str(exc_info.value)

    def test_good_schematic_loads(self, good_sch):
        sch = SchematicManager.load_schematic(str(good_sch))
        assert sch is not None

    def test_to_response_shape(self, flat_sch):
        with pytest.raises(SchematicLoadError) as exc_info:
            SchematicManager.load_schematic(str(flat_sch))
        r = exc_info.value.to_response()
        assert r["success"] is False
        assert r["error"] == "schematic_load_failed"
        assert r["flatSymbols"] == ["FLAT:FLAT_PART"]
        assert "errorDetails" in r


# ---------------------------------------------------------------------------
# Handlers surface the structured error
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlersSurfaceError:
    def test_list_schematic_components(self, flat_sch):
        iface = _make_iface()
        r = iface._handle_list_schematic_components({"schematicPath": str(flat_sch)})
        assert r["success"] is False
        assert r.get("error") == "schematic_load_failed"
        assert r.get("flatSymbols") == ["FLAT:FLAT_PART"]
        assert "repair_flat_symbols" in r["message"]
        assert r["message"] != "Failed to load schematic"

    def test_list_schematic_wires(self, flat_sch):
        iface = _make_iface()
        r = iface._handle_list_schematic_wires({"schematicPath": str(flat_sch)})
        assert r["success"] is False
        assert r.get("flatSymbols") == ["FLAT:FLAT_PART"]

    def test_batch_connect_aborts_with_diagnosis(self, flat_sch):
        import types

        from commands.schematic_batch import SchematicBatchCommands

        cmds = SchematicBatchCommands(types.SimpleNamespace())
        r = cmds.batch_connect(
            {
                "schematicPath": str(flat_sch),
                "connections": {"U1": {"1": "NET_X"}},
            }
        )
        assert r["success"] is False
        assert "FLAT:FLAT_PART" in r["message"]
        assert "All pin operations aborted" in r["message"]
        assert "connected 0" not in r["message"]

    def test_pin_locator_raises(self, flat_sch):
        from commands.pin_locator import PinLocator

        locator = PinLocator()
        with pytest.raises(SchematicLoadError):
            locator.get_pin_location(flat_sch, "U1", "1")

    def test_find_orphaned_wires_errors(self, flat_sch):
        iface = _make_iface()
        r = iface._handle_find_orphaned_wires({"schematicPath": str(flat_sch)})
        assert r["success"] is False
        assert r.get("error") == "schematic_load_failed"
        assert not r.get("message", "").startswith("Found ")

    def test_handle_command_backstop(self, flat_sch):
        """Any route that lets SchematicLoadError escape must still yield the
        structured error, never the generic 'Error handling command'."""
        iface = _make_iface()
        iface.command_routes = {
            "boom": lambda params: (_ for _ in ()).throw(
                SchematicLoadError(str(flat_sch), flat_symbols=["X:Y"])
            )
        }
        # Minimal attrs used by handle_command before dispatch
        iface.board = None
        iface.use_ipc = False
        r = iface.handle_command("boom", {})
        assert r["success"] is False
        assert r["error"] == "schematic_load_failed"
        assert r["flatSymbols"] == ["X:Y"]
        assert "Error handling command" not in r["message"]
