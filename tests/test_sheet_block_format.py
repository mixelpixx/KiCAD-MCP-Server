"""add_hierarchical_sheet writes the sheet block the way KiCad does.

KiCad names the sheet properties ``Sheetname`` and ``Sheetfile`` (every sheet
block in KiCad 10.0.6's demo projects, file versions 20241209 to 20260101) and
files a sheet's page number inside its own block, once per use of the parent:

    (sheet ...
      (property "Sheetname" "Power" ...)
      (property "Sheetfile" "power.kicad_sch" ...)
      (instances (project "design" (path "/<chain to the parent>" (page "2")))))

The root's (sheet_instances ...) holds only (path "/" (page "1")). The writer
used to emit ``Sheet name``/``Sheet file`` and append the page to the root's
sheet_instances as /<parent>/<block>, reading the parent uuid only when
unquoted (KiCad quotes it). KiCad 10 flags that block on load and rewrites it.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.schematic_hierarchy import SchematicHierarchyCommands  # noqa: E402

ROOT = "aaaa0000-0000-0000-0000-000000000001"
MID = "cccc0000-0000-0000-0000-000000000003"
BLOCK_A = "bbbb0000-0000-0000-0000-00000000000a"
BLOCK_B = "bbbb0000-0000-0000-0000-00000000000b"


def _cmds() -> SchematicHierarchyCommands:
    return SchematicHierarchyCommands(None)


def _sheet(block_uuid: str, name: str, file: str, path: str, page: int) -> str:
    return (
        "  (sheet (at 50 50) (size 30 20)\n"
        f'    (uuid "{block_uuid}")\n'
        f'    (property "Sheetname" "{name}" (at 50 48 0) (effects (font (size 1.27 1.27))))\n'
        f'    (property "Sheetfile" "{file}" (at 50 72 0) (effects (font (size 1.27 1.27))))\n'
        f'    (instances (project "design" (path "{path}" (page "{page}"))))\n'
        "  )\n"
    )


def _schematic(uuid: str, body: str = "") -> str:
    return (
        '(kicad_sch (version 20260306) (generator "eeschema")\n'
        f'  (uuid "{uuid}")\n  (paper "A4")\n  (lib_symbols)\n'
        f"{body}"
        '  (sheet_instances (path "/" (page "1")))\n)\n'
    )


def _project(tmp_path: Path, root_body: str = "") -> Path:
    (tmp_path / "design.kicad_pro").write_text('{"meta":{"version":1}}', encoding="utf-8")
    root = tmp_path / "design.kicad_sch"
    root.write_text(_schematic(ROOT, root_body), encoding="utf-8")
    return root


def _add(parent: Path, sub: Path, name: str = "Power") -> dict:
    sub.write_text(_schematic("dddd0000-0000-0000-0000-000000000004"), encoding="utf-8")
    return _cmds().add_hierarchical_sheet(
        {"schematicPath": str(parent), "subsheetPath": str(sub), "sheetName": name}
    )


def _new_block(content: str, sheet_uuid: str) -> str:
    at = content.index(f'(uuid "{sheet_uuid}")')
    start = [m.start() for m in re.finditer(r"\(sheet(?=\s)", content[:at])][-1]
    depth = 0
    for i in range(start, len(content)):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                return content[start : i + 1]
    raise AssertionError("unbalanced sheet block")


def _root_sheet_instances(content: str) -> str:
    return content[content.rindex("(sheet_instances") :]


@pytest.mark.unit
class TestSheetBlockFormat:
    def test_properties_use_kicad_names(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        r = _add(root, tmp_path / "power.kicad_sch")
        assert r["success"] is True
        block = _new_block(root.read_text(encoding="utf-8"), r["sheet_uuid"])
        assert '(property "Sheetname" "Power"' in block
        assert '(property "Sheetfile" "power.kicad_sch"' in block
        assert '"Sheet name"' not in block and '"Sheet file"' not in block

    def test_page_is_filed_in_the_block_under_the_project(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        r = _add(root, tmp_path / "power.kicad_sch")
        content = root.read_text(encoding="utf-8")
        block = _new_block(content, r["sheet_uuid"])
        # quoted root uuid is read; the path is the chain to the parent only
        assert f'(project "design"\n        (path "/{ROOT}" (page "2"))' in block
        assert r["page"] == 2 and r["pages"] == [2]
        # the root's sheet_instances is left alone
        assert _root_sheet_instances(content).count("(path") == 1

    def test_page_numbers_are_unique_across_the_project(self, tmp_path: Path) -> None:
        # The root already holds a sheet on page 2 and the mid sheet one on page 3.
        root = _project(tmp_path, _sheet(BLOCK_A, "Mid", "mid.kicad_sch", f"/{ROOT}", 2))
        (tmp_path / "mid.kicad_sch").write_text(
            _schematic(MID, _sheet(BLOCK_B, "Leaf", "leaf.kicad_sch", f"/{ROOT}/{BLOCK_A}", 3)),
            encoding="utf-8",
        )
        (tmp_path / "leaf.kicad_sch").write_text(_schematic("eeee0000-0000-0000-0000-00000000000e"))
        r = _add(root, tmp_path / "power.kicad_sch")
        assert r["page"] == 4

    def test_every_use_of_a_nested_parent_gets_a_path_and_page(self, tmp_path: Path) -> None:
        # mid.kicad_sch is used twice by the root (pages 2 and 3).
        root = _project(
            tmp_path,
            _sheet(BLOCK_A, "Mid A", "mid.kicad_sch", f"/{ROOT}", 2)
            + _sheet(BLOCK_B, "Mid B", "mid.kicad_sch", f"/{ROOT}", 3),
        )
        mid = tmp_path / "mid.kicad_sch"
        mid.write_text(_schematic(MID), encoding="utf-8")
        r = _add(mid, tmp_path / "leaf.kicad_sch", "Leaf")
        assert r["success"] is True
        block = _new_block(mid.read_text(encoding="utf-8"), r["sheet_uuid"])
        assert f'(path "/{ROOT}/{BLOCK_A}" (page "4"))' in block
        assert f'(path "/{ROOT}/{BLOCK_B}" (page "5"))' in block
        assert r["pages"] == [4, 5]

    def test_parent_without_sheet_instances(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        text = root.read_text(encoding="utf-8").replace(
            '  (sheet_instances (path "/" (page "1")))\n', ""
        )
        root.write_text(text, encoding="utf-8")
        r = _add(root, tmp_path / "power.kicad_sch")
        assert r["success"] is True
        content = root.read_text(encoding="utf-8")
        assert content.lstrip().startswith("(kicad_sch")
        assert content.rstrip().endswith(")")
        assert _new_block(content, r["sheet_uuid"])

    def test_remove_reports_the_nested_instance_data(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        r = _add(root, tmp_path / "power.kicad_sch")
        rem = _cmds().remove_hierarchical_sheet({"schematicPath": str(root), "sheetName": "Power"})
        assert rem["success"] is True and rem["removed_instance_path"] is True
        assert r["sheet_uuid"] not in root.read_text(encoding="utf-8")


@pytest.mark.integration
def test_kicad_keeps_the_block_as_written(tmp_path: Path) -> None:
    """kicad-cli re-saving the root leaves the new block's names and page alone.

    With the old format KiCad renamed both properties and moved the page from
    the root's sheet_instances into the block.
    """
    cli = shutil.which("kicad-cli")
    if not cli:
        pytest.skip("kicad-cli not available")
    root = _project(tmp_path)
    r = _add(root, tmp_path / "power.kicad_sch")
    assert r["success"] is True
    up = subprocess.run(
        [cli, "sch", "upgrade", "--force", str(root)], capture_output=True, text=True
    )
    assert up.returncode == 0, up.stderr
    content = root.read_text(encoding="utf-8")
    block = _new_block(content.replace("\t", " "), r["sheet_uuid"])
    assert '"Sheetname" "Power"' in block
    assert '"Sheetfile" "power.kicad_sch"' in block
    assert f'"/{ROOT}"' in block and '(page "2")' in block
    assert _root_sheet_instances(content).count("(path") == 1
