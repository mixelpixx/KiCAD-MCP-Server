"""list_library_footprints honours the filter and limit its schema declares (#407).

The zod schema advertised ``filter`` and ``limit`` but the handler read
neither, so a client asking for the first 10 QFN footprints of a library got
the whole library back.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
from commands.library import LibraryCommands, LibraryManager  # noqa: E402

pytestmark = pytest.mark.unit

NAMES = [
    "QFN-16_3x3mm_P0.5mm",
    "QFN-20_4x4mm_P0.5mm",
    "QFN-32_5x5mm_P0.5mm",
    "SOIC-8_3.9x4.9mm_P1.27mm",
    "SOIC-14_3.9x8.7mm_P1.27mm",
    "TSSOP-20_4.4x6.5mm_P0.65mm",
]


def _commands(tmp_path: Path) -> LibraryCommands:
    mgr = LibraryManager.__new__(LibraryManager)
    mgr.project_path = None
    mgr.footprint_cache = {}
    lib = tmp_path / "Package.pretty"
    lib.mkdir()
    for name in NAMES:
        (lib / f"{name}.kicad_mod").write_text("(footprint)")
    mgr.libraries = {"Package": str(lib)}
    return LibraryCommands(mgr)


def _list(tmp_path: Path, **params):
    return _commands(tmp_path).list_library_footprints({"library_name": "Package", **params})


def test_no_filter_or_limit_lists_the_whole_library(tmp_path: Path) -> None:
    result = _list(tmp_path)
    assert result["success"]
    assert sorted(result["footprints"]) == sorted(NAMES)
    assert result["count"] == result["total"] == len(NAMES)


def test_filter_is_a_case_insensitive_substring(tmp_path: Path) -> None:
    result = _list(tmp_path, filter="soic")
    assert sorted(result["footprints"]) == ["SOIC-14_3.9x8.7mm_P1.27mm", "SOIC-8_3.9x4.9mm_P1.27mm"]
    assert result["count"] == result["total"] == 2


def test_filter_accepts_a_star_wildcard(tmp_path: Path) -> None:
    result = _list(tmp_path, filter="QFN*P0.5")
    assert result["count"] == 3


def test_filter_treats_other_characters_literally(tmp_path: Path) -> None:
    # "." is not "any character" and an unbalanced "(" is not a regex error.
    cmds = _commands(tmp_path)

    def count(pattern: str) -> int:
        result = cmds.list_library_footprints({"library_name": "Package", "filter": pattern})
        assert result["success"]
        return result["count"]

    assert count("3.9x4.9") == 1
    assert count("16.3") == 0  # as a regex, "." would match the "_" in QFN-16_3x3mm
    assert count("QFN(") == 0


def test_limit_caps_the_list_and_reports_the_total(tmp_path: Path) -> None:
    result = _list(tmp_path, limit=2)
    assert result["success"]
    assert result["count"] == 2
    assert result["total"] == len(NAMES)
    assert result["footprints"] == sorted(NAMES)[:2]


def test_filter_applies_before_limit(tmp_path: Path) -> None:
    result = _list(tmp_path, filter="QFN", limit=2)
    assert result["footprints"] == ["QFN-16_3x3mm_P0.5mm", "QFN-20_4x4mm_P0.5mm"]
    assert (result["count"], result["total"]) == (2, 3)


@pytest.mark.parametrize("bad", [0, -1, 2.5, "10", True])
def test_limit_must_be_a_positive_integer(tmp_path: Path, bad) -> None:
    result = _list(tmp_path, limit=bad)
    assert result["success"] is False
    assert "limit" in result["message"]


def test_library_parameter_still_works(tmp_path: Path) -> None:
    result = _commands(tmp_path).list_library_footprints({"library": "Package", "limit": 1})
    assert result["count"] == 1
