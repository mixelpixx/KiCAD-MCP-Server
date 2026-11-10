"""In-memory net class membership: escaped patterns, rebuilt from the project file.

``register_membership_in_project_settings`` mirrors the project-file write into
the board's ``NET_SETTINGS`` so a KiCad 9 board save (which rewrites the
``.kicad_pro`` from memory) keeps it. Two KiCad behaviours shape it, both
checked on 9.0.9 and 10.0.8:

- a pattern is an anchored regular expression, so a raw ``D+`` also claims ``D``
  and ``DD``; the pattern is ``re.escape(net)`` (``netclass_pattern_for_net``);
- ``SetNetclassPatternAssignment`` appends, and Python can't read the list
  back, so moving a net between classes would leave it in the composite
  ``A,B``; the list is cleared and rebuilt from the project file instead.
"""

import json
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, call

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.routing import (  # noqa: E402
    persist_net_assignment_to_project,
    register_membership_in_project_settings,
    register_memberships_in_project_settings,
)
from utils.kicad_project import new_project_settings  # noqa: E402
from utils.project_netclasses import netclass_pattern_for_net  # noqa: E402


def _board(settings) -> MagicMock:
    board = MagicMock()
    board.GetDesignSettings.return_value.m_NetSettings = settings
    return board


def _settings() -> MagicMock:
    return MagicMock(
        spec=[
            "SetNetclassPatternAssignment",
            "ClearNetclassPatternAssignments",
            "ClearNetclassLabelAssignment",
            "ClearAllCaches",
        ]
    )


def _pro(tmp_path: Path) -> Path:
    pro = tmp_path / "board.kicad_pro"
    pro.write_text(json.dumps(new_project_settings("board"), indent=2))
    return pro


def test_pattern_for_a_regex_name_matches_only_that_net() -> None:
    pattern = netclass_pattern_for_net("D+")
    assert pattern == r"D\+"
    anchored = re.compile("^" + pattern + "$")
    assert anchored.match("D+")
    assert not anchored.match("D")
    assert not anchored.match("DD")


def test_registers_the_escaped_name_not_the_raw_one() -> None:
    settings = _settings()
    assert register_membership_in_project_settings(_board(settings), "D+", "HV") is None
    settings.SetNetclassPatternAssignment.assert_called_once_with(r"D\+", "HV")
    settings.ClearNetclassLabelAssignment.assert_called_once_with("D+")
    settings.ClearNetclassPatternAssignments.assert_not_called()


def test_moving_a_net_rebuilds_the_list_from_the_project_file(tmp_path: Path) -> None:
    """A then B must end as B alone, not the composite A,B that appending gives."""
    pro = _pro(tmp_path)
    settings = _settings()
    board = _board(settings)

    persist_net_assignment_to_project(str(pro), "D+", "A")
    register_membership_in_project_settings(board, "D+", "A", str(pro))
    persist_net_assignment_to_project(str(pro), "D+", "B")
    register_membership_in_project_settings(board, "D+", "B", str(pro))

    assert settings.ClearNetclassPatternAssignments.call_count == 2
    # The second rebuild sets the file's single entry for the net, now B.
    assert settings.SetNetclassPatternAssignment.call_args_list[-1] == call(r"D\+", "B")
    rebuilt = settings.SetNetclassPatternAssignment.call_args_list[1:]
    assert rebuilt == [call(r"D\+", "B")]
    assert settings.ClearAllCaches.call_count == 2


def test_rebuild_keeps_the_users_own_patterns(tmp_path: Path) -> None:
    pro = _pro(tmp_path)
    data = json.loads(pro.read_text())
    data["net_settings"]["netclass_patterns"] = [{"netclass": "CAN", "pattern": "/CAN_*"}]
    pro.write_text(json.dumps(data))
    settings = _settings()

    persist_net_assignment_to_project(str(pro), "HV_BUS", "HV")
    register_membership_in_project_settings(_board(settings), "HV_BUS", "HV", str(pro))

    settings.ClearNetclassPatternAssignments.assert_called_once()
    assert settings.SetNetclassPatternAssignment.call_args_list == [
        call("/CAN_*", "CAN"),
        call("HV_BUS", "HV"),
    ]


def test_several_nets_rebuild_once(tmp_path: Path) -> None:
    pro = _pro(tmp_path)
    settings = _settings()
    for net in ("HV_BUS", "HV_SENSE"):
        persist_net_assignment_to_project(str(pro), net, "HV")
    register_memberships_in_project_settings(
        _board(settings), ["HV_BUS", "HV_SENSE"], "HV", str(pro)
    )
    settings.ClearNetclassPatternAssignments.assert_called_once()
    assert settings.SetNetclassPatternAssignment.call_args_list == [
        call("HV_BUS", "HV"),
        call("HV_SENSE", "HV"),
    ]
    assert settings.ClearNetclassLabelAssignment.call_args_list == [
        call("HV_BUS"),
        call("HV_SENSE"),
    ]


def test_without_a_project_file_the_pattern_is_appended() -> None:
    settings = _settings()
    register_membership_in_project_settings(_board(settings), "N", "HV", "/nonexistent.kicad_pro")
    settings.ClearNetclassPatternAssignments.assert_not_called()
    settings.SetNetclassPatternAssignment.assert_called_once_with("N", "HV")


def test_settings_without_the_setter_are_left_alone() -> None:
    # KiCad 8's NET_SETTINGS has no SetNetclassPatternAssignment.
    settings = MagicMock(spec=["ClearAllCaches"])
    assert register_membership_in_project_settings(_board(settings), "N", "HV") is None
    settings.ClearAllCaches.assert_not_called()


def test_a_failing_setter_is_reported_not_raised() -> None:
    settings = _settings()
    settings.SetNetclassPatternAssignment.side_effect = RuntimeError("swig boom")
    warning = register_membership_in_project_settings(_board(settings), "N", "HV")
    assert warning is not None and "swig boom" in warning
