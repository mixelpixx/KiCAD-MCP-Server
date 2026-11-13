"""search_footprints with a library filter.

The filter used to be applied after an all-library scan capped at limit * 10
matches, so a library listed late in the table returned nothing whenever
earlier libraries already had enough matches.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
from commands.library import LibraryCommands, LibraryManager  # noqa: E402

pytestmark = pytest.mark.unit


def _manager(tmp_path: Path, n_early: int) -> LibraryManager:
    """A manager whose table holds n_early libraries full of matches, then "JLC"."""
    mgr = LibraryManager.__new__(LibraryManager)
    mgr.project_path = None
    mgr.footprint_cache = {}
    mgr.libraries = {}
    for i in range(n_early):
        lib = tmp_path / f"Stock{i}.pretty"
        lib.mkdir()
        for j in range(5):
            (lib / f"QFN-16_stock{i}_{j}.kicad_mod").write_text("(footprint)")
        mgr.libraries[f"Stock{i}"] = str(lib)
    jlc = tmp_path / "JLC.pretty"
    jlc.mkdir()
    (jlc / "QFN-16_L3.0-W3.0-P0.50-BL-EP1.7.kicad_mod").write_text("(footprint)")
    mgr.libraries["JLC"] = str(jlc)
    return mgr


def test_library_filter_finds_match_in_last_library(tmp_path: Path) -> None:
    """250 earlier matches must not hide the one in the requested library."""
    cmds = LibraryCommands(_manager(tmp_path, n_early=50))
    result = cmds.search_footprints({"search_term": "QFN-16", "library": "JLC", "limit": 5})
    assert result["success"]
    assert [r["full_name"] for r in result["footprints"]] == ["JLC:QFN-16_L3.0-W3.0-P0.50-BL-EP1.7"]


def test_library_filter_is_case_insensitive(tmp_path: Path) -> None:
    cmds = LibraryCommands(_manager(tmp_path, n_early=2))
    result = cmds.search_footprints({"search_term": "QFN-16", "library": "jlc"})
    assert result["count"] == 1


def test_library_filter_respects_limit(tmp_path: Path) -> None:
    cmds = LibraryCommands(_manager(tmp_path, n_early=2))
    result = cmds.search_footprints({"search_term": "QFN-16", "library": "Stock1", "limit": 3})
    assert result["count"] == 3
    assert all(r["library"] == "Stock1" for r in result["footprints"])


def test_unknown_library_returns_no_matches(tmp_path: Path) -> None:
    cmds = LibraryCommands(_manager(tmp_path, n_early=2))
    result = cmds.search_footprints({"search_term": "QFN-16", "library": "NoSuchLib"})
    assert result["success"]
    assert result["count"] == 0


def test_no_filter_still_searches_all_libraries(tmp_path: Path) -> None:
    cmds = LibraryCommands(_manager(tmp_path, n_early=2))
    result = cmds.search_footprints({"search_term": "QFN-16", "limit": 100})
    assert result["count"] == 11
