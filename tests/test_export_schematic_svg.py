"""
Tests for deterministic SVG page selection in export_schematic_svg and
the schematic view tools.

Regression coverage for the "export sheet X renders sheet Y" defect:
export_schematic_svg used to export directly into the user's output
directory and then glob-pick the first *.svg found there, so stale SVGs
from earlier exports of other sheets (or extra hierarchical pages) were
returned as the requested export. The handlers now export into a private
temp directory and select the root page by schematic filename stem.
"""

import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.schematic_handlers import _pick_root_svg  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_iface() -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)
    return iface


@pytest.fixture()
def iface():
    return _make_iface()


class FakeKicadCli:
    """subprocess.run side_effect emulating `kicad-cli sch export svg`.

    Writes `<schematic-stem>.svg` (content = per-sheet marker) into the
    output directory parsed from the command, plus any configured extra
    pages (hierarchical sub-sheets).
    """

    def __init__(self, extra_pages=None, page_names=None):
        # extra_pages: list of suffixes appended as "<stem>-<suffix>.svg"
        self.extra_pages = extra_pages or []
        # page_names: if set, write exactly these file names instead of
        # the stem-derived ones (used for the failure-path test)
        self.page_names = page_names

    def __call__(self, cmd, **kwargs):
        # Parse output dir (after -o or --output) and the schematic path
        out_dir = None
        sch_path = None
        for i, tok in enumerate(cmd):
            if tok in ("-o", "--output"):
                out_dir = cmd[i + 1]
            elif tok.endswith(".kicad_sch"):
                sch_path = tok
        assert out_dir is not None and sch_path is not None, cmd
        stem = Path(sch_path).stem
        marker = f"MARKER:{stem}"
        if self.page_names is not None:
            for name in self.page_names:
                Path(out_dir, name).write_text(f"{marker}:{name}")
        else:
            Path(out_dir, f"{stem}.svg").write_text(marker)
            for suffix in self.extra_pages:
                Path(out_dir, f"{stem}-{suffix}.svg").write_text(
                    f"{marker}:{suffix}"
                )

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()


def _make_sch(tmp_path, name):
    p = tmp_path / name
    p.write_text("(kicad_sch)")
    return str(p)


def _export(iface, sch, out, fake_cli):
    with patch(
        "commands.schematic_handlers.resolve_kicad_cli",
        return_value="/fake/kicad-cli",
    ), patch("subprocess.run", side_effect=fake_cli):
        return iface._handle_export_schematic_svg(
            {"schematicPath": sch, "outputPath": out}
        )


# ---------------------------------------------------------------------------
# _pick_root_svg unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPickRootSvg:
    def test_stem_match(self, tmp_path):
        (tmp_path / "root.svg").write_text("root")
        (tmp_path / "root-Sub1.svg").write_text("sub")
        picked = _pick_root_svg(str(tmp_path), "/x/y/root.kicad_sch")
        assert picked == str(tmp_path / "root.svg")

    def test_single_file_fallback(self, tmp_path):
        (tmp_path / "renamed.svg").write_text("only")
        picked = _pick_root_svg(str(tmp_path), "/x/y/other.kicad_sch")
        assert picked == str(tmp_path / "renamed.svg")

    def test_ambiguous_returns_none(self, tmp_path):
        (tmp_path / "a.svg").write_text("a")
        (tmp_path / "b.svg").write_text("b")
        assert _pick_root_svg(str(tmp_path), "/x/y/c.kicad_sch") is None


# ---------------------------------------------------------------------------
# export_schematic_svg
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExportSchematicSvg:
    def test_export_a_then_b_same_directory(self, iface, tmp_path):
        """The headline regression: exporting B after A into the same
        directory must return B's content, with decoy stale SVGs sorting
        both before and after the expected name."""
        sch_a = _make_sch(tmp_path, "sheet_a.kicad_sch")
        sch_b = _make_sch(tmp_path, "sheet_b.kicad_sch")
        out = tmp_path / "out"
        out.mkdir()
        # Decoys around any plausible pick order
        (out / "aaa_stale.svg").write_text("STALE-FIRST")
        (out / "zzz_stale.svg").write_text("STALE-LAST")

        r1 = _export(iface, sch_a, str(out / "a.svg"), FakeKicadCli())
        assert r1["success"], r1
        r2 = _export(iface, sch_b, str(out / "b.svg"), FakeKicadCli())
        assert r2["success"], r2

        assert (out / "b.svg").read_text() == "MARKER:sheet_b"
        assert (out / "a.svg").read_text() == "MARKER:sheet_a"

    def test_same_output_path_reuse(self, iface, tmp_path):
        sch_a = _make_sch(tmp_path, "sheet_a.kicad_sch")
        sch_b = _make_sch(tmp_path, "sheet_b.kicad_sch")
        out = tmp_path / "out"
        out.mkdir()
        view = str(out / "view.svg")

        assert _export(iface, sch_a, view, FakeKicadCli())["success"]
        assert _export(iface, sch_b, view, FakeKicadCli())["success"]

        assert Path(view).read_text() == "MARKER:sheet_b"
        # No orphan SVGs beyond the requested output
        assert sorted(os.listdir(out)) == ["view.svg"]

    def test_multipage_selects_root(self, iface, tmp_path):
        sch = _make_sch(tmp_path, "root.kicad_sch")
        out = tmp_path / "out"
        out.mkdir()
        r = _export(
            iface, sch, str(out / "root_view.svg"), FakeKicadCli(["Sub1"])
        )
        assert r["success"], r
        assert (out / "root_view.svg").read_text() == "MARKER:root"
        # Sub-sheet page is not leaked into the user directory
        assert sorted(os.listdir(out)) == ["root_view.svg"]
        # Pages are reported for transparency
        assert r.get("pages") == ["root-Sub1.svg", "root.svg"]

    def test_unidentifiable_root_fails_with_listing(self, iface, tmp_path):
        sch = _make_sch(tmp_path, "root.kicad_sch")
        out = tmp_path / "out"
        out.mkdir()
        fake = FakeKicadCli(page_names=["odd1.svg", "odd2.svg"])
        r = _export(iface, sch, str(out / "root.svg"), fake)
        assert r["success"] is False
        assert "root SVG" in r["message"]
        assert r["files"] == ["odd1.svg", "odd2.svg"]
        assert not (out / "root.svg").exists()

    def test_missing_params(self, iface):
        r = iface._handle_export_schematic_svg({"schematicPath": "x"})
        assert r["success"] is False
        assert "required" in r["message"]
        r = iface._handle_export_schematic_svg({"outputPath": "x"})
        assert r["success"] is False

    def test_missing_schematic(self, iface, tmp_path):
        r = iface._handle_export_schematic_svg(
            {
                "schematicPath": str(tmp_path / "nope.kicad_sch"),
                "outputPath": str(tmp_path / "o.svg"),
            }
        )
        assert r["success"] is False
        assert "not found" in r["message"]


# ---------------------------------------------------------------------------
# get_schematic_view
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSchematicView:
    def test_multipage_returns_root_content(self, iface, tmp_path):
        sch = _make_sch(tmp_path, "root.kicad_sch")
        with patch(
            "commands.schematic_handlers.resolve_kicad_cli",
            return_value="/fake/kicad-cli",
        ), patch("subprocess.run", side_effect=FakeKicadCli(["Sub1"])):
            r = iface._handle_get_schematic_view(
                {"schematicPath": sch, "format": "svg"}
            )
        assert r["success"], r
        assert r["format"] == "svg"
        assert r["imageData"] == "MARKER:root"
