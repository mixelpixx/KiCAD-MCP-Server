"""assign_net_to_class must leave a record that survives Update PCB from Schematic.

KiCad treats ``net_settings.netclass_assignments`` as derived from the schematic's
net-class directives and rewrites it on a schematic sync. On a schematic with no
directives the sync empties it, and every assignment the tool persisted there is
lost - silently, since rules keyed on those classes simply stop matching and DRC
passes. The user-defined ``netclass_patterns`` survive. These tests pin that the
writer also records an exact-name pattern, updates it in place, and that the
membership is still readable after a sync-like wipe of the derived map.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.routing import (  # noqa: E402
    apply_net_assignment_to_project_settings,
    persist_net_assignment_to_project,
)
from utils.kicad_project import new_project_settings  # noqa: E402
from utils.project_netclasses import load_project_net_classes  # noqa: E402


def test_writer_records_an_exact_name_pattern() -> None:
    data = apply_net_assignment_to_project_settings({}, "/TERM NEG", "TERMNEG")
    assert data["net_settings"]["netclass_patterns"] == [{"netclass": "TERMNEG", "pattern": "/TERM NEG"}]


def test_reassignment_updates_the_pattern_in_place() -> None:
    data = apply_net_assignment_to_project_settings({}, "PWR", "Power")
    apply_net_assignment_to_project_settings(data, "PWR", "HV")
    patterns = data["net_settings"]["netclass_patterns"]
    assert patterns == [{"netclass": "HV", "pattern": "PWR"}]


def test_existing_user_patterns_are_kept() -> None:
    data = {"net_settings": {"netclass_patterns": [{"netclass": "Power", "pattern": "+*V"}]}}
    apply_net_assignment_to_project_settings(data, "/TERM NEG", "TERMNEG")
    assert {"netclass": "Power", "pattern": "+*V"} in data["net_settings"]["netclass_patterns"]
    assert {"netclass": "TERMNEG", "pattern": "/TERM NEG"} in data["net_settings"]["netclass_patterns"]


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
    assert ("/TERM NEG", "TERMNEG") in loaded["patterns"]
    assert ("/HV PWR/CAN GND", "PACK") in loaded["patterns"]
