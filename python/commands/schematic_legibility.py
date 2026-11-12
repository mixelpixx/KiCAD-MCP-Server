"""Schematic legibility check: what a reader would trip over, not what ERC checks.

ERC and a netlist prove a sheet is connected; they say nothing about whether a
person can read it. This boxes (in sheet mm) every symbol body (from its library
graphics, rotated then mirrored as KiCad applies them), every visible reference
and value, every net/global/hierarchical label and every free text, and reports:

- text over text (a symbol's own fields included)
- text over another symbol's body
- a symbol's own field across a drawn line of its body (inside an IC's
  rectangle or beside a capacitor's plates is fine, whatever the body's size:
  KiCad's own Device:R puts its value inside the rectangle)
- body over body
- a wire through a text (a label's own wire only touches its edge)
- anything on the title block (KiCad's default drawing sheet, approx.) or
  outside the page frame
- a field stored at 180 degrees, or a free text at 180/270 (drawn upside down)

Calibrated against renders of a released three-sheet design: the text-size
model is the one in ``schematic_text_metrics``, shared with the declutter and
field-layout tools; a field's angle and justification live in the symbol's
frame and are carried through the symbol's rotation, then its mirror.
"""

import math
import re
from pathlib import Path

import sexpdata
from commands.schematic_text_metrics import LABEL_FLAG, text_height, text_width

S = sexpdata.Symbol
PAPER = {
    "A5": (210, 148),
    "A4": (297, 210),
    "A3": (420, 297),
    "A2": (594, 420),
    "A1": (841, 594),
    "A0": (1189, 841),
    "A": (279.4, 215.9),
    "B": (431.8, 279.4),
    "C": (558.8, 431.8),
    "D": (863.6, 558.8),
    "E": (1117.6, 863.6),
}


def find(node, tag):
    return [c for c in node if isinstance(c, list) and c and c[0] == S(tag)]


def first(node, tag):
    f = find(node, tag)
    return f[0] if f else None


def at_of(node):
    a = first(node, "at")
    if not a:
        return 0.0, 0.0, 0.0
    vals = [float(v) for v in a[1:4]] + [0.0] * (3 - len(a[1:4]))
    return vals[0], vals[1], vals[2]


def text_size(node):
    eff = first(node, "effects")
    if eff:
        font = first(eff, "font")
        if font:
            sz = first(font, "size")
            if sz:
                return float(sz[1]), float(sz[2])
    return 1.27, 1.27


def hidden(node):
    eff = first(node, "effects")
    if eff:
        if S("hide") in eff:
            return True
        h = first(eff, "hide")
        if h and (len(h) == 1 or str(h[1]) == "yes"):
            return True
    h = first(node, "hide")
    return bool(h and (len(h) == 1 or str(h[1]) == "yes"))


def justify(node):
    eff = first(node, "effects")
    j = first(eff, "justify") if eff else None
    return {str(x) for x in j[1:]} if j else set()


# KiCad stores characters that have a meaning in its text formats as {name}
# escapes (EscapeString / UnescapeString): a net "VPP/MCLR" is saved as
# "VPP{slash}MCLR". Measured raw, that was 14 characters wide instead of 8.
_KICAD_ESCAPES = {
    "slash": "/",
    "backslash": "\\",
    "dblquote": '"',
    "quote": "'",
    "lt": "<",
    "gt": ">",
    "colon": ":",
    "tab": " ",
    "return": " ",
    "space": " ",
    "brace": "{",
}
_ESCAPE_RE = re.compile(r"\{(" + "|".join(_KICAD_ESCAPES) + r")\}")
# Overbar (~{RESET}), superscript (^{2}) and subscript (_{in}) markup: the braces
# and the marker are not drawn; the inner text is (KiCad's markup parser).
_MARKUP_RE = re.compile(r"[~^_]\{([^{}]*)\}")


def display_text(text):
    """The characters KiCad draws for a stored text: markup stripped, escapes decoded."""
    prev = None
    while prev != text:  # nested markup: ~{A_{1}}
        prev, text = text, _MARKUP_RE.sub(r"\1", text)
    return _ESCAPE_RE.sub(lambda m: _KICAD_ESCAPES[m.group(1)], text)


def text_box(x, y, angle, text, size, just, label=False, is_label=False):
    """Axis-aligned box of a text anchored at (x, y).

    label: has a flag outline (global/hierarchical); is_label: any net label.
    """
    w = text_width(display_text(text), size[0])
    h = text_height(size[1])
    if label:
        w += size[0] * LABEL_FLAG  # flag / shape around global & hierarchical labels
    horiz = int(round(angle)) % 180 == 0
    if not is_label:
        # Fields and texts: justification runs along the text's own direction
        # (angle CCW, sheet y down). KiCad draws a 180/270 text upright with the
        # justification flipped, which covers the same box.
        a = math.radians(angle)
        ux, uy = round(math.cos(a)), -round(math.sin(a))  # along the text
        vx, vy = -uy, ux  # across it (top -> bottom for upright text)
        al = (0, w) if "left" in just else ((-w, 0) if "right" in just else (-w / 2, w / 2))
        ac = (-h, 0) if "bottom" in just else ((0, h) if "top" in just else (-h / 2, h / 2))
        xs = [x + ux * p + vx * q for p in al for q in ac]
        ys = [y + uy * p + vy * q for p in al for q in ac]
        return (min(xs), min(ys), max(xs), max(ys))
    # Labels: anchor -> box along the text direction
    if "left" in just:
        a0, a1 = 0, w
    elif "right" in just:
        a0, a1 = -w, 0
    else:
        a0, a1 = -w / 2, w / 2
    if "bottom" in just:
        b0, b1 = -h, 0
    elif "top" in just:
        b0, b1 = 0, h
    else:
        b0, b1 = -h / 2, h / 2
    # KiCad applies justify in screen terms after rotation: a 180-degree label with
    # justify right runs left of its anchor, so horizontal boxes are not flipped.
    side = not label  # a local net label: text beside its wire whatever the justify
    off = 0.2 * size[1]  # gap between wire and text, ~0.25 mm at 1.27 (rendered text then
    #                      sits ~1.2 mm off the wire once the glyph's own bearing is added)
    if horiz:
        if side:  # drawn above its wire, not centred on it
            return (x + a0, y - h - off, x + a1, y - off)
        return (x + a0, y + b0, x + a1, y + b1)
    # Vertical text: "left" grows upward from the anchor, "right" downward.
    if "right" in just:
        y0, y1 = 0, w
    elif "left" in just:
        y0, y1 = -w, 0
    else:
        y0, y1 = -w / 2, w / 2
    if side:  # drawn left of its wire
        return (x - h - off, y + y0, x - off, y + y1)
    return (x - h / 2, y + y0, x + h / 2, y + y1)


def field_box(x, y, angle, text, size, just, sym_rot, mirror):
    """Box of a symbol field. KiCad stores a field's angle and justification in the
    symbol's own frame: the text box is laid out about its anchor with the field's
    angle, then carried through the symbol's rotation and mirror (KiCad then draws
    the text upright inside that same box). A 90-degree field on a 90-degree
    resistor is therefore horizontal on the sheet."""
    b = text_box(0.0, 0.0, angle, text, size, just)
    corners = [(b[0], b[1]), (b[2], b[1]), (b[0], b[3]), (b[2], b[3])]
    r = math.radians(sym_rot)
    out = []
    for cx, cy in corners:
        # sheet y-down -> math y-up, apply mirror, rotate CCW by the symbol angle, back
        qx, qy = cx, -cy
        rx = qx * math.cos(r) - qy * math.sin(r)
        ry = qx * math.sin(r) + qy * math.cos(r)
        # mirror after the rotation, as KiCad applies it (a rot 270 + mirror y
        # Q-DPAK has its drain on the left and its right-justified field growing right)
        if mirror == "y":
            rx = -rx
        elif mirror == "x":
            ry = -ry
        out.append((x + rx, y - ry))
    return (
        min(p[0] for p in out),
        min(p[1] for p in out),
        max(p[0] for p in out),
        max(p[1] for p in out),
    )


def lib_graphics(sym_def, unit):
    """The graphic items (and pins) of a lib symbol that draw for one unit."""
    for sub in find(sym_def, "symbol"):
        name = str(sub[1])
        m = re.search(r"_(\d+)_(\d+)$", name)
        if m and int(m.group(1)) not in (0, unit):
            continue
        for g in sub[2:]:
            if (
                isinstance(g, list)
                and g
                and str(g[0]) in ("rectangle", "polyline", "circle", "arc", "bezier", "pin")
            ):
                yield g


def lib_segments(sym_def, unit):
    """The drawn lines of a lib symbol for one unit, in lib coords (y up).

    A rectangle gives its four edges, a polyline its legs, a pin its stub, a
    circle a 16-gon and an arc its two chords through the mid point. These are
    what a field can be drawn across. The bbox alone is mostly empty on a small
    part: a reference tucked beside a capacitor's pin stub crosses the box but
    no line, and reads fine.
    """
    segs = []

    def add(points, closed=False):
        pts = list(points)
        if closed and pts:
            pts.append(pts[0])
        segs.extend(zip(pts, pts[1:]))

    for g in lib_graphics(sym_def, unit):
        tag = str(g[0])
        if tag == "rectangle":
            s, e = first(g, "start"), first(g, "end")
            x0, y0, x1, y1 = float(s[1]), float(s[2]), float(e[1]), float(e[2])
            add([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], closed=True)
        elif tag in ("polyline", "bezier"):
            p = first(g, "pts")
            add([(float(xy[1]), float(xy[2])) for xy in (find(p, "xy") if p else [])])
        elif tag == "circle":
            c = first(g, "center")
            r = float(first(g, "radius")[1])
            cx, cy = float(c[1]), float(c[2])
            add(
                [
                    (cx + r * math.cos(k * math.pi / 8), cy + r * math.sin(k * math.pi / 8))
                    for k in range(16)
                ],
                closed=True,
            )
        elif tag == "arc":
            add(
                [
                    (float(p[1]), float(p[2]))
                    for p in (first(g, k) for k in ("start", "mid", "end"))
                    if p
                ]
            )
        elif tag == "pin":
            x, y, a = at_of(g)
            ln = float(first(g, "length")[1]) if first(g, "length") else 2.54
            add([(x, y), (x + ln * math.cos(math.radians(a)), y + ln * math.sin(math.radians(a)))])
    return segs


def lib_bbox(sym_def, unit, pins=True):
    """Local bbox (lib coords, y up) of a lib symbol's graphics for one unit.

    pins=False leaves the pin stubs out: the drawn body only. A resistor's box with
    its stubs is twice as long as the rectangle, and text or a power symbol in the
    empty space beside a stub is not over the part."""
    xs, ys = [], []

    def pts(node):
        tag = str(node[0])
        if tag in ("rectangle",):
            for k in ("start", "end"):
                p = first(node, k)
                xs.append(float(p[1]))
                ys.append(float(p[2]))
        elif tag in ("polyline", "bezier"):
            p = first(node, "pts")
            for xy in find(p, "xy") if p else []:
                xs.append(float(xy[1]))
                ys.append(float(xy[2]))
        elif tag == "circle":
            c = first(node, "center")
            r = float(first(node, "radius")[1])
            xs.extend([float(c[1]) - r, float(c[1]) + r])
            ys.extend([float(c[2]) - r, float(c[2]) + r])
        elif tag == "arc":
            for k in ("start", "mid", "end"):
                p = first(node, k)
                if p:
                    xs.append(float(p[1]))
                    ys.append(float(p[2]))
        elif tag == "pin" and pins:
            x, y, a = at_of(node)
            ln = float(first(node, "length")[1]) if first(node, "length") else 2.54
            xs.extend([x, x + ln * math.cos(math.radians(a))])
            ys.extend([y, y + ln * math.sin(math.radians(a))])

    for g in lib_graphics(sym_def, unit):
        pts(g)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def place_point(px, py, x, y, rot, mirror):
    """A lib point (y up) onto the sheet (y down): rotate CCW, then mirror, as KiCad does."""
    r = math.radians(rot)
    qx = px * math.cos(r) - py * math.sin(r)
    qy = px * math.sin(r) + py * math.cos(r)
    if mirror == "y":
        qx = -qx
    elif mirror == "x":
        qy = -qy
    return (x + qx, y - qy)


def place_box(lb, x, y, rot, mirror):
    corners = [(lb[0], lb[1]), (lb[2], lb[1]), (lb[0], lb[3]), (lb[2], lb[3])]
    out = [place_point(px, py, x, y, rot, mirror) for px, py in corners]
    return (
        min(p[0] for p in out),
        min(p[1] for p in out),
        max(p[0] for p in out),
        max(p[1] for p in out),
    )


def place_segments(segs, x, y, rot, mirror):
    return [
        (place_point(*p, x, y, rot, mirror), place_point(*q, x, y, rot, mirror)) for p, q in segs
    ]


def overlap(a, b, pad=0.0):
    return a[0] < b[2] - pad and b[0] < a[2] - pad and a[1] < b[3] - pad and b[1] < a[3] - pad


def segment_crosses_box(seg, box):
    """True when the segment has a run strictly inside the box (Liang-Barsky)."""
    (x0, y0), (x1, y1) = seg
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - box[0]), (dx, box[2] - x0), (-dy, y0 - box[1]), (dy, box[3] - y0)):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
    return t0 < t1


def collect(path):
    data = sexpdata.loads(Path(path).read_text(encoding="utf-8"))
    paper = first(data, "paper")
    name = str(paper[1]) if paper else "A4"
    if name == "User" and len(paper) >= 4:
        pw, ph = float(paper[2]), float(paper[3])
    else:
        pw, ph = PAPER.get(name, (297, 210))
    if paper and S("portrait") in paper:
        pw, ph = ph, pw
    libs = {}
    ls = first(data, "lib_symbols")
    for sd in find(ls, "symbol") if ls else []:
        libs[str(sd[1])] = sd
    bodies, texts, upside = [], [], []
    for sym in find(data, "symbol"):
        lid = first(sym, "lib_name") or first(sym, "lib_id")
        name = str(lid[1]) if lid else ""
        x, y, rot = at_of(sym)
        unit = int(first(sym, "unit")[1]) if first(sym, "unit") else 1
        mir = first(sym, "mirror")
        mirror = str(mir[1]) if mir else None
        ref = ""
        for prop in find(sym, "property"):
            if str(prop[1]) == "Reference":
                ref = str(prop[2])
        sd = libs.get(name)
        if sd is not None:
            lb = lib_bbox(sd, unit)
            if lb:
                segs = place_segments(lib_segments(sd, unit), x, y, rot, mirror)
                core = lib_bbox(sd, unit, pins=False)
                core_box = place_box(core, x, y, rot, mirror) if core else None
                bodies.append((ref, place_box(lb, x, y, rot, mirror), segs, core_box))
        for prop in find(sym, "property"):
            if hidden(prop) or str(prop[1]) not in ("Reference", "Value") or not str(prop[2]):
                continue
            px, py, pa = at_of(prop)
            if int(round(pa)) % 360 == 180:
                # seen on a 180-degree resistor: a field stored at 180 is drawn upside
                # down (270 on a 90-degree part renders upright, so only 180 is flagged)
                upside.append((f"{ref}.{prop[1]}", (px - 1, py - 1, px + 1, py + 1)))
            texts.append(
                (
                    f"{ref}.{prop[1]}",
                    field_box(
                        px, py, pa, str(prop[2]), text_size(prop), justify(prop), rot, mirror
                    ),
                    ref,
                )
            )
    for tag in ("label", "global_label", "hierarchical_label"):
        for lab in find(data, tag):
            x, y, a = at_of(lab)
            texts.append(
                (
                    f"{tag[:-6] or 'label'}:{lab[1]}",
                    text_box(
                        x,
                        y,
                        a,
                        str(lab[1]),
                        text_size(lab),
                        justify(lab),
                        label=tag != "label",
                        is_label=True,
                    ),
                    None,
                )
            )
    for t in find(data, "text"):
        x, y, a = at_of(t)
        lines = display_text(str(t[1])).split("\n")
        size = text_size(t)
        w = text_width(max(lines, key=len), size[0])
        line_h = size[1] * 1.35
        h = (len(lines) - 1) * line_h + size[1]
        just = justify(t)
        x0 = x if "left" in just else (x - w if "right" in just else x - w / 2)
        # KiCad anchors multi-line text by its block: bottom-justified text grows upward.
        if "bottom" in just:
            y0 = y - h
        elif "top" in just:
            y0 = y
        else:
            y0 = y - h / 2
        texts.append((f"text:{lines[0][:20]}", (x0, y0, x0 + w, y0 + h), None))
        if int(round(a)) % 360 in (180, 270):
            upside.append((f"text:{lines[0][:20]}", (x - 1, y - 1, x + 1, y + 1)))
    wires = []
    for w in find(data, "wire"):
        pts = first(w, "pts")
        xy = [(float(q[1]), float(q[2])) for q in find(pts, "xy")] if pts else []
        wires += list(zip(xy, xy[1:]))
    return (pw, ph), bodies, texts, upside, wires


def check(path):
    (pw, ph), bodies, texts, upside, wires = collect(path)
    frame = (10, 10, pw - 10, ph - 10)
    title = (pw - 122, ph - 47, pw - 10, ph - 10)  # KiCad default title block, approx.
    problems = [("upside down", n, b) for n, b in upside]
    items = [("body", n, b, n) for n, b, _s, _c in bodies] + [
        ("text", n, b, o) for n, b, o in texts
    ]
    for kind, name, box, owner in items:
        if overlap(box, title):
            problems.append(("on title block", name, box))
        if box[0] < frame[0] or box[1] < frame[1] or box[2] > frame[2] or box[3] > frame[3]:
            problems.append(("outside frame", name, box))
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a, b = texts[i], texts[j]
            # a symbol's own fields count too: a value drawn over its own reference
            # is as unreadable as one drawn over a neighbour's
            if overlap(a[1], b[1], pad=0.15):
                problems.append(("text over text", f"{a[0]} / {b[0]}", a[1]))
    for n, tb, owner in texts:
        # the text's interior: a line that only touches its edge is not across it
        ib = (tb[0] + 0.3, tb[1] + 0.3, tb[2] - 0.3, tb[3] - 0.3)
        for bn, bb, bs, core in bodies:
            if bn == owner:
                # A symbol's own field may sit inside its body (an IC's name;
                # Device:R's value at (0 0 90) inside its rectangle) or beside
                # it (a reference tucked next to a capacitor's pin stub), but
                # not across a drawn line of it: a value through the plates, a
                # name across the outline. Tested against the lines, not the
                # body's box: the box of a small part is mostly empty, and
                # box-based rules reported 74 stock parts on KiCad's StickHub
                # demo alone.
                if ib[0] < ib[2] and ib[1] < ib[3] and any(segment_crosses_box(s, ib) for s in bs):
                    problems.append(("field over own body", n, tb))
                continue
            # Another symbol: the same test on its drawn lines (pin stubs included,
            # since text across a stub is drawn over it), plus text centred inside
            # its outline. Its box with the stubs is mostly empty space beside the
            # pins: on KiCad's StickHub demo all 14 box-based reports were text
            # clearing a neighbour's stub, none visible on the render.
            crosses = (
                ib[0] < ib[2] and ib[1] < ib[3] and any(segment_crosses_box(s, ib) for s in bs)
            )
            cx, cy = (tb[0] + tb[2]) / 2, (tb[1] + tb[3]) / 2
            inside = core is not None and core[0] < cx < core[2] and core[1] < cy < core[3]
            if crosses or inside:
                problems.append(("text over body", f"{n} / {bn}", tb))
    for n, tb, owner in texts:
        # a wire through the middle of a text (not one that only touches its edge,
        # as a label's own wire does)
        ib = (tb[0] + 0.3, tb[1] + 0.3, tb[2] - 0.3, tb[3] - 0.3)
        if ib[0] >= ib[2] or ib[1] >= ib[3]:
            continue
        for (ax, ay), (bx, by) in wires:
            if ax == bx and ib[0] < ax < ib[2] and min(ay, by) < ib[3] and max(ay, by) > ib[1]:
                problems.append(("text over wire", n, tb))
                break
            if ay == by and ib[1] < ay < ib[3] and min(ax, bx) < ib[2] and max(ax, bx) > ib[0]:
                problems.append(("text over wire", n, tb))
                break
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            # drawn bodies only: two parts whose pin stubs meet (a wire-less
            # connection, or a power symbol on a pin end) are not on top of each other
            ci, cj = bodies[i][3], bodies[j][3]
            if ci and cj and overlap(ci, cj, pad=0.3):
                problems.append(
                    ("body over body", f"{bodies[i][0]} / {bodies[j][0]}", bodies[i][1])
                )
    return (pw, ph), problems


def check_legibility(path, max_problems=200):
    """Run the check on one sheet; returns counts by kind and each problem's box."""
    from collections import Counter

    page, problems = check(path)
    return {
        "page": {"width": page[0], "height": page[1]},
        "total": len(problems),
        "counts": dict(Counter(p[0] for p in problems)),
        "problems": [
            {
                "kind": k,
                "items": n,
                "box": {
                    "x0": round(b[0], 2),
                    "y0": round(b[1], 2),
                    "x1": round(b[2], 2),
                    "y1": round(b[3], 2),
                },
            }
            for k, n, b in problems[:max_problems]
        ],
    }
