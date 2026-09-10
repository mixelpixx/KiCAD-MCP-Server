"""Regression tests for #389: kicad-skip missing must not take down the server.

Six modules imported ``from skip import Schematic`` at their own top level.
Two of them (``library_schematic.py``, ``schematic.py``) sit on the import
chain ``kicad_interface`` -> ``schematic_handlers`` -> ``library_schematic``/
``schematic``, which runs before kicad_interface.py's own try/except block
even starts, so a missing kicad-skip raised an unhandled ModuleNotFoundError
at process startup instead of the intended structured JSON error.

These run kicad-skip absence in a genuinely separate subprocess
(``sys.modules["skip"] = None`` forces every import of it to fail) rather
than relying on conftest's session-wide stub, which would otherwise make
``from skip import Schematic`` succeed against the fake module and never
exercise the guard this issue is about.
"""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PYTHON_DIR = Path(__file__).resolve().parent.parent / "python"

_PREAMBLE = f"""
import sys
from unittest.mock import MagicMock

sys.path.insert(0, {str(PYTHON_DIR)!r})

# Force every import of kicad-skip to fail, regardless of whether it is
# actually installed in this interpreter.
sys.modules["skip"] = None

pcbnew = MagicMock(name="pcbnew")
pcbnew.__file__ = "/fake/pcbnew.py"
pcbnew.__spec__ = None
pcbnew.GetBuildVersion.return_value = "9.0.0-stub"
sys.modules["pcbnew"] = pcbnew
"""


def _run(body: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _PREAMBLE + body],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_kicad_interface_imports_without_kicad_skip():
    result = _run("import kicad_interface\nprint('OK')")
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_schematic_manager_raises_actionable_error_without_kicad_skip():
    result = _run(
        "from commands.schematic import SchematicManager, SchematicLoadError\n"
        "try:\n"
        "    SchematicManager.load_schematic('/nonexistent-but-checked-second.kicad_sch')\n"
        "except SchematicLoadError as e:\n"
        "    assert e.kind == 'not_found', e.kind\n"
        "try:\n"
        "    SchematicManager.create_schematic('t', path='/tmp/does-not-matter.kicad_sch')\n"
        "except SchematicLoadError as e:\n"
        "    assert e.kind == 'dependency_missing', e.kind\n"
        "    assert 'pip install kicad-skip' in str(e), str(e)\n"
        "    print('OK')\n"
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_component_and_connection_schematic_import_without_kicad_skip():
    result = _run(
        "import commands.component_schematic\n"
        "import commands.connection_schematic\n"
        "print('OK')"
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_unrelated_tool_still_works_without_kicad_skip():
    result = _run(
        "import kicad_interface\n"
        "from commands.board.layers import BoardLayerCommands\n"
        "import sys\n"
        "BoardLayerCommands(board=sys.modules['pcbnew'].GetBoard())\n"
        "print('OK')"
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
