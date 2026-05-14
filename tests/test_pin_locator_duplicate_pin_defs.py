"""
Regression tests for ``PinLocator.parse_symbol_definition`` when a symbol
defines the same pin number more than once.

Background
----------
Some community-generated symbol libraries — for example
``PCM_Diode_Schottky_AKL:MBRS130`` — include both an outer "real" pin
with a visible stub (non-zero ``length``) and an inner zero-length "ghost"
pin at a different ``at`` coordinate. Both definitions share the same pin
number. Conceptually the ghost is an internal join used for symbol
graphic anchoring; the real outer pin is where wires and labels are
placed by the schematic author.

Before this fix, ``parse_symbol_definition`` stored pins as
``pins[pin_data["number"]] = pin_data`` — a plain assignment. Each
duplicate-numbered definition encountered during recursion overwrote the
previous one. The recursion order put the ghost pins last for the MBRS130
symbol, so the ghost won and ``get_pin_location`` returned a coordinate
that did not match any wire/label. As a knock-on effect,
``get_connections_for_net`` failed to discover diode pins on the rails
they were wired to (e.g. ``D1/1`` on ``+BATT``).

The fix: when storing a duplicate-numbered pin, keep the entry with the
greater ``length``. The outer "real" pin has length > 0 (a visible stub
out to the wire-attach point); the inner ghost has length == 0. Ties
resolve to first-encountered, so legitimate same-length duplicates
(e.g., per-unit repetitions in multi-unit symbols) keep stable ordering
and existing behaviour.
"""

import sys
from pathlib import Path

import pytest
from sexpdata import Symbol

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.pin_locator import PinLocator  # noqa: E402

# ---------------------------------------------------------------------------
# Helper: build a (symbol …) sexp matching the structure KiCad writes
# ---------------------------------------------------------------------------


def _pin_sexp(number: str, name: str, x: float, y: float, angle: int, length: float):
    """Return an s-expression list that mimics a KiCad ``(pin …)`` definition."""
    return [
        Symbol("pin"),
        Symbol("passive"),
        Symbol("line"),
        [Symbol("at"), x, y, angle],
        [Symbol("length"), length],
        [Symbol("name"), f'"{name}"'],
        [Symbol("number"), f'"{number}"'],
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseSymbolDefinitionDuplicatePinNumbers:
    """``parse_symbol_definition`` must pick the outer (length>0) pin when a
    symbol defines the same pin number twice — once with a visible stub and
    once as a zero-length ghost."""

    def test_outer_pin_wins_when_ghost_appears_after(self) -> None:
        """Mirrors the real bug: outer pin defined first, ghost defined
        later. The ghost must not clobber the outer pin in the result."""
        symbol_def = [
            Symbol("symbol"),
            "MBRS130",
            # Outer "real" pins — the ones with a visible stub.
            _pin_sexp("2", "A", -3.81, 0, 0, 2.54),
            _pin_sexp("1", "K", 3.81, 0, 180, 2.54),
            # Inner ghost pins — zero-length, would have clobbered before.
            _pin_sexp("2", "A", -2.54, -2.54, 0, 0),
            _pin_sexp("1", "K", 2.54, 2.54, 180, 0),
        ]

        pins = PinLocator.parse_symbol_definition(symbol_def)

        # Pin 1 = outer K at (3.81, 0), length 2.54 — not the (2.54, 2.54) ghost.
        assert pins["1"]["x"] == 3.81, pins
        assert pins["1"]["y"] == 0.0, pins
        assert pins["1"]["length"] == 2.54, pins

        # Pin 2 = outer A at (-3.81, 0), length 2.54 — not the (-2.54, -2.54) ghost.
        assert pins["2"]["x"] == -3.81, pins
        assert pins["2"]["y"] == 0.0, pins
        assert pins["2"]["length"] == 2.54, pins

    def test_outer_pin_wins_when_ghost_appears_first(self) -> None:
        """Symmetry check: ghost defined first, outer pin defined later. The
        outer pin must overwrite the ghost (the heuristic is length-based,
        not order-based)."""
        symbol_def = [
            Symbol("symbol"),
            "MBRS130_alt_ordering",
            _pin_sexp("1", "K", 2.54, 2.54, 180, 0),
            _pin_sexp("2", "A", -2.54, -2.54, 0, 0),
            _pin_sexp("2", "A", -3.81, 0, 0, 2.54),
            _pin_sexp("1", "K", 3.81, 0, 180, 2.54),
        ]

        pins = PinLocator.parse_symbol_definition(symbol_def)

        assert pins["1"]["x"] == 3.81, pins
        assert pins["1"]["length"] == 2.54, pins
        assert pins["2"]["x"] == -3.81, pins
        assert pins["2"]["length"] == 2.54, pins

    def test_no_duplicates_unaffected(self) -> None:
        """Regression: a normal symbol with unique pin numbers stores the
        same data it always did. Behaviour for the common case is
        unchanged."""
        symbol_def = [
            Symbol("symbol"),
            "Device:R",
            _pin_sexp("1", "~", 0, 3.81, 270, 1.27),
            _pin_sexp("2", "~", 0, -3.81, 90, 1.27),
        ]

        pins = PinLocator.parse_symbol_definition(symbol_def)

        assert pins["1"]["x"] == 0.0
        assert pins["1"]["y"] == 3.81
        assert pins["1"]["length"] == 1.27
        assert pins["2"]["x"] == 0.0
        assert pins["2"]["y"] == -3.81
        assert pins["2"]["length"] == 1.27

    def test_equal_length_duplicates_keep_first_encountered(self) -> None:
        """When two definitions of the same pin number have equal length
        (e.g. per-unit repetitions in a multi-unit symbol), the first one
        encountered wins. The fix's length-strict-greater comparison keeps
        this case stable and matches pre-fix behaviour for the only case
        that pre-fix code handled correctly."""
        symbol_def = [
            Symbol("symbol"),
            "MultiUnit_Example",
            _pin_sexp("1", "VCC", 0, 5.0, 270, 1.27),
            _pin_sexp("1", "VCC", 0, 10.0, 270, 1.27),  # same length, different y
        ]

        pins = PinLocator.parse_symbol_definition(symbol_def)

        # First definition (y=5.0) wins.
        assert pins["1"]["y"] == 5.0, pins
