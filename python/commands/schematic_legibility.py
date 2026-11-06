"""Schematic legibility check: what a reader would trip over, not what ERC checks.

ERC and a netlist prove a sheet is connected; they say nothing about whether a
person can read it. This boxes (in sheet mm) every symbol body (from its library
graphics, rotated then mirrored as KiCad applies them), every visible reference
and value, every net/global/hierarchical label and every free text, and reports:

- text over text (a symbol's own fields included)
- text over another symbol's body
- a symbol's own field across its outline, or over a small part's graphic
- body over body
- anything on the title block (KiCad's default drawing sheet, approx.) or
  outside the page frame
- a field stored at 180 degrees, or a free text at 180/270 (drawn upside down)

Calibrated against renders of a released three-sheet design: text advance is
0.95 x size per character; a field's angle and justification live in the
symbol's frame and are carried through the symbol's rotation, then its mirror.
"""

import math
import re
from pathlib import Path

import sexpdata

S = sexpdata.Symbol
CHAR_W = 0.95  # advance per character, x text size: measured off renders (AP63205WU, U10 SW, 22uF 10V)
PAPER = {"A5": (210, 148), "A4": (297, 210), "A3": (420, 297), "A2": (594, 420), "A1": (841, 594),
         "A0": (1189, 841), "A": (279.4, 215.9), "B": (431.8, 279.4), "C": (558.8, 431.8),
         "D": (863.6, 558.8), "E": (1117.6, 863.6)}


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


def text_box(x, y, angle, text, size, just, label=False, is_label=False):
    """Axis-aligned box of a text anchored at (x, y).

    label: has a flag outline (global/hierarchical); is_label: any net label.
    """
    w = max(1, len(text)) * size[0] * CHAR_W
    h = size[1] * 1.2
    if label:
        w += size[0] * 1.5  # flag / shape around global & hierarchical labels
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
    if horiz:
        return (x + a0, y + b0, x + a1, y + b1)
    # Vertical text: "left" grows upward from the anchor, "right" downward.
    if "right" in just:
        y0, y1 = 0, w
    elif "left" in just:
        y0, y1 = -w, 0
    else:
        y0, y1 = -w / 2, w / 2
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
    return (min(p[0] for p in out), min(p[1] for p in out), max(p[0] for p in out), max(p[1] for p in out))


def lib_bbox(sym_def, unit):
    """Local bbox (lib coords, y up) of a lib symbol's graphics for one unit."""
    xs, ys = [], []

    def pts(node):
        tag = str(node[0])
        if tag in ("rectangle",):
            for k in ("start", "end"):
                p = first(node, k)
                xs.append(float(p[1])); ys.append(float(p[2]))
        elif tag in ("polyline", "bezier"):
            p = first(node, "pts")
            for xy in find(p, "xy") if p else []:
                xs.append(float(xy[1])); ys.append(float(xy[2]))
        elif tag == "circle":
            c = first(node, "center"); r = float(first(node, "radius")[1])
            xs.extend([float(c[1]) - r, float(c[1]) + r]); ys.extend([float(c[2]) - r, float(c[2]) + r])
        elif tag == "arc":
            for k in ("start", "mid", "end"):
                p = first(node, k)
                if p:
                    xs.append(float(p[1])); ys.append(float(p[2]))
        elif tag == "pin":
            x, y, a = at_of(node)
            ln = float(first(node, "length")[1]) if first(node, "length") else 2.54
            xs.extend([x, x + ln * math.cos(math.radians(a))]); ys.extend([y, y + ln * math.sin(math.radians(a))])

    for sub in find(sym_def, "symbol"):
        name = str(sub[1])
        m = re.search(r"_(\d+)_(\d+)$", name)
        if m and int(m.group(1)) not in (0, unit):
            continue
        for g in sub[2:]:
            if isinstance(g, list) and g and str(g[0]) in ("rectangle", "polyline", "circle", "arc", "bezier", "pin"):
                pts(g)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def place_box(lb, x, y, rot, mirror):
    corners = [(lb[0], lb[1]), (lb[2], lb[1]), (lb[0], lb[3]), (lb[2], lb[3])]
    out = []
    r = math.radians(rot)
    for px, py in corners:
        # lib y-up -> rotate CCW -> mirror (KiCad's order) -> sheet y-down
        qx = px * math.cos(r) - py * math.sin(r)
        qy = px * math.sin(r) + py * math.cos(r)
        if mirror == "y":
            qx = -qx
        elif mirror == "x":
            qy = -qy
        out.append((x + qx, y - qy))
    return (min(p[0] for p in out), min(p[1] for p in out), max(p[0] for p in out), max(p[1] for p in out))


def overlap(a, b, pad=0.0):
    return a[0] < b[2] - pad and b[0] < a[2] - pad and a[1] < b[3] - pad and b[1] < a[3] - pad


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
        if ref.startswith("#PWR") or ref.startswith("#FLG"):
            pass
        sd = libs.get(name)
        if sd is not None:
            lb = lib_bbox(sd, unit)
            if lb:
                bodies.append((ref, place_box(lb, x, y, rot, mirror)))
        for prop in find(sym, "property"):
            if hidden(prop) or str(prop[1]) not in ("Reference", "Value") or not str(prop[2]):
                continue
            px, py, pa = at_of(prop)
            if int(round(pa)) % 360 == 180:
                # seen on a 180-degree resistor: a field stored at 180 is drawn upside
                # down (270 on a 90-degree part renders upright, so only 180 is flagged)
                upside.append((f"{ref}.{prop[1]}", (px - 1, py - 1, px + 1, py + 1)))
            texts.append((f"{ref}.{prop[1]}", field_box(px, py, pa, str(prop[2]), text_size(prop), justify(prop), rot, mirror), ref))
    for tag in ("label", "global_label", "hierarchical_label"):
        for lab in find(data, tag):
            x, y, a = at_of(lab)
            texts.append((f"{tag[:-6] or 'label'}:{lab[1]}",
                          text_box(x, y, a, str(lab[1]), text_size(lab), justify(lab), label=tag != "label", is_label=True), None))
    for t in find(data, "text"):
        x, y, a = at_of(t)
        lines = str(t[1]).split("\n")
        size = text_size(t)
        w = max(len(l) for l in lines) * size[0] * CHAR_W
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
    return (pw, ph), bodies, texts, upside


def check(path):
    (pw, ph), bodies, texts, upside = collect(path)
    frame = (10, 10, pw - 10, ph - 10)
    title = (pw - 122, ph - 47, pw - 10, ph - 10)  # KiCad default title block, approx.
    problems = [("upside down", n, b) for n, b in upside]
    items = [("body", n, b, n) for n, b in bodies] + [("text", n, b, o) for n, b, o in texts]
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
        for bn, bb in bodies:
            if bn == owner:
                # A symbol's own field may sit inside its body (an IC's name) or
                # clear of it, but not across its outline or over a small part's
                # graphic (a rotated capacitor's value drawn through the plates).
                inside = tb[0] >= bb[0] and tb[1] >= bb[1] and tb[2] <= bb[2] and tb[3] <= bb[3]
                small = (bb[2] - bb[0]) < 8 or (bb[3] - bb[1]) < 8
                if overlap(tb, bb, pad=0.3) and (small or not inside):
                    problems.append(("field over own body", n, tb))
                continue
            if overlap(tb, bb, pad=0.3):
                problems.append(("text over body", f"{n} / {bn}", tb))
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            if overlap(bodies[i][1], bodies[j][1], pad=0.3):
                problems.append(("body over body", f"{bodies[i][0]} / {bodies[j][0]}", bodies[i][1]))
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
            {"kind": k, "items": n, "box": {"x0": round(b[0], 2), "y0": round(b[1], 2),
                                           "x1": round(b[2], 2), "y1": round(b[3], 2)}}
            for k, n, b in problems[:max_problems]
        ],
    }
