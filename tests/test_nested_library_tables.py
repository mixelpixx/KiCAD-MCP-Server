"""KiCad 10's nested library tables: ``(type "Table")`` rows are followed.

KiCad 10's global sym-lib-table and fp-lib-table hold one row standing for
every stock library:

    (lib (name "KiCad") (type "Table") (uri "${KICAD10_TEMPLATE_DIR}/sym-lib-table"))

The loaders followed a Table row only when its URI was already an absolute
path, and nothing resolved ``KICAD*_TEMPLATE_DIR``, so on a stock KiCad 10
install search_symbols found nothing, list_library_symbols("Device") failed,
and remove_library_table_entry reported the stock row as standing for 0
libraries (there are 223 in 10.0.6).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.library import LibraryManager  # noqa: E402
from commands.library_symbol import SymbolLibraryManager  # noqa: E402
from commands.library_tables import remove_library_table_entry  # noqa: E402
from utils.platform_helper import PlatformHelper  # noqa: E402

_TEMPLATE_VARS = ("KICAD10_TEMPLATE_DIR", "KICAD9_TEMPLATE_DIR", "KICAD8_TEMPLATE_DIR")


def _table(kind: str, rows: str) -> str:
    return f"({kind}\n\t(version 7)\n{rows})\n"


def _row(name: str, typ: str, uri: str) -> str:
    return f'\t(lib (name "{name}") (type "{typ}") (uri "{uri}") (options "") (descr ""))\n'


def _bare(cls):  # a manager without __init__'s library scan
    manager = cls.__new__(cls)
    manager.project_path = None
    manager.libraries = {}
    return manager


@pytest.fixture
def stock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake KiCad template dir holding the stock tables, one library each."""
    for var in _TEMPLATE_VARS + ("KICAD_TEMPLATE_DIR",):
        monkeypatch.delenv(var, raising=False)
    template = tmp_path / "template"
    template.mkdir()
    sym = tmp_path / "Device.kicad_sym"
    sym.write_text("(kicad_symbol_lib (version 20251024))\n", encoding="utf-8")
    pretty = tmp_path / "Resistor_SMD.pretty"
    pretty.mkdir()
    (template / "sym-lib-table").write_text(
        _table("sym_lib_table", _row("Device", "KiCad", str(sym))), encoding="utf-8"
    )
    (template / "fp-lib-table").write_text(
        _table("fp_lib_table", _row("Resistor_SMD", "KiCad", str(pretty))), encoding="utf-8"
    )
    monkeypatch.setenv("KICAD10_TEMPLATE_DIR", str(template))
    return template


def _global(tmp_path: Path, kind: str, filename: str) -> Path:
    path = tmp_path / f"global-{filename}"
    path.write_text(
        _table(kind, _row("KiCad", "Table", f"${{KICAD10_TEMPLATE_DIR}}/{filename}")),
        encoding="utf-8",
    )
    return path


@pytest.mark.unit
class TestNestedTables:
    def test_template_dir_from_environment(self, stock: Path) -> None:
        assert PlatformHelper.find_kicad_template_dir() == str(stock)

    def test_symbol_table_row_is_followed(self, stock: Path, tmp_path: Path) -> None:
        manager = _bare(SymbolLibraryManager)
        manager._parse_sym_lib_table(_global(tmp_path, "sym_lib_table", "sym-lib-table"))
        assert manager.libraries == {"Device": str(tmp_path / "Device.kicad_sym")}

    def test_footprint_table_row_is_followed(self, stock: Path, tmp_path: Path) -> None:
        manager = _bare(LibraryManager)
        manager._parse_fp_lib_table(_global(tmp_path, "fp_lib_table", "fp-lib-table"))
        assert manager.libraries == {"Resistor_SMD": str(tmp_path / "Resistor_SMD.pretty")}

    def test_table_that_includes_itself_terminates(self, stock: Path, tmp_path: Path) -> None:
        loop = stock / "sym-lib-table"
        text = loop.read_text(encoding="utf-8").replace(
            "(version 7)\n", "(version 7)\n" + _row("Self", "Table", str(loop))
        )
        loop.write_text(text, encoding="utf-8")
        manager = _bare(SymbolLibraryManager)
        manager._parse_sym_lib_table(_global(tmp_path, "sym_lib_table", "sym-lib-table"))
        assert list(manager.libraries) == ["Device"]

    def test_unresolvable_table_row_is_skipped(self, stock: Path, tmp_path: Path) -> None:
        table = tmp_path / "bad-sym-lib-table"
        table.write_text(
            _table("sym_lib_table", _row("Gone", "Table", "${KICAD10_NOPE}/sym-lib-table")),
            encoding="utf-8",
        )
        manager = _bare(SymbolLibraryManager)
        manager._parse_sym_lib_table(table)
        assert manager.libraries == {}

    def test_removal_warning_counts_the_stock_libraries(
        self, stock: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # KiCad defines KICAD10_TEMPLATE_DIR internally, so on a real machine it
        # is not in the environment: resolution has to come from discovery.
        monkeypatch.delenv("KICAD10_TEMPLATE_DIR")
        monkeypatch.setattr(
            PlatformHelper,
            "find_kicad_template_dir",
            staticmethod(lambda: str(stock)),
            raising=False,
        )
        table = _global(tmp_path, "sym_lib_table", "sym-lib-table")
        before = table.read_text(encoding="utf-8")
        r = remove_library_table_entry(
            {"tablePath": str(table), "tableType": "symbol", "libraryName": "KiCad", "dryRun": True}
        )
        assert r["success"] is True
        assert r["referencedLibraryCount"] == 1
        assert table.read_text(encoding="utf-8") == before


@pytest.mark.integration
def test_stock_kicad_install_resolves_device(tmp_path: Path) -> None:
    """On a real install, the stock row reaches the Device library."""
    template = PlatformHelper.find_kicad_template_dir()
    if not template or not (Path(template) / "sym-lib-table").is_file():
        pytest.skip("KiCad template directory not available")
    manager = _bare(SymbolLibraryManager)
    manager._parse_sym_lib_table(_global(tmp_path, "sym_lib_table", "sym-lib-table"))
    assert "Device" in manager.libraries
    assert Path(manager.libraries["Device"]).is_file()
