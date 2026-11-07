"""Regression (#479): rendering with pymupdf must not break pcbnew iteration.

When pcbnew and pymupdf share a SWIG runtime version, they share one type
table, and the last module to load registers its ``SwigPyIterator`` class
there. pymupdf's class has no ``next()``, which pcbnew's container wrappers
call, so after pymupdf loaded second, iterating BOARD.GetDrawings(),
BOARD.GetTracks() and similar containers raised "'SwigPyIterator' object has
no attribute 'next'" for the rest of the process. See utils/swig_compat.py.

Import order is process-wide state, so each real-KiCad case runs in a fresh
interpreter. The fix cases skip when the baseline does not reproduce the
conflict (for example pcbnew on swig_runtime_data4 and pymupdf on
swig_runtime_data5), so a pass always means the fix was exercised.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).resolve().parent.parent / "python"

_EXPECTED = {"drawings": 1, "tracks": 0}

# {before} runs before pcbnew is imported. {render} runs after pcbnew is
# loaded and must load pymupdf and render with it. The probe then walks the
# containers that used to break.
_PROBE = textwrap.dedent("""
    import json, sys
    {before}
    import pcbnew
    {render}

    board = pcbnew.BOARD()
    shape = pcbnew.PCB_SHAPE(board)
    shape.SetShape(pcbnew.SHAPE_T_SEGMENT)
    shape.SetLayer(pcbnew.Edge_Cuts)
    shape.SetStart(pcbnew.VECTOR2I(0, 0))
    shape.SetEnd(pcbnew.VECTOR2I(10_000_000, 0))
    board.Add(shape)

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

_RENDER_DIRECT = (
    "import pymupdf\n" 'pymupdf.open().new_page(width=10, height=10).get_pixmap().tobytes("png")\n'
)


def _run(before: str = "", render: str = _RENDER_DIRECT) -> dict:
    env = dict(os.environ, KICAD_SKIP_SYMBOL_WARMUP="1")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(PYTHON_DIR), env.get("PYTHONPATH")]))
    proc = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", _PROBE.format(before=before, render=render)],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
        stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def conflict_baseline() -> dict:
    """Result of the order that broke: pcbnew first, pymupdf second, no fix."""
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
        pytest.skip("requires KICAD_USE_REAL_PCBNEW=1")
    pytest.importorskip("pymupdf")
    return _run()


@pytest.fixture
def conflict_reproduces(conflict_baseline: dict) -> None:
    if conflict_baseline == _EXPECTED:
        pytest.skip("pcbnew and pymupdf do not share a SWIG runtime here; nothing to guard")


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_baseline_is_either_clean_or_the_known_conflict(conflict_baseline: dict) -> None:
    """Any other result would be a different problem from #479."""
    if conflict_baseline != _EXPECTED:
        assert "has no attribute 'next'" in str(conflict_baseline["drawings"]), conflict_baseline


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_server_startup_import_order_fixes_iteration(conflict_reproduces) -> None:
    """kicad_interface imports pymupdf first, so pcbnew registers last."""
    assert _run(before="import kicad_interface") == _EXPECTED


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_reregistering_after_pymupdf_fixes_any_import_order(conflict_reproduces) -> None:
    """pcbnew first, pymupdf second, then the helper restores pcbnew's class."""
    render = _RENDER_DIRECT + (
        "from utils.swig_compat import restore_pcbnew_iterator\n"
        "assert restore_pcbnew_iterator()\n"
    )
    assert _run(render=render) == _EXPECTED


@pytest.mark.integration
@pytest.mark.real_pcbnew
@pytest.mark.parametrize("module", ["commands.board.view", "commands.schematic_handlers"])
def test_view_rasterizers_leave_iteration_working(conflict_reproduces, tmp_path, module) -> None:
    """The real call sites: pcbnew is loaded first, then _svg_to_png loads fitz."""
    svg = tmp_path / "view.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        '<rect width="10" height="10"/></svg>'
    )
    render = (
        f"from {module} import _svg_to_png\n"
        f"assert _svg_to_png({str(svg)!r}, 10, 10), 'no PNG produced'\n"
        "assert 'pymupdf' in sys.modules, 'rendered without pymupdf'\n"
    )
    assert _run(render=render) == _EXPECTED


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


def test_restore_does_nothing_without_pcbnew(monkeypatch) -> None:
    from utils import swig_compat

    monkeypatch.delitem(sys.modules, "pcbnew", raising=False)
    assert swig_compat.restore_pcbnew_iterator() is False
    assert "pcbnew" not in sys.modules


def test_restore_tolerates_a_build_without_swigregister(monkeypatch) -> None:
    import types

    from utils import swig_compat

    fake = types.ModuleType("pcbnew")
    fake._pcbnew = types.SimpleNamespace()  # type: ignore[attr-defined]
    fake.SwigPyIterator = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pcbnew", fake)
    assert swig_compat.restore_pcbnew_iterator() is False
