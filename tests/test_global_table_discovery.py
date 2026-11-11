"""Library discovery when KiCad's global tables are not in ~/.config/kicad.

The table editor (``library_tables``) already found the user's global tables
through ``PlatformHelper.kicad_config_dirs``, which honours KICAD_CONFIG_HOME,
XDG_CONFIG_HOME and APPDATA. The three readers that list and search libraries
(``LibraryManager``, ``SymbolLibraryManager`` and the dynamic symbol loader)
each had their own hard-coded list of ``~/.config/kicad/<ver>`` paths. Two
consequences:

- With ``KICAD_CONFIG_HOME`` set (KiCad's own override, and how a user-space or
  CI install keeps its configuration), ``list_symbol_libraries`` and
  ``list_libraries`` found 0 libraries while ``list_library_table`` showed the
  table.
- On a fresh install, before KiCad has created a user table, they also found 0
  libraries, even though the stock libraries are all listed in KiCad's
  ``template/sym-lib-table`` and ``template/fp-lib-table``.

Everything here runs against a fake home; the real KiCad configuration is never
read or written.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands import library_tables  # noqa: E402
from commands.dynamic_symbol_loader import DynamicSymbolLoader  # noqa: E402
from commands.library import LibraryManager  # noqa: E402
from commands.library_symbol import SymbolLibraryManager  # noqa: E402
from utils.platform_helper import PlatformHelper  # noqa: E402

pytestmark = pytest.mark.unit


def _sym_table(rows):
    body = "".join(
        f'\t(lib (name "{n}") (type "KiCad") (uri "{u}") (options "") (descr ""))\n'
        for n, u in rows
    )
    return f"(sym_lib_table\n\t(version 7)\n{body})\n"


def _fp_table(rows):
    return _sym_table(rows).replace("sym_lib_table", "fp_lib_table")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fake home with no KiCad configuration, and a fake KiCad install.

    The install has one stock symbol library (StockSym), one stock footprint
    library (StockFp), and template tables that list them through the
    KICAD10_* variables, the way a real KiCad 10 install does.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    for var in (
        "APPDATA",
        "KICAD_CONFIG_HOME",
        "XDG_CONFIG_HOME",
        "KICAD10_TEMPLATE_DIR",
        "KICAD9_TEMPLATE_DIR",
        "KICAD8_TEMPLATE_DIR",
        "KICAD_TEMPLATE_DIR",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("KICAD_SKIP_SYMBOL_WARMUP", "1")
    monkeypatch.chdir(tmp_path)

    install = tmp_path / "install"
    symbols = install / "symbols"
    footprints = install / "footprints"
    template = install / "template"
    for d in (symbols, footprints / "StockFp.pretty", template):
        d.mkdir(parents=True, exist_ok=True)
    (symbols / "StockSym.kicad_sym").write_text("(kicad_symbol_lib)\n", encoding="utf-8")
    (template / "sym-lib-table").write_text(
        _sym_table([("StockSym", "${KICAD10_SYMBOL_DIR}/StockSym.kicad_sym")]), encoding="utf-8"
    )
    (template / "fp-lib-table").write_text(
        _fp_table([("StockFp", "${KICAD10_FOOTPRINT_DIR}/StockFp.pretty")]), encoding="utf-8"
    )
    monkeypatch.setenv("KICAD10_SYMBOL_DIR", str(symbols))
    monkeypatch.setenv("KICAD10_FOOTPRINT_DIR", str(footprints))
    monkeypatch.setenv("KICAD10_TEMPLATE_DIR", str(template))

    # A user library outside the install, for the user-table cases.
    user_lib = tmp_path / "mylibs"
    (user_lib / "Mine.pretty").mkdir(parents=True)
    (user_lib / "Mine.kicad_sym").write_text("(kicad_symbol_lib)\n", encoding="utf-8")
    return {"home": home, "tmp": tmp_path, "template": template, "user_lib": user_lib}


def _user_tables(config_dir: Path, user_lib: Path) -> None:
    config_dir.mkdir(parents=True)
    (config_dir / "sym-lib-table").write_text(
        _sym_table([("Mine", str(user_lib / "Mine.kicad_sym"))]), encoding="utf-8"
    )
    (config_dir / "fp-lib-table").write_text(
        _fp_table([("Mine", str(user_lib / "Mine.pretty"))]), encoding="utf-8"
    )


# --- KICAD_CONFIG_HOME ------------------------------------------------------ #


def test_symbol_reader_honours_kicad_config_home(env, monkeypatch):
    conf = env["tmp"] / "kconf"
    _user_tables(conf / "10.0", env["user_lib"])
    monkeypatch.setenv("KICAD_CONFIG_HOME", str(conf))
    assert "Mine" in SymbolLibraryManager().libraries


def test_footprint_reader_honours_kicad_config_home(env, monkeypatch):
    conf = env["tmp"] / "kconf"
    _user_tables(conf / "10.0", env["user_lib"])
    monkeypatch.setenv("KICAD_CONFIG_HOME", str(conf))
    assert "Mine" in LibraryManager().libraries


def test_dynamic_loader_finds_a_user_library_under_kicad_config_home(env, monkeypatch):
    conf = env["tmp"] / "kconf"
    _user_tables(conf / "10.0", env["user_lib"])
    monkeypatch.setenv("KICAD_CONFIG_HOME", str(conf))
    found = DynamicSymbolLoader().find_library_file("Mine")
    assert found is not None and Path(found).name == "Mine.kicad_sym"


def test_readers_honour_xdg_config_home(env, monkeypatch):
    xdg = env["tmp"] / "xdg"
    _user_tables(xdg / "kicad" / "10.0", env["user_lib"])
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    assert "Mine" in SymbolLibraryManager().libraries
    assert "Mine" in LibraryManager().libraries


# --- fresh install: no user table yet --------------------------------------- #


def test_fresh_install_lists_the_stock_symbol_libraries(env):
    libs = SymbolLibraryManager().libraries
    assert "StockSym" in libs


def test_fresh_install_lists_the_stock_footprint_libraries(env):
    libs = LibraryManager().libraries
    assert "StockFp" in libs


def test_user_table_wins_over_the_template(env):
    _user_tables(env["home"] / ".config" / "kicad" / "10.0", env["user_lib"])
    libs = SymbolLibraryManager().libraries
    assert "Mine" in libs
    assert "StockSym" not in libs  # the user table, not the template, is what KiCad reads


def test_writers_still_see_no_global_table_on_a_fresh_install(env):
    """The template is a read fallback only. A writer that took it for the
    global table would edit KiCad's install, or (via register) create a
    one-row user table that hides every stock library from KiCad."""
    assert library_tables.global_table_path("symbol") is None
    assert library_tables.global_table_path("footprint") is None
    assert library_tables.global_table_for_reading("symbol") == env["template"] / "sym-lib-table"


def test_nothing_found_when_there_is_neither_a_user_table_nor_a_template(env, monkeypatch):
    monkeypatch.setattr(PlatformHelper, "find_kicad_template_dir", staticmethod(lambda: None))
    assert library_tables.global_table_for_reading("symbol") is None
    assert SymbolLibraryManager().libraries == {}
