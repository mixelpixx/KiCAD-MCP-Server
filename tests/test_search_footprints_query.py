"""search_footprints reads the ``query`` its JSON-RPC schema declares (#407).

``tool_schemas.py`` declares a required ``query``, but the handler read only
``pattern`` (sent by the Node tool) and ``search_term``. A JSON-RPC client that
followed the schema searched for ``*`` and got the first 20 footprints of the
first libraries, whatever it asked for.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
from commands.library import LibraryCommands, LibraryManager  # noqa: E402

pytestmark = pytest.mark.unit

NAMES = ["R_0603_1608Metric", "R_0805_2012Metric", "C_0603_1608Metric"]


def _commands(tmp_path: Path) -> LibraryCommands:
    mgr = LibraryManager.__new__(LibraryManager)
    mgr.project_path = None
    mgr.footprint_cache = {}
    lib = tmp_path / "Passives.pretty"
    lib.mkdir()
    for name in NAMES:
        (lib / f"{name}.kicad_mod").write_text("(footprint)")
    mgr.libraries = {"Passives": str(lib)}
    return LibraryCommands(mgr)


def _found(result: dict) -> list:
    assert result["success"], result
    return sorted(fp["footprint"] for fp in result["footprints"])


def test_query_is_read(tmp_path: Path) -> None:
    result = _commands(tmp_path).search_footprints({"query": "0805"})
    assert _found(result) == ["R_0805_2012Metric"]
    assert result["pattern"] == "0805"


def test_query_with_library(tmp_path: Path) -> None:
    result = _commands(tmp_path).search_footprints({"query": "0603", "library": "passives"})
    assert _found(result) == ["C_0603_1608Metric", "R_0603_1608Metric"]


@pytest.mark.parametrize("key", ["pattern", "search_term"])
def test_older_keys_still_work(tmp_path: Path, key: str) -> None:
    assert _found(_commands(tmp_path).search_footprints({key: "C_*"})) == ["C_0603_1608Metric"]


def test_pattern_wins_over_query(tmp_path: Path) -> None:
    # The Node tool sends "pattern"; a stray "query" must not change its search.
    result = _commands(tmp_path).search_footprints({"pattern": "0805", "query": "C_"})
    assert _found(result) == ["R_0805_2012Metric"]


def test_no_pattern_still_lists_everything(tmp_path: Path) -> None:
    assert _found(_commands(tmp_path).search_footprints({})) == sorted(NAMES)
