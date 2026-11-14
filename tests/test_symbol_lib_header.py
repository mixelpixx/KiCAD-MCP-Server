"""New .kicad_sym headers match the project's schematic format (#420, PR #535).

KiCad refuses a library that declares a newer format than its own writer (a
20251024 header fails to load on KiCad 9), while a 20241209 header loads on
both 9 and 10 — with an upgrade notice on 10. So the KiCad 9 header is the
fallback, and the KiCad 10 header is written only when the project's root
schematic positively declares a KiCad 10 format. Which KiCad is installed
plays no part: several versions side by side must not force the newest
format on a project still on an older one.

The rule lives in commands.symbol_creator.symbol_lib_header and is shared by
all three writers (create_symbol, export_symbol, the Eagle importer). These
tests run without KiCad installed; they follow tests/test_schematic_writer_
format_compat.py from #410, which pins the same rule on the schematic side.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.eagle import generate_sym_lib  # noqa: E402
from commands.library_management import LibraryManagementCommands  # noqa: E402
from commands.symbol_creator import SymbolCreator, symbol_lib_header  # noqa: E402

# Format version tokens, by the KiCad release that introduced them.
V9 = 20250114
V10 = 20260101

SYMBOL_V9 = """(kicad_symbol_lib
\t(version 20241209)
\t(generator "test")
\t(generator_version "9.0")
\t(symbol "R_10K_0603"
\t\t(property "Reference" "R" (at 0 2.54 0))
\t\t(symbol "R_10K_0603_1_1"
\t\t\t(pin passive line (at -5.08 0 0) (length 2.54)
\t\t\t\t(name "1") (number "1"))
\t\t\t(pin passive line (at 5.08 0 180) (length 2.54)
\t\t\t\t(name "2") (number "2"))
\t\t)
\t)
)
"""


def _make_project(root: Path, sch_version: int) -> Path:
    """A KiCad project whose root schematic declares *sch_version*."""
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{root.name}.kicad_pro").write_text(
        '{"meta":{"filename":"' + root.name + '.kicad_pro"}}\n', encoding="utf-8"
    )
    (root / f"{root.name}.kicad_sch").write_text(
        f'(kicad_sch (version {sch_version}) (generator "test")\n' "(symbol_instances)\n)\n",
        encoding="utf-8",
    )
    return root


def _create_symbol(lib: Path) -> Path:
    """create_symbol with the smallest legal symbol; creates the library."""
    SymbolCreator().create_symbol(
        str(lib),
        "R_10K_0603",
        reference_prefix="R",
        pins=[
            {"name": "1", "number": "1", "type": "passive", "at": {"x": -5.08, "y": 0, "angle": 0}},
            {
                "name": "2",
                "number": "2",
                "type": "passive",
                "at": {"x": 5.08, "y": 0, "angle": 180},
            },
        ],
        rectangles=[{"x1": -2.54, "y1": 1.27, "x2": 2.54, "y2": -1.27}],
    )
    return lib


# ── symbol_lib_header ────────────────────────────────────────────────


def test_header_kicad10_project(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "proj", V10)
    assert symbol_lib_header(str(project)) == ("20251024", "10.0")


def test_header_kicad9_project(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "proj", V9)
    assert symbol_lib_header(str(project)) == ("20241209", "9.0")


def test_header_no_project(tmp_path: Path) -> None:
    # A global library, nowhere near a .kicad_pro: the safe fallback.
    assert symbol_lib_header(str(tmp_path)) == ("20241209", "9.0")
    assert symbol_lib_header(None) == ("20241209", "9.0")


def test_header_library_in_project_subdir(tmp_path: Path) -> None:
    # The walk goes up from the library's directory to the .kicad_pro.
    project = _make_project(tmp_path / "proj", V10)
    libs = project / "symbols"
    libs.mkdir()
    assert symbol_lib_header(str(libs)) == ("20251024", "10.0")


# ── create_symbol ────────────────────────────────────────────────────


def test_create_symbol_new_lib_kicad10_project(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "proj", V10)
    lib = _create_symbol(project / "symbols" / "proj.kicad_sym")
    text = lib.read_text(encoding="utf-8")
    assert "(version 20251024)" in text
    assert '(generator_version "10.0")' in text


def test_create_symbol_new_lib_kicad9_project(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "proj", V9)
    lib = _create_symbol(project / "symbols" / "proj.kicad_sym")
    text = lib.read_text(encoding="utf-8")
    assert "(version 20241209)" in text
    assert '(generator_version "9.0")' in text


def test_create_symbol_new_lib_no_project(tmp_path: Path) -> None:
    lib = _create_symbol(tmp_path / "global" / "my.kicad_sym")
    text = lib.read_text(encoding="utf-8")
    assert "(version 20241209)" in text
    assert '(generator_version "9.0")' in text


def test_create_symbol_existing_lib_keeps_header(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "proj", V10)
    lib = project / "symbols" / "proj.kicad_sym"
    lib.parent.mkdir(parents=True, exist_ok=True)
    lib.write_text(SYMBOL_V9, encoding="utf-8")
    _create_symbol(lib)  # adds a symbol; must not rewrite the header
    text = lib.read_text(encoding="utf-8")
    assert "(version 20241209)" in text
    assert "(version 20251024)" not in text


# ── export_symbol ─────────────────────────────────────────────────────


def _source_lib(tmp_path: Path) -> Path:
    lib = tmp_path / "src.kicad_sym"
    lib.write_text(SYMBOL_V9, encoding="utf-8")
    return lib


def test_export_symbol_kicad10_project(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "proj", V10)
    lib = _source_lib(tmp_path)
    out = project / "symbols" / "exported.kicad_sym"
    result = LibraryManagementCommands().export_symbol(
        {"libraryPath": str(lib), "symbolName": "R_10K_0603", "outputPath": str(out)}
    )
    assert result["success"] is True
    text = out.read_text(encoding="utf-8")
    assert "(version 20251024)" in text
    assert '(generator_version "10.0")' in text


def test_export_symbol_no_project(tmp_path: Path) -> None:
    lib = _source_lib(tmp_path)
    out = tmp_path / "exported.kicad_sym"
    result = LibraryManagementCommands().export_symbol(
        {"libraryPath": str(lib), "symbolName": "R_10K_0603", "outputPath": str(out)}
    )
    assert result["success"] is True
    text = out.read_text(encoding="utf-8")
    assert "(version 20241209)" in text
    assert '(generator_version "9.0")' in text


# ── Eagle importer ────────────────────────────────────────────────────


def _eagle_sym_geoms() -> list:
    from commands.eagle import _EagleSymGeom

    return [_EagleSymGeom(name="TESTSYM", kicad_id="eagle_import:TESTSYM", lib_name="eagle_import")]


def test_generate_sym_lib_kicad10_project(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "proj", V10)
    out = project / "proj_eagle.kicad_sym"
    generate_sym_lib(_eagle_sym_geoms(), str(out))
    text = out.read_text(encoding="utf-8")
    assert "(version 20251024)" in text
    assert '(generator_version "10.0")' in text


def test_generate_sym_lib_no_project(tmp_path: Path) -> None:
    out = tmp_path / "eagle_import.kicad_sym"
    generate_sym_lib(_eagle_sym_geoms(), str(out))
    text = out.read_text(encoding="utf-8")
    assert "(version 20241209)" in text
    assert '(generator_version "9.0")' in text
