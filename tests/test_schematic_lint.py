"""
Tests for lint_schematic_cosmetic (python/commands/schematic_lint.py).

Both passes are netlist-safe by construction: they never move a symbol,
pin, wire, junction, or label anchor — only display attributes change.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.schematic_lint import (  # noqa: E402
    SchematicLintCommands,
    _hide_pin_names,
    _orient_labels,
)

TEMPLATE_SCH = Path(__file__).parent.parent / "python" / "templates" / "empty.kicad_sch"

# Minimal schematic text with three lib defs:
#  - VendorA:NO_PIN_NAMES  — no (pin_names) block -> gets a full insert
#  - VendorA:HAS_PIN_NAMES — (pin_names (offset 1)) without hide -> hide added
#  - VendorA:ALREADY_HIDDEN — already hidden -> untouched
LINT_SCH = """\
(kicad_sch (version 20250114) (generator "eeschema")
  (uuid 99999999-0000-0000-0000-000000000000)
  (paper "A4")
  (lib_symbols
    (symbol "VendorA:NO_PIN_NAMES" (in_bom yes) (on_board yes)
      (property "Reference" "U" (at 0 0 0) (effects (font (size 1.27 1.27))))
      (symbol "NO_PIN_NAMES_1_1"
        (pin passive line (at -5.08 0 0) (length 2.54)
          (name "IN" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27))))
        )
      )
    )
    (symbol "VendorA:HAS_PIN_NAMES" (pin_names (offset 1.016)) (in_bom yes) (on_board yes)
      (property "Reference" "U" (at 0 0 0) (effects (font (size 1.27 1.27))))
      (symbol "HAS_PIN_NAMES_1_1"
        (pin passive line (at -5.08 0 0) (length 2.54)
          (name "IN" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27))))
        )
      )
    )
    (symbol "VendorA:ALREADY_HIDDEN" (pin_names (offset 1.016) (hide yes)) (in_bom yes) (on_board yes)
      (property "Reference" "U" (at 0 0 0) (effects (font (size 1.27 1.27))))
      (symbol "ALREADY_HIDDEN_1_1"
        (pin passive line (at -5.08 0 0) (length 2.54)
          (name "IN" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27))))
        )
      )
    )
  )
  (sheet_instances (path "/" (page "1")))
)
"""


@pytest.mark.unit
class TestHidePinNames:
    def test_all_three_cases(self):
        out, n = _hide_pin_names(LINT_SCH)
        assert n == 2  # insert + add-hide; already-hidden untouched
        # Every top-level def now hides pin names
        for name in ("NO_PIN_NAMES", "HAS_PIN_NAMES", "ALREADY_HIDDEN"):
            def_start = out.index(f'(symbol "VendorA:{name}"')
            sub_start = out.index(f'(symbol "{name}_1_1"')
            header = out[def_start:sub_start]
            assert "(pin_names" in header
            assert "hide" in header, name

    def test_idempotent(self):
        once, n1 = _hide_pin_names(LINT_SCH)
        twice, n2 = _hide_pin_names(once)
        assert n1 == 2
        assert n2 == 0
        assert twice == once

    def test_subunits_and_instances_untouched(self):
        out, _ = _hide_pin_names(LINT_SCH)
        # Sub-unit defs (no ':' in name) got no pin_names insert
        for name in ("NO_PIN_NAMES_1_1", "HAS_PIN_NAMES_1_1", "ALREADY_HIDDEN_1_1"):
            sub_start = out.index(f'(symbol "{name}"')
            sub_line_end = out.index("\n", sub_start)
            following = out[sub_line_end : sub_line_end + 60]
            assert "(pin_names" not in following

    def test_no_lib_symbols_noop(self):
        out, n = _hide_pin_names("(kicad_sch (version 1))")
        assert n == 0
        assert out == "(kicad_sch (version 1))"


@pytest.mark.unit
class TestOrientLabels:
    LABEL = (
        '\t(label "NETX"\n'
        "\t\t(at 10 20 0)\n"
        "\t\t(effects\n"
        "\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n"
        "\t\t\t(justify left bottom)\n"
        "\t\t)\n"
        "\t)\n"
    )

    def _sch(self, label_block):
        return f"(kicad_sch (version 1)\n{label_block})\n"

    @pytest.mark.parametrize(
        "pin_angle,expected_angle,expected_justify",
        [(0, 180, "right"), (180, 0, "left"), (90, 270, "right"), (270, 90, "left")],
    )
    def test_each_cardinal(self, pin_angle, expected_angle, expected_justify):
        src = self._sch(self.LABEL)
        out, n, skipped = _orient_labels(src, {(10.0, 20.0): pin_angle})
        assert n == 1
        assert skipped == 0
        assert f"(at 10 20 {expected_angle})" in out
        assert f"(justify {expected_justify})" in out
        # anchor untouched
        assert "(at 10 20 " in out

    def test_label_not_on_pin_untouched(self):
        src = self._sch(self.LABEL)
        out, n, skipped = _orient_labels(src, {(99.0, 99.0): 0})
        assert n == 0
        assert skipped == 1
        assert out == src

    def test_justify_inserted_when_missing(self):
        label = self.LABEL.replace("\t\t\t(justify left bottom)\n", "")
        src = self._sch(label)
        out, n, _ = _orient_labels(src, {(10.0, 20.0): 180})
        assert n == 1
        assert "(justify left)" in out

    def test_global_label_handled(self):
        label = self.LABEL.replace('(label "NETX"', '(global_label "NETX"')
        src = self._sch(label)
        out, n, _ = _orient_labels(src, {(10.0, 20.0): 90})
        assert n == 1
        assert "(at 10 20 270)" in out


# ---------------------------------------------------------------------------
# Handler-level
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandler:
    def _handler(self):
        return SchematicLintCommands().lint_schematic_cosmetic

    def test_missing_path(self):
        r = self._handler()({})
        assert r["success"] is False

    def test_nonexistent_file(self, tmp_path):
        r = self._handler()({"schematicPath": str(tmp_path / "no.kicad_sch")})
        assert r["success"] is False

    def test_bad_pass_name(self, tmp_path):
        sch = tmp_path / "s.kicad_sch"
        sch.write_text(LINT_SCH, encoding="utf-8")
        r = self._handler()({"schematicPath": str(sch), "passes": ["bogus"]})
        assert r["success"] is False
        assert "bogus" in r["message"]

    def test_dry_run_counts_but_no_write(self, tmp_path):
        sch = tmp_path / "s.kicad_sch"
        sch.write_text(LINT_SCH, encoding="utf-8")
        r = self._handler()(
            {"schematicPath": str(sch), "passes": ["hide_pin_names"], "dryRun": True}
        )
        assert r["success"] is True
        assert r["dryRun"] is True
        assert r["changed"] is True
        assert r["counts"]["hide_pin_names"] == 2
        assert sch.read_text(encoding="utf-8") == LINT_SCH

    def test_hide_pass_writes(self, tmp_path):
        sch = tmp_path / "s.kicad_sch"
        sch.write_text(LINT_SCH, encoding="utf-8")
        r = self._handler()({"schematicPath": str(sch), "passes": ["hide_pin_names"]})
        assert r["success"] is True
        assert r["changed"] is True
        content = sch.read_text(encoding="utf-8")
        assert content.count("(hide yes)") == 3

    def test_zero_counts_on_bare_sheet(self, tmp_path):
        sch = tmp_path / "s.kicad_sch"
        sch.write_text(TEMPLATE_SCH.read_text(encoding="utf-8"), encoding="utf-8")
        r = self._handler()({"schematicPath": str(sch)})
        assert r["success"] is True
        assert r["counts"]["orient_labels"] == 0


# ---------------------------------------------------------------------------
# Rotation/mirror integration (real kicad-skip + PinLocator)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRotationMirrorIntegration:
    """The case the raw-text reference script could not handle: labels on
    pins of rotated/mirrored instances must orient by the pin's TRUE
    sheet-space outward side."""

    @pytest.fixture(autouse=True)
    def _require_real_skip(self):
        skip_mod = pytest.importorskip("skip")
        if getattr(skip_mod, "__file__", None) is None:
            pytest.skip("real kicad-skip not installed (conftest stub)")

    def _build_sheet(self, tmp_path, rotation=0, mirror=None):
        """Template + one Device:R at (50,50) with rotation/mirror, plus a
        label at each pin position (computed by PinLocator itself)."""
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
        from commands.pin_locator import PinLocator

        mirror_sexp = f" (mirror {mirror})" if mirror else ""
        placed = (
            f'  (symbol (lib_id "Device:R") (at 50 50 {rotation}){mirror_sexp} (unit 1)\n'
            "    (in_bom yes) (on_board yes) (dnp no)\n"
            '    (uuid "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")\n'
            '    (property "Reference" "R1" (at 52 47 0)\n'
            "      (effects (font (size 1.27 1.27)))\n"
            "    )\n"
            '    (property "Value" "10k" (at 52 53 0)\n'
            "      (effects (font (size 1.27 1.27)))\n"
            "    )\n"
            "  )\n"
        )
        content = TEMPLATE_SCH.read_text(encoding="utf-8").rstrip()
        assert content.endswith(")")
        content = content[:-1] + "\n" + placed + ")\n"
        sch = tmp_path / "rot.kicad_sch"
        sch.write_text(content, encoding="utf-8")

        locator = PinLocator()
        pins = locator.get_all_symbol_pins(sch, "R1")
        assert pins
        labels = ""
        for i, (pin_num, coords) in enumerate(sorted(pins.items())):
            labels += (
                f'  (label "NET_{pin_num}" (at {round(coords[0], 2)} {round(coords[1], 2)} 0)\n'
                "    (effects (font (size 1.27 1.27)) (justify left bottom))\n"
                "  )\n"
            )
        content = sch.read_text(encoding="utf-8").rstrip()[:-1] + "\n" + labels + ")\n"
        sch.write_text(content, encoding="utf-8")
        return sch, locator, pins

    @pytest.mark.parametrize(
        "rotation,mirror",
        [(0, None), (90, None), (180, None), (0, "y"), (90, "x")],
    )
    def test_orientation_matches_pin_outward_side(self, tmp_path, rotation, mirror):
        from commands.pin_locator import PinLocator
        from commands.schematic_lint import _ORIENT, _build_pin_orient_map

        sch, _, pins = self._build_sheet(tmp_path, rotation=rotation, mirror=mirror)
        handler = SchematicLintCommands().lint_schematic_cosmetic
        r = handler({"schematicPath": str(sch), "passes": ["orient_labels"]})
        assert r["success"], r
        assert r["counts"]["orient_labels"] >= 1
        assert r["skippedLabels"] == 0

        # Each label's written angle must equal the _ORIENT entry for the
        # pin's true outward angle (fresh locator: file changed on disk).
        locator = PinLocator()
        pin_map = _build_pin_orient_map(sch)
        content = sch.read_text(encoding="utf-8")
        for pin_num, coords in pins.items():
            key = (round(coords[0], 2), round(coords[1], 2))
            expected_angle, expected_justify = _ORIENT[pin_map[key]]
            m = re.search(
                rf'\(label "NET_{pin_num}" \(at {key[0]} {key[1]} (\d+)\)',
                content,
            )
            assert m, f"label NET_{pin_num} anchor moved!"
            assert int(m.group(1)) == expected_angle
            assert f"(justify {expected_justify})" in content

    def test_anchor_multiset_invariant(self, tmp_path):
        """Netlist-safety proxy: the multiset of label anchors and symbol
        positions is unchanged after both passes."""
        sch, _, _ = self._build_sheet(tmp_path, rotation=90)

        def anchors(text):
            return sorted(
                (m.group(1), m.group(2))
                for m in re.finditer(r"\(at (-?[\d.]+) (-?[\d.]+)[ )]", text)
            )

        before_content = sch.read_text(encoding="utf-8")
        # angle may change; compare x/y pairs only
        before = anchors(before_content)
        r = SchematicLintCommands().lint_schematic_cosmetic({"schematicPath": str(sch)})
        assert r["success"], r
        after = anchors(sch.read_text(encoding="utf-8"))
        assert before == after
