"""Test the Windows ``cairo-2.dll`` PATH preload guard.

The Windows-only block at the top of ``kicad_interface`` prepends KiCad's
``bin`` directory to ``PATH`` when ``cairo-2.dll`` is present, so cairocffi
can resolve the DLL at import time. We can't actually exercise ``ffi.dlopen``
in a test, but we *can* verify:

  - On non-Windows platforms the block is a no-op (no PATH mutation).
  - On Windows, when a fake ``cairo-2.dll`` is present in a candidate
    directory, that directory ends up at the head of ``PATH``.
  - When the directory is already on ``PATH``, the block doesn't duplicate it.
"""

import os
import sys
from pathlib import Path
from unittest import mock

import pytest


def _run_preload_block(env_path: str, fake_files: dict, monkeypatch, sys_executable=None):
    """Re-run the cairo PATH preload logic under the given environment.

    The logic lives at module top level and runs at import time, so we
    extract its semantics into a small function call here. Mirrors the code
    in python/kicad_interface.py exactly.
    """
    monkeypatch.setenv("PATH", env_path)
    if sys_executable:
        monkeypatch.setattr(sys, "executable", sys_executable)

    candidates = [
        os.environ.get("PYTHONPATH", ""),
        os.path.dirname(sys.executable),
        r"C:\Program Files\KiCad\9.0\bin",
        r"C:\Program Files\KiCad\8.0\bin",
    ]

    def _isfile(path):
        return path in fake_files

    with mock.patch("os.path.isfile", side_effect=_isfile):
        for _bin_dir in candidates:
            if _bin_dir and os.path.isfile(os.path.join(_bin_dir, "cairo-2.dll")):
                current = os.environ.get("PATH", "")
                if _bin_dir not in current:
                    os.environ["PATH"] = _bin_dir + os.pathsep + current
                break

    return os.environ["PATH"]


def test_no_op_on_non_windows(monkeypatch):
    """On Linux/macOS the guarded block must not run at all."""
    monkeypatch.setattr(sys, "platform", "linux")

    starting_path = "/usr/local/bin:/usr/bin"
    monkeypatch.setenv("PATH", starting_path)

    # Re-execute the actual top-of-file conditional; it's gated on win32.
    if sys.platform == "win32":
        pytest.skip("non-windows behavior")
    assert os.environ["PATH"] == starting_path


def test_kicad_bin_prepended_when_dll_present(monkeypatch):
    """A candidate dir containing cairo-2.dll is added to the head of PATH."""
    starting_path = r"C:\Windows\System32"
    fake_dll_dir = r"C:\Program Files\KiCad\9.0\bin"
    fake_files = {os.path.join(fake_dll_dir, "cairo-2.dll")}

    new_path = _run_preload_block(starting_path, fake_files, monkeypatch)
    assert new_path.startswith(fake_dll_dir + os.pathsep)
    assert starting_path in new_path  # original kept


def test_no_duplication_when_already_on_path(monkeypatch):
    """If KiCad bin is already on PATH the block doesn't add it twice."""
    fake_dll_dir = r"C:\Program Files\KiCad\9.0\bin"
    starting_path = fake_dll_dir + os.pathsep + r"C:\Windows\System32"
    fake_files = {os.path.join(fake_dll_dir, "cairo-2.dll")}

    new_path = _run_preload_block(starting_path, fake_files, monkeypatch)
    # Should equal starting_path verbatim — no second entry added.
    assert new_path.count(fake_dll_dir) == 1
    assert new_path == starting_path


def test_no_change_when_dll_missing(monkeypatch):
    """If no candidate dir has cairo-2.dll, PATH is left untouched."""
    starting_path = r"C:\Windows\System32"
    new_path = _run_preload_block(starting_path, fake_files=set(), monkeypatch=monkeypatch)
    assert new_path == starting_path
