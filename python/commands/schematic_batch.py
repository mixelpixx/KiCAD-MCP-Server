"""
Batch schematic authoring commands.

Tools that place / edit / connect many things in one call to avoid per-item round-trips:
  - batch_add_components:            add many components at once
  - batch_edit_schematic_components: edit many components (value/footprint/reference/...)
  - replace_schematic_component:     swap a symbol, preserving position and field values
  - batch_add_no_connects:           add no-connect (X) flags to many pins
  - batch_connect:                   place net labels on many pins (with facing-label wiring)
  - batch_add_and_connect:           place components and wire their nets in one call

The command class is constructed with a reference to the KiCADInterface so it can reuse
existing single-item handlers (add/edit/get_schematic_component), the footprint library,
and the hierarchical-instance fixer when present.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from commands.dynamic_symbol_loader import DynamicSymbolLoader
from commands.pin_locator import PinLocator
from commands.schematic_text_utils import (
    _extract_property_position,
    _find_facing_label,
    _find_placed_symbol_block,
    _find_project_root,
    _move_property_in_block,
)
from commands.wire_manager import WireManager

logger = logging.getLogger("kicad_interface")

_GRID = 1.27  # 50-mil KiCad schematic grid (mm)


def _snap(val: float) -> float:
    """Round a coordinate to the nearest 50-mil (1.27mm) schematic grid point."""
    return round(round(val / _GRID) * _GRID, 4)


def _field_positions_for_pins(cx, cy, all_pins):
    """Compute (Reference, Value) field positions from pin axis. Returns list of (name,x,y,angle)."""
    off = 2.54
    if len(all_pins) == 2:
        coords = list(all_pins.values())
        p1x = float(coords[0][0]) if isinstance(coords[0], (list, tuple)) else float(coords[0]["x"])
        p1y = float(coords[0][1]) if isinstance(coords[0], (list, tuple)) else float(coords[0]["y"])
        p2x = float(coords[1][0]) if isinstance(coords[1], (list, tuple)) else float(coords[1]["x"])
        p2y = float(coords[1][1]) if isinstance(coords[1], (list, tuple)) else float(coords[1]["y"])
        if abs(p1y - p2y) > abs(p1x - p2x):  # vertical pin axis -> labels left/right
            return [("Reference", round(cx - off, 4), cy, 0), ("Value", round(cx + off, 4), cy, 0)]
        return [("Reference", cx, round(cy - off, 4), 0), ("Value", cx, round(cy + off, 4), 0)]
    if all_pins:  # multi-pin -> above topmost / below bottommost
        pin_ys = [
            float(c[1]) if isinstance(c, (list, tuple)) else float(c["y"])
            for c in all_pins.values()
        ]
        return [
            ("Reference", cx, round(min(pin_ys) - off, 4), 0),
            ("Value", cx, round(max(pin_ys) + off, 4), 0),
        ]
    return [("Reference", cx, round(cy - off, 4), 0), ("Value", cx, round(cy + off, 4), 0)]


def _bbox_from_pins(all_pins, cx, cy):
    """body_bbox from pin spread (±1.27mm), or center ±2.54mm fallback."""
    try:
        if all_pins:
            xs = [c[0] if isinstance(c, (list, tuple)) else c["x"] for c in all_pins.values()]
            ys = [c[1] if isinstance(c, (list, tuple)) else c["y"] for c in all_pins.values()]
            return {
                "x_min": min(xs) - _GRID,
                "y_min": min(ys) - _GRID,
                "x_max": max(xs) + _GRID,
                "y_max": max(ys) + _GRID,
            }
    except Exception:
        pass
    return {"x_min": cx - 2.54, "y_min": cy - 2.54, "x_max": cx + 2.54, "y_max": cy + 2.54}


class SchematicBatchCommands:
    """Handlers for batch schematic authoring. Holds a back-reference to KiCADInterface."""

    def __init__(self, iface):
        self.iface = iface

    def batch_add_components(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add multiple components to a schematic in a single call."""
        logger.info("Batch adding components to schematic")
        try:
            schematic_path = params.get("schematicPath")
            components = params.get("components", [])
            origin_x = params.get("origin_x", 0) or 0
            origin_y = params.get("origin_y", 0) or 0
            auto_position_fields = params.get("auto_position_fields", True)

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not components:
                return {
                    "success": False,
                    "message": "components list is required and must be non-empty",
                }

            schematic_file = Path(schematic_path)
            project_path = schematic_file.parent
            loader = DynamicSymbolLoader(project_path=project_path)
            locator = PinLocator()

            results: List[Dict[str, Any]] = []
            errors: List[Dict[str, Any]] = []

            for comp in components:
                symbol = comp.get("symbol", "")
                if ":" not in symbol:
                    errors.append(
                        {
                            "symbol": symbol,
                            "reference": comp.get("reference", "?"),
                            "error": "symbol must be 'Library:SymbolName'",
                        }
                    )
                    continue

                library, sym_name = symbol.split(":", 1)
                reference = comp.get("reference", "X?")
                value = comp.get("value", sym_name)
                footprint = comp.get("footprint", "")
                pos = comp.get("position", {})
                x = (pos.get("x", 0) if isinstance(pos, dict) else 0) + origin_x
                y = (pos.get("y", 0) if isinstance(pos, dict) else 0) + origin_y
                rotation = comp.get("rotation", 0)
                include_pins = comp.get("includePins", False)

                try:
                    loader.add_component(
                        schematic_file,
                        library,
                        sym_name,
                        reference=reference,
                        value=value,
                        footprint=footprint,
                        x=x,
                        y=y,
                        angle=rotation,
                        project_path=project_path,
                    )

                    entry: Dict[str, Any] = {
                        "reference": reference,
                        "symbol": symbol,
                        "snapped_position": {"x": _snap(x), "y": _snap(y)},
                    }

                    if footprint and self.iface.footprint_library.find_footprint(footprint) is None:
                        entry["footprint_warning"] = (
                            f"Footprint '{footprint}' was not found in any registered footprint library "
                            "(validation only — the string WAS written to the Footprint field). "
                            "Use search_footprints to find a valid footprint string."
                        )

                    locator._schematic_cache.pop(str(schematic_file), None)
                    all_pins = locator.get_all_symbol_pins(schematic_file, reference) or {}

                    block_text = None
                    raw_content = schematic_file.read_text(encoding="utf-8")
                    block_text, block_start, block_end = _find_placed_symbol_block(
                        raw_content, reference
                    )
                    if auto_position_fields and block_text:
                        cx, cy = _snap(x), _snap(y)
                        new_block = block_text
                        for prop, px, py, pa in _field_positions_for_pins(cx, cy, all_pins):
                            new_block, _ = _move_property_in_block(
                                new_block, prop, px, py, pa, True
                            )
                        if new_block != block_text:
                            raw_content = (
                                raw_content[:block_start] + new_block + raw_content[block_end + 1 :]
                            )
                            schematic_file.write_text(raw_content, encoding="utf-8")
                            block_text = new_block

                    if block_text:
                        ref_pos = _extract_property_position(block_text, "Reference")
                        val_pos = _extract_property_position(block_text, "Value")
                        if ref_pos:
                            entry["ref_position"] = ref_pos
                        if val_pos:
                            entry["value_position"] = val_pos

                    if include_pins:
                        pins_def = locator.get_symbol_pins(schematic_file, symbol) or {}
                        pins = {
                            pin_num: {
                                "x": coords[0],
                                "y": coords[1],
                                "name": pins_def.get(str(pin_num), {}).get("name", str(pin_num)),
                            }
                            for pin_num, coords in all_pins.items()
                        }
                        entry["pins"] = pins
                        if not pins:
                            entry["pins_error"] = (
                                f"Pin extraction returned no data for {reference} ({symbol}). "
                                "Use get_schematic_pin_locations as a follow-up if needed."
                            )

                    entry["body_bbox"] = _bbox_from_pins(all_pins, _snap(x), _snap(y))
                    results.append(entry)

                except Exception as e:
                    logger.error(f"Error adding {reference} ({symbol}): {e}")
                    errors.append({"symbol": symbol, "reference": reference, "error": str(e)})

            # If this schematic is a sub-sheet of another, fix hierarchical instance paths
            # (best-effort; only when the interface provides the fixer).
            hier = getattr(self.iface, "hierarchy_commands", None)
            if hier is not None:
                sch_name = schematic_file.name
                for candidate in project_path.glob("*.kicad_sch"):
                    if candidate.resolve() == schematic_file.resolve():
                        continue
                    try:
                        candidate_content = candidate.read_text(encoding="utf-8")
                        if sch_name in candidate_content:
                            hier.fix_subsheet_instances(str(candidate), candidate_content)
                    except Exception:
                        pass

            placement_bbox = None
            bbs = [r["body_bbox"] for r in results if "body_bbox" in r]
            if bbs:
                placement_bbox = {
                    "x_min": min(b["x_min"] for b in bbs),
                    "y_min": min(b["y_min"] for b in bbs),
                    "x_max": max(b["x_max"] for b in bbs),
                    "y_max": max(b["y_max"] for b in bbs),
                }

            return {
                "success": len(errors) == 0,
                "added": results,
                "errors": errors,
                "added_count": len(results),
                "error_count": len(errors),
                "placement_bbox": placement_bbox,
            }

        except Exception as e:
            logger.error(f"Error in batch_add_components: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def batch_edit_schematic_components(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Edit multiple components in one call via the single-component edit handler."""
        logger.info("Batch editing schematic components")
        schematic_path = params.get("schematicPath")
        components = params.get("components")

        if not schematic_path:
            return {"success": False, "message": "schematicPath is required"}
        if not components or not isinstance(components, dict):
            return {
                "success": False,
                "message": "components must be a dict {reference: {footprint?, value?, newReference?}}",
            }

        updated: Dict[str, Any] = {}
        errors: List[Dict[str, Any]] = []
        for reference, props in components.items():
            sub_params = {"schematicPath": schematic_path, "reference": reference, **props}
            result = self.iface._handle_edit_schematic_component(sub_params)
            if result.get("success"):
                updated[reference] = result.get("updated", {})
            else:
                errors.append(
                    {"reference": reference, "error": result.get("message", "Unknown error")}
                )

        return {
            "success": len(errors) == 0,
            "updated_count": len(updated),
            "error_count": len(errors),
            "updated": updated,
            "errors": errors,
        }

    def replace_schematic_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Replace a placed symbol with a different symbol, preserving position and fields."""
        logger.info("Replacing schematic component")
        try:
            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            new_symbol = params.get("newSymbol")
            new_rotation = params.get("newRotation")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}
            if not new_symbol:
                return {
                    "success": False,
                    "message": "newSymbol is required (e.g. 'Device:D_Zener')",
                }
            if ":" not in new_symbol:
                return {"success": False, "message": "newSymbol must be in 'Library:Symbol' format"}
            new_library, new_type = new_symbol.split(":", 1)

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            comp_info = self.iface._handle_get_schematic_component(
                {"schematicPath": schematic_path, "reference": reference}
            )
            if not comp_info.get("success"):
                return {
                    "success": False,
                    "message": f"Cannot find component '{reference}': {comp_info.get('message', '')}",
                }

            old_pos = comp_info.get("position", {})
            old_x = old_pos.get("x", 0)
            old_y = old_pos.get("y", 0)
            old_rotation = old_pos.get("angle", 0)
            old_fields = comp_info.get("fields", {})
            use_rotation = new_rotation if new_rotation is not None else old_rotation

            content = sch_file.read_text(encoding="utf-8")
            block_text, block_start, block_end = _find_placed_symbol_block(content, reference)
            if block_text is None:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic file",
                }

            trim_start = block_start
            while trim_start > 0 and content[trim_start - 1] in (" ", "\t"):
                trim_start -= 1
            if trim_start > 0 and content[trim_start - 1] == "\n":
                trim_start -= 1
            content = content[:trim_start] + content[block_end + 1 :]
            sch_file.write_text(content, encoding="utf-8")

            derived_project_path = _find_project_root(sch_file.parent)
            loader = DynamicSymbolLoader(project_path=derived_project_path)

            def _field_value(name, default):
                fd = old_fields.get(name)
                return (
                    fd.get("value", default)
                    if isinstance(fd, dict)
                    else (fd if fd is not None else default)
                )

            old_value = _field_value("Value", new_type)
            old_footprint = _field_value("Footprint", "")

            loader.add_component(
                sch_file,
                new_library,
                new_type,
                reference=reference,
                value=old_value,
                footprint=old_footprint,
                x=old_x,
                y=old_y,
                angle=use_rotation,
                project_path=derived_project_path,
            )

            fields_to_restore = {}
            for fname, fdata in old_fields.items():
                if fname in ("Reference", "Value", "Footprint"):
                    continue
                fields_to_restore[fname] = (
                    fdata.get("value", "") if isinstance(fdata, dict) else str(fdata)
                )

            if fields_to_restore:
                content_after = sch_file.read_text(encoding="utf-8")
                new_block, _, _ = _find_placed_symbol_block(content_after, reference)
                if new_block:
                    for fname, fval in fields_to_restore.items():
                        prop_pat = re.compile(
                            r'(\(property\s+"' + re.escape(fname) + r'"\s+)"[^"]*"'
                        )
                        content_after = prop_pat.sub(
                            r'\1"' + fval.replace('"', '\\"') + '"', content_after, count=1
                        )
                    sch_file.write_text(content_after, encoding="utf-8")

            pin_locator = PinLocator()
            pins_raw = pin_locator.get_all_symbol_pins(sch_file, reference) or {}
            pins_def = pin_locator.get_symbol_pins(sch_file, f"{new_library}:{new_type}") or {}
            pins = {
                pin_num: {
                    "x": coords[0],
                    "y": coords[1],
                    "name": pins_def.get(str(pin_num), {}).get("name", str(pin_num)),
                }
                for pin_num, coords in pins_raw.items()
            }

            return {
                "success": True,
                "reference": reference,
                "newSymbol": new_symbol,
                "position": {"x": old_x, "y": old_y, "rotation": use_rotation},
                "pins": pins,
                "message": f"Replaced {reference} with {new_symbol} at ({old_x}, {old_y})",
            }

        except Exception as e:
            logger.error(f"Error replacing schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def batch_add_no_connects(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add no-connect flags to multiple pins in a single call."""
        logger.info("Batch adding no-connect flags")
        try:
            schematic_path = params.get("schematicPath")
            pins = params.get("pins", [])
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not pins:
                return {"success": False, "message": "pins list is required and must be non-empty"}

            sch_path = Path(schematic_path)
            locator = PinLocator()
            placed: List[Dict[str, Any]] = []
            failed: List[Dict[str, Any]] = []

            for entry in pins:
                comp_ref = entry.get("componentRef")
                pin_name = entry.get("pinName")
                if not comp_ref or pin_name is None:
                    failed.append(
                        {"entry": entry, "reason": "componentRef and pinName are required"}
                    )
                    continue
                try:
                    pin_loc = locator.get_pin_location(sch_path, comp_ref, str(pin_name))
                    if not pin_loc:
                        all_pins = locator.get_all_symbol_pins(sch_path, comp_ref) or {}
                        if len(all_pins) == 1:
                            pin_loc = next(iter(all_pins.values()))
                        else:
                            avail = sorted(all_pins.keys()) if all_pins else []
                            failed.append(
                                {
                                    "componentRef": comp_ref,
                                    "pinName": str(pin_name),
                                    "reason": f"Pin not found; available: {avail}",
                                }
                            )
                            continue
                    if WireManager.add_no_connect(sch_path, pin_loc):
                        placed.append(
                            {
                                "componentRef": comp_ref,
                                "pinName": str(pin_name),
                                "position": {"x": pin_loc[0], "y": pin_loc[1]},
                            }
                        )
                    else:
                        failed.append(
                            {
                                "componentRef": comp_ref,
                                "pinName": str(pin_name),
                                "reason": "add_no_connect returned False",
                            }
                        )
                except Exception as pin_err:
                    failed.append(
                        {"componentRef": comp_ref, "pinName": str(pin_name), "reason": str(pin_err)}
                    )

            return {
                "success": len(failed) == 0,
                "message": f"Placed {len(placed)} no-connect marker(s), {len(failed)} failed",
                "placed": placed,
                "failed": failed,
            }
        except Exception as e:
            logger.error(f"Error in batch_add_no_connects: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def batch_connect(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Place net labels on multiple pins in a single call, with facing-label wiring."""
        logger.info("Batch connect: placing net labels on multiple pins")
        try:
            schematic_path = params.get("schematicPath")
            connections = params.get("connections")
            replace = bool(params.get("replace", False))

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not connections or not isinstance(connections, dict):
                return {
                    "success": False,
                    "message": "connections must be a dict {ref: {pin: netName}}",
                }

            locator = PinLocator()
            sch_path = Path(schematic_path)

            try:
                from skip import Schematic

                Schematic(str(sch_path))
            except Exception as parse_err:
                return {
                    "success": False,
                    "message": (
                        f"ERROR: Failed to load schematic at {schematic_path}: {parse_err}. "
                        "All pin operations aborted. Run run_erc to check the schematic."
                    ),
                }

            placed: List[Dict[str, Any]] = []
            failed: List[Dict[str, Any]] = []
            placed_positions: Dict[tuple, str] = {}

            for ref, pin_map in connections.items():
                if not isinstance(pin_map, dict):
                    failed.append({"ref": ref, "reason": "pin_map must be a dict {pin: netName}"})
                    continue
                for pin_id, net_name in pin_map.items():
                    try:
                        resolved_pin = str(pin_id)
                        position = locator.get_pin_location(sch_path, ref, resolved_pin)
                        if not position:
                            all_pins = locator.get_all_symbol_pins(sch_path, ref) or {}
                            if len(all_pins) == 1:
                                resolved_pin = next(iter(all_pins))
                                position = all_pins[resolved_pin]
                            else:
                                avail = sorted(all_pins.keys()) if all_pins else []
                                failed.append(
                                    {
                                        "ref": ref,
                                        "pin": resolved_pin,
                                        "reason": f"pin not found; available: {avail}",
                                    }
                                )
                                continue

                        pos_key = (round(float(position[0]), 2), round(float(position[1]), 2))
                        if placed_positions.get(pos_key) == net_name:
                            placed.append(
                                {
                                    "ref": ref,
                                    "pin": str(pin_id),
                                    "net": net_name,
                                    "position": {"x": position[0], "y": position[1]},
                                    "note": "deduped: label already placed at this coordinate for this net",
                                }
                            )
                            continue

                        raw_angle = locator.get_pin_angle(sch_path, ref, resolved_pin) or 0
                        cardinal = round(raw_angle / 90) * 90 % 360
                        orientation = {0: 180, 90: 270, 180: 0, 270: 90}.get(cardinal, 0)

                        existing_pos = _find_facing_label(sch_path, net_name, position, orientation)
                        if existing_pos:
                            if WireManager.add_wire(sch_path, list(position), existing_pos):
                                placed.append(
                                    {
                                        "ref": ref,
                                        "pin": str(pin_id),
                                        "net": net_name,
                                        "position": {"x": position[0], "y": position[1]},
                                        "note": f"wired to existing label at ({existing_pos[0]},{existing_pos[1]})",
                                    }
                                )
                                placed_positions[pos_key] = net_name
                            else:
                                failed.append(
                                    {
                                        "ref": ref,
                                        "pin": str(pin_id),
                                        "net": net_name,
                                        "reason": "wire-to-existing-label failed",
                                    }
                                )
                            continue

                        if replace:
                            WireManager.delete_label(
                                sch_path, net_name, list(position), tolerance=0.5
                            )
                            self._delete_labels_at(sch_path, position)

                        if WireManager.add_label(
                            sch_path,
                            net_name,
                            position,
                            label_type="label",
                            orientation=orientation,
                        ):
                            placed.append(
                                {
                                    "ref": ref,
                                    "pin": str(pin_id),
                                    "net": net_name,
                                    "position": {"x": position[0], "y": position[1]},
                                }
                            )
                            placed_positions[pos_key] = net_name
                        else:
                            failed.append(
                                {
                                    "ref": ref,
                                    "pin": str(pin_id),
                                    "net": net_name,
                                    "reason": "add_label failed",
                                }
                            )
                    except Exception as pin_err:
                        failed.append({"ref": ref, "pin": str(pin_id), "reason": str(pin_err)})

            result: Dict[str, Any] = {
                "success": len(failed) == 0,
                "message": f"Placed {len(placed)} label(s), {len(failed)} failed",
                "placed": placed,
                "failed": failed,
            }
            warnings = self._pwr_flag_warnings(sch_path, locator, placed)
            if warnings:
                result["warnings"] = warnings
            return result

        except Exception as e:
            logger.error(f"Error in batch_connect: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    @staticmethod
    def _delete_labels_at(sch_path, position):
        """Drop any (label ...) within 0.5mm of *position* (used by batch_connect replace=True)."""
        try:
            import sexpdata
            from sexpdata import Symbol
            from utils.sexpr_format import dumps as kicad_dumps

            data = sexpdata.loads(sch_path.read_text(encoding="utf-8"))
            changed = False
            new_data = []
            for item in data:
                if isinstance(item, list) and len(item) > 0 and item[0] == Symbol("label"):
                    at = next(
                        (
                            p
                            for p in item[1:]
                            if isinstance(p, list) and len(p) >= 3 and p[0] == Symbol("at")
                        ),
                        None,
                    )
                    if (
                        at
                        and abs(float(at[1]) - position[0]) < 0.5
                        and abs(float(at[2]) - position[1]) < 0.5
                    ):
                        changed = True
                        continue
                new_data.append(item)
            if changed:
                sch_path.write_text(kicad_dumps(new_data), encoding="utf-8")
        except Exception as e:
            logger.warning(f"replace cleanup failed: {e}")

    @staticmethod
    def _pwr_flag_warnings(sch_path, locator, placed):
        """Warn about power nets that have no PWR_FLAG attached."""
        keywords = {
            "VCC",
            "VDD",
            "VIN",
            "VBUS",
            "VBAT",
            "GND",
            "AGND",
            "DGND",
            "PGND",
            "+5V",
            "+3V3",
            "+12V",
            "+3.3V",
            "+5.0V",
            "PWR",
            "POWER",
            "AVCC",
        }
        try:
            placed_nets = {p["net"] for p in placed}
            power_nets = {n for n in placed_nets if any(kw in n.upper() for kw in keywords)}
            if not power_nets:
                return []
            pwr_flag_nets: set = set()
            try:
                from skip import Schematic

                sch_obj = Schematic(str(sch_path))
                pwr_flag_refs = [
                    sym.property.Reference.value
                    for sym in getattr(sch_obj, "symbol", [])
                    if "PWR_FLAG" in (sym.lib_id.value if hasattr(sym, "lib_id") else "")
                    and hasattr(sym.property, "Reference")
                ]
                for pref in pwr_flag_refs:
                    ppin = locator.get_pin_location(sch_path, pref, "1")
                    if not ppin:
                        all_p = locator.get_all_symbol_pins(sch_path, pref) or {}
                        ppin = next(iter(all_p.values())) if all_p else None
                    if ppin:
                        for pl in placed:
                            if (
                                abs(pl["position"]["x"] - ppin[0]) < 0.5
                                and abs(pl["position"]["y"] - ppin[1]) < 0.5
                            ):
                                pwr_flag_nets.add(pl["net"])
            except Exception:
                pass
            missing = sorted(power_nets - pwr_flag_nets)
            if missing:
                return [
                    f"Power nets without PWR_FLAG: {', '.join(missing)}. "
                    "Add a PWR_FLAG component to each to suppress ERC power-pin errors."
                ]
        except Exception:
            pass
        return []

    def batch_add_and_connect(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Place multiple components and connect their pins in a single call."""
        logger.info("Batch add-and-connect: placing components and wiring nets")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            raw_components = params.get("components", [])
            if not raw_components:
                return {
                    "success": False,
                    "message": "components list is required and must be non-empty",
                }

            components_for_add = []
            nets_per_ref: Dict[str, Any] = {}
            for comp in raw_components:
                components_for_add.append({k: v for k, v in comp.items() if k != "nets"})
                if comp.get("nets"):
                    nets_per_ref[comp.get("reference", "")] = comp["nets"]

            add_params = {k: v for k, v in params.items() if k != "components"}
            add_params["components"] = components_for_add
            add_result = self.batch_add_components(add_params)

            connect_result: Dict[str, Any] = {
                "placed": [],
                "failed": [],
                "message": "no nets specified",
            }
            if nets_per_ref:
                connect_result = self.batch_connect(
                    {"schematicPath": schematic_path, "connections": nets_per_ref}
                )

            add_errors = add_result.get("errors", [])
            conn_placed = connect_result.get("placed", [])
            conn_failed = connect_result.get("failed", [])

            return {
                "success": add_result.get("added_count", 0) > 0,
                "message": (
                    f"Placed {add_result.get('added_count', 0)} component(s)"
                    f"{' (' + str(len(add_errors)) + ' failed)' if add_errors else ''}, "
                    f"connected {len(conn_placed)} pin(s)"
                    f"{' (' + str(len(conn_failed)) + ' failed)' if conn_failed else ''}"
                ),
                "added_count": add_result.get("added_count", 0),
                "added": add_result.get("added", []),
                "connected_count": len(conn_placed),
                "connected": conn_placed,
                "placement_bbox": add_result.get("placement_bbox"),
                "errors": add_errors,
                "failed_connections": conn_failed,
                "warnings": connect_result.get("warnings", []),
            }

        except Exception as e:
            logger.error(f"Error in batch_add_and_connect: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def update_symbol_from_library(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Refresh lib_symbols cache entries from the symbol library."""
        from commands.update_symbol_from_library import update_symbol_from_library

        try:
            return update_symbol_from_library(params)
        except Exception as e:
            logger.error(f"Error in update_symbol_from_library: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}
