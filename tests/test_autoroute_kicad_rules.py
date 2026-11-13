"""autoroute passes the board's .kicad_dru and .kicad_pro to Freerouting (kicadRules).

A DSN carries only net-class clearances. Freerouting master after 2.5.0 reads a KiCad custom
rules file and project file given in -de (freerouting #1121, #1130); 2.5.0 logs them as unknown
and routes on. The log lines below are copied from real runs of both on the same board.
"""

import sys
import types
from unittest.mock import patch

import commands.freerouting as fr_mod
import pytest
from commands.freerouting import (
    _build_freerouting_cmd,
    _kicad_rules_report,
    _stage_kicad_rule_files,
)

from tests.test_autoroute_best_of_n import (  # noqa: F401  (fixtures)
    _java_on_path,
    _make_cmds,
    _make_ses,
    _patch_exec_mode,
    _ses_from_cmd,
    _stub_pcbnew,
    fake_jar,
    workdir,
)

pytestmark = pytest.mark.unit

# Freerouting master 01db81ca on a 6-layer board with a 40-rule .kicad_dru.
MASTER_LOG = """\
2026-11-13 13:05:53.412 INFO   Using the KiCad design rules of 'test.kicad_dru'.
2026-11-13 13:05:53.418 INFO   Using the KiCad project 'test.kicad_pro': minimum track width 150.0 um.
2026-11-13 13:05:56.296 WARN   [845FB3\\E32400] KiCad design rules: rule 'FP:J7-edge': constraint \
edge_clearance 0.2000 mm not translated (only minimum clearances are translated)
2026-11-13 13:05:56.296 WARN   [845FB3\\E32400] KiCad design rules: rule 'V:STRING-SMID1': constraint \
creepage 0.8000 mm not translated (Specctra has no creepage), only the clearance of 0.8000 mm of \
the rule applies
2026-11-13 13:05:56.297 WARN   [845FB3\\E32400] KiCad design rules: rule 'V:STRING-SMID1': constraint \
creepage 0.8000 mm not translated (Specctra has no creepage), only the clearance of 0.8000 mm of \
the rule applies
"""
# Freerouting 2.5.0, same command line.
RELEASE_LOG = """\
2026-11-13 13:04:57.006 WARN   Unknown file type in -de argument: test.kicad_dru. Expected .dsn, \
.json, .ses, or .rules
2026-11-13 13:04:57.007 WARN   Unknown file type in -de argument: test.kicad_pro. Expected .dsn, \
.json, .ses, or .rules
"""


def test_rule_files_are_staged_beside_the_dsn(tmp_path):
    board = tmp_path / "board dir" / "my board.kicad_pcb"
    board.parent.mkdir()
    board.write_text("(kicad_pcb)\n")
    (tmp_path / "board dir" / "my board.kicad_dru").write_text("(version 1)\n")
    staging = tmp_path / "staging"
    staging.mkdir()
    staged = _stage_kicad_rule_files(str(board), str(staging), "my board")
    assert staged == [str(staging / "my board.kicad_dru")]  # no .kicad_pro: none staged
    assert (staging / "my board.kicad_dru").read_text() == "(version 1)\n"


def test_files_follow_the_dsn_in_de():
    cmd = _build_freerouting_cmd(
        "/fr.jar",
        "/s/b.dsn",
        "/s/b.ses",
        5,
        False,
        design_files=["/s/b.kicad_dru", "/s/b.kicad_pro"],
    )
    de = cmd.index("-de")
    assert cmd[de + 1 : de + 4] == ["/s/b.dsn", "/s/b.kicad_dru", "/s/b.kicad_pro"]
    assert cmd[de + 4] == "-do"


def test_docker_sees_the_files_under_work(monkeypatch):
    monkeypatch.setattr(fr_mod, "_find_docker", lambda: "docker")
    cmd = _build_freerouting_cmd(
        "/fr.jar", "/s/b.dsn", "/s/b.ses", 5, True, design_files=["/s/b.kicad_dru"]
    )
    de = cmd.index("-de")
    assert cmd[de + 1 : de + 3] == ["/work/b.dsn", "/work/b.kicad_dru"]


def test_no_files_no_change():
    assert _build_freerouting_cmd("/fr.jar", "/s/b.dsn", "/s/b.ses", 5, False) == (
        _build_freerouting_cmd("/fr.jar", "/s/b.dsn", "/s/b.ses", 5, False, design_files=[])
    )


def test_report_from_master():
    r = _kicad_rules_report(MASTER_LOG, ["/s/test.kicad_dru", "/s/test.kicad_pro"])
    assert r["applied"] == ["test.kicad_dru", "test.kicad_pro"]
    assert r["ignored"] == []
    assert r["warningCount"] == 2  # the repeated line counts once
    assert r["warnings"][1].startswith("rule 'V:STRING-SMID1': constraint creepage 0.8000 mm")
    assert "note" not in r


def test_report_from_a_release_that_does_not_read_them():
    r = _kicad_rules_report(RELEASE_LOG, ["/s/test.kicad_dru", "/s/test.kicad_pro"])
    assert r["applied"] == []
    assert r["ignored"] == ["test.kicad_dru", "test.kicad_pro"]
    assert "KiCad's DRC" in r["note"]


def test_warnings_are_capped():
    log = "".join(f"WARN KiCad design rules: rule 'R{i}': not translated\n" for i in range(30))
    r = _kicad_rules_report(log, ["/s/test.kicad_dru"])
    assert r["warningCount"] == 30
    assert len(r["warnings"]) == 20


def _run(workdir, fake_jar, params, stdout="", returncode=0):
    cc = _make_cmds(workdir / "test.kicad_pcb")
    _patch_exec_mode(cc)
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        de = cmd.index("-de")
        seen["de"] = []
        for a in cmd[de + 1 :]:
            if a.startswith("-"):
                break
            seen["de"].append(a)
        seen["staged"] = {a: open(a).read() for a in seen["de"][1:]}
        if returncode == 0:
            _ses_from_cmd(cmd).write_text(_make_ses(num_nets=5))
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    with (
        patch.object(fr_mod, "subprocess") as sp,
        patch.dict(sys.modules, {"pcbnew": _stub_pcbnew()}),
    ):
        sp.run.side_effect = fake_run
        sp.TimeoutExpired = TimeoutError
        out = cc.autoroute(
            {
                "boardPath": str(workdir / "test.kicad_pcb"),
                "freeroutingJar": str(fake_jar),
                **params,
            }
        )
    return out, seen


@pytest.fixture()
def rules(workdir):
    (workdir / "test.kicad_dru").write_text(
        "(version 1)\n(rule HV (constraint clearance (min 3mm)))\n"
    )
    (workdir / "test.kicad_pro").write_text('{"board": {}}\n')
    return workdir


def test_autoroute_passes_the_boards_rule_files(rules, fake_jar):
    out, seen = _run(rules, fake_jar, {}, stdout=MASTER_LOG)
    assert out["success"], out
    assert [p.rsplit("/", 1)[-1] for p in seen["de"]] == [
        "test.dsn",
        "test.kicad_dru",
        "test.kicad_pro",
    ]
    # Copies in the staging directory, not the originals; the originals are untouched.
    assert all(not p.startswith(str(rules)) for p in seen["de"])
    assert "(rule HV" in list(seen["staged"].values())[0]
    assert (rules / "test.kicad_dru").read_text().startswith("(version 1)")
    assert out["kicad_rules"]["applied"] == ["test.kicad_dru", "test.kicad_pro"]


def test_autoroute_reports_files_a_release_ignored(rules, fake_jar):
    out, _ = _run(rules, fake_jar, {}, stdout=RELEASE_LOG)
    assert out["success"], out
    assert out["kicad_rules"]["ignored"] == ["test.kicad_dru", "test.kicad_pro"]


def test_kicad_rules_false_leaves_them_out(rules, fake_jar):
    out, seen = _run(rules, fake_jar, {"kicadRules": False})
    assert out["success"], out
    assert len(seen["de"]) == 1
    assert out["kicad_rules"] is None


def test_board_without_rule_files_is_unchanged(workdir, fake_jar):
    out, seen = _run(workdir, fake_jar, {})
    assert out["success"], out
    assert len(seen["de"]) == 1
    assert out["kicad_rules"] is None


def test_a_failed_run_names_the_rule_files(rules, fake_jar):
    out, _ = _run(rules, fake_jar, {}, stdout="ERROR cannot read 'test.kicad_dru'", returncode=1)
    assert out["success"] is False
    assert "kicadRules: false" in out["hint"]
    assert out["kicad_rules"]["files"] == ["test.kicad_dru", "test.kicad_pro"]
