"""get_footprint_info reads the library and footprint both schemas declare (#407).

The zod schema sends ``library_name`` and ``footprint_name``; the JSON-RPC
schema declares ``library`` and ``footprint``. The handler read only
``footprint_name``, so:

* the library was ignored: a name that exists in two libraries came back
  from whichever library was listed first;
* a JSON-RPC client always got "Missing footprint parameter";
* an unknown footprint failed with a Python NameError instead of saying it
  was not found.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
from commands.library import LibraryCommands, LibraryManager  # noqa: E402

pytestmark = pytest.mark.unit

FOOTPRINT = """(footprint "{name}"
  (descr "{descr}")
  (pad "1" smd rect (at -0.8 0) (size 0.9 0.9) (layers "F.Cu"))
  (pad "2" smd rect (at 0.8 0) (size 0.9 0.9) (layers "F.Cu"))
)
"""


def _commands(tmp_path: Path) -> LibraryCommands:
    mgr = LibraryManager.__new__(LibraryManager)
    mgr.project_path = None
    mgr.footprint_cache = {}
    mgr.libraries = {}
    # The same footprint name in two libraries, told apart by its description.
    for nickname in ("Stock", "Custom"):
        lib = tmp_path / f"{nickname}.pretty"
        lib.mkdir()
        (lib / "R_0603.kicad_mod").write_text(
            FOOTPRINT.format(name="R_0603", descr=f"{nickname} 0603")
        )
        mgr.libraries[nickname] = str(lib)
    return LibraryCommands(mgr)


def _info(tmp_path: Path, **params) -> dict:
    result = _commands(tmp_path).get_footprint_info(params)
    assert result["success"], result
    return result["info"]


def test_zod_library_name_picks_the_library(tmp_path: Path) -> None:
    info = _info(tmp_path, library_name="Custom", footprint_name="R_0603")
    assert info["library"] == "Custom"
    assert info["full_name"] == "Custom:R_0603"


def test_jsonrpc_library_and_footprint_are_read(tmp_path: Path) -> None:
    info = _info(tmp_path, library="Custom", footprint="R_0603")
    assert info["full_name"] == "Custom:R_0603"


def test_full_name_in_footprint_still_works(tmp_path: Path) -> None:
    assert _info(tmp_path, footprint_name="Custom:R_0603")["library"] == "Custom"


def test_footprint_alone_still_searches_all_libraries(tmp_path: Path) -> None:
    assert _info(tmp_path, footprint_name="R_0603")["library"] == "Stock"


def test_conflicting_library_is_refused(tmp_path: Path) -> None:
    result = _commands(tmp_path).get_footprint_info(
        {"library_name": "Stock", "footprint_name": "Custom:R_0603"}
    )
    assert result["success"] is False
    assert "Stock" in result["message"] and "Custom" in result["message"]


def test_missing_footprint_is_reported(tmp_path: Path) -> None:
    result = _commands(tmp_path).get_footprint_info({"library_name": "Stock"})
    assert result["success"] is False
    assert result["message"] == "Missing footprint parameter"


@pytest.mark.parametrize(
    "params, expected",
    [
        ({"library_name": "Stock", "footprint_name": "R_9999"}, "Stock:R_9999"),
        ({"footprint_name": "R_9999"}, "R_9999"),
        ({"library_name": "NoSuchLib", "footprint_name": "R_0603"}, "NoSuchLib:R_0603"),
    ],
)
def test_unknown_footprint_says_not_found(tmp_path: Path, params: dict, expected: str) -> None:
    result = _commands(tmp_path).get_footprint_info(params)
    assert result["success"] is False
    assert result["message"] == f"Footprint not found: {expected}"
