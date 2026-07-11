"""Tests for #302: project net classes reach the Specctra DSN export.

Net-class definitions live in ``.kicad_pro``; the headless ``LoadBoard()``
path never reads them, so ``ExportSpecctraDSN`` exported every net at the
Default class width — a silent electrical hazard on the autoroute path.
These tests cover the ``.kicad_pro`` parser, the NET_SETTINGS application
step (against a fake pcbnew), and the report/warning surface of
``FreeroutingCommands._apply_project_net_classes``.
"""

import json
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from kicad_mcp.utils.project_netclasses import (  # noqa: E402
    apply_net_classes_to_board,
    load_project_net_classes,
)


def _project_json(**net_settings) -> str:
    return json.dumps({"net_settings": net_settings})


# ---------------------------------------------------------------------------
# Fake pcbnew + board, recording exactly the calls the fix performs.
# ---------------------------------------------------------------------------


class FakeNetclass:
    def __init__(self, name: str = "Default") -> None:
        self.name = name
        self.values: dict = {}
        self.priority = None

    def __getattr__(self, attr: str):
        if attr.startswith("Set"):

            def setter(value, _key=attr[3:]):
                self.values[_key] = value

            return setter
        raise AttributeError(attr)

    def SetPriority(self, value: int) -> None:
        self.priority = value


class FakeNetSettings:
    def __init__(self) -> None:
        self.default = FakeNetclass("Default")
        self.netclasses: dict = {}
        self.pattern_assignments: list = []
        self.caches_cleared = False

    def GetDefaultNetclass(self) -> FakeNetclass:
        return self.default

    def SetNetclass(self, name: str, netclass: FakeNetclass) -> None:
        self.netclasses[name] = netclass

    def SetNetclassPatternAssignment(self, pattern: str, name: str) -> None:
        self.pattern_assignments.append((pattern, name))

    def ClearAllCaches(self) -> None:
        self.caches_cleared = True


class FakeBoard:
    def __init__(self) -> None:
        self.net_settings = FakeNetSettings()
        self.synchronized_with = None

    def GetDesignSettings(self):
        return types.SimpleNamespace(m_NetSettings=self.net_settings)

    def SynchronizeNetsAndNetClasses(self, reset: bool) -> None:
        self.synchronized_with = reset


def _fake_pcbnew() -> types.ModuleType:
    module = types.ModuleType("pcbnew")
    module.FromMM = lambda mm: int(round(mm * 1_000_000))  # type: ignore[attr-defined]
    module.NETCLASS = FakeNetclass  # type: ignore[attr-defined]
    return module


# ---------------------------------------------------------------------------
# load_project_net_classes
# ---------------------------------------------------------------------------


def test_load_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_project_net_classes(str(tmp_path / "absent.kicad_pro")) is None
    assert load_project_net_classes(None) is None
    assert load_project_net_classes("") is None


def test_load_malformed_json_raises_value_error(tmp_path: Path) -> None:
    pro = tmp_path / "bad.kicad_pro"
    pro.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="bad.kicad_pro"):
        load_project_net_classes(str(pro))


def test_load_parses_classes_patterns_and_assignments(tmp_path: Path) -> None:
    pro = tmp_path / "t.kicad_pro"
    pro.write_text(
        _project_json(
            classes=[
                {"name": "Default", "track_width": 0.25},
                {"name": "Power", "track_width": 2.0, "clearance": 0.35},
            ],
            netclass_patterns=[
                {"netclass": "Power", "pattern": "PWR*"},
            ],
            netclass_assignments={
                "GND": ["Power"],
                "VBUS": "Power",  # bare-string value tolerated
            },
        ),
        encoding="utf-8",
    )
    settings = load_project_net_classes(str(pro))
    assert settings is not None
    assert [c["name"] for c in settings["classes"]] == ["Default", "Power"]
    assert settings["patterns"] == [("PWR*", "Power")]
    assert settings["assignments"] == {"GND": ["Power"], "VBUS": ["Power"]}


def test_load_skips_malformed_entries(tmp_path: Path) -> None:
    pro = tmp_path / "t.kicad_pro"
    pro.write_text(
        _project_json(
            classes=[{"track_width": 1.0}, "junk", {"name": "OK"}],
            netclass_patterns=[{"pattern": "X"}, {"netclass": "Y"}, "junk"],
            netclass_assignments={"N1": 42, "N2": [3, "Real"]},
        ),
        encoding="utf-8",
    )
    settings = load_project_net_classes(str(pro))
    assert settings is not None
    assert [c["name"] for c in settings["classes"]] == ["OK"]
    assert settings["patterns"] == []
    assert settings["assignments"] == {"N2": ["Real"]}


def test_load_handles_null_net_settings(tmp_path: Path) -> None:
    pro = tmp_path / "t.kicad_pro"
    pro.write_text(json.dumps({"net_settings": None}), encoding="utf-8")
    settings = load_project_net_classes(str(pro))
    assert settings == {"classes": [], "patterns": [], "assignments": {}}


# ---------------------------------------------------------------------------
# apply_net_classes_to_board
# ---------------------------------------------------------------------------


def _apply(settings):
    board = FakeBoard()
    with mock.patch.dict(sys.modules, {"pcbnew": _fake_pcbnew()}):
        report = apply_net_classes_to_board(board, settings)
    return board, report


def test_apply_registers_custom_class_with_mm_conversion() -> None:
    board, report = _apply(
        {
            "classes": [
                {
                    "name": "Power",
                    "track_width": 2.0,
                    "clearance": 0.35,
                    "via_diameter": 1.2,
                    "via_drill": 0.6,
                    "priority": 0,
                }
            ],
            "patterns": [("PWR", "Power"), ("PWR2", "Power")],
            "assignments": {},
        }
    )
    ns = board.net_settings
    assert list(ns.netclasses) == ["Power"]
    power = ns.netclasses["Power"]
    assert power.values["TrackWidth"] == 2_000_000
    assert power.values["Clearance"] == 350_000
    assert power.values["ViaDiameter"] == 1_200_000
    assert power.values["ViaDrill"] == 600_000
    assert power.priority == 0
    assert ns.pattern_assignments == [("PWR", "Power"), ("PWR2", "Power")]
    assert ns.caches_cleared is True
    assert board.synchronized_with is False  # keep current track/via sizes
    assert report["applied"] == ["Power"]
    assert report["assignments"] == 2


def test_apply_updates_default_class_in_place() -> None:
    board, report = _apply(
        {
            "classes": [{"name": "Default", "track_width": 0.3}],
            "patterns": [],
            "assignments": {},
        }
    )
    ns = board.net_settings
    assert ns.netclasses == {}  # Default is never re-registered
    assert ns.default.values["TrackWidth"] == 300_000
    assert report["applied"] == []
    assert report["defaultUpdated"] is True


def test_apply_expresses_explicit_assignments_as_exact_patterns() -> None:
    board, report = _apply(
        {
            "classes": [{"name": "HV", "clearance": 1.0}],
            "patterns": [],
            "assignments": {"Net-(D1-Pad2)": ["HV"]},
        }
    )
    assert board.net_settings.pattern_assignments == [("Net-(D1-Pad2)", "HV")]
    assert report["assignments"] == 1


def test_apply_skips_non_numeric_values() -> None:
    board, _ = _apply(
        {
            "classes": [
                {"name": "Odd", "track_width": "wide", "clearance": True, "via_drill": 0.4}
            ],
            "patterns": [],
            "assignments": {},
        }
    )
    odd = board.net_settings.netclasses["Odd"]
    assert odd.values == {"ViaDrill": 400_000}


# ---------------------------------------------------------------------------
# FreeroutingCommands._apply_project_net_classes (report/warning surface)
# ---------------------------------------------------------------------------


from kicad_mcp.commands.freerouting import FreeroutingCommands  # noqa: E402


def test_report_warns_when_project_file_missing(tmp_path: Path) -> None:
    fc = FreeroutingCommands(FakeBoard())
    report = fc._apply_project_net_classes(str(tmp_path / "board.kicad_pcb"))
    assert report["applied"] == []
    assert ".kicad_pro" in report["warning"]


def test_report_warns_on_unreadable_project(tmp_path: Path) -> None:
    (tmp_path / "board.kicad_pro").write_text("{broken", encoding="utf-8")
    fc = FreeroutingCommands(FakeBoard())
    report = fc._apply_project_net_classes(str(tmp_path / "board.kicad_pcb"))
    assert report["applied"] == []
    assert "Default-class rules only" in report["warning"]


def test_report_names_dropped_classes_when_apply_fails(tmp_path: Path) -> None:
    (tmp_path / "board.kicad_pro").write_text(
        _project_json(classes=[{"name": "Power", "track_width": 2.0}]),
        encoding="utf-8",
    )

    class ExplodingBoard:
        def GetDesignSettings(self):
            raise RuntimeError("no m_NetSettings on this build")

    fc = FreeroutingCommands(ExplodingBoard())
    with mock.patch.dict(sys.modules, {"pcbnew": _fake_pcbnew()}):
        report = fc._apply_project_net_classes(str(tmp_path / "board.kicad_pcb"))
    assert report["applied"] == []
    assert "Power" in report["warning"]
    assert "Default-class rules only" in report["warning"]


def test_report_success_includes_project_file(tmp_path: Path) -> None:
    (tmp_path / "board.kicad_pro").write_text(
        _project_json(
            classes=[{"name": "Power", "track_width": 2.0}],
            netclass_patterns=[{"netclass": "Power", "pattern": "PWR"}],
        ),
        encoding="utf-8",
    )
    board = FakeBoard()
    fc = FreeroutingCommands(board)
    with mock.patch.dict(sys.modules, {"pcbnew": _fake_pcbnew()}):
        report = fc._apply_project_net_classes(str(tmp_path / "board.kicad_pcb"))
    assert report["applied"] == ["Power"]
    assert report["projectFile"] == str(tmp_path / "board.kicad_pro")
    assert "warning" not in report
    assert board.net_settings.pattern_assignments == [("PWR", "Power")]
