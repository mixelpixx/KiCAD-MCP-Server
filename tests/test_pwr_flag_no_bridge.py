"""
Regression tests for the PWR_FLAG over-merge bug in _parse_virtual_connections.

Background
----------
KiCad schematics use ``power:PWR_FLAG`` symbols (reference prefix ``#FLG``) as
ERC markers that assert "this rail really is driven, do not warn." Every such
symbol has ``Value="PWR_FLAG"`` regardless of which rail it sits on — it
inherits the rail's name from the wire/label it is wired to.

Commit 7f3a379 ("Treat PWR_FLAG anchors as connected in orphan-wire detection")
added ``#FLG`` symbols to the same loop that handles ``#PWR`` power-port
symbols inside ``_parse_virtual_connections``. The intent — registering the
pwr-flag pin position so ``find_orphaned_wires`` would not flag wire ends
terminating on a pwr-flag as dangling — was correct, but the implementation
also added each pwr-flag pin to ``label_to_points`` keyed under the literal
string ``"PWR_FLAG"``.

This made ``label_to_points["PWR_FLAG"]`` a list of every pwr-flag pin in the
sheet. In ``_find_connected_wires`` the BFS uses ``label_to_points`` for
virtual jumps: when it visits a wire endpoint with ``point_to_label[pt] ==
"PWR_FLAG"`` it jumps to every other point that shares that label. With a
schematic that has one pwr-flag per power rail — common practice — the BFS
walks from a rail's label, across the pwr-flag stub wire, across the
``"PWR_FLAG"`` virtual jump to every other pwr-flag, and out through their
stub wires into every other rail. The result is that ``get_net_connections``
for any single rail returns the union of pins on *every* rail that has a
pwr-flag.

The fix: pwr-flag pin positions are still registered in ``point_to_label``
(so orphan-wire detection sees them as valid anchors), but they are not
added to ``label_to_points`` under any shared key. The pwr-flag remains
electrically connected to its rail via the wire-graph BFS through the wire
it sits on; the label-jump mechanism is unnecessary for that path and
actively harmful when the "label" is the same for unrelated rails.

These tests pin the fix in place.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.wire_connectivity import (  # noqa: E402
    _parse_virtual_connections,
    _to_iu,
)

# ---------------------------------------------------------------------------
# Mock helpers (mirror the style used in test_net_connectivity.py and
# test_label_at_pin_net_connections.py)
# ---------------------------------------------------------------------------


def _make_power_symbol(ref: str, value: str) -> MagicMock:
    """Build a mock for a #PWR* (power port) or #FLG* (pwr-flag) symbol.

    The symbol does not carry its own pin coordinates — those are returned
    by the (mocked) ``PinLocator.get_all_symbol_pins`` keyed by ``ref``.
    """
    sym = MagicMock()
    sym.property = MagicMock()
    sym.property.Reference = MagicMock()
    sym.property.Reference.value = ref
    sym.property.Value = MagicMock()
    sym.property.Value.value = value
    sym.lib_id = MagicMock()
    sym.lib_id.value = "power:" + value
    return sym


# ---------------------------------------------------------------------------
# Unit-level tests: _parse_virtual_connections directly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseVirtualConnectionsPwrFlagHandling:
    """Direct tests on _parse_virtual_connections to pin the contract.

    The contract is: pwr-flag pin positions land in ``point_to_label`` (so
    orphan-wire detection sees them) but never in ``label_to_points`` under
    a shared "PWR_FLAG" key (so BFS-via-label-jump cannot bridge unrelated
    rails through them).
    """

    def test_two_pwr_flags_do_not_share_a_label_to_points_entry(self) -> None:
        """The over-merge regression: two distinct pwr-flags must NOT register
        under a single ``label_to_points["PWR_FLAG"]`` key.

        On the buggy code, ``label_to_points["PWR_FLAG"]`` was a list of
        every pwr-flag position; on the fixed code, that key is absent."""
        flg1 = _make_power_symbol("#FLG01", "PWR_FLAG")
        flg2 = _make_power_symbol("#FLG02", "PWR_FLAG")

        sch = MagicMock()
        sch.symbol = [flg1, flg2]
        # No labels — exercise the symbol-loop path only.
        for attr in ("label", "global_label"):
            if hasattr(sch, attr):
                delattr(sch, attr)

        pin_positions = {
            "#FLG01": {"1": (10.0, 20.0)},
            "#FLG02": {"1": (30.0, 40.0)},
        }

        with patch(
            "commands.pin_locator.PinLocator.get_all_symbol_pins",
            side_effect=lambda path, ref: pin_positions.get(ref, {}),
        ):
            # Pass an empty sexp so the label-parsing branch is a no-op and
            # only the symbol-loop branch runs.
            point_to_label, label_to_points = _parse_virtual_connections(sch, "/fake/path", sexp=[])

        # Orphan-detection benefit preserved: both pwr-flag pin positions are
        # registered as anchors.
        assert _to_iu(10.0, 20.0) in point_to_label
        assert _to_iu(30.0, 40.0) in point_to_label

        # Over-merge fix: pwr-flags do not share a label_to_points key, so BFS
        # cannot virtually jump from one pwr-flag to another.
        pwr_flag_points = label_to_points.get("PWR_FLAG", [])
        assert len(pwr_flag_points) == 0, (
            f"PWR_FLAG pin positions must not appear in label_to_points "
            f"(would let BFS bridge unrelated rails). Got: {pwr_flag_points}"
        )

    def test_pwr_port_symbol_still_registers_in_both_maps(self) -> None:
        """Regression: power-port (#PWR*) symbols continue to feed both maps.

        Their Value *is* the net name, so BFS-via-label-jump correctly
        bridges multiple instances of the same named rail."""
        pwr_a = _make_power_symbol("#PWR001", "+BATT")
        pwr_b = _make_power_symbol("#PWR002", "+BATT")

        sch = MagicMock()
        sch.symbol = [pwr_a, pwr_b]
        for attr in ("label", "global_label"):
            if hasattr(sch, attr):
                delattr(sch, attr)

        pin_positions = {
            "#PWR001": {"1": (5.0, 5.0)},
            "#PWR002": {"1": (50.0, 50.0)},
        }

        with patch(
            "commands.pin_locator.PinLocator.get_all_symbol_pins",
            side_effect=lambda path, ref: pin_positions.get(ref, {}),
        ):
            point_to_label, label_to_points = _parse_virtual_connections(sch, "/fake/path", sexp=[])

        assert _to_iu(5.0, 5.0) in point_to_label
        assert _to_iu(50.0, 50.0) in point_to_label
        assert point_to_label[_to_iu(5.0, 5.0)] == "+BATT"
        # Both power-port pin positions appear under the shared "+BATT" key —
        # this is the correct behaviour for power ports.
        assert _to_iu(5.0, 5.0) in label_to_points.get("+BATT", [])
        assert _to_iu(50.0, 50.0) in label_to_points.get("+BATT", [])

    def test_pwr_flag_at_same_point_as_pwr_port_does_not_clobber_port_label(
        self,
    ) -> None:
        """Edge case: if a pwr-flag and a power-port symbol happen to share
        a pin coordinate, the power-port's net name must win in
        ``point_to_label`` so BFS-via-label-jump still resolves correctly
        for the rail."""
        pwr = _make_power_symbol("#PWR001", "+BATT")
        flg = _make_power_symbol("#FLG01", "PWR_FLAG")

        sch = MagicMock()
        # Order matters: the pwr-flag is processed AFTER the power port to
        # exercise the setdefault guard. Reversing the order would still pass
        # because the power port writes unconditionally — both orders are
        # acceptable, the point is the final state.
        sch.symbol = [pwr, flg]
        for attr in ("label", "global_label"):
            if hasattr(sch, attr):
                delattr(sch, attr)

        pin_positions = {
            "#PWR001": {"1": (7.0, 7.0)},
            "#FLG01": {"1": (7.0, 7.0)},  # same coordinate as the power port
        }

        with patch(
            "commands.pin_locator.PinLocator.get_all_symbol_pins",
            side_effect=lambda path, ref: pin_positions.get(ref, {}),
        ):
            point_to_label, label_to_points = _parse_virtual_connections(sch, "/fake/path", sexp=[])

        assert point_to_label[_to_iu(7.0, 7.0)] == "+BATT"
        assert _to_iu(7.0, 7.0) in label_to_points.get("+BATT", [])
        assert "PWR_FLAG" not in label_to_points


# Note: an end-to-end test that exercises ``_process_single_sheet`` would be
# a natural complement here, but it would require either (a) writing a real
# minimal .kicad_sch fixture containing power-port and pwr-flag symbol
# definitions, or (b) mocking enough of the sexp pipeline that the test no
# longer exercises real code. The unit-level tests above are sufficient to
# pin the fix: the BFS-via-label-jump mechanism in ``_find_connected_wires``
# uses ``label_to_points`` for the jump, so an empty ``label_to_points["PWR_FLAG"]``
# (proven by ``test_two_pwr_flags_do_not_share_a_label_to_points_entry``)
# is sufficient to guarantee no virtual bridging through pwr-flags.
