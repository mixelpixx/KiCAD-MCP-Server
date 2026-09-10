"""utils.sheet_tree: the design is what the root sheet reaches, nothing else.

Shared by backannotate_footprints (which must not rewrite a backup) and
sync_schematic_to_board (which must not read one, #400).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.unit

from utils.sheet_tree import sheet_tree, sub_sheet_files  # noqa: E402


def _sheet(file_name: str, prop: str = "Sheetfile") -> str:
    return (
        '  (sheet (at 50 50) (size 20 20) (uuid "0")\n'
        '    (property "Sheetname" "x")\n'
        f'    (property "{prop}" "{file_name}")\n'
        "  )\n"
    )


def _sch(*sheets: str) -> str:
    return "(kicad_sch (version 20250114)\n" + "".join(sheets) + ")\n"


def test_sub_sheet_files_reads_every_top_level_sheet_reference() -> None:
    text = _sch(_sheet("a.kicad_sch"), _sheet("dir/b.kicad_sch"))
    assert sub_sheet_files(text) == ["a.kicad_sch", "dir/b.kicad_sch"]


def test_sub_sheet_files_accepts_the_legacy_property_spelling() -> None:
    assert sub_sheet_files(_sch(_sheet("old.kicad_sch", prop="Sheet file"))) == ["old.kicad_sch"]


def test_sub_sheet_files_unescapes_the_file_name() -> None:
    text = _sch(_sheet('odd\\"name.kicad_sch'))
    assert sub_sheet_files(text) == ['odd"name.kicad_sch']


def test_tree_is_root_first_then_breadth_first(tmp_path: Path) -> None:
    (tmp_path / "root.kicad_sch").write_text(_sch(_sheet("a.kicad_sch"), _sheet("b.kicad_sch")))
    (tmp_path / "a.kicad_sch").write_text(_sch(_sheet("deep/c.kicad_sch")))
    (tmp_path / "b.kicad_sch").write_text(_sch())
    (tmp_path / "deep").mkdir()
    (tmp_path / "deep" / "c.kicad_sch").write_text(_sch())
    names = [p.relative_to(tmp_path).as_posix() for p in sheet_tree(tmp_path / "root.kicad_sch")]
    assert names == ["root.kicad_sch", "a.kicad_sch", "b.kicad_sch", "deep/c.kicad_sch"]


def test_a_reused_sheet_file_is_listed_once(tmp_path: Path) -> None:
    (tmp_path / "root.kicad_sch").write_text(_sch(_sheet("sub.kicad_sch"), _sheet("sub.kicad_sch")))
    (tmp_path / "sub.kicad_sch").write_text(_sch())
    assert [p.name for p in sheet_tree(tmp_path / "root.kicad_sch")] == [
        "root.kicad_sch",
        "sub.kicad_sch",
    ]


def test_a_missing_sheet_is_skipped_not_fatal(tmp_path: Path) -> None:
    (tmp_path / "root.kicad_sch").write_text(
        _sch(_sheet("gone.kicad_sch"), _sheet("there.kicad_sch"))
    )
    (tmp_path / "there.kicad_sch").write_text(_sch())
    assert [p.name for p in sheet_tree(tmp_path / "root.kicad_sch")] == [
        "root.kicad_sch",
        "there.kicad_sch",
    ]


def test_backup_and_history_copies_are_never_reached(tmp_path: Path) -> None:
    """The failure mode of #400: rglob finds these, the walk cannot."""
    (tmp_path / "root.kicad_sch").write_text(_sch(_sheet("sub.kicad_sch")))
    (tmp_path / "sub.kicad_sch").write_text(_sch())
    for directory in (".history", ".mcp-backups", "_backup", "other_project"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "root.kicad_sch").write_text(_sch(_sheet("sub.kicad_sch")))
        (tmp_path / directory / "sub.kicad_sch").write_text(_sch())
    (tmp_path / "zz_stray.kicad_sch").write_text(_sch())

    reached = sheet_tree(tmp_path / "root.kicad_sch")
    assert [p.name for p in reached] == ["root.kicad_sch", "sub.kicad_sch"]
    assert all(p.parent == tmp_path for p in reached)
    assert len(list(tmp_path.rglob("*.kicad_sch"))) == 11  # what the old glob would have read


def test_a_root_that_does_not_exist_yields_nothing(tmp_path: Path) -> None:
    assert sheet_tree(tmp_path / "nope.kicad_sch") == []
