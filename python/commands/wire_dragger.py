"""
WireDragger — drag connected wires when a schematic component is moved.

All methods operate on in-memory sexpdata lists (no disk I/O).
"""

import logging
import math
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

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
        "label",
        "global_label",
        "hierarchical_label",
        "no_connect",
        "property",
        "unit",
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
    def find_symbol(sch_data: list, reference: str, unit: Optional[int] = None) -> Any:
        """
        Find a placed symbol by reference designator.

        Returns (symbol_item, old_x, old_y, rotation, lib_id, mirror_x, mirror_y)
        or None if the reference is not found.

        unit: for a multi-unit part every unit is placed as its own (symbol ...)
            block under one shared reference (U201 A-E), so a bare reference is
            ambiguous — which block you get depends on file order. Passing the
            unit number selects a specific one; None keeps the historical
            first-match behaviour, which is exact for single-unit parts.

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

            # Check Reference property.
            # kicad-skip may write a trailing "_" on references (e.g. "R1_") when
            # cloning symbols; strip it so callers passing the canonical "R1"
            # still find the symbol. Mirrors the rstrip in PinLocator.get_pin_location.
            ref_val = None
            for sub in item[1:]:
                if isinstance(sub, list) and len(sub) >= 3 and sub[0] == prop_k:
                    if str(sub[1]).strip('"') == "Reference":
                        ref_val = str(sub[2]).strip('"')
                        break
            if ref_val is None or ref_val.rstrip("_") != reference:
                continue

            if unit is not None and WireDragger._symbol_unit(item) != int(unit):
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
    def _symbol_unit(item: list) -> Optional[int]:
        """Return the (unit N) of a placed symbol block, or None if absent."""
        unit_k = _K["unit"]
        for sub_item in item[1:]:
            if isinstance(sub_item, list) and sub_item and sub_item[0] == unit_k:
                if len(sub_item) >= 2:
                    try:
                        return int(sub_item[1])
                    except (TypeError, ValueError):
                        return None
        return None

    @staticmethod
    def list_symbol_units(sch_data: list, reference: str) -> List[int]:
        """Return the units placed for *reference*, in file order.

        Used to tell a caller which units exist when it has to pick one.
        """
        sym_k = _K["symbol"]
        prop_k = _K["property"]
        units: List[int] = []
        for item in sch_data:
            if not (isinstance(item, list) and item and item[0] == sym_k):
                continue
            ref_val = None
            for sub_item in item[1:]:
                if isinstance(sub_item, list) and len(sub_item) >= 3 and sub_item[0] == prop_k:
                    if str(sub_item[1]).strip('"') == "Reference":
                        ref_val = str(sub_item[2]).strip('"')
                        break
            if ref_val is None or ref_val.rstrip("_") != reference:
                continue
            u = WireDragger._symbol_unit(item)
            if u is not None:
                units.append(u)
        return units

    @staticmethod
    def get_pin_defs(sch_data: list, lib_id: str, unit: Optional[int] = None) -> Dict:
        """
        Get pin definitions from lib_symbols for the given lib_id.

        Returns the same dict format as PinLocator.parse_symbol_definition:
        {pin_num: {"x": ..., "y": ..., ...}}.

        unit: keep only the pins belonging to that unit (plus unit 0, which is
            common to every unit). Without it a multi-unit part reports all its
            pins for one placement, and the caller would drag wires attached to
            units that never moved.
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
                    pins = PinLocator.parse_symbol_definition(sym_def)
                    if unit is None:
                        return pins
                    return {
                        num: pin
                        for num, pin in pins.items()
                        if pin.get("unit") in (0, None, int(unit))
                    }
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

        Library pins are stored Y-up; the schematic is Y-down. Order matches
        eeschema: Y-flip to screen → rotate (screen-CCW) → mirror → translate.

        eeschema's TRANSFORM matrix for rotation 90 is (0, 1, -1, 0) —
        i.e. screen-CCW in Y-down: (x, y) → (y, -x). Our `_rotate` helper is
        standard math (Y-up CCW), so we negate the rotation angle to convert.

        Mirror axis semantics match eeschema's symbol.h:
          (mirror x) = SYM_MIRROR_X = TRANSFORM(1, 0, 0, -1) → negates Y.
          (mirror y) = SYM_MIRROR_Y = TRANSFORM(-1, 0, 0, 1) → negates X.
        """
        lx, ly = px, -py  # Y-flip: lib Y-up → screen Y-down
        rx, ry = _rotate(lx, ly, -rotation)  # negate angle: math-CCW → screen-CCW
        # Mirror reflects the *placed* (already-rotated) symbol — i.e. in screen
        # space, AFTER the rotation. Applying it before the rotation only agrees
        # for 0°/180° turns; for 90°/270° it swaps the pins (verified against the
        # kicad-cli netlist in test_pin_world_xy_eeschema_truth).
        if mirror_x:
            ry = -ry  # SYM_MIRROR_X negates screen-Y
        if mirror_y:
            rx = -rx  # SYM_MIRROR_Y negates screen-X
        return sym_x + rx, sym_y + ry

    @staticmethod
    def compute_pin_positions(
        sch_data: list,
        reference: str,
        new_x: float,
        new_y: float,
        unit: Optional[int] = None,
    ) -> Dict[str, Tuple[Tuple[float, float], Tuple[float, float]]]:
        """
        Compute world pin positions before and after a component move.

        Returns {pin_num: (old_world_xy, new_world_xy)}.
        old_world_xy uses the symbol's current position; new_world_xy uses (new_x, new_y).
        """
        found = WireDragger.find_symbol(sch_data, reference, unit)
        if found is None:
            return {}
        _, old_x, old_y, rotation, lib_id, mirror_x, mirror_y = found

        pins = WireDragger.get_pin_defs(sch_data, lib_id, unit)
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
    def compute_pin_positions_for_rotation(
        sch_data: list,
        reference: str,
        new_rotation: float,
        new_mirror_x: bool,
        new_mirror_y: bool,
        unit: Optional[int] = None,
    ) -> Dict[str, Tuple[Tuple[float, float], Tuple[float, float]]]:
        """
        Compute world pin positions before and after a rotation/mirror change.

        The symbol stays at the same (x, y); only the rotation and mirror state change.
        Returns {pin_num: (old_world_xy, new_world_xy)}.
        """
        found = WireDragger.find_symbol(sch_data, reference, unit)
        if found is None:
            return {}
        _, sym_x, sym_y, old_rotation, lib_id, old_mirror_x, old_mirror_y = found

        pins = WireDragger.get_pin_defs(sch_data, lib_id, unit)
        result: Dict[str, Tuple] = {}
        for pin_num, pin in pins.items():
            px, py = pin["x"], pin["y"]
            old_wx, old_wy = WireDragger.pin_world_xy(
                px, py, sym_x, sym_y, old_rotation, old_mirror_x, old_mirror_y
            )
            new_wx, new_wy = WireDragger.pin_world_xy(
                px, py, sym_x, sym_y, new_rotation, new_mirror_x, new_mirror_y
            )
            result[pin_num] = (
                (round(old_wx, 6), round(old_wy, 6)),
                (round(new_wx, 6), round(new_wy, 6)),
            )
        return result

    @staticmethod
    def update_symbol_rotation_mirror(
        sch_data: list,
        reference: str,
        new_rotation: float,
        new_mirror: Optional[str],
        unit: Optional[int] = None,
    ) -> bool:
        """
        Update the rotation in (at x y rot) and the (mirror x/y) token for a symbol.

        new_mirror: "x", "y", or None (removes any existing mirror token).
        Returns True if the symbol was found and updated.
        """
        found = WireDragger.find_symbol(sch_data, reference, unit)
        if found is None:
            return False
        item = found[0]
        at_k = _K["at"]
        mirror_k = _K["mirror"]

        # Update rotation in (at x y rot). KiCad writes symbol angles as
        # integers (0/90/180/270), so normalize integral values to int to
        # match eeschema's output exactly (avoids a spurious "90.0" token).
        rot_val = int(new_rotation) if float(new_rotation).is_integer() else new_rotation
        for sub in item[1:]:
            if isinstance(sub, list) and sub and sub[0] == at_k and len(sub) >= 4:
                sub[3] = rot_val
                break

        # Remove existing (mirror ...) token(s)
        to_remove = [
            i for i, sub in enumerate(item) if isinstance(sub, list) and sub and sub[0] == mirror_k
        ]
        for i in reversed(to_remove):
            del item[i]

        # Insert new mirror token if requested
        if new_mirror in ("x", "y"):
            item.append([mirror_k, Symbol(new_mirror)])

        return True

    @staticmethod
    def drag_wires(
        sch_data: list,
        old_to_new: Dict[Tuple[float, float], Tuple[float, float]],
        eps: float = EPS,
        anchor_points: Optional[Set[Tuple[float, float]]] = None,
        straighten: bool = True,
    ) -> Dict:
        """
        Move wire endpoints, junctions, net labels and no-connect flags from old
        positions to new positions.
        Removes zero-length wires that result from the move.
        Modifies sch_data in place.

        old_to_new: {(old_x, old_y): (new_x, new_y)}
        anchor_points: coordinates that must not be shifted by the orthogonality
            pass — typically the pins of stationary symbols plus the moved
            symbol's own new pin positions.
        straighten: restore right angles on segments that the move turned
            diagonal (see :meth:`_straighten_bent_wires`).

        Returns {'endpoints_moved': N, 'wires_removed': M, 'labels_moved': L,
        'no_connects_moved': K, 'wires_straightened': S, 'wires_left_diagonal': D}.
        """
        wire_k = _K["wire"]
        pts_k = _K["pts"]
        xy_k = _K["xy"]
        junction_k = _K["junction"]
        at_k = _K["at"]
        no_connect_k = _K["no_connect"]
        label_ks = (_K["label"], _K["global_label"], _K["hierarchical_label"])

        # Snapshot every wire's endpoints before anything moves. The
        # orthogonality pass below needs to know which segments *used* to be
        # axis-aligned; once the first pass has run, that information is gone.
        pre_move: Dict[int, Tuple[Tuple[float, float], Tuple[float, float]]] = {}
        for item in sch_data:
            seg = WireDragger._wire_endpoints(item)
            if seg is not None:
                pre_move[id(item)] = seg

        def find_new(x: float, y: float) -> Optional[Tuple[float, float]]:
            for (ox, oy), (nx, ny) in old_to_new.items():
                if _coords_match(x, y, ox, oy, eps):
                    return nx, ny
            return None

        endpoints_moved = 0
        labels_moved = 0
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

        # Third pass: drag net labels that sit exactly on a moved pin so they
        # stay attached to it. Without this, a label coincident with a rotated
        # pin is left behind while the pin's wiring moves away — silently
        # re-netting it (e.g. a test-point label merging onto an adjacent rail).
        for item in sch_data:
            if not (isinstance(item, list) and item and item[0] in label_ks):
                continue
            for sub in item[1:]:
                if isinstance(sub, list) and sub and sub[0] == at_k and len(sub) >= 3:
                    nc = find_new(float(sub[1]), float(sub[2]))
                    if nc is not None:
                        sub[1] = nc[0]
                        sub[2] = nc[1]
                        labels_moved += 1
                    break

        # Fourth pass: drag no-connect flags sitting on a moved pin. A flag left
        # behind reads to KiCad as two separate errors — a dangling no-connect
        # where the flag stayed and an unconnected pin where the symbol went —
        # neither of which describes anything the user did.
        no_connects_moved = 0
        for item in sch_data:
            if not (isinstance(item, list) and item and item[0] == no_connect_k):
                continue
            for sub in item[1:]:
                if isinstance(sub, list) and sub and sub[0] == at_k and len(sub) >= 3:
                    nc = find_new(float(sub[1]), float(sub[2]))
                    if nc is not None:
                        sub[1] = nc[0]
                        sub[2] = nc[1]
                        no_connects_moved += 1
                    break

        straighten_summary = {"wires_straightened": 0, "wires_left_diagonal": 0}
        if straighten:
            straighten_summary = WireDragger._straighten_bent_wires(
                sch_data, pre_move, anchor_points or set(), eps
            )

        return {
            "endpoints_moved": endpoints_moved,
            "wires_removed": len(zero_length_indices),
            "labels_moved": labels_moved,
            "no_connects_moved": no_connects_moved,
            **straighten_summary,
        }

    @staticmethod
    def _wire_endpoints(item):
        """Return ((x1, y1), (x2, y2)) for a wire s-expression, or None.

        Only two-point segments are considered: that is what eeschema writes for
        a wire, and the orthogonality logic below is defined for a segment.
        """
        if not (isinstance(item, list) and item and item[0] == _K["wire"]):
            return None
        for sub in item[1:]:
            if isinstance(sub, list) and sub and sub[0] == _K["pts"]:
                xy_items = [
                    q for q in sub[1:] if isinstance(q, list) and len(q) >= 3 and q[0] == _K["xy"]
                ]
                if len(xy_items) != 2:
                    return None
                return (
                    (float(xy_items[0][1]), float(xy_items[0][2])),
                    (float(xy_items[1][1]), float(xy_items[1][2])),
                )
        return None

    @staticmethod
    def _wire_xy_nodes(item) -> List[list]:
        """Return the mutable (xy ...) sub-lists of a wire, in file order."""
        for sub in item[1:]:
            if isinstance(sub, list) and sub and sub[0] == _K["pts"]:
                return [
                    q for q in sub[1:] if isinstance(q, list) and len(q) >= 3 and q[0] == _K["xy"]
                ]
        return []

    @staticmethod
    def _move_point(
        sch_data: list,
        old_pt: Tuple[float, float],
        new_pt: Tuple[float, float],
        eps: float = EPS,
    ) -> int:
        """Move every item anchored at *old_pt* to *new_pt*.

        Wire endpoints, junctions, labels and no-connect flags all move together,
        so whatever met at that coordinate still meets after the move.
        Returns the number of coordinates updated.
        """
        at_k = _K["at"]
        moved = 0
        for item in sch_data:
            if not (isinstance(item, list) and item):
                continue
            if item[0] == _K["wire"]:
                for xy_item in WireDragger._wire_xy_nodes(item):
                    if _coords_match(
                        float(xy_item[1]), float(xy_item[2]), old_pt[0], old_pt[1], eps
                    ):
                        xy_item[1], xy_item[2] = new_pt
                        moved += 1
            elif item[0] in (
                _K["junction"],
                _K["no_connect"],
                _K["label"],
                _K["global_label"],
                _K["hierarchical_label"],
            ):
                for sub in item[1:]:
                    if isinstance(sub, list) and sub and sub[0] == at_k and len(sub) >= 3:
                        if _coords_match(float(sub[1]), float(sub[2]), old_pt[0], old_pt[1], eps):
                            sub[1], sub[2] = new_pt
                            moved += 1
                        break
        return moved

    @staticmethod
    def _straighten_bent_wires(
        sch_data: list,
        pre_move: Dict[int, Tuple[Tuple[float, float], Tuple[float, float]]],
        anchor_points: Set[Tuple[float, float]],
        eps: float = EPS,
        max_passes: int = 8,
    ) -> Dict:
        """Restore right angles on segments the drag turned diagonal.

        Dragging a pin moves only the endpoint that touches it. A wire routed
        pin -> corner -> corner -> pin is a chain of separate segments, so the
        first segment ends up diagonal while the corner it leads to stays put --
        the trace stops being orthogonal and its bend lands off-grid, which is
        what eeschema then reports as endpoint_off_grid.

        The fix is what dragging in eeschema does: carry the corner along. For
        each segment that *was* axis-aligned, had exactly one endpoint dragged
        and is now diagonal, the free end is shifted onto the dragged end's axis.
        That shift moves everything meeting at the corner, which can bend the
        next segment in the chain -- hence the repeat passes, which settle once
        nothing else needs straightening.

        A free end is left alone (and the segment left diagonal) when it is a
        pin of a stationary symbol, an explicit junction, or a fork where three
        or more wire ends meet: moving those would drag unrelated wiring or tear
        a connection apart. Those cases are counted, not silently reshaped.
        """
        wires = [item for item in sch_data if WireDragger._wire_endpoints(item) is not None]
        junction_points = set()
        for item in sch_data:
            if not (isinstance(item, list) and item and item[0] == _K["junction"]):
                continue
            for sub in item[1:]:
                if isinstance(sub, list) and sub and sub[0] == _K["at"] and len(sub) >= 3:
                    junction_points.add((round(float(sub[1]), 6), round(float(sub[2]), 6)))
                    break

        def is_anchored(pt: Tuple[float, float]) -> bool:
            if (round(pt[0], 6), round(pt[1], 6)) in junction_points:
                return True
            if any(_coords_match(pt[0], pt[1], ax, ay, eps) for (ax, ay) in anchor_points):
                return True
            # Fork: three or more wire ends meeting here.
            touching = 0
            for w in wires:
                ends = WireDragger._wire_endpoints(w)
                if ends is None:
                    continue
                for end in ends:
                    if _coords_match(pt[0], pt[1], end[0], end[1], eps):
                        touching += 1
            return touching >= 3

        straightened = 0
        left_diagonal = 0

        for _pass in range(max_passes):
            changed = False
            left_diagonal = 0
            for wire in wires:
                orig = pre_move.get(id(wire))
                cur = WireDragger._wire_endpoints(wire)
                if orig is None or cur is None:
                    continue

                was_h = abs(orig[0][1] - orig[1][1]) < eps
                was_v = abs(orig[0][0] - orig[1][0]) < eps
                if not (was_h or was_v):
                    continue  # deliberately diagonal before the move; leave it
                if abs(cur[0][0] - cur[1][0]) < eps or abs(cur[0][1] - cur[1][1]) < eps:
                    continue  # still axis-aligned

                dragged = [
                    i
                    for i in (0, 1)
                    if not _coords_match(cur[i][0], cur[i][1], orig[i][0], orig[i][1], eps)
                ]
                if len(dragged) != 1:
                    continue  # both ends moved (or neither): not ours to fix
                m = dragged[0]
                free_pt = cur[1 - m]
                if is_anchored(free_pt):
                    left_diagonal += 1
                    continue

                # A horizontal segment keeps its X span and follows the dragged
                # end's Y; a vertical one mirrors that.
                target = (free_pt[0], cur[m][1]) if was_h else (cur[m][0], free_pt[1])
                if _coords_match(target[0], target[1], free_pt[0], free_pt[1], eps):
                    continue

                WireDragger._move_point(sch_data, free_pt, target, eps)
                straightened += 1
                changed = True
            if not changed:
                break
        else:
            logger.warning(
                "Orthogonality pass hit its %d-pass limit; some segments may still be diagonal",
                max_passes,
            )

        if left_diagonal:
            logger.info(
                "%d segment(s) left diagonal: the free end is pinned by a "
                "junction, a fork, or another component's pin",
                left_diagonal,
            )

        return {"wires_straightened": straightened, "wires_left_diagonal": left_diagonal}

    @staticmethod
    def update_symbol_position(
        sch_data: list,
        reference: str,
        new_x: float,
        new_y: float,
        unit: Optional[int] = None,
    ) -> bool:
        """
        Update the (at x y rot) of the named symbol in sch_data.
        Returns True if the symbol was found and updated.
        """
        found = WireDragger.find_symbol(sch_data, reference, unit)
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
        moved_unit: Optional[int] = None,
    ) -> Dict[Tuple[float, float], str]:
        """
        Return a map of {world_xy: reference} for every pin of every symbol
        in sch_data *except* the one that moved.

        This is used to detect pins of stationary components that coincide
        with pins of the moved component (touching-pin connections).

        moved_unit: when a single unit of a multi-unit part moved, the part's
            other units did not — they are stationary and their pins belong in
            the map.
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
            item_unit = WireDragger._symbol_unit(item)
            if ref_val is None:
                continue
            if ref_val == moved_reference and (moved_unit is None or item_unit == moved_unit):
                continue
            # Skip template / power symbols whose references start with special chars
            # but we still want to handle them — no filtering needed here.

            # Find lib_id and position for this symbol
            found = WireDragger.find_symbol(sch_data, ref_val, item_unit)
            if found is None:
                continue
            _, sx, sy, rotation, lib_id, mirror_x, mirror_y = found
            pins = WireDragger.get_pin_defs(sch_data, lib_id, item_unit)
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
        moved_unit: Optional[int] = None,
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

        stationary_pins = WireDragger.get_all_stationary_pin_positions(
            sch_data, moved_reference, moved_unit
        )
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
