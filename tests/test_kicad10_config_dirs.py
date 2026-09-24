"""KiCad 10 user configuration directories (#425).

Three lookups were fixed to KiCad 9's configuration directory and failed
without an error on a machine that has only KiCad 10:

- ``register_footprint_library`` / ``register_symbol_library`` with
  ``scope="global"`` searched only ``kicad/9.0``, created a 9.0 table when none
  was there, and reported success. KiCad 10 reads ``kicad/10.0``, so the library
  never appeared. (With ``APPDATA`` unset, as on Linux and macOS, the first
  candidate was even a relative ``kicad/9.0`` under the server's working
  directory.)
- ``${KICAD10_3RD_PARTY}`` (PCM libraries) resolved only when the variable was
  set in the shell: the configuration branch read only the 9.0
  ``kicad_common.json``, only for ``KICAD9_3RD_PARTY``, and defaulted to 9.0.

Everything here runs against a fake home directory; the real KiCad
configuration is never read or written.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.footprint import FootprintCreator  # noqa: E402
from commands.library import LibraryManager  # noqa: E402
from commands.library_symbol import SymbolLibraryManager  # noqa: E402
from commands.symbol_creator import SymbolCreator  # noqa: E402
from utils.platform_helper import PlatformHelper  # noqa: E402

pytestmark = pytest.mark.unit

# The global tables KiCad 10 writes on first start: one row that chains to the
# stock table in the install (C:/KiCad/10.0 on this author's machine).
KICAD10_FP_TABLE = (
    "(fp_lib_table\n"
    "\t(version 7)\n"
    '\t(lib (name "KiCad") (type "Table") (uri "C:/KiCad/10.0/share/kicad/template/'
    'fp-lib-table") (options "") (descr "KiCad Default Libraries"))\n'
    ")\n"
)
KICAD10_SYM_TABLE = KICAD10_FP_TABLE.replace("fp_lib_table", "sym_lib_table").replace(
    "fp-lib-table", "sym-lib-table"
)
# What KiCad writes before the user adds a path variable.
KICAD_COMMON_NO_VARS = {"environment": {"vars": None}}


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake home directory with no KiCad configuration yet.

    Every variable that could point a lookup outside it is cleared, and the
    working directory moves into the temporary tree, so even a lookup that
    builds a relative path cannot write into the repository.
    """
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake)
    for var in (
        "APPDATA",
        "KICAD_CONFIG_HOME",
        "XDG_CONFIG_HOME",
        "KICAD10_3RD_PARTY",
        "KICAD9_3RD_PARTY",
        "KICAD8_3RD_PARTY",
        "KICAD_3RD_PARTY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    return fake


def _config(home: Path, version: str, **files: str) -> Path:
    """A KiCad user config directory for *version*, Linux layout."""
    directory = home / ".config" / "kicad" / version
    directory.mkdir(parents=True)
    for name, text in files.items():
        (directory / name.replace("_", "-")).write_text(text, encoding="utf-8")
    return directory


def _kicad_common(config_dir: Path, data: dict) -> None:
    (config_dir / "kicad_common.json").write_text(json.dumps(data), encoding="utf-8")


def _files_under(*roots: Path) -> set:
    return {p for root in roots if root.exists() for p in root.rglob("*") if p.is_file()}


# --- the config directory list --------------------------------------------- #


def test_config_dirs_put_the_newest_version_first(home, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    dirs = PlatformHelper.kicad_config_dirs()
    assert dirs[0] == tmp_path / "Roaming" / "kicad" / "10.0"
    versions = [d.name for d in dirs]
    assert versions.index("10.0") < versions.index("9.0") < versions.index("8.0")
    assert len(dirs) == len(set(dirs))


def test_kicad_config_home_is_searched_first(home, tmp_path, monkeypatch):
    # KiCad itself uses $KICAD_CONFIG_HOME/<version> instead of the platform
    # directory when the variable is set.
    monkeypatch.setenv("KICAD_CONFIG_HOME", str(tmp_path / "custom"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert PlatformHelper.kicad_config_dirs()[0] == tmp_path / "custom" / "10.0"


# --- global library registration ------------------------------------------- #


def test_global_footprint_registration_writes_the_kicad_10_table(home, tmp_path):
    config = _config(home, "10.0", fp_lib_table=KICAD10_FP_TABLE)
    pretty = tmp_path / "libs" / "Mine.pretty"
    pretty.mkdir(parents=True)

    r = FootprintCreator().register_footprint_library(library_path=str(pretty), scope="global")

    assert r["success"], r
    assert r["table_path"] == str(config / "fp-lib-table")
    table = (config / "fp-lib-table").read_text(encoding="utf-8")
    assert '(lib (name "Mine")' in table
    assert '(name "KiCad") (type "Table")' in table  # the stock row is kept
    assert not (home / ".config" / "kicad" / "9.0").exists()
    assert not (tmp_path / "kicad").exists()  # nothing relative to the cwd


def test_global_symbol_registration_writes_the_kicad_10_table(home, tmp_path):
    config = _config(home, "10.0", sym_lib_table=KICAD10_SYM_TABLE)
    lib = tmp_path / "libs" / "Mine.kicad_sym"
    lib.parent.mkdir(parents=True)
    lib.write_text("(kicad_symbol_lib)", encoding="utf-8")

    r = SymbolCreator().register_symbol_library(library_path=str(lib), scope="global")

    assert r["success"], r
    assert r["table_path"] == str(config / "sym-lib-table")
    assert '(lib (name "Mine")' in (config / "sym-lib-table").read_text(encoding="utf-8")
    assert not (home / ".config" / "kicad" / "9.0").exists()
    assert not (tmp_path / "kicad").exists()


def test_the_newest_table_wins_on_an_upgraded_machine(home, tmp_path):
    old = _config(home, "9.0", fp_lib_table=KICAD10_FP_TABLE)
    new = _config(home, "10.0", fp_lib_table=KICAD10_FP_TABLE)
    pretty = tmp_path / "Mine.pretty"
    pretty.mkdir()

    r = FootprintCreator().register_footprint_library(library_path=str(pretty), scope="global")

    assert r["table_path"] == str(new / "fp-lib-table")
    assert "Mine" not in (old / "fp-lib-table").read_text(encoding="utf-8")


@pytest.mark.parametrize("kind", ["footprint", "symbol"])
def test_no_global_table_is_an_error_and_creates_nothing(home, tmp_path, kind):
    # KiCad sets up its stock libraries on first start only when the global
    # table is missing, so a table created here, holding one row, would leave
    # that KiCad without any of them.
    _config(home, "10.0")  # KiCad 10 config directory, but no table in it
    before = _files_under(home, tmp_path)
    if kind == "footprint":
        pretty = tmp_path / "Mine.pretty"
        pretty.mkdir()
        r = FootprintCreator().register_footprint_library(library_path=str(pretty), scope="global")
        filename = "fp-lib-table"
    else:
        r = SymbolCreator().register_symbol_library(
            library_path=str(tmp_path / "Mine.kicad_sym"), scope="global"
        )
        filename = "sym-lib-table"

    assert r["success"] is False
    assert f"No global {filename} found" in r["error"]
    assert "scope='project'" in r["error"]
    assert _files_under(home, tmp_path) == before


# --- ${KICAD10_3RD_PARTY} ------------------------------------------------- #


def test_3rd_party_dir_defaults_to_the_kicad_10_location(home):
    _kicad_common(_config(home, "10.0"), KICAD_COMMON_NO_VARS)
    pcm = home / ".local" / "share" / "kicad" / "10.0" / "3rdparty"
    pcm.mkdir(parents=True)
    assert PlatformHelper.find_kicad_3rd_party_dir() == str(pcm)


def test_3rd_party_dir_reads_the_kicad_10_variable(home, tmp_path):
    # Set under Preferences > Configure Paths, stored with the version's own name.
    pcm = tmp_path / "pcm-packages"
    pcm.mkdir()
    _kicad_common(_config(home, "10.0"), {"environment": {"vars": {"KICAD10_3RD_PARTY": str(pcm)}}})
    assert PlatformHelper.find_kicad_3rd_party_dir() == str(pcm)


def test_3rd_party_dir_prefers_the_newest_configuration(home, tmp_path):
    stale = tmp_path / "kicad9-packages"
    stale.mkdir()
    _kicad_common(_config(home, "9.0"), {"environment": {"vars": {"KICAD9_3RD_PARTY": str(stale)}}})
    _kicad_common(_config(home, "10.0"), KICAD_COMMON_NO_VARS)
    pcm = home / "Documents" / "KiCad" / "10.0" / "3rdparty"
    pcm.mkdir(parents=True)
    assert PlatformHelper.find_kicad_3rd_party_dir() == str(pcm)


def test_3rd_party_dir_falls_back_to_an_older_default(home):
    # The symbol side always searched 10.0, 9.0 and 8.0 in turn; keep that.
    _kicad_common(_config(home, "10.0"), KICAD_COMMON_NO_VARS)
    old = home / "Documents" / "KiCad" / "9.0" / "3rdparty"
    old.mkdir(parents=True)
    assert PlatformHelper.find_kicad_3rd_party_dir() == str(old)


def test_shell_variable_still_wins(home, tmp_path, monkeypatch):
    _kicad_common(_config(home, "10.0"), KICAD_COMMON_NO_VARS)
    (home / "Documents" / "KiCad" / "10.0" / "3rdparty").mkdir(parents=True)
    shell = tmp_path / "from-shell"
    shell.mkdir()
    monkeypatch.setenv("KICAD10_3RD_PARTY", str(shell))
    assert PlatformHelper.find_kicad_3rd_party_dir() == str(shell)


def test_footprint_library_manager_resolves_a_kicad_10_pcm_row(home):
    """End to end: a PCM row in the KiCad 10 global table resolves."""
    pretty = (
        home / "Documents" / "KiCad" / "10.0" / "3rdparty" / "footprints" / "com_x" / "Pcm.pretty"
    )
    pretty.mkdir(parents=True)
    config = _config(
        home,
        "10.0",
        fp_lib_table=(
            "(fp_lib_table\n\t(version 7)\n"
            '\t(lib (name "Pcm") (type "KiCad") (uri "${KICAD10_3RD_PARTY}/footprints/com_x/'
            'Pcm.pretty") (options "") (descr ""))\n)\n'
        ),
    )
    _kicad_common(config, KICAD_COMMON_NO_VARS)

    assert LibraryManager().libraries.get("Pcm") == str(pretty)


def test_symbol_library_manager_resolves_a_linux_pcm_row(home, monkeypatch):
    """The symbol side searched only Documents/KiCad/<ver>/3rdparty, which is
    the Windows and macOS default; Linux keeps PCM packages under
    ~/.local/share/kicad/<ver>/3rdparty."""
    monkeypatch.setenv("KICAD_SKIP_SYMBOL_WARMUP", "1")
    lib = home / ".local" / "share" / "kicad" / "10.0" / "3rdparty" / "symbols" / "com_x"
    lib.mkdir(parents=True)
    lib = lib / "Pcm.kicad_sym"
    lib.write_text("(kicad_symbol_lib)", encoding="utf-8")
    config = _config(
        home,
        "10.0",
        sym_lib_table=(
            "(sym_lib_table\n\t(version 7)\n"
            '\t(lib (name "Pcm") (type "KiCad") (uri "${KICAD10_3RD_PARTY}/symbols/com_x/'
            'Pcm.kicad_sym") (options "") (descr ""))\n)\n'
        ),
    )
    _kicad_common(config, KICAD_COMMON_NO_VARS)

    assert SymbolLibraryManager().libraries.get("Pcm") == str(lib)
