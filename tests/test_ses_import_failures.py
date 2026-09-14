"""Regression tests: SES imports that fail silently.

1. ``ImportSpecctraSES`` / ``ExportSpecctraDSN`` return ``False`` on failure. The old
   check ``result is not True and result != 0`` treated that as success because
   ``False == 0`` in Python, so ``import_ses`` and ``autoroute`` reported success
   while nothing had been written to the board.

2. ``ImportSpecctraSES`` aborts the whole import when the SES ``(placement ...)``
   block names a reference that is not on the board. Freerouting always writes that
   block, and the DSN export renames duplicate references (``REF**`` ->
   ``REF**_1``), so any board with non-unique references could not be imported.
   Freerouting never moves parts, so the block is dropped before import.
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


def test_import_ses_hands_pcbnew_a_file_without_placement(
    cmds: FreeroutingCommands, tmp_path: Path
) -> None:
    ses = tmp_path / "board.ses"
    ses.write_text(SES)
    seen = {}

    def fake_import(board: Any, path: str) -> bool:
        seen["text"] = Path(path).read_text()
        return True

    pcbnew_mock.ImportSpecctraSES.side_effect = fake_import

    result = cmds.import_ses({"sesPath": str(ses)})

    assert result["success"] is True
    assert "(placement" not in seen["text"]
    assert "(net GND" in seen["text"]
    assert ses.read_text() == SES  # the caller's file is left untouched
