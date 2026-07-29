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
