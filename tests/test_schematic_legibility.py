"""check_schematic_legibility: boxes for bodies, fields, labels and texts.

Each case pins a behaviour that was measured against KiCad renders of a real
three-sheet design.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.schematic_legibility import check_legibility  # noqa: E402

# A resistor-like body: 2 x 5 mm rectangle with 1.27 mm pins top and bottom (lib y up).
LIB_R = """
  (symbol "T:R"
    (symbol "R_0_1" (rectangle (start -1.016 -2.54) (end 1.016 2.54)))
    (symbol "R_1_1"
      (pin passive line (at 0 3.81 270) (length 1.27) (name "~") (number "1"))
      (pin passive line (at 0 -3.81 90) (length 1.27) (name "~") (number "2"))))
"""
# An asymmetric body: rectangle from x 0 to 6, used to see the mirror.
LIB_A = """
  (symbol "T:A"
    (symbol "A_0_1" (rectangle (start 0 -1) (end 6 1))))
"""


def sheet(tmp_path, body, paper="A4"):
    f = tmp_path / "s.kicad_sch"
    f.write_text(f'(kicad_sch (version 20250114) (paper "{paper}")\n'
                 f"(lib_symbols {LIB_R} {LIB_A})\n{body})", encoding="utf-8")
    return f


def field(name, text, x, y, angle=0, justify=None, hide=False):
    j = f" (justify {justify})" if justify else ""
    h = " (hide yes)" if hide else ""
    return (f'(property "{name}" "{text}" (at {x} {y} {angle}) '
            f"(effects (font (size 1.27 1.27)){j}{h}))")


def symbol(lib, ref, x, y, rot=0, mirror=None, fields=()):
    m = f" (mirror {mirror})" if mirror else ""
    return (f'(symbol (lib_id "{lib}") (at {x} {y} {rot}){m} (unit 1) '
            + field("Reference", ref, x, y - 10, hide=True) + " ".join(fields) + ")")


def kinds(f):
    return {p["kind"] for p in check_legibility(f)["problems"]}


def test_clean_sheet_has_no_problems(tmp_path):
    f = sheet(tmp_path, symbol("T:R", "R1", 100, 100, fields=[field("Value", "10K", 102.03, 101.27, justify="left")])
              + '\n(label "NET A" (at 50 50 0) (effects (font (size 1.27 1.27)) (justify left)))')
    r = check_legibility(f)
    assert r["total"] == 0, r


def test_labels_on_top_of_each_other(tmp_path):
    f = sheet(tmp_path, '(label "VDDA" (at 50 50 0) (effects (font (size 1.27 1.27)) (justify left)))\n'
                        '(label "VDDA" (at 52 50 0) (effects (font (size 1.27 1.27)) (justify left)))')
    assert "text over text" in kinds(f)


def test_field_angle_is_in_the_symbols_frame(tmp_path):
    # A resistor turned 90 degrees with its value field at 90: KiCad draws it
    # horizontally, here clear of the body to the right.
    clear = symbol("T:R", "R1", 100, 100, rot=90, fields=[field("Value", "1.0M 0.1%", 100, 97, angle=90)])
    assert "field over own body" not in kinds(sheet(tmp_path, clear))
    # The same value at angle 0 on that resistor runs vertically, straight through it.
    through = symbol("T:R", "R1", 100, 100, rot=90, fields=[field("Value", "1.0M 0.1%", 100, 100, angle=0)])
    assert "field over own body" in kinds(sheet(tmp_path, through))


def test_a_symbols_own_fields_may_not_overlap(tmp_path):
    f = sheet(tmp_path, symbol("T:R", "Y2", 100, 100, fields=[
        field("Value", "25MHz CL18pF", 110, 100), field("Reference", "Y2", 110, 100.2)]).replace(
        field("Reference", "Y2", 100, 90, hide=True), ""))
    assert "text over text" in kinds(f)


def test_mirror_is_applied_after_rotation(tmp_path):
    # Body x 0..6 mirrored about y: it lies at x -6..0 of the anchor, so text to the
    # right of the anchor is clear and text to the left is on the body.
    right = symbol("T:A", "U1", 100, 100, mirror="y", fields=[field("Value", "ABC", 104, 100)])
    left = symbol("T:A", "U1", 100, 100, mirror="y", fields=[field("Value", "ABC", 97, 100)])
    assert "field over own body" not in kinds(sheet(tmp_path, right))
    assert "field over own body" in kinds(sheet(tmp_path, left))


def test_outside_frame_and_title_block(tmp_path):
    f = sheet(tmp_path, '(label "EDGE" (at 290 100 0) (effects (font (size 1.27 1.27)) (justify left)))\n'
                        '(text "NOTE ON THE TITLE BLOCK" (at 230 185 0) (effects (font (size 1.27 1.27))))')
    k = kinds(f)
    assert "outside frame" in k and "on title block" in k


def test_paper_size_and_orientation(tmp_path):
    # On A3 the same label is well inside the frame.
    body = '(label "EDGE" (at 290 100 0) (effects (font (size 1.27 1.27)) (justify left)))'
    assert check_legibility(sheet(tmp_path, body, paper="A3"))["total"] == 0
    f = tmp_path / "p.kicad_sch"
    f.write_text('(kicad_sch (version 20250114) (paper "A4" portrait) (lib_symbols) '
                 '(label "WIDE" (at 250 100 0) (effects (font (size 1.27 1.27)) (justify left))))')
    assert check_legibility(f)["page"] == {"width": 210, "height": 297}
    assert "outside frame" in kinds(f)


def test_upside_down_field(tmp_path):
    f = sheet(tmp_path, symbol("T:R", "R1", 100, 100, rot=180,
                               fields=[field("Value", "11K", 105, 100, angle=180)]))
    assert "upside down" in kinds(f)


def test_hidden_fields_are_ignored(tmp_path):
    f = sheet(tmp_path, symbol("T:R", "R1", 100, 100, fields=[field("Value", "10K", 100, 100, hide=True)]))
    assert check_legibility(f)["total"] == 0


def test_wire_through_text(tmp_path):
    # A riser through a value (seen in a real design: through R18's "0.1%").
    f = sheet(tmp_path, symbol("T:R", "R1", 100, 100, fields=[field("Value", "2.7M 0.1%", 102.03, 101.27, justify="left")])
              + "\n(wire (pts (xy 107 90) (xy 107 110)))")
    assert "text over wire" in kinds(f)


def test_a_labels_own_wire_is_not_text_over_wire(tmp_path):
    f = sheet(tmp_path, '(label "SDA" (at 50 50 0) (effects (font (size 1.27 1.27)) (justify left bottom)))\n'
                        "(wire (pts (xy 50 50) (xy 70 50)))")
    assert "text over wire" not in kinds(f)
