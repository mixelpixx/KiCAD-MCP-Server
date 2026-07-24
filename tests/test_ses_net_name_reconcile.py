"""Regression tests for issue #246:

    Freerouting SES import strips leading '/' from global net names

KiCad global-label nets are named with a leading '/' (e.g. ``/GND``). A Specctra
DSN round-trip through Freerouting can drop that prefix, so ``ImportSpecctraSES``
fails its exact-string net lookup and creates a phantom slashless net, leaving
the real ``/GND`` unconnected. ``_reconcile_ses_net_names`` repairs the SES text
before import by re-adding the '/' to any net that matches a board net only when
prefixed.

These tests exercise that pure text-rewrite against the real SES token format
``(net "NAME" ...`` (the pcbnew import + board-net enumeration are a thin shell
validated end-to-end by the maintainer).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.freerouting import _reconcile_ses_net_names  # noqa: E402

BOARD_NETS = ["", "/GND", "/3V3", "/VIN_FUSED", "SIGNAL_NO_SLASH"]


def _ses(*net_names: str) -> str:
    """A minimal SES body with one (net "NAME" (wire ...)) block per name."""
    blocks = [f'(net "{n}"\n  (wire (path F.Cu 200 0 0 1 1))\n)\n' for n in net_names]
    return "(session test\n  (routes\n    (network_out\n" + "".join(blocks) + "    )\n  )\n)\n"


def test_slashless_global_net_is_reprefixed():
    text, remapped = _reconcile_ses_net_names(_ses("GND"), BOARD_NETS)
    assert '(net "/GND"' in text
    assert '(net "GND"' not in text
    assert remapped == ["GND"]


def test_already_slashed_name_is_untouched():
    text, remapped = _reconcile_ses_net_names(_ses("/GND"), BOARD_NETS)
    assert '(net "/GND"' in text
    assert remapped == []  # idempotent


def test_net_that_is_genuinely_slashless_on_board_is_left_alone():
    # Board has SIGNAL_NO_SLASH with no slash, so it must not be rewritten.
    text, remapped = _reconcile_ses_net_names(_ses("SIGNAL_NO_SLASH"), BOARD_NETS)
    assert '(net "SIGNAL_NO_SLASH"' in text
    assert '(net "/SIGNAL_NO_SLASH"' not in text
    assert remapped == []


def test_unknown_net_is_left_alone():
    # Neither MYSTERY nor /MYSTERY is on the board -> no change.
    text, remapped = _reconcile_ses_net_names(_ses("MYSTERY"), BOARD_NETS)
    assert '(net "MYSTERY"' in text
    assert remapped == []


def test_multiple_nets_mixed():
    text, remapped = _reconcile_ses_net_names(
        _ses("GND", "3V3", "VIN_FUSED", "MYSTERY"), BOARD_NETS
    )
    assert '(net "/GND"' in text
    assert '(net "/3V3"' in text
    assert '(net "/VIN_FUSED"' in text
    assert '(net "MYSTERY"' in text  # untouched
    assert sorted(remapped) == ["3V3", "GND", "VIN_FUSED"]


def test_wire_payload_is_preserved():
    text, _ = _reconcile_ses_net_names(_ses("GND"), BOARD_NETS)
    # Only the net token changes; routing geometry is untouched.
    assert "(wire (path F.Cu 200 0 0 1 1))" in text


def test_empty_board_net_list_changes_nothing():
    original = _ses("GND")
    text, remapped = _reconcile_ses_net_names(original, [])
    assert text == original
    assert remapped == []
