"""The net-class assignment contract between #315 and #302.

`assign_net_to_class` (#315) persists membership to
``net_settings.netclass_assignments`` in the ``.kicad_pro``, and the DSN
exporter (#302) reads that same key back to rebuild the board's NET_SETTINGS
before ``ExportSpecctraDSN``. Two features, two files, one shared on-disk key —
and neither side's own tests cross the boundary, so a change to the key name or
the value shape on either side would pass both suites and silently stop routed
power nets from getting their width.

This file pins the seam.
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


def test_writer_output_is_readable_by_the_dsn_loader() -> None:
    """The pure writer's shape must be exactly what the pure reader expects."""
    data = apply_net_assignment_to_project_settings({}, "PWR", "Power")
    assignments = data["net_settings"]["netclass_assignments"]

    # Shape the reader documents: net name -> list of class names.
    assert assignments == {"PWR": ["Power"]}
    assert isinstance(assignments["PWR"], list)


def test_persisted_assignment_survives_a_real_round_trip(tmp_path: Path) -> None:
    """Write via #315's persistence path, read via #302's loader."""
    pro = tmp_path / "board.kicad_pro"
    data = new_project_settings("board")
    power = dict(data["net_settings"]["classes"][0])
    power.update(name="Power", track_width=2.0)
    data["net_settings"]["classes"].append(power)
    pro.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = persist_net_assignment_to_project(str(pro), "PWR", "Power")
    assert result["persisted"] is True, result

    settings = load_project_net_classes(str(pro))
    assert settings is not None
    assert settings["assignments"] == {"PWR": ["Power"]}
    # The class definition the assignment points at must still be there —
    # persisting membership must not clobber net_settings.classes.
    assert "Power" in [c["name"] for c in settings["classes"]]


def test_last_assignment_wins_as_both_sides_document(tmp_path: Path) -> None:
    """Both modules independently state that a net keeps only its most recent
    assignment and composite membership is not modeled. Pin that agreement."""
    pro = tmp_path / "board.kicad_pro"
    pro.write_text(json.dumps(new_project_settings("board")), encoding="utf-8")

    persist_net_assignment_to_project(str(pro), "PWR", "Power")
    persist_net_assignment_to_project(str(pro), "PWR", "HighVoltage")

    settings = load_project_net_classes(str(pro))
    assert settings is not None
    assert settings["assignments"] == {"PWR": ["HighVoltage"]}


def test_multiple_nets_accumulate(tmp_path: Path) -> None:
    pro = tmp_path / "board.kicad_pro"
    pro.write_text(json.dumps(new_project_settings("board")), encoding="utf-8")

    persist_net_assignment_to_project(str(pro), "PWR", "Power")
    persist_net_assignment_to_project(str(pro), "PWR2", "Power")

    settings = load_project_net_classes(str(pro))
    assert settings is not None
    assert settings["assignments"] == {"PWR": ["Power"], "PWR2": ["Power"]}
