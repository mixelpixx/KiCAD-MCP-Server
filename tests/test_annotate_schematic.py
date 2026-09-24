"""annotate_schematic numbers each use of a sheet, across the project (#432).

It used to call kicad-skip's ``setAllReferences``, which wrote one number into
every ``(path ...)`` entry, so both uses of a sheet placed twice got the same
reference. It took the used numbers from the one file being annotated, so a
number taken on another sheet was handed out again. And it gave each unit of a
multi-unit part a number of its own. On a copy of KiCad 10.0.5's
complex_hierarchy demo, kicad-cli listed the part twice (three times in the
second case) and warned about annotation errors.
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
from commands.schematic_handlers import SchematicHandlersMixin  # noqa: E402
from utils.symbol_instances import _placed_symbols, _project_entries  # noqa: E402

pytestmark = pytest.mark.unit

ROOT = "aaaa0000-0000-0000-0000-000000000001"
AMP = "bbbb0000-0000-0000-0000-000000000002"
BLOCK_A = "a1a10000-0000-0000-0000-00000000000a"
BLOCK_B = "b2b20000-0000-0000-0000-00000000000b"
USE_A = f"/{ROOT}/{BLOCK_A}"
USE_B = f"/{ROOT}/{BLOCK_B}"

GND_DEFINITION = (
    "\t(lib_symbols\n"
    '\t\t(symbol "power:GND"\n\t\t\t(power)\n'
    '\t\t\t(property "Reference" "#PWR"\n\t\t\t\t(at 0 0 0)\n\t\t\t)\n'
    "\t\t)\n\t)\n"
)


def _sheet_block(block_uuid: str, file_name: str) -> str:
    return (
        f'\t(sheet\n\t\t(at 50 50)\n\t\t(size 30 20)\n\t\t(uuid "{block_uuid}")\n'
        '\t\t(property "Sheetname" "S"\n\t\t\t(at 50 49 0)\n\t\t)\n'
        f'\t\t(property "Sheetfile" "{file_name}"\n\t\t\t(at 50 71 0)\n\t\t)\n\t)\n'
    )


def _symbol(
    reference: str,
    entries: Optional[List[tuple]],
    lib_id: str = "Device:R",
    value: str = "10k",
    unit: int = 1,
) -> str:
    """A placed symbol in KiCad's layout; *entries* None leaves out (instances ...)."""
    instances = ""
    if entries is not None:
        paths = "".join(
            f'\t\t\t\t(path "{path}"\n\t\t\t\t\t(reference "{ref}")\n'
            f"\t\t\t\t\t(unit {unit})\n\t\t\t\t)\n"
            for path, ref in entries
        )
        instances = f'\t\t(instances\n\t\t\t(project "design"\n{paths}\t\t\t)\n\t\t)\n'
    return (
        f'\t(symbol\n\t\t(lib_id "{lib_id}")\n\t\t(at 100 100 0)\n\t\t(unit {unit})\n'
        f'\t\t(uuid "{uuid.uuid4()}")\n'
        f'\t\t(property "Reference" "{reference}"\n\t\t\t(at 102 100 0)\n\t\t)\n'
        f'\t\t(property "Value" "{value}"\n\t\t\t(at 102 102 0)\n\t\t)\n'
        f"{instances}\t)\n"
    )


def _sch(own_uuid: str, *items: str, libs: str = "\t(lib_symbols)\n", root: bool = True) -> str:
    tail = '\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)\n' if root else ""
    return (
        '(kicad_sch\n\t(version 20250114)\n\t(generator "eeschema")\n'
        f'\t(uuid "{own_uuid}")\n\t(paper "A4")\n{libs}' + "".join(items) + tail + ")\n"
    )


def _write(path: Path, text: str) -> Path:
    path.write_bytes(text.encode("utf-8"))
    return path


def _twice(tmp_path: Path, *root_items: str) -> Path:
    """design.kicad_sch uses amp.kicad_sch twice (blocks A and B)."""
    (tmp_path / "design.kicad_pro").write_text("{}", encoding="utf-8")
    _write(
        tmp_path / "design.kicad_sch",
        _sch(
            ROOT,
            *root_items,
            _sheet_block(BLOCK_A, "amp.kicad_sch"),
            _sheet_block(BLOCK_B, "amp.kicad_sch"),
        ),
    )
    return tmp_path / "amp.kicad_sch"


def _annotate(sheet: Path) -> dict:
    return SchematicHandlersMixin._handle_annotate_schematic(
        SimpleNamespace(), {"schematicPath": str(sheet)}
    )


def _uses(sheet: Path) -> List[List[tuple]]:
    """Per placed symbol, in file order: its (path, reference) entries."""
    text = sheet.read_text(encoding="utf-8")
    return [
        [(e.path, e.reference) for e in _project_entries(text[s:e], "design") or []]
        for s, e in _placed_symbols(text)
    ]


def _fields(sheet: Path) -> List[str]:
    """The Reference field of each placed symbol (not of the lib_symbols definitions)."""
    text = sheet.read_text(encoding="utf-8")
    fields = []
    for s, e in _placed_symbols(text):
        m = re.search(r'\(property "Reference" "([^"]*)"', text[s:e])
        fields.append(m.group(1) if m else "")
    return fields


class TestAnnotate:
    def test_each_use_of_a_sheet_gets_its_own_number(self, tmp_path):
        amp = _twice(tmp_path, _symbol("R2", [(f"/{ROOT}", "R2")]))
        _write(amp, _sch(AMP, _symbol("R?", [(USE_A, "R?"), (USE_B, "R?")]), root=False))

        r = _annotate(amp)

        # R2 is taken on the root sheet, so the second use gets R3.
        assert _uses(amp) == [[(USE_A, "R1"), (USE_B, "R3")]]
        assert _fields(amp) == ["R1"]
        assert r["success"] is True
        [item] = r["annotated"]
        assert (item["oldReference"], item["newReference"]) == ("R?", "R1")
        assert item["instances"] == [
            {"path": USE_A, "reference": "R1"},
            {"path": USE_B, "reference": "R3"},
        ]

    def test_numbers_taken_on_other_sheets_are_skipped(self, tmp_path):
        (tmp_path / "design.kicad_pro").write_text("{}", encoding="utf-8")
        _write(
            tmp_path / "design.kicad_sch",
            _sch(ROOT, _symbol("R1", [(f"/{ROOT}", "R1")]), _sheet_block(BLOCK_A, "sub.kicad_sch")),
        )
        sub = _write(
            tmp_path / "sub.kicad_sch", _sch(AMP, _symbol("R?", [(USE_A, "R?")]), root=False)
        )

        r = _annotate(sub)

        assert _uses(sub) == [[(USE_A, "R2")]]
        assert "instances" not in r["annotated"][0]  # one use: nothing extra to report

    def test_the_units_of_one_part_share_a_number_in_each_use(self, tmp_path):
        amp = _twice(tmp_path)
        both = [(USE_A, "U?"), (USE_B, "U?")]
        _write(
            amp,
            _sch(
                AMP,
                _symbol("U?", both, lib_id="Amplifier_Operational:LM358", value="LM358", unit=1),
                _symbol("U?", both, lib_id="Amplifier_Operational:LM358", value="LM358", unit=2),
                _symbol("U?", both, lib_id="Amplifier_Operational:LM358", value="LM358", unit=1),
                root=False,
            ),
        )

        _annotate(amp)

        # Units A and B of the first package share a number; the second unit A
        # starts a new package. Each use has its own numbers.
        assert _uses(amp) == [
            [(USE_A, "U1"), (USE_B, "U3")],
            [(USE_A, "U1"), (USE_B, "U3")],
            [(USE_A, "U2"), (USE_B, "U4")],
        ]

    def test_power_symbols_get_the_leading_zero(self, tmp_path):
        (tmp_path / "design.kicad_pro").write_text("{}", encoding="utf-8")
        root = _write(
            tmp_path / "design.kicad_sch",
            _sch(
                ROOT,
                _symbol("#PWR01", [(f"/{ROOT}", "#PWR01")], lib_id="power:GND", value="GND"),
                _symbol("#PWR?", [(f"/{ROOT}", "#PWR?")], lib_id="power:GND", value="GND"),
                libs=GND_DEFINITION,
            ),
        )

        _annotate(root)

        assert _fields(root) == ["#PWR01", "#PWR02"]

    def test_annotated_parts_and_templates_are_left_alone(self, tmp_path):
        (tmp_path / "design.kicad_pro").write_text("{}", encoding="utf-8")
        root = _write(
            tmp_path / "design.kicad_sch",
            _sch(
                ROOT,
                _symbol("R5", [(f"/{ROOT}", "R5")]),
                _symbol("_TEMPLATE_Device_R", [(f"/{ROOT}", "_TEMPLATE_Device_R")]),
            ),
        )
        before = root.read_bytes()

        r = _annotate(root)

        assert r == {
            "success": True,
            "annotated": [],
            "message": "All components already annotated",
        }
        assert root.read_bytes() == before

    def test_a_use_without_an_entry_is_filled_in_and_numbered(self, tmp_path):
        # Placed before the sheet's second use existed: one entry only.
        amp = _twice(tmp_path)
        _write(amp, _sch(AMP, _symbol("R?", [(USE_A, "R?")]), root=False))

        _annotate(amp)

        assert _uses(amp) == [[(USE_A, "R1"), (USE_B, "R2")]]

    def test_a_symbol_without_instance_data_is_numbered_through_its_field(self, tmp_path):
        (tmp_path / "design.kicad_pro").write_text("{}", encoding="utf-8")
        root = _write(tmp_path / "design.kicad_sch", _sch(ROOT, _symbol("C?", None)))
        _annotate(root)
        assert _fields(root) == ["C1"]

    def test_only_reference_tokens_change(self, tmp_path):
        amp = _twice(tmp_path)
        original = _sch(AMP, _symbol("R?", [(USE_A, "R?"), (USE_B, "R?")]), root=False)
        _write(amp, original.replace("\n", "\r\n"))

        _annotate(amp)

        expected = (
            original.replace('"Reference" "R?"', '"Reference" "R1"', 1)
            .replace('(reference "R?")', '(reference "R1")', 1)
            .replace('(reference "R?")', '(reference "R2")', 1)
            .replace("\n", "\r\n")
        )
        assert amp.read_bytes().decode("utf-8") == expected

    def test_requires_an_existing_schematic(self, tmp_path):
        assert _annotate(tmp_path / "missing.kicad_sch")["success"] is False
        r = SchematicHandlersMixin._handle_annotate_schematic(SimpleNamespace(), {})
        assert r == {"success": False, "message": "schematicPath is required"}


# --------------------------------------------------------------------------- #
# Against kicad-cli (skipped where KiCad is not installed)
# --------------------------------------------------------------------------- #


def _complex_hierarchy() -> Optional[Path]:
    from utils.kicad_roots import kicad_install_roots

    candidates = [root / "share" / "kicad" / "demos" for root in kicad_install_roots()] + [
        Path("/usr/share/kicad/demos"),
        Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/demos"),
    ]
    return next(
        (c / "complex_hierarchy" for c in candidates if (c / "complex_hierarchy").is_dir()), None
    )


@pytest.mark.integration
def test_kicad_cli_netlist_after_annotating_a_sheet_used_twice(tmp_path):
    """The #432 reproduction: R1 on the root, then R? on ampli_ht (used twice)."""
    cli = shutil.which("kicad-cli")
    demo = _complex_hierarchy()
    if not cli or demo is None:
        pytest.skip("kicad-cli or KiCad's complex_hierarchy demo not installed")
    if DynamicSymbolLoader().find_library_file("Device") is None:
        pytest.skip("KiCad's Device symbol library not installed")
    proj = tmp_path / "complex_hierarchy"
    shutil.copytree(demo, proj, ignore=shutil.ignore_patterns("~*"))
    root, amp = proj / "complex_hierarchy.kicad_sch", proj / "ampli_ht.kicad_sch"
    for sheet, reference, x in ((root, "R1", 250.19), (amp, "R?", 200.66)):
        DynamicSymbolLoader(project_path=proj).add_component(
            sheet, "Device", "R", reference=reference, value="10k", x=x, y=30.48
        )

    r = _annotate(amp)

    assert [i["reference"] for i in r["annotated"][0]["instances"]] == ["R2", "R3"]
    out = tmp_path / "out.net"
    run = subprocess.run(
        [cli, "sch", "export", "netlist", "-o", str(out), str(root)], capture_output=True, text=True
    )
    refs = re.findall(r'\(comp\s+\(ref\s+"([^"]+)"\)', out.read_text(encoding="utf-8"))
    assert [ref for ref, n in Counter(refs).items() if n > 1] == []
    assert {"R1", "R2", "R3"} <= set(refs)
    assert "annotation" not in (run.stdout + run.stderr).lower()
