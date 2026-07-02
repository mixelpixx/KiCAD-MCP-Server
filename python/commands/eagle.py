"""
Eagle (.brd / .sch) → KiCad (.kicad_pcb / .kicad_sch) import commands.

Coordinate-system notes (from KiCad source sch_io_eagle.cpp):
  • Eagle schematic: X right, Y up  (origin anywhere)
  • KiCad schematic: X right, Y down
  • Conversion:  kicad_x = eagle_x
                 kicad_y = y_offset - eagle_y   (y_offset shifts everything positive)

  • Eagle lib-symbol coords: Y up   (same as Eagle schematic)
  • KiCad lib-symbol coords: Y up   (same! — confirmed by Device:R pin 1 at (0, 3.81))
  • Therefore NO Y-flip needed inside symbol definitions.

  • Instance rotation: the Y-flip inverts the apparent rotation direction.
    KiCad_rotation = (-Eagle_rotation) mod 360
"""

from __future__ import annotations

import logging
import math
import os
import re
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("kicad_interface")

# ── Constants ─────────────────────────────────────────────────────────────────
_POWER_LIBS = frozenset({"supply1", "supply2"})
_FRAME_DEVICESETS = frozenset({"a4l-loc", "a3l-loc", "frames", "frame"})
# Passive two-terminal parts whose pin names/numbers should be hidden, like the
# standard KiCad R/L/C symbols.  Detected by the deviceset ref prefix.
_PASSIVE_PREFIXES = frozenset({"R", "L", "C"})
# Two-terminal parts whose Reference/Value get the "vertical" side-placement rule
# (rotated 90°, Reference left / Value right, centred) when drawn vertically.
# R/L/C plus diodes (D) and LEDs.
_VERT_LABEL_PREFIXES = frozenset({"R", "L", "C", "D", "LED"})

_PIN_TYPE: Dict[str, str] = {
    "in":  "input",          "out": "output",
    "io":  "bidirectional",  "oc":  "open_collector",
    "pas": "passive",        "pwr": "power_in",
    "sup": "power_out",      "nc":  "no_connect",
    "hiz": "tri_state",
}
_PIN_LEN: Dict[str, float] = {
    "point": 0.0, "short": 2.54, "middle": 5.08, "long": 7.62,
}

# ── Utility helpers ────────────────────────────────────────────────────────────
def _uid() -> str:
    return str(uuid.uuid4())

def _fmt(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".")

def _escape(s: str) -> str:
    return str(s).replace('"', '\\"')

def _sanitize(s: str) -> str:
    """Make a string safe for use in KiCad symbol names (quoted)."""
    return re.sub(r'[<>"/\\|?*\s]+', "_", s).strip("_") or "X"

def _parse_rot(rot: Optional[str]) -> Tuple[float, bool]:
    """Parse Eagle rotation string like 'R90', 'MR180', 'SMR0' → (degrees, mirror)."""
    if not rot:
        return 0.0, False
    mirror = "M" in rot
    s = rot.replace("S", "").replace("M", "").replace("R", "").strip()
    try:
        return (float(s) if s else 0.0), mirror
    except ValueError:
        return 0.0, mirror

def _krot(eagle_deg: float, mirror: bool = False) -> int:
    """
    Convert an Eagle rotation to the KiCad placement angle.

    The symbol geometry is stored in the library in the original Eagle-local
    frame (Y-up); instances are placed at (eagle_x, y_off - eagle_y).

    KiCad's *placement* angle equals the Eagle rotation for BOTH mirrored and
    non-mirrored parts — the mirror itself is expressed with a separate
    "(mirror y)" flag (see mirror_field below), never by folding it into angle.

    This was reverse-engineered directly from KiCad's own source
    (SCH_SYMBOL::SetOrientation + the S-expr parser's (at .. angle)/(mirror ..)
    handling in sch_io_kicad_sexpr_parser.cpp) and then confirmed by exporting
    a calibration schematic to SVG.  KiCad's effective lib->sheet transform is:

        angle a, no mirror : (lx, ly) -> R(a) with the built-in Y-flip
        angle a, mirror y  : same, then negate sheet X   == Eagle's mirror
                                                            (reflect about Y)

    Eagle's "M" mirrors about the Y axis (flip X), which is exactly KiCad's
    "(mirror y)" — NOT "(mirror x)".  The earlier "(mirror x)"+(180-a) rule
    only coincided for a=0/180 (where (A0,mirror x) == (A180,mirror y)), which
    is why IC1@MR180 looked fine but IC13/FET3@MR90 rendered 180-degrees off
    (i.e. double-mirrored).
    """
    return int(eagle_deg % 360)

def _render_local(lx: float, ly: float, krot: int, mirror: bool) -> Tuple[float, float]:
    """
    Transform a symbol-local point (Eagle-local, Y-up) to the KiCad sheet
    delta from the placement origin, matching KiCad's REAL effective transform
    (angle == Eagle angle, mirror expressed as "(mirror y)").  Calibrated
    against KiCad SVG output; used only for bounding-box computation.

        delta = (a*lx + b*ly, c*lx + d*ly)
    """
    a, b, c, d = _TEFF[(int(krot) % 360, "y" if mirror else "none")]
    return (a * lx + b * ly, c * lx + d * ly)


# KiCad effective library->sheet transform (includes the built-in Y flip),
# calibrated from actual SVG output.  Key = (placement_angle, mirror_flag).
_TEFF: Dict[Tuple[int, str], Tuple[int, int, int, int]] = {
    (0,   "none"): (1, 0, 0, -1), (90,  "none"): (0, -1, -1, 0),
    (180, "none"): (-1, 0, 0, 1), (270, "none"): (0, 1, 1, 0),
    (0,   "y"): (-1, 0, 0, -1),   (90,  "y"): (0, 1, -1, 0),
    (180, "y"): (1, 0, 0, 1),     (270, "y"): (0, -1, 1, 0),
}

def _symbol_local_points(sg: "_EagleSymGeom") -> List[Tuple[float, float]]:
    """All extreme local points of a symbol (body + pin ends) for bbox use."""
    pts: List[Tuple[float, float]] = []
    for (x1, y1, x2, y2, *_rest) in sg.wires:
        pts.append((x1, y1)); pts.append((x2, y2))
    for (cx, cy, r) in sg.circles:
        pts += [(cx - r, cy - r), (cx + r, cy + r)]
    for (x1, y1, x2, y2) in sg.rectangles:
        pts += [(x1, y1), (x2, y2)]
    for poly in sg.polygons:
        pts += list(poly)
    for pin in sg.pins:
        pts.append((pin.x, pin.y))
        a = math.radians(pin.angle or 0.0)
        L = pin.length_mm or 0.0
        pts.append((pin.x + L * math.cos(a), pin.y + L * math.sin(a)))
    return pts


def _pin_lead(pin: "_EaglePin", indent: str) -> str:
    """Graphical lead line that replaces a pin's stub.

    Pins are emitted with length 0 so that KiCad's electrical connection point
    sits exactly on the pin origin (pin.x, pin.y) for *every* orientation —
    KiCad computes the connection point of a non-zero-length pin differently for
    vertical (90/270) vs. horizontal (0/180) pins, which left vertically drawn
    pins (power/GND symbols, rotated device pins) electrically unconnected even
    though the wire visually touched them.  The visible lead is preserved here
    as a plain polyline so symbols look identical.  Returns '' for zero length.
    """
    L = pin.length_mm or 0.0
    if L <= 0:
        return ""
    a = math.radians(pin.angle or 0.0)
    ex = pin.x + L * math.cos(a)
    ey = pin.y + L * math.sin(a)
    # Lead starts at the grid-snapped connection point (see pin emission below).
    sx = round(pin.x / _GRID_MM) * _GRID_MM
    sy = round(pin.y / _GRID_MM) * _GRID_MM
    return (f'{indent}(polyline (pts (xy {_fmt(sx)} {_fmt(sy)})'
            f' (xy {_fmt(ex)} {_fmt(ey)}))'
            f' (stroke (width 0) (type default)) (fill (type none)))\n')

# Standard KiCad paper sizes, landscape (name, width_mm, height_mm), small→large.
_PAPER_SIZES = [
    ("A4",  297.0, 210.0),
    ("A3",  420.0, 297.0),
    ("A2",  594.0, 420.0),
    ("A1",  841.0, 594.0),
    ("A0", 1189.0, 841.0),
]
_SHEET_MARGIN = 15.0   # mm clear border kept around the content
_GRID_MM      = 1.27   # KiCad default schematic grid (50 mil)
# Max distance (in grid steps) a net label may be moved onto its wire's free end
# / nearest segment when snapping. Kept as a module global so it can be tuned.
_LABEL_FE_STEPS  = 8.0
_LABEL_SEG_STEPS = 10.0


def _gridsnap(v: float) -> float:
    """Snap a single coordinate to the KiCad schematic grid."""
    return round(v / _GRID_MM) * _GRID_MM


def _trim_wires(
    wires: List[Tuple[float, float, float, float]],
    conn_pts: "set",
) -> List[Tuple[float, float, float, float]]:
    """Trim/remove dangling wire stubs left over from the Eagle source.

    Eagle frequently draws wires that overshoot their label or pin by a grid
    step (or leaves an isolated stub), which KiCad flags as an unconnected wire
    endpoint and which visually looks like a label/pin sitting off the wire.

    For every wire we gather its *anchor* points — connection points
    (pins/labels/junctions) lying on it plus points where another wire meets it.
    The wire is then shortened to span only between its outermost anchors, and a
    wire with fewer than two anchors (i.e. it bridges nothing) is dropped. This
    never disconnects two connection points: anchors are exactly the points that
    matter, and only empty overshoot beyond them is removed.
    """
    def key(x: float, y: float) -> Tuple[float, float]:
        return (round(x, 3), round(y, 3))

    def on_seg(pt: Tuple[float, float], seg: Tuple[float, float, float, float]) -> bool:
        x, y = pt
        x1, y1, x2, y2 = seg
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if abs(cross) > 1e-3:
            return False
        l2 = (x2 - x1) ** 2 + (y2 - y1) ** 2
        if l2 == 0:
            return abs(x - x1) < 1e-3 and abs(y - y1) < 1e-3
        t = ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) / l2
        return -1e-6 <= t <= 1 + 1e-6

    wires = [tuple(round(v, 3) for v in w) for w in wires]
    changed = True
    while changed:
        changed = False
        endcnt: Dict[Tuple[float, float], int] = {}
        for x1, y1, x2, y2 in wires:
            endcnt[key(x1, y1)] = endcnt.get(key(x1, y1), 0) + 1
            endcnt[key(x2, y2)] = endcnt.get(key(x2, y2), 0) + 1

        new_wires: List[Tuple[float, float, float, float]] = []
        for i, (x1, y1, x2, y2) in enumerate(wires):
            seg = (x1, y1, x2, y2)
            anchors: "set" = set()
            for cp in conn_pts:
                if on_seg(cp, seg):
                    anchors.add(key(cp[0], cp[1]))
            # endpoints supported by other wires (shared endpoint or T-contact)
            for j, other in enumerate(wires):
                if j == i:
                    continue
                for ep in ((other[0], other[1]), (other[2], other[3])):
                    if on_seg(ep, seg):
                        anchors.add(key(ep[0], ep[1]))
            # own endpoints only count as anchors if another wire meets there
            if endcnt[key(x1, y1)] >= 2:
                anchors.add(key(x1, y1))
            if endcnt[key(x2, y2)] >= 2:
                anchors.add(key(x2, y2))

            if len(anchors) < 2:
                changed = True          # pure stub / appendage → drop
                continue

            dx, dy = x2 - x1, y2 - y1
            l2 = dx * dx + dy * dy or 1.0
            ts = [((ax - x1) * dx + (ay - y1) * dy) / l2 for ax, ay in anchors]
            tmin, tmax = max(0.0, min(ts)), min(1.0, max(ts))
            nx1, ny1 = round(x1 + tmin * dx, 3), round(y1 + tmin * dy, 3)
            nx2, ny2 = round(x1 + tmax * dx, 3), round(y1 + tmax * dy, 3)
            if (nx1, ny1) == (nx2, ny2):
                changed = True          # collapsed to a point → drop
                continue
            nw = (nx1, ny1, nx2, ny2)
            if nw != seg:
                changed = True
            new_wires.append(nw)
        wires = new_wires
    return wires


def _choose_paper(w: float, h: float) -> Tuple[str, float, float]:
    """Smallest standard landscape sheet that fits w×h plus margins (fallback A0)."""
    for name, pw, ph in _PAPER_SIZES:
        if w + 2 * _SHEET_MARGIN <= pw and h + 2 * _SHEET_MARGIN <= ph:
            return name, pw, ph
    return _PAPER_SIZES[-1]

def _arc_segments(
    x1: float, y1: float, x2: float, y2: float, curve_deg: float
) -> List[Tuple[float, float, float, float]]:
    """
    Approximate an Eagle arc (chord + CCW angle) with line segments.
    Returns list of (sx, sy, ex, ey) in the SAME coordinate system (no Y-flip here).
    """
    alpha = math.radians(curve_deg)
    dx, dy = x2 - x1, y2 - y1
    chord = math.hypot(dx, dy)
    if chord < 1e-10 or abs(alpha) < 1e-10:
        return [(x1, y1, x2, y2)]
    mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    px, py = -dy / chord, dx / chord
    # distance from chord midpoint to arc centre
    try:
        d = chord / 2.0 / math.tan(alpha / 2.0)
    except ZeroDivisionError:
        return [(x1, y1, x2, y2)]
    cx, cy = mx + d * px, my + d * py
    r = math.hypot(x1 - cx, y1 - cy)
    ts = math.atan2(y1 - cy, x1 - cx)
    steps = max(3, int(abs(curve_deg) / 30.0))
    segs: List[Tuple[float, float, float, float]] = []
    for i in range(steps):
        a1 = ts + alpha * i / steps
        a2 = ts + alpha * (i + 1) / steps
        segs.append((
            cx + r * math.cos(a1), cy + r * math.sin(a1),
            cx + r * math.cos(a2), cy + r * math.sin(a2),
        ))
    return segs


# ── Eagle data containers ──────────────────────────────────────────────────────
class _EaglePin:
    """One pin as read from an Eagle symbol definition."""
    __slots__ = ("name", "x", "y", "length_mm", "direction", "angle")

    def __init__(self, el: ET.Element) -> None:
        self.name      = el.get("name", "?")
        self.x         = float(el.get("x", 0))
        self.y         = float(el.get("y", 0))
        self.length_mm = _PIN_LEN.get(el.get("length", "middle"), 5.08)
        self.direction = el.get("direction", "io")
        self.angle, _ = _parse_rot(el.get("rot", "R0"))


class _EagleSymGeom:
    """Complete geometry of one Eagle symbol (from a library)."""
    __slots__ = (
        "name", "kicad_id", "lib_name", "is_power", "ref_prefix",
        "wires",      # [(x1,y1,x2,y2, curve_deg|None), ...]
        "circles",    # [(cx, cy, radius), ...]
        "rectangles", # [(x1,y1,x2,y2), ...]
        "polygons",   # [[(x,y), ...], ...]
        "pins",       # [_EaglePin, ...]
        "pin_pads",   # {pin_name: pad_number}  (from deviceset <connect>)
    )

    def __init__(self, name: str, kicad_id: str, lib_name: str) -> None:
        self.name       = name
        self.kicad_id   = kicad_id
        self.lib_name   = lib_name
        self.is_power   = lib_name.lower() in _POWER_LIBS
        self.ref_prefix = "P" if self.is_power else "U"
        self.wires:      List[Tuple]            = []
        self.circles:    List[Tuple]            = []
        self.rectangles: List[Tuple]            = []
        self.polygons:   List[List[Tuple]]      = []
        self.pins:       List[_EaglePin]        = []
        self.pin_pads:   Dict[str, str]         = {}

    def pin_number(self, pin_name: str, index: int) -> str:
        """
        KiCad pin number for a pin.  Uses the physical pad from the Eagle
        <connect> map; falls back to a 1-based sequential number when the
        symbol has no pad mapping (e.g. power/supply symbols).
        """
        pad = self.pin_pads.get(pin_name)
        return pad if pad else str(index + 1)

    def with_pads(self, kicad_id: str, pin_pads: Dict[str, str]) -> "_EagleSymGeom":
        """
        Return a variant of this symbol that shares the geometry but carries
        its own pad map and kicad_id.  Needed because one Eagle symbol can be
        reused by several gates/devices with different pad numbers (connectors,
        resistor arrays, ...), which KiCad expresses as separate lib symbols.
        """
        v = _EagleSymGeom(self.name, kicad_id, self.lib_name)
        v.ref_prefix = self.ref_prefix
        v.wires      = self.wires
        v.circles    = self.circles
        v.rectangles = self.rectangles
        v.polygons   = self.polygons
        v.pins       = self.pins
        v.pin_pads   = dict(pin_pads)
        return v


class _EagleInst:
    """One gate placement on an Eagle schematic sheet (a part may have many)."""
    __slots__ = ("part", "gate", "x", "y", "angle", "mirror",
                 "sym_geom", "part_ref")

    def __init__(self, el: ET.Element) -> None:
        self.part  = el.get("part", "")
        self.gate  = el.get("gate", "G$1")
        self.x     = float(el.get("x", 0))
        self.y     = float(el.get("y", 0))
        self.angle, self.mirror = _parse_rot(el.get("rot", "R0"))
        self.sym_geom: Optional[_EagleSymGeom] = None
        self.part_ref: Optional[_EaglePart]    = None


class _EaglePart:
    """Eagle part (logical component: library + deviceset + device + value)."""
    __slots__ = ("name", "value", "lib_name", "ds_name", "device",
                 "is_power", "is_frame", "sym_geom")

    def __init__(self, el: ET.Element) -> None:
        self.name     = el.get("name", "")
        self.value    = el.get("value", "")
        self.lib_name = el.get("library", "")
        self.ds_name  = el.get("deviceset", "")
        self.device   = el.get("device", "")
        self.is_power = self.lib_name.lower() in _POWER_LIBS
        self.is_frame = self.ds_name.lower() in _FRAME_DEVICESETS
        self.sym_geom: Optional[_EagleSymGeom] = None


# ── Eagle XML parser ───────────────────────────────────────────────────────────
def parse_eagle_schematic(sch_path: str):
    """
    Parse an Eagle .sch XML file.

    Handles multi-sheet designs (sheets laid side-by-side) and multi-gate
    parts (each gate becomes its own placement).

    Returns
    -------
    parts      : dict  part_name → _EaglePart   (sym_geom filled in)
    instances  : list  of _EagleInst            (one per gate, all sheets)
    net_wires  : list  of (net_name, x1, y1, x2, y2)
    net_labels : list  of (net_name, x, y, angle_deg)
    junctions  : list  of (x, y)
    """
    root = ET.parse(sch_path).getroot()
    sch  = root.find("drawing/schematic")
    if sch is None:
        raise ValueError("Not an Eagle schematic (missing <drawing/schematic>)")

    # ── 1. Collect symbol geometry from embedded libraries ─────────────────
    # (lib_name, sym_name) → _EagleSymGeom
    sym_geoms: Dict[Tuple[str, str], _EagleSymGeom] = {}
    # (lib_name, ds_name, gate_name) → eagle_sym_name
    gate_to_sym: Dict[Tuple[str, str, str], str] = {}
    # (lib_name, ds_name, device_name, gate_name) → {pin_name: pad}
    connects: Dict[Tuple[str, str, str, str], Dict[str, str]] = {}

    # Dedup: track which kicad_ids are already in use
    used_kicad_ids: Dict[str, Tuple[str, str]] = {}   # kicad_id → (lib, sym)

    for lib in sch.findall("libraries/library"):
        lib_name = lib.get("name", "")

        # -- symbols --
        for sym_el in lib.findall("symbols/symbol"):
            sym_name = sym_el.get("name", "")
            kicad_id = f"eagle_import:{_sanitize(sym_name)}"
            if kicad_id in used_kicad_ids and used_kicad_ids[kicad_id] != (lib_name, sym_name):
                kicad_id = f"eagle_import:{_sanitize(lib_name)}_{_sanitize(sym_name)}"
            used_kicad_ids[kicad_id] = (lib_name, sym_name)

            sg = _EagleSymGeom(sym_name, kicad_id, lib_name)

            for w in sym_el.findall("wire"):
                try:
                    curve_s = w.get("curve")
                    sg.wires.append((
                        float(w.get("x1", 0)), float(w.get("y1", 0)),
                        float(w.get("x2", 0)), float(w.get("y2", 0)),
                        float(curve_s) if curve_s else None,
                    ))
                except (ValueError, TypeError):
                    pass

            for c in sym_el.findall("circle"):
                try:
                    sg.circles.append((
                        float(c.get("x", 0)), float(c.get("y", 0)),
                        float(c.get("radius", 0)),
                    ))
                except (ValueError, TypeError):
                    pass

            for r in sym_el.findall("rectangle"):
                try:
                    sg.rectangles.append((
                        float(r.get("x1", 0)), float(r.get("y1", 0)),
                        float(r.get("x2", 0)), float(r.get("y2", 0)),
                    ))
                except (ValueError, TypeError):
                    pass

            for poly in sym_el.findall("polygon"):
                verts: List[Tuple[float, float]] = []
                for v in poly.findall("vertex"):
                    try:
                        verts.append((float(v.get("x", 0)), float(v.get("y", 0))))
                    except (ValueError, TypeError):
                        pass
                if len(verts) >= 2:
                    sg.polygons.append(verts)

            sg.pins = [_EaglePin(p) for p in sym_el.findall("pin")]
            sym_geoms[(lib_name, sym_name)] = sg

        # -- devicesets: gate→symbol map, ref prefix, and per-device pad maps --
        for ds in lib.findall("devicesets/deviceset"):
            ds_name = ds.get("name", "")
            prefix  = ds.get("prefix", "U")

            for gate in ds.findall("gates/gate"):
                gate_name = gate.get("name", "")
                sym_name  = gate.get("symbol", "")
                gate_to_sym[(lib_name, ds_name, gate_name)] = sym_name
                sg = sym_geoms.get((lib_name, sym_name))
                if sg:
                    sg.ref_prefix = prefix

            # Pad map per (device, gate): {(dev_name, gate): {pin: pad}}
            for dev in ds.findall("devices/device"):
                dev_name = dev.get("name", "")
                for con in dev.findall("connects/connect"):
                    g   = con.get("gate", "")
                    pin = con.get("pin", "")
                    pad = con.get("pad", "")
                    if g and pin and pad:
                        connects.setdefault((lib_name, ds_name, dev_name, g), {})[pin] = pad

    # ── 2. Parse parts ─────────────────────────────────────────────────────
    parts: Dict[str, _EaglePart] = {}
    for el in sch.findall("parts/part"):
        p = _EaglePart(el)
        parts[p.name] = p

    # ── 3+4. Parse ALL sheets: instances (one per gate) + nets ─────────────
    # Each Eagle sheet is laid out side-by-side in X so nothing overlaps.
    instances:  List[_EagleInst]                             = []
    net_wires:  List[Tuple[str, float, float, float, float]] = []
    net_labels: List[Tuple[str, float, float, float]]        = []
    junctions:  List[Tuple[float, float]]                    = []

    # Variant cache: (lib, sym, pad_signature) → _EagleSymGeom (with pad map)
    variant_geoms: Dict[Tuple[str, str, Tuple], _EagleSymGeom] = {}
    # base kicad_id → number of distinct variants seen (for id suffixing)
    variant_count: Dict[str, int] = {}

    def _resolve_pads(part: _EaglePart, gate: str, sym_name: str) -> Dict[str, str]:
        key = (part.lib_name, part.ds_name, part.device, gate)
        if key in connects:
            return connects[key]
        # Fallback: any device of this deviceset/gate that has a pad map
        for (ln, dn, _dev, g), pads in connects.items():
            if ln == part.lib_name and dn == part.ds_name and g == gate:
                return pads
        return {}

    def _resolve_geom(part: _EaglePart, gate: str) -> Optional[_EagleSymGeom]:
        sym_name = gate_to_sym.get((part.lib_name, part.ds_name, gate), "")
        if not sym_name:
            # Fallback: first gate defined for this library+deviceset
            for (ln, dn, _), sn in gate_to_sym.items():
                if ln == part.lib_name and dn == part.ds_name:
                    sym_name = sn
                    break
        base = sym_geoms.get((part.lib_name, sym_name)) if sym_name else None
        if base is None:
            return None

        pads = _resolve_pads(part, gate, sym_name)
        sig  = tuple(sorted(pads.items()))
        vkey = (part.lib_name, sym_name, sig)
        if vkey in variant_geoms:
            return variant_geoms[vkey]

        # First variant for this base symbol keeps the base id; later distinct
        # pad maps get a numeric suffix so KiCad sees them as separate symbols.
        n = variant_count.get(base.kicad_id, 0)
        kid = base.kicad_id if n == 0 else f"{base.kicad_id}_{n + 1}"
        variant_count[base.kicad_id] = n + 1

        variant = base.with_pads(kid, pads)
        variant_geoms[vkey] = variant
        return variant

    SHEET_DX = 500.0  # mm between successive sheets in the merged KiCad sheet

    for si, sheet in enumerate(sch.findall("sheets/sheet")):
        dx = si * SHEET_DX

        # -- instances (each gate is its own placement) --
        for el in sheet.findall("instances/instance"):
            inst = _EagleInst(el)
            inst.x += dx
            part = parts.get(inst.part)
            inst.part_ref = part
            if part and not part.is_frame:
                inst.sym_geom = _resolve_geom(part, inst.gate)
                # Record on the part too (used for value/metadata lookups)
                if part.sym_geom is None and inst.sym_geom is not None:
                    part.sym_geom = inst.sym_geom
            instances.append(inst)

        # -- nets --
        for net in sheet.findall("nets/net"):
            net_name = net.get("name", "")
            for seg in net.findall("segment"):
                for w in seg.findall("wire"):
                    try:
                        net_wires.append((
                            net_name,
                            float(w.get("x1", 0)) + dx, float(w.get("y1", 0)),
                            float(w.get("x2", 0)) + dx, float(w.get("y2", 0)),
                        ))
                    except (ValueError, TypeError):
                        pass
                for lbl in seg.findall("label"):
                    try:
                        angle, _ = _parse_rot(lbl.get("rot", "R0"))
                        net_labels.append((
                            net_name,
                            float(lbl.get("x", 0)) + dx,
                            float(lbl.get("y", 0)),
                            angle,
                        ))
                    except (ValueError, TypeError):
                        pass
                for junc in seg.findall("junction"):
                    try:
                        junctions.append((
                            float(junc.get("x", 0)) + dx,
                            float(junc.get("y", 0)),
                        ))
                    except (ValueError, TypeError):
                        pass

    return parts, instances, net_wires, net_labels, junctions


# ── KiCad lib_symbol generator ─────────────────────────────────────────────────
def _baked_kicad_id(sg: "_EagleSymGeom", krot: int) -> str:
    """lib_id for the rotation/mirror-baked variant of a symbol."""
    return f"{sg.kicad_id}__m{int(krot) % 360}"

def _bake_xform(krot: int):
    """Return an (x, y) -> (x, y) transform that bakes a mirrored instance's
    (rotation krot + mirror-y) placement into the symbol geometry, so the
    instance can be placed with an identity transform (at x y 0, no mirror).

    Placing the baked symbol at (origin, 0, no-mirror) makes KiCad apply the
    identity library transform _TEFF[(0,"none")] = (1,0,0,-1); we therefore
    store (dx, -dy) where (dx, dy) is the sheet-space offset the original
    mirrored placement would have produced.  KiCad cannot electrically connect
    wires to pins on mirrored symbols, so eliminating the mirror flag is what
    makes those nets connect.
    """
    def _x(lx: float, ly: float) -> Tuple[float, float]:
        dx, dy = _render_local(lx, ly, krot, True)
        return (dx, -dy)
    return _x

def _gen_lib_symbol(sg: _EagleSymGeom, xform=None, name_id: str = None) -> str:
    """
    Generate the KiCad lib_symbol S-expression for an Eagle symbol.

    Key rule: Eagle lib-symbols and KiCad lib-symbols both use Y-up,
    so no Y coordinate flip is needed inside the symbol definition.
    Pin angles are also kept as-is (both use CCW from +X).

    When ``xform`` is given (used for mirrored instances) every geometry point
    and pin position is passed through it, producing a "baked" variant named
    ``name_id`` that is placed with an identity instance transform.
    """
    # Sub-symbol names MUST start with the parent symbol's leaf name (the
    # part after the ':' in the lib_id).  The dedup logic may prefix the
    # kicad_id with the library name, so derive the leaf from kicad_id — not
    # from sg.name — otherwise KiCad rejects the mismatched sub-symbol.
    kid   = name_id or sg.kicad_id
    leaf  = kid.split(":")[-1]
    ref   = _escape(sg.ref_prefix or "U")
    sym   = _escape(kid)
    power = "\n      (power)" if sg.is_power else ""
    hide  = (' (pin_numbers (hide yes)) (pin_names (hide yes))'
             if (sg.is_power or (sg.ref_prefix or "").upper() in _PASSIVE_PREFIXES)
             else '')

    def T(x: float, y: float) -> Tuple[float, float]:
        return xform(x, y) if xform else (x, y)

    L: List[str] = []
    L.append(f'    (symbol "{sym}"{hide} (in_bom yes) (on_board yes){power}\n')
    L.append(f'      (property "Reference" "{ref}" (at 0 0 0)'
             f'\n        (effects (font (size 1.27 1.27))))\n')
    L.append(f'      (property "Value" "{_escape(sg.name)}" (at 0 0 0)'
             f'\n        (effects (font (size 1.27 1.27))))\n')
    L.append(f'      (property "Footprint" "" (at 0 0 0)'
             f'\n        (effects (font (size 1.27 1.27)) hide))\n')
    L.append(f'      (property "Datasheet" "" (at 0 0 0)'
             f'\n        (effects (font (size 1.27 1.27)) hide))\n')

    # ── Drawing body in sub-symbol _0_1 ─────────────────────────────────
    L.append(f'      (symbol "{_escape(leaf)}_0_1"\n')

    def _polyline(points: List[Tuple[float, float]], fill: str = "none") -> str:
        pts = " ".join(f"(xy {_fmt(x)} {_fmt(y)})" for x, y in points)
        return (f'        (polyline (pts {pts})'
                f' (stroke (width 0) (type default)) (fill (type {fill})))\n')

    for x1, y1, x2, y2, curve in sg.wires:
        if curve is not None:
            # Approximate arc with polyline segments (segment first, then bake).
            for sx, sy, ex, ey in _arc_segments(x1, y1, x2, y2, curve):
                L.append(_polyline([T(sx, sy), T(ex, ey)]))
        else:
            L.append(_polyline([T(x1, y1), T(x2, y2)]))

    for cx, cy, r in sg.circles:
        tcx, tcy = T(cx, cy)
        L.append(
            f'        (circle (center {_fmt(tcx)} {_fmt(tcy)}) (radius {_fmt(r)})'
            f' (stroke (width 0) (type default)) (fill (type none)))\n'
        )

    for x1, y1, x2, y2 in sg.rectangles:
        if xform is None:
            L.append(
                f'        (rectangle (start {_fmt(x1)} {_fmt(y1)})'
                f' (end {_fmt(x2)} {_fmt(y2)})'
                f' (stroke (width 0) (type default)) (fill (type none)))\n'
            )
        else:
            # A rotated/mirrored rectangle is no longer axis-aligned → polyline.
            L.append(_polyline(
                [T(x1, y1), T(x2, y1), T(x2, y2), T(x1, y2), T(x1, y1)]))

    for verts in sg.polygons:
        tv = [T(x, y) for x, y in verts]
        L.append(_polyline(tv + [tv[0]], fill="outline"))

    # Visible pin leads (pins themselves are emitted with length 0 below).
    # The lead starts at the grid-snapped pin connection point so it stays
    # visually attached to the (snapped) pin marker.
    def _gsnap(pt: Tuple[float, float]) -> Tuple[float, float]:
        return (round(pt[0] / _GRID_MM) * _GRID_MM,
                round(pt[1] / _GRID_MM) * _GRID_MM)

    for pin in sg.pins:
        L2 = pin.length_mm or 0.0
        if L2 <= 0:
            continue
        a = math.radians(pin.angle or 0.0)
        p0 = _gsnap(T(pin.x, pin.y))
        p1 = T(pin.x + L2 * math.cos(a), pin.y + L2 * math.sin(a))
        L.append(_polyline([p0, p1]))

    L.append('      )\n')

    # ── Pins in sub-symbol _1_1 ──────────────────────────────────────────
    L.append(f'      (symbol "{_escape(leaf)}_1_1"\n')

    for idx, pin in enumerate(sg.pins):
        ptype = _PIN_TYPE.get(pin.direction.lower(), "bidirectional")
        number = sg.pin_number(pin.name, idx)
        # Snap the (length-0) electrical connection point to the schematic grid.
        # Most Eagle symbols already define pins on-grid (no-op); a few (e.g. the
        # N-MOSFET symbol) place pins off-grid. Instance origins and wires are
        # grid-snapped as well, and grid snapping is invariant under whole-grid
        # shifts, so the pin and the wire that meets it still coincide.
        pax, pay = _gsnap(T(pin.x, pin.y))
        # Pin orientation only affects the (hidden, zero-length) pin marker and
        # name placement; bake it so it still points along the drawn lead.
        pang = int(pin.angle % 360)
        if xform is not None:
            a = math.radians(pin.angle or 0.0)
            bx, by = T(pin.x + math.cos(a), pin.y + math.sin(a))
            pang = int(round(math.degrees(math.atan2(by - pay, bx - pax))) % 360)
            pang = (pang // 90) * 90
        # Pins are length 0 so KiCad's connection point is exactly the pin
        # position for all orientations; the drawn lead is added to the body.
        L.append(
            f'        (pin {ptype} line'
            f' (at {_fmt(pax)} {_fmt(pay)} {pang})'
            f' (length 0)\n'
            f'          (name "{_escape(pin.name)}" (effects (font (size 1.016 1.016))))\n'
            f'          (number "{_escape(number)}" (effects (font (size 1.016 1.016)))))\n'
        )

    L.append('      )\n')
    L.append('    )\n')
    return "".join(L)


# ── KiCad symbol library generator (.kicad_sym) ────────────────────────────────
def generate_sym_lib(sym_geoms: List["_EagleSymGeom"], lib_path: str) -> None:
    """
    Write a stand-alone KiCad symbol library (.kicad_sym) from a list of
    Eagle symbol geometries.

    The library nickname used in the schematic is "eagle_import" (matching the
    lib_id prefix "eagle_import:SYMBOLNAME").  A matching sym-lib-table entry
    lets KiCad resolve the symbols both from the embedded lib_symbols section
    and from this library file.
    """
    out: List[str] = []
    out.append('(kicad_symbol_lib (version 20250114)'
               ' (generator "kicad_symbol_editor")\n')

    for sg in sym_geoms:
        # In a .kicad_sym file the symbol name has NO library prefix — the
        # prefix comes from the library nickname in sym-lib-table.  Use the
        # kicad_id leaf (after ':') so the name matches what the schematic
        # references (eagle_import:<leaf>) and stays unique across libraries.
        leaf  = sg.kicad_id.split(":")[-1]
        power = "\n  (power)" if sg.is_power else ""
        ref   = _escape(sg.ref_prefix or "U")
        name  = _escape(leaf)
        hide  = (' (pin_numbers (hide yes)) (pin_names (hide yes))'
                 if (sg.is_power or (sg.ref_prefix or "").upper() in _PASSIVE_PREFIXES)
                 else '')

        out.append(f'  (symbol "{name}"{hide} (in_bom yes) (on_board yes){power}\n')
        out.append(f'    (property "Reference" "{ref}" (at 0 0 0)'
                   f'\n      (effects (font (size 1.27 1.27))))\n')
        out.append(f'    (property "Value" "{name}" (at 0 0 0)'
                   f'\n      (effects (font (size 1.27 1.27))))\n')
        out.append(f'    (property "Footprint" "" (at 0 0 0)'
                   f'\n      (effects (font (size 1.27 1.27)) hide))\n')
        out.append(f'    (property "Datasheet" "" (at 0 0 0)'
                   f'\n      (effects (font (size 1.27 1.27)) hide))\n')

        # ── Drawing body ──────────────────────────────────────────────
        out.append(f'    (symbol "{_escape(leaf)}_0_1"\n')

        for x1, y1, x2, y2, curve in sg.wires:
            if curve is not None:
                for sx, sy, ex, ey in _arc_segments(x1, y1, x2, y2, curve):
                    out.append(
                        f'      (polyline (pts (xy {_fmt(sx)} {_fmt(sy)})'
                        f' (xy {_fmt(ex)} {_fmt(ey)}))'
                        f' (stroke (width 0) (type default)) (fill (type none)))\n'
                    )
            else:
                out.append(
                    f'      (polyline (pts (xy {_fmt(x1)} {_fmt(y1)})'
                    f' (xy {_fmt(x2)} {_fmt(y2)}))'
                    f' (stroke (width 0) (type default)) (fill (type none)))\n'
                )

        for cx, cy, r in sg.circles:
            out.append(
                f'      (circle (center {_fmt(cx)} {_fmt(cy)}) (radius {_fmt(r)})'
                f' (stroke (width 0) (type default)) (fill (type none)))\n'
            )

        for x1, y1, x2, y2 in sg.rectangles:
            out.append(
                f'      (rectangle (start {_fmt(x1)} {_fmt(y1)})'
                f' (end {_fmt(x2)} {_fmt(y2)})'
                f' (stroke (width 0) (type default)) (fill (type none)))\n'
            )

        for verts in sg.polygons:
            pts = " ".join(f"(xy {_fmt(x)} {_fmt(y)})" for x, y in verts)
            pts += f" (xy {_fmt(verts[0][0])} {_fmt(verts[0][1])})"
            out.append(
                f'      (polyline (pts {pts})'
                f' (stroke (width 0) (type default)) (fill (type outline)))\n'
            )

        # Visible pin leads (pins themselves are emitted with length 0 below).
        for pin in sg.pins:
            out.append(_pin_lead(pin, '      '))

        out.append('    )\n')

        # ── Pins ─────────────────────────────────────────────────────
        out.append(f'    (symbol "{_escape(leaf)}_1_1"\n')
        for idx, pin in enumerate(sg.pins):
            ptype = _PIN_TYPE.get(pin.direction.lower(), "bidirectional")
            number = sg.pin_number(pin.name, idx)
            # Snap the length-0 connection point to the schematic grid so library
            # pins stay grid-aligned (matches the schematic's embedded symbols).
            spx = round(pin.x / _GRID_MM) * _GRID_MM
            spy = round(pin.y / _GRID_MM) * _GRID_MM
            out.append(
                f'      (pin {ptype} line'
                f' (at {_fmt(spx)} {_fmt(spy)} {int(pin.angle % 360)})'
                f' (length 0)\n'
                f'        (name "{_escape(pin.name)}"'
                f' (effects (font (size 1.016 1.016))))\n'
                f'        (number "{_escape(number)}"'
                f' (effects (font (size 1.016 1.016)))))\n'
            )
        out.append('    )\n')
        out.append('  )\n')

    out.append(')\n')
    os.makedirs(os.path.dirname(os.path.abspath(lib_path)), exist_ok=True)
    with open(lib_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(out)


def generate_sym_lib_table(project_dir: str, lib_filename: str) -> None:
    """
    Write a project-level sym-lib-table so KiCad can resolve
    'eagle_import:SYMBOLNAME' lib-ids from the local .kicad_sym file.
    """
    table_path = os.path.join(project_dir, "sym-lib-table")
    content = (
        "(sym_lib_table\n"
        f'  (lib (name "eagle_import") (type "KiCad")'
        f' (uri "${{KIPRJMOD}}/{lib_filename}")'
        f' (options "") (descr "Eagle imported symbols"))\n'
        ")\n"
    )
    with open(table_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


# ── KiCad schematic generator ──────────────────────────────────────────────────
def generate_kicad_sch(
    parts:      Dict[str, _EaglePart],
    instances:  List[_EagleInst],
    net_wires:  List[Tuple[str, float, float, float, float]],
    net_labels: List[Tuple[str, float, float, float]],
    junctions:  List[Tuple[float, float]],
    output_path: str,
) -> str:
    """
    Write a .kicad_sch from parsed Eagle data.
    Returns the schematic UUID string.
    """
    # Y offset: flip Eagle Y (Y-up) to KiCad Y (Y-down).  Snap the base to the
    # grid so that everything on-grid in Eagle also lands on KiCad's grid.
    all_ys = [inst.y for inst in instances]
    y_off  = round(((max(all_ys) if all_ys else 200.0) + 20.0) / _GRID_MM) * _GRID_MM

    def ky(y: float) -> float:
        """Eagle schematic Y → KiCad schematic Y."""
        return y_off - y

    # ── Collect the lib_symbols we need (from every gate instance) ──────
    needed: Dict[str, _EagleSymGeom] = {}
    for inst in instances:
        sg = inst.sym_geom
        if sg is not None and sg.kicad_id not in needed:
            needed[sg.kicad_id] = sg

    # ── Pre-pass: content bounding box (symbol geometry + wires/labels) ──
    bxs: List[float] = []
    bys: List[float] = []
    for inst in instances:
        part = inst.part_ref
        if part is None or part.is_frame or inst.sym_geom is None:
            continue
        krot = _krot(inst.angle, inst.mirror)
        ox0, oy0 = inst.x, ky(inst.y)
        for lx, ly in _symbol_local_points(inst.sym_geom):
            dx, dy = _render_local(lx, ly, krot, inst.mirror)
            bxs.append(ox0 + dx); bys.append(oy0 + dy)
    for _n, x1, y1, x2, y2 in net_wires:
        bxs += [x1, x2]; bys += [ky(y1), ky(y2)]
    for jx, jy in junctions:
        bxs.append(jx); bys.append(ky(jy))
    for _n, lx, ly, _a in net_labels:
        bxs.append(lx); bys.append(ky(ly))

    if bxs:
        min_x, max_x = min(bxs), max(bxs)
        min_y, max_y = min(bys), max(bys)
    else:
        min_x = max_x = min_y = max_y = 0.0
    content_w, content_h = max_x - min_x, max_y - min_y

    # Pick a sheet that fits, then centre the content on it (grid-snapped).
    paper, pw, ph = _choose_paper(content_w, content_h)
    ox = round((pw / 2.0 - (min_x + max_x) / 2.0) / _GRID_MM) * _GRID_MM
    oy = round((ph / 2.0 - (min_y + max_y) / 2.0) / _GRID_MM) * _GRID_MM

    def px(x: float) -> float:
        """Final KiCad X: apply centring offset, snapped to the schematic grid.

        Some Eagle sources place parts (and their wires) off the 1.27 mm grid.
        Snapping every emitted coordinate to the grid is safe for connectivity:
        rounding is invariant under integer-grid shifts, and every symbol's pin
        offsets are whole grid multiples, so a pin and the wire endpoint that
        touched it (identical Eagle coordinates) always snap to the same grid
        node and stay electrically connected.
        """
        return round((x + ox) / _GRID_MM) * _GRID_MM

    def py(y_kicad: float) -> float:
        """Final KiCad Y (input already Y-flipped): centring offset + grid snap."""
        return round((y_kicad + oy) / _GRID_MM) * _GRID_MM

    # ── Write schematic ─────────────────────────────────────────────────
    sch_uuid = _uid()
    out: List[str] = []

    out.append(f'(kicad_sch (version 20250114) (generator "KiCAD Schematic Editor")\n\n')
    out.append(f'  (uuid {sch_uuid})\n\n')
    out.append(f'  (paper "{paper}")\n\n')

    # lib_symbols section
    out.append("  (lib_symbols\n")
    for sg in needed.values():
        out.append(_gen_lib_symbol(sg))
    # Baked (rotation+mirror) variants for mirrored instances.  KiCad cannot
    # electrically connect wires to pins on mirrored symbols, so mirrored
    # placements reference a geometry-baked variant placed with an identity
    # instance transform (at x y 0, no mirror) instead.
    baked_needed: Dict[str, Tuple[_EagleSymGeom, int]] = {}
    for inst in instances:
        if inst.mirror and inst.sym_geom is not None:
            krot = _krot(inst.angle, inst.mirror)
            bid = _baked_kicad_id(inst.sym_geom, krot)
            if bid not in baked_needed:
                baked_needed[bid] = (inst.sym_geom, krot)
    for bid, (sg, krot) in baked_needed.items():
        out.append(_gen_lib_symbol(sg, xform=_bake_xform(krot), name_id=bid))
    out.append("  )\n\n")

    # Component placements — one KiCad symbol per Eagle gate instance
    pin_world_pts: List[Tuple[float, float]] = []   # every pin's connection point
    pwr_counter = 0
    for inst in instances:
        part = inst.part_ref
        if part is None or part.is_frame or inst.sym_geom is None:
            continue
        sg = inst.sym_geom

        kx   = px(inst.x)
        kycmp = py(ky(inst.y))

        krot = _krot(inst.angle, inst.mirror)
        # Mirrored instances reference a geometry-baked variant and are placed
        # with an identity transform so wires can connect to their pins.
        if inst.mirror:
            lib_id_use  = _baked_kicad_id(sg, krot)
            place_rot   = 0
        else:
            lib_id_use  = sg.kicad_id
            place_rot   = krot
        mirror_field = ""

        # Rendered bounding box of this instance (delta from its origin) so the
        # Reference/Value labels can be placed clear of the symbol body instead
        # of a fixed origin offset that lands inside large/rotated symbols.
        _pts = [_render_local(lx, ly, krot, inst.mirror)
                for lx, ly in _symbol_local_points(sg)]
        if _pts:
            _dxs = [p[0] for p in _pts]; _dys = [p[1] for p in _pts]
            bb_min_x, bb_max_x = min(_dxs), max(_dxs)
            bb_top, bb_bot = min(_dys), max(_dys)
        else:
            bb_min_x, bb_max_x = -1.27, 1.27
            bb_top, bb_bot = -1.27, 1.27
        bb_cx = (bb_min_x + bb_max_x) / 2.0
        bb_cy = (bb_top + bb_bot) / 2.0

        # Two-terminal R/L/C and diodes/LEDs drawn vertically: the top/bottom of
        # the body are the pin ends (with wires attached), so put the labels to the
        # SIDES instead — Reference on the left, Value on the right — off the wires.
        # Use the actual designator prefix (what the user sees) so diodes whose
        # deviceset prefix is generic (e.g. "U") are still recognised.
        _refm = re.match(r"[A-Za-z]+", part.name or "")
        _desig_pfx = _refm.group(0).upper() if _refm else (sg.ref_prefix or "").upper()
        is_passive = _desig_pfx in _VERT_LABEL_PREFIXES
        # "Vertical" is decided by the actual pin geometry (pins stacked
        # top/bottom), which is exactly what makes an R/L/C look vertical, rather
        # than the symbol's bounding-box aspect (electrolytic caps etc. can have a
        # wide body yet vertical pins).  The pin midpoint is the true body centre,
        # so we centre the rotated labels on it even for asymmetric symbols.
        _pin_r = [_render_local(pp.x, pp.y, krot, inst.mirror) for pp in sg.pins]
        if len(_pin_r) >= 2:
            _pxs = [p[0] for p in _pin_r]; _pys = [p[1] for p in _pin_r]
            vertical = (max(_pys) - min(_pys)) > (max(_pxs) - min(_pxs))
            pin_cx = (min(_pxs) + max(_pxs)) / 2.0
            pin_cy = (min(_pys) + max(_pys)) / 2.0
        else:
            vertical = (bb_bot - bb_top) > (bb_max_x - bb_min_x)
            pin_cx, pin_cy = bb_cx, bb_cy
        ref_just = ""
        val_just = ""
        ref_rot  = 0
        val_rot  = 0
        if is_passive and vertical:
            # Vertical R/L/C: rotate the Reference/Value text 90° so it runs
            # alongside the body (KiCad's own convention), Reference on the left
            # and Value on the right, both centred on the component body.
            #
            # KiCad ADDS the symbol instance's placement rotation to a property's
            # text angle, so to make the text land vertical on the sheet the stored
            # angle must compensate for place_rot (e.g. an instance placed at 90°
            # needs a stored 0° to display vertically). Mirror-baked variants are
            # placed at place_rot 0, so they simply store 90°.
            ref_px = px(inst.x + bb_min_x - 1.27); ref_py = py(ky(inst.y) + pin_cy)
            val_px = px(inst.x + bb_max_x + 1.27); val_py = py(ky(inst.y) + pin_cy)
            ref_rot = (90 - place_rot) % 180
            val_rot = (90 - place_rot) % 180
        else:
            ref_px = px(inst.x + bb_cx); ref_py = py(ky(inst.y) + bb_top - 1.27)
            val_px = px(inst.x + bb_cx); val_py = py(ky(inst.y) + bb_bot + 1.27)

        if part.is_power:
            pwr_counter += 1
            ref_val          = f"#PWR{pwr_counter:04d}"
            in_bom, on_board = "no", "no"
        else:
            ref_val          = part.name
            in_bom, on_board = "yes", "yes"

        val_str = part.value or sg.name

        out.append(
            f'  (symbol (lib_id "{_escape(lib_id_use)}")'
            f' (at {_fmt(kx)} {_fmt(kycmp)} {place_rot}){mirror_field} (unit 1)\n'
            f'    (in_bom {in_bom}) (on_board {on_board}) (dnp no)'
            f' (uuid {_uid()})\n'
        )
        # Power-symbol references (#PWR…) are auto-generated and carry no useful
        # information, so keep them hidden like KiCad's own power symbols do.
        ref_hide = " hide" if part.is_power else ""
        out.append(
            f'    (property "Reference" "{_escape(ref_val)}"'
            f' (at {_fmt(ref_px)} {_fmt(ref_py)} {ref_rot})\n'
            f'      (effects (font (size 1.27 1.27)){ref_just}{ref_hide}))\n'
        )
        out.append(
            f'    (property "Value" "{_escape(val_str)}"'
            f' (at {_fmt(val_px)} {_fmt(val_py)} {val_rot})\n'
            f'      (effects (font (size 1.27 1.27)){val_just}))\n'
        )
        out.append(
            f'    (property "Footprint" ""'
            f' (at {_fmt(kx)} {_fmt(kycmp)} 0)\n'
            f'      (effects (font (size 1.27 1.27)) hide))\n'
        )
        out.append(
            f'    (property "Datasheet" "~"'
            f' (at {_fmt(kx)} {_fmt(kycmp)} 0)\n'
            f'      (effects (font (size 1.27 1.27)) hide))\n'
        )
        # Pin UUID entries (KiCad references pins here by NUMBER, not name)
        for idx, pin in enumerate(sg.pins):
            number = sg.pin_number(pin.name, idx)
            out.append(f'    (pin "{_escape(number)}" (uuid {_uid()}))\n')
        out.append('  )\n\n')

        # Record each pin's electrical connection point in KiCad space (matches
        # the length-0 pin emitted in the lib symbol), used to trim dangling wire
        # stubs later.  Mirrored instances use the geometry-baked variant.
        _bx = _bake_xform(krot) if inst.mirror else None
        _pa = math.radians(place_rot)
        _ca, _sa = math.cos(_pa), math.sin(_pa)
        for pin in sg.pins:
            _lx, _ly = (_bx(pin.x, pin.y) if _bx else (pin.x, pin.y))
            _lx, _ly = _gridsnap(_lx), _gridsnap(_ly)
            _wx = kx + (_lx * _ca - _ly * _sa)
            _wy = kycmp - (_lx * _sa + _ly * _ca)
            pin_world_pts.append((round(_wx, 3), round(_wy, 3)))

    # ── Net labels: move each label ONTO its net's wire ─────────────────
    # Eagle attaches a label to a net by segment membership, so the label anchor
    # may float a grid step or two off the actual wire. KiCad only treats a label
    # as connected when its anchor lies exactly on a wire/pin, so the label is
    # *moved onto* the wire (in Eagle space, before the page transform, so it stays
    # grid-aligned) — the wire is never moved to the label. We prefer the wire's
    # nearest free end (a clean terminus) and rotate/justify the text to run
    # outward from the wire so it never sits on top of it.
    _wires_by_net: Dict[str, List[Tuple[float, float, float, float]]] = {}
    for _nn, _x1, _y1, _x2, _y2 in net_wires:
        _wires_by_net.setdefault(_nn, []).append((_x1, _y1, _x2, _y2))

    # Per-net free ends (degree-1 endpoints) with the neighbour they connect to.
    _free_ends_by_net: Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]] = {}
    for _nn, _segs in _wires_by_net.items():
        _deg: Dict[Tuple[float, float], int] = {}
        _nbr: Dict[Tuple[float, float], Tuple[float, float]] = {}
        for _x1, _y1, _x2, _y2 in _segs:
            _a = (round(_x1, 4), round(_y1, 4)); _b = (round(_x2, 4), round(_y2, 4))
            _deg[_a] = _deg.get(_a, 0) + 1; _deg[_b] = _deg.get(_b, 0) + 1
            _nbr[_a] = _b; _nbr[_b] = _a
        _free_ends_by_net[_nn] = [(p, _nbr[p]) for p, d in _deg.items() if d == 1]

    def _snap_to_net(name: str, lx: float, ly: float):
        """Snap a label onto its net's wire.

        Returns (sx, sy, dx, dy) in Eagle space, where (dx, dy) is the direction
        the incident wire leaves the snap point (0,0 if unknown).
        """
        segs = _wires_by_net.get(name)
        if not segs:
            return lx, ly, 0.0, 0.0
        # 1) Prefer the nearest free end (clean terminus, kills the overshoot stub).
        best_fe = None
        for (ex, ey), (ox, oy) in _free_ends_by_net.get(name, []):
            d2 = (lx - ex) ** 2 + (ly - ey) ** 2
            if best_fe is None or d2 < best_fe[0]:
                best_fe = (d2, ex, ey, ox, oy)
        if best_fe is not None and best_fe[0] <= (_LABEL_FE_STEPS * _GRID_MM) ** 2:
            _, ex, ey, ox, oy = best_fe
            return ex, ey, ox - ex, oy - ey
        # 2) Otherwise project onto the nearest wire segment of the same net.
        best = None
        for x1, y1, x2, y2 in segs:
            dx, dy = x2 - x1, y2 - y1
            seg_len2 = dx * dx + dy * dy
            if seg_len2 == 0:
                qx, qy = x1, y1
            else:
                t = ((lx - x1) * dx + (ly - y1) * dy) / seg_len2
                t = max(0.0, min(1.0, t))
                qx, qy = x1 + t * dx, y1 + t * dy
            d2 = (lx - qx) ** 2 + (ly - qy) ** 2
            if best is None or d2 < best[0]:
                best = (d2, qx, qy, dx, dy)
        if best is not None and best[0] <= (_LABEL_SEG_STEPS * _GRID_MM) ** 2:
            _, qx, qy, dx, dy = best
            return qx, qy, dx, dy
        return lx, ly, 0.0, 0.0

    # Final label placement in KiCad space, with outward-pointing justification.
    snapped_labels: List[Tuple[str, float, float, int, str]] = []
    for net_name, lx, ly, angle in net_labels:
        slx, sly, dxe, dye = _snap_to_net(net_name, lx, ly)
        kdx, kdy = dxe, -dye                      # wire direction in KiCad space
        # A label has two justify axes. The vertical axis is always "bottom"; the
        # horizontal axis follows the wire so the text always reads *outward* from
        # it (anchored at the end nearest the wire).
        if kdx == 0 and kdy == 0:
            rot, hjust = _krot(angle), "left"
        elif abs(kdx) >= abs(kdy):                # horizontal wire → label rot 0
            rot = 0
            hjust = "right" if kdx > 0 else "left"
        else:                                     # vertical wire → label rot 90
            rot = 90
            hjust = "right" if kdy < 0 else "left"
        just = f"{hjust} bottom"
        snapped_labels.append((net_name, px(slx), py(ky(sly)), rot, just))

    # ── Connection points + dangling-wire trimming ──────────────────────
    # Labels ARE trim anchors: a wire that legitimately terminates at a net label
    # (e.g. pin → wire → label) must be kept. Because each label now sits exactly
    # on the wire, the wire is only ever *shortened* to the label, never grown.
    conn_pts = set()
    for _p in pin_world_pts:
        conn_pts.add((round(_p[0], 3), round(_p[1], 3)))
    for _nn, _lx, _ly, _r, _j in snapped_labels:
        conn_pts.add((round(_lx, 3), round(_ly, 3)))
    junction_pts = [(px(jx), py(ky(jy))) for jx, jy in junctions]
    for _jx, _jy in junction_pts:
        conn_pts.add((round(_jx, 3), round(_jy, 3)))

    kicad_wires = [
        (px(x1), py(ky(y1)), px(x2), py(ky(y2)))
        for _net_name, x1, y1, x2, y2 in net_wires
    ]
    kicad_wires = _trim_wires(kicad_wires, conn_pts)

    # Net wires (trimmed)
    for x1, y1, x2, y2 in kicad_wires:
        out.append(
            f'  (wire (pts (xy {_fmt(x1)} {_fmt(y1)})'
            f' (xy {_fmt(x2)} {_fmt(y2)}))\n'
            f'    (stroke (width 0) (type default)) (uuid {_uid()}))\n'
        )

    # Junctions
    for jx, jy in junction_pts:
        out.append(
            f'  (junction (at {_fmt(jx)} {_fmt(jy)})'
            f' (diameter 0) (color 0 0 0 0) (uuid {_uid()}))\n'
        )

    # Net labels (moved onto the wire, justified so the text runs off it)
    for net_name, lxk, lyk, lrot, ljust in snapped_labels:
        just_s = f' (justify {ljust})' if ljust else ""
        out.append(
            f'  (label "{_escape(net_name)}" (at {_fmt(lxk)} {_fmt(lyk)} {lrot})\n'
            f'    (effects (font (size 1.016 1.016)){just_s}) (uuid {_uid()}))\n'
        )

    out.append("  (sheet_instances\n    (path \"/\" (page \"1\"))\n  )\n")
    out.append(")\n")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(out)

    return sch_uuid


# ── EagleCommands (MCP handler) ────────────────────────────────────────────────
class EagleCommands:
    """Handles Eagle-related MCP commands."""

    def __init__(self) -> None:
        self._kicad_cli = self._find_kicad_cli()

    @staticmethod
    def _find_kicad_cli() -> Optional[str]:
        candidates: List[str] = []
        if sys.platform == "win32":
            for v in ("10.0", "9.0", "8.0"):
                candidates.append(rf"C:\Program Files\KiCad\{v}\bin\kicad-cli.exe")
        else:
            candidates += ["kicad-cli", "/usr/bin/kicad-cli", "/usr/local/bin/kicad-cli"]
        for c in candidates:
            if os.path.exists(c):
                return c
        return "kicad-cli"

    # ── Public command ─────────────────────────────────────────────────────────
    def import_eagle_project(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert an Eagle project to a KiCad project.

        Params
        ------
        board_file     : path to Eagle .brd file (required)
        schematic_file : path to Eagle .sch file (optional; auto-detected from .brd)
        output_dir     : destination directory   (optional; defaults beside .brd)
        project_name   : project name            (optional; defaults to .brd stem)
        """
        board_file:   Optional[str] = params.get("board_file")
        sch_file:     Optional[str] = (params.get("schematic_file")
                                       or params.get("sch_file"))
        output_dir:   Optional[str] = params.get("output_dir")
        project_name: Optional[str] = params.get("project_name")

        if not board_file:
            return {"success": False, "error": "board_file is required"}
        if not os.path.exists(board_file):
            return {"success": False, "error": f"board_file not found: {board_file}"}

        brd_base     = os.path.splitext(os.path.basename(board_file))[0]
        project_name = project_name or brd_base
        safe_name    = re.sub(r'[<>:"/\\|?* ]', "_", project_name)

        if not sch_file:
            candidate = os.path.splitext(board_file)[0] + ".sch"
            if os.path.exists(candidate):
                sch_file = candidate

        if not output_dir:
            output_dir = os.path.join(
                os.path.dirname(os.path.abspath(board_file)), safe_name
            )
        os.makedirs(output_dir, exist_ok=True)

        results: Dict[str, Any] = {
            "success": False,
            "project_name": safe_name,
            "output_dir": output_dir,
        }

        # 1. Import PCB
        pcb_out = os.path.join(output_dir, safe_name + ".kicad_pcb")
        pcb_ok, pcb_msg = self._import_pcb(board_file, pcb_out)
        results["pcb_path"]    = pcb_out if pcb_ok else None
        results["pcb_message"] = pcb_msg

        # 2. Import schematic
        sch_out  = os.path.join(output_dir, safe_name + ".kicad_sch")
        sch_ok   = False
        sch_msg  = "No .sch file found"
        sch_uuid = None
        if sch_file and os.path.exists(sch_file):
            sch_ok, sch_msg, sch_uuid = self._import_schematic(sch_file, sch_out)
        results["sch_path"]    = sch_out if sch_ok else None
        results["sch_message"] = sch_msg

        # 3. Create .kicad_pro (with correct UUID so KiCad links it to the .kicad_sch)
        pro_path = os.path.join(output_dir, safe_name + ".kicad_pro")
        self._create_project_file(pro_path, safe_name, sch_uuid)
        results["project_path"] = pro_path

        results["success"] = pcb_ok
        results["message"]  = (
            f"PCB: {'OK' if pcb_ok else 'FAILED'}; "
            f"Schematic: {'OK' if sch_ok else 'FAILED/SKIPPED'}"
        )
        logger.info("Eagle import done: %s", results["message"])
        return results

    # ── Private helpers ────────────────────────────────────────────────────────
    def _import_pcb(self, brd_file: str, pcb_out: str) -> Tuple[bool, str]:
        cli = self._kicad_cli
        if not cli:
            return False, "kicad-cli not found"
        try:
            result = subprocess.run(
                [cli, "pcb", "import", "--format", "eagle",
                 "--output", pcb_out, brd_file],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0 and os.path.exists(pcb_out):
                return True, "PCB imported successfully"
            return False, result.stderr or result.stdout or "kicad-cli non-zero"
        except Exception as e:
            return False, str(e)

    def _import_schematic(
        self, sch_file: str, sch_out: str
    ) -> Tuple[bool, str, Optional[str]]:
        try:
            parts, instances, net_wires, net_labels, junctions = \
                parse_eagle_schematic(sch_file)

            sch_uuid = generate_kicad_sch(
                parts, instances, net_wires, net_labels, junctions, sch_out
            )

            if not (os.path.exists(sch_out) and os.path.getsize(sch_out) > 50):
                return False, "Output file too small", None

            # ── Generate .kicad_sym library ──────────────────────────────────
            proj_dir     = os.path.dirname(sch_out)
            proj_stem    = os.path.splitext(os.path.basename(sch_out))[0]
            lib_filename = f"{proj_stem}_eagle.kicad_sym"
            lib_path     = os.path.join(proj_dir, lib_filename)

            # Collect unique symbol geometries used by any gate instance
            unique_syms: Dict[str, "_EagleSymGeom"] = {}
            for inst in instances:
                sg = inst.sym_geom
                if sg is not None and sg.kicad_id not in unique_syms:
                    unique_syms[sg.kicad_id] = sg

            generate_sym_lib(list(unique_syms.values()), lib_path)
            generate_sym_lib_table(proj_dir, lib_filename)
            logger.info("Symbol library written: %s", lib_path)

            # ── Normalise through kicad-skip ─────────────────────────────────
            try:
                from skip import Schematic as _Schematic
                _s = _Schematic(sch_out)
                _s.write(sch_out)
                logger.info("Normalised via kicad-skip: %s", sch_out)
            except Exception as e:
                logger.warning("kicad-skip normalisation skipped: %s", e)

            n_comp = sum(
                1 for inst in instances
                if inst.part_ref and not inst.part_ref.is_frame and inst.sym_geom
            )
            n_nets = len({w[0] for w in net_wires})
            msg = (f"Schematic converted ({n_comp} placements, "
                   f"{n_nets} nets, {len(junctions)} junctions,"
                   f" {len(unique_syms)} unique symbols)")
            return True, msg, sch_uuid

        except Exception:
            logger.exception("Eagle schematic import failed")
            return False, "Conversion error (see log)", None

    @staticmethod
    def _create_project_file(
        pro_path: str, name: str, sch_uuid: Optional[str] = None
    ) -> None:
        import json as _json
        sheet_uuid = sch_uuid or str(uuid.uuid4())
        pro = {
            "board": {"design_settings": {}, "layer_presets": [], "viewports": []},
            "boards": [],
            "cvpcb": {"equivalence_files": []},
            "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
            "meta": {"filename": f"{name}.kicad_pro", "version": 1},
            "sheets": [[sheet_uuid, ""]],
            "text_variables": {},
        }
        with open(pro_path, "w", encoding="utf-8") as fh:
            _json.dump(pro, fh, indent=2)
