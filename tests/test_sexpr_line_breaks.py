"""Line breaks in values the server writes into KiCad files.

KiCad's writer escapes a line feed as ``\\n`` and a carriage return as ``\\r``
inside a quoted token, and its lexer reads a file line by line, so a raw line
break leaves the token unterminated. ``escape_sexpr_string`` escaped only the
backslash and the quote, so a multi-line value -- a Description set through
``edit_schematic_component``, a sheet property, a library symbol property --
made the file unreadable. A root schematic then fails to load. A sub-sheet is
left out of the design without a word: kicad-cli still exits 0 and ERC stays
clean. On KiCad's complex_hierarchy demo, one such Value took the netlist from
68 components to 10.

Hierarchical label and sheet pin names were not escaped at all, and neither
were the name and value add_library_symbol_property writes.

The reader has to match what KiCad reads: ``\\n`` is a line break, while
``C:\\\\new`` (an escaped backslash followed by "n") is a backslash and an "n".
"""

import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Optional

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import sexpdata  # noqa: E402
from utils.sexpr_format import (  # noqa: E402
    QUOTED_VALUE,
    escape_sexpr_string,
    unescape_sexpr_string,
)

BS = "\\"
QT = '"'
TEMPLATE_SCH = Path(__file__).parent.parent / "python" / "templates" / "empty.kicad_sch"

MULTI_LINE_VALUES = [
    "two\nlines",
    "windows\r\nline end",
    "trailing line break\n",
    f"a {QT}quoted{QT} word\nand a second line",
    f"C:{BS}new{BS}notes",  # an escaped backslash before "n" is not a line break
    f"literal {BS}n in the text",
    "tab\tinside",
]

DESCRIPTION = f"Thin film, 0.1%\nAEC-Q200 {QT}automotive{QT}"

PLACED_RESISTOR = """\
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    (property "Reference" "R1" (at 51.27 47.46 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "10k" (at 51.27 52.54 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "" (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "Datasheet" "~" (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
  )
"""


def _schematic(path: Path, body: str = "", own_uuid: Optional[str] = None) -> Path:
    """empty.kicad_sch, which embeds Device:R, with *body* before its last paren."""
    text = TEMPLATE_SCH.read_text(encoding="utf-8")
    if own_uuid:
        text = re.sub(r'\(uuid\s+"?[0-9a-fA-F-]+"?\)', f'(uuid "{own_uuid}")', text, count=1)
    text = text.rstrip()
    path.write_bytes((text[:-1] + body + ")\n").encode("utf-8"))
    return path


def _raw_property(text: str, name: str) -> str:
    """The still-escaped value of the first property *name* in *text*."""
    m = re.search(r'\(property\s+"' + re.escape(name) + r'"\s+' + QUOTED_VALUE, text)
    assert m, f"no {name} property written"
    return m.group(1)


@pytest.mark.unit
class TestHelpers:
    def test_escape_writes_what_kicad_writes(self) -> None:
        # Backslash, quote, line feed and carriage return are escaped; a tab
        # stays raw, as in files KiCad saves.
        value = f"a{BS}b{QT}c\nd\re\tf"
        assert escape_sexpr_string(value) == f"a{BS}{BS}b{BS}{QT}c{BS}nd{BS}re\tf"

    @pytest.mark.parametrize("value", MULTI_LINE_VALUES)
    def test_escaped_value_has_no_raw_line_break(self, value: str) -> None:
        escaped = escape_sexpr_string(value)
        assert "\n" not in escaped and "\r" not in escaped

    @pytest.mark.parametrize("value", MULTI_LINE_VALUES)
    def test_round_trip(self, value: str) -> None:
        assert unescape_sexpr_string(escape_sexpr_string(value)) == value

    @pytest.mark.parametrize("value", MULTI_LINE_VALUES)
    def test_sexpdata_reads_the_escaped_token_back(self, value: str) -> None:
        # sexpdata backs the formatter the other writers use; both write paths
        # must agree on what a token means.
        parsed = sexpdata.loads(f'(property "Description" "{escape_sexpr_string(value)}")')
        assert parsed[2] == value

    @pytest.mark.parametrize(
        "in_file, expected",
        [
            (f"A{BS}nB", "A\nB"),
            (f"A{BS}rB", "A\rB"),
            (f"A{BS}tB", "A\tB"),
            (f"C:{BS}{BS}new", f"C:{BS}new"),
            (f"A{BS}{QT}B", f"A{QT}B"),
            (f"A{BS}qB", f"A{BS}qB"),
        ],
    )
    def test_unescape_reads_what_kicad_reads(self, in_file: str, expected: str) -> None:
        # Checked with kicad-cli 10.0.5: `sch upgrade` re-saves \t as a tab and
        # keeps an unknown escape such as \q as a backslash and a "q".
        assert unescape_sexpr_string(in_file) == expected


@pytest.mark.integration
class TestWritersEscapeLineBreaks:
    def test_component_property(self, tmp_path: Path) -> None:
        from kicad_interface import KiCADInterface

        sch = _schematic(tmp_path / "board.kicad_sch", PLACED_RESISTOR)
        iface = KiCADInterface()
        result = iface.handle_command(
            "edit_schematic_component",
            {
                "schematicPath": str(sch),
                "reference": "R1",
                "properties": {"Description": DESCRIPTION},
            },
        )
        assert result["success"] is True, result
        raw = _raw_property(sch.read_text(encoding="utf-8"), "Description")
        assert "\n" not in raw
        assert unescape_sexpr_string(raw) == DESCRIPTION

        got = iface.handle_command(
            "get_schematic_component", {"schematicPath": str(sch), "reference": "R1"}
        )
        assert got["fields"]["Description"]["value"] == DESCRIPTION

    def test_sheet_property(self, tmp_path: Path) -> None:
        from commands.schematic_hierarchy import SchematicHierarchyCommands

        (tmp_path / "design.kicad_pro").write_text('{"meta":{"version":1}}', encoding="utf-8")
        root = _schematic(tmp_path / "design.kicad_sch", own_uuid=str(uuid.uuid4()))
        sub = _schematic(tmp_path / "power.kicad_sch", own_uuid=str(uuid.uuid4()))
        cmds = SchematicHierarchyCommands(None)
        linked = cmds.add_hierarchical_sheet(
            {"schematicPath": str(root), "subsheetPath": str(sub), "sheetName": "Power"}
        )
        assert linked["success"] is True, linked

        result = cmds.set_sheet_property(
            {"schematicPath": str(root), "sheetName": "Power", "key": "Notes", "value": DESCRIPTION}
        )
        assert result["success"] is True, result
        raw = _raw_property(root.read_text(encoding="utf-8"), "Notes")
        assert "\n" not in raw
        assert unescape_sexpr_string(raw) == DESCRIPTION

    def test_library_symbol_property(self, tmp_path: Path) -> None:
        from commands.add_library_symbol_property import add_library_symbol_property

        sch = _schematic(tmp_path / "board.kicad_sch")
        result = add_library_symbol_property(
            {
                "schematicPath": str(sch),
                "libraryName": "Device",
                "symbolName": "R",
                "propertyName": "Notes",
                "propertyValue": DESCRIPTION,
            }
        )
        assert result["success"] is True, result
        text = sch.read_text(encoding="utf-8")
        raw = _raw_property(text, "Notes")
        assert "\n" not in raw
        assert unescape_sexpr_string(raw) == DESCRIPTION
        # The whole file still reads as one (kicad_sch ...) form.
        assert sexpdata.loads(text)[0] == sexpdata.Symbol("kicad_sch")

    def test_label_and_sheet_pin_names(self) -> None:
        from commands.wire_manager import (
            WireManager,
            _make_hierarchical_label_text,
            _make_sheet_pin_text,
        )

        name = f"DATA {QT}A{QT}\nB"
        label = sexpdata.loads(_make_hierarchical_label_text(name, [10, 20]))
        pin = sexpdata.loads(_make_sheet_pin_text(name, "input", [10, 20]))
        assert label[1] == name and pin[1] == name
        # The pin head stays on one line: the name's line break is escaped.
        first_line = _make_sheet_pin_text(name, "input", [10, 20]).split("\n")[0]
        assert first_line.endswith(" input")

        # add_sheet_pin finds a sheet by its name as the file spells it.
        sheet_name = f"Power {QT}A{QT}"
        content = (
            "(kicad_sch\n  (sheet (at 0 0) (size 10 10)\n"
            f'    (property "Sheetname" "{escape_sexpr_string(sheet_name)}" (at 0 0 0))\n'
            "  )\n)\n"
        )
        updated, found = WireManager.add_sheet_pin(content, sheet_name, "VIN", "input", [0, 5])
        assert found is True
        assert '(pin "VIN" input' in updated

    def test_footprint_description_is_read_with_its_line_breaks(self, tmp_path: Path) -> None:
        from parsers.kicad_mod_parser import parse_kicad_mod

        mod = tmp_path / "R_0603.kicad_mod"
        mod.write_bytes(
            (
                '(footprint "R_0603"\n'
                f'  (descr "Resistor{BS}nSMD 0603, path C:{BS}{BS}new")\n'
                '  (tags "resistor")\n'
                ")\n"
            ).encode("utf-8")
        )
        parsed = parse_kicad_mod(str(mod))
        assert parsed is not None
        assert parsed["description"] == f"Resistor\nSMD 0603, path C:{BS}new"


@pytest.mark.integration
def test_kicad_keeps_a_sub_sheet_with_a_multi_line_property(tmp_path: Path) -> None:
    """A line break in a sub-sheet property must not drop the sheet.

    Before the fix, kicad-cli exported 0 components here and still exited 0.
    """
    cli = shutil.which("kicad-cli")
    if not cli:
        pytest.skip("kicad-cli not available")
    from commands.schematic_hierarchy import SchematicHierarchyCommands
    from kicad_interface import KiCADInterface

    (tmp_path / "design.kicad_pro").write_text('{"meta":{"version":1}}', encoding="utf-8")
    root = _schematic(tmp_path / "design.kicad_sch", own_uuid=str(uuid.uuid4()))
    sub = _schematic(tmp_path / "sub.kicad_sch", PLACED_RESISTOR, own_uuid=str(uuid.uuid4()))
    linked = SchematicHierarchyCommands(None).add_hierarchical_sheet(
        {"schematicPath": str(root), "subsheetPath": str(sub), "sheetName": "Sub"}
    )
    assert linked["success"] is True, linked

    def components() -> int:
        out = tmp_path / "net.xml"
        if out.exists():
            out.unlink()
        run = subprocess.run(
            [cli, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(out), str(root)],
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stdout + run.stderr
        return out.read_text(encoding="utf-8").count("<comp ")

    assert components() == 1
    result = KiCADInterface().handle_command(
        "edit_schematic_component",
        {
            "schematicPath": str(sub),
            "reference": "R1",
            "properties": {"Description": "first line\nsecond line"},
        },
    )
    assert result["success"] is True, result
    assert components() == 1
