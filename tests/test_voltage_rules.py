"""set_voltage_clearance_rules: clearance/creepage graded by working voltage.

Unit tests for the planner, renderer and file edit, plus a real-KiCad test
(``KICAD_USE_REAL_PCBNEW=1``) in which ``kicad-cli pcb drc`` is the oracle.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from utils.voltage_rules import (  # noqa: E402
    BEGIN,
    END,
    VoltageRuleError,
    check_balanced,
    normalise_table,
    plan_rules,
    render_block,
    replace_block,
    write_rules,
)

TABLE = [
    {"upTo": 50, "clearance": 0.2},
    {"upTo": 400, "clearance": 1.0, "creepage": 2.0},
    {"upTo": 800, "clearance": 3.0, "creepage": 5.0},
]
CLASSES = [
    {"name": "STACK", "voltage": 800},
    {"name": "MODULE", "voltage": 400},
]


def _by_pair(plan):
    return {(e["a"], e["b"]): e for e in plan}


# --- planning --------------------------------------------------------------- #


@pytest.mark.unit
def test_working_voltage_is_the_difference_and_picks_the_covering_row():
    plan = _by_pair(plan_rules(CLASSES, TABLE))
    assert plan[("STACK", "MODULE")]["voltage"] == 400
    assert plan[("STACK", "MODULE")]["clearance"] == 1.0
    assert plan[("STACK", "(other nets)")]["clearance"] == 3.0
    assert plan[("MODULE", "(other nets)")]["creepage"] == 2.0


@pytest.mark.unit
def test_pair_override_replaces_the_difference():
    plan = _by_pair(
        plan_rules(CLASSES, TABLE, pairs=[{"a": "MODULE", "b": "STACK", "voltage": 800}])
    )
    e = plan[("STACK", "MODULE")]
    assert (e["voltage"], e["source"], e["clearance"]) == (800, "pair", 3.0)


@pytest.mark.unit
def test_other_nets_rules_can_be_skipped():
    plan = plan_rules(CLASSES, TABLE, other_nets_voltage=None)
    assert [(e["a"], e["b"]) for e in plan] == [("STACK", "MODULE")]


@pytest.mark.unit
@pytest.mark.parametrize(
    "classes,table,pairs,match",
    [
        ([{"name": "X", "voltage": 900}], TABLE, None, "above the spacing table"),
        (
            CLASSES,
            [{"upTo": 50, "clearance": 1.0}, {"upTo": 400, "clearance": 0.5}],
            None,
            "cannot need less",
        ),
        ([{"name": "A'B", "voltage": 1}], TABLE, None, "contains one of"),
        (CLASSES + [{"name": "STACK", "voltage": 1}], TABLE, None, "listed twice"),
        (CLASSES, TABLE, [{"a": "STACK", "b": "NOPE", "voltage": 1}], "not in classes"),
        (CLASSES, [], None, "at least one row"),
        ([{"name": "X", "voltage": -5}], TABLE, None, "must not be negative"),
    ],
)
def test_bad_input_is_refused_with_a_reason(classes, table, pairs, match):
    with pytest.raises(VoltageRuleError, match=match):
        plan_rules(classes, table, pairs)


@pytest.mark.unit
def test_table_is_sorted_by_voltage():
    rows = normalise_table(list(reversed(TABLE)))
    assert [r["upTo"] for r in rows] == [50, 400, 800]


# --- rendering and file edit -------------------------------------------------- #


@pytest.mark.unit
def test_rendered_block_parses_and_names_every_rule():
    block = render_block(plan_rules(CLASSES, TABLE), ["STACK", "MODULE"])
    assert check_balanced(block) is None
    assert '(rule "V:STACK-MODULE"' in block
    assert "(condition \"A.hasNetclass('STACK') && B.hasNetclass('MODULE')\")" in block
    assert "!(B.hasNetclass('STACK') || B.hasNetclass('MODULE'))" in block
    assert "(constraint creepage (min 5mm))" in block


@pytest.mark.unit
def test_check_balanced_ignores_parens_in_strings_and_comments():
    assert check_balanced('(rule "a)" # stray ) here\n (x))') is None
    assert "unclosed" in check_balanced("(rule (x)")
    assert "unexpected" in check_balanced("(x))")


@pytest.mark.unit
def test_rerun_replaces_the_block_and_keeps_hand_rules(tmp_path):
    dru = tmp_path / "b.kicad_dru"
    hand = '(version 1)\n(rule "mine" (constraint clearance (min 0.3mm)))\n'
    dru.write_text(hand)
    write_rules(str(dru), render_block(plan_rules(CLASSES, TABLE), ["STACK", "MODULE"]))
    write_rules(str(dru), render_block(plan_rules(CLASSES[:1], TABLE), ["STACK"]))
    text = dru.read_text()
    assert text.count(BEGIN) == 1 and text.count(END) == 1
    assert '(rule "mine"' in text
    assert "V:STACK-MODULE" not in text  # from the first run, replaced
    assert text.rstrip().endswith(END)  # block last, so later hand rules can't override it
    assert check_balanced(text) is None


@pytest.mark.unit
def test_refuses_to_write_into_a_file_that_does_not_parse(tmp_path):
    dru = tmp_path / "b.kicad_dru"
    broken = '(version 1)\n(rule "mine" (constraint clearance (min 0.3mm))\n'
    dru.write_text(broken)
    with pytest.raises(VoltageRuleError, match="silently ignores"):
        write_rules(str(dru), render_block(plan_rules(CLASSES, TABLE), ["STACK", "MODULE"]))
    assert dru.read_text() == broken


@pytest.mark.unit
def test_replace_block_creates_the_version_header_for_a_new_file():
    out = replace_block("", "BLOCK")
    assert out.startswith("(version 1)") and out.rstrip().endswith("BLOCK")


# --- real KiCad: kicad-cli DRC is the oracle ---------------------------------- #


def _board(tmp_path, outline=True):
    """Four parallel F.Cu tracks 2.0 mm apart (1.75 mm edge to edge): STACK, MODULE, MODULE2, LOGIC.

    Classes by pattern in the .kicad_pro: STACK (800 V), MODULE (400 V), MOD2 (400 V);
    LOGIC is in no listed class.
    """
    import pcbnew

    board_path = tmp_path / "v.kicad_pcb"
    board = pcbnew.BOARD()
    for n, y in (("STACKNET", 10.0), ("MODNET", 12.0), ("MOD2NET", 14.0), ("LOGICNET", 16.0)):
        board.Add(pcbnew.NETINFO_ITEM(board, n))
        t = pcbnew.PCB_TRACK(board)
        t.SetLayer(pcbnew.F_Cu)
        t.SetStart(pcbnew.VECTOR2I(0, pcbnew.FromMM(y)))
        t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(20), pcbnew.FromMM(y)))
        t.SetWidth(pcbnew.FromMM(0.25))
        t.SetNet(board.FindNet(n))
        board.Add(t)
    if outline:
        for x1, y1, x2, y2 in ((-5, 0, 25, 0), (25, 0, 25, 20), (25, 20, -5, 20), (-5, 20, -5, 0)):
            s = pcbnew.PCB_SHAPE(board)
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
            s.SetLayer(pcbnew.Edge_Cuts)
            s.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
            s.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x2), pcbnew.FromMM(y2)))
            board.Add(s)
    pcbnew.SaveBoard(str(board_path), board)
    nc = {"clearance": 0.2, "track_width": 0.25, "via_diameter": 0.6, "via_drill": 0.3}
    pro = {
        "board": {"design_settings": {"rules": {"min_clearance": 0.1}}},
        "net_settings": {
            "classes": [{"name": n, **nc} for n in ("Default", "STACK", "MODULE", "MOD2")],
            "meta": {"version": 4},
            "netclass_patterns": [
                {"netclass": "STACK", "pattern": "STACKNET"},
                {"netclass": "MODULE", "pattern": "MODNET"},
                {"netclass": "MOD2", "pattern": "MOD2NET"},
            ],
        },
    }
    (tmp_path / "v.kicad_pro").write_text(json.dumps(pro))
    return board_path


def _rule_violations(board_path):
    rep = board_path.with_suffix(".drc.json")
    subprocess.run(
        ["kicad-cli", "pcb", "drc", "--format", "json", "-o", str(rep), str(board_path)],
        capture_output=True,
        check=True,
    )
    found = set()
    for v in json.loads(rep.read_text())["violations"]:
        if v["type"] in ("clearance", "creepage") and "rule 'V:" in v["description"]:
            rule = v["description"].split("rule '")[1].split("'")[0]
            found.add((v["type"], rule))
    return found


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_kicad_enforces_the_graded_rules(tmp_path):
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1" or not shutil.which("kicad-cli"):
        pytest.skip("needs KICAD_USE_REAL_PCBNEW=1 and kicad-cli")
    from commands.design_rules import DesignRuleCommands

    board_path = _board(tmp_path)
    # Adjacent pairs at 1.75 mm: STACK-MODULE (400 V -> 1.0 mm, creepage 2.0 mm),
    # MODULE-MOD2 (0 V -> 0.2 mm), MOD2-LOGIC (400 V vs other -> 1.0 / 2.0 mm).
    r = DesignRuleCommands().set_voltage_clearance_rules(
        {
            "boardPath": str(board_path),
            "classes": [
                {"name": "STACK", "voltage": 800},
                {"name": "MODULE", "voltage": 400},
                {"name": "MOD2", "voltage": 400},
            ],
            "spacing": TABLE,
        }
    )
    assert r["success"], r
    assert r["warnings"] == []
    found = _rule_violations(board_path)
    assert ("creepage", "V:STACK-MODULE") in found  # 1.75 < 2.0 creepage
    assert ("clearance", "V:STACK-MODULE") not in found  # 1.75 > 1.0 clearance
    assert ("creepage", "V:MOD2-other") in found
    assert not any("MODULE-MOD2" in rule for _, rule in found)  # same potential: 0.2 mm

    # A STACK-MODULE override to 800 V makes the clearance fail too.
    r = DesignRuleCommands().set_voltage_clearance_rules(
        {
            "boardPath": str(board_path),
            "classes": [{"name": "STACK", "voltage": 800}, {"name": "MODULE", "voltage": 400}],
            "pairs": [{"a": "STACK", "b": "MODULE", "voltage": 800}],
            "spacing": TABLE,
            "otherNetsVoltage": None,
        }
    )
    assert r["success"], r
    found = _rule_violations(board_path)
    assert ("clearance", "V:STACK-MODULE") in found  # 1.75 < 3.0
    assert not any("MOD2" in rule for _, rule in found)  # replaced block has no MOD2 rules


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_unknown_class_is_reported(tmp_path):
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
        pytest.skip("needs KICAD_USE_REAL_PCBNEW=1")
    from commands.design_rules import DesignRuleCommands

    board_path = _board(tmp_path)
    r = DesignRuleCommands().set_voltage_clearance_rules(
        {
            "boardPath": str(board_path),
            "classes": [{"name": "STACK", "voltage": 800}, {"name": "TYPO", "voltage": 0}],
            "spacing": TABLE,
            "dryRun": True,
        }
    )
    assert r["success"] and "TYPO" in " ".join(r["warnings"])
    assert not board_path.with_suffix(".kicad_dru").exists()  # dry run wrote nothing


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_creepage_without_a_board_outline_is_warned(tmp_path):
    """kicad-cli DRC 10.0.8 segfaults on a creepage rule when there is no outline."""
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
        pytest.skip("needs KICAD_USE_REAL_PCBNEW=1")
    from commands.design_rules import DesignRuleCommands

    board_path = _board(tmp_path, outline=False)
    r = DesignRuleCommands().set_voltage_clearance_rules(
        {"boardPath": str(board_path), "classes": CLASSES, "spacing": TABLE, "dryRun": True}
    )
    assert any("Edge.Cuts" in w for w in r["warnings"])
    no_creepage = [{"upTo": 800, "clearance": 3.0}]
    r = DesignRuleCommands().set_voltage_clearance_rules(
        {"boardPath": str(board_path), "classes": CLASSES, "spacing": no_creepage, "dryRun": True}
    )
    assert not any("Edge.Cuts" in w for w in r["warnings"])
