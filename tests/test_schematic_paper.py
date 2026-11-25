"""Schematic paper size: set_schematic_paper and the paper option on create_*."""

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.modules.setdefault("pcbnew", MagicMock())

from commands.schematic_paper import (  # noqa: E402
    PAPER_DIMENSIONS_MM,
    PAPER_SIZES,
    normalize_paper,
    set_paper,
)
from kicad_interface import KiCADInterface  # noqa: E402

ROOT_UUID = "11111111-2222-3333-4444-555555555555"
A4_SHEET = f"""(kicad_sch
\t(version 20260101)
\t(generator "eeschema")
\t(generator_version "10.0")
\t(uuid "{ROOT_UUID}")
\t(paper "A4")
\t(lib_symbols)
\t(sheet_instances
\t\t(path "/"
\t\t\t(page "1")
\t\t)
\t)
)
"""


def _load(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        module_name,
        os.path.join(os.path.dirname(__file__), "..", "python", "commands", filename),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def sheet(tmp_path: Path) -> Path:
    path = tmp_path / "board.kicad_sch"
    path.write_text(A4_SHEET, encoding="utf-8")
    return path


def test_paper_sizes_are_kicads() -> None:
    assert PAPER_SIZES == (
        "A5", "A4", "A3", "A2", "A1", "A0", "A", "B", "C", "D", "E",
        "USLetter", "USLegal", "USLedger",
    )  # fmt: skip


def test_every_paper_size_has_dimensions() -> None:
    assert set(PAPER_DIMENSIONS_MM) == set(PAPER_SIZES)
    for width, height in PAPER_DIMENSIONS_MM.values():
        assert width > height  # landscape


def test_us_paper_dimensions_are_kicads() -> None:
    assert PAPER_DIMENSIONS_MM["USLetter"] == (279.4, 215.9)
    assert PAPER_DIMENSIONS_MM["USLegal"] == (355.6, 215.9)
    assert PAPER_DIMENSIONS_MM["USLedger"] == (431.8, 279.4)

def test_normalize_paper_is_case_insensitive() -> None:
    assert normalize_paper("a3") == "A3"
    assert normalize_paper("usletter") == "USLetter"
    assert normalize_paper(" A4 ") == "A4"
    assert normalize_paper("A6") is None
    assert normalize_paper("Letter") is None


def test_set_paper_replaces_existing(sheet: Path) -> None:
    set_paper(sheet, "A3")
    text = sheet.read_text(encoding="utf-8")
    assert '(paper "A3")' in text
    assert text.count("(paper") == 1


def test_set_paper_portrait_toggles(sheet: Path) -> None:
    set_paper(sheet, "A4", portrait=True)
    assert '(paper "A4" portrait)' in sheet.read_text(encoding="utf-8")
    set_paper(sheet, "A4", portrait=False)
    text = sheet.read_text(encoding="utf-8")
    assert '(paper "A4")' in text
    assert "portrait" not in text


def test_set_paper_inserts_when_missing(sheet: Path) -> None:
    sheet.write_text(A4_SHEET.replace('\t(paper "A4")\n', ""), encoding="utf-8")
    set_paper(sheet, "A3")
    text = sheet.read_text(encoding="utf-8")
    assert text.count("(paper") == 1
    assert text.index('(paper "A3")') > text.index(ROOT_UUID)
    assert text.index('(paper "A3")') < text.index("(lib_symbols")


def test_set_paper_rejects_unknown(sheet: Path) -> None:
    before = sheet.read_bytes()
    with pytest.raises(ValueError):
        set_paper(sheet, "A6")
    assert sheet.read_bytes() == before


def test_set_paper_ignores_paper_inside_sub_elements(sheet: Path) -> None:
    # Only the root-level token counts; text that merely says (paper ...) is left alone.
    sheet.write_text(
        A4_SHEET.replace("\t(lib_symbols)", '\t(lib_symbols)\n\t(text "see (paper \\"A0\\")")'),
        encoding="utf-8",
    )
    set_paper(sheet, "A3")
    text = sheet.read_text(encoding="utf-8")
    assert '\t(paper "A3")' in text
    assert 'see (paper \\"A0\\")' in text


def test_handler_sets_paper(sheet: Path) -> None:
    iface = KiCADInterface.__new__(KiCADInterface)
    result = iface._handle_set_schematic_paper({"schematicPath": str(sheet), "paper": "a3"})
    assert result["success"] is True, result
    assert result["paper"] == "A3"
    assert result["portrait"] is False
    assert '(paper "A3")' in sheet.read_text(encoding="utf-8")


def test_handler_reports_valid_names(sheet: Path) -> None:
    iface = KiCADInterface.__new__(KiCADInterface)
    result = iface._handle_set_schematic_paper({"schematicPath": str(sheet), "paper": "Letter"})
    assert result["success"] is False
    assert "USLetter" in result["message"]
    assert '(paper "A4")' in sheet.read_text(encoding="utf-8")


def test_handler_requires_existing_file(tmp_path: Path) -> None:
    iface = KiCADInterface.__new__(KiCADInterface)
    missing = tmp_path / "nope.kicad_sch"
    assert (
        iface._handle_set_schematic_paper({"schematicPath": str(missing), "paper": "A3"})["success"]
        is False
    )
    assert iface._handle_set_schematic_paper({"paper": "A3"})["success"] is False


def test_set_schematic_paper_is_guarded_while_open() -> None:
    assert "set_schematic_paper" in KiCADInterface._SCHEMATIC_MUTATING_COMMANDS


def test_create_schematic_paper_param(tmp_path: Path) -> None:
    mod = _load("schematic_module_paper", "schematic.py")
    with patch.object(mod, "Schematic", MagicMock()):
        mod.SchematicManager.create_schematic("big", path=str(tmp_path), paper="A3")
        mod.SchematicManager.create_schematic("plain", path=str(tmp_path))
    assert '(paper "A3")' in (tmp_path / "big.kicad_sch").read_text(encoding="utf-8")
    assert '(paper "A4")' in (tmp_path / "plain.kicad_sch").read_text(encoding="utf-8")


def test_create_schematic_rejects_unknown_paper_before_writing(tmp_path: Path) -> None:
    mod = _load("schematic_module_paper_bad", "schematic.py")
    with patch.object(mod, "Schematic", MagicMock()), pytest.raises(ValueError):
        mod.SchematicManager.create_schematic("bad", path=str(tmp_path), paper="A6")
    assert not (tmp_path / "bad.kicad_sch").exists()


def test_create_project_paper_param(tmp_path: Path) -> None:
    mod = _load("project_module_paper", "project.py")
    with patch.object(mod, "pcbnew", MagicMock()):
        result = mod.ProjectCommands().create_project(
            {"name": "big", "path": str(tmp_path), "paper": "A3", "portrait": True}
        )
    assert result["success"] is True, result
    assert '(paper "A3" portrait)' in (tmp_path / "big.kicad_sch").read_text(encoding="utf-8")


def test_create_project_rejects_unknown_paper_before_writing(tmp_path: Path) -> None:
    mod = _load("project_module_paper_bad", "project.py")
    with patch.object(mod, "pcbnew", MagicMock()):
        result = mod.ProjectCommands().create_project(
            {"name": "bad", "path": str(tmp_path), "paper": "A6"}
        )
    assert result["success"] is False
    assert "USLetter" in result["message"]
    assert list(tmp_path.iterdir()) == []


def test_create_schematic_handler_passes_paper(tmp_path: Path) -> None:
    from commands import schematic_handlers

    iface = KiCADInterface.__new__(KiCADInterface)
    with (
        patch.object(schematic_handlers.SchematicManager, "create_schematic") as create,
        patch.object(schematic_handlers.SchematicManager, "save_schematic", return_value=True),
    ):
        iface._handle_create_schematic(
            {"name": "big", "path": str(tmp_path), "paper": "A3", "portrait": True}
        )
    assert create.call_args.kwargs["paper"] == "A3"
    assert create.call_args.kwargs["portrait"] is True


def test_create_schematic_handler_reports_unknown_paper(tmp_path: Path) -> None:
    iface = KiCADInterface.__new__(KiCADInterface)
    result = iface._handle_create_schematic({"name": "bad", "path": str(tmp_path), "paper": "A6"})
    assert result["success"] is False
    assert "USLetter" in result["message"]


def test_set_paper_inserts_into_single_line_file(tmp_path: Path) -> None:
    # Files from other generators may put the whole sheet on one line.
    import sexpdata

    path = tmp_path / "flat.kicad_sch"
    path.write_text(
        f'(kicad_sch (version 20260101) (generator "x") (uuid "{ROOT_UUID}") (lib_symbols))',
        encoding="utf-8",
    )
    set_paper(path, "A3")
    text = path.read_text(encoding="utf-8")
    assert text.count("(kicad_sch") == 1
    assert text.count("(paper") == 1
    tree = sexpdata.loads(text)
    assert [sexpdata.Symbol("paper"), "A3"] in tree
