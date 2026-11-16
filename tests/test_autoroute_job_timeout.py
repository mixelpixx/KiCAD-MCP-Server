"""autoroute gives Freerouting a time budget of its own (--router.job_timeout).

Freerouting writes its session file only when it ends. A run that reached the
subprocess timeout was killed and returned nothing, however much it had routed
(a 6-layer board: 40 minutes of routing lost, 91 connections still open). With
a job timeout the router stops by itself and the partial result is imported.
"""

import sys
import types
from unittest.mock import patch

import commands.freerouting as fr_mod
import pytest
from commands.freerouting import _build_freerouting_cmd, _hms, _router_time_budget

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


@pytest.mark.parametrize(
    "seconds, text",
    [
        (1, "00:00:01"),
        (270, "00:04:30"),
        (3600, "01:00:00"),
        (3725, "01:02:05"),
        (90000, "25:00:00"),
    ],
)
def test_hms(seconds, text):
    assert _hms(seconds) == text


@pytest.mark.parametrize(
    "timeout, requested, budget",
    [
        (900, None, 810),  # a tenth of the wait is the margin
        (300, None, 240),  # margin never under 60 s (Freerouting's 30 s grace + JVM/DSN start)
        (3600, None, 3480),  # margin never over 120 s
        (300, 100, 100),  # the caller's value
        (300, 299, 240),  # capped below the wait, or the kill would come first
        (300, 0, None),  # 0: no budget passed
        (60, None, None),  # nothing left after the margin
        (61, None, None),  # a default budget shorter than the margin is not passed
        (119, None, None),
        (120, None, 60),  # from here the default budget is at least the margin
        (100, 30, 30),  # an explicit jobTimeout still fits under a short wait
        (60, 30, None),  # no room at all: dropped (the kill message says why)
        (300, "abc", 240),  # not a number: the default
        (None, None, None),
    ],
)
def test_router_time_budget(timeout, requested, budget):
    assert _router_time_budget(timeout, requested) == budget


def test_command_carries_the_job_timeout():
    with (
        patch.object(fr_mod, "_find_java", return_value="/usr/bin/java"),
        patch.object(fr_mod, "_jar_required_java", return_value=21),
    ):
        with_budget = _build_freerouting_cmd(
            "/x/fr.jar", "/w/a.dsn", "/w/a.ses", 20, False, job_timeout=270
        )
        without = _build_freerouting_cmd("/x/fr.jar", "/w/a.dsn", "/w/a.ses", 20, False)
    assert "--router.job_timeout=00:04:30" in with_budget
    assert not [a for a in without if a.startswith("--router.job_timeout")]


def _run(workdir, fake_jar, params, stdout):
    cc = _make_cmds(workdir / "test.kicad_pcb")
    _patch_exec_mode(cc)
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        seen["timeout"] = kw.get("timeout")
        _ses_from_cmd(cmd).write_text(_make_ses(num_nets=5))
        return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")

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


def test_autoroute_passes_a_budget_shorter_than_the_wait(workdir, fake_jar):
    out, seen = _run(
        workdir, fake_jar, {"timeout": 600}, "Auto-routing stage completed: 0 unrouted"
    )
    assert out["success"], out
    assert "--router.job_timeout=00:09:00" in seen["cmd"]
    assert seen["timeout"] == 600  # the wait itself is unchanged
    assert out["job_timeout_seconds"] == 540
    assert out["time_budget_reached"] is False


def test_partial_result_is_imported_and_reported(workdir, fake_jar):
    """The router stopped at its budget: the SES is imported and the reply says so."""
    out, _ = _run(
        workdir,
        fake_jar,
        {"timeout": 600},
        "Auto-routing stage completed with timeout: started with 49 unrouted nets, 16 unrouted",
    )
    assert out["success"], out
    assert out["time_budget_reached"] is True


def test_job_timeout_zero_passes_no_budget(workdir, fake_jar):
    out, seen = _run(workdir, fake_jar, {"timeout": 600, "jobTimeout": 0}, "ok")
    assert out["success"], out
    assert not [a for a in seen["cmd"] if a.startswith("--router.job_timeout")]
    assert out["job_timeout_seconds"] is None


def test_kill_message_says_nothing_was_kept(workdir, fake_jar):
    cc = _make_cmds(workdir / "test.kicad_pcb")
    _patch_exec_mode(cc)
    with (
        patch.object(fr_mod, "subprocess") as sp,
        patch.dict(sys.modules, {"pcbnew": _stub_pcbnew()}),
    ):
        sp.TimeoutExpired = TimeoutError
        sp.run.side_effect = TimeoutError()
        out = cc.autoroute(
            {
                "boardPath": str(workdir / "test.kicad_pcb"),
                "freeroutingJar": str(fake_jar),
                "timeout": 600,
            }
        )
    assert out["success"] is False
    assert "timed out after 600s" in out["message"]
    assert "Nothing it routed was kept" in out["errorDetails"]
    assert "540s" in out["errorDetails"]


@pytest.mark.parametrize(
    "params, says",
    [
        ({"timeout": 60, "jobTimeout": 30}, "The jobTimeout of 30s was not passed"),
        ({"timeout": 90}, "a timeout under 120s leaves no room"),
        ({"timeout": 600, "jobTimeout": 0}, "(jobTimeout: 0)"),
    ],
)
def test_kill_message_says_why_no_budget_was_passed(workdir, fake_jar, params, says):
    cc = _make_cmds(workdir / "test.kicad_pcb")
    _patch_exec_mode(cc)
    with (
        patch.object(fr_mod, "subprocess") as sp,
        patch.dict(sys.modules, {"pcbnew": _stub_pcbnew()}),
    ):
        sp.TimeoutExpired = TimeoutError
        sp.run.side_effect = TimeoutError()
        out = cc.autoroute(
            {
                "boardPath": str(workdir / "test.kicad_pcb"),
                "freeroutingJar": str(fake_jar),
                **params,
            }
        )
    assert out["success"] is False
    assert says in out["errorDetails"], out["errorDetails"]
    assert "Nothing it routed was kept" in out["errorDetails"]
