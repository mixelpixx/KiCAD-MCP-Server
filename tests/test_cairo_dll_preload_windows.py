"""``ensure_cairo_on_path``, the Windows ``cairo-2.dll`` PATH preload.

cairocffi loads the DLL with ``ffi.dlopen("cairo-2")``, which searches PATH.
``kicad_interface`` calls ``utils.kicad_roots.ensure_cairo_on_path`` at the top
of the module on Windows, before anything can import cairocffi. The candidates
are the directories the caller passes, then the ``bin`` directory of every KiCad
install root, newest first. They used to be a fixed list that ended at
``Program Files\\KiCad\\9.0`` and ``8.0``, so a KiCad 10 install, or any install
under a custom root, was never found (#425).

These tests call the real function; they used to re-run a copy of the old
block, so they could not notice it changing.
"""

import ast
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import utils.kicad_roots as kicad_roots  # noqa: E402
from utils.kicad_roots import ensure_cairo_on_path  # noqa: E402

pytestmark = pytest.mark.unit

SYSTEM32 = os.path.join("C:" + os.sep, "Windows", "System32")


def _with_dll(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "cairo-2.dll").write_bytes(b"")
    return directory


@pytest.fixture
def kicad10(tmp_path, monkeypatch):
    """The only KiCad on the machine: 10.0 under a custom root such as C:\\KiCad."""
    root = tmp_path / "KiCad" / "10.0"
    _with_dll(root / "bin")
    monkeypatch.setattr(kicad_roots, "kicad_install_roots", lambda: [root])
    return root


def test_a_kicad_10_install_is_found(kicad10, monkeypatch):
    monkeypatch.setenv("PATH", SYSTEM32)
    bin_dir = str(kicad10 / "bin")
    assert ensure_cairo_on_path() == bin_dir
    assert os.environ["PATH"] == bin_dir + os.pathsep + SYSTEM32


def test_the_newest_install_wins(tmp_path, monkeypatch):
    new = tmp_path / "KiCad" / "10.0"
    old = tmp_path / "KiCad" / "9.0"
    for root in (new, old):
        _with_dll(root / "bin")
    monkeypatch.setattr(kicad_roots, "kicad_install_roots", lambda: [new, old])
    monkeypatch.setenv("PATH", SYSTEM32)
    assert ensure_cairo_on_path() == str(new / "bin")


def test_the_callers_directories_come_first(kicad10, tmp_path, monkeypatch):
    # kicad_interface passes the Python executable's directory: KiCad's own
    # Python lives in the bin directory that holds the DLL.
    python_dir = _with_dll(tmp_path / "python")
    monkeypatch.setenv("PATH", SYSTEM32)
    assert ensure_cairo_on_path(["", str(python_dir)]) == str(python_dir)


def test_install_roots_are_not_discovered_when_a_caller_directory_has_the_dll(
    tmp_path, monkeypatch
):
    # Discovery walks the registry; skip it when the DLL is already found.
    def discover():
        raise AssertionError("install roots should not be discovered")

    monkeypatch.setattr(kicad_roots, "kicad_install_roots", discover)
    monkeypatch.setenv("PATH", SYSTEM32)
    python_dir = _with_dll(tmp_path / "python")
    assert ensure_cairo_on_path([str(python_dir)]) == str(python_dir)


def test_a_directory_already_on_path_is_not_added_again(kicad10, monkeypatch):
    # Written with a trailing separator, it is still the same directory.
    bin_dir = str(kicad10 / "bin")
    starting = bin_dir + os.sep + os.pathsep + SYSTEM32
    monkeypatch.setenv("PATH", starting)
    assert ensure_cairo_on_path() == bin_dir
    assert os.environ["PATH"] == starting


def test_path_is_untouched_when_no_candidate_has_the_dll(tmp_path, monkeypatch):
    empty_root = tmp_path / "KiCad" / "10.0"
    (empty_root / "bin").mkdir(parents=True)
    monkeypatch.setattr(kicad_roots, "kicad_install_roots", lambda: [empty_root])
    monkeypatch.setenv("PATH", SYSTEM32)
    assert ensure_cairo_on_path(["", str(tmp_path)]) is None
    assert os.environ["PATH"] == SYSTEM32


@pytest.mark.skipif(sys.version_info < (3, 10), reason="sys.stdlib_module_names is Python 3.10+")
def test_the_worker_calls_it_before_its_first_third_party_import():
    """kicad_interface must extend PATH before anything that can import
    cairocffi, i.e. before its first import outside the standard library."""
    source = Path(__file__).resolve().parent.parent / "python" / "kicad_interface.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))

    def calls_preload(node: ast.AST) -> bool:
        return any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "ensure_cairo_on_path"
            for n in ast.walk(node)
        )

    def first_party_or_third_party(node: ast.AST) -> bool:
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            return False
        return any(name.split(".")[0] not in sys.stdlib_module_names for name in names)

    body = tree.body
    preload = next(i for i, node in enumerate(body) if calls_preload(node))
    first_import = next(i for i, node in enumerate(body) if first_party_or_third_party(node))
    assert preload < first_import
