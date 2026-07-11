"""Tests for the best-of-N scoring in autoroute (`_score_ses`).

Best-of-N support is ported from morningfire-pcb-automation
(https://github.com/NiNjA-CodE/morningfire-pcb-automation,
scripts/routing/freeroute_runner.py::score_ses). These tests pin the
scoring contract so future changes don't silently shift the ranking.
"""
import sys
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

from kicad_mcp.commands.freerouting import _score_ses  # noqa: E402


def _ses(nets, segments, vias=0):
    """Build a minimal SES text with the given (net, segment_count) shape.

    The parser only looks at `(net NAME\n  (wire` occurrences and `(wire`
    / `(via ` substrings, so a synthetic fixture is enough.
    """
    chunks = []
    for net, seg_count in nets:
        chunks.append(f'(net "{net}"\n')
        for _ in range(seg_count):
            chunks.append("  (wire (path F.Cu 200 0 0 1 1))\n")
        chunks.append(")\n")
    # Tack on extra wires not tied to a (net ...) header — counted as
    # segments but not as nets.
    for _ in range(segments - sum(s for _, s in nets)):
        chunks.append("  (wire (path F.Cu 200 0 0 1 1))\n")
    for _ in range(vias):
        chunks.append('  (via "Via[0-1]_600:300_um" 100 200)\n')
    return "".join(chunks)


@pytest.mark.unit
def test_empty_ses_scores_zero():
    r = _score_ses("", [])
    assert r["score"] == 0
    assert r["nets"] == 0
    assert r["segments"] == 0


@pytest.mark.unit
def test_more_nets_always_beats_more_segments():
    """A single extra net (1000 pts) must beat any reasonable seg count delta."""
    a = _score_ses(_ses([("N1", 50), ("N2", 50), ("N3", 50)], segments=150), [])
    b = _score_ses(_ses([("N1", 50), ("N2", 50)], segments=999), [])
    assert a["nets"] == 3 and b["nets"] == 2
    assert a["score"] > b["score"], "+1 net (1000 pts) must dominate segment delta"


@pytest.mark.unit
def test_segments_break_ties_when_net_counts_equal():
    a = _score_ses(_ses([("N1", 10), ("N2", 10)], segments=20), [])
    b = _score_ses(_ses([("N1", 30), ("N2", 30)], segments=60), [])
    assert a["nets"] == b["nets"] == 2
    assert b["score"] > a["score"], "more segments breaks tie when net counts equal"


@pytest.mark.unit
def test_target_bonus_dominates_when_all_targets_routed():
    """The 50,000-point bonus must outweigh marginal nets/segments differences."""
    # `with_targets` has the targets but fewer overall nets.
    with_targets = _score_ses(
        _ses([("CRITICAL_A", 10), ("CRITICAL_B", 10)], segments=20),
        target_nets=["CRITICAL_A", "CRITICAL_B"],
    )
    # `without_targets` has more nets but is missing one target.
    without_targets = _score_ses(
        _ses([
            ("CRITICAL_A", 10),
            ("OTHER1", 10), ("OTHER2", 10), ("OTHER3", 10),
            ("OTHER4", 10), ("OTHER5", 10), ("OTHER6", 10),
        ], segments=70),
        target_nets=["CRITICAL_A", "CRITICAL_B"],
    )
    assert without_targets["targets_missing"] == ["CRITICAL_B"]
    assert with_targets["targets_missing"] == []
    assert with_targets["score"] > without_targets["score"], (
        "all-targets bonus must beat marginal net-count gain"
    )


@pytest.mark.unit
def test_target_bonus_inactive_when_targets_unspecified():
    """No targets configured -> score == nets*1000 + segments (no bonus)."""
    r = _score_ses(_ses([("X", 5)], segments=5), [])
    assert r["score"] == 1000 + 5
    assert r["targets_found"] == [] and r["targets_missing"] == []


@pytest.mark.unit
def test_quoted_net_names_in_ses_are_normalised():
    """Freerouting writes nets as `(net "X"` — surrounding quotes must be stripped."""
    text = '(net "MY_NET"\n  (wire (path F.Cu 200 0 0 1 1))\n)\n'
    r = _score_ses(text, target_nets=["MY_NET"])
    assert r["targets_missing"] == [], "quoted net name should match unquoted target"
    assert r["targets_found"] == ["MY_NET"]


@pytest.mark.unit
def test_targets_missing_and_found_are_sorted_for_stable_output():
    text = _ses(
        [("Z_NET", 1), ("A_NET", 1), ("M_NET", 1)],
        segments=3,
    )
    r = _score_ses(text, target_nets=["Z_NET", "A_NET", "MISSING_X", "MISSING_A"])
    assert r["targets_found"] == ["A_NET", "Z_NET"]
    assert r["targets_missing"] == ["MISSING_A", "MISSING_X"]


@pytest.mark.unit
def test_via_count_is_reported_independently_of_score():
    r = _score_ses(_ses([("X", 2)], segments=2, vias=7), [])
    assert r["vias"] == 7
    # Score formula does NOT include vias by design.
    assert r["score"] == 1 * 1000 + 2
