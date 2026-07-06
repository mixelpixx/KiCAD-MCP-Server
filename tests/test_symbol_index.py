"""
Tests for the persistent symbol index (python/commands/symbol_index.py) and
its wiring into SymbolLibraryManager / search_symbols.

Pure-Python file I/O: no pcbnew, no KICAD_USE_REAL_PCBNEW needed.
"""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.library_symbol import (  # noqa: E402
    SymbolLibraryCommands,
    SymbolLibraryManager,
)
from commands.symbol_index import VERSION, SymbolIndexStore  # noqa: E402

FIXTURE_LIB = Path(__file__).parent / "fixtures" / "Simulation_SPICE_minimal.kicad_sym"


def _manager_for(lib_path: Path, store: SymbolIndexStore) -> SymbolLibraryManager:
    """Build a manager via __new__ (no sym-lib-table scan, no warm thread)."""
    import threading

    manager = SymbolLibraryManager.__new__(SymbolLibraryManager)
    manager.project_path = None
    manager.libraries = {"Simulation_SPICE": str(lib_path)}
    manager.symbol_cache = {}
    manager._cache_lock = threading.Lock()
    manager.index_store = store
    return manager


@pytest.fixture()
def store(tmp_path):
    return SymbolIndexStore(tmp_path / "symbol_index.json")


@pytest.fixture()
def lib_file(tmp_path):
    dest = tmp_path / "Simulation_SPICE_minimal.kicad_sym"
    shutil.copy(FIXTURE_LIB, dest)
    return dest


@pytest.mark.unit
class TestSymbolIndexStore:
    def test_build_creates_index_file(self, store, lib_file):
        manager = _manager_for(lib_file, store)
        symbols = manager.list_symbols("Simulation_SPICE")
        assert symbols
        store.flush()

        assert store.path.is_file()
        data = json.loads(store.path.read_text(encoding="utf-8"))
        assert data["version"] == VERSION
        key = str(lib_file.resolve())
        assert key in data["entries"]
        entry = data["entries"][key]
        assert entry["mtime"] == os.stat(lib_file).st_mtime
        assert entry["size"] == os.stat(lib_file).st_size
        assert len(entry["symbols"]) == len(symbols)

    def test_second_manager_hits_index_without_parsing(
        self, store, lib_file, monkeypatch
    ):
        manager1 = _manager_for(lib_file, store)
        expected = manager1.list_symbols("Simulation_SPICE")
        store.flush()

        # Fresh store instance sharing the same path (simulates a restart)
        store2 = SymbolIndexStore(store.path)
        manager2 = _manager_for(lib_file, store2)
        monkeypatch.setattr(
            SymbolLibraryManager,
            "_parse_kicad_sym_file",
            lambda self, *a, **k: pytest.fail("must not re-parse on index hit"),
        )
        symbols = manager2.list_symbols("Simulation_SPICE")
        assert [s.name for s in symbols] == [s.name for s in expected]
        assert [s.full_ref for s in symbols] == [s.full_ref for s in expected]

    def test_mtime_invalidation(self, store, lib_file):
        manager = _manager_for(lib_file, store)
        manager.list_symbols("Simulation_SPICE")
        store.flush()

        t = os.stat(lib_file).st_mtime
        os.utime(lib_file, (t + 10, t + 10))
        assert store.get(str(lib_file)) is None

        # list_symbols re-parses (fresh manager to bypass in-memory cache)
        store2 = SymbolIndexStore(store.path)
        manager2 = _manager_for(lib_file, store2)
        parse_count = {"n": 0}
        original = SymbolLibraryManager._parse_kicad_sym_file

        def counting(self, *a, **k):
            parse_count["n"] += 1
            return original(self, *a, **k)

        SymbolLibraryManager._parse_kicad_sym_file = counting
        try:
            symbols = manager2.list_symbols("Simulation_SPICE")
        finally:
            SymbolLibraryManager._parse_kicad_sym_file = original
        assert symbols
        assert parse_count["n"] == 1

    def test_corrupt_index_starts_empty(self, tmp_path, lib_file):
        index_path = tmp_path / "symbol_index.json"
        index_path.write_text("{ not json !!", encoding="utf-8")
        store = SymbolIndexStore(index_path)
        assert store.get(str(lib_file)) is None
        # And it can still be rebuilt + flushed
        manager = _manager_for(lib_file, store)
        assert manager.list_symbols("Simulation_SPICE")
        store.flush()
        assert json.loads(index_path.read_text(encoding="utf-8"))["version"] == VERSION

    def test_version_mismatch_invalidates(self, tmp_path, lib_file):
        index_path = tmp_path / "symbol_index.json"
        st = os.stat(lib_file)
        index_path.write_text(
            json.dumps(
                {
                    "version": 0,
                    "entries": {
                        str(lib_file.resolve()): {
                            "mtime": st.st_mtime,
                            "size": st.st_size,
                            "symbols": [{"name": "STALE", "library": "X"}],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        store = SymbolIndexStore(index_path)
        assert store.get(str(lib_file)) is None

    def test_invalidate(self, store, lib_file):
        manager = _manager_for(lib_file, store)
        manager.list_symbols("Simulation_SPICE")
        assert store.get(str(lib_file)) is not None
        store.invalidate(str(lib_file))
        assert store.get(str(lib_file)) is None


@pytest.mark.unit
class TestSearchSymbolsIntegration:
    def _commands(self, lib_file, store) -> SymbolLibraryCommands:
        commands = SymbolLibraryCommands.__new__(SymbolLibraryCommands)
        commands.library_manager = _manager_for(lib_file, store)
        return commands

    def test_search_hits_via_index(self, store, lib_file):
        # Prime the index, then search through a fresh manager
        _manager_for(lib_file, store).list_symbols("Simulation_SPICE")
        store.flush()

        commands = self._commands(lib_file, SymbolIndexStore(store.path))
        r = commands.search_symbols({"query": "OPAMP"})
        assert r["success"], r
        assert any(s["full_ref"] == "Simulation_SPICE:OPAMP" for s in r["symbols"])

    def test_rebuild_index_forces_reparse(self, store, lib_file):
        commands = self._commands(lib_file, store)
        assert commands.search_symbols({"query": "OPAMP"})["success"]

        parse_count = {"n": 0}
        original = SymbolLibraryManager._parse_kicad_sym_file

        def counting(self, *a, **k):
            parse_count["n"] += 1
            return original(self, *a, **k)

        SymbolLibraryManager._parse_kicad_sym_file = counting
        try:
            r = commands.search_symbols({"query": "OPAMP", "rebuildIndex": True})
        finally:
            SymbolLibraryManager._parse_kicad_sym_file = original
        assert r["success"], r
        assert parse_count["n"] == 1  # index + in-memory cache both bypassed
        assert any(s["full_ref"] == "Simulation_SPICE:OPAMP" for s in r["symbols"])
