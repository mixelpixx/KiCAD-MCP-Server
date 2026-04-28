"""
WireDragger — drag connected wires when a schematic component is moved.

All methods operate on in-memory sexpdata lists (no disk I/O).
"""

import logging
import math
import uuid
from typing import Any, Dict, List, Optional, Tuple

import sexpdata
from sexpdata import Symbol

logger = logging.getLogger("kicad_interface")

# Module-level Symbol constants
_K = {
    name: Symbol(name)
    for name in [
        "symbol",
        "at",
        "lib_id",
        "mirror",
        "lib_symbols",
        "pts",
        "xy",
        "wire",
        "junction",
        "property",
        "stroke",
        "width",
        "type",
        "uuid",
    ]
}

EPS = 1e-4  # mm — coordinate match tolerance


def _rotate(x: float, y: float, angle_deg: float) -> Tuple[float, float]:
    """Rotate (x, y) around the origin by angle_deg degrees (CCW)."""
    if angle_deg == 0:
        return x, y
    rad = math.radians(angle_deg)
    c, s = math.cos(rad), math.sin(rad)
    return x * c - y * s, x * s + y * c


def _coords_match(ax: float, ay: float, bx: float, by: float, eps: float = EPS) -> bool:
    return abs(ax - bx) < eps and abs(ay - by) < eps


class WireDragger:
    """Pure-logic helpers for wire-endpoint dragging during component moves."""

    @staticmethod
    def find_symbol(sch_data: list, reference: str) -> Any:
        """
        Find a placed symbol by reference designator.

        Returns (symbol_item, old_x, old_y, rotation, lib_id, mirror_x, mirror_y)
        or None if the reference is not found.

        mirror_x=True means the symbol has (mirror x) — flips the X local axis.
        mirror_y=True means the symbol has (mirror y) — flips the Y local axis.
        """
        sym_k = _K["symbol"]
        prop_k = _K["property"]
        at_k = _K["at"]
        lib_id_k = _K["lib_id"]
        mirror_k = _K["mirror"]

        for item in sch_data:
            if not (isinstance(item, list) and item and item[0] == sym_k):
                continue

            # Check Reference property
            ref_val = None
            for sub in item[1:]:
                if isinstance(sub, list) and len(sub) >= 3 and sub[0] == prop_k:
                    if str(sub[1]).strip('"') == "Reference":
                        ref_val = str(sub[2]).strip('"')
                        break
            if ref_val != reference:
                continue

            old_x = old_y = rotation = 0.0
            lib_id = ""
            mirror_x = mirror_y = False

            for sub in item[1:]:
                if not isinstance(sub, list) or not sub:
                    continue
                tag = sub[0]
                if tag == at_k:
                    if len(sub) >= 3:
                        old_x = float(sub[1])
                        old_y = float(sub[2])
                    if len(sub) >= 4:
                        rotation = float(sub[3])
                elif tag == lib_id_k and len(sub) >= 2:
                    lib_id = str(sub[1]).strip('"')
                elif tag == mirror_k and len(sub) >= 2:
                    mv = str(sub[1])
                    if mv == "x":
                        mirror_x = True
                    elif mv == "y":
                        mirror_y = True

            return item, old_x, old_y, rotation, lib_id, mirror_x, mirror_y

        return None

    @staticmethod
    def get_pin_defs(sch_data: list, lib_id: str) -> Dict:
        """
        Get pin definitions from lib_symbols for the given lib_id.

        Returns the same dict format as PinLocator.parse_symbol_definition:
        {pin_num: {"x": ..., "y": ..., ...}}.
        """
        from commands.pin_locator import PinLocator

        lib_sym_k = _K["lib_symbols"]
        symbol_k = _K["symbol"]

        for item in sch_data:
            if not (isinstance(item, list) and item and item[0] == lib_sym_k):
                continue
            for sym_def in item[1:]:
                if not (isinstance(sym_def, list) and sym_def and sym_def[0] == symbol_k):
                    continue
                if len(sym_def) < 2:
                    continue
                name = str(sym_def[1]).strip('"')
                if name == lib_id:
                    return PinLocator.parse_symbol_definition(sym_def)
            break  # only one lib_symbols section
        return {}

    @staticmethod
    def pin_world_xy(
        px: float,
        py: float,
        sym_x: float,
        sym_y: float,
        rotation: float,
        mirror_x: bool,
        mirror_y: bool,
    ) -> Tuple[float, float]:
        """
        Compute the world coordinate of a pin given the symbol transform.

        KiCAD applies mirror first (in local space), then rotation, then translation.
        mirror_x negates the local X axis; mirror_y negates the local Y axis.
        """
        lx, ly = px, py
        if mirror_x:
            lx = -lx
        if mirror_y:
            ly = -ly
        rx, ry = _rotate(lx, ly, rotation)
        return sym_x + rx, sym_y + ry

    @staticmethod
    def compute_pin_positions(
        sch_data: list,
        reference: str,
        new_x: float,
        new_y: float,
    ) -> Dict[str, Tuple[Tuple[float, float], Tuple[float, float]]]:
        """
        Compute world pin positions before and after a component move.

        Returns {pin_num: (old_world_xy, new_world_xy)}.
        old_world_xy uses the symbol's current position; new_world_xy uses (new_x, new_y).
        """
        found = WireDragger.find_symbol(sch_data, reference)
        if found is None:
            return {}
        _, old_x, old_y, rotation, lib_id, mirror_x, mirror_y = found

        pins = WireDragger.get_pin_defs(sch_data, lib_id)
        result: Dict[str, Tuple] = {}
        for pin_num, pin in pins.items():
            px, py = pin["x"], pin["y"]
            old_wx, old_wy = WireDragger.pin_world_xy(
                px, py, old_x, old_y, rotation, mirror_x, mirror_y
            )
            new_wx, new_wy = WireDragger.pin_world_xy(
                px, py, new_x, new_y, rotation, mirror_x, mirror_y
            )
            result[pin_num] = (
                (round(old_wx, 6), round(old_wy, 6)),
                (round(new_wx, 6), round(new_wy, 6)),
            )
        return result

    @staticmethod
    def drag_wires(
        sch_data: list,
        old_to_new: Dict[Tuple[float, float], Tuple[float, float]],
        eps: float = EPS,
    ) -> Dict:
        """
        Move wire endpoints and junctions from old positions to new positions.
        Removes zero-length wires that result from the move.
        Modifies sch_data in place.

        old_to_new: {(old_x, old_y): (new_x, new_y)}

        Returns {'endpoints_moved': N, 'wires_removed': M}.
        """
        wire_k = _K["wire"]
        pts_k = _K["pts"]
        xy_k = _K["xy"]
        junction_k = _K["junction"]
        at_k = _K["at"]

        def find_new(x: float, y: float) -> Optional[Tuple[float, float]]:
            for (ox, oy), (nx, ny) in old_to_new.items():
                if _coords_match(x, y, ox, oy, eps):
                    return nx, ny
            return None

        endpoints_moved = 0
        zero_length_indices = []

        # First pass: update wire endpoints
        for idx, item in enumerate(sch_data):
            if not (isinstance(item, list) and item and item[0] == wire_k):
                continue

            pts_sub = None
            for sub in item[1:]:
                if isinstance(sub, list) and sub and sub[0] == pts_k:
                    pts_sub = sub
                    break
            if pts_sub is None:
                continue

            xy_items = [
                p for p in pts_sub[1:] if isinstance(p, list) and len(p) >= 3 and p[0] == xy_k
            ]
            for xy_item in xy_items:
                nc = find_new(float(xy_item[1]), float(xy_item[2]))
                if nc is not None:
                    xy_item[1] = nc[0]
                    xy_item[2] = nc[1]
                    endpoints_moved += 1

            # Check if this wire is now zero-length
            if len(xy_items) >= 2:
                x1, y1 = float(xy_items[0][1]), float(xy_items[0][2])
                x2, y2 = float(xy_items[-1][1]), float(xy_items[-1][2])
                if _coords_match(x1, y1, x2, y2, eps):
                    zero_length_indices.append(idx)

        # Remove zero-length wires (backwards to preserve indices)
        for idx in reversed(zero_length_indices):
            del sch_data[idx]

        # Second pass: update junctions
        for item in sch_data:
            if not (isinstance(item, list) and item and item[0] == junction_k):
                continue
            for sub in item[1:]:
                if isinstance(sub, list) and sub and sub[0] == at_k and len(sub) >= 3:
                    nc = find_new(float(sub[1]), float(sub[2]))
                    if nc is not None:
                        sub[1] = nc[0]
                        sub[2] = nc[1]
                    break

        return {
            "endpoints_moved": endpoints_moved,
            "wires_removed": len(zero_length_indices),
        }

    @staticmethod
    def update_symbol_position(sch_data: list, reference: str, new_x: float, new_y: float) -> bool:
        """
        Update the (at x y rot) of the named symbol in sch_data.
        Returns True if the symbol was found and updated.
        """
        found = WireDragger.find_symbol(sch_data, reference)
        if found is None:
            return False
        item = found[0]
        at_k = _K["at"]
        prop_k = _K["property"]

        # Find current position and compute delta
        old_x = old_y = None
        for sub in item[1:]:
            if isinstance(sub, list) and sub and sub[0] == at_k and len(sub) >= 3:
                old_x, old_y = sub[1], sub[2]
                sub[1] = new_x
                sub[2] = new_y
                break
        if old_x is None or old_y is None:
            return False

        dx = new_x - old_x
        dy = new_y - old_y

        # Shift all property label positions by the same delta
        for sub in item[1:]:
            if isinstance(sub, list) and sub and sub[0] == prop_k:
                for psub in sub[1:]:
                    if isinstance(psub, list) and psub and psub[0] == at_k and len(psub) >= 3:
                        psub[1] += dx
                        psub[2] += dy
                        break
        return True

    @staticmethod
    def _make_wire_sexp(x1: float, y1: float, x2: float, y2: float) -> list:
        """Build a wire s-expression list in KiCAD schematic format."""
        wire_uuid = str(uuid.uuid4())
        return [
            _K["wire"],
            [_K["pts"], [_K["xy"], x1, y1], [_K["xy"], x2, y2]],
            [_K["stroke"], [_K["width"], 0], [_K["type"], Symbol("default")]],
            [_K["uuid"], wire_uuid],
        ]

    @staticmethod
    def get_all_stationary_pin_positions(
        sch_data: list,
        moved_reference: str,
    ) -> Dict[Tuple[float, float], str]:
        """
        Return a map of {world_xy: reference} for every pin of every symbol
        in sch_data *except* moved_reference.

        This is used to detect pins of stationary components that coincide
        with pins of the moved component (touching-pin connections).
        """
        sym_k = _K["symbol"]
        prop_k = _K["property"]
        result: Dict[Tuple[float, float], str] = {}

        for item in sch_data:
            if not (isinstance(item, list) and item and item[0] == sym_k):
                continue
            # Determine reference
            ref_val = None
            for sub in item[1:]:
                if isinstance(sub, list) and len(sub) >= 3 and sub[0] == prop_k:
                    if str(sub[1]).strip('"') == "Reference":
                        ref_val = str(sub[2]).strip('"')
                        break
            if ref_val is None or ref_val == moved_reference:
                continue
            # Skip template / power symbols whose references start with special chars
            # but we still want to handle them — no filtering needed here.

            # Find lib_id and position for this symbol
            found = WireDragger.find_symbol(sch_data, ref_val)
            if found is None:
                continue
            _, sx, sy, rotation, lib_id, mirror_x, mirror_y = found
            pins = WireDragger.get_pin_defs(sch_data, lib_id)
            for pin_num, pin in pins.items():
                wx, wy = WireDragger.pin_world_xy(
                    pin["x"], pin["y"], sx, sy, rotation, mirror_x, mirror_y
                )
                key = (round(wx, 6), round(wy, 6))
                result[key] = ref_val

        return result

    @staticmethod
    def synthesize_touching_pin_wires(
        sch_data: list,
        moved_reference: str,
        pin_positions: Dict[str, Tuple[Tuple[float, float], Tuple[float, float]]],
        eps: float = EPS,
    ) -> int:
        """
        Detect touching-pin connections and synthesize wire segments to bridge gaps
        created by moving a component.

        For each pin of *moved_reference* whose old world position coincides with
        a pin of a stationary component:
          - If the pin moved (old_xy != new_xy), insert a wire from old_xy to new_xy.
          - If the pin now lands on another stationary pin's position, skip (they touch again).
          - If old_xy == new_xy, do nothing (no gap was created).

        Modifies sch_data in place.
        Returns the number of wire segments synthesized.
        """
        if not pin_positions:
            return 0

        stationary_pins = WireDragger.get_all_stationary_pin_positions(sch_data, moved_reference)
        if not stationary_pins:
            return 0

        synthesized = 0

        for pin_num, (old_xy, new_xy) in pin_positions.items():
            # Check if a stationary pin touches this pin's old position
            touching = any(
                _coords_match(old_xy[0], old_xy[1], sx, sy, eps) for (sx, sy) in stationary_pins
            )
            if not touching:
                continue

            # The pin has moved — check if it actually separated
            if _coords_match(old_xy[0], old_xy[1], new_xy[0], new_xy[1], eps):
                # Pin didn't actually move; no gap
                continue

            # Check if the pin's new position happens to touch another stationary pin
            # (component moved into a different touching position — no wire needed)
            rejoining = any(
                _coords_match(new_xy[0], new_xy[1], sx, sy, eps) for (sx, sy) in stationary_pins
            )
            if rejoining:
                logger.debug(
                    f"Pin {moved_reference}/{pin_num} moved from {old_xy} to {new_xy} "
                    f"and rejoins another stationary pin; no wire synthesized"
                )
                continue

            logger.info(
                f"Synthesizing wire for touching-pin connection: "
                f"{moved_reference}/{pin_num} moved from {old_xy} to {new_xy}"
            )
            wire = WireDragger._make_wire_sexp(old_xy[0], old_xy[1], new_xy[0], new_xy[1])
            # Insert before the last item (sheet_instances) to keep file tidy,
            # but appending is also valid — just append.
            sch_data.append(wire)
            synthesized += 1

        return synthesized
