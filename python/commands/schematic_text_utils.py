"""
Shared text/S-expression helpers for schematic command modules.

These operate directly on ``.kicad_sch`` file text (no pcbnew / KiCADInterface needed)
and are used by the field-layout, batch-authoring and hierarchy command modules. Keeping
them here avoids those modules importing helpers from one another.
"""

import math
import re
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import sexpdata
from utils.sexpr_format import QUOTED_VALUE, match_paren, unescape_sexpr_string

_KICAD_INTERNAL_PROPS = frozenset(
    {"ki_keywords", "ki_description", "ki_fp_filters", "ki_locked", "ki_model"}
)


def _find_matching_paren(s: str, start: int) -> int:
    """Return index of the ')' matching the '(' at position *start*, or -1.

    Parens inside quoted strings are text: KiCad writes pin names such as
    "PA13(JTMS" raw.
    """
    return match_paren(s, start)


def _find_placed_symbol_block(
    content: str, reference: str, unit: Optional[int] = None
) -> Tuple[Optional[str], int, int]:
    """Find the placed symbol block for *reference*. Returns (block, start, end) or (None, -1, -1).

    ``unit`` picks one placement of a multi-unit part, whose units all carry the
    same reference; without it the first block in file order wins.
    """
    lib_sym_pos = content.find("(lib_symbols")
    lib_sym_end = _find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1
    pattern = re.compile(r'\(symbol\s+\(lib_id\s+"')
    search_start = 0
    while True:
        m = pattern.search(content, search_start)
        if not m:
            break
        pos = m.start()
        if lib_sym_pos >= 0 and lib_sym_pos <= pos <= lib_sym_end:
            search_start = lib_sym_end + 1
            continue
        end = _find_matching_paren(content, pos)
        if end < 0:
            search_start = pos + 1
            continue
        block_text = content[pos : end + 1]
        if re.search(r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"', block_text):
            if unit is None:
                return block_text, pos, end
            um = re.search(r"\(unit\s+(\d+)\)", block_text)
            if um and int(um.group(1)) == int(unit):
                return block_text, pos, end
        search_start = end + 1
    return None, -1, -1


def _extract_component_properties(block_text: str, exclude_internal: bool = True) -> Dict[str, str]:
    """Extract {name: value} for all (property "name" "value" ...) entries in a symbol block."""
    props = {}
    for m in re.finditer(r"\(property\s+" + QUOTED_VALUE + r"\s+" + QUOTED_VALUE, block_text):
        name = unescape_sexpr_string(m.group(1))
        value = unescape_sexpr_string(m.group(2))
        if exclude_internal and name in _KICAD_INTERNAL_PROPS:
            continue
        props[name] = value
    return props


def _extract_property_position(block_text: str, property_name: str) -> Optional[Dict[str, float]]:
    """Return {"x","y","angle"} of a named property's (at ...), or None."""
    pat = re.compile(
        r'\(property\s+"'
        + re.escape(property_name)
        + r'"\s+"(?:[^"\\]|\\.)*"\s+\(at\s+([-\d.]+)\s+([-\d.]+)(?:\s+([-\d.]+))?\)'
    )
    m = pat.search(block_text)
    if m:
        return {
            "x": float(m.group(1)),
            "y": float(m.group(2)),
            "angle": float(m.group(3)) if m.group(3) is not None else 0.0,
        }
    return None


def _normalize_angle(angle: float) -> Union[int, float]:
    """Return int when *angle* is a whole number so S-expressions write '0'/'90'."""
    rounded = round(float(angle), 6)
    if rounded == int(rounded):
        return int(rounded)
    return rounded


def _extract_symbol_transform(block_text: str) -> Tuple[float, Optional[str]]:
    """Return ``(rotation_deg, mirror)`` for a placed ``(symbol ...)`` block.

    ``rotation_deg`` is read from the symbol's top-level ``(at x y [rot])``
    (default 0.0). ``mirror`` is ``"x"``, ``"y"``, or ``None`` from a top-level
    ``(mirror x|y)`` child.
    """
    try:
        parsed = sexpdata.loads(block_text)
    except Exception:
        return 0.0, None

    if not isinstance(parsed, list):
        return 0.0, None

    sym_at = sexpdata.Symbol("at")
    sym_mirror = sexpdata.Symbol("mirror")
    rotation = 0.0
    mirror: Optional[str] = None
    for child in parsed[1:]:
        if not isinstance(child, list) or not child:
            continue
        if child[0] == sym_at:
            if len(child) >= 4:
                rotation = float(child[3])
        elif child[0] == sym_mirror and len(child) >= 2:
            mval = str(child[1]).lower()
            if mval in ("x", "y"):
                mirror = mval
    return rotation, mirror


def _extract_property_justify(block_text: str, property_name: str) -> Tuple[str, str]:
    """Return stored ``(horizontal, vertical)`` justification of a named property.

    Horizontal is ``"left"``/``"center"``/``"right"``; vertical is
    ``"top"``/``"center"``/``"bottom"``. Missing ``(justify ...)`` or omitted
    axes default to ``"center"`` (KiCad's schematic field default).
    """
    try:
        parsed = sexpdata.loads(block_text)
    except Exception:
        return "center", "center"

    if not isinstance(parsed, list):
        return "center", "center"

    sym_prop = sexpdata.Symbol("property")
    sym_effects = sexpdata.Symbol("effects")
    sym_justify = sexpdata.Symbol("justify")
    for child in parsed[1:]:
        if (
            isinstance(child, list)
            and len(child) >= 3
            and child[0] == sym_prop
            and str(child[1]) == property_name
        ):
            for sub in child[3:]:
                if isinstance(sub, list) and sub and sub[0] == sym_effects:
                    for eff in sub[1:]:
                        if isinstance(eff, list) and eff and eff[0] == sym_justify:
                            tokens = {str(t).lower() for t in eff[1:]}
                            horiz = (
                                "left"
                                if "left" in tokens
                                else ("right" if "right" in tokens else "center")
                            )
                            vert = (
                                "top"
                                if "top" in tokens
                                else ("bottom" if "bottom" in tokens else "center")
                            )
                            return horiz, vert
            return "center", "center"

    return "center", "center"


def sheet_angle_to_stored_angle(
    sheet_angle: float, symbol_rotation: float, mirror: Optional[str] = None
) -> Union[int, float]:
    """Convert a desired sheet-absolute field angle to KiCad's stored symbol-frame angle.

    KiCad stores a field's angle in the symbol's own coordinate frame and draws
    schematic fields upright (0° = horizontal, 90° = vertical). On a symbol
    rotated 90° or 270°, stored 90° draws horizontally (0°) and stored 0° draws
    vertically (90°). The result is normalised to ``[0, 180)`` so stored 180°
    (which KiCad renders upside down on fields) is never produced.
    """
    target = -float(sheet_angle) if mirror in ("x", "y") else float(sheet_angle)
    stored = _normalize_angle((target - float(symbol_rotation)) % 180.0)
    return 0 if stored == 180 else stored


def stored_angle_to_drawn_angle(
    stored_angle: float, symbol_rotation: float, mirror: Optional[str] = None
) -> Union[int, float]:
    """Convert a stored symbol-frame field angle to its drawn sheet-absolute angle.

    Returns an angle in ``[0, 180)`` (``0`` = horizontal, ``90`` = vertical).
    """
    combined = (float(stored_angle) + float(symbol_rotation)) % 180.0
    if mirror in ("x", "y"):
        combined = (-combined) % 180.0
    drawn = _normalize_angle(combined)
    return 0 if drawn == 180 else drawn


def effective_field_justification(
    stored_horizontal: str,
    stored_vertical: str,
    stored_angle: float,
    symbol_rotation: float,
    mirror: Optional[str] = None,
) -> Dict[str, str]:
    """Compute a field's effective sheet-space justification as KiCad renders it.

    KiCad lays out a field's text box using its stored angle and justification in
    the symbol's frame, rotates CCW by ``symbol_rotation``, then applies
    ``mirror`` (``"y"`` flips X, ``"x"`` flips Y), and draws the text upright
    inside that box. Comparing the transformed text axes against the upright
    drawn axes at ``stored_angle_to_drawn_angle(...)`` determines whether
    horizontal (``left`` <-> ``right``) and/or vertical (``top`` <-> ``bottom``)
    justification flip on the sheet.
    """
    theta = math.radians(float(stored_angle) + float(symbol_rotation))
    ux, uy = math.cos(theta), math.sin(theta)
    vx, vy = math.sin(theta), -math.cos(theta)
    if mirror == "y":
        ux, vx = -ux, -vx
    elif mirror == "x":
        uy, vy = -uy, -vy

    drawn = stored_angle_to_drawn_angle(stored_angle, symbol_rotation, mirror)
    d_rad = math.radians(float(drawn))
    dux, duy = math.cos(d_rad), math.sin(d_rad)
    dvx, dvy = math.sin(d_rad), -math.cos(d_rad)

    h_flip = {"left": "right", "right": "left", "center": "center"}
    v_flip = {"top": "bottom", "bottom": "top", "center": "center"}
    h_norm = stored_horizontal if stored_horizontal in h_flip else "center"
    v_norm = stored_vertical if stored_vertical in v_flip else "center"

    eff_h = h_flip[h_norm] if (ux * dux + uy * duy) < 0 else h_norm
    eff_v = v_flip[v_norm] if (vx * dvx + vy * dvy) < 0 else v_norm
    return {"horizontal": eff_h, "vertical": eff_v}


def _format_justify_label(horizontal: str, vertical: str) -> str:
    """Format a ``(horizontal, vertical)`` justification pair as a concise KiCad string."""
    parts = [p for p in (horizontal, vertical) if p != "center"]
    return " ".join(parts) if parts else "center"


def _extract_property_visible(block_text: str, property_name: str) -> bool:
    """True if the named property is visible (no hide flag)."""
    m = re.search(r'\(property\s+"' + re.escape(property_name) + r'"', block_text)
    if not m:
        return True
    end = _find_matching_paren(block_text, m.start())
    if end < 0:
        return True
    prop_sub = block_text[m.start() : end + 1]
    return "(hide yes)" not in prop_sub and "(hide)" not in prop_sub


def _apply_visibility(block: str, property_name: str, visible: bool) -> str:
    """Add or remove a (hide yes) flag on a property's (effects ...) sub-expression."""
    m = re.search(r'\(property\s+"' + re.escape(property_name) + r'"', block)
    if not m:
        return block
    ps = m.start()
    pe = _find_matching_paren(block, ps)
    if pe < 0:
        return block
    prop_sub = block[ps : pe + 1]
    is_hidden = "(hide yes)" in prop_sub or "(hide)" in prop_sub
    if not visible and not is_hidden:
        em = re.search(r"\(effects", prop_sub)
        if em:
            es = em.start()
            ee = _find_matching_paren(prop_sub, es)
            if ee >= 0:
                prop_sub = prop_sub[:es] + prop_sub[es:ee] + " (hide yes))" + prop_sub[ee + 1 :]
    elif visible and is_hidden:
        for tok in (" (hide yes)", "(hide yes) ", "(hide yes)", " (hide)", "(hide) ", "(hide)"):
            prop_sub = prop_sub.replace(tok, "")
    return block[:ps] + prop_sub + block[pe + 1 :]


def _move_property_in_block(block_text, property_name, x, y, angle, visible) -> Tuple[str, int]:
    """Replace a property's (at ...) and apply visibility. Returns (new_block, n_substitutions)."""
    prop_pat = re.compile(
        r'(\(property\s+"'
        + re.escape(property_name)
        + r'"\s+"(?:[^"\\]|\\.)*"\s+)\(at\s+[-\d.]+\s+[-\d.]+(?:\s+[-\d.]+)?\)'
    )
    new_block, n_subs = prop_pat.subn(r"\g<1>" + f"(at {x} {y} {angle})", block_text)
    if n_subs == 0:
        return block_text, 0
    return _apply_visibility(new_block, property_name, visible), n_subs


def _find_project_root(start_dir: Path) -> Path:
    """Walk up from *start_dir* to the nearest dir containing a .kicad_pro (else start_dir)."""
    current = start_dir.resolve()
    while True:
        if list(current.glob("*.kicad_pro")):
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return start_dir


# Outward direction of a pin by its label orientation, in sheet coordinates (y down).
_OUTWARD = {0: (1, 0), 90: (0, -1), 180: (-1, 0), 270: (0, 1)}


def _straight_ahead(position, orientation, target, tol=0.01):
    """True when *target* lies on the pin's outward axis, in front of the pin."""
    d = _OUTWARD.get(int(round(orientation / 90) * 90) % 360)
    if d is None:
        return False
    dx, dy = float(target[0]) - float(position[0]), float(target[1]) - float(position[1])
    along = dx * d[0] + dy * d[1]
    across = abs(dx * d[1] - dy * d[0])
    return along > tol and across <= tol


def _find_facing_label(sch_path, net_name, position, orientation, proximity_mm=14.0):
    """Return [x, y] of an existing label for *net_name* that faces *position*, else None.

    "Facing" = within proximity_mm, oriented 180° opposite, and straight out in front
    of the pin on its own axis, so a single wire between the two pins is cleaner than
    two overlapping labels. A label off that axis is not facing: joining it would draw
    a diagonal wire, which no schematic is drawn with (and a label behind the pin would
    send the wire back across the symbol body).
    """
    try:
        content = sch_path.read_text(encoding="utf-8")
        pat = re.compile(r'\(label\s+"([^"]+)"\s+\(at\s+([-\d.]+)\s+([-\d.]+)\s+([\d.]+)\)')
        px, py = float(position[0]), float(position[1])
        facing = (int(round(orientation)) % 360 + 180) % 360
        for m in pat.finditer(content):
            if m.group(1) != net_name:
                continue
            lx, ly, la = float(m.group(2)), float(m.group(3)), float(m.group(4))
            if math.hypot(lx - px, ly - py) > proximity_mm:
                continue
            if int(round(la)) % 360 == facing and _straight_ahead(position, orientation, (lx, ly)):
                return [lx, ly]
    except Exception:
        pass
    return None
