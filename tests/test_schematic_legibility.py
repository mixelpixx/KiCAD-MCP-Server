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
# power:GND as KiCad draws it: the stub is a polyline leg from (0 0), where its
# zero-length pin is, not a pin of its own.
LIB_GND = """
  (symbol "T:GND" (power)
    (symbol "GND_0_1"
      (polyline (pts (xy 0 0) (xy 0 -1.27) (xy 1.27 -1.27) (xy 0 -2.54) (xy -1.27 -1.27) (xy 0 -1.27))))
    (symbol "GND_1_1" (pin power_in line (at 0 0 270) (length 0) (name "GND") (number "1"))))
"""
# interf_u's LED: its light arrows reach 0.76 mm past the cathode's pin end.
LIB_LED = """
  (symbol "T:LED"
    (symbol "LED_0_1"
      (polyline (pts (xy -3.048 -0.762) (xy -4.572 -2.286) (xy -3.81 -2.286) (xy -4.572 -2.286)
                     (xy -4.572 -1.524)))
      (polyline (pts (xy -1.778 -0.762) (xy -3.302 -2.286) (xy -2.54 -2.286) (xy -3.302 -2.286)
                     (xy -3.302 -1.524)))
      (polyline (pts (xy -1.27 0) (xy 1.27 0)))
      (polyline (pts (xy -1.27 -1.27) (xy -1.27 1.27)))
      (polyline (pts (xy 1.27 -1.27) (xy 1.27 1.27) (xy -1.27 0) (xy 1.27 -1.27)))
      (pin passive line (at -3.81 0 0) (length 2.54) (name "K") (number "1"))
      (pin passive line (at 3.81 0 180) (length 2.54) (name "A") (number "2"))))
"""
# vme-wren's wire pad (W1): its zero-length pin is in the middle of its outline.
LIB_PAD = """
  (symbol "T:PAD"
    (symbol "PAD_1_1"
      (polyline (pts (xy -0.762 -0.508) (xy -0.762 0.508) (xy -0.508 0.762) (xy 0.508 0.762)
                     (xy 0.762 0.508) (xy 0.762 -0.508) (xy 0.508 -0.762) (xy -0.508 -0.762)
                     (xy -0.762 -0.508)))
      (pin bidirectional line (at 0 0 180) (length 0) (name "1") (number "1"))))
"""


def sheet(tmp_path, body, paper="A4"):
    f = tmp_path / "s.kicad_sch"
    f.write_text(
        f'(kicad_sch (version 20250114) (paper "{paper}")\n'
        f"(lib_symbols {LIB_R} {LIB_A} {LIB_GND} {LIB_LED} {LIB_PAD})\n{body})",
        encoding="utf-8",
    )
    return f


def field(name, text, x, y, angle=0, justify=None, hide=False):
    j = f" (justify {justify})" if justify else ""
    h = " (hide yes)" if hide else ""
    return (
        f'(property "{name}" "{text}" (at {x} {y} {angle}) '
        f"(effects (font (size 1.27 1.27)){j}{h}))"
    )


def symbol(lib, ref, x, y, rot=0, mirror=None, fields=()):
    m = f" (mirror {mirror})" if mirror else ""
    return (
        f'(symbol (lib_id "{lib}") (at {x} {y} {rot}){m} (unit 1) '
        + field("Reference", ref, x, y - 10, hide=True)
        + " ".join(fields)
        + ")"
    )


def kinds(f):
    return {p["kind"] for p in check_legibility(f)["problems"]}


def test_clean_sheet_has_no_problems(tmp_path):
    f = sheet(
        tmp_path,
        symbol(
            "T:R", "R1", 100, 100, fields=[field("Value", "10K", 102.03, 101.27, justify="left")]
        )
        + '\n(label "NET A" (at 50 50 0) (effects (font (size 1.27 1.27)) (justify left)))',
    )
    r = check_legibility(f)
    assert r["total"] == 0, r


def test_labels_on_top_of_each_other(tmp_path):
    f = sheet(
        tmp_path,
        '(label "VDDA" (at 50 50 0) (effects (font (size 1.27 1.27)) (justify left)))\n'
        '(label "VDDA" (at 52 50 0) (effects (font (size 1.27 1.27)) (justify left)))',
    )
    assert "text over text" in kinds(f)


def test_field_angle_is_in_the_symbols_frame(tmp_path):
    # A resistor turned 90 degrees with its value field at 90: KiCad draws it
    # horizontally, here clear of the body to the right.
    clear = symbol(
        "T:R", "R1", 100, 100, rot=90, fields=[field("Value", "1.0M 0.1%", 100, 97, angle=90)]
    )
    assert "field over own body" not in kinds(sheet(tmp_path, clear))
    # The same value at angle 0 on that resistor runs vertically, straight through it.
    through = symbol(
        "T:R", "R1", 100, 100, rot=90, fields=[field("Value", "1.0M 0.1%", 100, 100, angle=0)]
    )
    assert "field over own body" in kinds(sheet(tmp_path, through))


def test_a_symbols_own_fields_may_not_overlap(tmp_path):
    f = sheet(
        tmp_path,
        symbol(
            "T:R",
            "Y2",
            100,
            100,
            fields=[field("Value", "25MHz CL18pF", 110, 100), field("Reference", "Y2", 110, 100.2)],
        ).replace(field("Reference", "Y2", 100, 90, hide=True), ""),
    )
    assert "text over text" in kinds(f)


def test_mirror_is_applied_after_rotation(tmp_path):
    # Body x 0..6 mirrored about y: it lies at x -6..0 of the anchor. A value
    # straddling x 94 crosses the mirrored body's left edge (and would be clear
    # of an unmirrored one); a value straddling x 106 is clear of the mirrored
    # body (and would cross an unmirrored one).
    right = symbol("T:A", "U1", 100, 100, mirror="y", fields=[field("Value", "ABC", 105.5, 100)])
    left = symbol("T:A", "U1", 100, 100, mirror="y", fields=[field("Value", "ABC", 94.5, 100)])
    assert "field over own body" not in kinds(sheet(tmp_path, right))
    assert "field over own body" in kinds(sheet(tmp_path, left))


def test_field_inside_own_body_is_accepted_whatever_the_body_size(tmp_path):
    # KiCad's Device:R puts its value at (0 0 90), inside the 2 x 5 mm rectangle:
    # a short value fits inside and is not a problem; a long one crosses the
    # outline top and bottom and is.
    fits = symbol("T:R", "R1", 100, 100, fields=[field("Value", "10K", 100, 100, angle=90)])
    assert check_legibility(sheet(tmp_path, fits))["total"] == 0
    crosses = symbol(
        "T:R", "R1", 100, 100, fields=[field("Value", "100K 1% 0603", 100, 100, angle=90)]
    )
    assert "field over own body" in kinds(sheet(tmp_path, crosses))


def test_outside_frame_and_title_block(tmp_path):
    f = sheet(
        tmp_path,
        '(label "EDGE" (at 290 100 0) (effects (font (size 1.27 1.27)) (justify left)))\n'
        '(text "NOTE ON THE TITLE BLOCK" (at 230 185 0) (effects (font (size 1.27 1.27))))',
    )
    k = kinds(f)
    assert "outside frame" in k and "on title block" in k


def test_paper_size_and_orientation(tmp_path):
    # On A3 the same label is well inside the frame.
    body = '(label "EDGE" (at 290 100 0) (effects (font (size 1.27 1.27)) (justify left)))'
    assert check_legibility(sheet(tmp_path, body, paper="A3"))["total"] == 0
    f = tmp_path / "p.kicad_sch"
    f.write_text(
        '(kicad_sch (version 20250114) (paper "A4" portrait) (lib_symbols) '
        '(label "WIDE" (at 250 100 0) (effects (font (size 1.27 1.27)) (justify left))))'
    )
    assert check_legibility(f)["page"] == {"width": 210, "height": 297}
    assert "outside frame" in kinds(f)


def test_upside_down_field(tmp_path):
    f = sheet(
        tmp_path,
        symbol("T:R", "R1", 100, 100, rot=180, fields=[field("Value", "11K", 105, 100, angle=180)]),
    )
    assert "upside down" in kinds(f)


def test_hidden_fields_are_ignored(tmp_path):
    f = sheet(
        tmp_path, symbol("T:R", "R1", 100, 100, fields=[field("Value", "10K", 100, 100, hide=True)])
    )
    assert check_legibility(f)["total"] == 0


def test_wire_through_text(tmp_path):
    # A riser through a value (seen in a real design: through R18's "0.1%").
    f = sheet(
        tmp_path,
        symbol(
            "T:R",
            "R1",
            100,
            100,
            fields=[field("Value", "2.7M 0.1%", 102.03, 101.27, justify="left")],
        )
        + "\n(wire (pts (xy 107 90) (xy 107 110)))",
    )
    assert "text over wire" in kinds(f)


def test_a_labels_own_wire_is_not_text_over_wire(tmp_path):
    f = sheet(
        tmp_path,
        '(label "SDA" (at 50 50 0) (effects (font (size 1.27 1.27)) (justify left bottom)))\n'
        "(wire (pts (xy 50 50) (xy 70 50)))",
    )
    assert "text over wire" not in kinds(f)


# R at (100, 100): body x 98.98-101.02, y 97.46-102.54; pin stubs at x 100, y 96.19-97.46 and
# 102.54-103.81. The cross-symbol rules use those drawn lines, as the own-field rule does.
def label(text, x, y, angle=0, justify="left"):
    return (
        f'(label "{text}" (at {x} {y} {angle}) '
        f"(effects (font (size 1.27 1.27)) (justify {justify})))"
    )


def test_text_beside_another_parts_pin_stub_is_not_over_its_body(tmp_path):
    """Inside the part's box with its stubs, but clear of every drawn line: the false
    positives on StickHub, bus_pci and pic_programmer were all of this kind."""
    f = sheet(tmp_path, symbol("T:R", "R1", 100, 100) + label("N", 100.6, 97.0))
    assert "text over body" not in kinds(f)


def test_text_across_another_parts_outline_is_over_its_body(tmp_path):
    f = sheet(tmp_path, symbol("T:R", "R1", 100, 100) + label("ACROSS THE PART", 96.0, 100.6))
    assert "text over body" in kinds(f)


def test_text_inside_another_parts_outline_is_over_its_body(tmp_path):
    """Clear of the lines but in the middle of the body: still drawn over the part."""
    f = sheet(
        tmp_path,
        symbol("T:A", "A1", 100, 100)
        + '(text "x" (at 103 100 0) (effects (font (size 1.27 1.27))))',
    )
    assert "text over body" in kinds(f)


def test_pin_stubs_that_meet_are_not_body_over_body(tmp_path):
    """Two parts whose stubs overlap (a power symbol on a pin end, parts joined pin to
    pin) are not on top of each other; their drawn bodies are compared."""
    meet = symbol("T:R", "R1", 100, 100) + symbol("T:R", "R2", 100, 106)
    assert "body over body" not in kinds(sheet(tmp_path, meet))
    stacked = symbol("T:R", "R1", 100, 100) + symbol("T:R", "R2", 100.5, 102)
    assert "body over body" in kinds(sheet(tmp_path, stacked))


def test_kicad_escapes_and_markup_are_measured_as_drawn():
    from commands.schematic_legibility import display_text, text_box

    assert display_text("VPP{slash}MCLR") == "VPP/MCLR"
    assert display_text("A{backslash}B{dblquote}{lt}{gt}{colon}") == 'A\\B"<>:'
    assert display_text("~{RESET}") == "RESET"
    assert display_text("V_{in}^{2}") == "Vin2"
    assert display_text("~{A_{1}}") == "A1"
    assert display_text("{unknown}") == "{unknown}"  # not an escape: drawn as is
    size, just = (1.27, 1.27), {"left"}
    escaped = text_box(0, 0, 0, "VPP{slash}MCLR", size, just, is_label=True)
    plain = text_box(0, 0, 0, "VPP/MCLR", size, just, is_label=True)
    assert escaped == plain


def note(text, x, y, angle=0, justify="left bottom"):
    return (
        f'(text "{text}" (at {x} {y} {angle}) '
        f"(effects (font (size 1.27 1.27)) (justify {justify})))"
    )


def test_a_rotated_note_runs_along_its_angle(tmp_path):
    """KiCad 10's jetson csi.kicad_sch: "CSI x2" at 90 degrees runs bottom to top,
    clear of the label at x 261.62 that a box laid flat reached."""
    lab = label("CAM0.CSI2_CLK-", 261.62, 55.88, justify="left bottom")
    upright = note("CSI x2", 254.635, 54.61, angle=90)
    assert "text over text" not in kinds(sheet(tmp_path, upright + lab))
    flat = note("CSI x2", 254.635, 54.61)
    assert "text over text" in kinds(sheet(tmp_path, flat + lab))


def test_a_rotated_block_swaps_its_width_and_height(tmp_path):
    """A two-line note is boxed 16.9 mm wide (its longest line) and 2.98 mm tall
    (both lines). At 90 degrees the box is 2.98 wide and 16.9 tall, left of and
    above a "left bottom" anchor, which is where KiCad 10 draws the block; KiCad
    draws a note at 270 exactly as at 90 (both seen on a kicad-cli SVG export)."""
    from commands.schematic_legibility import collect

    def box(angle):
        f = sheet(tmp_path, note("LONGEST LINE A\\nB", 100, 100, angle=angle))
        return [round(v, 3) for v in collect(f)[2][0][1]]

    w, h = 14 * 1.27 * 0.95, 1.27 * 1.35 + 1.27
    assert box(0) == [100, round(100 - h, 3), round(100 + w, 3), 100]
    assert box(90) == [round(100 - h, 3), round(100 - w, 3), 100, 100]
    assert box(270) == box(90)


def test_title_block_is_kicads_default_drawing_sheet(tmp_path):
    """On A4 the block's top line is at y 166 (210 - 44) and its left line at x 177
    (297 - 120). A GND value just above it (vme-wren slow_gpio's #PWR01036.Value at
    y 163.07..164.59) or just left of it is clear of it."""
    above = note("GND", 250, 163.07, justify="left top")
    left = note("GND", 176.5, 180, justify="right")
    on = note("GND", 250, 167, justify="left top")
    assert "on title block" not in kinds(sheet(tmp_path, above))
    assert "on title block" not in kinds(sheet(tmp_path, left))
    assert "on title block" in kinds(sheet(tmp_path, on))


def test_a_power_symbol_on_a_pin_end_is_not_body_over_body(tmp_path):
    """The three body-over-body reports on KiCad 10's demos, none visible on the
    render: GND on an LED's cathode (interf_u D1 / #019; the LED's arrows reach past
    the pin end) and GND on a wire pad (vme-wren W1 / #PWR0571; the pin is in the
    middle of the pad). GND's stub starts on the pin, so its box did too."""
    led = symbol("T:LED", "D1", 100, 100, rot=90) + symbol("T:GND", "#019", 100, 103.81)
    assert "body over body" not in kinds(sheet(tmp_path, led))
    pad = symbol("T:PAD", "W1", 100, 100) + symbol("T:GND", "#PWR0571", 100, 100)
    assert "body over body" not in kinds(sheet(tmp_path, pad))


def test_a_power_symbol_dropped_on_a_part_is_body_over_body(tmp_path):
    """Power symbols are compared like any part: a GND drawn across a resistor is.
    So is a part drawn wholly inside another's outline, though no lines cross."""
    f = sheet(tmp_path, symbol("T:R", "R1", 100, 100) + symbol("T:GND", "#PWR1", 100, 99))
    assert "body over body" in kinds(f)
    inside = symbol("T:R", "R2", 100, 100) + symbol("T:PAD", "W2", 100, 100)
    assert "body over body" in kinds(sheet(tmp_path, inside))
