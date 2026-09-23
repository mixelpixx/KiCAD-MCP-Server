"""KiCad 10 and relocated installs in the Windows fallbacks (#416).

``launch_kicad_ui`` (``KiCADProcessManager.get_executable_path``) and
``list_footprint_libraries`` kept their own fixed ``Program Files\\KiCad\\9.0``
lists, so with KiCad 9 and 10 side by side they picked the KiCad 9 GUI and
libraries, and an install under a custom root such as ``C:\\KiCad\\10.0`` was not
found at all. Both now consult ``utils.kicad_roots.kicad_install_roots`` (the
shared discovery from #286) before the fixed locations, and the library listing
lets the newest install win a library-name clash.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import utils.kicad_process as kicad_process  # noqa: E402
import utils.kicad_roots as kicad_roots  # noqa: E402
from commands.footprint import FootprintCreator  # noqa: E402

pytestmark = pytest.mark.unit


def _root(tmp_path: Path, version: str) -> Path:
    root = tmp_path / "KiCad" / version
    (root / "bin").mkdir(parents=True)
    return root


def test_launcher_finds_pcbnew_under_a_discovered_root(tmp_path, monkeypatch):
    new, old = _root(tmp_path, "10.0"), _root(tmp_path, "9.0")
    for root in (new, old):
        (root / "bin" / "pcbnew.exe").write_text("")
    monkeypatch.setattr(kicad_process.platform, "system", lambda: "Windows")
    # nothing on PATH: `where pcbnew` / `where kicad` both fail
    monkeypatch.setattr(
        kicad_process.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="")
    )
    monkeypatch.setattr(kicad_roots, "kicad_install_roots", lambda: [new, old])

    assert kicad_process.KiCADProcessManager.get_executable_path() == new / "bin" / "pcbnew.exe"


def _library(root: Path, lib: str, footprint: str) -> None:
    pretty = root / "share" / "kicad" / "footprints" / f"{lib}.pretty"
    pretty.mkdir(parents=True)
    (pretty / f"{footprint}.kicad_mod").write_text("(footprint)")


def test_footprint_listing_prefers_the_newest_install(tmp_path, monkeypatch):
    new, old = _root(tmp_path, "10.0"), _root(tmp_path, "9.0")
    _library(new, "Zz_Issue416_Lib", "From_KiCad10")
    _library(old, "Zz_Issue416_Lib", "From_KiCad9")
    monkeypatch.setattr(kicad_roots, "kicad_install_roots", lambda: [new, old])

    result = FootprintCreator().list_footprint_libraries()

    lib = result["libraries"]["Zz_Issue416_Lib"]
    assert lib["footprints"] == ["From_KiCad10"]
    assert Path(lib["path"]).parent.parent.parent.parent == new
