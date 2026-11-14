"""search_footprints and list_library_footprints read a pattern the same way.

Both document "substring, case-insensitive, ``*`` as a wildcard". Only
list_library_footprints escaped the rest of the pattern (#545), so
search_footprints read it as a regex: ``3x14+6`` meant "one or more 4" and
found nothing, and ``(`` raised "missing ), unterminated subpattern".
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
from commands.library import (  # noqa: E402
    LibraryCommands,
    LibraryManager,
    footprint_name_pattern,
)

pytestmark = pytest.mark.unit

# Names from KiCad's Connector_DIN library: five 3x14+6 footprints and two
# others that a regex reading of the pattern would or would not match.
DIN = [
    "DIN41612_B_3x14+6_Female_Horizontal_THT",
    "DIN41612_B_3x14+6_Female_Vertical_THT",
    "DIN41612_B_3x14+6_Male_Horizontal_THT",
    "DIN41612_B_3x14+6_Male_Vertical_THT",
    "DIN41612_B_3x14+6_Male_Vertical_THT_PressFit",
    "DIN41612_B_3x16_Male_Vertical_THT",
    "DIN41612_C_3x32_Female_Horizontal_THT",
]
QFN = ["QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm", "QFN-16-1EP_3x3mm_P0_5mm"]


def _manager(tmp_path: Path) -> LibraryManager:
    mgr = LibraryManager.__new__(LibraryManager)
    mgr.project_path = None
    mgr.footprint_cache = {}
    mgr.libraries = {}
    for nickname, names in (("Connector_DIN", DIN), ("Package_DFN_QFN", QFN)):
        lib = tmp_path / f"{nickname}.pretty"
        lib.mkdir()
        for name in names:
            (lib / f"{name}.kicad_mod").write_text("(footprint)")
        mgr.libraries[nickname] = str(lib)
    return mgr


def _search(mgr: LibraryManager, pattern: str, library=None) -> list:
    result = LibraryCommands(mgr).search_footprints(
        {"pattern": pattern, "library": library, "limit": 100}
    )
    assert result["success"], result
    return sorted(fp["footprint"] for fp in result["footprints"])


def _listed(mgr: LibraryManager, library: str, pattern: str) -> list:
    result = LibraryCommands(mgr).list_library_footprints(
        {"library_name": library, "filter": pattern}
    )
    assert result["success"], result
    return sorted(result["footprints"])


@pytest.mark.parametrize(
    "pattern, matches",
    [
        ("3x14+6", True),
        ("3X14+6", True),  # case-insensitive
        ("3x14*Male", True),  # * spans any run of characters
        ("3x144+6", False),  # + is literal, not "one or more 4"
        ("(", False),  # not a regex error
        ("P0.5", False),  # . is literal, so it doesn't match "P0_5"
    ],
)
def test_footprint_name_pattern(pattern: str, matches: bool) -> None:
    name = "DIN41612_B_3x14+6_Male_Vertical_THT_P0_5"
    assert (footprint_name_pattern(pattern).search(name) is not None) is matches


def test_search_plus_is_literal(tmp_path: Path) -> None:
    assert _search(_manager(tmp_path), "3x14+6", "Connector_DIN") == sorted(DIN[:5])


def test_search_unbalanced_paren_finds_nothing_instead_of_failing(tmp_path: Path) -> None:
    assert _search(_manager(tmp_path), "(") == []


def test_search_dot_is_literal(tmp_path: Path) -> None:
    assert _search(_manager(tmp_path), "P0.5mm") == ["QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm"]


@pytest.mark.parametrize("pattern", ["*", "**", ""])
def test_search_star_and_empty_match_everything(tmp_path: Path, pattern: str) -> None:
    assert _search(_manager(tmp_path), pattern) == sorted(DIN + QFN)


def test_search_wildcard_and_case(tmp_path: Path) -> None:
    assert _search(_manager(tmp_path), "din*b_3x14*FEMALE") == sorted(DIN[:2])


@pytest.mark.parametrize(
    "library, pattern",
    [
        ("Connector_DIN", "3x14+6"),
        ("Connector_DIN", "("),
        ("Connector_DIN", "**"),
        ("Connector_DIN", "din*b_3x14*FEMALE"),
        ("Package_DFN_QFN", "P0.5mm"),
    ],
)
def test_both_tools_agree(tmp_path: Path, library: str, pattern: str) -> None:
    mgr = _manager(tmp_path)
    assert _search(mgr, pattern, library) == _listed(mgr, library, pattern)
