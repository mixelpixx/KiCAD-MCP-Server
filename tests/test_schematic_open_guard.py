"""Schematic edits are refused while KiCad has the schematic open (issue #472).

KiCad keeps its own copy of an open schematic and does not reload it when the
file changes on disk, so saving in KiCad silently overwrote what the schematic
tools wrote. KiCad 10's IPC API cannot reload a schematic, but it reports
which one is open.
"""

import os
import re
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import kicad_interface  # noqa: E402
from kicad_api.ipc_backend import IPCBackend  # noqa: E402
from kicad_interface import KiCADInterface, KiCADProcessManager  # noqa: E402

REPO = Path(__file__).parent.parent


def _open(name, path=""):
    return {"name": name, "path": path}


class _FakeIPCBackend:
    def __init__(self, open_schematics=(), connected=True):
        self.open_schematics = list(open_schematics)
        self.connected = connected

    def connect(self):
        self.connected = True
        return True

    def is_connected(self):
        return self.connected

    def get_open_schematics(self):
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
        name: handler
        for name in KiCADInterface._SCHEMATIC_MUTATING_COMMANDS | {"list_schematic_components"}
    }
    return iface


def _run(open_schematics, command, params):
    calls = []
    iface = _make_iface(_FakeIPCBackend(open_schematics), calls)
    result = iface.handle_command(command, params)
    return result, calls


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    (root / "sheets" / "power" / "rails").mkdir(parents=True)
    (root / "proj.kicad_pro").write_text("{}")
    (root / "proj.kicad_sch").write_text("(kicad_sch)")
    (root / "sheets" / "power.kicad_sch").write_text("(kicad_sch)")
    (root / "sheets" / "power" / "rails" / "ldo.kicad_sch").write_text("(kicad_sch)")
    return root


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(kicad_interface, "ALLOW_OPEN_SCHEMATIC_EDITS", False)
    monkeypatch.setattr(kicad_interface.interactive_schematic, "INTERACTIVE_SCHEMATIC", False)
    monkeypatch.setattr(KiCADProcessManager, "is_running", staticmethod(lambda: False))


# --- refusing and allowing ------------------------------------------------- #


def test_edit_refused_while_schematic_open(project):
    result, calls = _run(
        [_open("proj.kicad_sch")],
        "add_schematic_wire",
        {"schematicPath": str(project / "proj.kicad_sch")},
    )

    assert result["success"] is False
    assert result["schematicOpenInKicad"] is True
    assert "KICAD_ALLOW_OPEN_SCHEMATIC_EDITS" in result["errorDetails"]
    assert calls == []


@pytest.mark.parametrize("sheet", ["sheets/power.kicad_sch", "sheets/power/rails/ldo.kicad_sch"])
def test_sub_sheet_edit_refused_while_project_open(project, sheet):
    result, calls = _run(
        [_open("proj.kicad_sch")], "add_schematic_wire", {"schematicPath": str(project / sheet)}
    )

    assert result["success"] is False
    assert calls == []


def test_parent_schematic_param_is_checked(project):
    result, calls = _run(
        [_open("proj.kicad_sch")],
        "create_hierarchical_subsheet",
        {"parentSchematicPath": str(project / "proj.kicad_sch")},
    )

    assert result["success"] is False
    assert calls == []


def test_edit_allowed_when_another_schematic_is_open(project):
    result, calls = _run(
        [_open("other.kicad_sch")],
        "add_schematic_wire",
        {"schematicPath": str(project / "proj.kicad_sch")},
    )

    assert result["success"] is True
    assert len(calls) == 1


def test_read_allowed_while_schematic_open(project):
    result, calls = _run(
        [_open("proj.kicad_sch")],
        "list_schematic_components",
        {"schematicPath": str(project / "proj.kicad_sch")},
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

    result, calls = _run(
        [_open("proj.kicad_sch")],
        "add_schematic_wire",
        {"schematicPath": str(project / "proj.kicad_sch")},
    )

    assert result["success"] is True
    assert len(calls) == 1


def test_guard_runs_for_swig_sessions(project, monkeypatch):
    """SWIG users write to disk, so they need the guard most."""
    monkeypatch.setattr(kicad_interface, "KICAD_BACKEND", "swig")
    monkeypatch.setattr(KiCADProcessManager, "is_running", staticmethod(lambda: True))
    probe = _FakeIPCBackend([_open("proj.kicad_sch")], connected=False)
    monkeypatch.setattr("kicad_api.ipc_backend.IPCBackend", lambda: probe)
    calls = []
    iface = _make_iface(None, calls)

    result = iface.handle_command(
        "add_schematic_wire", {"schematicPath": str(project / "proj.kicad_sch")}
    )

    assert result["success"] is False
    assert calls == []


# --- matching by project path ---------------------------------------------- #


def test_full_path_match_refuses(project):
    result, _ = _run(
        [_open("proj.kicad_sch", str(project / "proj.kicad_sch"))],
        "add_schematic_wire",
        {"schematicPath": str(project / "sheets" / "power.kicad_sch")},
    )

    assert result["success"] is False


def test_same_named_project_elsewhere_is_not_refused(project, tmp_path):
    other = tmp_path / "copy" / "proj.kicad_sch"

    result, calls = _run(
        [_open("proj.kicad_sch", str(other))],
        "add_schematic_wire",
        {"schematicPath": str(project / "proj.kicad_sch")},
    )

    assert result["success"] is True
    assert len(calls) == 1


# --- commands that write only for some parameters --------------------------- #


@pytest.mark.parametrize(
    "command, params, refused",
    [
        ("lint_offgrid", {}, False),
        ("lint_offgrid", {"fix": True}, True),
        ("lint_schematic_cosmetic", {}, True),
        ("lint_schematic_cosmetic", {"dryRun": True}, False),
        ("suggest_schematic_declutter", {}, False),
        ("suggest_schematic_declutter", {"apply": True}, True),
        ("backannotate_footprints", {}, True),
        ("backannotate_footprints", {"dryRun": True}, False),
    ],
)
def test_conditional_writers(project, command, params, refused):
    params = {"schematicPath": str(project / "proj.kicad_sch"), **params}

    result, calls = _run([_open("proj.kicad_sch")], command, params)

    assert (result["success"] is False) is refused
    assert len(calls) == (0 if refused else 1)


@pytest.mark.parametrize("params, refused", [({}, True), ({"dry_run": True}, False)])
def test_enrich_datasheets_preview_allowed(project, params, refused):
    params = {"schematic_path": str(project / "proj.kicad_sch"), **params}

    result, calls = _run([_open("proj.kicad_sch")], "enrich_datasheets", params)

    assert (result["success"] is False) is refused
    assert len(calls) == (0 if refused else 1)


def test_backannotate_with_only_the_board_checks_its_schematic(project):
    result, calls = _run(
        [_open("proj.kicad_sch")],
        "backannotate_footprints",
        {"boardPath": str(project / "proj.kicad_pcb")},
    )

    assert result["success"] is False
    assert calls == []


@pytest.mark.parametrize(
    "name, params, refused",
    [
        ("proj.kicad_sch", {}, False),
        ("proj.kicad_sch", {"dryRun": False}, True),
        ("lib.kicad_sym", {"dryRun": False}, False),
    ],
)
def test_repair_flat_symbols_on_open_schematic(project, name, params, refused):
    (project / "lib.kicad_sym").write_text("(kicad_symbol_lib)")

    result, _ = _run(
        [_open("proj.kicad_sch")],
        "repair_flat_symbols",
        {"path": str(project / name), **params},
    )

    assert (result["success"] is False) is refused


@pytest.mark.parametrize("key", ["schematicPaths", "projectsDir"])
def test_update_symbol_from_library_checks_every_schematic(project, tmp_path, key):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "unrelated.kicad_sch").write_text("(kicad_sch)")
    if key == "schematicPaths":
        params = {key: [str(unrelated / "unrelated.kicad_sch"), str(project / "proj.kicad_sch")]}
    else:
        params = {key: str(tmp_path)}

    result, calls = _run([_open("proj.kicad_sch")], "update_symbol_from_library", params)

    assert result["success"] is False
    assert calls == []


@pytest.mark.parametrize("exists", [True, False])
def test_create_schematic_over_an_open_file(project, exists):
    name = "proj" if exists else "new"

    result, _ = _run(
        [_open("proj.kicad_sch")], "create_schematic", {"name": name, "path": str(project)}
    )

    assert (result["success"] is False) is exists


@pytest.mark.parametrize("name, refused", [("proj", True), ("new", False)])
def test_create_project_over_an_open_schematic(project, name, refused):
    _, calls = _run(
        [_open("proj.kicad_sch")], "create_project", {"name": name, "path": str(project)}
    )

    assert len(calls) == (0 if refused else 1)


# --- keeping the list current ---------------------------------------------- #

# Schematic tools that are not read-only but never write a .kicad_sch.
_NOT_SCHEMATIC_WRITERS = {
    "sync_schematic_to_board": "writes the board",
    "create_board_from_schematic": "writes the board",
    "set_symbol_pin_type": "writes a .kicad_sym library",
}


def _ts_set(source, name):
    body = source[source.index(f"export const {name}") :]
    return set(re.findall(r'"([a-z_0-9]+)"', body[: body.index("]);")]))


def test_every_schematic_writer_is_guarded():
    """Every schematic tool that READ_ONLY_TOOLS does not cover is guarded or exempted."""
    tools = REPO / "src" / "tools"
    modes = (tools / "operating-mode.ts").read_text(encoding="utf-8")
    read_only = _ts_set(modes, "READ_ONLY_TOOLS") | _ts_set(modes, "EXPORT_TOOLS")
    files = [
        *sorted(tools.glob("schematic*.ts")),
        tools / "datasheet.ts",
        tools / "library-symbol.ts",
    ]
    registered = set()
    for f in files:
        registered |= set(
            re.findall(r'server\.(?:tool|registerTool)\(\s*"([a-z_0-9]+)"', f.read_text())
        )

    unguarded = (
        registered
        - read_only
        - KiCADInterface._SCHEMATIC_MUTATING_COMMANDS
        - set(_NOT_SCHEMATIC_WRITERS)
    )

    assert unguarded == set()


def test_guarded_commands_exist():
    source = Path(kicad_interface.__file__).read_text(encoding="utf-8")
    start = source.index("self.command_routes = {")
    block = source[start : source.index("\n        }\n", start)]
    routes = set(re.findall(r'^\s+"([a-z_0-9]+)":', block, re.M))

    assert KiCADInterface._SCHEMATIC_MUTATING_COMMANDS <= routes
    assert set(KiCADInterface._SCHEMATIC_WRITE_CONDITIONS) <= (
        KiCADInterface._SCHEMATIC_MUTATING_COMMANDS
    )


# --- IPCBackend.get_open_schematics ---------------------------------------- #

DOCTYPE_SCHEMATIC = 1


class _FakeDoc:
    def __init__(self, board_filename, project_path):
        self.board_filename = board_filename
        self.project = types.SimpleNamespace(path=project_path)


class _FakeKiCad:
    def __init__(self, docs):
        self.docs = docs
        self.requested = []

    def ping(self):
        return None

    def get_open_documents(self, doc_type):
        self.requested.append(doc_type)
        return list(self.docs)


def _backend_with(monkeypatch, docs):
    types_mod = types.ModuleType("kipy.proto.common.types")
    types_mod.DocumentType = types.SimpleNamespace(DOCTYPE_SCHEMATIC=DOCTYPE_SCHEMATIC)
    for name, mod in (
        ("kipy", types.ModuleType("kipy")),
        ("kipy.proto", types.ModuleType("kipy.proto")),
        ("kipy.proto.common", types.ModuleType("kipy.proto.common")),
        ("kipy.proto.common.types", types_mod),
    ):
        monkeypatch.setitem(sys.modules, name, mod)
    backend = IPCBackend()
    backend._kicad = _FakeKiCad(docs)
    backend._connected = True
    return backend


def test_get_open_schematics_without_project_path(monkeypatch):
    """KiCad 10.0.7 reports only the file name for an open schematic."""
    backend = _backend_with(monkeypatch, [_FakeDoc("proj.kicad_sch", "")])

    assert backend.get_open_schematics() == [_open("proj.kicad_sch")]
    assert backend._kicad.requested == [DOCTYPE_SCHEMATIC]


def test_get_open_schematics_with_project_path(monkeypatch):
    project_dir = os.path.join("home", "u", "proj")
    backend = _backend_with(monkeypatch, [_FakeDoc("proj.kicad_sch", project_dir)])

    assert backend.get_open_schematics() == [
        _open("proj.kicad_sch", os.path.join(project_dir, "proj.kicad_sch"))
    ]


def test_get_open_schematics_skips_other_documents(monkeypatch):
    backend = _backend_with(monkeypatch, [_FakeDoc("", ""), _FakeDoc("proj.kicad_pcb", "/p")])

    assert backend.get_open_schematics() == []


def test_get_open_schematics_when_disconnected():
    backend = IPCBackend()

    assert backend.get_open_schematics() == []
