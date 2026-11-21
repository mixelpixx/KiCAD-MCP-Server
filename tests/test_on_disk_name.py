"""A boardPath in another letter case must not rename the board on a case-insensitive file system.

Tristan Lewis, Windows 11 / KiCad 10.0.1 (2026-11-17): autoroute with boardPath "board.kicad_pcb"
on a project whose file is "Board.kicad_pcb" saved the board, and renamed its .kicad_pro, to the
lower-case spelling. ``on_disk_name`` gives the save the name the file already has. The file system
here is case-sensitive, so the case-insensitive lookup is simulated.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.freerouting import on_disk_name  # noqa: E402


def test_existing_spelling_is_kept(tmp_path):
    f = tmp_path / "Board.kicad_pcb"
    f.write_bytes(b"")
    assert on_disk_name(str(f)) == str(f)


def test_missing_file_is_returned_unchanged(tmp_path):
    p = str(tmp_path / "new.kicad_pcb")
    assert on_disk_name(p) == p


def test_other_case_resolves_to_the_on_disk_name(tmp_path, monkeypatch):
    (tmp_path / "Board.kicad_pcb").write_bytes(b"")
    asked = tmp_path / "board.kicad_pcb"
    real_exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda self: True if self == asked else real_exists(self))
    monkeypatch.setattr(os.path, "samefile", lambda a, b: True)
    assert on_disk_name(str(asked)) == str(tmp_path / "Board.kicad_pcb")
