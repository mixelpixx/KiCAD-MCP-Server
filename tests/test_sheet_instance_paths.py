"""Hierarchical instance paths for every use of a sheet (#428).

KiCad records a placed symbol's reference once per use of its sheet: one
``(path ...)`` entry per use inside ``(instances (project ...))``, each path
starting at the root. Three cases were still wrong after #424:

1. A sheet used more than once got one entry, for its first use only. KiCad's
   complex_hierarchy demo uses ampli_ht.kicad_sch twice (RV201 in one use,
   RV301 in the other). With one entry, kicad-cli 10.0.5 exports the netlist
   with "schematic has annotation errors" and one part listed twice.
2. A sheet in a subdirectory of the project never found its root and got a
   one-level ``/<sheet-uuid>`` path. KiCad's royalblue54L_feather demo keeps
   every sub-sheet in ``sch/``.
3. ``fix_subsheet_instances`` matched only the ``Sheet file`` spelling (KiCad
   writes ``Sheetfile``), built ``/<parent>/<block>`` (wrong below level 2),
   copied the existing reference into a second use, and ignored the sheets
   below the one being linked.

The synthetic hierarchies below mirror the demos' structure. The last classes
check against the demos and kicad-cli themselves and skip where KiCad is not
installed.
"""

import re
import shutil
import subprocess
import sys
import uuid
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.dynamic_symbol_loader import DynamicSymbolLoader  # noqa: E402
from commands.schematic_batch import SchematicBatchCommands  # noqa: E402
from commands.schematic_hierarchy import SchematicHierarchyCommands  # noqa: E402
from utils.sheet_tree import instance_paths, project_name, sheet_tree  # noqa: E402
from utils.symbol_instances import (  # noqa: E402
    ReferenceAllocator,
    _placed_symbols,
    _project_entries,
    instance_report,
)

ROOT = "aaaa0000-0000-0000-0000-000000000001"
MID = "bbbb0000-0000-0000-0000-000000000002"
LEAF = "cccc0000-0000-0000-0000-000000000003"
BLOCK_A = "a1a10000-0000-0000-0000-00000000000a"
BLOCK_B = "b2b20000-0000-0000-0000-00000000000b"
BLOCK_L = "c3c30000-0000-0000-0000-00000000000c"


def _sheet_block(block_uuid: str, file_name: str, key: str = "Sheetfile") -> str:
    return (
        "\t(sheet\n\t\t(at 50 50)\n\t\t(size 30 20)\n"
        f'\t\t(uuid "{block_uuid}")\n'
        '\t\t(property "Sheetname" "S"\n\t\t\t(at 50 49 0)\n\t\t)\n'
        f'\t\t(property "{key}" "{file_name}"\n\t\t\t(at 50 71 0)\n\t\t)\n'
        "\t)\n"
    )


def _symbol(reference: str, entries: List[tuple], project: str = "design", unit: int = 1) -> str:
    """A placed symbol in KiCad's layout, with one (path ...) per *entries* item."""
    paths = "".join(
        f'\t\t\t\t(path "{path}"\n\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit {unit})\n\t\t\t\t)\n'
        for path, ref in entries
    )
    return (
        '\t(symbol\n\t\t(lib_id "Device:R")\n\t\t(at 100 100 0)\n'
        f"\t\t(unit {unit})\n"
        f'\t\t(uuid "{uuid.uuid4()}")\n'
        f'\t\t(property "Reference" "{reference}"\n\t\t\t(at 102 100 0)\n\t\t)\n'
        f'\t\t(instances\n\t\t\t(project "{project}"\n{paths}\t\t\t)\n\t\t)\n'
        "\t)\n"
    )


def _sch(own_uuid: str, *items: str, sheet_instances: bool = True) -> str:
    tail = '\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)\n'
    return (
        '(kicad_sch\n\t(version 20250114)\n\t(generator "eeschema")\n'
        f'\t(uuid "{own_uuid}")\n\t(paper "A4")\n\t(lib_symbols)\n'
        + "".join(items)
        + (tail if sheet_instances else "")
        + ")\n"
    )


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _project(tmp_path: Path, name: str = "design") -> Path:
    (tmp_path / f"{name}.kicad_pro").write_text("{}", encoding="utf-8")
    return tmp_path / f"{name}.kicad_sch"


def _entries_of(sheet: Path, reference: str) -> List[tuple]:
    """(path, reference) entries of the symbol whose Reference field is *reference*."""
    text = sheet.read_text(encoding="utf-8")
    for start, end in _placed_symbols(text):
        block = text[start:end]
        if f'(property "Reference" "{reference}"' in block:
            return [(e.path, e.reference) for e in _project_entries(block, "design") or []]
    raise AssertionError(f"{reference} not found in {sheet.name}")


# --------------------------------------------------------------------------- #
# instance_paths
# --------------------------------------------------------------------------- #


@pytest.mark.unit
class TestInstancePaths:
    def test_the_root_is_its_own_uuid(self, tmp_path):
        root = _write(_project(tmp_path), _sch(ROOT))
        assert instance_paths(root) == (root, [f"/{ROOT}"])

    def test_a_sheet_used_twice_has_a_path_per_use_in_sheet_order(self, tmp_path):
        root = _write(
            _project(tmp_path),
            _sch(
                ROOT, _sheet_block(BLOCK_A, "amp.kicad_sch"), _sheet_block(BLOCK_B, "amp.kicad_sch")
            ),
        )
        amp = _write(tmp_path / "amp.kicad_sch", _sch(MID, sheet_instances=False))
        assert instance_paths(amp)[1] == [f"/{ROOT}/{BLOCK_A}", f"/{ROOT}/{BLOCK_B}"]
        assert instance_paths(amp)[0] == root

    def test_a_sheet_inside_a_sheet_used_twice_has_two_paths(self, tmp_path):
        _write(
            _project(tmp_path),
            _sch(
                ROOT, _sheet_block(BLOCK_A, "mid.kicad_sch"), _sheet_block(BLOCK_B, "mid.kicad_sch")
            ),
        )
        _write(tmp_path / "mid.kicad_sch", _sch(MID, _sheet_block(BLOCK_L, "leaf.kicad_sch")))
        leaf = _write(tmp_path / "leaf.kicad_sch", _sch(LEAF))
        assert instance_paths(leaf)[1] == [
            f"/{ROOT}/{BLOCK_A}/{BLOCK_L}",
            f"/{ROOT}/{BLOCK_B}/{BLOCK_L}",
        ]

    @pytest.mark.parametrize("child_has_sheet_instances", [True, False])
    def test_a_sheet_in_a_subdirectory_finds_its_root(self, tmp_path, child_has_sheet_instances):
        # royalblue54L_feather keeps its sub-sheets in sch/. create_schematic
        # writes (sheet_instances ...) into every file, so the sub-sheet looks
        # like a root from inside its own directory; it must not win.
        _write(_project(tmp_path), _sch(ROOT, _sheet_block(BLOCK_A, "sch/child.kicad_sch")))
        child = _write(
            tmp_path / "sch" / "child.kicad_sch",
            _sch(LEAF, sheet_instances=child_has_sheet_instances),
        )
        assert instance_paths(child)[1] == [f"/{ROOT}/{BLOCK_A}"]

    def test_an_unlinked_sheet_keeps_its_own_uuid(self, tmp_path):
        _write(_project(tmp_path), _sch(ROOT))
        orphan = _write(tmp_path / "orphan.kicad_sch", _sch(LEAF))
        assert instance_paths(orphan) == (None, [f"/{LEAF}"])

    def test_a_sheet_that_contains_itself_does_not_hang(self, tmp_path):
        # KiCad refuses such a file, but the walk must still finish: the
        # search for other.kicad_sch passes through the loop first.
        _write(
            _project(tmp_path),
            _sch(
                ROOT,
                _sheet_block(BLOCK_A, "loop.kicad_sch"),
                _sheet_block(BLOCK_B, "other.kicad_sch"),
            ),
        )
        _write(tmp_path / "loop.kicad_sch", _sch(MID, _sheet_block(BLOCK_L, "loop.kicad_sch")))
        other = _write(tmp_path / "other.kicad_sch", _sch(LEAF))
        assert instance_paths(other)[1] == [f"/{ROOT}/{BLOCK_B}"]

    def test_the_project_is_the_one_whose_root_reaches_the_sheet(self, tmp_path):
        # KiCad's ecc83 demo keeps ecc83-pp and ecc83-pp_v2 in one directory.
        _write(_project(tmp_path, "a_first"), _sch(ROOT))
        v2 = _write(
            _project(tmp_path, "b_second"), _sch(MID, _sheet_block(BLOCK_A, "sub.kicad_sch"))
        )
        sub = _write(tmp_path / "sub.kicad_sch", _sch(LEAF, sheet_instances=False))
        assert project_name(v2) == "b_second"
        assert project_name(sub) == "b_second"


# --------------------------------------------------------------------------- #
# Reference allocation
# --------------------------------------------------------------------------- #


@pytest.mark.unit
class TestReferenceAllocator:
    def test_first_free_number(self):
        allocator = ReferenceAllocator(["R1", "R2", "R4", "C1"])
        assert allocator.next_for("R7") == "R3"
        assert allocator.next_for("R7") == "R5"
        assert allocator.next_for("C9") == "C2"

    def test_power_symbols_keep_the_leading_zero(self):
        assert ReferenceAllocator(["#PWR01", "#PWR02"]).next_for("#PWR01") == "#PWR03"

    def test_unannotated_references_are_left_alone(self):
        assert ReferenceAllocator(["R1"]).next_for("R?") == "R?"

    def test_report_only_for_a_sheet_used_more_than_once(self):
        assert instance_report([("/a", "R1")]) == {}
        report = instance_report([("/a/b", "R1"), ("/a/c", "R3")])
        assert report["instances"] == [
            {"path": "/a/b", "reference": "R1"},
            {"path": "/a/c", "reference": "R3"},
        ]
        assert "R1, R3" in report["instances_note"]


# --------------------------------------------------------------------------- #
# Placing a part on a sheet used twice
# --------------------------------------------------------------------------- #


@pytest.mark.unit
class TestPlacementOnASheetUsedTwice:
    def _hierarchy(self, tmp_path: Path) -> Path:
        # R2 is already used on the root, so the second use of the new part
        # must skip it.
        _write(
            _project(tmp_path),
            _sch(
                ROOT,
                _symbol("R2", [(f"/{ROOT}", "R2")]),
                _sheet_block(BLOCK_A, "amp.kicad_sch"),
                _sheet_block(BLOCK_B, "amp.kicad_sch"),
            ),
        )
        return _write(tmp_path / "amp.kicad_sch", _sch(MID, sheet_instances=False))

    def _place(self, sheet: Path, reference: str, unit: int = 1) -> DynamicSymbolLoader:
        loader = DynamicSymbolLoader()
        loader.create_component_instance(
            sheet, "Device", "R", reference=reference, value="10k", x=100, y=100, unit=unit
        )
        return loader

    def test_each_use_gets_its_own_reference(self, tmp_path):
        amp = self._hierarchy(tmp_path)
        loader = self._place(amp, "R1")
        expected = [(f"/{ROOT}/{BLOCK_A}", "R1"), (f"/{ROOT}/{BLOCK_B}", "R3")]
        assert loader.placed_instances == expected
        assert _entries_of(amp, "R1") == expected

    def test_the_units_of_one_part_share_a_reference_in_each_use(self, tmp_path):
        amp = self._hierarchy(tmp_path)
        self._place(amp, "U1", unit=1)
        second = self._place(amp, "U1", unit=2)
        # U1 unit B in the second use is the same package as unit A there.
        assert second.placed_instances == [
            (f"/{ROOT}/{BLOCK_A}", "U1"),
            (f"/{ROOT}/{BLOCK_B}", "U2"),
        ]

    def test_batch_add_components_reports_each_use(self, tmp_path, monkeypatch):
        # No symbol library needed: the placed instance is what is checked.
        monkeypatch.setattr(DynamicSymbolLoader, "inject_symbol_into_schematic", lambda *a: None)
        amp = self._hierarchy(tmp_path)
        r = SchematicBatchCommands(SimpleNamespace()).batch_add_components(
            {
                "schematicPath": str(amp),
                "components": [
                    {"symbol": "Device:R", "reference": "R1", "position": {"x": 100, "y": 100}},
                    {"symbol": "Device:R", "reference": "R4", "position": {"x": 120, "y": 100}},
                ],
            }
        )
        assert r["success"], r
        uses = {e["reference"]: [i["reference"] for i in e["instances"]] for e in r["added"]}
        # R2 is taken on the root, R1 and R4 by the requests themselves.
        assert uses == {"R1": ["R1", "R3"], "R4": ["R4", "R5"]}
        assert _entries_of(amp, "R4") == [
            (f"/{ROOT}/{BLOCK_A}", "R4"),
            (f"/{ROOT}/{BLOCK_B}", "R5"),
        ]

    def test_a_sheet_used_once_is_unchanged(self, tmp_path):
        _write(_project(tmp_path), _sch(ROOT, _sheet_block(BLOCK_A, "one.kicad_sch")))
        one = _write(tmp_path / "one.kicad_sch", _sch(MID, sheet_instances=False))
        loader = self._place(one, "R1")
        assert loader.placed_instances == [(f"/{ROOT}/{BLOCK_A}", "R1")]
        assert instance_report(loader.placed_instances) == {}


# --------------------------------------------------------------------------- #
# fix_subsheet_instances (runs when a sheet is linked)
# --------------------------------------------------------------------------- #


def _fix(parent: Path) -> List[str]:
    cmds = SchematicHierarchyCommands(SimpleNamespace())
    return cmds.fix_subsheet_instances(str(parent), parent.read_text(encoding="utf-8"))


@pytest.mark.unit
class TestFixSubsheetInstances:
    def test_kicad_spelling_and_quoted_uuid(self, tmp_path):
        # A KiCad-saved parent: "Sheetfile", and (uuid "...") in quotes. The old
        # fixer matched only "Sheet file", so nothing was ever added.
        root = _write(_project(tmp_path), _sch(ROOT, _sheet_block(BLOCK_A, "child.kicad_sch")))
        child = _write(
            tmp_path / "child.kicad_sch",
            _sch(LEAF, _symbol("R1", [(f"/{LEAF}", "R1")]), sheet_instances=False),
        )
        assert _fix(root) == [str(child)]
        assert _entries_of(child, "R1") == [(f"/{LEAF}", "R1"), (f"/{ROOT}/{BLOCK_A}", "R1")]

    def test_a_sheet_below_level_2_gets_a_path_from_the_root(self, tmp_path):
        _write(_project(tmp_path), _sch(ROOT, _sheet_block(BLOCK_A, "mid.kicad_sch")))
        mid = _write(tmp_path / "mid.kicad_sch", _sch(MID, _sheet_block(BLOCK_L, "leaf.kicad_sch")))
        leaf = _write(tmp_path / "leaf.kicad_sch", _sch(LEAF, _symbol("R1", [(f"/{LEAF}", "R1")])))
        _fix(mid)
        # Not /<mid>/<block>: the path starts at the root.
        assert _entries_of(leaf, "R1")[-1] == (f"/{ROOT}/{BLOCK_A}/{BLOCK_L}", "R1")

    def test_a_second_use_gets_a_reference_of_its_own(self, tmp_path):
        root = _write(
            _project(tmp_path),
            _sch(
                ROOT, _sheet_block(BLOCK_A, "amp.kicad_sch"), _sheet_block(BLOCK_B, "amp.kicad_sch")
            ),
        )
        amp = _write(
            tmp_path / "amp.kicad_sch",
            _sch(MID, _symbol("R1", [(f"/{ROOT}/{BLOCK_A}", "R1")]), sheet_instances=False),
        )
        _fix(root)
        assert _entries_of(amp, "R1") == [
            (f"/{ROOT}/{BLOCK_A}", "R1"),
            (f"/{ROOT}/{BLOCK_B}", "R2"),
        ]

    def test_the_sheets_below_the_linked_one_are_covered(self, tmp_path):
        root = _write(_project(tmp_path), _sch(ROOT, _sheet_block(BLOCK_A, "mid.kicad_sch")))
        _write(tmp_path / "mid.kicad_sch", _sch(MID, _sheet_block(BLOCK_L, "leaf.kicad_sch")))
        leaf = _write(tmp_path / "leaf.kicad_sch", _sch(LEAF, _symbol("R1", [(f"/{LEAF}", "R1")])))
        modified = _fix(root)
        assert str(leaf) in modified
        assert (f"/{ROOT}/{BLOCK_A}/{BLOCK_L}", "R1") in _entries_of(leaf, "R1")

    def test_a_second_run_changes_nothing(self, tmp_path):
        root = _write(
            _project(tmp_path),
            _sch(
                ROOT, _sheet_block(BLOCK_A, "amp.kicad_sch"), _sheet_block(BLOCK_B, "amp.kicad_sch")
            ),
        )
        amp = _write(
            tmp_path / "amp.kicad_sch",
            _sch(MID, _symbol("R1", [(f"/{ROOT}/{BLOCK_A}", "R1")]), sheet_instances=False),
        )
        _fix(root)
        once = amp.read_bytes()
        assert _fix(root) == []
        assert amp.read_bytes() == once

    def test_the_file_keeps_its_layout_and_line_endings(self, tmp_path):
        root = _write(_project(tmp_path), _sch(ROOT, _sheet_block(BLOCK_A, "child.kicad_sch")))
        text = _sch(LEAF, _symbol("R1", [(f"/{LEAF}", "R1")]), sheet_instances=False)
        child = _write(tmp_path / "child.kicad_sch", text.replace("\n", "\r\n"))
        _fix(root)
        raw = child.read_bytes().decode("utf-8")
        assert "\n" not in raw.replace("\r\n", "")
        # The new entry copies the existing one: KiCad's one-token-per-line form.
        new_entry = (
            f'\t\t\t\t(path "/{ROOT}/{BLOCK_A}"\r\n\t\t\t\t\t(reference "R1")\r\n'
            "\t\t\t\t\t(unit 1)\r\n\t\t\t\t)"
        )
        assert new_entry in raw


# --------------------------------------------------------------------------- #
# Against KiCad itself (skipped where KiCad is not installed)
# --------------------------------------------------------------------------- #


def _kicad_demos() -> Optional[Path]:
    from utils.kicad_roots import kicad_install_roots

    candidates = [root / "share" / "kicad" / "demos" for root in kicad_install_roots()] + [
        Path("/usr/share/kicad/demos"),
        Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/demos"),
    ]
    return next((c for c in candidates if c.is_dir()), None)


@pytest.mark.integration
@pytest.mark.parametrize("demo", ["complex_hierarchy", "multichannel", "royalblue54L_feather"])
def test_paths_match_what_kicad_wrote_in_its_demos(demo):
    """Every sheet of the demo: the computed paths are the ones KiCad wrote.

    complex_hierarchy and multichannel use one sheet 2 and 4 times;
    royalblue54L_feather keeps its sub-sheets in a subdirectory. KiCad
    sometimes keeps a stale one-level entry from before a sheet was linked, so
    extra one-level paths in KiCad's data are allowed.
    """
    demos = _kicad_demos()
    if demos is None or not (demos / demo).is_dir():
        pytest.skip(f"KiCad demo {demo} not installed")
    pro = next((demos / demo).glob("*.kicad_pro"))
    checked = 0
    for sheet in sheet_tree(pro.with_suffix(".kicad_sch")):
        text = sheet.read_text(encoding="utf-8")
        kicad_paths = set()
        for start, end in _placed_symbols(text):
            kicad_paths.update(e.path for e in _project_entries(text[start:end], pro.stem) or [])
        if not kicad_paths:
            continue
        computed = set(instance_paths(sheet)[1])
        assert computed <= kicad_paths, sheet.name
        assert all(p.count("/") == 1 for p in kicad_paths - computed), sheet.name
        assert project_name(sheet) == pro.stem
        checked += 1
    assert checked


@pytest.mark.integration
def test_kicad_cli_netlist_has_a_part_per_use(tmp_path):
    """Link a sheet under a sheet, use that sheet twice, and ask kicad-cli.

    Parts are placed before any linking, as when a design is built bottom up.
    Before #428 the netlist listed R1 and R2 twice each and kicad-cli warned
    about annotation errors.
    """
    cli = shutil.which("kicad-cli")
    if not cli:
        pytest.skip("kicad-cli not available")
    if DynamicSymbolLoader().find_library_file("Device") is None:
        pytest.skip("KiCad's Device symbol library not installed")
    version = subprocess.run([cli, "version"], capture_output=True, text=True).stdout
    if int(re.match(r"\s*(\d+)", version or "0").group(1)) < 9:
        pytest.skip("the fixture uses the KiCad 9 file format")

    root = _project(tmp_path, "linking")
    for sheet, own in (
        (root, ROOT),
        (tmp_path / "mid.kicad_sch", MID),
        (tmp_path / "leaf.kicad_sch", LEAF),
    ):
        _write(sheet, _sch(own))
    mid, leaf = tmp_path / "mid.kicad_sch", tmp_path / "leaf.kicad_sch"
    for sheet, reference in ((leaf, "R1"), (mid, "R2")):
        DynamicSymbolLoader(project_path=tmp_path).add_component(
            sheet, "Device", "R", reference=reference, value="10k", x=50.8, y=50.8
        )
    hier = SchematicHierarchyCommands(SimpleNamespace())
    for parent, child, x in ((mid, leaf, 50), (root, mid, 50), (root, mid, 150)):
        r = hier.add_hierarchical_sheet(
            {
                "schematicPath": str(parent),
                "subsheetPath": str(child),
                "position": {"x": x, "y": 50},
            }
        )
        assert r["success"], r

    out = tmp_path / "linking.net"
    run = subprocess.run(
        [cli, "sch", "export", "netlist", "-o", str(out), str(root)],
        capture_output=True,
        text=True,
    )
    refs = re.findall(r'\(comp\s+\(ref\s+"([^"]+)"\)', out.read_text(encoding="utf-8"))
    assert sorted(refs) == ["R1", "R2", "R3", "R4"], refs
    assert not [r for r, n in Counter(refs).items() if n > 1]
    assert "annotation" not in (run.stdout + run.stderr).lower()
