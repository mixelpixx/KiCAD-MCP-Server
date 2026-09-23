"""IPC place_component on KiCad 10 / kipy 0.7+ (takes over the fixes in #378).

Two calls in the IPC placement path no longer exist in the form the code used:

* ``pcbnew.GetGlobalFootprintLib()`` is gone in KiCad 10 (checked against the
  KiCad 10.0.5 pcbnew module), so ``_load_footprint_from_library`` raised
  AttributeError on every call, logged it, and returned None.
* ``KiCad.get_open_documents()`` requires a document type (kicad-python 0.7.1
  signature ``get_open_documents(self, doc_type)``), so the board path lookup in
  ``_place_loaded_footprint`` raised TypeError, fell through to
  ``pcbnew.GetBoard()`` (None outside KiCad's process), and gave up.

Either way place_component ended in the placeholder path instead of placing the
library footprint. These tests run without KiCad: the pcbnew stub refuses
GetGlobalFootprintLib the way KiCad 10 does, and the fake kipy board exposes the
same ``name`` / ``get_project().path`` a real kipy Board does.
"""

import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import kicad_api.ipc_backend as ipc_backend  # noqa: E402
from kicad_api.ipc_backend import IPCBoardAPI  # noqa: E402

pytestmark = pytest.mark.unit


def _board(name="demo.kicad_pcb", project_path="/projects/demo"):
    board = MagicMock(name="kipy.Board")
    board.name = name
    board.get_project.return_value = SimpleNamespace(path=project_path)
    return board


def _api(board):
    kicad = MagicMock(name="kipy.KiCad")
    kicad.get_open_documents.side_effect = TypeError(
        "get_open_documents() missing 1 required positional argument: 'doc_type'"
    )
    api = IPCBoardAPI(kicad, notify_callback=MagicMock())
    api._board = board
    return api


@pytest.fixture()
def pcbnew_kicad10(monkeypatch):
    """The session pcbnew stub, reshaped like KiCad 10 for one test."""
    stub = sys.modules["pcbnew"]
    monkeypatch.setattr(
        stub,
        "GetGlobalFootprintLib",
        MagicMock(side_effect=AttributeError("module 'pcbnew' has no attribute")),
    )
    monkeypatch.setattr(stub, "FootprintLoad", MagicMock(name="FootprintLoad"))
    monkeypatch.setattr(stub, "LoadBoard", MagicMock(name="LoadBoard"))
    monkeypatch.setattr(stub, "SaveBoard", MagicMock(name="SaveBoard"))
    monkeypatch.setattr(stub, "GetBoard", MagicMock(return_value=None))
    return stub


class _FakeLibraryManager:
    instances: list = []

    def __init__(self, project_path=None):
        self.project_path = project_path
        _FakeLibraryManager.instances.append(self)

    def find_footprint(self, spec):
        return {
            "Resistor_SMD:R_0603_1608Metric": ("/libs/Resistor_SMD.pretty", "R_0603_1608Metric"),
            "R_0603_1608Metric": ("/libs/Resistor_SMD.pretty", "R_0603_1608Metric"),
        }.get(spec)


@pytest.fixture()
def fake_libraries(monkeypatch):
    import commands.library

    _FakeLibraryManager.instances = []
    monkeypatch.setattr(commands.library, "LibraryManager", _FakeLibraryManager)
    return _FakeLibraryManager


class TestBoardFilePath:
    def test_composes_project_directory_and_board_name(self):
        api = _api(_board("demo.kicad_pcb", "/projects/demo"))
        assert Path(api._board_file_path()) == Path("/projects/demo/demo.kicad_pcb")

    def test_board_name_alone_when_there_is_no_project_path(self):
        api = _api(_board("demo.kicad_pcb", ""))
        assert api._board_file_path() == "demo.kicad_pcb"

    def test_none_when_no_board_is_open(self):
        api = _api(None)
        api._board = None
        api._kicad.get_board.side_effect = RuntimeError("no board open")
        assert api._board_file_path() is None


class TestLoadFootprintFromLibrary:
    @pytest.mark.parametrize("spec", ["Resistor_SMD:R_0603_1608Metric", "R_0603_1608Metric"])
    def test_loads_through_the_library_tables_not_the_removed_global_lib(
        self, pcbnew_kicad10, fake_libraries, spec
    ):
        sentinel = object()
        pcbnew_kicad10.FootprintLoad.return_value = sentinel
        api = _api(_board("demo.kicad_pcb", "/projects/demo"))

        assert api._load_footprint_from_library(spec) is sentinel
        pcbnew_kicad10.FootprintLoad.assert_called_once_with(
            "/libs/Resistor_SMD.pretty", "R_0603_1608Metric"
        )
        pcbnew_kicad10.GetGlobalFootprintLib.assert_not_called()
        # the bound project's own fp-lib-table takes part in the lookup
        assert fake_libraries.instances[-1].project_path == Path("/projects/demo")

    def test_unknown_footprint_returns_none_without_loading(self, pcbnew_kicad10, fake_libraries):
        api = _api(_board())
        assert api._load_footprint_from_library("Nope:Missing") is None
        pcbnew_kicad10.FootprintLoad.assert_not_called()


class TestPlaceLoadedFootprint:
    def test_loads_and_saves_the_bound_board_file(self, pcbnew_kicad10, monkeypatch, tmp_path):
        board_file = tmp_path / "demo.kicad_pcb"
        board_file.write_text("(kicad_pcb)")
        board = _board("demo.kicad_pcb", str(tmp_path))
        api = _api(board)
        monkeypatch.setattr(ipc_backend, "preserve_project_settings", lambda path: nullcontext())
        pcb = MagicMock(name="pcbnew.BOARD")
        pcbnew_kicad10.LoadBoard.return_value = pcb
        footprint = MagicMock(name="FOOTPRINT")
        footprint.IsFlipped.return_value = False

        placed = api._place_loaded_footprint(footprint, "R1", 10.0, 20.0, 90.0, "F.Cu", "10k")

        assert placed is True
        pcbnew_kicad10.LoadBoard.assert_called_once_with(str(board_file))
        pcb.Add.assert_called_once_with(footprint)
        pcbnew_kicad10.SaveBoard.assert_called_once_with(str(board_file), pcb)
        # the path came from the bound board, not the typeless document listing
        api._kicad.get_open_documents.assert_not_called()
