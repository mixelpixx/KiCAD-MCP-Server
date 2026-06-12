"""Unit tests for the kicad-cli-backed export handlers on ``KiCADInterface``.

These handlers (``_handle_export_*``) shell out to ``kicad-cli``. The tests mock
the subprocess call and the filesystem, then assert command construction,
validation, and error handling. No real ``kicad-cli`` binary, board, or
schematic is touched.

conftest.py pre-installs a MagicMock for ``pcbnew`` in sys.modules so
kicad_interface imports without a real KiCAD install.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.unit

from kicad_interface import KiCADInterface  # noqa: E402

# (handler suffix, minimal params) — correct output key per handler, schematicPath for sch tools
PCB_HANDLERS = [
    ("gerbers", {"outputDir": "/out"}),
    ("drill", {"outputDir": "/out"}),
    ("ipc2581", {"outputPath": "/out/x.xml"}),
    ("odb", {"outputPath": "/out/x.zip"}),
    ("ipcd356", {"outputPath": "/out/x.d356"}),
    ("gencad", {"outputPath": "/out/x.cad"}),
    ("pos", {"outputPath": "/out/x.pos"}),
    ("pcb_pdf", {"outputPath": "/out/x.pdf"}),
    ("pcb_svg", {"outputPath": "/out/x.svg"}),
    ("pcb_dxf", {"outputPath": "/out/x.dxf"}),
    ("gerber_single", {"outputPath": "/out/x.gbr", "layers": ["F.Cu"]}),
    ("3d_cli", {"outputPath": "/out/x.step", "format": "step"}),
]
SCH_HANDLERS = [
    ("sch_bom", {"outputPath": "/out/b.csv", "schematicPath": "/p/x.kicad_sch"}),
    ("sch_pdf", {"outputPath": "/out/b.pdf", "schematicPath": "/p/x.kicad_sch"}),
    ("sch_python_bom", {"outputPath": "/out/b.xml", "schematicPath": "/p/x.kicad_sch"}),
    ("sch_svg", {"outputDir": "/out", "schematicPath": "/p/x.kicad_sch"}),
    ("sch_dxf", {"outputDir": "/out", "schematicPath": "/p/x.kicad_sch"}),
    ("sch_hpgl", {"outputDir": "/out", "schematicPath": "/p/x.kicad_sch"}),
    ("sch_ps", {"outputDir": "/out", "schematicPath": "/p/x.kicad_sch"}),
]
ALL_HANDLERS = PCB_HANDLERS + SCH_HANDLERS


def _make_iface():
    """KiCADInterface instance with the cli/board-path helpers mocked."""
    iface = KiCADInterface.__new__(KiCADInterface)
    iface.board = None
    iface._find_kicad_cli_static = MagicMock(return_value="kicad-cli")
    iface._current_board_path = MagicMock(return_value="/proj/board.kicad_pcb")
    return iface


def _call(iface, suffix, params, rc=0, stderr=""):
    """Invoke a handler with subprocess + filesystem mocked. Returns (result, run_mock)."""
    method = getattr(iface, f"_handle_export_{suffix}")
    fake = SimpleNamespace(returncode=rc, stdout="", stderr=stderr)
    with (
        patch("subprocess.run", return_value=fake) as run,
        patch("os.path.exists", return_value=True),
        patch("os.makedirs"),
        patch("os.listdir", return_value=["a.out"]),
        patch("os.path.isfile", return_value=True),
    ):
        result = method(dict(params))
    return result, run


class TestAllHandlers:
    @pytest.mark.parametrize("suffix,params", ALL_HANDLERS)
    def test_success_invokes_kicad_cli(self, suffix, params):
        iface = _make_iface()
        result, run = _call(iface, suffix, params, rc=0)
        assert result["success"] is True, result
        run.assert_called_once()
        cmd = run.call_args.args[0]
        assert cmd[0] == "kicad-cli"
        assert cmd[1] in ("pcb", "sch")
        assert cmd[2] == "export"

    @pytest.mark.parametrize("suffix,params", ALL_HANDLERS)
    def test_cli_not_found(self, suffix, params):
        iface = _make_iface()
        iface._find_kicad_cli_static = MagicMock(return_value=None)
        result, _ = _call(iface, suffix, params)
        assert result["success"] is False
        assert "kicad-cli" in result["message"].lower()

    @pytest.mark.parametrize("suffix,params", ALL_HANDLERS)
    def test_subprocess_failure_propagates(self, suffix, params):
        iface = _make_iface()
        result, _ = _call(iface, suffix, params, rc=1, stderr="boom")
        assert result["success"] is False


class TestValidation:
    def test_missing_output_errors(self):
        iface = _make_iface()
        result, _ = _call(iface, "gerbers", {})
        assert result["success"] is False

    def test_pcb_no_board_resolvable_errors(self):
        iface = _make_iface()
        iface._current_board_path = MagicMock(return_value=None)
        result, _ = _call(iface, "ipc2581", {"outputPath": "/o/x.xml"})
        assert result["success"] is False

    def test_sch_missing_schematic_errors(self):
        iface = _make_iface()
        result, _ = _call(iface, "sch_bom", {"outputPath": "/o/b.csv"})
        assert result["success"] is False


class TestFlagConstruction:
    """Detailed flag mapping for the originally-authored handlers."""

    def test_gerbers_flags(self):
        iface = _make_iface()
        _, run = _call(
            iface,
            "gerbers",
            {
                "outputDir": "/out",
                "layers": ["F.Cu", "B.Cu"],
                "subtractSoldermask": True,
                "noX2": True,
                "precision": 5,
            },
        )
        cmd = run.call_args.args[0]
        assert "--subtract-soldermask" in cmd
        assert "--no-x2" in cmd
        assert "--layers" in cmd
        assert "F.Cu,B.Cu" in cmd
        assert cmd[cmd.index("--precision") + 1] == "5"

    def test_gerbers_omitted_flags_absent(self):
        iface = _make_iface()
        _, run = _call(iface, "gerbers", {"outputDir": "/out"})
        cmd = run.call_args.args[0]
        assert "--no-x2" not in cmd
        assert "--subtract-soldermask" not in cmd

    def test_drill_flags(self):
        iface = _make_iface()
        _, run = _call(
            iface,
            "drill",
            {
                "outputDir": "/out",
                "format": "gerber",
                "excellonSeparateTh": True,
                "generateMap": True,
            },
        )
        cmd = run.call_args.args[0]
        assert "--excellon-separate-th" in cmd
        assert "--generate-map" in cmd
        assert cmd[cmd.index("--format") + 1] == "gerber"

    def test_ipc2581_bom_column_mapping(self):
        iface = _make_iface()
        _, run = _call(
            iface,
            "ipc2581",
            {"outputPath": "/o/x.xml", "bomColIntId": "FAST P/N"},
        )
        cmd = run.call_args.args[0]
        assert cmd[cmd.index("--bom-col-int-id") + 1] == "FAST P/N"
