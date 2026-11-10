"""The pattern assign_net_to_class records puts only its own net in the class.

KiCad compiles every netclass pattern as an anchored regular expression (and a
wildcard beside it), so a raw net name over-matches: ``HV+`` is "H then one or
more V" and also captures ``HV`` and ``HVV``. These tests put patterns into
KiCad's own ``NET_SETTINGS`` through ``SetNetclassPatternAssignment``, which is
what the project loader calls, and ask ``GetEffectiveNetClass`` which class each
name lands in. Requires KICAD_USE_REAL_PCBNEW=1 under KiCad's bundled Python.

One board holds every pattern: ``pcbnew.BOARD()`` objects made in the same
process share their pattern assignments (checked on KiCad 10.0.8), so a fresh
board per case would not isolate anything.
"""

import json
import os
import sys
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.real_pcbnew,
]


@pytest.fixture(autouse=True)
def require_real_pcbnew() -> None:
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
        pytest.skip("real pcbnew netclass pattern test requires KICAD_USE_REAL_PCBNEW=1")


# (net the tool assigns, class it goes to, names that must NOT land in that class)
CASES = [
    ("HV+", "NCPAT_PLUS", ["HV", "HVV"]),
    ("/SPI.CLK", "NCPAT_DOT", ["/SPIxCLK"]),
    ("Net-(R1-Pad1)", "NCPAT_PAREN", ["Net-R1-Pad1"]),
    ("/TERM NEG", "NCPAT_SPACE", ["/TERMxNEG"]),
    ("+5V", "NCPAT_LEADPLUS", ["5V", "+5VA"]),
]


def _net_settings_with_classes(pcbnew):
    board = pcbnew.BOARD()
    settings = board.GetDesignSettings().m_NetSettings
    if not hasattr(settings, "SetNetclassPatternAssignment"):
        pytest.skip("NET_SETTINGS.SetNetclassPatternAssignment needs KiCad 9+")
    for _net, class_name, _others in CASES:
        settings.SetNetclass(class_name, pcbnew.NETCLASS(class_name))
    return board, settings


def _effective(settings, name: str) -> str:
    if hasattr(settings, "ClearAllCaches"):
        settings.ClearAllCaches()
    return settings.GetEffectiveNetClass(name).GetName()


def test_recorded_pattern_matches_only_its_own_net() -> None:
    import pcbnew
    from commands.routing import netclass_pattern_for_net

    _board, settings = _net_settings_with_classes(pcbnew)
    for net, class_name, _others in CASES:
        settings.SetNetclassPatternAssignment(netclass_pattern_for_net(net), class_name)

    for net, class_name, others in CASES:
        assert _effective(settings, net) == class_name, net
        for other in others:
            assert _effective(settings, other) == "Default", (net, other)


def test_the_raw_name_would_capture_other_nets() -> None:
    """The control: what the first version of this fix wrote, and why it was wrong."""
    import pcbnew

    _board, settings = _net_settings_with_classes(pcbnew)
    settings.SetNetclassPatternAssignment("NCPAT_RAW_HV+", "NCPAT_PLUS")
    assert _effective(settings, "NCPAT_RAW_HV+") == "NCPAT_PLUS"
    assert _effective(settings, "NCPAT_RAW_HV") == "NCPAT_PLUS"
    assert _effective(settings, "NCPAT_RAW_HVV") == "NCPAT_PLUS"


def test_project_file_record_reaches_kicad_through_the_loader(tmp_path: Path) -> None:
    """End to end: the entry assign_net_to_class persists, read back by the project
    loader and pushed into NET_SETTINGS the way export_dsn does, selects one net."""
    import pcbnew
    from commands.routing import persist_net_assignment_to_project
    from utils.kicad_project import new_project_settings
    from utils.project_netclasses import apply_net_classes_to_board, load_project_net_classes

    pro = tmp_path / "board.kicad_pro"
    data = new_project_settings("board")
    data["net_settings"]["classes"].append({"name": "NCPAT_LOADER", "clearance": 5.0})
    pro.write_text(json.dumps(data, indent=2))
    # Net names not used by the other tests here: boards in one process share patterns.
    assert persist_net_assignment_to_project(str(pro), "LDR+", "NCPAT_LOADER")["persisted"]

    board = pcbnew.BOARD()
    settings = board.GetDesignSettings().m_NetSettings
    if not hasattr(settings, "SetNetclassPatternAssignment"):
        pytest.skip("NET_SETTINGS.SetNetclassPatternAssignment needs KiCad 9+")
    loaded = load_project_net_classes(str(pro))
    assert (r"LDR\+", "NCPAT_LOADER") in loaded["patterns"]
    assert loaded["assignments"] == {"LDR+": ["NCPAT_LOADER"]}
    apply_net_classes_to_board(board, loaded)

    assert _effective(settings, "LDR+") == "NCPAT_LOADER"
    assert _effective(settings, "LDR") == "Default"
    assert _effective(settings, "LDRR") == "Default"
