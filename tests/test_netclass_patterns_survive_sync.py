"""assign_net_to_class must leave a record that survives Update PCB from Schematic.

KiCad treats ``net_settings.netclass_assignments`` as derived from the schematic's
net-class directives and rewrites it on a schematic sync. On a schematic with no
directives the sync empties it, and every assignment the tool persisted there is
lost - silently, since rules keyed on those classes simply stop matching and DRC
passes. The user-defined ``netclass_patterns`` survive. These tests pin that the
writer also records a pattern for the net, updates it in place, and that the
membership is still readable after a sync-like wipe of the derived map.

The pattern is ``re.escape(net)``, not the raw name: KiCad reads a netclass
pattern as an anchored regular expression, so a raw ``HV+`` also captures ``HV``
and ``HVV``. ``tests/test_netclass_patterns_real_pcbnew.py`` checks that against
KiCad's own ``NET_SETTINGS``; the tests here are the pure JSON side.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.routing import (  # noqa: E402
    apply_net_assignment_to_project_settings,
    netclass_pattern_for_net,
    persist_net_assignment_to_project,
)
from utils.kicad_project import new_project_settings  # noqa: E402
from utils.project_netclasses import load_project_net_classes  # noqa: E402


def test_writer_records_the_nets_own_pattern() -> None:
    data = apply_net_assignment_to_project_settings({}, "/TERM NEG", "TERMNEG")
    assert data["net_settings"]["netclass_patterns"] == [
        {"netclass": "TERMNEG", "pattern": r"/TERM\ NEG"}
    ]


def test_pattern_escapes_regex_metacharacters() -> None:
    """``HV+`` as a pattern is the regex "H then one or more V": it captures ``HV``
    and ``HVV``. The record must be the escaped form, and a plain name stays as is."""
    assert netclass_pattern_for_net("HV+") == r"HV\+"
    assert netclass_pattern_for_net("/SPI.CLK") == r"/SPI\.CLK"
    assert netclass_pattern_for_net("Net-(R1-Pad1)") == r"Net\-\(R1\-Pad1\)"
    assert netclass_pattern_for_net("PWR") == "PWR"
    for name in ("HV+", "HV", "HVV", "/SPI.CLK", "/SPIxCLK", "Net-(R1-Pad1)", "Net-R1-Pad1"):
        pattern = re.compile("^" + netclass_pattern_for_net("HV+") + "$")
        assert bool(pattern.match(name)) == (name == "HV+"), name
    data = apply_net_assignment_to_project_settings({}, "HV+", "HV")
    assert data["net_settings"]["netclass_patterns"] == [{"netclass": "HV", "pattern": r"HV\+"}]


def test_reassignment_updates_the_pattern_in_place() -> None:
    data = apply_net_assignment_to_project_settings({}, "PWR", "Power")
    apply_net_assignment_to_project_settings(data, "PWR", "HV")
    patterns = data["net_settings"]["netclass_patterns"]
    assert patterns == [{"netclass": "HV", "pattern": "PWR"}]


def test_reassignment_of_a_regex_name_compares_the_escaped_form() -> None:
    data = apply_net_assignment_to_project_settings({}, "HV+", "Power")
    apply_net_assignment_to_project_settings(data, "HV+", "HV")
    assert data["net_settings"]["netclass_patterns"] == [{"netclass": "HV", "pattern": r"HV\+"}]


def test_a_raw_name_entry_is_rewritten_not_duplicated() -> None:
    """An earlier build recorded the raw name. Re-running the tool on that net must
    replace that entry, which over-matches, instead of adding the escaped one next to it."""
    data = {"net_settings": {"netclass_patterns": [{"netclass": "Power", "pattern": "HV+"}]}}
    apply_net_assignment_to_project_settings(data, "HV+", "HV")
    assert data["net_settings"]["netclass_patterns"] == [{"netclass": "HV", "pattern": r"HV\+"}]


def test_existing_user_patterns_are_kept() -> None:
    data = {"net_settings": {"netclass_patterns": [{"netclass": "Power", "pattern": "+*V"}]}}
    apply_net_assignment_to_project_settings(data, "/TERM NEG", "TERMNEG")
    assert {"netclass": "Power", "pattern": "+*V"} in data["net_settings"]["netclass_patterns"]
    assert {"netclass": "TERMNEG", "pattern": r"/TERM\ NEG"} in data["net_settings"][
        "netclass_patterns"
    ]


def test_membership_survives_a_sync_that_empties_the_derived_map(tmp_path: Path) -> None:
    pro = tmp_path / "board.kicad_pro"
    pro.write_text(json.dumps(new_project_settings("board"), indent=2))
    for net, cls in (("/TERM NEG", "TERMNEG"), ("/HV PWR/CAN GND", "PACK")):
        assert persist_net_assignment_to_project(str(pro), net, cls)["persisted"]

    # What Update PCB from Schematic does on a schematic without net-class directives.
    data = json.loads(pro.read_text())
    data["net_settings"]["netclass_assignments"] = None
    pro.write_text(json.dumps(data, indent=2))

    loaded = load_project_net_classes(str(pro))
    assert loaded["assignments"] == {}
    assert (r"/TERM\ NEG", "TERMNEG") in loaded["patterns"]
    assert (r"/HV\ PWR/CAN\ GND", "PACK") in loaded["patterns"]
