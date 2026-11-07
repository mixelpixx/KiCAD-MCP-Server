"""Project-scope library registration writes ${KIPRJMOD}-relative URIs.

``register_symbol_library`` and ``register_footprint_library`` with
``scope="project"`` wrote the library's absolute path into the project's
``sym-lib-table`` / ``fp-lib-table``. The project then breaks as soon as it is
moved, cloned on another machine, or opened from Windows after being made under
WSL: every library in the table points at the old location. KiCad's own library
manager writes ``${KIPRJMOD}/...`` for a library inside the project.
"""

import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.footprint import FootprintCreator  # noqa: E402
from commands.library import LibraryManager  # noqa: E402
from commands.library_tables import project_library_uri  # noqa: E402
from commands.symbol_creator import SymbolCreator  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("KICAD_SKIP_SYMBOL_WARMUP", "1")
    proj = tmp_path / "board"
    (proj / "lib" / "Mine.pretty").mkdir(parents=True)
    (proj / "lib" / "Mine.kicad_sym").write_text("(kicad_symbol_lib)\n", encoding="utf-8")
    (proj / "board.kicad_pro").write_text("{}\n", encoding="utf-8")
    return proj


def test_symbol_library_inside_the_project_is_kiprjmod_relative(project):
    r = SymbolCreator().register_symbol_library(
        library_path=str(project / "lib" / "Mine.kicad_sym"),
        scope="project",
        project_path=str(project / "board.kicad_pro"),
    )
    assert r["success"] and not r["already_registered"]
    assert r["uri"] == "${KIPRJMOD}/lib/Mine.kicad_sym"
    assert '(uri "${KIPRJMOD}/lib/Mine.kicad_sym")' in (project / "sym-lib-table").read_text()


def test_footprint_library_inside_the_project_is_kiprjmod_relative(project):
    r = FootprintCreator().register_footprint_library(
        library_path=str(project / "lib" / "Mine.pretty"),
        scope="project",
        project_path=str(project / "board.kicad_pro"),
    )
    assert r["success"] and not r["already_registered"]
    assert '(uri "${KIPRJMOD}/lib/Mine.pretty")' in (project / "fp-lib-table").read_text()


def test_registered_footprint_library_still_resolves_after_the_project_moves(project, tmp_path):
    FootprintCreator().register_footprint_library(
        library_path=str(project / "lib" / "Mine.pretty"),
        scope="project",
        project_path=str(project / "board.kicad_pro"),
    )
    moved = tmp_path / "elsewhere" / "board"
    shutil.move(str(project), str(moved))
    libs = LibraryManager(project_path=moved).libraries
    assert "Mine" in libs
    assert Path(libs["Mine"]) == moved / "lib" / "Mine.pretty"


def test_library_outside_the_project_keeps_its_absolute_path(project, tmp_path):
    outside = tmp_path / "shared" / "Other.pretty"
    outside.mkdir(parents=True)
    FootprintCreator().register_footprint_library(
        library_path=str(outside),
        scope="project",
        project_path=str(project / "board.kicad_pro"),
    )
    assert str(outside).replace("\\", "/") in (project / "fp-lib-table").read_text()


def test_an_existing_absolute_entry_counts_as_already_registered(project):
    """A table written before this change holds the absolute URI under another
    nickname; registering again must not add a duplicate row."""
    lib = project / "lib" / "Mine.pretty"
    (project / "fp-lib-table").write_text(
        "(fp_lib_table\n  (version 7)\n"
        f'  (lib (name "OldNick")(type "KiCad")(uri "{str(lib).replace(os.sep, "/")}")'
        '(options "")(descr ""))\n)\n',
        encoding="utf-8",
    )
    r = FootprintCreator().register_footprint_library(
        library_path=str(lib), scope="project", project_path=str(project / "board.kicad_pro")
    )
    assert r["already_registered"]


def test_project_library_uri_helper(tmp_path):
    assert project_library_uri(tmp_path / "a" / "x.pretty", tmp_path) == "${KIPRJMOD}/a/x.pretty"
    assert project_library_uri(tmp_path / "x.pretty", tmp_path / "proj") == str(
        tmp_path / "x.pretty"
    ).replace("\\", "/")
