"""Schematic edits are refused while KiCad has the schematic open (issue #472).

KiCad keeps its own copy of an open schematic and does not reload it when the
file changes on disk, so saving in KiCad silently overwrote what the schematic
tools wrote. KiCad 10's IPC API cannot reload a schematic, but it reports
which one is open.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import kicad_interface  # noqa: E402
from kicad_interface import KiCADInterface, KiCADProcessManager  # noqa: E402


class _FakeIPCBackend:
    def __init__(self, open_schematics=(), connected=True):
        self.open_schematics = list(open_schematics)
        self.connected = connected

    def is_connected(self):
        return self.connected

    def get_open_schematic_names(self):
        return list(self.open_schematics)


def _make_iface(ipc_backend, calls):
    iface = KiCADInterface.__new__(KiCADInterface)
    iface.use_ipc = False
    iface.ipc_backend = ipc_backend
    iface.ipc_board_api = None
    iface.board = None
    iface.session_backend = None
    iface.session_board_path = None
    iface._last_auto_save_status = None

    def handler(params):
        calls.append(params)
        return {"success": True}

    iface.command_routes = {
        "add_schematic_wire": handler,
        "create_hierarchical_subsheet": handler,
        "list_schematic_components": handler,
    }
    return iface


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    (root / "sheets").mkdir(parents=True)
    (root / "proj.kicad_pro").write_text("{}")
    (root / "proj.kicad_sch").write_text("(kicad_sch)")
    (root / "sheets" / "power.kicad_sch").write_text("(kicad_sch)")
    return root


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(kicad_interface, "ALLOW_OPEN_SCHEMATIC_EDITS", False)
    monkeypatch.setattr(kicad_interface.interactive_schematic, "INTERACTIVE_SCHEMATIC", False)
    monkeypatch.setattr(KiCADProcessManager, "is_running", staticmethod(lambda: False))


def test_edit_refused_while_schematic_open(project):
    calls = []
    iface = _make_iface(_FakeIPCBackend(["proj.kicad_sch"]), calls)

    result = iface.handle_command(
        "add_schematic_wire", {"schematicPath": str(project / "proj.kicad_sch")}
    )

    assert result["success"] is False
    assert result["schematicOpenInKicad"] is True
    assert "KICAD_ALLOW_OPEN_SCHEMATIC_EDITS" in result["errorDetails"]
    assert calls == []


def test_sub_sheet_edit_refused_while_project_open(project):
    calls = []
    iface = _make_iface(_FakeIPCBackend(["proj.kicad_sch"]), calls)

    result = iface.handle_command(
        "add_schematic_wire", {"schematicPath": str(project / "sheets" / "power.kicad_sch")}
    )

    assert result["success"] is False
    assert calls == []


def test_parent_schematic_param_is_checked(project):
    calls = []
    iface = _make_iface(_FakeIPCBackend(["proj.kicad_sch"]), calls)

    result = iface.handle_command(
        "create_hierarchical_subsheet",
        {"parentSchematicPath": str(project / "proj.kicad_sch")},
    )

    assert result["success"] is False
    assert calls == []


def test_edit_allowed_when_another_schematic_is_open(project):
    calls = []
    iface = _make_iface(_FakeIPCBackend(["other.kicad_sch"]), calls)

    result = iface.handle_command(
        "add_schematic_wire", {"schematicPath": str(project / "proj.kicad_sch")}
    )

    assert result["success"] is True
    assert len(calls) == 1


def test_read_allowed_while_schematic_open(project):
    calls = []
    iface = _make_iface(_FakeIPCBackend(["proj.kicad_sch"]), calls)

    result = iface.handle_command(
        "list_schematic_components", {"schematicPath": str(project / "proj.kicad_sch")}
    )

    assert result["success"] is True
    assert len(calls) == 1


def test_edit_allowed_without_kicad(project):
    calls = []
    iface = _make_iface(None, calls)

    result = iface.handle_command(
        "add_schematic_wire", {"schematicPath": str(project / "proj.kicad_sch")}
    )

    assert result["success"] is True
    assert len(calls) == 1


@pytest.mark.parametrize(
    "setting",
    [
        (kicad_interface, "ALLOW_OPEN_SCHEMATIC_EDITS"),
        (kicad_interface.interactive_schematic, "INTERACTIVE_SCHEMATIC"),
    ],
)
def test_edit_allowed_when_opted_out(project, monkeypatch, setting):
    monkeypatch.setattr(*setting, True)
    calls = []
    iface = _make_iface(_FakeIPCBackend(["proj.kicad_sch"]), calls)

    result = iface.handle_command(
        "add_schematic_wire", {"schematicPath": str(project / "proj.kicad_sch")}
    )

    assert result["success"] is True
    assert len(calls) == 1


def test_guarded_commands_exist():
    source = Path(kicad_interface.__file__).read_text(encoding="utf-8")
    start = source.index("self.command_routes = {")
    block = source[start : source.index("\n        }\n", start)]
    routes = set(re.findall(r'^\s+"([a-z_0-9]+)":', block, re.M))

    assert KiCADInterface._SCHEMATIC_MUTATING_COMMANDS <= routes
