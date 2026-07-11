"""
Regression test for the "empty-cache early-return" bug in SymbolLibraryCommands.

Scenario
--------
When a project is opened for the first time (e.g. right after `create_project`)
the `sym-lib-table` may not exist on disk yet.  `SymbolLibraryManager.__init__`
succeeds but leaves `self.libraries` empty.

The original `_rebuild_if_needed` guard was:

    if self.library_manager.project_path == project_path:
        return   # ← BUG: triggers even when libraries == {}

Because `project_path` already matched, the manager was never rebuilt when the
sym-lib-table finally appeared, so subsequent list_symbols / search_symbols calls
returned nothing.

Fix: also require that at least one library was loaded before skipping the rebuild.
"""

import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from kicad_mcp.commands.library_symbol import SymbolLibraryCommands, SymbolLibraryManager


def _make_empty_manager(project_path) -> SymbolLibraryManager:
    """Return a SymbolLibraryManager that matches the project but has no libraries loaded."""
    manager = SymbolLibraryManager.__new__(SymbolLibraryManager)
    manager.project_path = project_path
    manager.libraries = {}        # <-- empty: sym-lib-table wasn't there yet
    manager.symbol_cache = {}
    manager._cache_lock = threading.Lock()
    return manager


@pytest.mark.unit
class TestSymbolLibraryEmptyCacheRebuild:
    """Ensure _rebuild_if_needed re-initialises the manager when the cache is empty."""

    def test_rebuild_triggered_when_libraries_empty(self):
        """
        If the manager has a matching project_path but no libraries, calling
        _rebuild_if_needed with the same path MUST trigger a rebuild (not early-return).
        """
        project_path = "/fake/project/test.kicad_pro"

        cmds = SymbolLibraryCommands.__new__(SymbolLibraryCommands)
        cmds.library_manager = _make_empty_manager(project_path)

        rebuild_count = {"n": 0}
        original_manager = cmds.library_manager

        def fake_init(self, project_path=None):
            rebuild_count["n"] += 1
            self.project_path = project_path
            self.libraries = {"SomeLib": "/fake/SomeLib.kicad_sym"}
            self.symbol_cache = {}
            self._cache_lock = threading.Lock()

        with patch.object(SymbolLibraryManager, "__init__", fake_init):
            cmds.use_project(Path(project_path))

        assert rebuild_count["n"] == 1, (
            "Expected use_project to construct a new SymbolLibraryManager "
            "when libraries={}, but it returned early instead."
        )
        assert cmds.library_manager is not original_manager, (
            "The manager instance should have been replaced after rebuild."
        )
        assert len(cmds.library_manager.libraries) > 0

    def test_no_rebuild_when_libraries_already_loaded(self):
        """
        When the manager already has libraries loaded for this project, skip rebuild
        (the original happy-path must still work).
        """
        project_path = "/fake/project/test.kicad_pro"

        cmds = SymbolLibraryCommands.__new__(SymbolLibraryCommands)
        manager = _make_empty_manager(Path(project_path))
        manager.libraries = {"SomeLib": "/fake/SomeLib.kicad_sym"}  # non-empty
        cmds.library_manager = manager
        original_manager = cmds.library_manager

        rebuild_count = {"n": 0}

        def fake_init(self, project_path=None):
            rebuild_count["n"] += 1

        with patch.object(SymbolLibraryManager, "__init__", fake_init):
            cmds.use_project(Path(project_path))

        assert rebuild_count["n"] == 0, (
            "Should NOT rebuild when libraries are already loaded for the same project."
        )
        assert cmds.library_manager is original_manager

    def test_rebuild_on_different_project_path(self):
        """Changing project path always triggers rebuild (existing behaviour)."""
        old_path = "/fake/project/old.kicad_pro"
        new_path = "/fake/project/new.kicad_pro"

        cmds = SymbolLibraryCommands.__new__(SymbolLibraryCommands)
        manager = _make_empty_manager(Path(old_path))
        manager.libraries = {"SomeLib": "/fake/SomeLib.kicad_sym"}
        cmds.library_manager = manager

        rebuild_count = {"n": 0}

        def fake_init(self, project_path=None):
            rebuild_count["n"] += 1
            self.project_path = project_path
            self.libraries = {}
            self.symbol_cache = {}
            self._cache_lock = threading.Lock()

        with patch.object(SymbolLibraryManager, "__init__", fake_init):
            cmds.use_project(Path(new_path))

        assert rebuild_count["n"] == 1, (
            "Switching to a different project path must always trigger rebuild."
        )
