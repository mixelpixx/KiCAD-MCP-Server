"""Regression tests for issue #248:

    sync_schematic_to_board re-parses the project's fp-lib-table on every
    call instead of caching it

``_add_missing_footprints_from_schematic`` used to build a fresh
``LibraryManager`` (which re-parses the global + project fp-lib-table,
recursively following any ``Table`` references) on every single call. In an
iterative rebuild flow, where the tool is invoked repeatedly against the same
project, that is pure re-parsing overhead. ``_get_project_library_manager``
caches the manager on the interface instance and rebuilds it only when the
project directory changes or an fp-lib-table it parsed is modified (e.g. by
``register_footprint_library`` or a KiCad GUI edit mid-session).
"""

import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.schematic_handlers import SchematicHandlersMixin  # noqa: E402


class _Host(SchematicHandlersMixin):
    """Stand-in for KiCADInterface — only the caching attributes matter here."""


def _fake_library_manager():
    """A drop-in replacement for LibraryManager that records each construction."""
    calls = []

    class _FakeLibraryManager:
        def __init__(self, project_path=None):
            calls.append(project_path)
            self.project_path = project_path
            self.libraries = {}

    return _FakeLibraryManager, calls


def test_same_project_dir_reuses_cached_manager():
    fake_cls, calls = _fake_library_manager()
    host = _Host()
    project_dir = Path("/tmp/project_a")
    with patch("commands.library.LibraryManager", fake_cls):
        first = host._get_project_library_manager(project_dir)
        second = host._get_project_library_manager(project_dir)
        third = host._get_project_library_manager(project_dir)
    assert first is second is third
    assert calls == [project_dir]


def test_different_project_dir_rebuilds_manager():
    fake_cls, calls = _fake_library_manager()
    host = _Host()
    with patch("commands.library.LibraryManager", fake_cls):
        first = host._get_project_library_manager(Path("/tmp/project_a"))
        second = host._get_project_library_manager(Path("/tmp/project_b"))
        back_to_first = host._get_project_library_manager(Path("/tmp/project_a"))
    assert first is not second
    assert back_to_first is not first  # switching projects again also rebuilds
    assert calls == [Path("/tmp/project_a"), Path("/tmp/project_b"), Path("/tmp/project_a")]


def test_cache_is_per_instance_not_global():
    fake_cls, calls = _fake_library_manager()
    project_dir = Path("/tmp/project_a")
    with patch("commands.library.LibraryManager", fake_cls):
        _Host()._get_project_library_manager(project_dir)
        _Host()._get_project_library_manager(project_dir)
    # Two distinct hosts (distinct KiCADInterface sessions) must not share state.
    assert calls == [project_dir, project_dir]


def test_fp_lib_table_edit_invalidates_cache(tmp_path):
    """Editing the project fp-lib-table mid-session must rebuild the manager.

    ``register_footprint_library`` rewrites the project (or global)
    fp-lib-table while the server is running, and the KiCad GUI can too. A
    cache keyed only on the project directory would keep serving library data
    parsed *before* the edit — footprints from a just-registered library
    would be silently skipped by ``sync_schematic_to_board``.
    """
    fake_cls, calls = _fake_library_manager()
    host = _Host()
    table = tmp_path / "fp-lib-table"
    table.write_text("(fp_lib_table\n  (version 7)\n)\n")
    with patch("commands.library.LibraryManager", fake_cls):
        first = host._get_project_library_manager(tmp_path)
        assert host._get_project_library_manager(tmp_path) is first  # cache hit
        # A registration rewrites the table. Force the mtime forward so the
        # test doesn't depend on filesystem timestamp granularity.
        table.write_text('(fp_lib_table\n  (version 7)\n  (lib (name "custom"))\n)\n')
        bumped = time.time_ns() + 1_000_000_000
        os.utime(table, ns=(bumped, bumped))
        rebuilt = host._get_project_library_manager(tmp_path)
    assert rebuilt is not first
    assert calls == [tmp_path, tmp_path]
