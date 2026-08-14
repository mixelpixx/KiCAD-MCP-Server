"""Regression tests for #336 — S-expression property values were not escape-aware.

KiCad escapes a backslash as ``\\\\`` and a quote as ``\\"`` inside double-quoted
tokens. Readers using the obvious ``"([^"]*)"`` stop at the FIRST quote,
including an escaped one, so a value containing ``\\"`` is truncated and left
ending in a lone backslash. Written back out, that trailing backslash escapes
the closing quote: the token runs on and swallows the rest of the file.

``power:GND``'s Description in the stock KiCad library is the value that
surfaced this — it contains an escaped quote.

Two halves have to be right, and so does their ORDER. Escaping quotes without
escaping backslashes first is a no-op on exactly the values that break, which
is why three writers appeared to escape and did not.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import sexpdata  # noqa: E402
from utils.sexpr_format import (  # noqa: E402
    QUOTED_VALUE,
    QUOTED_VALUE_SKIP,
    escape_sexpr_string,
    unescape_sexpr_string,
)

BS = "\\"
QT = '"'

NASTY_VALUES = [
    "plain",
    f"has{QT}quote",
    f"has{BS}backslash",
    f"both{BS}{QT}together",
    f"trailing{BS}",
    f"{BS}leading",
    f"{BS}{BS}doubled",
    'Ground "GND" reference',  # the power:GND Description shape
    f"C:{BS}path{BS}to{BS}file",  # a Windows path in a Datasheet property
]


class TestRoundTrip:
    @pytest.mark.parametrize("value", NASTY_VALUES)
    def test_escape_then_unescape_is_identity(self, value):
        assert unescape_sexpr_string(escape_sexpr_string(value)) == value

    @pytest.mark.parametrize("value", NASTY_VALUES)
    def test_round_trip_through_the_regex(self, value):
        """The reader must recover exactly what the writer emitted."""
        token = f'"{escape_sexpr_string(value)}"'
        m = re.search(QUOTED_VALUE, token)
        assert m is not None, f"pattern did not match {token!r}"
        assert unescape_sexpr_string(m.group(1)) == value

    @pytest.mark.parametrize("value", NASTY_VALUES)
    def test_emitted_property_parses_as_sexpr(self, value):
        """The check that fails on the old code: a truncated value leaves a
        trailing backslash that escapes the closing quote, so the whole
        remainder of the file is swallowed into one token."""
        fragment = f'(property "Description" "{escape_sexpr_string(value)}") (symbol "after")'
        parsed = sexpdata.loads(f"(root {fragment})")
        # The sentinel after the property must survive as its own form.
        assert len(parsed) == 3, f"the property token ran on: {parsed!r}"


class TestOldPatternWasBroken:
    """Pin the failure so the fix cannot be quietly reverted."""

    @pytest.mark.parametrize("value", [f"has{QT}quote", f"both{BS}{QT}together"])
    def test_naive_pattern_truncates(self, value):
        token = f'"{escape_sexpr_string(value)}"'
        naive = re.search(r'"([^"]*)"', token)
        assert naive is not None
        assert naive.group(1) != value, "this value would not have exposed the bug"

    def test_quote_only_escaper_is_a_noop_on_backslashes(self):
        """What footprint.py / symbol_creator.py / eagle.py used to do."""
        value = f"path{BS}"
        quote_only = value.replace('"', '\\"')
        assert quote_only == value  # nothing escaped at all
        # ...and emitting it escapes the closing quote.
        with pytest.raises(Exception):
            sexpdata.loads(f'(root (property "P" "{quote_only}") (after))')
        # The correct escaper does not.
        sexpdata.loads(f'(root (property "P" "{escape_sexpr_string(value)}") (after))')


class TestSkipVariant:
    """QUOTED_VALUE_SKIP exists so substituting the pattern cannot silently
    shift later positional group indices — the bug this fix nearly introduced
    into dynamic_symbol_loader's (at x y angle) capture."""

    def test_skip_captures_nothing(self):
        pattern = (
            r"\(property\s+" + QUOTED_VALUE + r"\s+" + QUOTED_VALUE_SKIP + r"\s+\(at\s+(\d+)\)"
        )
        m = re.search(pattern, '(property "Name" "Value" (at 42)')
        assert m is not None
        assert m.group(1) == "Name"
        assert m.group(2) == "42", "the coordinate group must stay at index 2"

    def test_skip_still_spans_escaped_quotes(self):
        value = escape_sexpr_string(f"has{QT}quote")
        pattern = (
            r"\(property\s+" + QUOTED_VALUE + r"\s+" + QUOTED_VALUE_SKIP + r"\s+\(at\s+(\d+)\)"
        )
        m = re.search(pattern, f'(property "Name" "{value}" (at 42)')
        assert m is not None and m.group(2) == "42"


class TestCallSitesAreConverted:
    """A grep-style guard: the naive pattern must not come back in the modules
    that read user-controlled property values."""

    CONVERTED = [
        "dynamic_symbol_loader.py",
        "library_symbol.py",
        "schematic_text_utils.py",
        "datasheet_manager.py",
        "schematic_hierarchy.py",
    ]

    @pytest.mark.parametrize("filename", CONVERTED)
    def test_no_naive_property_value_pattern_remains(self, filename):
        path = Path(__file__).parent.parent / "python" / "commands" / filename
        source = path.read_text(encoding="utf-8")
        offenders = [
            line
            for line in source.splitlines()
            if r'\(property\s+"([^"]' in line or r'"\s+"([^"]*)"' in line
        ]
        assert not offenders, (
            f"{filename} still reads property values with a non-escape-aware "
            f"pattern (#336). Use QUOTED_VALUE + unescape_sexpr_string. "
            f"Offenders: {offenders}"
        )

    @pytest.mark.parametrize(
        "filename", ["footprint.py", "symbol_creator.py", "eagle.py", "schematic_handlers.py"]
    )
    def test_writers_do_not_hand_roll_a_quote_only_escaper(self, filename):
        path = Path(__file__).parent.parent / "python" / "commands" / filename
        source = path.read_text(encoding="utf-8")
        assert (
            """replace('"', '\\\\"')""" not in source
        ), f"{filename} escapes quotes without escaping backslashes first (#336)"


# ---------------------------------------------------------------------------
# The #336 sweep converted the READERS. create_component_instance is a WRITER
# that was missed: it unescapes a library property value and then interpolates
# it straight back into a quoted token. The stock power:VCC / power:GND
# Description carries an escaped quote, so placing either of those symbols —
# i.e. almost any real schematic — emitted a file KiCad could not load at all,
# and ERC failed with "Failed to load schematic".
# ---------------------------------------------------------------------------

DESC_WITH_QUOTES = 'Power symbol creates a global label with name "VCC"'


def _sch_with_lib_symbol(description: str) -> str:
    """A minimal schematic whose lib_symbols entry carries `description`."""
    return (
        '(kicad_sch (version 20231120) (generator "eeschema")\n'
        "  (uuid 11111111-2222-3333-4444-555555555555)\n"
        "  (lib_symbols\n"
        '    (symbol "power:VCC"\n'
        '      (property "Reference" "#PWR" (at 0 -3.81 0) (effects (font (size 1.27 1.27))))\n'
        '      (property "Value" "VCC" (at 0 3.556 0) (effects (font (size 1.27 1.27))))\n'
        '      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27))))\n'
        '      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27))))\n'
        f'      (property "Description" "{escape_sexpr_string(description)}"'
        " (at 0 0 0) (effects (font (size 1.27 1.27))))\n"
        '      (symbol "VCC_1_1"\n'
        "        (pin power_in line (at 0 0 90) (length 0)\n"
        '          (name "" (effects (font (size 1.27 1.27))))\n'
        '          (number "1" (effects (font (size 1.27 1.27))))\n'
        "        )\n"
        "      )\n"
        "    )\n"
        "  )\n"
        '  (sheet_instances (path "/" (page "1")))\n'
        ")\n"
    )


class TestPlacedInstanceEscapesCopiedValues:
    def _place(self, tmp_path, description):
        from commands.dynamic_symbol_loader import DynamicSymbolLoader

        sch = tmp_path / "t.kicad_sch"
        sch.write_text(_sch_with_lib_symbol(description), encoding="utf-8")
        (tmp_path / "t.kicad_pro").write_text("{}", encoding="utf-8")

        DynamicSymbolLoader(project_path=tmp_path).create_component_instance(
            sch, "power", "VCC", reference="#PWR01", value="VCC", x=100, y=65
        )
        return sch.read_text(encoding="utf-8")

    def test_output_is_still_parseable(self, tmp_path):
        """The whole point: a quote in a copied value must not break the file."""
        content = self._place(tmp_path, DESC_WITH_QUOTES)
        sexpdata.loads(content)  # raises if the token ran on

    def test_copied_description_round_trips(self, tmp_path):
        content = self._place(tmp_path, DESC_WITH_QUOTES)
        found = [
            unescape_sexpr_string(m)
            for m in re.findall(r'\(property\s+"Description"\s+' + QUOTED_VALUE, content)
        ]
        # One in lib_symbols, one on the placed instance; both must survive intact.
        assert found == [DESC_WITH_QUOTES, DESC_WITH_QUOTES], found

    def test_no_bare_quote_leaks_into_the_instance(self, tmp_path):
        content = self._place(tmp_path, DESC_WITH_QUOTES)
        assert 'name "VCC""' not in content, "unescaped quote written into the instance"

    @pytest.mark.parametrize("value", NASTY_VALUES)
    def test_any_nasty_description_survives(self, tmp_path, value):
        content = self._place(tmp_path, value)
        sexpdata.loads(content)
        found = [
            unescape_sexpr_string(m)
            for m in re.findall(r'\(property\s+"Description"\s+' + QUOTED_VALUE, content)
        ]
        assert found == [value, value], found
