"""autoroute passes Freerouting settings through: routerSettings -> --router.<name>=<value>.

Freerouting has per-run settings autoroute had no parameter for: classes to route first
(priority_net_classes), one via per plane pad (plane_as_priority), classes to leave alone.
"""

import sys
import types
from unittest.mock import patch

import pytest

import commands.freerouting as fr_mod
from commands.freerouting import _build_freerouting_cmd, _router_setting_args
from tests.test_autoroute_best_of_n import (  # noqa: F401  (fixtures)
    _make_cmds,
    _make_ses,
    _patch_exec_mode,
    _ses_from_cmd,
    _stub_pcbnew,
    fake_jar,
    workdir,
)

pytestmark = pytest.mark.unit


def test_settings_become_router_options():
    args = _router_setting_args(
        {
            "autorouter.priority_net_classes": ["DIFF", "ANALOG"],
            "autorouter.plane_as_priority": True,
            "via_costs": 42,
            "plane_via_costs": 2.5,
            "autorouter.ignore_net_classes": "HV",
        }
    )
    assert args == [
        "--router.autorouter.priority_net_classes=DIFF,ANALOG",
        "--router.autorouter.plane_as_priority=true",
        "--router.via_costs=42",
        "--router.plane_via_costs=2.5",
        "--router.autorouter.ignore_net_classes=HV",
    ]


def test_no_settings_no_options():
    assert _router_setting_args(None) == []
    assert _router_setting_args({}) == []


@pytest.mark.parametrize(
    "settings, fragment",
    [
        ({"via_costs=1 -de /etc/passwd": 1}, "not a Freerouting setting name"),
        ({"--gui.enabled": True}, "not a Freerouting setting name"),
        ({"Autorouter.MaxPasses": 3}, "not a Freerouting setting name"),
        ({"": 1}, "not a Freerouting setting name"),
        ({"job_timeout": "00:01:00"}, "jobTimeout"),
        ({"max_passes": 5}, "maxPasses"),
        ({"autorouter.max_passes": 5}, "maxPasses"),
        ({"via_costs": None}, "not a string, number or boolean"),
        ({"via_costs": {"a": 1}}, "not a string, number or boolean"),
        ({"autorouter.priority_net_classes": []}, "empty list"),
        ({"autorouter.priority_net_classes": ["A", ""]}, "not a string, number or boolean"),
        (["via_costs"], "must be an object"),
    ],
)
def test_bad_settings_are_refused(settings, fragment):
    with pytest.raises(ValueError) as e:
        _router_setting_args(settings)
    assert fragment in str(e.value)


def test_command_carries_the_options_after_the_fixed_ones():
    with (
        patch.object(fr_mod, "_find_java", return_value="/usr/bin/java"),
        patch.object(fr_mod, "_jar_required_java", return_value=21),
    ):
        cmd = _build_freerouting_cmd(
            "/x/fr.jar",
            "/w/a.dsn",
            "/w/a.ses",
            20,
            False,
            job_timeout=270,
            router_args=["--router.autorouter.plane_as_priority=true"],
        )
    assert cmd[-2:] == [
        "--router.job_timeout=00:04:30",
        "--router.autorouter.plane_as_priority=true",
    ]


def _autoroute(workdir, fake_jar, params):
    cc = _make_cmds(workdir / "test.kicad_pcb")
    _patch_exec_mode(cc)
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        _ses_from_cmd(cmd).write_text(_make_ses(num_nets=5))
        return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

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
    return out, seen, sp


def test_autoroute_passes_router_settings(workdir, fake_jar):
    out, seen, _ = _autoroute(
        workdir,
        fake_jar,
        {
            "routerSettings": {
                "autorouter.priority_net_classes": ["PRIO"],
                "autorouter.plane_as_priority": True,
            }
        },
    )
    assert out["success"], out
    assert "--router.autorouter.priority_net_classes=PRIO" in seen["cmd"]
    assert "--router.autorouter.plane_as_priority=true" in seen["cmd"]
    assert out["router_settings"] == [
        "--router.autorouter.priority_net_classes=PRIO",
        "--router.autorouter.plane_as_priority=true",
    ]


def test_autoroute_refuses_bad_settings_before_running(workdir, fake_jar):
    out, seen, sp = _autoroute(workdir, fake_jar, {"routerSettings": {"max_passes": 3}})
    assert out["success"] is False
    assert out["message"] == "Invalid routerSettings"
    assert "maxPasses" in out["errorDetails"]
    assert sp.run.call_count == 0


def test_autoroute_without_settings_is_unchanged(workdir, fake_jar):
    out, seen, _ = _autoroute(workdir, fake_jar, {})
    assert out["success"], out
    assert out["router_settings"] == []
    assert [a for a in seen["cmd"] if a.startswith("--router.")] == [
        next(a for a in seen["cmd"] if a.startswith("--router.job_timeout="))
    ]
