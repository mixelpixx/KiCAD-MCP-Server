"""
Regression tests for user-defined environment variables from kicad_common.json.

KiCad stores custom path variables (Preferences > Configure Paths) in
kicad_common.json under ``environment.vars``.  Users reference these in
sym-lib-table / fp-lib-table URIs, e.g. ``${SEEK}/seex.kicad_sym``.

Prior to this fix ``_resolve_uri`` only knew about built-in KiCad variables
(``KICAD9_SYMBOL_DIR``, ``KICAD_3RD_PARTY``, ``KIPRJMOD``, ...) and never read
kicad_common.json, so libraries registered with custom variables silently
failed to resolve.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.library import LibraryManager
from commands.library_symbol import SymbolLibraryManager
from commands import library, library_symbol


def _make_footprint_manager() -> LibraryManager:
    manager = LibraryManager.__new__(LibraryManager)
    manager.project_path = None
    manager.libraries = {}
    manager.footprint_cache = {}
    return manager


def _make_symbol_manager() -> SymbolLibraryManager:
    manager = SymbolLibraryManager.__new__(SymbolLibraryManager)
    manager.project_path = None
    manager.libraries = {}
    manager.symbol_cache = {}
    return manager


@pytest.mark.unit
def test_symbol_manager_resolves_user_defined_env_var(monkeypatch, tmp_path):
    """A user-defined var from kicad_common.json must resolve in _resolve_uri."""
    monkeypatch.setattr(
        library_symbol.PlatformHelper,
        "load_kicad_env_vars",
        staticmethod(lambda: {"MY_CUSTOM_LIB": str(tmp_path / "libs")}),
    )

    target = tmp_path / "libs" / "mylib.kicad_sym"
    target.parent.mkdir(parents=True)
    target.touch()

    manager = _make_symbol_manager()

    resolved = manager._resolve_uri("${MY_CUSTOM_LIB}/mylib.kicad_sym")
    assert resolved == str(target)


@pytest.mark.unit
def test_library_manager_resolves_user_defined_env_var(monkeypatch, tmp_path):
    """User-defined vars must also work for footprint library URIs."""
    monkeypatch.setattr(
        library.PlatformHelper,
        "load_kicad_env_vars",
        staticmethod(lambda: {"MY_CUSTOM_LIB": str(tmp_path / "libs")}),
    )

    target_dir = tmp_path / "libs" / "mylib.pretty"
    target_dir.mkdir(parents=True)

    manager = _make_footprint_manager()

    resolved = manager._resolve_uri("${MY_CUSTOM_LIB}/mylib.pretty")
    assert resolved == str(target_dir)


@pytest.mark.unit
def test_sym_lib_table_entry_with_user_var_is_loaded(monkeypatch, tmp_path):
    """End-to-end: a sym-lib-table row using a user-defined var must end up
    in ``manager.libraries`` after parsing."""
    monkeypatch.setattr(
        library_symbol.PlatformHelper,
        "load_kicad_env_vars",
        staticmethod(lambda: {"MY_CUSTOM_LIB": str(tmp_path / "libs")}),
    )

    lib_file = tmp_path / "libs" / "mylib.kicad_sym"
    lib_file.parent.mkdir(parents=True)
    lib_file.write_text("(kicad_symbol_lib (version 20231120))", encoding="utf-8")

    table_path = tmp_path / "sym-lib-table"
    table_path.write_text(
        "\n".join(
            [
                "(sym_lib_table",
                '  (lib (name "mylib")(type "KiCad")'
                f'(uri "${{MY_CUSTOM_LIB}}/mylib.kicad_sym")(options "")(descr ""))',
                ")",
            ]
        ),
        encoding="utf-8",
    )

    manager = _make_symbol_manager()
    manager._parse_sym_lib_table(table_path)

    assert manager.libraries.get("mylib") == str(lib_file)


@pytest.mark.unit
def test_user_defined_and_builtin_vars_coexist(monkeypatch, tmp_path):
    """User-defined vars and built-in vars (KIPRJMOD) must both resolve
    without interfering with each other."""
    monkeypatch.setattr(
        library_symbol.PlatformHelper,
        "load_kicad_env_vars",
        staticmethod(lambda: {"MY_CUSTOM_LIB": str(tmp_path / "libs")}),
    )

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    lib_file = tmp_path / "libs" / "lib.kicad_sym"
    lib_file.parent.mkdir(parents=True)
    lib_file.write_text("(kicad_symbol_lib (version 20231120))", encoding="utf-8")

    manager = _make_symbol_manager()
    manager.project_path = project_dir

    assert manager._resolve_uri("${MY_CUSTOM_LIB}/lib.kicad_sym") == str(lib_file)
    assert manager._resolve_uri("${KIPRJMOD}") == str(project_dir)
