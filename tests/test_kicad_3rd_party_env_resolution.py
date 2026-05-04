"""
Regression tests for ``${KICAD_3RD_PARTY}`` (no-version-prefix) URI resolution
in both the symbol and footprint library managers.

Background:
    The Import-LIB-KiCad-Plugin (impart) documentation registers third-party
    libraries using ``${KICAD_3RD_PARTY}`` without a KiCad-version prefix.
    KiCad accepts both unprefixed and version-prefixed forms in lib-tables.

    Prior to this fix the env-var dictionaries in ``_resolve_uri`` only handled
    ``KICAD8/9/10_3RD_PARTY`` (analogous to ``KICAD_SYMBOL_DIR`` which *was*
    in the dictionary without a prefix). Lib-table rows authored as
    ``${KICAD_3RD_PARTY}/Foo.kicad_sym`` or ``${KICAD_3RD_PARTY}/Foo.pretty``
    therefore failed to resolve and disappeared from MCP listings even though
    KiCad's GUI showed them correctly.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.library import LibraryManager
from commands.library_symbol import SymbolLibraryManager


@pytest.mark.unit
def test_symbol_manager_resolves_unprefixed_kicad_3rd_party(monkeypatch, tmp_path):
    monkeypatch.setenv("KICAD_3RD_PARTY", str(tmp_path))
    target = tmp_path / "EasyEDA.kicad_sym"
    target.touch()

    manager = SymbolLibraryManager.__new__(SymbolLibraryManager)
    manager.project_path = None

    resolved = manager._resolve_uri("${KICAD_3RD_PARTY}/EasyEDA.kicad_sym")
    assert resolved == str(target)


@pytest.mark.unit
def test_library_manager_resolves_unprefixed_kicad_3rd_party(monkeypatch, tmp_path):
    monkeypatch.setenv("KICAD_3RD_PARTY", str(tmp_path))
    target_dir = tmp_path / "EasyEDA.pretty"
    target_dir.mkdir()

    manager = LibraryManager.__new__(LibraryManager)
    manager.project_path = None

    resolved = manager._resolve_uri("${KICAD_3RD_PARTY}/EasyEDA.pretty")
    assert resolved == str(target_dir)


@pytest.mark.unit
def test_versioned_and_unprefixed_forms_both_work(monkeypatch, tmp_path):
    """Both ``${KICAD10_3RD_PARTY}`` and ``${KICAD_3RD_PARTY}`` must resolve when
    the corresponding env vars are set, even pointing at the same directory."""
    monkeypatch.setenv("KICAD10_3RD_PARTY", str(tmp_path))
    monkeypatch.setenv("KICAD_3RD_PARTY", str(tmp_path))

    sym_target = tmp_path / "Mixed.kicad_sym"
    sym_target.touch()
    fp_target = tmp_path / "Mixed.pretty"
    fp_target.mkdir()

    sym_mgr = SymbolLibraryManager.__new__(SymbolLibraryManager)
    sym_mgr.project_path = None
    fp_mgr = LibraryManager.__new__(LibraryManager)
    fp_mgr.project_path = None

    assert sym_mgr._resolve_uri("${KICAD10_3RD_PARTY}/Mixed.kicad_sym") == str(sym_target)
    assert sym_mgr._resolve_uri("${KICAD_3RD_PARTY}/Mixed.kicad_sym") == str(sym_target)
    assert fp_mgr._resolve_uri("${KICAD10_3RD_PARTY}/Mixed.pretty") == str(fp_target)
    assert fp_mgr._resolve_uri("${KICAD_3RD_PARTY}/Mixed.pretty") == str(fp_target)
