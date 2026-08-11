"""
Schematic field-placement commands.

Tools:
  - set_schematic_property_position:          move one Reference/Value field
  - batch_set_schematic_property_positions:   move many fields in one file read/write
  - autoplace_schematic_fields:               auto-position Ref/Value fields outside the
                                              component body and any attached net labels

This module is self-contained: it gathers the enriched component/label data it needs
(body bounding boxes, field positions, pin tips) directly from the schematic + PinLocator,
rather than depending on the output shape of other handlers.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List

from commands.pin_locator import PinLocator
from commands.schematic import SchematicLoadError, SchematicManager
from commands.schematic_text_utils import (
    _extract_property_position,
    _extract_property_visible,
    _find_placed_symbol_block,
    _move_property_in_block,
)

logger = logging.getLogger("kicad_interface")

_GRID = 1.27  # 50-mil KiCad schematic grid (mm)
_BODY_PAD_MM = 1.27

# ── Enriched data gathering (replicates list_schematic_components' fork enrichment) ──


def _gather_components(
    schematic, sch_path: Path, raw_content: str, locator: PinLocator
) -> List[Dict[str, Any]]:
    """Build enriched component dicts: position, value, libId, pins, body_bbox, ref/value_field."""
    components: List[Dict[str, Any]] = []
    for symbol in schematic.symbol:
        if not hasattr(symbol.property, "Reference"):
            continue
        ref = symbol.property.Reference.value
        if ref.startswith("_TEMPLATE"):
            continue
        lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else ""
        value = symbol.property.Value.value if hasattr(symbol.property, "Value") else ""
        position = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]

        comp: Dict[str, Any] = {
            "reference": ref,
            "libId": lib_id,
            "value": value,
            "position": {"x": float(position[0]), "y": float(position[1])},
            "rotation": float(position[2]) if len(position) > 2 else 0,
        }

        block_text, _, _ = _find_placed_symbol_block(raw_content, ref)
        if block_text:
            ref_pos = _extract_property_position(block_text, "Reference")
            if ref_pos:
                ref_pos["visible"] = _extract_property_visible(block_text, "Reference")
                comp["ref_field"] = ref_pos
            val_pos = _extract_property_position(block_text, "Value")
            if val_pos:
                val_pos["visible"] = _extract_property_visible(block_text, "Value")
                comp["value_field"] = val_pos

        try:
            all_pins = locator.get_all_symbol_pins(sch_path, ref)
            if all_pins:
                pins_def = locator.get_symbol_pins(sch_path, lib_id) or {}
                pin_list = []
                for pin_num, coords in all_pins.items():
                    pin_info = {"number": pin_num, "position": {"x": coords[0], "y": coords[1]}}
                    if pin_num in pins_def:
                        pin_info["name"] = pins_def[pin_num].get("name", pin_num)
                    pin_list.append(pin_info)
                comp["pins"] = pin_list
                xs = [p["position"]["x"] for p in pin_list]
                ys = [p["position"]["y"] for p in pin_list]
                comp["body_bbox"] = {
                    "x_min": min(xs) - _BODY_PAD_MM,
                    "y_min": min(ys) - _BODY_PAD_MM,
                    "x_max": max(xs) + _BODY_PAD_MM,
                    "y_max": max(ys) + _BODY_PAD_MM,
                }
        except Exception:
            pass  # pin lookup is best-effort

        components.append(comp)
    return components


def _gather_labels(schematic) -> List[Dict[str, Any]]:
    """Net + global labels as {type, name, position, angle}."""
    labels = []
    for attr, kind in (("label", "net"), ("global_label", "global")):
        for lbl in getattr(schematic, attr, []):
            if not hasattr(lbl, "value"):
                continue
            pos = lbl.at.value if hasattr(lbl, "at") and hasattr(lbl.at, "value") else [0, 0, 0]
            labels.append(
                {
                    "type": kind,
                    "name": lbl.value,
                    "position": {"x": float(pos[0]), "y": float(pos[1])},
                    "angle": float(pos[2]) if len(pos) > 2 else 0,
                }
            )
    return labels


def _bbox_overlaps(a, b, margin=0.0):
    return (
        a["x_min"] - margin < b["x_max"]
        and a["x_max"] + margin > b["x_min"]
        and a["y_min"] - margin < b["y_max"]
        and a["y_max"] + margin > b["y_min"]
    )


class SchematicFieldLayoutCommands:
    """Handlers for schematic field placement."""

    def set_schematic_property_position(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Move a symbol's Reference or Value property field to a new coordinate."""
        logger.info("Setting schematic property position")
        try:
            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            property_name = params.get("property")
            x = params.get("x")
            y = params.get("y")
            angle = params.get("angle", 0)
            visible = params.get("visible", True)

            if not all([schematic_path, reference, property_name, x is not None, y is not None]):
                return {
                    "success": False,
                    "message": "Missing required parameters: schematicPath, reference, property, x, y",
                }
            if property_name not in ("Reference", "Value"):
                return {"success": False, "message": "property must be 'Reference' or 'Value'"}

            sch_path = Path(schematic_path)
            if not sch_path.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            content = sch_path.read_text(encoding="utf-8")
            block_text, block_start, block_end = _find_placed_symbol_block(content, reference)
            if block_text is None:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic",
                }

            old_pos = _extract_property_position(block_text, property_name)
            new_block, n_subs = _move_property_in_block(
                block_text, property_name, x, y, angle, visible
            )
            if n_subs == 0:
                return {
                    "success": False,
                    "message": f"Property '{property_name}' not found in {reference}",
                }

            new_content = content[:block_start] + new_block + content[block_end + 1 :]
            sch_path.write_text(new_content, encoding="utf-8")

            old_str = (
                f"({old_pos['x']}, {old_pos['y']}, {old_pos['angle']}°)" if old_pos else "unknown"
            )
            return {
                "success": True,
                "message": f"Moved {reference}.{property_name} from {old_str} to ({x}, {y}, {angle}°)",
            }
        except Exception as e:
            logger.error(f"Error setting property position: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def batch_set_schematic_property_positions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Batch-move Reference/Value property fields for many components in one read/write."""
        logger.info("Batch setting schematic property positions")
        try:
            schematic_path = params.get("schematicPath")
            updates = params.get("updates", [])

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not updates:
                return {"success": False, "message": "updates list is required"}

            sch_path = Path(schematic_path)
            if not sch_path.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            content = sch_path.read_text(encoding="utf-8")
            applied: List[Dict[str, Any]] = []
            failed: List[Dict[str, Any]] = []

            for upd in updates:
                reference = upd.get("reference")
                property_name = upd.get("property")
                x = upd.get("x")
                y = upd.get("y")
                angle = upd.get("angle", 0)
                visible = upd.get("visible", True)

                if not reference or not property_name or x is None or y is None:
                    failed.append(
                        {
                            "reference": reference,
                            "property": property_name,
                            "reason": "Missing required fields: reference, property, x, y",
                        }
                    )
                    continue
                if property_name not in ("Reference", "Value"):
                    failed.append(
                        {
                            "reference": reference,
                            "property": property_name,
                            "reason": "property must be 'Reference' or 'Value'",
                        }
                    )
                    continue

                block_text, block_start, block_end = _find_placed_symbol_block(content, reference)
                if block_text is None:
                    failed.append(
                        {
                            "reference": reference,
                            "property": property_name,
                            "reason": f"Component '{reference}' not found in schematic",
                        }
                    )
                    continue

                new_block, n_subs = _move_property_in_block(
                    block_text, property_name, x, y, angle, visible
                )
                if n_subs == 0:
                    failed.append(
                        {
                            "reference": reference,
                            "property": property_name,
                            "reason": f"Property '{property_name}' not found in {reference} block",
                        }
                    )
                    continue

                content = content[:block_start] + new_block + content[block_end + 1 :]
                applied.append(
                    {
                        "reference": reference,
                        "property": property_name,
                        "x": x,
                        "y": y,
                        "angle": angle,
                        "visible": visible,
                    }
                )

            if applied:
                sch_path.write_text(content, encoding="utf-8")

            return {
                "success": len(failed) == 0,
                "applied": applied,
                "failed": failed,
                "applied_count": len(applied),
                "failed_count": len(failed),
            }
        except Exception as e:
            logger.error(f"Error in batch_set_schematic_property_positions: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def autoplace_schematic_fields(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Re-position Reference and Value fields outside the body and any attached net labels."""
        logger.info("Auto-placing schematic fields")
        try:
            schematic_path = params.get("schematicPath")
            references_filter = params.get("references")
            clearance = float(params.get("clearance", _GRID))

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            sch_path = Path(schematic_path)
            if not sch_path.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            chars_per_mm, text_height = 1.5, 1.27

            def snap(val):
                return round(round(val / _GRID) * _GRID, 4)

            def label_bbox(lx, ly, angle, name):
                length = max(len(name), 1) * chars_per_mm + 1.0
                half_h = text_height / 2.0
                a = round(angle / 90) * 90 % 360
                if a == 0:
                    return {
                        "x_min": lx,
                        "y_min": ly - half_h,
                        "x_max": lx + length,
                        "y_max": ly + half_h,
                    }
                if a == 90:
                    return {
                        "x_min": lx - half_h,
                        "y_min": ly - length,
                        "x_max": lx + half_h,
                        "y_max": ly,
                    }
                if a == 180:
                    return {
                        "x_min": lx - length,
                        "y_min": ly - half_h,
                        "x_max": lx,
                        "y_max": ly + half_h,
                    }
                return {
                    "x_min": lx - half_h,
                    "y_min": ly,
                    "x_max": lx + half_h,
                    "y_max": ly + length,
                }

            def union(bb, other):
                return {
                    "x_min": min(bb["x_min"], other["x_min"]),
                    "y_min": min(bb["y_min"], other["y_min"]),
                    "x_max": max(bb["x_max"], other["x_max"]),
                    "y_max": max(bb["y_max"], other["y_max"]),
                }

            def field_bbox(fx, fy, text):
                half_w = max(len(str(text)), 1) * 0.75 / 2.0
                half_h = text_height / 2.0
                return {
                    "x_min": fx - half_w,
                    "y_min": fy - half_h,
                    "x_max": fx + half_w,
                    "y_max": fy + half_h,
                }

            try:
                schematic = SchematicManager.load_schematic(schematic_path)
            except SchematicLoadError as e:
                return e.to_response()
            raw_content = sch_path.read_text(encoding="utf-8")
            locator = PinLocator()

            components = _gather_components(schematic, sch_path, raw_content, locator)
            if references_filter:
                components = [c for c in components if c["reference"] in references_filter]
            net_labels = [
                lb for lb in _gather_labels(schematic) if lb.get("type") in ("net", "global")
            ]

            comp_ext_bboxes: Dict[str, Dict[str, float]] = {}
            comp_pin_map: Dict[str, Dict[str, Any]] = {}

            for comp in components:
                ref = comp["reference"]
                cx, cy = comp["position"]["x"], comp["position"]["y"]
                body_bb = comp.get("body_bbox") or {
                    "x_min": cx - 2.54,
                    "y_min": cy - 2.54,
                    "x_max": cx + 2.54,
                    "y_max": cy + 2.54,
                }
                ext_bb = dict(body_bb)

                all_pins: Dict[str, Any] = {}
                for p in comp.get("pins", []):
                    pnum = str(p.get("number", p.get("name", "")))
                    px = p.get("x", p.get("position", {}).get("x", cx))
                    py = p.get("y", p.get("position", {}).get("y", cy))
                    all_pins[pnum] = [float(px), float(py)]
                if not all_pins:
                    all_pins = locator.get_all_symbol_pins(sch_path, ref) or {}
                comp_pin_map[ref] = all_pins

                for lbl in net_labels:
                    lx, ly = lbl["position"]["x"], lbl["position"]["y"]
                    for pin_coords in all_pins.values():
                        px = (
                            pin_coords[0]
                            if isinstance(pin_coords, (list, tuple))
                            else pin_coords["x"]
                        )
                        py = (
                            pin_coords[1]
                            if isinstance(pin_coords, (list, tuple))
                            else pin_coords["y"]
                        )
                        if abs(lx - px) < 0.6 and abs(ly - py) < 0.6:
                            ext_bb = union(
                                ext_bb, label_bbox(lx, ly, lbl.get("angle", 0), lbl.get("name", ""))
                            )
                            break
                comp_ext_bboxes[ref] = ext_bb

            updates: List[Dict[str, Any]] = []
            placed_field_bboxes: List[Dict[str, float]] = []

            def has_collision(ref_bb, val_bb, exclude_ref):
                for other_ref, other_ext in comp_ext_bboxes.items():
                    if other_ref == exclude_ref:
                        continue
                    if _bbox_overlaps(ref_bb, other_ext, 0.3) or _bbox_overlaps(
                        val_bb, other_ext, 0.3
                    ):
                        return True
                for fb in placed_field_bboxes:
                    if _bbox_overlaps(ref_bb, fb, 0.2) or _bbox_overlaps(val_bb, fb, 0.2):
                        return True
                return False

            for comp in components:
                ref = comp["reference"]
                lib_id = comp.get("libId", "")
                if ref.startswith("#") or ref.startswith("_TEMPLATE"):
                    continue
                cx, cy = comp["position"]["x"], comp["position"]["y"]
                val_text = comp.get("value", ref)

                is_power = lib_id.startswith("kicad_power:") or lib_id.startswith("power:")
                if is_power:
                    ext_bb = dict(
                        comp.get("body_bbox")
                        or {
                            "x_min": cx - 1.27,
                            "y_min": cy - 1.27,
                            "x_max": cx + 1.27,
                            "y_max": cy + 1.27,
                        }
                    )
                    num_pins = 0
                else:
                    ext_bb = comp_ext_bboxes[ref]
                    num_pins = len(comp_pin_map[ref])

                if num_pins == 2:
                    coords = list(comp_pin_map[ref].values())
                    p1x = (
                        float(coords[0][0])
                        if isinstance(coords[0], (list, tuple))
                        else float(coords[0]["x"])
                    )
                    p1y = (
                        float(coords[0][1])
                        if isinstance(coords[0], (list, tuple))
                        else float(coords[0]["y"])
                    )
                    p2x = (
                        float(coords[1][0])
                        if isinstance(coords[1], (list, tuple))
                        else float(coords[1]["x"])
                    )
                    p2y = (
                        float(coords[1][1])
                        if isinstance(coords[1], (list, tuple))
                        else float(coords[1]["y"])
                    )
                    sides = (
                        ["right", "left", "above", "below"]
                        if abs(p1y - p2y) > abs(p1x - p2x)
                        else ["above", "below", "right", "left"]
                    )
                else:
                    sides = ["above", "below", "right", "left"]

                def try_side(side):
                    half_ref_h = text_height / 2.0
                    half_ref_w = max(len(ref), 1) * 0.75 / 2.0
                    half_val_w = max(len(str(val_text)), 1) * 0.75 / 2.0
                    stack = text_height
                    if side == "above":
                        ref_y = snap(ext_bb["y_min"] - half_ref_h - clearance)
                        return cx, ref_y, cx, ref_y - stack
                    if side == "below":
                        ref_y = snap(ext_bb["y_max"] + half_ref_h + clearance)
                        return cx, ref_y, cx, ref_y + stack
                    if side == "right":
                        x0 = ext_bb["x_max"] + clearance
                        ref_y = snap(cy)
                        return snap(x0 + half_ref_w), ref_y, snap(x0 + half_val_w), ref_y + stack
                    x0 = ext_bb["x_min"] - clearance
                    ref_y = snap(cy)
                    return snap(x0 - half_ref_w), ref_y, snap(x0 - half_val_w), ref_y + stack

                ref_x = ref_y = val_x = val_y = ref_bb = val_bb = None
                for side in sides:
                    rx, ry, vx, vy = try_side(side)
                    rb, vb = field_bbox(rx, ry, ref), field_bbox(vx, vy, val_text)
                    if not has_collision(rb, vb, ref):
                        ref_x, ref_y, val_x, val_y, ref_bb, val_bb = rx, ry, vx, vy, rb, vb
                        break
                if ref_x is None:
                    ref_x, ref_y, val_x, val_y = try_side(sides[0])
                    ref_bb, val_bb = field_bbox(ref_x, ref_y, ref), field_bbox(
                        val_x, val_y, val_text
                    )

                placed_field_bboxes.append(ref_bb)
                placed_field_bboxes.append(val_bb)
                updates.append(
                    {"reference": ref, "property": "Reference", "x": ref_x, "y": ref_y, "angle": 0}
                )
                updates.append(
                    {"reference": ref, "property": "Value", "x": val_x, "y": val_y, "angle": 0}
                )

            if not updates:
                return {"success": True, "message": "No components to update.", "updated_count": 0}

            batch_result = self.batch_set_schematic_property_positions(
                {"schematicPath": schematic_path, "updates": updates}
            )
            applied = batch_result.get("applied_count", 0)
            failed = batch_result.get("failed_count", 0)
            return {
                "success": batch_result.get("success", False),
                "message": f"Auto-placed fields for {applied // 2} component(s) "
                f"({applied} fields updated{', ' + str(failed) + ' failed' if failed else ''}).",
                "updated_count": applied,
                "failed_count": failed,
                "failed": batch_result.get("failed", []),
            }

        except Exception as e:
            logger.error(f"Error in autoplace_schematic_fields: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}
