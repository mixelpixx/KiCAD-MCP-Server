"""
WireDragger — drag connected wires when a schematic component is moved.

All methods operate on in-memory sexpdata lists (no disk I/O).
"""

import math
import logging
from typing import Dict, Optional, Tuple

import sexpdata
from sexpdata import Symbol

logger = logging.getLogger("kicad_interface")

# Module-level Symbol constants
_K = {
    name: Symbol(name)
    for name in [
        "symbol", "at", "lib_id", "mirror", "lib_symbols",
        "pts", "xy", "wire", "junction", "property",
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


def _coords_match(ax: float, ay: float, bx: float, by: float,
                  eps: float = EPS) -> bool:
    return abs(ax - bx) < eps and abs(ay - by) < eps


class WireDragger:
    """Pure-logic helpers for wire-endpoint dragging during component moves."""

    @staticmethod
    def find_symbol(sch_data: list, reference: str):
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
        px: float, py: float,
        sym_x: float, sym_y: float,
        rotation: float,
        mirror_x: bool, mirror_y: bool,
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

        def find_new(x: float, y: float):
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
                p for p in pts_sub[1:]
                if isinstance(p, list) and len(p) >= 3 and p[0] == xy_k
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
    def update_symbol_position(
        sch_data: list, reference: str, new_x: float, new_y: float
    ) -> bool:
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
        if old_x is None:
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
