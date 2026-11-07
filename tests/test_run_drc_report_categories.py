"""run_drc read only the "violations" list of kicad-cli's JSON report. kicad-cli writes
missing connections to "unconnected_items" and schematic mismatches to "schematic_parity",
so a board with unrouted nets reported none of them, and each violation lost the items it
names (which pad, which track, their UUIDs). It also ran DRC on whatever zone fill was saved,
unlike the DRC dialog, whose default is to refill first.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.design_rules import DesignRuleCommands  # noqa: E402

REPORT = {
    "date": "2026-11-04",
    "violations": [
        {
            "type": "shorting_items",
            "severity": "error",
            "description": "Items shorting two nets (nets A and B)",
            "items": [
                {
                    "description": "Via [A] on F.Cu - B.Cu",
                    "pos": {"x": 1.0, "y": 2.0},
                    "uuid": "u-via",
                },
                {
                    "description": "Pad 3 [B] of U1 on F.Cu",
                    "pos": {"x": 1.1, "y": 2.1},
                    "uuid": "u-pad",
                },
            ],
        }
    ],
    "unconnected_items": [
        {
            "type": "unconnected_items",
            "severity": "error",
            "description": "Missing connection between items",
            "items": [
                {
                    "description": "Pad 2 [C] of U1 on F.Cu",
                    "pos": {"x": 3.0, "y": 4.0},
                    "uuid": "u-p2",
                },
                {"description": "Track [C] on F.Cu", "pos": {"x": 3.5, "y": 4.0}, "uuid": "u-t"},
            ],
        }
    ],
    "schematic_parity": [
        {
            "type": "missing_footprint",
            "severity": "warning",
            "description": "Missing footprint R9",
            "items": [],
        }
    ],
}


def test_parse_reads_all_three_report_lists():
    v, by_type, by_sev, by_cat = DesignRuleCommands._parse_drc_report(REPORT)
    assert len(v) == 3
    assert by_cat == {"violations": 1, "unconnected_items": 1, "schematic_parity": 1}
    assert by_type["unconnected_items"] == 1
    assert by_sev == {"error": 2, "warning": 1, "info": 0}


def test_parse_keeps_the_items_a_violation_names():
    v, *_ = DesignRuleCommands._parse_drc_report(REPORT)
    short = v[0]
    assert short["category"] == "violations"
    assert [i["uuid"] for i in short["items"]] == ["u-via", "u-pad"]
    assert short["items"][1]["description"].startswith("Pad 3 [B]")
    assert short["location"] == {"x": 1.0, "y": 2.0, "unit": "mm"}
    assert v[2]["location"] == {"x": 0, "y": 0, "unit": "mm"}  # no items: location stays 0,0


def test_parse_tolerates_missing_or_null_lists():
    v, by_type, by_sev, by_cat = DesignRuleCommands._parse_drc_report({"violations": None})
    assert v == [] and by_type == {} and by_cat == {}


def test_flags_refill_by_default_and_parity_on_request():
    assert DesignRuleCommands._drc_flags({}) == ["--refill-zones"]
    assert DesignRuleCommands._drc_flags({"refillZones": False}) == []
    assert DesignRuleCommands._drc_flags({"schematicParity": True}) == [
        "--refill-zones",
        "--schematic-parity",
    ]


def _commands(
    tmp_path, monkeypatch, help_text, runs, report=REPORT, stdout="", rc=0, with_sch=True
):
    """DesignRuleCommands on a stub board, with kicad-cli faked: `--help` prints help_text,
    a check writes `report` to --output; every call is appended to `runs`."""
    import subprocess

    board_file = tmp_path / "b.kicad_pcb"
    board_file.write_text("(kicad_pcb)")
    if with_sch:
        (tmp_path / "b.kicad_sch").write_text("(kicad_sch)")
    DesignRuleCommands._refill_support = {}
    cmds = DesignRuleCommands.__new__(DesignRuleCommands)
    cmds.board = MagicMock()
    cmds.board.GetFileName.return_value = str(board_file)
    monkeypatch.setattr(cmds, "_find_kicad_cli", lambda: "kicad-cli")

    def fake_run(cmd, **kw):
        runs.append(cmd)
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout=help_text, stderr="")
        out = cmd[cmd.index("--output") + 1]
        if "json" in cmd and rc == 0:
            Path(out).write_text(json.dumps(report))
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return cmds, board_file


KICAD10_HELP = "Usage: drc [--help] [--refill-zones] [--save-board] [--schematic-parity] INPUT_FILE"
KICAD9_HELP = "Usage: drc [--help] [--schematic-parity] INPUT_FILE"


def test_run_drc_passes_flags_and_reports_unconnected(tmp_path, monkeypatch):
    runs = []
    cmds, board_file = _commands(tmp_path, monkeypatch, KICAD10_HELP, runs)
    res = cmds.run_drc({"schematicParity": True})
    assert res["success"], res
    check = [c for c in runs if "--help" not in c][0]
    assert "--refill-zones" in check and "--schematic-parity" in check
    assert check[-1] == str(board_file)  # board file stays the last argument
    assert res["summary"]["total"] == 3
    assert res["summary"]["by_category"]["unconnected_items"] == 1
    assert res["zonesRefilled"] is True
    assert any("not saved" in n for n in res["notes"]), res["notes"]
    assert res["warnings"] == []
    saved = json.loads(Path(res["violationsFile"]).read_text())
    assert saved["violations"][1]["category"] == "unconnected_items"
    assert saved["violations"][1]["items"][0]["uuid"] == "u-p2"


def test_run_drc_without_refill_support_runs_on_saved_fills(tmp_path, monkeypatch):
    """KiCad 8/9 kicad-cli has no --refill-zones: passing it fails every run_drc."""
    runs = []
    cmds, _ = _commands(tmp_path, monkeypatch, KICAD9_HELP, runs)
    res = cmds.run_drc({})
    assert res["success"], res
    assert not any("--refill-zones" in c for c in runs if "--help" not in c)
    assert res["zonesRefilled"] is False
    assert any("saved in the board file" in n for n in res["notes"]), res["notes"]
    assert res["summary"]["by_category"]["unconnected_items"] == 1  # still reported
    # the version probe is cached per kicad-cli path
    cmds.run_drc({})
    assert sum(1 for c in runs if "--help" in c) == 1


def test_run_drc_refill_off_skips_the_probe(tmp_path, monkeypatch):
    runs = []
    cmds, _ = _commands(tmp_path, monkeypatch, KICAD10_HELP, runs)
    res = cmds.run_drc({"refillZones": False})
    assert res["zonesRefilled"] is False and res["notes"] == []
    assert not any("--help" in c for c in runs)


def test_run_drc_failure_reports_stdout_when_stderr_is_empty(tmp_path, monkeypatch):
    runs = []
    cmds, _ = _commands(
        tmp_path,
        monkeypatch,
        KICAD10_HELP,
        runs,
        rc=1,
        stdout="Unknown argument: --bogus\nUsage: drc ...",
    )
    res = cmds.run_drc({})
    assert res["success"] is False
    assert "Unknown argument" in res["errorDetails"]


def test_parity_without_a_schematic_warns(tmp_path, monkeypatch):
    runs = []
    cmds, _ = _commands(
        tmp_path,
        monkeypatch,
        KICAD10_HELP,
        runs,
        with_sch=False,
        stdout="Failed to fetch schematic netlist for parity tests.",
    )
    res = cmds.run_drc({"schematicParity": True})
    assert res["success"], res
    assert len(res["warnings"]) == 1 and "did not run" in res["warnings"][0]


def test_flags_respect_refill_support():
    assert DesignRuleCommands._drc_flags({}, refill_supported=False) == []
    assert DesignRuleCommands._drc_flags({"schematicParity": True}, False) == ["--schematic-parity"]
