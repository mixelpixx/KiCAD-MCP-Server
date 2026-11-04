"""Regression: rendering with pymupdf must not break pcbnew container iteration.

pcbnew and pymupdf share SWIG's runtime type table. If pymupdf is imported after
pcbnew, iterating BOARD.GetDrawings(), BOARD.GetTracks() and similar containers
raises "'SwigPyIterator' object has no attribute 'next'" for the rest of the
process, so list_graphics and every other tool that walks those containers
failed after the first get_board_2d_view. See utils/swig_compat.py.

Import order is process-wide state, so each case runs in a fresh interpreter.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).resolve().parent.parent / "python"

pytestmark = [pytest.mark.integration, pytest.mark.real_pcbnew]

# Build a board with one drawing, render a tiny PDF page with pymupdf the way
# the view tools do, then walk the containers that used to break.
_PROBE = textwrap.dedent("""
    import json, sys
    {setup}
    import pcbnew
    import pymupdf

    board = pcbnew.BOARD()
    shape = pcbnew.PCB_SHAPE(board)
    shape.SetShape(pcbnew.SHAPE_T_SEGMENT)
    shape.SetLayer(pcbnew.Edge_Cuts)
    shape.SetStart(pcbnew.VECTOR2I(0, 0))
    shape.SetEnd(pcbnew.VECTOR2I(10_000_000, 0))
    board.Add(shape)

    doc = pymupdf.open()
    doc.new_page(width=10, height=10).get_pixmap().tobytes("png")

    result = {{}}
    for name, fn in (
        ("drawings", lambda: len(board.GetDrawings())),
        ("tracks", lambda: len(board.GetTracks())),
    ):
        try:
            result[name] = fn()
        except Exception as e:
            result[name] = f"{{type(e).__name__}}: {{e}}"
    print(json.dumps(result))
    """)


def _require_real_stack() -> None:
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
        pytest.skip("requires KICAD_USE_REAL_PCBNEW=1")
    pytest.importorskip("pymupdf")


def _run(setup: str) -> dict:
    env = dict(os.environ, KICAD_SKIP_SYMBOL_WARMUP="1")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(PYTHON_DIR), env.get("PYTHONPATH")]))
    proc = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", _PROBE.format(setup=setup)],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
        stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_kicad_interface_import_keeps_board_iteration_working() -> None:
    """The server's startup path must leave pcbnew iteration working after a render."""
    _require_real_stack()
    assert _run("import kicad_interface") == {"drawings": 1, "tracks": 0}


def test_preload_helper_keeps_board_iteration_working() -> None:
    _require_real_stack()
    assert _run("from utils.swig_compat import preload_pymupdf; preload_pymupdf()") == {
        "drawings": 1,
        "tracks": 0,
    }


def test_import_order_still_matters() -> None:
    """Documents the underlying conflict; skipped if a pymupdf release fixes it."""
    _require_real_stack()
    result = _run("")  # pcbnew first, pymupdf second: the order that broke
    if result == {"drawings": 1, "tracks": 0}:
        pytest.skip("this pymupdf build does not trigger the SWIG iterator conflict")
    assert "has no attribute 'next'" in str(result["drawings"])


def test_preload_tolerates_missing_pymupdf(monkeypatch) -> None:
    """Without pymupdf the helper reports False and does not raise."""
    import builtins

    from utils import swig_compat

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pymupdf":
            raise ImportError("No module named 'pymupdf'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "pymupdf", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert swig_compat.preload_pymupdf() is False
