"""Regression tests for issue #245: KiCad 10 Windows install paths must be in
the auto-discovery candidate lists (footprints and symbols), with env-var
overrides for KiCad 10.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.library import LibraryManager  # noqa: E402
from commands.library_symbol import SymbolLibraryManager  # noqa: E402

K10_FOOTPRINTS = "C:/Program Files/KiCad/10.0/share/kicad/footprints"
K10_SYMBOLS = "C:/Program Files/KiCad/10.0/share/kicad/symbols"


@pytest.mark.unit
class TestKicad10FootprintDir:
    def test_k10_windows_path_is_discovered(self):
        lm = LibraryManager.__new__(LibraryManager)
        with patch("commands.library.os.path.isdir", side_effect=lambda p: p == K10_FOOTPRINTS):
            assert lm._find_kicad_footprint_dir() == K10_FOOTPRINTS

    def test_k10_env_override_wins(self, monkeypatch):
        lm = LibraryManager.__new__(LibraryManager)
        monkeypatch.delenv("KICAD9_FOOTPRINT_DIR", raising=False)
        monkeypatch.setenv("KICAD10_FOOTPRINT_DIR", "/custom/k10/footprints")
        with patch("commands.library.os.path.isdir", return_value=True):
            assert lm._find_kicad_footprint_dir() == "/custom/k10/footprints"


@pytest.mark.unit
class TestKicad10SymbolDir:
    def test_k10_windows_path_is_discovered(self):
        sm = SymbolLibraryManager.__new__(SymbolLibraryManager)
        with patch("commands.library_symbol.os.path.isdir", side_effect=lambda p: p == K10_SYMBOLS):
            assert sm._find_kicad_symbol_dir() == K10_SYMBOLS

    def test_k10_env_override_wins(self, monkeypatch):
        sm = SymbolLibraryManager.__new__(SymbolLibraryManager)
        monkeypatch.delenv("KICAD9_SYMBOL_DIR", raising=False)
        monkeypatch.setenv("KICAD10_SYMBOL_DIR", "/custom/k10/symbols")
        with patch("commands.library_symbol.os.path.isdir", return_value=True):
            assert sm._find_kicad_symbol_dir() == "/custom/k10/symbols"
