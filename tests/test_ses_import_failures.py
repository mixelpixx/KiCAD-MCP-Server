"""Regression tests: SES imports that fail silently.

1. ``ImportSpecctraSES`` / ``ExportSpecctraDSN`` return ``False`` on failure. The old
   check ``result is not True and result != 0`` treated that as success because
   ``False == 0`` in Python, so ``import_ses`` and ``autoroute`` reported success
   while nothing had been written to the board.

2. ``ImportSpecctraSES`` aborts the whole import when the SES ``(placement ...)``
   block names a reference that is not on the board (reported on KiCad 10.0.6,
   where the DSN export renamed duplicate ``REF**`` references to ``REF**_1``).
   ``autoroute`` strips the block from a copy, since a headless run never moves
   parts. ``import_ses`` may be handed an SES from Freerouting's GUI, where parts
   can be moved, so it drops only the entries naming a reference that is missing
   from the board or not unique on it.
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.freerouting import (  # noqa: E402
    FreeroutingCommands,
    _api_ok,
    _prune_ses_placement,
    _strip_ses_placement,
)

pcbnew_mock = sys.modules["pcbnew"]

SES = """(session board
  (base_design board)
  (placement
    (resolution um 10)
    (component "Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical"
      (place "REF**_1" 674750 -832500 front 0)
    )
  )
  (was_is
  )
  (routes
    (resolution um 10)
    (network_out
      (net GND
        (wire (path F.Cu 5000 0 0 1000 0))
      )
    )
  )
)
"""


@pytest.fixture(autouse=True)
def _reset_pcbnew() -> Any:
    pcbnew_mock.reset_mock()
    pcbnew_mock.ImportSpecctraSES.side_effect = None
    yield


@pytest.fixture
def cmds() -> FreeroutingCommands:
    board = MagicMock()
    board.GetFileName.return_value = ""
    board.GetTracks.return_value = []
    board.GetNetInfo.return_value.GetNetCount.return_value = 0
    return FreeroutingCommands(board=board)


def test_api_ok_accepts_true_and_legacy_zero() -> None:
    assert _api_ok(True)
    assert _api_ok(0)


def test_api_ok_rejects_false_and_other_values() -> None:
    assert not _api_ok(False)  # False == 0, the original bug
    assert not _api_ok(None)
    assert not _api_ok(1)
    assert not _api_ok(MagicMock())


def test_strip_placement_removes_only_the_placement_block() -> None:
    out = _strip_ses_placement(SES)
    assert "(placement" not in out
    assert "REF**_1" not in out
    assert "(net GND" in out
    assert "(wire (path F.Cu 5000 0 0 1000 0))" in out
    assert out.count("(") == out.count(")")


def test_strip_placement_without_block_is_a_no_op() -> None:
    text = "(session x (routes (network_out)))"
    assert _strip_ses_placement(text) == text


def test_import_ses_reports_failure_when_pcbnew_returns_false(
    cmds: FreeroutingCommands, tmp_path: Path
) -> None:
    ses = tmp_path / "board.ses"
    ses.write_text(SES)
    pcbnew_mock.ImportSpecctraSES.return_value = False

    result = cmds.import_ses({"sesPath": str(ses)})

    assert result["success"] is False
    assert "SES import failed" in result["message"]


SES_MIXED = """(session board
  (base_design board)
  (placement
    (resolution um 10)
    (component "Resistor_SMD:R_0603_1608Metric"
      (place R1 40000 20000 back 270)
    )
    (component "Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical"
      (place "REF**" 674750 -832500 front 0)
      (place "REF**_1" 684750 -832500 front 0)
    )
  )
  (routes
    (resolution um 10)
    (network_out
      (net GND
        (wire (path F.Cu 5000 0 0 1000 0))
      )
    )
  )
)
"""


def _footprints(*refs: str) -> list:
    fps = []
    for ref in refs:
        fp = MagicMock()
        fp.GetReference.return_value = ref
        fps.append(fp)
    return fps


def test_strip_placement_ignores_parens_inside_quoted_names() -> None:
    text = '(session s (placement (component "Odd(name" (place R1 0 0 front 0))) (routes (x)))'
    out = _strip_ses_placement(text)
    assert out == "(session s  (routes (x)))"


def test_prune_keeps_resolvable_entries_and_drops_the_rest() -> None:
    board_refs = ["R1", "REF**", "REF**"]  # R1 unique; REF** placed twice
    out, dropped = _prune_ses_placement(SES_MIXED, board_refs)
    assert sorted(dropped) == ["REF**", "REF**_1"]
    assert "(place R1 40000 20000 back 270)" in out  # a GUI move still applies
    assert "REF**" not in out
    # the connector group lost all its entries and is gone; R1's group remains
    assert "PinHeader_1x01" not in out
    assert "Resistor_SMD:R_0603_1608Metric" in out
    assert "(net GND" in out
    assert out.count("(") == out.count(")")


def test_prune_is_a_no_op_when_every_entry_resolves() -> None:
    text = SES_MIXED.replace('(place "REF**" 674750 -832500 front 0)', "").replace(
        '(place "REF**_1" 684750 -832500 front 0)', ""
    )
    out, dropped = _prune_ses_placement(text, ["R1"])
    assert dropped == []
    assert out == text


def _capture_import(seen: dict) -> Any:
    def fake_import(board: Any, path: str) -> bool:
        seen["text"] = Path(path).read_text()
        return True

    return fake_import


def test_import_ses_drops_placement_for_references_not_on_the_board(
    cmds: FreeroutingCommands, tmp_path: Path
) -> None:
    ses = tmp_path / "board.ses"
    ses.write_text(SES)
    cmds.board.GetFootprints.return_value = []
    seen: dict = {}
    pcbnew_mock.ImportSpecctraSES.side_effect = _capture_import(seen)

    result = cmds.import_ses({"sesPath": str(ses)})

    assert result["success"] is True
    assert "REF**_1" not in seen["text"]
    assert "(net GND" in seen["text"]
    assert result["placementSkipped"] == ["REF**_1"]
    assert ses.read_text() == SES  # the caller's file is left untouched


def test_import_ses_keeps_placement_for_parts_on_the_board(
    cmds: FreeroutingCommands, tmp_path: Path
) -> None:
    ses = tmp_path / "board.ses"
    ses.write_text(SES_MIXED)
    cmds.board.GetFootprints.return_value = _footprints("R1", "REF**", "REF**")
    seen: dict = {}
    pcbnew_mock.ImportSpecctraSES.side_effect = _capture_import(seen)

    result = cmds.import_ses({"sesPath": str(ses)})

    assert result["success"] is True
    assert "(place R1 40000 20000 back 270)" in seen["text"]
    assert result["placementSkipped"] == ["REF**", "REF**_1"]


def test_import_ses_failure_warns_about_the_board_in_memory(
    cmds: FreeroutingCommands, tmp_path: Path
) -> None:
    ses = tmp_path / "board.ses"
    ses.write_text(SES)
    pcbnew_mock.ImportSpecctraSES.return_value = False

    result = cmds.import_ses({"sesPath": str(ses)})

    assert result["success"] is False
    assert "Reopen the board from disk" in result["errorDetails"]
    cmds.board.Save.assert_not_called()
