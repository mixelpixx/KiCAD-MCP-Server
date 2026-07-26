"""Regression tests for the module-level symbol caches (#299 / #320).

The caches in ``dynamic_symbol_loader`` and ``library_symbol`` survive across
loader / manager instances by design, but symbol libraries are not immutable
during a process run: ``create_symbol`` / ``delete_symbol`` rewrite
``.kicad_sym`` files and ``register_symbol_library`` rewrites the
sym-lib-table. These tests pin the guards that keep cached data from
outliving on-disk edits:

- resolution misses are never cached (create-then-place flows depend on it),
- resolved paths are revalidated with ``exists()``,
- extracted symbol blocks and parsed symbol lists carry the source file's
  ``mtime_ns`` and expire when it changes,
- the ``SymbolCreator`` write paths explicitly clear the loader caches.
"""

import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands import dynamic_symbol_loader as dsl_mod  # noqa: E402
from commands.dynamic_symbol_loader import DynamicSymbolLoader  # noqa: E402
from commands.library_symbol import SymbolLibraryManager  # noqa: E402

MINIMAL_LIB = """(kicad_symbol_lib (version 20241209) (generator "test")
  (symbol "Foo" (in_bom yes) (on_board yes)
    (property "Reference" "U" (at 0 0 0))
    (property "Value" "Foo" (at 0 0 0))
    (property "Description" "First revision" (at 0 0 0))
  )
)
"""

MINIMAL_LIB_EDITED = MINIMAL_LIB.replace('"Value" "Foo"', '"Value" "FooV2"')

MINIMAL_LIB_TWO_SYMBOLS = MINIMAL_LIB.replace(
    ")\n",
    """)
  (symbol "Bar" (in_bom yes) (on_board yes)
    (property "Reference" "U" (at 0 0 0))
    (property "Value" "Bar" (at 0 0 0))
    (property "Description" "Second symbol" (at 0 0 0))
  )
)
""",
    1,
)


def _bump_mtime(path: Path) -> None:
    """Force the mtime forward so tests don't depend on fs timestamp granularity."""
    ns = time.time_ns() + 1_000_000_000
    os.utime(path, ns=(ns, ns))


@pytest.fixture(autouse=True)
def _clean_loader_caches():
    """Module caches must not leak between tests (in either direction)."""
    DynamicSymbolLoader.clear_library_caches()
    yield
    DynamicSymbolLoader.clear_library_caches()


def test_library_created_after_first_miss_is_found(tmp_path, monkeypatch):
    """A resolution miss must not be cached: register-then-place depends on it."""
    monkeypatch.setenv("KICAD_SYMBOL_DIR", str(tmp_path))
    assert DynamicSymbolLoader().find_library_file("Foo") is None
    (tmp_path / "Foo.kicad_sym").write_text(MINIMAL_LIB, encoding="utf-8")
    assert DynamicSymbolLoader().find_library_file("Foo") == tmp_path / "Foo.kicad_sym"


def test_deleted_library_is_not_served_from_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("KICAD_SYMBOL_DIR", str(tmp_path))
    lib = tmp_path / "Foo.kicad_sym"
    lib.write_text(MINIMAL_LIB, encoding="utf-8")
    assert DynamicSymbolLoader().find_library_file("Foo") == lib
    lib.unlink()
    assert DynamicSymbolLoader().find_library_file("Foo") is None


def test_symbol_edit_invalidates_extract_cache(tmp_path, monkeypatch):
    """add_library-style edits must be visible to the next extract."""
    monkeypatch.setenv("KICAD_SYMBOL_DIR", str(tmp_path))
    lib = tmp_path / "Foo.kicad_sym"
    lib.write_text(MINIMAL_LIB, encoding="utf-8")
    first = DynamicSymbolLoader().extract_symbol_from_library("Foo", "Foo")
    assert first is not None
    assert '"FooV2"' not in first
    lib.write_text(MINIMAL_LIB_EDITED, encoding="utf-8")
    _bump_mtime(lib)
    second = DynamicSymbolLoader().extract_symbol_from_library("Foo", "Foo")
    assert second is not None
    assert '"FooV2"' in second


def test_symbol_created_after_missing_extract_is_found(tmp_path, monkeypatch):
    """A cached "symbol not found" expires when the library file changes."""
    monkeypatch.setenv("KICAD_SYMBOL_DIR", str(tmp_path))
    lib = tmp_path / "Foo.kicad_sym"
    lib.write_text(MINIMAL_LIB, encoding="utf-8")
    assert DynamicSymbolLoader().extract_symbol_from_library("Foo", "Bar") is None
    lib.write_text(MINIMAL_LIB_TWO_SYMBOLS, encoding="utf-8")
    _bump_mtime(lib)
    assert DynamicSymbolLoader().extract_symbol_from_library("Foo", "Bar") is not None


def test_symbol_creator_write_clears_loader_caches(tmp_path, monkeypatch):
    """The mutating write paths must drop the resolution caches explicitly."""
    from commands.symbol_creator import SymbolCreator

    monkeypatch.setenv("KICAD_SYMBOL_DIR", str(tmp_path))
    lib = tmp_path / "Foo.kicad_sym"
    lib.write_text(MINIMAL_LIB, encoding="utf-8")
    assert DynamicSymbolLoader().find_library_file("Foo") == lib
    assert dsl_mod._LIB_DIRS_CACHE is not None  # primed by the lookup
    result = SymbolCreator().create_symbol(library_path=str(lib), name="Baz", pins=[])
    assert result["success"] is True, result
    assert dsl_mod._LIB_DIRS_CACHE is None  # cleared by the write


def test_instance_patched_discovery_does_not_poison_shared_cache(tmp_path):
    """Loaders with instance-patched discovery must bypass the shared cache.

    tests/test_symdir_extends.py builds one loader per test, each with
    ``loader.find_kicad_symbol_libraries = lambda: [its own tmp dir]`` and the
    SAME library name. That per-instance state is invisible to any
    module-level cache key, so the first loader's resolution must not be
    served to the second.
    """
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    for d in (dir_a, dir_b):
        d.mkdir()
        (d / "TestLib.kicad_sym").write_text(MINIMAL_LIB, encoding="utf-8")

    loader_a = DynamicSymbolLoader()
    loader_a.find_kicad_symbol_libraries = lambda: [dir_a]  # type: ignore[method-assign]
    loader_b = DynamicSymbolLoader()
    loader_b.find_kicad_symbol_libraries = lambda: [dir_b]  # type: ignore[method-assign]

    assert loader_a.find_library_file("TestLib") == dir_a / "TestLib.kicad_sym"
    assert loader_b.find_library_file("TestLib") == dir_b / "TestLib.kicad_sym"


def test_env_change_invalidates_discovery_caches(tmp_path, monkeypatch):
    """KICAD*_SYMBOL_DIR is an input to discovery, so it belongs to the key."""
    dir_a, dir_b = tmp_path / "a", tmp_path / "b"
    for d in (dir_a, dir_b):
        d.mkdir()
        (d / "TestLib.kicad_sym").write_text(MINIMAL_LIB, encoding="utf-8")

    monkeypatch.setenv("KICAD_SYMBOL_DIR", str(dir_a))
    assert DynamicSymbolLoader().find_library_file("TestLib") == dir_a / "TestLib.kicad_sym"
    monkeypatch.setenv("KICAD_SYMBOL_DIR", str(dir_b))
    assert DynamicSymbolLoader().find_library_file("TestLib") == dir_b / "TestLib.kicad_sym"


def _manager_for(lib: Path, nickname: str) -> SymbolLibraryManager:
    manager = SymbolLibraryManager.__new__(SymbolLibraryManager)
    manager.project_path = None
    manager.libraries = {nickname: str(lib)}
    manager.symbol_cache = {}
    manager._cache_lock = threading.Lock()
    return manager


def test_list_symbols_reparses_after_library_edit(tmp_path):
    """The process-wide parsed-symbol cache expires when the file changes."""
    lib = tmp_path / "Edit.kicad_sym"
    lib.write_text(MINIMAL_LIB, encoding="utf-8")
    assert len(_manager_for(lib, "Edit").list_symbols("Edit")) == 1
    lib.write_text(MINIMAL_LIB_TWO_SYMBOLS, encoding="utf-8")
    _bump_mtime(lib)
    # A FRESH manager (empty instance cache) must not be served the stale
    # process-wide entry.
    names = [s.name for s in _manager_for(lib, "Edit").list_symbols("Edit")]
    assert sorted(names) == ["Bar", "Foo"]
