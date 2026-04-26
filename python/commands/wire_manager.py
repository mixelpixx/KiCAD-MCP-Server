"""
Wire Manager for KiCad Schematics

Handles wire creation using S-expression manipulation, similar to dynamic symbol loading.
kicad-skip's wire API doesn't support creating wires with standard parameters, so we
manipulate the .kicad_sch file directly.
"""

import logging
import math
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, List, Optional, Tuple

import sexpdata
from sexpdata import Symbol

logger = logging.getLogger("kicad_interface")

# Module-level Symbol constants — avoids repeated allocation on every call
_SYM_WIRE = Symbol("wire")
_SYM_PTS = Symbol("pts")
_SYM_XY = Symbol("xy")
_SYM_AT = Symbol("at")
_SYM_LABEL = Symbol("label")
_SYM_GLOBAL_LABEL = Symbol("global_label")
_SYM_HIERARCHICAL_LABEL = Symbol("hierarchical_label")
_SYM_STROKE = Symbol("stroke")
_SYM_WIDTH = Symbol("width")
_SYM_TYPE = Symbol("type")
_SYM_UUID = Symbol("uuid")
_SYM_SHEET_INSTANCES = Symbol("sheet_instances")
_SYM_JUNCTION = Symbol("junction")
_SYM_LIB_SYMBOLS = Symbol("lib_symbols")
_SYM_LIB_ID = Symbol("lib_id")
_SYM_MIRROR = Symbol("mirror")
_SYM_PIN = Symbol("pin")
_SYM_SYMBOL = Symbol("symbol")
_SYM_UNIT = Symbol("unit")
_IU_PER_MM = 10000


def _find_insertion_point(content: str) -> int:
    """Find the right place to insert new elements in a .kicad_sch file.

    Looks for (sheet_instances (KiCad 8) first, falls back to inserting
    before the final closing paren (KiCad 9+).
    """
    marker = "(sheet_instances"
    pos = content.rfind(marker)
    if pos != -1:
        return pos
    pos = content.rfind(")")
    if pos == -1:
        raise ValueError("Could not find insertion point in schematic")
    return pos


def _text_insert(file_path: Path, sexp_text: str) -> bool:
    """Insert S-expression text into a .kicad_sch file preserving formatting."""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    insert_at = _find_insertion_point(content)
    content = content[:insert_at] + sexp_text + content[insert_at:]

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def _make_hierarchical_label_text(
    text: str,
    position: List[float],
    shape: str = "bidirectional",
    orientation: int = 0,
) -> str:
    """Generate a hierarchical_label S-expression as formatted text.

    orientation: 0=right (label points right, justify left),
                 180=left (label points left, justify right),
                 90/270=vertical.
    """
    uid = str(uuid.uuid4())
    justify = "right" if orientation == 180 else "left"
    return (
        f'\t(hierarchical_label "{text}"\n'
        f"\t\t(shape {shape})\n"
        f"\t\t(at {position[0]} {position[1]} {orientation})\n"
        f"\t\t(effects\n"
        f"\t\t\t(font\n"
        f"\t\t\t\t(size 1.27 1.27)\n"
        f"\t\t\t)\n"
        f"\t\t\t(justify {justify})\n"
        f"\t\t)\n"
        f'\t\t(uuid "{uid}")\n'
        f"\t)\n"
    )


def _make_sheet_pin_text(
    pin_name: str,
    pin_type: str,
    position: List[float],
    orientation: int = 0,
) -> str:
    """Generate a sheet pin S-expression as formatted text (indented for inside sheet block).

    orientation: 0=right side of sheet box, 180=left side.
    """
    uid = str(uuid.uuid4())
    justify = "left" if orientation == 0 else "right"
    return (
        f'\t\t(pin "{pin_name}" {pin_type}\n'
        f"\t\t\t(at {position[0]} {position[1]} {orientation})\n"
        f'\t\t\t(uuid "{uid}")\n'
        f"\t\t\t(effects\n"
        f"\t\t\t\t(font\n"
        f"\t\t\t\t\t(size 1.27 1.27)\n"
        f"\t\t\t\t)\n"
        f"\t\t\t\t(justify {justify})\n"
        f"\t\t\t)\n"
        f"\t\t)\n"
    )


class WireManager:
    """Manage wires in KiCad schematics using S-expression manipulation"""

    # Regex to parse sub-unit names like "LM324_2_1" → (base="LM324", unit=2, style=1)
    # The sub-unit suffix is <base>_<unit>_<style> where unit and style are integers.
    # Assumes KiCad's <base>_<unit>_<style> convention (rightmost two underscore-separated numeric groups are unit/style); unparseable names fall back to including all pins via the else branch in _parse_lib_pins.
    _SUB_UNIT_RE = re.compile(r"^(.+)_(\d+)_(\d+)$")

    @staticmethod
    def add_wire(
        schematic_path: Path,
        start_point: List[float],
        end_point: List[float],
        stroke_width: float = 0,
        stroke_type: str = "default",
    ) -> bool:
        """
        Add a wire to the schematic using S-expression manipulation

        Args:
            schematic_path: Path to .kicad_sch file
            start_point: [x, y] coordinates for wire start
            end_point: [x, y] coordinates for wire end
            stroke_width: Wire width (default 0 for standard)
            stroke_type: Stroke type (default, solid, dashed, etc.)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Read schematic
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            # Break any existing wire that passes through a new endpoint (T-junction support)
            for pt in (start_point, end_point):
                splits = WireManager._break_wires_at_point(sch_data, pt)
                if splits:
                    logger.info(f"Broke {splits} wire(s) at new wire endpoint {pt}")

            # Create wire S-expression
            # Format: (wire (pts (xy x1 y1) (xy x2 y2)) (stroke (width N) (type default)) (uuid ...))
            wire_sexp = WireManager._make_wire_sexp(
                start_point, end_point, stroke_width, stroke_type
            )

            # Find insertion point (before sheet_instances)
            sheet_instances_index = None
            for i, item in enumerate(sch_data):
                if isinstance(item, list) and len(item) > 0 and item[0] == _SYM_SHEET_INSTANCES:
                    sheet_instances_index = i
                    break

            if sheet_instances_index is None:
                logger.error("No sheet_instances section found in schematic")
                return False

            # Insert wire before sheet_instances
            sch_data.insert(sheet_instances_index, wire_sexp)
            logger.info(f"Injected wire from {start_point} to {end_point}")

            WireManager.sync_junctions(sch_data)

            # Write back
            with open(schematic_path, "w", encoding="utf-8") as f:
                output = sexpdata.dumps(sch_data)
                f.write(output)

            logger.info(f"Successfully added wire to {schematic_path.name}")
            return True

        except Exception as e:
            logger.error(f"Error adding wire: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_polyline_wire(
        schematic_path: Path,
        points: List[List[float]],
        stroke_width: float = 0,
        stroke_type: str = "default",
    ) -> bool:
        """
        Add a multi-segment wire (polyline) to the schematic

        Args:
            schematic_path: Path to .kicad_sch file
            points: List of [x, y] coordinates for each point in the path
            stroke_width: Wire width
            stroke_type: Stroke type

        Returns:
            True if successful, False otherwise
        """
        try:
            if len(points) < 2:
                logger.error("Polyline requires at least 2 points")
                return False

            # Read schematic
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            # Break any existing wire at the outer endpoints of the new path
            for pt in (points[0], points[-1]):
                splits = WireManager._break_wires_at_point(sch_data, pt)
                if splits:
                    logger.info(f"Broke {splits} wire(s) at new polyline endpoint {pt}")

            # KiCAD wire elements only support exactly 2 pts each.
            # Split N waypoints into N-1 individual wire segments.
            wire_sexps = [
                WireManager._make_wire_sexp(points[i], points[i + 1], stroke_width, stroke_type)
                for i in range(len(points) - 1)
            ]

            # Find insertion point
            sheet_instances_index = None
            for i, item in enumerate(sch_data):
                if isinstance(item, list) and len(item) > 0 and item[0] == _SYM_SHEET_INSTANCES:
                    sheet_instances_index = i
                    break

            if sheet_instances_index is None:
                logger.error("No sheet_instances section found in schematic")
                return False

            # Insert all segments (in reverse so order is preserved after inserts)
            for wire_sexp in reversed(wire_sexps):
                sch_data.insert(sheet_instances_index, wire_sexp)
            logger.info(
                f"Injected {len(wire_sexps)} wire segments for {len(points)}-point polyline"
            )

            WireManager.sync_junctions(sch_data)

            # Write back
            with open(schematic_path, "w", encoding="utf-8") as f:
                output = sexpdata.dumps(sch_data)
                f.write(output)

            logger.info(f"Successfully added polyline wire to {schematic_path.name}")
            return True

        except Exception as e:
            logger.error(f"Error adding polyline wire: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_label(
        schematic_path: Path,
        text: str,
        position: List[float],
        label_type: str = "label",
        orientation: int = 0,
    ) -> bool:
        """
        Add a net label to the schematic

        Args:
            schematic_path: Path to .kicad_sch file
            text: Label text (net name)
            position: [x, y] coordinates for label
            label_type: Type of label ('label', 'global_label', 'hierarchical_label')
            orientation: Rotation angle (0, 90, 180, 270)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Read schematic
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            # Create label S-expression
            # Format: (label "TEXT" (at x y angle) (effects (font (size 1.27 1.27))))
            label_sexp = [
                Symbol(label_type),
                text,
                [Symbol("at"), position[0], position[1], orientation],
                [Symbol("fields_autoplaced"), Symbol("yes")],
                [
                    Symbol("effects"),
                    [Symbol("font"), [Symbol("size"), 1.27, 1.27]],
                    [Symbol("justify"), Symbol("left"), Symbol("bottom")],
                ],
                [Symbol("uuid"), str(uuid.uuid4())],
            ]

            # Find insertion point
            sheet_instances_index = None
            for i, item in enumerate(sch_data):
                if isinstance(item, list) and len(item) > 0 and item[0] == _SYM_SHEET_INSTANCES:
                    sheet_instances_index = i
                    break

            if sheet_instances_index is None:
                # Sub-sheets in hierarchical designs don't have (sheet_instances).
                # Fall back to appending before the final closing paren of (kicad_sch ...).
                sheet_instances_index = len(sch_data)

            # Insert label
            sch_data.insert(sheet_instances_index, label_sexp)
            logger.info(f"Injected label '{text}' at {position}")

            # Write back
            with open(schematic_path, "w", encoding="utf-8") as f:
                output = sexpdata.dumps(sch_data)
                f.write(output)

            logger.info(f"Successfully added label to {schematic_path.name}")
            return True

        except Exception as e:
            logger.error(f"Error adding label: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def _parse_wire(
        wire_item: Any,
    ) -> Optional[Tuple[Tuple[float, float], Tuple[float, float], float, str]]:
        """
        Parse a wire S-expression item in a single pass.
        Returns ((x1,y1), (x2,y2), stroke_width, stroke_type), or None if not a valid wire.
        """
        if not (isinstance(wire_item, list) and len(wire_item) >= 2 and wire_item[0] == _SYM_WIRE):
            return None
        start = end = None
        stroke_width: float = 0
        stroke_type: str = "default"
        for part in wire_item[1:]:
            if not isinstance(part, list) or not part:
                continue
            tag = part[0]
            if tag == _SYM_PTS:
                found: List[Tuple[float, float]] = []
                for p in part[1:]:
                    if isinstance(p, list) and len(p) >= 3 and p[0] == _SYM_XY:
                        found.append((float(p[1]), float(p[2])))
                        if len(found) == 2:
                            break
                if len(found) == 2:
                    start, end = found[0], found[1]
            elif tag == _SYM_STROKE:
                for sp in part[1:]:
                    if isinstance(sp, list) and len(sp) >= 2:
                        if sp[0] == _SYM_WIDTH:
                            stroke_width = sp[1]
                        elif sp[0] == _SYM_TYPE:
                            stroke_type = str(sp[1])
        if start is not None and end is not None:
            return start, end, stroke_width, stroke_type
        return None

    @staticmethod
    def _point_strictly_on_wire(
        px: float,
        py: float,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        eps: float = 1e-6,
    ) -> bool:
        """
        Return True if (px, py) lies strictly between (x1,y1) and (x2,y2)
        on a horizontal or vertical wire segment (not at either endpoint).
        """
        if abs(y1 - y2) < eps:  # horizontal wire
            if abs(py - y1) > eps:
                return False
            lo, hi = min(x1, x2), max(x1, x2)
            return lo + eps < px < hi - eps
        if abs(x1 - x2) < eps:  # vertical wire
            if abs(px - x1) > eps:
                return False
            lo, hi = min(y1, y2), max(y1, y2)
            return lo + eps < py < hi - eps
        return False

    @staticmethod
    def _make_wire_sexp(
        start: List[float],
        end: List[float],
        stroke_width: float = 0,
        stroke_type: str = "default",
    ) -> list:
        return [
            _SYM_WIRE,
            [_SYM_PTS, [_SYM_XY, start[0], start[1]], [_SYM_XY, end[0], end[1]]],
            [_SYM_STROKE, [_SYM_WIDTH, stroke_width], [_SYM_TYPE, Symbol(stroke_type)]],
            [_SYM_UUID, str(uuid.uuid4())],
        ]

    @staticmethod
    def _break_wires_at_point(sch_data: list, position: List[float]) -> int:
        """
        Split any wire segment that passes through *position* as a strict
        midpoint (i.e. position is not an existing endpoint).  Mirrors
        KiCAD's SCH_LINE_WIRE_BUS_TOOL::BreakSegments behaviour.

        Returns the number of wires split.
        """
        px, py = float(position[0]), float(position[1])
        splits = 0
        i = 0
        while i < len(sch_data):
            parsed = WireManager._parse_wire(sch_data[i])
            if parsed is not None:
                (x1, y1), (x2, y2), stroke_width, stroke_type = parsed
                if WireManager._point_strictly_on_wire(px, py, x1, y1, x2, y2):
                    seg_a = WireManager._make_wire_sexp(
                        [x1, y1], [px, py], stroke_width, stroke_type
                    )
                    seg_b = WireManager._make_wire_sexp(
                        [px, py], [x2, y2], stroke_width, stroke_type
                    )
                    sch_data[i : i + 1] = [seg_a, seg_b]
                    logger.info(f"Split wire ({x1},{y1})->({x2},{y2}) at ({px},{py})")
                    splits += 1
                    i += 2  # skip the two new segments
                    continue
            i += 1
        return splits

    @staticmethod
    def _collect_wire_endpoints(sch_data: list) -> List[Tuple[float, float]]:
        """Return all (x, y) endpoints for every wire in sch_data."""
        endpoints: List[Tuple[float, float]] = []
        for item in sch_data:
            parsed = WireManager._parse_wire(item)
            if parsed is not None:
                (x1, y1), (x2, y2), _, _ = parsed
                endpoints.append((x1, y1))
                endpoints.append((x2, y2))
        return endpoints

    @staticmethod
    def _get_existing_junctions(sch_data: list) -> dict:
        """Return {(iu_x, iu_y): index_in_sch_data} for every junction element."""
        result: dict = {}
        for i, item in enumerate(sch_data):
            if not (isinstance(item, list) and len(item) > 0 and item[0] == _SYM_JUNCTION):
                continue
            at_entry = next(
                (p for p in item[1:] if isinstance(p, list) and len(p) >= 3 and p[0] == _SYM_AT),
                None,
            )
            if at_entry is None:
                continue
            x, y = float(at_entry[1]), float(at_entry[2])
            result[(round(x * _IU_PER_MM), round(y * _IU_PER_MM))] = i
        return result

    @staticmethod
    def _make_junction_sexp(x: float, y: float, diameter: float = 0) -> list:
        return [
            _SYM_JUNCTION,
            [_SYM_AT, x, y],
            [Symbol("diameter"), diameter],
            [Symbol("color"), 0, 0, 0, 0],
            [_SYM_UUID, str(uuid.uuid4())],
        ]

    @staticmethod
    def _parse_lib_pins(sym_def: list, unit: int = 1) -> List[Tuple[float, float]]:
        """Extract pin local (x, y) positions for *unit* from a lib_symbols symbol definition.

        Only collects pins from sub-unit symbols whose parsed unit number matches *unit*
        OR is 0 (the "common" body drawn on every unit, e.g. power pins on an op-amp).
        Sub-units whose unit index is neither *unit* nor 0 are skipped entirely.

        If the lib_symbols entry has no nested (symbol ...) children at all (rare, simple
        defs), falls back to collecting every (pin ...) directly from the top-level entry.

        Uses a stack instead of recursion to handle nested sub-unit symbols.
        """
        pins: List[Tuple[float, float]] = []

        # Separate top-level direct children into sub-unit symbols vs other nodes.
        sub_units: list = []
        direct_pins: list = []
        for child in sym_def[1:]:
            if not isinstance(child, list) or not child:
                continue
            if child[0] == _SYM_SYMBOL:
                sub_units.append(child)
            elif child[0] == _SYM_PIN:
                direct_pins.append(child)

        if not sub_units:
            # Fallback: simple definition with no nested sub-unit symbols — collect all pins.
            nodes_to_search = direct_pins
        else:
            # Filter sub-units by parsed unit number.
            nodes_to_search = []
            for sub in sub_units:
                sub_name = (
                    sub[1]
                    if len(sub) > 1 and isinstance(sub[1], str)
                    else str(sub[1]) if len(sub) > 1 else ""
                )
                m = WireManager._SUB_UNIT_RE.match(sub_name)
                if m:
                    sub_unit_num = int(m.group(2))
                    if sub_unit_num == unit or sub_unit_num == 0:
                        nodes_to_search.extend(sub[1:])
                else:
                    # Name doesn't match the expected pattern — include it (fail-safe).
                    logger.debug(
                        "lib_symbols sub-unit name %r did not match <base>_<unit>_<style>; "
                        "including all its pins as fallback",
                        sub_name,
                    )
                    nodes_to_search.extend(sub[1:])

        # Walk the selected nodes to collect (pin ...) entries via stack.
        stack: list = list(nodes_to_search)
        while stack:
            node = stack.pop()
            if not isinstance(node, list) or not node:
                continue
            if node[0] == _SYM_PIN:
                at = next(
                    (
                        p
                        for p in node[1:]
                        if isinstance(p, list) and len(p) >= 3 and p[0] == _SYM_AT
                    ),
                    None,
                )
                if at:
                    pins.append((float(at[1]), float(at[2])))
                continue  # don't recurse into pin sub-expressions
            stack.extend(node[1:])
        return pins

    @staticmethod
    def _collect_pin_positions(sch_data: list) -> List[Tuple[float, float]]:
        """Return world (x, y) positions for every placed component pin in sch_data.

        Parses lib_symbols for pin local coordinates (unit-aware), then applies the KiCad
        transform chain (y-negate → mirror → rotate → translate) to each pin.
        """
        # Build {lib_id: sym_def} from the embedded lib_symbols section.
        # We defer pin extraction until we know which unit each placed instance uses.
        lib_sym_defs: dict = {}
        for item in sch_data:
            if not (isinstance(item, list) and len(item) > 0 and item[0] == _SYM_LIB_SYMBOLS):
                continue
            for sym_def in item[1:]:
                if not (
                    isinstance(sym_def, list) and len(sym_def) > 1 and sym_def[0] == _SYM_SYMBOL
                ):
                    continue
                lib_id = sym_def[1] if isinstance(sym_def[1], str) else str(sym_def[1])
                lib_sym_defs[lib_id] = sym_def
            break

        # Transform each placed symbol's pins to world coordinates
        world_positions: List[Tuple[float, float]] = []
        for item in sch_data:
            if not (isinstance(item, list) and len(item) > 0 and item[0] == _SYM_SYMBOL):
                continue
            lib_id_part = next(
                (
                    p
                    for p in item[1:]
                    if isinstance(p, list) and len(p) >= 2 and p[0] == _SYM_LIB_ID
                ),
                None,
            )
            if lib_id_part is None:
                continue  # not a placed instance (e.g. sub-unit inside lib_symbols)
            lib_id = lib_id_part[1] if isinstance(lib_id_part[1], str) else str(lib_id_part[1])

            # Read the placed unit number (default 1 for single-unit parts).
            unit_part = next(
                (p for p in item[1:] if isinstance(p, list) and len(p) >= 2 and p[0] == _SYM_UNIT),
                None,
            )
            unit_num = int(unit_part[1]) if unit_part is not None else 1

            at_part = next(
                (p for p in item[1:] if isinstance(p, list) and len(p) >= 3 and p[0] == _SYM_AT),
                None,
            )
            if at_part is None:
                continue
            sym_x, sym_y = float(at_part[1]), float(at_part[2])
            rotation = float(at_part[3]) if len(at_part) > 3 else 0.0

            mirror_x = mirror_y = False
            for part in item[1:]:
                if isinstance(part, list) and len(part) >= 2 and part[0] == _SYM_MIRROR:
                    if part[1] == Symbol("x"):
                        mirror_x = True
                    elif part[1] == Symbol("y"):
                        mirror_y = True

            sym_def = lib_sym_defs.get(lib_id)
            if sym_def is None:
                continue
            local_pins = WireManager._parse_lib_pins(sym_def, unit=unit_num)

            for lx, ly in local_pins:
                # KiCad lib uses y-up; schematic uses y-down — negate before transform
                ly = -ly
                if mirror_x:
                    ly = -ly
                if mirror_y:
                    lx = -lx
                if rotation != 0.0:
                    rad = math.radians(rotation)
                    c, s = math.cos(rad), math.sin(rad)
                    lx, ly = lx * c - ly * s, lx * s + ly * c
                world_positions.append((sym_x + lx, sym_y + ly))

        return world_positions

    @staticmethod
    def sync_junctions(sch_data: list) -> Tuple[int, int]:
        """Add missing junctions and remove stale ones in sch_data in-place.

        A junction is needed at any point where the total of wire endpoints plus
        component pin positions is ≥ 3 and at least one wire endpoint is present.
        This covers wire-only T/X junctions and wire-meets-pin-with-another-wire cases.

        Returns (added_count, removed_count).
        """
        from collections import Counter

        wire_endpoints = WireManager._collect_wire_endpoints(sch_data)
        wire_iu: Counter = Counter(
            (round(x * _IU_PER_MM), round(y * _IU_PER_MM)) for x, y in wire_endpoints
        )

        pin_positions = WireManager._collect_pin_positions(sch_data)
        pin_iu: Counter = Counter(
            (round(x * _IU_PER_MM), round(y * _IU_PER_MM)) for x, y in pin_positions
        )

        # wire_iu.items() guarantees wire_cnt >= 1, so no extra guard needed
        needed_iu = {iu for iu, wire_cnt in wire_iu.items() if wire_cnt + pin_iu.get(iu, 0) >= 3}

        existing = WireManager._get_existing_junctions(sch_data)
        existing_iu = set(existing.keys())

        # Remove stale junctions; work in reverse index order to avoid shifting
        stale_indices = sorted([existing[iu] for iu in existing_iu - needed_iu], reverse=True)
        for idx in stale_indices:
            del sch_data[idx]
        removed = len(stale_indices)

        # Locate insertion point for new junctions
        sheet_instances_index = None
        for i, item in enumerate(sch_data):
            if isinstance(item, list) and len(item) > 0 and item[0] == _SYM_SHEET_INSTANCES:
                sheet_instances_index = i
                break

        to_add = needed_iu - existing_iu
        added = 0
        if to_add:
            if sheet_instances_index is None:
                logger.warning("sync_junctions: no sheet_instances found, skipping junction insert")
            else:
                for iu_x, iu_y in to_add:
                    x = iu_x / _IU_PER_MM
                    y = iu_y / _IU_PER_MM
                    sch_data.insert(sheet_instances_index, WireManager._make_junction_sexp(x, y))
                    sheet_instances_index += 1
                    added += 1

        if added or removed:
            logger.info(f"sync_junctions: added {added}, removed {removed}")
        return added, removed

    @staticmethod
    def add_no_connect(schematic_path: Path, position: List[float]) -> bool:
        """
        Add a no-connect flag to the schematic

        Args:
            schematic_path: Path to .kicad_sch file
            position: [x, y] coordinates for no-connect flag

        Returns:
            True if successful, False otherwise
        """
        try:
            # Read schematic
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            # Create no_connect S-expression
            # Format: (no_connect (at x y) (uuid ...))
            no_connect_sexp = [
                Symbol("no_connect"),
                [Symbol("at"), position[0], position[1]],
                [Symbol("uuid"), str(uuid.uuid4())],
            ]

            # Find insertion point
            sheet_instances_index = None
            for i, item in enumerate(sch_data):
                if isinstance(item, list) and len(item) > 0 and item[0] == _SYM_SHEET_INSTANCES:
                    sheet_instances_index = i
                    break

            if sheet_instances_index is None:
                logger.error("No sheet_instances section found in schematic")
                return False

            # Insert no_connect
            sch_data.insert(sheet_instances_index, no_connect_sexp)
            logger.info(f"Injected no-connect at {position}")

            # Write back
            with open(schematic_path, "w", encoding="utf-8") as f:
                output = sexpdata.dumps(sch_data)
                f.write(output)

            logger.info(f"Successfully added no-connect to {schematic_path.name}")
            return True

        except Exception as e:
            logger.error(f"Error adding no-connect: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def delete_wire(
        schematic_path: Path,
        start_point: List[float],
        end_point: List[float],
        tolerance: float = 0.5,
    ) -> bool:
        """
        Delete a wire from the schematic matching given start/end coordinates.

        Args:
            schematic_path: Path to .kicad_sch file
            start_point: [x, y] coordinates for wire start
            end_point: [x, y] coordinates for wire end
            tolerance: Maximum coordinate difference to consider a match (mm)

        Returns:
            True if a wire was found and removed, False otherwise
        """
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            sx, sy = start_point
            ex, ey = end_point

            for i, item in enumerate(sch_data):
                if not (isinstance(item, list) and len(item) > 0 and item[0] == _SYM_WIRE):
                    continue

                # Extract pts from the wire s-expression
                pts_list = None
                for part in item[1:]:
                    if isinstance(part, list) and len(part) > 0 and part[0] == _SYM_PTS:
                        pts_list = part
                        break

                if pts_list is None:
                    continue

                xy_points = [
                    p
                    for p in pts_list[1:]
                    if isinstance(p, list) and len(p) >= 3 and p[0] == _SYM_XY
                ]
                if len(xy_points) < 2:
                    continue

                x1, y1 = float(xy_points[0][1]), float(xy_points[0][2])
                x2, y2 = float(xy_points[-1][1]), float(xy_points[-1][2])

                match_fwd = (
                    abs(x1 - sx) < tolerance
                    and abs(y1 - sy) < tolerance
                    and abs(x2 - ex) < tolerance
                    and abs(y2 - ey) < tolerance
                )
                match_rev = (
                    abs(x1 - ex) < tolerance
                    and abs(y1 - ey) < tolerance
                    and abs(x2 - sx) < tolerance
                    and abs(y2 - sy) < tolerance
                )

                if match_fwd or match_rev:
                    del sch_data[i]
                    WireManager.sync_junctions(sch_data)
                    with open(schematic_path, "w", encoding="utf-8") as f:
                        f.write(sexpdata.dumps(sch_data))
                    logger.info(f"Deleted wire from {start_point} to {end_point}")
                    return True

            logger.warning(f"No matching wire found for {start_point} to {end_point}")
            return False

        except Exception as e:
            logger.error(f"Error deleting wire: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def delete_label(
        schematic_path: Path,
        net_name: str,
        position: Optional[List[float]] = None,
        tolerance: float = 0.5,
    ) -> bool:
        """
        Delete a net label from the schematic by name (and optionally position).

        Args:
            schematic_path: Path to .kicad_sch file
            net_name: Net label text to match
            position: Optional [x, y] to disambiguate when multiple labels share a name
            tolerance: Maximum coordinate difference to consider a match (mm)

        Returns:
            True if a label was found and removed, False otherwise
        """
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            _LABEL_TYPES = {_SYM_LABEL, _SYM_GLOBAL_LABEL, _SYM_HIERARCHICAL_LABEL}
            for i, item in enumerate(sch_data):
                if not (isinstance(item, list) and len(item) > 0 and item[0] in _LABEL_TYPES):
                    continue

                # Second element is the label text
                if len(item) < 2 or item[1] != net_name:
                    continue

                if position is not None:
                    # Find (at x y ...) sub-expression and check coordinates
                    at_entry = next(
                        (
                            p
                            for p in item[1:]
                            if isinstance(p, list) and len(p) >= 3 and p[0] == _SYM_AT
                        ),
                        None,
                    )
                    if at_entry is None:
                        continue
                    lx, ly = float(at_entry[1]), float(at_entry[2])
                    if not (
                        abs(lx - position[0]) < tolerance and abs(ly - position[1]) < tolerance
                    ):
                        continue

                del sch_data[i]
                with open(schematic_path, "w", encoding="utf-8") as f:
                    f.write(sexpdata.dumps(sch_data))
                logger.info(f"Deleted label '{net_name}'")
                return True

            logger.warning(f"No matching label found for '{net_name}'")
            return False

        except Exception as e:
            logger.error(f"Error deleting label: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def create_orthogonal_path(
        start: List[float], end: List[float], prefer_horizontal_first: bool = True
    ) -> List[List[float]]:
        """
        Create an orthogonal (right-angle) path between two points

        Args:
            start: [x, y] start coordinates
            end: [x, y] end coordinates
            prefer_horizontal_first: If True, route horizontally first, else vertically first

        Returns:
            List of points defining the path: [start, corner, end]
        """
        x1, y1 = start
        x2, y2 = end

        if prefer_horizontal_first:
            # Route: start → (x2, y1) → end
            corner = [x2, y1]
        else:
            # Route: start → (x1, y2) → end
            corner = [x1, y2]

        # If start and end are already aligned, return direct path
        if x1 == x2 or y1 == y2:
            return [start, end]

        return [start, corner, end]

    @staticmethod
    def list_texts(schematic_path: Path) -> Optional[List[Any]]:
        """Return all free-form text annotations (SCH_TEXT) in a schematic.

        Each entry is a dict with keys: text, position (x/y), angle,
        font_size, bold, italic, justify, uuid.
        Returns None on parse error.
        """
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_data = sexpdata.loads(f.read())

            _SYM_TEXT = Symbol("text")
            _SYM_EFFECTS = Symbol("effects")
            _SYM_FONT = Symbol("font")
            _SYM_SIZE = Symbol("size")
            _SYM_JUSTIFY = Symbol("justify")
            _SYM_BOLD = Symbol("bold")
            _SYM_ITALIC = Symbol("italic")

            results = []
            for item in sch_data:
                if not (isinstance(item, list) and len(item) >= 2 and item[0] == _SYM_TEXT):
                    continue
                # item[1] is the text string
                text_val = item[1] if len(item) > 1 else ""

                pos_x = pos_y = angle = 0.0
                font_size = 1.27
                bold = italic = False
                justify = "left"
                uid = ""

                for part in item[2:]:
                    if not isinstance(part, list) or not part:
                        continue
                    tag = part[0]
                    if tag == _SYM_AT and len(part) >= 3:
                        pos_x = float(part[1])
                        pos_y = float(part[2])
                        angle = float(part[3]) if len(part) >= 4 else 0.0
                    elif tag == _SYM_UUID and len(part) >= 2:
                        uid = str(part[1])
                    elif tag == _SYM_EFFECTS:
                        for eff in part[1:]:
                            if not isinstance(eff, list) or not eff:
                                continue
                            if eff[0] == _SYM_FONT:
                                for fp in eff[1:]:
                                    if not isinstance(fp, list) or not fp:
                                        continue
                                    if fp[0] == _SYM_SIZE and len(fp) >= 2:
                                        font_size = float(fp[1])
                                    elif fp[0] == _SYM_BOLD and len(fp) >= 2:
                                        bold = str(fp[1]).lower() == "yes"
                                    elif fp[0] == _SYM_ITALIC and len(fp) >= 2:
                                        italic = str(fp[1]).lower() == "yes"
                            elif eff[0] == _SYM_JUSTIFY and len(eff) >= 2:
                                justify = str(eff[1])

                results.append(
                    {
                        "text": text_val,
                        "position": {"x": pos_x, "y": pos_y},
                        "angle": angle,
                        "font_size": font_size,
                        "bold": bold,
                        "italic": italic,
                        "justify": justify,
                        "uuid": uid,
                    }
                )
            return results
        except Exception as e:
            logger.error(f"Error listing texts: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return None

    @staticmethod
    def add_text(
        schematic_path: Path,
        text: str,
        position: List[float],
        angle: float = 0,
        font_size: float = 1.27,
        bold: bool = False,
        italic: bool = False,
        justify: str = "left",
    ) -> bool:
        """Add a free-form text annotation (SCH_TEXT) to a KiCad schematic."""
        try:
            text_escaped = text.replace("\\", "\\\\").replace('"', '\\"')
            uid = str(uuid.uuid4())
            font_attrs = f"\n\t\t\t\t(size {font_size} {font_size})"
            if bold:
                font_attrs += "\n\t\t\t\t(bold yes)"
            if italic:
                font_attrs += "\n\t\t\t\t(italic yes)"
            text_sexp = (
                f'\t(text "{text_escaped}"\n'
                f"\t\t(exclude_from_sim no)\n"
                f"\t\t(at {position[0]} {position[1]} {angle})\n"
                f"\t\t(effects\n"
                f"\t\t\t(font{font_attrs}\n"
                f"\t\t\t)\n"
                f"\t\t\t(justify {justify} bottom)\n"
                f"\t\t)\n"
                f'\t\t(uuid "{uid}")\n'
                f"\t)\n"
            )
            _text_insert(schematic_path, text_sexp)
            logger.info(f"Added text '{text}' at {position}")
            return True
        except Exception as e:
            logger.error(f"Error adding text: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_hierarchical_label(
        schematic_path: Path,
        text: str,
        position: List[float],
        shape: str = "bidirectional",
        orientation: int = 0,
    ) -> bool:
        """Add a hierarchical label to a sub-sheet schematic."""
        try:
            label_text = _make_hierarchical_label_text(text, position, shape, orientation)
            _text_insert(schematic_path, label_text)
            logger.info(f"Added hierarchical_label '{text}' at {position} shape={shape}")
            return True
        except Exception as e:
            logger.error(f"Error adding hierarchical label: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_sheet_pin(
        content: str,
        sheet_name: str,
        pin_name: str,
        pin_type: str,
        position: List[float],
        orientation: int = 0,
    ) -> Tuple[str, bool]:
        """Insert a sheet pin into the named sheet block in the parent schematic.

        Returns (modified_content, success).
        """
        lines = content.split("\n")
        sheetname_pattern = re.compile(
            r'\(property\s+"Sheetname"\s+"' + re.escape(sheet_name) + r'"'
        )
        sheet_block_pattern = re.compile(r"^\t\(sheet\b")

        # Find the sheet block that contains the target Sheetname property
        i = 0
        while i < len(lines):
            if sheet_block_pattern.match(lines[i]):
                # Walk forward to find closing paren of this block
                depth = sum(1 for c in lines[i] if c == "(") - sum(1 for c in lines[i] if c == ")")
                j = i + 1
                found_name = False
                while j < len(lines) and depth > 0:
                    if sheetname_pattern.search(lines[j]):
                        found_name = True
                    depth += sum(1 for c in lines[j] if c == "(") - sum(
                        1 for c in lines[j] if c == ")"
                    )
                    j += 1
                b_end = j - 1  # index of closing ")" line of the sheet block

                if found_name:
                    # Insert pin text before the closing paren of the sheet block
                    pin_text = _make_sheet_pin_text(pin_name, pin_type, position, orientation)
                    pin_lines = pin_text.rstrip("\n").split("\n")
                    for offset, line in enumerate(pin_lines):
                        lines.insert(b_end + offset, line)
                    logger.info(f"Added sheet pin '{pin_name}' to sheet '{sheet_name}'")
                    return "\n".join(lines), True

                i = b_end + 1
                continue
            i += 1

        return content, False


if __name__ == "__main__":
    # Test wire creation
    import shutil
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))

    print("=" * 80)
    print("WIRE MANAGER TEST")
    print("=" * 80)

    # Create test schematic (cross-platform temp directory)
    test_path = Path(tempfile.gettempdir()) / "test_wire_manager.kicad_sch"
    template_path = Path(__file__).parent.parent / "templates" / "empty.kicad_sch"

    shutil.copy(template_path, test_path)
    print(f"\n✓ Created test schematic: {test_path}")

    # Test 1: Add simple wire
    print("\n[1/4] Testing simple wire creation...")
    success = WireManager.add_wire(test_path, [50.8, 50.8], [101.6, 50.8])
    print(f"  {'✓' if success else '✗'} Simple wire: {success}")

    # Test 2: Add orthogonal wire
    print("\n[2/4] Testing orthogonal wire...")
    path = WireManager.create_orthogonal_path([50.8, 60.96], [101.6, 88.9])
    print(f"  Orthogonal path: {path}")
    success = WireManager.add_polyline_wire(test_path, path)
    print(f"  {'✓' if success else '✗'} Polyline wire: {success}")

    # Test 3: Add label
    print("\n[3/4] Testing label creation...")
    success = WireManager.add_label(test_path, "VCC", [76.2, 50.8])
    print(f"  {'✓' if success else '✗'} Label: {success}")

    # Test 4: Add no-connect
    print("\n[4/4] Testing no-connect creation...")
    success = WireManager.add_no_connect(test_path, [127, 50.8])
    print(f"  {'✓' if success else '✗'} No-connect: {success}")

    # Verify with kicad-skip
    print("\n[Verification] Loading with kicad-skip...")
    try:
        from skip import Schematic

        sch = Schematic(str(test_path))
        wire_count = len(list(sch.wire)) if hasattr(sch, "wire") else 0
        print(f"  ✓ Loaded successfully")
        print(f"  ✓ Wire count: {wire_count}")
    except Exception as e:
        print(f"  ✗ Failed: {e}")

    print("\n" + "=" * 80)
    print(f"Test schematic saved: {test_path}")
    print("Open in KiCad to verify visual appearance!")
    print("=" * 80)
