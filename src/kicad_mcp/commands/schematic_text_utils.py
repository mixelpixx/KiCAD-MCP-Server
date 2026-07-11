"""
Shared text/S-expression helpers for schematic command modules.

These operate directly on ``.kicad_sch`` file text (no pcbnew / KiCADInterface needed)
and are used by the field-layout, batch-authoring and hierarchy command modules. Keeping
them here avoids those modules importing helpers from one another.
"""

import math
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

_KICAD_INTERNAL_PROPS = frozenset(
    {"ki_keywords", "ki_description", "ki_fp_filters", "ki_locked", "ki_model"}
)

# Paper sizes (landscape, mm). Border frame is ~12.7mm from each edge.
_PAPER_DIMS = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
    "A": (279.4, 215.9),
    "B": (431.8, 279.4),
    "C": (558.8, 431.8),
    "D": (863.6, 558.8),
    "E": (1117.6, 863.6),
}


def _find_matching_paren(s: str, start: int) -> int:
    """Return index of the ')' matching the '(' at position *start*, or -1."""
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _find_placed_symbol_block(content: str, reference: str) -> Tuple[Optional[str], int, int]:
    """Find the placed symbol block for *reference*. Returns (block, start, end) or (None, -1, -1)."""
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
            return block_text, pos, end
        search_start = end + 1
    return None, -1, -1


def _extract_component_properties(block_text: str, exclude_internal: bool = True) -> Dict[str, str]:
    """Extract {name: value} for all (property "name" "value" ...) entries in a symbol block."""
    props = {}
    for m in re.finditer(r'\(property\s+"([^"]*)"\s+"([^"]*)"', block_text):
        name, value = m.group(1), m.group(2)
        if exclude_internal and name in _KICAD_INTERNAL_PROPS:
            continue
        props[name] = value
    return props


def _extract_property_position(block_text: str, property_name: str) -> Optional[Dict[str, float]]:
    """Return {"x","y","angle"} of a named property's (at ...), or None."""
    pat = re.compile(
        r'\(property\s+"'
        + re.escape(property_name)
        + r'"\s+"[^"]*"\s+\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)'
    )
    m = pat.search(block_text)
    if m:
        return {"x": float(m.group(1)), "y": float(m.group(2)), "angle": float(m.group(3))}
    return None


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


def _get_sheet_usable_area(schematic_path) -> Tuple[float, float, float, float]:
    """Return (left, top, right, bottom) usable bounds in mm for the sheet's paper size."""
    border = 12.7
    width, height = 297.0, 210.0  # default A4
    try:
        with open(schematic_path, "r", encoding="utf-8") as f:
            content = f.read(4096)
        m = re.search(r'\(paper\s+"([^"]+)"', content)
        if m and m.group(1).strip() in _PAPER_DIMS:
            width, height = _PAPER_DIMS[m.group(1).strip()]
    except Exception:
        pass
    return (border, border, width - border, height - border)


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
        + r'"\s+"[^"]*"\s+)\(at\s+[-\d.]+\s+[-\d.]+\s+[-\d.]+\)'
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


def _find_facing_label(sch_path, net_name, position, orientation, proximity_mm=14.0):
    """Return [x, y] of an existing label for *net_name* that faces *position*, else None.

    "Facing" = within proximity_mm and oriented 180° opposite, so a single wire between
    the two pins is cleaner than two overlapping labels.
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
            if int(round(la)) % 360 == facing:
                return [lx, ly]
    except Exception:
        pass
    return None
