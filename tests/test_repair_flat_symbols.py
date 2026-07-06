"""
Tests for the repair_flat_symbols tool (python/commands/symbol_repair.py).

Flat SnapEDA/SamacSys captures put pins/graphics directly under the
top-level (symbol "NAME") with no _1_1 sub-unit; kicad-skip crashes on
them. The tool wraps the drawable children in a proper sub-unit via pure
balanced-paren text insertion (never a sexpdata round-trip).
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.symbol_repair import SymbolRepairCommands  # noqa: E402

FLAT_SYM = """\
(kicad_symbol_lib (version 20211014) (generator SamacSys_ECAD_Model)
  (symbol "NCV7356" (in_bom yes) (on_board yes)
    (property "Reference" "IC" (id 0) (at 27.94 7.62 0)
      (effects (font (size 1.27 1.27)) (justify left top))
    )
    (property "Value" "NCV7356" (id 1) (at 27.94 5.08 0)
      (effects (font (size 1.27 1.27)) (justify left top))
    )
    (pin passive line (at 0 0 0) (length 5.08)
      (name "TXD" (effects (font (size 1.27 1.27))))
      (number "1" (effects (font (size 1.27 1.27))))
    )
    (pin passive line (at 0 -2.54 0) (length 5.08)
      (name "GND" (effects (font (size 1.27 1.27))))
      (number "2" (effects (font (size 1.27 1.27))))
    )
    (rectangle (start 5.08 2.54) (end 22.86 -7.62)
      (stroke (width 0.254) (type default)) (fill (type background))
    )
  )
)
"""

WRAPPED_SYM = """\
(kicad_symbol_lib (version 20211014) (generator kicad_symbol_editor)
  (symbol "GOOD_PART" (in_bom yes) (on_board yes)
    (property "Reference" "U" (id 0) (at 0 0 0)
      (effects (font (size 1.27 1.27)))
    )
    (symbol "GOOD_PART_1_1"
      (pin passive line (at 0 0 0) (length 2.54)
        (name "P1" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27))))
      )
    )
  )
)
"""

MULTI_SYM = """\
(kicad_symbol_lib (version 20211014) (generator test)
  (symbol "FLAT_ONE" (in_bom yes) (on_board yes)
    (property "Reference" "U" (id 0) (at 0 0 0)
      (effects (font (size 1.27 1.27)))
    )
    (pin passive line (at 0 0 0) (length 2.54)
      (name "A" (effects (font (size 1.27 1.27))))
      (number "1" (effects (font (size 1.27 1.27))))
    )
  )
  (symbol "GOOD_PART" (in_bom yes) (on_board yes)
    (property "Reference" "U" (id 0) (at 0 0 0)
      (effects (font (size 1.27 1.27)))
    )
    (symbol "GOOD_PART_1_1"
      (pin passive line (at 0 0 0) (length 2.54)
        (name "P1" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27))))
      )
    )
  )
  (symbol "DERIVED_PART" (extends "GOOD_PART")
    (property "Reference" "U" (id 0) (at 0 0 0)
      (effects (font (size 1.27 1.27)))
    )
  )
)
"""

# A schematic embedding a flat symbol snapshot in (lib_symbols) — symbol
# names carry the LIB: prefix but sub-unit names must not. Property values
# contain unescaped parens to exercise the string-aware scanner.
FLAT_SCH = """\
(kicad_sch (version 20250114) (generator "eeschema") (generator_version "9.0")
  (uuid 11111111-2222-3333-4444-555555555555)
  (paper "A4")
  (lib_symbols
    (symbol "VendorLib:ADM3057E" (pin_numbers hide) (in_bom yes) (on_board yes)
      (property "Reference" "U" (at 0 0 0) (effects (font (size 1.27 1.27))))
      (property "Description" "Isolated CAN (5kV rms) transceiver" (at 0 2 0)
        (effects (font (size 1.27 1.27)))
      )
      (pin passive line (at 0 0 0) (length 2.54)
        (name "VIO(1)" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27))))
      )
    )
  )
  (symbol (lib_id "VendorLib:ADM3057E") (at 50 50 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid aaaaaaaa-bbbb-cccc-dddd-111111111111)
    (property "Reference" "U1" (at 50 45 0) (effects (font (size 1.27 1.27))))
    (property "Value" "ADM3057E" (at 50 55 0) (effects (font (size 1.27 1.27))))
  )
  (sheet_instances (path "/" (page "1")))
)
"""


@pytest.fixture()
def commands():
    return SymbolRepairCommands()


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


@pytest.mark.unit
class TestRepairFlatSymbols:
    def test_dry_run_default_reports_without_writing(self, commands, tmp_path):
        path = _write(tmp_path, "flat.kicad_sym", FLAT_SYM)
        r = commands.repair_flat_symbols({"path": path})
        assert r["success"] is True
        assert r["dryRun"] is True
        assert r["flat_symbols_found"] == ["NCV7356"]
        assert r["repaired"] == []
        assert Path(path).read_text(encoding="utf-8") == FLAT_SYM  # untouched

    def test_repair_writes_subunit(self, commands, tmp_path):
        path = _write(tmp_path, "flat.kicad_sym", FLAT_SYM)
        r = commands.repair_flat_symbols({"path": path, "dryRun": False})
        assert r["success"] is True
        assert r["repaired"] == ["NCV7356"]
        content = Path(path).read_text(encoding="utf-8")
        assert '(symbol "NCV7356_1_1"' in content
        # No-reformat guarantee: original property lines appear verbatim
        assert '    (property "Reference" "IC" (id 0) (at 27.94 7.62 0)' in content

    def test_idempotent(self, commands, tmp_path):
        path = _write(tmp_path, "flat.kicad_sym", FLAT_SYM)
        commands.repair_flat_symbols({"path": path, "dryRun": False})
        first = Path(path).read_text(encoding="utf-8")
        r = commands.repair_flat_symbols({"path": path, "dryRun": False})
        assert r["success"] is True
        assert r["flat_symbols_found"] == []
        assert "skipped_reason" in r
        assert Path(path).read_text(encoding="utf-8") == first

    def test_wrapped_symbol_untouched(self, commands, tmp_path):
        path = _write(tmp_path, "good.kicad_sym", WRAPPED_SYM)
        r = commands.repair_flat_symbols({"path": path, "dryRun": False})
        assert r["success"] is True
        assert r["flat_symbols_found"] == []
        assert Path(path).read_text(encoding="utf-8") == WRAPPED_SYM

    def test_multi_symbol_lib_wraps_only_flat(self, commands, tmp_path):
        path = _write(tmp_path, "multi.kicad_sym", MULTI_SYM)
        r = commands.repair_flat_symbols({"path": path, "dryRun": False})
        assert r["success"] is True
        assert r["flat_symbols_found"] == ["FLAT_ONE"]
        content = Path(path).read_text(encoding="utf-8")
        assert '(symbol "FLAT_ONE_1_1"' in content
        assert content.count('(symbol "GOOD_PART_1_1"') == 1
        assert '(symbol "DERIVED_PART_1_1"' not in content

    def test_schematic_embedded_snapshot(self, commands, tmp_path):
        path = _write(tmp_path, "flat.kicad_sch", FLAT_SCH)
        r = commands.repair_flat_symbols({"path": path, "dryRun": False})
        assert r["success"] is True
        assert r["flat_symbols_found"] == ["VendorLib:ADM3057E"]
        content = Path(path).read_text(encoding="utf-8")
        # LIB: prefix stripped from the sub-unit name
        assert '(symbol "ADM3057E_1_1"' in content
        assert '(symbol "VendorLib:ADM3057E_1_1"' not in content
        # Placed instance outside lib_symbols untouched
        assert '(symbol (lib_id "VendorLib:ADM3057E") (at 50 50 0) (unit 1)' in content

    def test_schematic_without_lib_symbols(self, commands, tmp_path):
        path = _write(tmp_path, "bare.kicad_sch", "(kicad_sch (version 1))")
        r = commands.repair_flat_symbols({"path": path, "dryRun": False})
        assert r["success"] is True
        assert r["flat_symbols_found"] == []
        assert "no lib_symbols" in r["skipped_reason"]

    def test_bad_extension(self, commands, tmp_path):
        path = _write(tmp_path, "notes.txt", "hello")
        r = commands.repair_flat_symbols({"path": path})
        assert r["success"] is False
        assert ".kicad_sym or .kicad_sch" in r["message"]

    def test_missing_path(self, commands, tmp_path):
        r = commands.repair_flat_symbols({})
        assert r["success"] is False
        r = commands.repair_flat_symbols({"path": str(tmp_path / "nope.kicad_sym")})
        assert r["success"] is False
        assert "not found" in r["message"]

    def test_unbalanced_file_fails_cleanly(self, commands, tmp_path):
        path = _write(tmp_path, "broken.kicad_sym", "(kicad_symbol_lib (symbol \"X\" (pin ")
        before = Path(path).read_text(encoding="utf-8")
        r = commands.repair_flat_symbols({"path": path, "dryRun": False})
        assert r["success"] is False
        assert Path(path).read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# Integration: kicad-skip can load the repaired schematic
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestKicadSkipLoads:
    @pytest.fixture(autouse=True)
    def _require_real_skip(self):
        skip_mod = pytest.importorskip("skip")
        if getattr(skip_mod, "__file__", None) is None:
            pytest.skip("real kicad-skip not installed (conftest stub)")
        self.skip = skip_mod

    def test_flat_schematic_fails_then_repaired_loads(self, commands, tmp_path):
        path = _write(tmp_path, "flat.kicad_sch", FLAT_SCH)
        with pytest.raises(Exception):
            self.skip.Schematic(path)

        r = commands.repair_flat_symbols({"path": path, "dryRun": False})
        assert r["success"] is True

        sch = self.skip.Schematic(path)  # must not raise now
        refs = [s.property.Reference.value for s in sch.symbol]
        assert "U1" in refs


# ---------------------------------------------------------------------------
# Integration: kicad-cli renders flat and repaired schematics identically
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRenderNeutral:
    def test_svg_render_identity(self, commands, tmp_path):
        if shutil.which("kicad-cli") is None:
            pytest.skip("kicad-cli not available")

        # Same file name in two directories: kicad-cli embeds the file name
        # in the rendered title block.
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        flat = _write(tmp_path / "a", "sheet.kicad_sch", FLAT_SCH)
        repaired = _write(tmp_path / "b", "sheet.kicad_sch", FLAT_SCH)
        r = commands.repair_flat_symbols({"path": repaired, "dryRun": False})
        assert r["success"] is True

        def _export(sch, out_dir):
            out_dir.mkdir()
            subprocess.run(
                ["kicad-cli", "sch", "export", "svg", sch, "-o", str(out_dir)],
                check=True,
                capture_output=True,
                timeout=120,
            )
            svgs = sorted(out_dir.glob("*.svg"))
            assert len(svgs) == 1
            return svgs[0].read_text(encoding="utf-8")

        svg_flat = _export(flat, tmp_path / "out_flat")
        svg_repaired = _export(repaired, tmp_path / "out_repaired")
        # Strip the title block (carries the file name/date) before comparing
        import re as _re

        def _normalize(svg):
            return _re.sub(r"<title>.*?</title>", "", svg, flags=_re.S)

        assert _normalize(svg_flat) == _normalize(svg_repaired)
