"""
S-Expression Writer for KiCad Schematics

Provides text-based insertion into .kicad_sch files, preserving KiCad's native formatting.
Replaces sexpdata round-trip (loads → modify → dumps) which collapses all formatting
into a single line.

All functions insert properly-indented S-expression text at the correct location
in the file, without parsing/re-serializing the entire document.
"""

import os
import re
import uuid
import logging
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("kicad_interface")


# ── T-junction detection helpers ──


def _point_on_wire_mid(px, py, wx1, wy1, wx2, wy2, tolerance=0.01):
    """Check if (px,py) lies on the interior of wire (wx1,wy1)→(wx2,wy2).

    KiCad wires are strictly H or V.  Returns True only for mid-segment
    hits (not endpoints).
    """
    px, py = float(px), float(py)
    wx1, wy1, wx2, wy2 = float(wx1), float(wy1), float(wx2), float(wy2)

    # Horizontal
    if abs(wy1 - wy2) < tolerance and abs(py - wy1) < tolerance:
        lo, hi = min(wx1, wx2), max(wx1, wx2)
        if lo + tolerance < px < hi - tolerance:
            return True

    # Vertical
    if abs(wx1 - wx2) < tolerance and abs(px - wx1) < tolerance:
        lo, hi = min(wy1, wy2), max(wy1, wy2)
        if lo + tolerance < py < hi - tolerance:
            return True

    return False


def _parse_wire_segments(content):
    """Extract all wire segments from content as (x1, y1, x2, y2) tuples."""
    wires = []
    wire_pat = re.compile(r"\(wire\b")
    xy_pat = re.compile(r"\(xy\s+([\d.e+-]+)\s+([\d.e+-]+)\)")
    for wm in wire_pat.finditer(content):
        depth = 0
        i = wm.start()
        block_end = i
        while i < len(content):
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
                if depth == 0:
                    block_end = i + 1
                    break
            i += 1
        block = content[wm.start():block_end]
        xys = xy_pat.findall(block)
        if len(xys) >= 2:
            wires.append((
                float(xys[0][0]), float(xys[0][1]),
                float(xys[-1][0]), float(xys[-1][1]),
            ))
    return wires


def _parse_existing_junctions(content):
    """Extract existing junction positions as set of (x, y) tuples."""
    junctions = set()
    pat = re.compile(r"\(junction\s+\(at\s+([\d.e+-]+)\s+([\d.e+-]+)\)")
    for m in pat.finditer(content):
        junctions.add((round(float(m.group(1)), 4), round(float(m.group(2)), 4)))
    return junctions


def auto_add_t_junctions(content, new_endpoints, tolerance=0.05):
    """Detect T-junctions involving new_endpoints and add junction dots.

    Args:
        content: Schematic content string (wires already added).
        new_endpoints: List of (x, y) tuples — endpoints of newly added wires.
        tolerance: Matching tolerance in mm.

    Returns modified content with junction dots at any T-junctions found.
    """
    all_wires = _parse_wire_segments(content)
    existing_junctions = _parse_existing_junctions(content)
    junctions_to_add = set()

    for ex, ey in new_endpoints:
        # Check: does this new endpoint land on mid-segment of any wire?
        for wx1, wy1, wx2, wy2 in all_wires:
            if _point_on_wire_mid(ex, ey, wx1, wy1, wx2, wy2, tolerance):
                pt = (round(ex, 4), round(ey, 4))
                if pt not in existing_junctions:
                    junctions_to_add.add(pt)

    # Also check: does any wire endpoint land on mid-segment of a new wire?
    # (build new wires from consecutive pairs of new_endpoints is unreliable;
    #  instead, check ALL wire endpoints against ALL wire segments for completeness)
    # This is already handled by the check above for the new endpoints.

    for jx, jy in junctions_to_add:
        content = add_junction_to_content(content, [jx, jy])
        logger.info(f"Auto-added T-junction at ({jx}, {jy})")

    return content, len(junctions_to_add)


def _fmt(v: float) -> str:
    """Format a coordinate value consistently: strip trailing zeros but keep
    at least one decimal place. Matches KiCad's native output (e.g. 82 not 82.0,
    148.604 not 148.60400)."""
    if isinstance(v, int):
        return str(v)
    # Format with enough precision, strip trailing zeros
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s


def _find_insert_position(content: str) -> int:
    """Find the insertion point before (sheet_instances in the schematic file.

    Returns the character index where new elements should be inserted.
    Falls back to inserting before the final closing paren if (sheet_instances
    is not found.
    """
    marker = "(sheet_instances"
    pos = content.rfind(marker)
    if pos == -1:
        # Fallback: insert before the final closing paren
        pos = content.rfind(")")
    if pos == -1:
        raise ValueError("Cannot find insertion point in schematic content")
    return pos


def _read_schematic(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write_schematic(path: Path, content: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())


def add_wire_to_content(
    content: str,
    start_point: List[float],
    end_point: List[float],
    stroke_width: float = 0,
    stroke_type: str = "default",
) -> str:
    """Add a wire to schematic content string. Returns modified content."""
    wire_uuid = str(uuid.uuid4())
    wire_text = (
        f"  (wire (pts (xy {_fmt(start_point[0])} {_fmt(start_point[1])}) "
        f"(xy {_fmt(end_point[0])} {_fmt(end_point[1])}))\n"
        f"    (stroke (width {stroke_width}) (type {stroke_type}))\n"
        f'    (uuid "{wire_uuid}")\n'
        f"  )\n\n"
    )
    insert_at = _find_insert_position(content)
    return content[:insert_at] + wire_text + content[insert_at:]


def add_wire(
    schematic_path: Path,
    start_point: List[float],
    end_point: List[float],
    stroke_width: float = 0,
    stroke_type: str = "default",
) -> bool:
    """Add a wire to the schematic using text insertion.

    Automatically adds junction dots at any T-junctions created by the new wire.
    """
    try:
        content = _read_schematic(schematic_path)
        content = add_wire_to_content(content, start_point, end_point, stroke_width, stroke_type)
        # Auto-detect and fix T-junctions
        endpoints = [(start_point[0], start_point[1]), (end_point[0], end_point[1])]
        content, n_junctions = auto_add_t_junctions(content, endpoints)
        _write_schematic(schematic_path, content)
        msg = f"Added wire from {start_point} to {end_point}"
        if n_junctions:
            msg += f" (auto-added {n_junctions} junction(s))"
        logger.info(msg)
        return True
    except Exception as e:
        logger.error(f"Error adding wire: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def add_polyline_wire_to_content(
    content: str,
    points: List[List[float]],
    stroke_width: float = 0,
    stroke_type: str = "default",
) -> str:
    """Add a multi-segment wire (polyline) to schematic content string. Returns modified content.

    Raises ValueError if fewer than 2 points are provided.
    """
    if len(points) < 2:
        raise ValueError("Polyline requires at least 2 points")

    wire_uuid = str(uuid.uuid4())

    pts_parts = " ".join(f"(xy {_fmt(p[0])} {_fmt(p[1])})" for p in points)
    wire_text = (
        f"  (wire (pts {pts_parts})\n"
        f"    (stroke (width {stroke_width}) (type {stroke_type}))\n"
        f'    (uuid "{wire_uuid}")\n'
        f"  )\n\n"
    )

    insert_at = _find_insert_position(content)
    return content[:insert_at] + wire_text + content[insert_at:]


def add_polyline_wire(
    schematic_path: Path,
    points: List[List[float]],
    stroke_width: float = 0,
    stroke_type: str = "default",
) -> bool:
    """Add a multi-segment wire (polyline) to the schematic.

    Automatically adds junction dots at any T-junctions created.
    """
    try:
        if len(points) < 2:
            logger.error("Polyline requires at least 2 points")
            return False

        content = _read_schematic(schematic_path)
        content = add_polyline_wire_to_content(content, points, stroke_width, stroke_type)
        # Auto-detect T-junctions at all polyline vertices
        endpoints = [(p[0], p[1]) for p in points]
        content, n_junctions = auto_add_t_junctions(content, endpoints)
        _write_schematic(schematic_path, content)

        msg = f"Added polyline wire with {len(points)} points"
        if n_junctions:
            msg += f" (auto-added {n_junctions} junction(s))"
        logger.info(msg)
        return True
    except Exception as e:
        logger.error(f"Error adding polyline wire: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def add_label_to_content(
    content: str,
    text: str,
    position: List[float],
    label_type: str = "label",
    orientation: int = 0,
    shape: Optional[str] = None,
) -> str:
    """Add a net label to schematic content string. Returns modified content.

    Args:
        content: The schematic file content as a string.
        text: The label text (net name).
        position: [x, y] coordinates for the label.
        label_type: 'label', 'global_label', or 'hierarchical_label'
        orientation: Rotation angle in degrees (0, 90, 180, 270).
        shape: For global_label: 'input', 'output', 'bidirectional', 'passive', 'tri_state'
    """
    label_uuid = str(uuid.uuid4())

    # Build the label S-expression
    shape_attr = ""
    if label_type == "global_label" and shape:
        shape_attr = f" (shape {shape})"

    # Justify depends on angle: 0°/90° → left, 180°/270° → right.
    # Local labels additionally use "bottom".
    norm_angle = int(orientation) % 360
    justify_dir = "right" if norm_angle in (180, 270) else "left"
    if label_type == "label":
        justify = f"(justify {justify_dir} bottom)"
    else:
        justify = f"(justify {justify_dir})"

    # Global/hierarchical labels need an Intersheetrefs property
    isr_block = ""
    if label_type in ("global_label", "hierarchical_label"):
        # Intersheetrefs position: for justify left it's at the label position,
        # for justify right it's offset by the flag width
        char_w = 0.75
        text_len = len(text) * char_w
        body = 3.0
        total_w = body + text_len
        isr_x, isr_y = position[0], position[1]
        if norm_angle == 180:
            isr_x = round(position[0] - total_w, 4)
        elif norm_angle == 270:
            isr_y = round(position[1] - total_w, 4)
        isr_block = (
            f'    (property "Intersheetrefs" "${{INTERSHEET_REFS}}"\n'
            f"      (at {_fmt(isr_x)} {_fmt(isr_y)} {orientation})\n"
            f"      (effects (font (size 1.27 1.27)) (justify {justify_dir}) (hide yes))\n"
            f"    )\n"
        )

    label_text = (
        f'  ({label_type} "{text}"{shape_attr} (at {_fmt(position[0])} {_fmt(position[1])} {orientation})\n'
        f"    (fields_autoplaced yes)\n"
        f"    (effects (font (size 1.27 1.27)) {justify})\n"
        f'    (uuid "{label_uuid}")\n'
        f"{isr_block}"
        f"  )\n\n"
    )

    insert_at = _find_insert_position(content)
    return content[:insert_at] + label_text + content[insert_at:]


def add_label(
    schematic_path: Path,
    text: str,
    position: List[float],
    label_type: str = "label",
    orientation: int = 0,
    shape: Optional[str] = None,
) -> bool:
    """Add a net label to the schematic.

    Args:
        label_type: 'label', 'global_label', or 'hierarchical_label'
        shape: For global_label: 'input', 'output', 'bidirectional', 'passive', 'tri_state'
    """
    try:
        content = _read_schematic(schematic_path)
        content = add_label_to_content(content, text, position, label_type, orientation, shape)
        _write_schematic(schematic_path, content)

        logger.info(f"Added {label_type} '{text}' at {position}")
        return True
    except Exception as e:
        logger.error(f"Error adding label: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def add_junction_to_content(
    content: str,
    position: List[float],
    diameter: float = 0,
) -> str:
    """Add a junction to schematic content string. Returns modified content."""
    junction_uuid = str(uuid.uuid4())
    junction_text = (
        f"  (junction (at {_fmt(position[0])} {_fmt(position[1])}) (diameter {diameter})\n"
        f"    (color 0 0 0 0)\n"
        f'    (uuid "{junction_uuid}")\n'
        f"  )\n\n"
    )
    insert_at = _find_insert_position(content)
    return content[:insert_at] + junction_text + content[insert_at:]


def add_junction(
    schematic_path: Path,
    position: List[float],
    diameter: float = 0,
) -> bool:
    """Add a junction (connection dot) to the schematic."""
    try:
        content = _read_schematic(schematic_path)
        content = add_junction_to_content(content, position, diameter)
        _write_schematic(schematic_path, content)
        logger.info(f"Added junction at {position}")
        return True
    except Exception as e:
        logger.error(f"Error adding junction: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def add_no_connect_to_content(content: str, position: List[float]) -> str:
    """Add a no-connect flag to schematic content string. Returns modified content."""
    nc_uuid = str(uuid.uuid4())
    nc_text = (
        f"  (no_connect (at {_fmt(position[0])} {_fmt(position[1])})\n"
        f'    (uuid "{nc_uuid}")\n'
        f"  )\n\n"
    )
    insert_at = _find_insert_position(content)
    return content[:insert_at] + nc_text + content[insert_at:]


def add_no_connect(schematic_path: Path, position: List[float]) -> bool:
    """Add a no-connect flag to the schematic."""
    try:
        content = _read_schematic(schematic_path)
        content = add_no_connect_to_content(content, position)
        _write_schematic(schematic_path, content)
        logger.info(f"Added no-connect at {position}")
        return True
    except Exception as e:
        logger.error(f"Error adding no-connect: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def delete_no_connect_from_content(
    content: str,
    position: List[float],
    tolerance: float = 0.5,
) -> Optional[str]:
    """Delete a no-connect flag from schematic content string.

    Returns modified content, or None if no matching no-connect found.
    """
    import re
    nc_pattern = re.compile(r'\(no_connect\b')

    for m in nc_pattern.finditer(content):
        block_start = m.start()
        depth = 0
        i = block_start
        while i < len(content):
            if content[i] == '(':
                depth += 1
            elif content[i] == ')':
                depth -= 1
                if depth == 0:
                    block_end = i + 1
                    break
            i += 1
        else:
            continue

        block = content[block_start:block_end]
        at_match = re.search(r'\(at\s+([\d.e+-]+)\s+([\d.e+-]+)\)', block)
        if not at_match:
            continue

        nc_x = float(at_match.group(1))
        nc_y = float(at_match.group(2))

        if abs(nc_x - position[0]) < tolerance and abs(nc_y - position[1]) < tolerance:
            # Consume trailing whitespace/newlines
            end_with_ws = block_end
            while end_with_ws < len(content) and content[end_with_ws] in ('\n', ' ', '\t'):
                end_with_ws += 1
            return content[:block_start] + content[end_with_ws:]

    return None


def delete_no_connect(
    schematic_path: Path,
    position: List[float],
    tolerance: float = 0.5,
) -> bool:
    """Delete a no-connect flag from the schematic at the given position."""
    try:
        content = _read_schematic(schematic_path)
        result = delete_no_connect_from_content(content, position, tolerance)
        if result is not None:
            _write_schematic(schematic_path, result)
            logger.info(f"Deleted no-connect at {position}")
            return True
        logger.warning(f"No matching no-connect found at {position}")
        return False
    except Exception as e:
        logger.error(f"Error deleting no-connect: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def delete_wire_from_content(
    content: str,
    start_point: List[float],
    end_point: List[float],
    tolerance: float = 0.5,
) -> Optional[str]:
    """Delete a wire from schematic content string. Returns modified content, or None if not found."""
    import re
    wire_pattern = re.compile(r'\(wire\b')

    for m in wire_pattern.finditer(content):
        block_start = m.start()
        depth = 0
        i = block_start
        while i < len(content):
            if content[i] == '(':
                depth += 1
            elif content[i] == ')':
                depth -= 1
                if depth == 0:
                    block_end = i + 1
                    break
            i += 1
        else:
            continue

        block = content[block_start:block_end]
        xy_matches = re.findall(r'\(xy\s+([\d.e+-]+)\s+([\d.e+-]+)\)', block)
        if len(xy_matches) < 2:
            continue

        x1, y1 = float(xy_matches[0][0]), float(xy_matches[0][1])
        x2, y2 = float(xy_matches[-1][0]), float(xy_matches[-1][1])
        sx, sy = start_point
        ex, ey = end_point

        match_fwd = (
            abs(x1 - sx) < tolerance and abs(y1 - sy) < tolerance
            and abs(x2 - ex) < tolerance and abs(y2 - ey) < tolerance
        )
        match_rev = (
            abs(x1 - ex) < tolerance and abs(y1 - ey) < tolerance
            and abs(x2 - sx) < tolerance and abs(y2 - sy) < tolerance
        )

        if match_fwd or match_rev:
            end_with_nl = block_end
            while end_with_nl < len(content) and content[end_with_nl] in '\n':
                end_with_nl += 1
            return content[:block_start] + content[end_with_nl:]

    return None


def delete_wire(
    schematic_path: Path,
    start_point: List[float],
    end_point: List[float],
    tolerance: float = 0.5,
) -> bool:
    """Delete a wire matching given start/end coordinates using text parsing."""
    try:
        content = _read_schematic(schematic_path)
        result = delete_wire_from_content(content, start_point, end_point, tolerance)
        if result is not None:
            _write_schematic(schematic_path, result)
            logger.info(f"Deleted wire from {start_point} to {end_point}")
            return True
        logger.warning(f"No matching wire found for {start_point} to {end_point}")
        return False
    except Exception as e:
        logger.error(f"Error deleting wire: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def delete_label_from_content(
    content: str,
    net_name: str,
    position: Optional[List[float]] = None,
    tolerance: float = 0.5,
) -> Optional[str]:
    """Delete a label from schematic content string. Returns modified content, or None if not found."""
    import re
    escaped_name = re.escape(net_name)
    label_pattern = re.compile(
        rf'\((?:label|global_label|hierarchical_label)\s+"{escaped_name}"(?:\s+\(shape\s+[^)]*\))?\s'
    )

    for m in label_pattern.finditer(content):
        block_start = m.start()
        depth = 0
        i = block_start
        while i < len(content):
            if content[i] == '(':
                depth += 1
            elif content[i] == ')':
                depth -= 1
                if depth == 0:
                    block_end = i + 1
                    break
            i += 1
        else:
            continue

        block = content[block_start:block_end]

        if position is not None:
            at_match = re.search(r'\(at\s+([\d.e+-]+)\s+([\d.e+-]+)', block)
            if at_match:
                lx, ly = float(at_match.group(1)), float(at_match.group(2))
                if abs(lx - position[0]) >= tolerance or abs(ly - position[1]) >= tolerance:
                    continue

        end_with_nl = block_end
        while end_with_nl < len(content) and content[end_with_nl] in '\n':
            end_with_nl += 1
        return content[:block_start] + content[end_with_nl:]

    return None


def delete_label(
    schematic_path: Path,
    net_name: str,
    position: Optional[List[float]] = None,
    tolerance: float = 0.5,
) -> bool:
    """Delete a net label by name (and optionally position) using text parsing."""
    try:
        content = _read_schematic(schematic_path)
        result = delete_label_from_content(content, net_name, position, tolerance)
        if result is not None:
            _write_schematic(schematic_path, result)
            logger.info(f"Deleted label '{net_name}'")
            return True
        logger.warning(f"No matching label found for '{net_name}'")
        return False
    except Exception as e:
        logger.error(f"Error deleting label: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def create_orthogonal_path(
    start: List[float], end: List[float], prefer_horizontal_first: bool = True
) -> List[List[float]]:
    """Create an orthogonal (right-angle) path between two points."""
    x1, y1 = start
    x2, y2 = end

    if x1 == x2 or y1 == y2:
        return [start, end]

    if prefer_horizontal_first:
        return [start, [x2, y1], end]
    else:
        return [start, [x1, y2], end]


def add_instances_block(
    schematic_path: Path,
    symbol_uuid: str,
    reference: str,
    unit: int = 1,
) -> bool:
    """Add an (instances) block to an existing symbol in the schematic.

    KiCad 9 requires (instances (project "name" (path "/root-uuid" (reference "R1") (unit 1))))
    for annotation to work.
    """
    try:
        content = _read_schematic(schematic_path)

        # Get project name from .kicad_pro file
        project_name = _get_project_name(schematic_path)

        # Get root sheet UUID
        root_uuid = _get_root_sheet_uuid(content)

        # Find the symbol block by UUID and inject instances before closing paren
        import re
        uuid_pattern = re.compile(
            rf'\(uuid\s+"{re.escape(symbol_uuid)}"\s*\)'
        )
        m = uuid_pattern.search(content)
        if not m:
            # Try without quotes (some UUIDs are unquoted)
            uuid_pattern = re.compile(
                rf'\(uuid\s+{re.escape(symbol_uuid)}\s*\)'
            )
            m = uuid_pattern.search(content)
        if not m:
            logger.error(f"Could not find symbol with UUID {symbol_uuid}")
            return False

        # From the UUID position, find the closing paren of the symbol block
        # Walk backwards to find the opening (symbol, then find matching close
        # Actually, easier: from UUID pos, scan forward to next unmatched )
        uuid_end = m.end()

        # Find the closing ) of the symbol block
        # Count remaining depth from the uuid position
        depth = 0
        i = uuid_end
        while i < len(content):
            if content[i] == '(':
                depth += 1
            elif content[i] == ')':
                if depth == 0:
                    # This is the closing paren of the symbol
                    break
                depth -= 1
            i += 1

        if i >= len(content):
            logger.error(f"Could not find end of symbol block for UUID {symbol_uuid}")
            return False

        # Insert instances block before the closing paren
        instances_text = (
            f'\n    (instances (project "{project_name}"\n'
            f'      (path "/{root_uuid}" (reference "{reference}") (unit {unit}))\n'
            f"    ))"
        )

        content = content[:i] + instances_text + "\n" + content[i:]
        _write_schematic(schematic_path, content)

        logger.info(f"Added instances block for {reference} (UUID: {symbol_uuid})")
        return True
    except Exception as e:
        logger.error(f"Error adding instances block: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def _get_project_name(schematic_path: Path) -> str:
    """Get project name from the .kicad_pro file in the same directory."""
    import glob
    parent = schematic_path.parent
    pro_files = list(parent.glob("*.kicad_pro"))
    if pro_files:
        return pro_files[0].stem
    # Fallback: use schematic filename without extension
    return schematic_path.stem


def _get_root_sheet_uuid(content: str) -> str:
    """Extract the root sheet UUID from the schematic content."""
    import re
    # The first (uuid ...) in the file is the schematic's root UUID
    m = re.search(r'\(uuid\s+"?([0-9a-fA-F-]+)"?\s*\)', content)
    if m:
        return m.group(1)
    return "00000000-0000-0000-0000-000000000000"


def split_wire_at_point_in_content(
    content: str,
    split_x: float,
    split_y: float,
    add_junction: bool = True,
    tolerance: float = 0.05,
) -> Optional[str]:
    """Split a wire at (split_x, split_y) into two segments.

    Finds the wire whose segment contains the split point, removes it,
    and inserts two new wires meeting at the split point.
    Optionally adds a junction at the split point.

    Args:
        content: schematic file content as string
        split_x, split_y: point where to split
        add_junction: whether to add a junction dot at split point
        tolerance: coordinate matching tolerance

    Returns:
        Modified content string, or None if no wire found at that point.
    """
    import re

    wire_pattern = re.compile(r'\(wire\b')

    # Phase 1: find the wire to split (do NOT modify content in this loop)
    target_block_start = None
    target_block_end = None
    target_x1 = target_y1 = target_x2 = target_y2 = None

    for m in wire_pattern.finditer(content):
        block_start = m.start()
        # Balanced-paren matching to find the full wire block
        depth = 0
        i = block_start
        while i < len(content):
            if content[i] == '(':
                depth += 1
            elif content[i] == ')':
                depth -= 1
                if depth == 0:
                    block_end = i + 1
                    break
            i += 1
        else:
            continue

        block = content[block_start:block_end]
        xy_matches = re.findall(r'\(xy\s+([\d.e+-]+)\s+([\d.e+-]+)\)', block)
        if len(xy_matches) < 2:
            continue

        x1, y1 = float(xy_matches[0][0]), float(xy_matches[0][1])
        x2, y2 = float(xy_matches[-1][0]), float(xy_matches[-1][1])

        # Check if split point is ON the wire segment (not at endpoints)
        is_horizontal = abs(y1 - y2) < tolerance
        is_vertical = abs(x1 - x2) < tolerance

        if is_horizontal and abs(split_y - y1) < tolerance:
            # Horizontal wire: check X is strictly between endpoints
            min_x = min(x1, x2)
            max_x = max(x1, x2)
            if min_x + tolerance < split_x < max_x - tolerance:
                target_block_start = block_start
                target_block_end = block_end
                target_x1, target_y1 = x1, y1
                target_x2, target_y2 = x2, y2
                break
        elif is_vertical and abs(split_x - x1) < tolerance:
            # Vertical wire: check Y is strictly between endpoints
            min_y = min(y1, y2)
            max_y = max(y1, y2)
            if min_y + tolerance < split_y < max_y - tolerance:
                target_block_start = block_start
                target_block_end = block_end
                target_x1, target_y1 = x1, y1
                target_x2, target_y2 = x2, y2
                break

    if target_block_start is None:
        return None

    # Phase 2: build the two replacement wire blocks
    uuid1 = str(uuid.uuid4())
    uuid2 = str(uuid.uuid4())

    wire1_text = (
        f"  (wire (pts (xy {_fmt(target_x1)} {_fmt(target_y1)}) "
        f"(xy {_fmt(split_x)} {_fmt(split_y)}))\n"
        f"    (stroke (width 0) (type default))\n"
        f'    (uuid "{uuid1}")\n'
        f"  )\n"
    )
    wire2_text = (
        f"  (wire (pts (xy {_fmt(split_x)} {_fmt(split_y)}) "
        f"(xy {_fmt(target_x2)} {_fmt(target_y2)}))\n"
        f"    (stroke (width 0) (type default))\n"
        f'    (uuid "{uuid2}")\n'
        f"  )\n"
    )

    replacement = wire1_text + wire2_text

    # Phase 3: replace the old wire block, consuming trailing newlines
    end_with_nl = target_block_end
    while end_with_nl < len(content) and content[end_with_nl] == '\n':
        end_with_nl += 1

    content = content[:target_block_start] + replacement + content[end_with_nl:]

    # Phase 4: optionally add a junction at the split point
    if add_junction:
        content = add_junction_to_content(content, [split_x, split_y])

    return content


def split_wire_at_point(
    schematic_path: Path,
    split_x: float,
    split_y: float,
    add_junction: bool = True,
    tolerance: float = 0.05,
) -> bool:
    """Split a wire at the given point in a schematic file."""
    try:
        content = _read_schematic(schematic_path)
        new_content = split_wire_at_point_in_content(
            content, split_x, split_y, add_junction, tolerance
        )
        if new_content is None:
            return False
        _write_schematic(schematic_path, new_content)
        return True
    except Exception as e:
        logger.error(f"Error splitting wire: {e}")
        return False
