"""
Component-related command implementations for KiCAD interface
"""

import base64
import logging
import math
import os
from typing import Any, Dict, List, Optional, Tuple

import pcbnew
from commands.library import LibraryManager
from commands.placement_optimizer import PlacementOptimizerCommands

logger = logging.getLogger("kicad_interface")


class ComponentCommands(PlacementOptimizerCommands):
    """Handles component-related KiCAD operations"""

    def __init__(
        self, board: Optional[pcbnew.BOARD] = None, library_manager: Optional[LibraryManager] = None
    ):
        """Initialize with optional board instance and library manager"""
        self.board = board
        self.library_manager = library_manager or LibraryManager()

    def place_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Place a component on the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # Get parameters
            component_id = params.get("componentId")
            position = params.get("position")
            reference = params.get("reference")
            value = params.get("value")
            footprint = params.get("footprint")
            rotation = params.get("rotation", 0)
            layer = params.get("layer", "F.Cu")

            if not component_id or not position:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "componentId and position are required",
                }

            # Find footprint using library manager
            # component_id can be "Library:Footprint" or just "Footprint"
            footprint_result = self.library_manager.find_footprint(component_id)

            if not footprint_result:
                # Try to suggest similar footprints
                suggestions = self.library_manager.search_footprints(f"*{component_id}*", limit=5)
                suggestion_text = ""
                if suggestions:
                    suggestion_text = "\n\nDid you mean one of these?\n" + "\n".join(
                        [f"  - {s['full_name']}" for s in suggestions]
                    )

                return {
                    "success": False,
                    "message": "Footprint not found",
                    "errorDetails": f"Could not find footprint: {component_id}{suggestion_text}",
                }

            library_path, footprint_name = footprint_result

            # Load footprint from library
            # Extract library nickname from path
            library_nickname = None
            for nick, path in self.library_manager.libraries.items():
                if path == library_path:
                    library_nickname = nick
                    break

            if not library_nickname:
                return {
                    "success": False,
                    "message": "Internal error",
                    "errorDetails": "Could not determine library nickname",
                }

            # Load the footprint
            module = pcbnew.FootprintLoad(library_path, footprint_name)
            if not module:
                return {
                    "success": False,
                    "message": "Failed to load footprint",
                    "errorDetails": f"Could not load footprint from {library_path}/{footprint_name}",
                }

            # Set position
            scale = (
                1000000
                if position["unit"] == "mm"
                else (25400 if position["unit"] == "mil" else 25400000)
            )  # mm, mil, or inch to nm
            x_nm = int(position["x"] * scale)
            y_nm = int(position["y"] * scale)
            module.SetPosition(pcbnew.VECTOR2I(x_nm, y_nm))

            # Set reference if provided
            if reference:
                module.SetReference(reference)

            # Set value if provided
            if value:
                module.SetValue(value)

            # Set footprint if provided (use existing library_nickname and footprint_name)
            # For KiCAD 9.x compatibility, use SetFPID instead of SetFootprintName
            if footprint:
                # Parse footprint string if it's in "Library:Footprint" format
                if ":" in footprint:
                    lib_name, fp_name = footprint.split(":", 1)
                else:
                    # Use the library_nickname we already have from loading
                    lib_name = library_nickname
                    fp_name = footprint
                fpid = pcbnew.LIB_ID(lib_name, fp_name)
                module.SetFPID(fpid)
            else:
                # Use the footprint we just loaded
                fpid = pcbnew.LIB_ID(library_nickname, footprint_name)
                module.SetFPID(fpid)

            # Set rotation (KiCAD 9.0 uses EDA_ANGLE)
            angle = pcbnew.EDA_ANGLE(rotation, pcbnew.DEGREES_T)
            module.SetOrientation(angle)

            # Set layer for F.Cu (or non-B.Cu) before adding to board
            if layer != "B.Cu":
                layer_id = self.board.GetLayerID(layer)
                if layer_id >= 0:
                    module.SetLayer(layer_id)

            # Add to board first — Flip() requires board context in KiCAD 9
            self.board.Add(module)

            # Flip to B.Cu after add (board context needed, otherwise hangs 30s)
            if layer == "B.Cu":
                if not module.IsFlipped():
                    module.Flip(module.GetPosition(), False)

            return {
                "success": True,
                "message": f"Placed component: {component_id}",
                "component": {
                    "reference": module.GetReference(),
                    "value": module.GetValue(),
                    "position": {"x": position["x"], "y": position["y"], "unit": position["unit"]},
                    "rotation": rotation,
                    "layer": layer,
                },
            }

        except Exception as e:
            logger.error(f"Error placing component: {str(e)}")
            return {
                "success": False,
                "message": "Failed to place component",
                "errorDetails": str(e),
            }

    def move_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Move an existing component to a new position"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            reference = params.get("reference")
            position = params.get("position")
            rotation = params.get("rotation")
            layer = params.get("layer")

            if not reference or not position:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "reference and position are required",
                }

            # Find the component
            module = self.board.FindFootprintByReference(reference)
            if not module:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component: {reference}",
                }

            # Set new position
            scale = (
                1000000
                if position["unit"] == "mm"
                else (25400 if position["unit"] == "mil" else 25400000)
            )  # mm, mil, or inch to nm
            x_nm = int(position["x"] * scale)
            y_nm = int(position["y"] * scale)
            module.SetPosition(pcbnew.VECTOR2I(x_nm, y_nm))

            # Set new rotation if provided
            if rotation is not None:
                angle = pcbnew.EDA_ANGLE(rotation, pcbnew.DEGREES_T)
                module.SetOrientation(angle)

            # Flip to target layer if specified
            if layer:
                current_layer = self.board.GetLayerName(module.GetLayer())
                if layer == "B.Cu" and current_layer != "B.Cu":
                    module.Flip(module.GetPosition(), False)
                elif layer == "F.Cu" and current_layer != "F.Cu":
                    module.Flip(module.GetPosition(), False)

            return {
                "success": True,
                "message": f"Moved component: {reference}",
                "component": {
                    "reference": reference,
                    "position": {"x": position["x"], "y": position["y"], "unit": position["unit"]},
                    "rotation": (
                        rotation if rotation is not None else module.GetOrientation().AsDegrees()
                    ),
                    "layer": self.board.GetLayerName(module.GetLayer()),
                },
            }

        except Exception as e:
            logger.error(f"Error moving component: {str(e)}")
            return {"success": False, "message": "Failed to move component", "errorDetails": str(e)}

    def batch_move_components(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Move multiple footprints transactionally.

        ``moves`` accepts either ``{"R1": {"x": 10, "y": 20, "rot": 90}}`` or
        ``{"R1": {"position": {"x": 10, "y": 20, "unit": "mm"}, "rotation": 90}}``.
        If any reference or coordinate is invalid, no footprint is changed.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            moves = params.get("moves") or params.get("placements")
            if not isinstance(moves, dict) or not moves:
                return {
                    "success": False,
                    "message": "Missing moves",
                    "errorDetails": "moves must be a non-empty object keyed by reference",
                }

            dry_run = bool(params.get("dryRun", False))
            save = bool(params.get("save", True)) and not dry_run and not params.get("_deferSave")
            prepared = []
            missing = []

            for ref, spec in moves.items():
                module = self.board.FindFootprintByReference(ref)
                if not module:
                    missing.append(ref)
                    continue
                if not isinstance(spec, dict):
                    return {
                        "success": False,
                        "message": "Bad move spec",
                        "errorDetails": f"moves['{ref}'] must be an object",
                    }
                pos_spec = spec.get("position") if isinstance(spec.get("position"), dict) else spec
                if "x" not in pos_spec or "y" not in pos_spec:
                    return {
                        "success": False,
                        "message": "Bad move spec",
                        "errorDetails": f"moves['{ref}'] requires x and y",
                    }
                unit = pos_spec.get("unit", spec.get("unit", "mm"))
                scale = self._unit_to_nm(unit)
                x_nm = int(float(pos_spec["x"]) * scale)
                y_nm = int(float(pos_spec["y"]) * scale)
                rotation = spec.get("rotation", spec.get("rot"))
                layer = spec.get("layer")
                prepared.append((ref, module, x_nm, y_nm, rotation, layer, unit))

            if missing:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component(s): {', '.join(sorted(missing))}",
                }

            if dry_run:
                return {
                    "success": True,
                    "message": f"Validated {len(prepared)} component moves",
                    "dryRun": True,
                    "moved": [],
                }

            old_states = []
            try:
                for _ref, module, _x, _y, _rot, _layer, _unit in prepared:
                    old_states.append(
                        (
                            module,
                            module.GetPosition(),
                            module.GetOrientation(),
                            module.GetLayer(),
                        )
                    )

                moved = []
                for ref, module, x_nm, y_nm, rotation, layer, unit in prepared:
                    module.SetPosition(pcbnew.VECTOR2I(x_nm, y_nm))
                    if rotation is not None:
                        module.SetOrientation(pcbnew.EDA_ANGLE(float(rotation), pcbnew.DEGREES_T))
                    if layer:
                        current_layer = self.board.GetLayerName(module.GetLayer())
                        if layer in ("F.Cu", "B.Cu") and current_layer != layer:
                            module.Flip(module.GetPosition(), False)
                    moved.append(
                        {
                            "reference": ref,
                            "position": {
                                "x": x_nm / self._unit_to_nm(unit),
                                "y": y_nm / self._unit_to_nm(unit),
                                "unit": unit,
                            },
                            "rotation": module.GetOrientation().AsDegrees(),
                            "layer": self.board.GetLayerName(module.GetLayer()),
                        }
                    )

                if save:
                    board_path = self.board.GetFileName()
                    if not board_path:
                        raise RuntimeError("Board has no file path; cannot save batch move")
                    pcbnew.SaveBoard(board_path, self.board)

                return {
                    "success": True,
                    "message": f"Moved {len(moved)} component(s)",
                    "moved": moved,
                    "saved": save,
                }
            except Exception:
                for module, pos, orientation, layer_id in old_states:
                    try:
                        module.SetPosition(pos)
                        module.SetOrientation(orientation)
                        if module.GetLayer() != layer_id:
                            module.Flip(module.GetPosition(), False)
                    except Exception:
                        logger.warning("Failed to roll back footprint state", exc_info=True)
                raise

        except Exception as e:
            logger.error(f"Error batch moving components: {str(e)}")
            return {
                "success": False,
                "message": "Failed to batch move components",
                "errorDetails": str(e),
            }

    def rotate_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Rotate an existing component"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            reference = params.get("reference")
            angle = params.get("angle")

            if not reference or angle is None:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "reference and angle are required",
                }

            # Find the component
            module = self.board.FindFootprintByReference(reference)
            if not module:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component: {reference}",
                }

            # Set rotation
            rotation_angle = pcbnew.EDA_ANGLE(angle, pcbnew.DEGREES_T)
            module.SetOrientation(rotation_angle)

            return {
                "success": True,
                "message": f"Rotated component: {reference}",
                "component": {"reference": reference, "rotation": angle},
            }

        except Exception as e:
            logger.error(f"Error rotating component: {str(e)}")
            return {
                "success": False,
                "message": "Failed to rotate component",
                "errorDetails": str(e),
            }

    def delete_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a component from the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            reference = params.get("reference")
            if not reference:
                return {
                    "success": False,
                    "message": "Missing reference",
                    "errorDetails": "reference parameter is required",
                }

            # Find the component
            module = self.board.FindFootprintByReference(reference)
            if not module:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component: {reference}",
                }

            # Remove from board
            self.board.Remove(module)

            return {"success": True, "message": f"Deleted component: {reference}"}

        except Exception as e:
            logger.error(f"Error deleting component: {str(e)}")
            return {
                "success": False,
                "message": "Failed to delete component",
                "errorDetails": str(e),
            }

    def edit_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Edit the properties of an existing component"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            reference = params.get("reference")
            new_reference = params.get("newReference")
            value = params.get("value")
            footprint = params.get("footprint")

            if not reference:
                return {
                    "success": False,
                    "message": "Missing reference",
                    "errorDetails": "reference parameter is required",
                }

            # Find the component
            module = self.board.FindFootprintByReference(reference)
            if not module:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component: {reference}",
                }

            # Update properties
            if new_reference:
                module.SetReference(new_reference)
            if value:
                module.SetValue(value)
            if footprint:
                # For KiCAD 9.x compatibility, use SetFPID instead of SetFootprintName
                # Parse footprint string (format: "Library:Footprint")
                if ":" in footprint:
                    lib_name, fp_name = footprint.split(":", 1)
                    fpid = pcbnew.LIB_ID(lib_name, fp_name)
                    module.SetFPID(fpid)
                else:
                    # If no library specified, keep existing library
                    current_fpid = module.GetFPID()
                    lib_name = current_fpid.GetLibNickname().GetUTF8()
                    fpid = pcbnew.LIB_ID(lib_name, footprint)
                    module.SetFPID(fpid)

            return {
                "success": True,
                "message": f"Updated component: {reference}",
                "component": {
                    "reference": new_reference or reference,
                    "value": value or module.GetValue(),
                    "footprint": footprint or module.GetFPIDAsString(),
                },
            }

        except Exception as e:
            logger.error(f"Error editing component: {str(e)}")
            return {"success": False, "message": "Failed to edit component", "errorDetails": str(e)}

    def set_footprint_type(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Set the placement type and exclusion flags of an existing PCB footprint.

        The placement type controls whether a footprint appears in pick-and-place
        (.pos) output files. KiCAD recognises three types:
          - ``through_hole``  — PTH component (through-hole)
          - ``smd``           — SMD component (surface-mount)
          - ``unspecified``   — neither bit set (default for manually-placed items)

        Optional exclusion flags (omit to leave unchanged):
          - ``exclude_from_pos_files`` — suppress this ref from .pos exports
          - ``exclude_from_bom``       — suppress this ref from BoM exports
          - ``not_in_schematic``       — marks footprint as board-only (no schematic
                                         symbol); KiCAD stores this as FP_BOARD_ONLY
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            reference = params.get("reference")
            fp_type = params.get("type")

            if not reference:
                return {
                    "success": False,
                    "message": "Missing reference",
                    "errorDetails": "reference parameter is required",
                }
            if fp_type not in ("smd", "through_hole", "unspecified"):
                return {
                    "success": False,
                    "message": "Invalid type",
                    "errorDetails": "type must be one of: smd, through_hole, unspecified",
                }

            # Find the footprint
            module = self.board.FindFootprintByReference(reference)
            if not module:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component: {reference}",
                }

            # --- Placement type (mutually exclusive bits) ---
            # Read current attributes, clear both type bits, then set the new one.
            attrs = module.GetAttributes()
            attrs &= ~(pcbnew.FP_THROUGH_HOLE | pcbnew.FP_SMD)
            if fp_type == "through_hole":
                attrs |= pcbnew.FP_THROUGH_HOLE
            elif fp_type == "smd":
                attrs |= pcbnew.FP_SMD
            # "unspecified" leaves both bits clear
            module.SetAttributes(attrs)

            # --- Optional exclusion flags ---
            # Use the dedicated setters so we don't have to manage bit masks manually.
            if "exclude_from_pos_files" in params:
                module.SetExcludedFromPosFiles(bool(params["exclude_from_pos_files"]))
            if "exclude_from_bom" in params:
                module.SetExcludedFromBOM(bool(params["exclude_from_bom"]))
            if "not_in_schematic" in params:
                # FP_BOARD_ONLY is the underlying bit for the "not in schematic" flag.
                module.SetBoardOnly(bool(params["not_in_schematic"]))

            # Read back the final state so the caller can verify.
            final_attrs = module.GetAttributes()
            if final_attrs & pcbnew.FP_THROUGH_HOLE:
                resolved_type = "through_hole"
            elif final_attrs & pcbnew.FP_SMD:
                resolved_type = "smd"
            else:
                resolved_type = "unspecified"

            return {
                "success": True,
                "message": f"Updated footprint type for {reference}",
                "component": {
                    "reference": reference,
                    "type": resolved_type,
                    "exclude_from_pos_files": module.IsExcludedFromPosFiles(),
                    "exclude_from_bom": module.IsExcludedFromBOM(),
                    "not_in_schematic": module.IsBoardOnly(),
                },
            }

        except Exception as e:
            logger.error(f"Error setting footprint type: {str(e)}")
            return {
                "success": False,
                "message": "Failed to set footprint type",
                "errorDetails": str(e),
            }

    def get_component_properties(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get detailed properties of a component"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            reference = params.get("reference")
            if not reference:
                return {
                    "success": False,
                    "message": "Missing reference",
                    "errorDetails": "reference parameter is required",
                }

            # Find the component
            module = self.board.FindFootprintByReference(reference)
            if not module:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component: {reference}",
                }

            # Get position in mm
            pos = module.GetPosition()
            x_mm = pos.x / 1000000
            y_mm = pos.y / 1000000

            # Get bounding box
            bbox = module.GetBoundingBox()
            bbox_data = {
                "min_x": bbox.GetLeft() / 1000000,
                "min_y": bbox.GetTop() / 1000000,
                "max_x": bbox.GetRight() / 1000000,
                "max_y": bbox.GetBottom() / 1000000,
                "width": (bbox.GetRight() - bbox.GetLeft()) / 1000000,
                "height": (bbox.GetBottom() - bbox.GetTop()) / 1000000,
                "unit": "mm",
            }

            # Try to get courtyard bounds (preferred for placement clearance)
            courtyard_data = None
            try:
                for layer_id in [pcbnew.F_CrtYd, pcbnew.B_CrtYd]:
                    courtyard = module.GetCourtyard(layer_id)
                    if courtyard and courtyard.OutlineCount() > 0:
                        cbox = courtyard.BBox()
                        courtyard_data = {
                            "min_x": cbox.GetLeft() / 1000000,
                            "min_y": cbox.GetTop() / 1000000,
                            "max_x": cbox.GetRight() / 1000000,
                            "max_y": cbox.GetBottom() / 1000000,
                            "width": (cbox.GetRight() - cbox.GetLeft()) / 1000000,
                            "height": (cbox.GetBottom() - cbox.GetTop()) / 1000000,
                            "unit": "mm",
                        }
                        break
            except Exception:
                pass  # Courtyard may not exist or API may differ

            # Resolve placement type as a human-readable string
            raw_attrs = module.GetAttributes()
            if raw_attrs & pcbnew.FP_THROUGH_HOLE:
                placement_type = "through_hole"
            elif raw_attrs & pcbnew.FP_SMD:
                placement_type = "smd"
            else:
                placement_type = "unspecified"

            return {
                "success": True,
                "component": {
                    "reference": module.GetReference(),
                    "value": module.GetValue(),
                    "footprint": module.GetFPIDAsString(),
                    "position": {"x": x_mm, "y": y_mm, "unit": "mm"},
                    "rotation": module.GetOrientation().AsDegrees(),
                    "layer": self.board.GetLayerName(module.GetLayer()),
                    "attributes": {
                        "type": placement_type,
                        "exclude_from_pos_files": module.IsExcludedFromPosFiles(),
                        "exclude_from_bom": module.IsExcludedFromBOM(),
                        "not_in_schematic": module.IsBoardOnly(),
                    },
                    "boundingBox": bbox_data,
                    "courtyard": courtyard_data,
                },
            }

        except Exception as e:
            logger.error(f"Error getting component properties: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get component properties",
                "errorDetails": str(e),
            }

    def get_component_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a list of all components on the board"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            components = []
            for module in self.board.GetFootprints():
                pos = module.GetPosition()
                x_mm = pos.x / 1000000
                y_mm = pos.y / 1000000

                bbox = module.GetBoundingBox()
                bbox_data = {
                    "min_x": bbox.GetLeft() / 1000000,
                    "min_y": bbox.GetTop() / 1000000,
                    "max_x": bbox.GetRight() / 1000000,
                    "max_y": bbox.GetBottom() / 1000000,
                    "width": (bbox.GetRight() - bbox.GetLeft()) / 1000000,
                    "height": (bbox.GetBottom() - bbox.GetTop()) / 1000000,
                    "unit": "mm",
                }

                components.append(
                    {
                        "reference": module.GetReference(),
                        "value": module.GetValue(),
                        "footprint": module.GetFPIDAsString(),
                        "position": {"x": x_mm, "y": y_mm, "unit": "mm"},
                        "rotation": module.GetOrientation().AsDegrees(),
                        "layer": self.board.GetLayerName(module.GetLayer()),
                        "boundingBox": bbox_data,
                    }
                )

            return {"success": True, "components": components}

        except Exception as e:
            logger.error(f"Error getting component list: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get component list",
                "errorDetails": str(e),
            }

    def find_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Find components matching search criteria (reference, value, or footprint pattern)"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # Get search parameters
            reference_pattern = params.get("reference", "").lower()
            value_pattern = params.get("value", "").lower()
            footprint_pattern = params.get("footprint", "").lower()

            if not reference_pattern and not value_pattern and not footprint_pattern:
                return {
                    "success": False,
                    "message": "Missing search criteria",
                    "errorDetails": "At least one of reference, value, or footprint pattern is required",
                }

            matches = []
            for module in self.board.GetFootprints():
                ref = module.GetReference().lower()
                val = module.GetValue().lower()
                fp = module.GetFPIDAsString().lower()

                # Check if component matches all provided patterns
                match = True
                if reference_pattern and reference_pattern not in ref:
                    match = False
                if value_pattern and value_pattern not in val:
                    match = False
                if footprint_pattern and footprint_pattern not in fp:
                    match = False

                if match:
                    pos = module.GetPosition()
                    matches.append(
                        {
                            "reference": module.GetReference(),
                            "value": module.GetValue(),
                            "footprint": module.GetFPIDAsString(),
                            "position": {"x": pos.x / 1000000, "y": pos.y / 1000000, "unit": "mm"},
                            "rotation": module.GetOrientation().AsDegrees(),
                            "layer": self.board.GetLayerName(module.GetLayer()),
                        }
                    )

            return {"success": True, "matchCount": len(matches), "components": matches}

        except Exception as e:
            logger.error(f"Error finding components: {str(e)}")
            return {
                "success": False,
                "message": "Failed to find components",
                "errorDetails": str(e),
            }

    def get_component_pads(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get all pads for a component with their positions and net connections"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            reference = params.get("reference")
            if not reference:
                return {
                    "success": False,
                    "message": "Missing reference",
                    "errorDetails": "reference parameter is required",
                }

            # Find the component
            module = self.board.FindFootprintByReference(reference)
            if not module:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component: {reference}",
                }

            pads = []
            for pad in module.Pads():
                pos = pad.GetPosition()
                size = pad.GetSize()

                # Get pad shape as string
                shape_map = {
                    pcbnew.PAD_SHAPE_CIRCLE: "circle",
                    pcbnew.PAD_SHAPE_RECT: "rect",
                    pcbnew.PAD_SHAPE_OVAL: "oval",
                    pcbnew.PAD_SHAPE_TRAPEZOID: "trapezoid",
                    pcbnew.PAD_SHAPE_ROUNDRECT: "roundrect",
                    pcbnew.PAD_SHAPE_CHAMFERED_RECT: "chamfered_rect",
                    pcbnew.PAD_SHAPE_CUSTOM: "custom",
                }
                shape = shape_map.get(pad.GetShape(), "unknown")

                # Get pad type
                type_map = {
                    pcbnew.PAD_ATTRIB_PTH: "through_hole",
                    pcbnew.PAD_ATTRIB_SMD: "smd",
                    pcbnew.PAD_ATTRIB_CONN: "connector",
                    pcbnew.PAD_ATTRIB_NPTH: "npth",
                }
                pad_type = type_map.get(pad.GetAttribute(), "unknown")

                pads.append(
                    {
                        "name": pad.GetName(),
                        "number": pad.GetNumber(),
                        "position": {"x": pos.x / 1000000, "y": pos.y / 1000000, "unit": "mm"},
                        "net": pad.GetNetname(),
                        "netCode": pad.GetNetCode(),
                        "shape": shape,
                        "type": pad_type,
                        "size": {"x": size.x / 1000000, "y": size.y / 1000000, "unit": "mm"},
                        "drillSize": (
                            pad.GetDrillSize().x / 1000000 if pad.GetDrillSize().x > 0 else None
                        ),
                    }
                )

            # Get component position for reference
            comp_pos = module.GetPosition()

            return {
                "success": True,
                "reference": reference,
                "componentPosition": {
                    "x": comp_pos.x / 1000000,
                    "y": comp_pos.y / 1000000,
                    "unit": "mm",
                },
                "padCount": len(pads),
                "pads": pads,
            }

        except Exception as e:
            logger.error(f"Error getting component pads: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get component pads",
                "errorDetails": str(e),
            }

    def get_pads(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Alias-friendly pad query for one footprint or every footprint."""
        reference = params.get("reference") or params.get("ref")
        if reference:
            return self.get_component_pads(
                {"reference": reference, "unit": params.get("unit", "mm")}
            )
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }
            refs = params.get("refs")
            refs_filter = set(refs) if refs else None
            footprints = [
                fp
                for fp in self.board.GetFootprints()
                if refs_filter is None or fp.GetReference() in refs_filter
            ]
            pads = []
            for fp in footprints:
                pads.extend(self._pads_for_footprint(fp))
            return {"success": True, "padCount": len(pads), "pads": pads}
        except Exception as e:
            logger.error(f"Error getting pads: {str(e)}")
            return {"success": False, "message": "Failed to get pads", "errorDetails": str(e)}

    def get_net_pads(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return every pad attached to a net name or net code."""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }
            net = params.get("net")
            net_code = params.get("netCode")
            if net is None and net_code is None:
                return {
                    "success": False,
                    "message": "Missing net",
                    "errorDetails": "net or netCode is required",
                }
            pads = []
            for fp in self.board.GetFootprints():
                for pad in fp.Pads():
                    if net is not None and pad.GetNetname() != net:
                        continue
                    if net_code is not None and pad.GetNetCode() != net_code:
                        continue
                    pads.append(self._pad_payload(fp, pad))
            return {
                "success": True,
                "net": net,
                "netCode": net_code,
                "padCount": len(pads),
                "pads": pads,
            }
        except Exception as e:
            logger.error(f"Error getting net pads: {str(e)}")
            return {"success": False, "message": "Failed to get net pads", "errorDetails": str(e)}

    def get_component_geometry(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return separated footprint geometry bboxes.

        The aggregate ``GetBoundingBox()`` often includes text and keepouts, so
        placement tools need per-domain bboxes: body/fab, pads, courtyard,
        keepout, silk, text, plus the raw aggregate.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }
            reference = params.get("reference") or params.get("ref")
            refs = params.get("refs")
            if reference:
                refs = [reference]
            ref_filter = set(refs) if refs else None

            geometries = []
            for fp in self.board.GetFootprints():
                if ref_filter is not None and fp.GetReference() not in ref_filter:
                    continue
                geometries.append(self._footprint_geometry(fp))

            if reference:
                if not geometries:
                    return {
                        "success": False,
                        "message": "Component not found",
                        "errorDetails": f"Could not find component: {reference}",
                    }
                return {"success": True, "geometry": geometries[0]}
            return {"success": True, "count": len(geometries), "geometries": geometries}
        except Exception as e:
            logger.error(f"Error getting component geometry: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get component geometry",
                "errorDetails": str(e),
            }

    def get_ratsnest(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Estimate ratsnest/airwire segments from pad positions grouped by net.

        KiCad's live ratsnest is editor state, so this returns a deterministic
        minimum-spanning-tree estimate per net from current pad XY coordinates.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }
            nets_filter = params.get("nets")
            if nets_filter:
                nets_filter = set(nets_filter)
            max_pads_per_net = int(params.get("maxPadsPerNet", 128))
            grouped: Dict[str, List[Dict[str, Any]]] = {}
            for fp in self.board.GetFootprints():
                for pad in fp.Pads():
                    net = pad.GetNetname()
                    if not net or (nets_filter is not None and net not in nets_filter):
                        continue
                    grouped.setdefault(net, []).append(self._pad_payload(fp, pad))

            nets = []
            total_length = 0.0
            total_segments = 0
            for net, pads in sorted(grouped.items()):
                if len(pads) > max_pads_per_net:
                    nets.append(
                        {
                            "net": net,
                            "padCount": len(pads),
                            "skipped": True,
                            "reason": f"pad count exceeds maxPadsPerNet={max_pads_per_net}",
                        }
                    )
                    continue
                segments = self._mst_airwires(pads)
                length = sum(seg["length_mm"] for seg in segments)
                total_length += length
                total_segments += len(segments)
                nets.append(
                    {
                        "net": net,
                        "padCount": len(pads),
                        "segmentCount": len(segments),
                        "estimatedLengthMm": round(length, 3),
                        "segments": segments,
                    }
                )
            return {
                "success": True,
                "netCount": len(nets),
                "segmentCount": total_segments,
                "estimatedLengthMm": round(total_length, 3),
                "nets": nets,
            }
        except Exception as e:
            logger.error(f"Error estimating ratsnest: {str(e)}")
            return {
                "success": False,
                "message": "Failed to estimate ratsnest",
                "errorDetails": str(e),
            }

    def estimate_airwire_lengths(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Alias for get_ratsnest."""
        return self.get_ratsnest(params)

    def check_placement_clearance(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Classify placement conflicts by geometry domain.

        This is a fast placement pre-check; copper-rule DRC remains available
        through ``run_drc``. The result separates body, courtyard, keepout,
        silkscreen/text and pad bbox conflicts so callers can decide whether a
        proposed placement is merely untidy or physically illegal.
        """
        try:
            geom_result = self.get_component_geometry({"refs": params.get("refs")})
            if not geom_result.get("success"):
                return geom_result
            geometries = geom_result.get("geometries", [])
            margin = float(params.get("margin", 0.0))
            pad_clearance = float(params.get("padClearance", params.get("pad_clearance", 0.0)))
            violations = []
            checks = [
                ("body_overlap", "body_bbox", "body_bbox", margin),
                ("courtyard_overlap", "courtyard_bbox", "courtyard_bbox", margin),
                ("keepout_violation", "keepout_bbox", "body_bbox", margin),
                ("silk_overlap", "silk_bbox", "silk_bbox", margin),
                ("text_overlap", "text_bbox", "text_bbox", margin),
                ("pad_clearance", "pads_bbox", "pads_bbox", pad_clearance),
            ]
            for i in range(len(geometries)):
                for j in range(i + 1, len(geometries)):
                    a = geometries[i]
                    b = geometries[j]
                    for vtype, a_key, b_key, clearance in checks:
                        for left, right in ((a, b), (b, a)) if a_key != b_key else ((a, b),):
                            abox = left.get(a_key)
                            bbox = right.get(b_key)
                            overlap = self._bbox_overlap(abox, bbox, clearance)
                            if overlap:
                                violations.append(
                                    {
                                        "type": vtype,
                                        "a": left["reference"],
                                        "b": right["reference"],
                                        "bbox": overlap,
                                    }
                                )
            summary: Dict[str, int] = {}
            for violation in violations:
                summary[violation["type"]] = summary.get(violation["type"], 0) + 1
            return {
                "success": True,
                "clear": len(violations) == 0,
                "violationCount": len(violations),
                "summary": summary,
                "violations": violations,
            }
        except Exception as e:
            logger.error(f"Error checking placement clearance: {str(e)}")
            return {
                "success": False,
                "message": "Failed to check placement clearance",
                "errorDetails": str(e),
            }

    def move_footprint_text(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Move or update a footprint's reference/value/user text field."""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }
            reference = params.get("reference") or params.get("ref")
            field = params.get("field", "reference")
            if not reference:
                return {"success": False, "message": "reference is required"}
            fp = self.board.FindFootprintByReference(reference)
            if not fp:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component: {reference}",
                }
            text_item = self._find_footprint_text(fp, field)
            if text_item is None:
                return {
                    "success": False,
                    "message": "Footprint text not found",
                    "errorDetails": f"Could not find field '{field}' on {reference}",
                }
            unit = params.get("unit", "mm")
            if "x" in params and "y" in params:
                text_item.SetPosition(
                    pcbnew.VECTOR2I(
                        int(float(params["x"]) * self._unit_to_nm(unit)),
                        int(float(params["y"]) * self._unit_to_nm(unit)),
                    )
                )
            if params.get("rotation") is not None:
                angle = float(params["rotation"])
                if hasattr(text_item, "SetTextAngle"):
                    text_item.SetTextAngle(pcbnew.EDA_ANGLE(angle, pcbnew.DEGREES_T))
                elif hasattr(text_item, "SetTextAngleDegrees"):
                    text_item.SetTextAngleDegrees(angle)
            if params.get("layer"):
                text_item.SetLayer(self.board.GetLayerID(params["layer"]))
            if params.get("visible") is not None:
                if hasattr(text_item, "SetVisible"):
                    text_item.SetVisible(bool(params["visible"]))
                elif hasattr(text_item, "SetShown"):
                    text_item.SetShown(bool(params["visible"]))
            pos = text_item.GetPosition()
            return {
                "success": True,
                "message": f"Moved {reference} {field} text",
                "text": {
                    "reference": reference,
                    "field": field,
                    "position": {"x": pos.x / 1_000_000, "y": pos.y / 1_000_000, "unit": "mm"},
                    "layer": self.board.GetLayerName(text_item.GetLayer()),
                },
            }
        except Exception as e:
            logger.error(f"Error moving footprint text: {str(e)}")
            return {
                "success": False,
                "message": "Failed to move footprint text",
                "errorDetails": str(e),
            }

    def get_pad_position(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get the position of a specific pad on a component"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            reference = params.get("reference")
            pad_name = params.get("padName") or params.get("padNumber") or params.get("pad")

            if not reference:
                return {
                    "success": False,
                    "message": "Missing reference",
                    "errorDetails": "reference parameter is required",
                }
            if not pad_name:
                return {
                    "success": False,
                    "message": "Missing pad identifier",
                    "errorDetails": "padName or padNumber parameter is required",
                }

            # Find the component
            module = self.board.FindFootprintByReference(reference)
            if not module:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component: {reference}",
                }

            # Find the specific pad
            pad = module.FindPadByNumber(str(pad_name))
            if not pad:
                # List available pads in error message
                available_pads = [p.GetNumber() for p in module.Pads()]
                return {
                    "success": False,
                    "message": "Pad not found",
                    "errorDetails": f"Pad '{pad_name}' not found on {reference}. Available pads: {', '.join(available_pads)}",
                }

            pos = pad.GetPosition()
            size = pad.GetSize()

            return {
                "success": True,
                "reference": reference,
                "padName": pad.GetNumber(),
                "position": {"x": pos.x / 1000000, "y": pos.y / 1000000, "unit": "mm"},
                "net": pad.GetNetname(),
                "netCode": pad.GetNetCode(),
                "size": {"x": size.x / 1000000, "y": size.y / 1000000, "unit": "mm"},
            }

        except Exception as e:
            logger.error(f"Error getting pad position: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get pad position",
                "errorDetails": str(e),
            }

    def place_component_array(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Place an array of components in a grid or circular pattern"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            component_id = params.get("componentId")
            pattern = params.get("pattern", "grid")  # grid or circular
            count = params.get("count")
            reference_prefix = params.get("referencePrefix", "U")
            value = params.get("value")

            if not component_id or not count:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "componentId and count are required",
                }

            if pattern == "grid":
                start_position = params.get("startPosition")
                rows = params.get("rows")
                columns = params.get("columns")
                spacing_x = params.get("spacingX")
                spacing_y = params.get("spacingY")
                rotation = params.get("rotation", 0)
                layer = params.get("layer", "F.Cu")

                if not start_position or not rows or not columns or not spacing_x or not spacing_y:
                    return {
                        "success": False,
                        "message": "Missing grid parameters",
                        "errorDetails": "For grid pattern, startPosition, rows, columns, spacingX, and spacingY are required",
                    }

                if rows * columns != count:
                    return {
                        "success": False,
                        "message": "Invalid grid parameters",
                        "errorDetails": "rows * columns must equal count",
                    }

                placed_components = self._place_grid_array(
                    component_id,
                    start_position,
                    rows,
                    columns,
                    spacing_x,
                    spacing_y,
                    reference_prefix,
                    value,
                    rotation,
                    layer,
                )

            elif pattern == "circular":
                center = params.get("center")
                radius = params.get("radius")
                angle_start = params.get("angleStart", 0)
                angle_step = params.get("angleStep")
                rotation_offset = params.get("rotationOffset", 0)
                layer = params.get("layer", "F.Cu")

                if not center or not radius or not angle_step:
                    return {
                        "success": False,
                        "message": "Missing circular parameters",
                        "errorDetails": "For circular pattern, center, radius, and angleStep are required",
                    }

                placed_components = self._place_circular_array(
                    component_id,
                    center,
                    radius,
                    count,
                    angle_start,
                    angle_step,
                    reference_prefix,
                    value,
                    rotation_offset,
                    layer,
                )

            else:
                return {
                    "success": False,
                    "message": "Invalid pattern",
                    "errorDetails": "Pattern must be 'grid' or 'circular'",
                }

            return {
                "success": True,
                "message": f"Placed {count} components in {pattern} pattern",
                "components": placed_components,
            }

        except Exception as e:
            logger.error(f"Error placing component array: {str(e)}")
            return {
                "success": False,
                "message": "Failed to place component array",
                "errorDetails": str(e),
            }

    def align_components(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Align multiple components along a line or distribute them evenly"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            references = params.get("references", [])
            alignment = params.get("alignment", "horizontal")  # horizontal, vertical, or edge
            distribution = params.get("distribution", "none")  # none, equal, or spacing
            spacing = params.get("spacing")

            if not references or len(references) < 2:
                return {
                    "success": False,
                    "message": "Missing references",
                    "errorDetails": "At least two component references are required",
                }

            # Find all referenced components
            components = []
            for ref in references:
                module = self.board.FindFootprintByReference(ref)
                if not module:
                    return {
                        "success": False,
                        "message": "Component not found",
                        "errorDetails": f"Could not find component: {ref}",
                    }
                components.append(module)

            # Perform alignment based on selected option
            if alignment == "horizontal":
                self._align_components_horizontally(components, distribution, spacing)
            elif alignment == "vertical":
                self._align_components_vertically(components, distribution, spacing)
            elif alignment == "edge":
                edge = params.get("edge")
                if not edge:
                    return {
                        "success": False,
                        "message": "Missing edge parameter",
                        "errorDetails": "Edge parameter is required for edge alignment",
                    }
                self._align_components_to_edge(components, edge)
            else:
                return {
                    "success": False,
                    "message": "Invalid alignment option",
                    "errorDetails": "Alignment must be 'horizontal', 'vertical', or 'edge'",
                }

            # Prepare result data
            aligned_components = []
            for module in components:
                pos = module.GetPosition()
                aligned_components.append(
                    {
                        "reference": module.GetReference(),
                        "position": {"x": pos.x / 1000000, "y": pos.y / 1000000, "unit": "mm"},
                        "rotation": module.GetOrientation().AsDegrees(),
                    }
                )

            return {
                "success": True,
                "message": f"Aligned {len(components)} components",
                "alignment": alignment,
                "distribution": distribution,
                "components": aligned_components,
            }

        except Exception as e:
            logger.error(f"Error aligning components: {str(e)}")
            return {
                "success": False,
                "message": "Failed to align components",
                "errorDetails": str(e),
            }

    def duplicate_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Duplicate an existing component"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            reference = params.get("reference")
            new_reference = params.get("newReference")
            position = params.get("position")
            rotation = params.get("rotation")

            if not reference or not new_reference:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "reference and newReference are required",
                }

            # Find the source component
            source = self.board.FindFootprintByReference(reference)
            if not source:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component: {reference}",
                }

            # Check if new reference already exists
            if self.board.FindFootprintByReference(new_reference):
                return {
                    "success": False,
                    "message": "Reference already exists",
                    "errorDetails": f"A component with reference {new_reference} already exists",
                }

            # Create new footprint with the same properties
            new_module = pcbnew.FOOTPRINT(self.board)
            # For KiCAD 9.x compatibility, use SetFPID instead of SetFootprintName
            new_module.SetFPID(source.GetFPID())
            new_module.SetValue(source.GetValue())
            new_module.SetReference(new_reference)
            new_module.SetLayer(source.GetLayer())

            # Copy pads and other items
            for pad in source.Pads():
                new_pad = pcbnew.PAD(new_module)
                new_pad.Copy(pad)
                new_module.Add(new_pad)

            # Set position if provided, otherwise use offset from original
            if position:
                scale = (
                    1000000
                    if position.get("unit", "mm") == "mm"
                    else (25400 if position.get("unit", "mm") == "mil" else 25400000)
                )  # mm, mil, or inch to nm
                x_nm = int(position["x"] * scale)
                y_nm = int(position["y"] * scale)
                new_module.SetPosition(pcbnew.VECTOR2I(x_nm, y_nm))
            else:
                # Offset by 5mm
                source_pos = source.GetPosition()
                new_module.SetPosition(pcbnew.VECTOR2I(source_pos.x + 5000000, source_pos.y))

            # Set rotation if provided, otherwise use same as original
            if rotation is not None:
                rotation_angle = pcbnew.EDA_ANGLE(rotation, pcbnew.DEGREES_T)
                new_module.SetOrientation(rotation_angle)
            else:
                new_module.SetOrientation(source.GetOrientation())

            # Add to board
            self.board.Add(new_module)

            # Get final position in mm
            pos = new_module.GetPosition()

            return {
                "success": True,
                "message": f"Duplicated component {reference} to {new_reference}",
                "component": {
                    "reference": new_reference,
                    "value": new_module.GetValue(),
                    "footprint": new_module.GetFPIDAsString(),
                    "position": {"x": pos.x / 1000000, "y": pos.y / 1000000, "unit": "mm"},
                    "rotation": new_module.GetOrientation().AsDegrees(),
                    "layer": self.board.GetLayerName(new_module.GetLayer()),
                },
            }

        except Exception as e:
            logger.error(f"Error duplicating component: {str(e)}")
            return {
                "success": False,
                "message": "Failed to duplicate component",
                "errorDetails": str(e),
            }

    def _place_grid_array(
        self,
        component_id: str,
        start_position: Dict[str, Any],
        rows: int,
        columns: int,
        spacing_x: float,
        spacing_y: float,
        reference_prefix: str,
        value: str,
        rotation: float,
        layer: str,
    ) -> List[Dict[str, Any]]:
        """Place components in a grid pattern and return the list of placed components"""
        placed = []

        # Convert spacing to nm
        unit = start_position.get("unit", "mm")
        scale = (
            1000000 if unit == "mm" else (25400 if unit == "mil" else 25400000)
        )  # mm, mil, or inch to nm
        spacing_x_nm = int(spacing_x * scale)
        spacing_y_nm = int(spacing_y * scale)

        # Get layer ID
        layer_id = self.board.GetLayerID(layer)

        for row in range(rows):
            for col in range(columns):
                # Calculate position
                x = start_position["x"] + (col * spacing_x)
                y = start_position["y"] + (row * spacing_y)

                # Generate reference
                index = row * columns + col + 1
                component_reference = f"{reference_prefix}{index}"

                # Place component
                result = self.place_component(
                    {
                        "componentId": component_id,
                        "position": {"x": x, "y": y, "unit": unit},
                        "reference": component_reference,
                        "value": value,
                        "rotation": rotation,
                        "layer": layer,
                    }
                )

                if result["success"]:
                    placed.append(result["component"])

        return placed

    def _place_circular_array(
        self,
        component_id: str,
        center: Dict[str, Any],
        radius: float,
        count: int,
        angle_start: float,
        angle_step: float,
        reference_prefix: str,
        value: str,
        rotation_offset: float,
        layer: str,
    ) -> List[Dict[str, Any]]:
        """Place components in a circular pattern and return the list of placed components"""
        placed = []

        # Get unit
        unit = center.get("unit", "mm")

        for i in range(count):
            # Calculate angle for this component
            angle = angle_start + (i * angle_step)
            angle_rad = math.radians(angle)

            # Calculate position
            x = center["x"] + (radius * math.cos(angle_rad))
            y = center["y"] + (radius * math.sin(angle_rad))

            # Generate reference
            component_reference = f"{reference_prefix}{i+1}"

            # Calculate rotation (pointing outward from center)
            component_rotation = angle + rotation_offset

            # Place component
            result = self.place_component(
                {
                    "componentId": component_id,
                    "position": {"x": x, "y": y, "unit": unit},
                    "reference": component_reference,
                    "value": value,
                    "rotation": component_rotation,
                    "layer": layer,
                }
            )

            if result["success"]:
                placed.append(result["component"])

        return placed

    def _align_components_horizontally(
        self, components: List[pcbnew.FOOTPRINT], distribution: str, spacing: Optional[float]
    ) -> None:
        """Align components horizontally and optionally distribute them"""
        if not components:
            return

        # Find the average Y coordinate
        y_sum = sum(module.GetPosition().y for module in components)
        y_avg = y_sum // len(components)

        # Sort components by X position
        components.sort(key=lambda m: m.GetPosition().x)

        # Set Y coordinate for all components
        for module in components:
            pos = module.GetPosition()
            module.SetPosition(pcbnew.VECTOR2I(pos.x, y_avg))

        # Handle distribution if requested
        if distribution == "equal" and len(components) > 1:
            # Get leftmost and rightmost X coordinates
            x_min = components[0].GetPosition().x
            x_max = components[-1].GetPosition().x

            # Calculate equal spacing
            total_space = x_max - x_min
            spacing_nm = total_space // (len(components) - 1)

            # Set X positions with equal spacing
            for i in range(1, len(components) - 1):
                pos = components[i].GetPosition()
                new_x = x_min + (i * spacing_nm)
                components[i].SetPosition(pcbnew.VECTOR2I(new_x, pos.y))

        elif distribution == "spacing" and spacing is not None:
            # Convert spacing to nanometers
            spacing_nm = int(spacing * 1000000)  # assuming mm

            # Set X positions with the specified spacing
            x_current = components[0].GetPosition().x
            for i in range(1, len(components)):
                pos = components[i].GetPosition()
                x_current += spacing_nm
                components[i].SetPosition(pcbnew.VECTOR2I(x_current, pos.y))

    def _align_components_vertically(
        self, components: List[pcbnew.FOOTPRINT], distribution: str, spacing: Optional[float]
    ) -> None:
        """Align components vertically and optionally distribute them"""
        if not components:
            return

        # Find the average X coordinate
        x_sum = sum(module.GetPosition().x for module in components)
        x_avg = x_sum // len(components)

        # Sort components by Y position
        components.sort(key=lambda m: m.GetPosition().y)

        # Set X coordinate for all components
        for module in components:
            pos = module.GetPosition()
            module.SetPosition(pcbnew.VECTOR2I(x_avg, pos.y))

        # Handle distribution if requested
        if distribution == "equal" and len(components) > 1:
            # Get topmost and bottommost Y coordinates
            y_min = components[0].GetPosition().y
            y_max = components[-1].GetPosition().y

            # Calculate equal spacing
            total_space = y_max - y_min
            spacing_nm = total_space // (len(components) - 1)

            # Set Y positions with equal spacing
            for i in range(1, len(components) - 1):
                pos = components[i].GetPosition()
                new_y = y_min + (i * spacing_nm)
                components[i].SetPosition(pcbnew.VECTOR2I(pos.x, new_y))

        elif distribution == "spacing" and spacing is not None:
            # Convert spacing to nanometers
            spacing_nm = int(spacing * 1000000)  # assuming mm

            # Set Y positions with the specified spacing
            y_current = components[0].GetPosition().y
            for i in range(1, len(components)):
                pos = components[i].GetPosition()
                y_current += spacing_nm
                components[i].SetPosition(pcbnew.VECTOR2I(pos.x, y_current))

    def _align_components_to_edge(self, components: List[pcbnew.FOOTPRINT], edge: str) -> None:
        """Align components to the specified edge of the board"""
        if not components:
            return

        # Get board bounds
        board_box = self.board.GetBoardEdgesBoundingBox()
        left = board_box.GetLeft()
        right = board_box.GetRight()
        top = board_box.GetTop()
        bottom = board_box.GetBottom()

        # Align based on specified edge
        if edge == "left":
            for module in components:
                pos = module.GetPosition()
                module.SetPosition(pcbnew.VECTOR2I(left + 2000000, pos.y))  # 2mm offset from edge
        elif edge == "right":
            for module in components:
                pos = module.GetPosition()
                module.SetPosition(pcbnew.VECTOR2I(right - 2000000, pos.y))  # 2mm offset from edge
        elif edge == "top":
            for module in components:
                pos = module.GetPosition()
                module.SetPosition(pcbnew.VECTOR2I(pos.x, top + 2000000))  # 2mm offset from edge
        elif edge == "bottom":
            for module in components:
                pos = module.GetPosition()
                module.SetPosition(pcbnew.VECTOR2I(pos.x, bottom - 2000000))  # 2mm offset from edge
        else:
            logger.warning(f"Unknown edge alignment: {edge}")

    # -----------------------------------------------------------------------
    # check_courtyard_overlaps
    #
    # Originally prototyped in morningfire-pcb-automation
    #   https://github.com/NiNjA-CodE/morningfire-pcb-automation
    #   (scripts/placement/check_overlaps.py — AABB lookup-table version)
    #
    # The version here uses the real courtyard polygons from the loaded
    # board (more accurate than a static lookup), with virtual-placement
    # support so an AI can validate a proposed move before committing it.
    # -----------------------------------------------------------------------
    def check_courtyard_overlaps(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Detect courtyard overlaps between footprints (and board-edge violations).

        Each footprint has an F.Courtyard / B.Courtyard polygon that defines its
        physical keepout. KiCad's own DRC reports `courtyards_overlap` after the
        fact; this tool lets the caller check ahead of time — either against
        the current placement or against a hypothetical placement
        (``positions``) that hasn't been committed to the board yet.

        Args:
            positions: Optional dict ``{ref: [x, y]}`` or ``{ref: [x, y, rot]}``
                in mm/degrees. Virtual placements: the listed refs are
                temporarily considered to be at the given (x, y[, rot]). The
                board file is not modified.
            refs: Optional list of reference designators to limit the check
                to. Default: every footprint on the board.
            margin: Extra clearance in mm to enforce around each courtyard
                (default 0). Overlaps below this margin are flagged.
            include_boundary: If True (default), also flag courtyards that
                extend past the board outline.
            board_outline: Optional ``{"x1": ..., "y1": ..., "x2": ..., "y2":
                ..., "unit": "mm"|"inch"}`` override; otherwise the board's
                Edge.Cuts bounding box is used.

        Returns:
            ``{"success": True, "overlaps": [...], "boundary_violations": [...],
                "summary": {...}}``
            Each overlap entry has ``{a, b, overlap_x_mm, overlap_y_mm,
            overlap_area_mm2, bbox}``; each boundary entry has
            ``{ref, bbox, exceeds: {top, bottom, left, right} in mm}``.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            ref_filter = params.get("refs")
            if ref_filter is not None:
                ref_filter = set(ref_filter)

            margin_mm = float(params.get("margin", 0.0))
            include_boundary = bool(params.get("include_boundary", True))

            virtual = {}
            for ref, spec in (params.get("positions") or {}).items():
                if not isinstance(spec, (list, tuple)) or len(spec) not in (2, 3):
                    return {
                        "success": False,
                        "message": "Bad position spec",
                        "errorDetails": f"positions['{ref}'] must be [x, y] or [x, y, rot]; "
                        f"got {spec!r}",
                    }
                virtual[ref] = spec

            # Resolve board outline once.
            outline_bbox = self._resolve_outline_bbox(params.get("board_outline"))

            # Gather courtyard bboxes for every footprint we'll consider.
            entries = []
            for fp in self.board.GetFootprints():
                ref = fp.GetReference()
                if ref_filter is not None and ref not in ref_filter:
                    continue
                bbox = self._footprint_courtyard_bbox(fp, virtual.get(ref))
                if bbox is None:
                    continue
                # Expand by margin
                if margin_mm:
                    x1, y1, x2, y2 = bbox
                    bbox = (x1 - margin_mm, y1 - margin_mm, x2 + margin_mm, y2 + margin_mm)
                entries.append((ref, bbox))

            # Pairwise overlap (AABB intersect — matches KiCad DRC's
            # courtyard-overlap detection model).
            overlaps = []
            entries_sorted = sorted(entries, key=lambda e: e[0])
            for i in range(len(entries_sorted)):
                a_ref, a = entries_sorted[i]
                for j in range(i + 1, len(entries_sorted)):
                    b_ref, b = entries_sorted[j]
                    if a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]:
                        ox = min(a[2], b[2]) - max(a[0], b[0])
                        oy = min(a[3], b[3]) - max(a[1], b[1])
                        overlaps.append(
                            {
                                "a": a_ref,
                                "b": b_ref,
                                "overlap_x_mm": round(ox, 3),
                                "overlap_y_mm": round(oy, 3),
                                "overlap_area_mm2": round(ox * oy, 4),
                                "bbox": {
                                    "x1": round(max(a[0], b[0]), 3),
                                    "y1": round(max(a[1], b[1]), 3),
                                    "x2": round(min(a[2], b[2]), 3),
                                    "y2": round(min(a[3], b[3]), 3),
                                    "unit": "mm",
                                },
                            }
                        )

            # Boundary violations
            boundary_violations = []
            if include_boundary and outline_bbox is not None:
                ox1, oy1, ox2, oy2 = outline_bbox
                for ref, bbox in entries_sorted:
                    x1, y1, x2, y2 = bbox
                    exceeds = {}
                    if x1 < ox1 - 1e-6:
                        exceeds["left"] = round(ox1 - x1, 3)
                    if x2 > ox2 + 1e-6:
                        exceeds["right"] = round(x2 - ox2, 3)
                    if y1 < oy1 - 1e-6:
                        exceeds["top"] = round(oy1 - y1, 3)
                    if y2 > oy2 + 1e-6:
                        exceeds["bottom"] = round(y2 - oy2, 3)
                    if exceeds:
                        boundary_violations.append(
                            {
                                "ref": ref,
                                "bbox": {
                                    "x1": round(x1, 3),
                                    "y1": round(y1, 3),
                                    "x2": round(x2, 3),
                                    "y2": round(y2, 3),
                                    "unit": "mm",
                                },
                                "exceeds": exceeds,
                            }
                        )

            return {
                "success": True,
                "overlaps": overlaps,
                "boundary_violations": boundary_violations,
                "summary": {
                    "checked": len(entries_sorted),
                    "overlap_count": len(overlaps),
                    "boundary_violation_count": len(boundary_violations),
                    "margin_mm": margin_mm,
                    "virtual_placements": len(virtual),
                    "board_outline_mm": (
                        None
                        if outline_bbox is None
                        else {
                            "x1": round(outline_bbox[0], 3),
                            "y1": round(outline_bbox[1], 3),
                            "x2": round(outline_bbox[2], 3),
                            "y2": round(outline_bbox[3], 3),
                            "unit": "mm",
                        }
                    ),
                },
            }
        except Exception as e:
            logger.error(f"check_courtyard_overlaps failed: {e}", exc_info=True)
            return {
                "success": False,
                "message": "check_courtyard_overlaps failed",
                "errorDetails": str(e),
            }

    # --- helpers for check_courtyard_overlaps ----------------------------

    @staticmethod
    def _nm_to_mm(v):
        return v / 1_000_000.0

    @staticmethod
    def _unit_to_nm(unit: str) -> float:
        unit = (unit or "mm").lower()
        if unit == "mm":
            return 1_000_000.0
        if unit == "mil":
            return 25_400.0
        if unit in ("inch", "in"):
            return 25_400_000.0
        raise ValueError(f"Unsupported unit: {unit}")

    @staticmethod
    def _bbox_payload(box) -> Optional[Dict[str, Any]]:
        if box is None:
            return None
        try:
            raw_left = box.GetLeft()
            raw_top = box.GetTop()
            raw_right = box.GetRight()
            raw_bottom = box.GetBottom()
            if not all(
                isinstance(v, (int, float)) for v in (raw_left, raw_top, raw_right, raw_bottom)
            ):
                return None
            left = raw_left / 1_000_000.0
            top = raw_top / 1_000_000.0
            right = raw_right / 1_000_000.0
            bottom = raw_bottom / 1_000_000.0
        except Exception:
            return None
        return {
            "min_x": left,
            "min_y": top,
            "max_x": right,
            "max_y": bottom,
            "width": right - left,
            "height": bottom - top,
            "unit": "mm",
        }

    @staticmethod
    def _bbox_from_points(points: List[Tuple[float, float]]) -> Optional[Dict[str, Any]]:
        if not points:
            return None
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return {
            "min_x": min(xs),
            "min_y": min(ys),
            "max_x": max(xs),
            "max_y": max(ys),
            "width": max(xs) - min(xs),
            "height": max(ys) - min(ys),
            "unit": "mm",
        }

    @classmethod
    def _merge_bboxes(cls, boxes: List[Optional[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
        clean = [
            b
            for b in boxes
            if b
            and all(
                isinstance(b.get(k), (int, float)) for k in ("min_x", "min_y", "max_x", "max_y")
            )
        ]
        if not clean:
            return None
        return {
            "min_x": min(b["min_x"] for b in clean),
            "min_y": min(b["min_y"] for b in clean),
            "max_x": max(b["max_x"] for b in clean),
            "max_y": max(b["max_y"] for b in clean),
            "width": max(b["max_x"] for b in clean) - min(b["min_x"] for b in clean),
            "height": max(b["max_y"] for b in clean) - min(b["min_y"] for b in clean),
            "unit": "mm",
        }

    def _pads_for_footprint(self, fp) -> List[Dict[str, Any]]:
        return [self._pad_payload(fp, pad) for pad in fp.Pads()]

    def _pad_payload(self, fp, pad) -> Dict[str, Any]:
        pos = pad.GetPosition()
        size = pad.GetSize()
        drill = pad.GetDrillSize() if hasattr(pad, "GetDrillSize") else None
        layers = []
        try:
            layer_set = pad.GetLayerSet()
            for layer_id in range(pcbnew.PCB_LAYER_ID_COUNT):
                if layer_set.Contains(layer_id):
                    layers.append(self.board.GetLayerName(layer_id))
        except Exception:
            try:
                layers.append(self.board.GetLayerName(pad.GetLayer()))
            except Exception:
                pass
        return {
            "reference": fp.GetReference(),
            "name": pad.GetName() if hasattr(pad, "GetName") else pad.GetNumber(),
            "number": pad.GetNumber(),
            "position": {"x": pos.x / 1_000_000, "y": pos.y / 1_000_000, "unit": "mm"},
            "net": pad.GetNetname(),
            "netCode": pad.GetNetCode(),
            "layers": layers,
            "size": {"x": size.x / 1_000_000, "y": size.y / 1_000_000, "unit": "mm"},
            "drillSize": (
                None
                if drill is None or getattr(drill, "x", 0) <= 0
                else {"x": drill.x / 1_000_000, "y": drill.y / 1_000_000, "unit": "mm"}
            ),
            "bbox": self._bbox_payload(
                pad.GetBoundingBox() if hasattr(pad, "GetBoundingBox") else None
            ),
        }

    def _footprint_geometry(self, fp) -> Dict[str, Any]:
        pos = fp.GetPosition()
        layer = self.board.GetLayerName(fp.GetLayer())
        raw_bbox = self._bbox_payload(fp.GetBoundingBox())
        pads_bbox = self._merge_bboxes(
            [
                self._bbox_payload(pad.GetBoundingBox())
                for pad in fp.Pads()
                if hasattr(pad, "GetBoundingBox")
            ]
        )
        if pads_bbox is None:
            pad_points = []
            for pad in fp.Pads():
                p = pad.GetPosition()
                s = pad.GetSize()
                pad_points.extend(
                    [
                        ((p.x - s.x / 2) / 1_000_000, (p.y - s.y / 2) / 1_000_000),
                        ((p.x + s.x / 2) / 1_000_000, (p.y + s.y / 2) / 1_000_000),
                    ]
                )
            pads_bbox = self._bbox_from_points(pad_points)

        courtyard_boxes = []
        for layer_id in (getattr(pcbnew, "F_CrtYd", None), getattr(pcbnew, "B_CrtYd", None)):
            if layer_id is None:
                continue
            try:
                ct = fp.GetCourtyard(layer_id)
                if ct is not None and ct.OutlineCount() > 0:
                    courtyard_boxes.append(self._bbox_payload(ct.BBox()))
            except Exception:
                continue

        drawings = self._footprint_drawings(fp)
        fab_bbox = self._items_bbox_on_layers(drawings, {"F.Fab", "B.Fab"})
        silk_bbox = self._items_bbox_on_layers(drawings, {"F.SilkS", "B.SilkS"})
        text_bbox = self._text_bbox(fp)
        keepout_bbox = self._keepout_bbox(fp, drawings)

        return {
            "reference": fp.GetReference(),
            "value": fp.GetValue(),
            "footprint": fp.GetFPIDAsString(),
            "position": {"x": pos.x / 1_000_000, "y": pos.y / 1_000_000, "unit": "mm"},
            "rotation": fp.GetOrientation().AsDegrees(),
            "layer": layer,
            "raw_bbox": raw_bbox,
            "body_bbox": fab_bbox or pads_bbox or raw_bbox,
            "pads_bbox": pads_bbox,
            "courtyard_bbox": self._merge_bboxes(courtyard_boxes),
            "keepout_bbox": keepout_bbox,
            "fab_bbox": fab_bbox,
            "silk_bbox": silk_bbox,
            "text_bbox": text_bbox,
        }

    def _footprint_drawings(self, fp) -> List[Any]:
        for attr in ("GraphicalItems", "GetDrawings", "Drawings"):
            if hasattr(fp, attr):
                try:
                    return list(getattr(fp, attr)())
                except Exception:
                    continue
        return []

    def _items_bbox_on_layers(
        self, items: List[Any], layer_names: set[str]
    ) -> Optional[Dict[str, Any]]:
        boxes = []
        for item in items:
            try:
                layer_name = self.board.GetLayerName(item.GetLayer())
            except Exception:
                continue
            if layer_name in layer_names and hasattr(item, "GetBoundingBox"):
                boxes.append(self._bbox_payload(item.GetBoundingBox()))
        return self._merge_bboxes(boxes)

    def _text_bbox(self, fp) -> Optional[Dict[str, Any]]:
        boxes = []
        for field in ("reference", "value"):
            text = self._find_footprint_text(fp, field)
            if text is not None and hasattr(text, "GetBoundingBox"):
                boxes.append(self._bbox_payload(text.GetBoundingBox()))
        for item in self._footprint_drawings(fp):
            if hasattr(item, "GetText") and hasattr(item, "GetBoundingBox"):
                boxes.append(self._bbox_payload(item.GetBoundingBox()))
        return self._merge_bboxes(boxes)

    def _keepout_bbox(self, fp, drawings: List[Any]) -> Optional[Dict[str, Any]]:
        boxes = []
        for attr in ("Zones", "GetZones"):
            if hasattr(fp, attr):
                try:
                    for zone in getattr(fp, attr)():
                        if hasattr(zone, "GetBoundingBox"):
                            boxes.append(self._bbox_payload(zone.GetBoundingBox()))
                except Exception:
                    pass
        for item in drawings:
            try:
                layer_name = self.board.GetLayerName(item.GetLayer())
            except Exception:
                layer_name = ""
            if "keepout" in layer_name.lower() and hasattr(item, "GetBoundingBox"):
                boxes.append(self._bbox_payload(item.GetBoundingBox()))
            elif (
                hasattr(item, "IsKeepout") and item.IsKeepout() and hasattr(item, "GetBoundingBox")
            ):
                boxes.append(self._bbox_payload(item.GetBoundingBox()))
        return self._merge_bboxes(boxes)

    def _find_footprint_text(self, fp, field: str):
        key = (field or "reference").lower()
        if key in ("reference", "ref"):
            for attr in ("Reference", "GetReferenceField"):
                if hasattr(fp, attr):
                    try:
                        return getattr(fp, attr)()
                    except Exception:
                        pass
        if key in ("value", "val"):
            for attr in ("Value", "GetValueField"):
                if hasattr(fp, attr):
                    try:
                        return getattr(fp, attr)()
                    except Exception:
                        pass
        if hasattr(fp, "GetFieldByName"):
            try:
                return fp.GetFieldByName(field)
            except Exception:
                pass
        for item in self._footprint_drawings(fp):
            try:
                if hasattr(item, "GetText") and item.GetText() == field:
                    return item
            except Exception:
                continue
        return None

    @staticmethod
    def _bbox_overlap(
        a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]], margin: float = 0.0
    ) -> Optional[Dict[str, Any]]:
        if not a or not b:
            return None
        ax1 = a["min_x"] - margin
        ay1 = a["min_y"] - margin
        ax2 = a["max_x"] + margin
        ay2 = a["max_y"] + margin
        bx1 = b["min_x"] - margin
        by1 = b["min_y"] - margin
        bx2 = b["max_x"] + margin
        by2 = b["max_y"] + margin
        if ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1:
            x1 = max(ax1, bx1)
            y1 = max(ay1, by1)
            x2 = min(ax2, bx2)
            y2 = min(ay2, by2)
            return {
                "min_x": round(x1, 3),
                "min_y": round(y1, 3),
                "max_x": round(x2, 3),
                "max_y": round(y2, 3),
                "width": round(x2 - x1, 3),
                "height": round(y2 - y1, 3),
                "unit": "mm",
            }
        return None

    @staticmethod
    def _mst_airwires(pads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if len(pads) < 2:
            return []
        remaining = set(range(1, len(pads)))
        connected = {0}
        segments = []
        while remaining:
            best = None
            for i in connected:
                pi = pads[i]["position"]
                for j in remaining:
                    pj = pads[j]["position"]
                    dx = pj["x"] - pi["x"]
                    dy = pj["y"] - pi["y"]
                    length = math.hypot(dx, dy)
                    if best is None or length < best[0]:
                        best = (length, i, j, dx, dy)
            if best is None:
                break
            length, i, j, dx, dy = best
            remaining.remove(j)
            connected.add(j)
            segments.append(
                {
                    "from": {"reference": pads[i]["reference"], "pad": pads[i]["number"]},
                    "to": {"reference": pads[j]["reference"], "pad": pads[j]["number"]},
                    "start": pads[i]["position"],
                    "end": pads[j]["position"],
                    "dx_mm": round(dx, 3),
                    "dy_mm": round(dy, 3),
                    "length_mm": round(length, 3),
                    "angle_deg": round(math.degrees(math.atan2(dy, dx)), 2),
                }
            )
        return segments

    def _resolve_outline_bbox(self, override):
        """Return (x1, y1, x2, y2) in mm for the board outline, or None.

        Priority:
          1. caller-supplied override dict (x1,y1,x2,y2 + unit)
          2. board.GetBoardEdgesBoundingBox()
        """
        if override:
            scale = 1.0 if override.get("unit", "mm") == "mm" else 25.4
            return (
                override["x1"] * scale,
                override["y1"] * scale,
                override["x2"] * scale,
                override["y2"] * scale,
            )
        try:
            bb = self.board.GetBoardEdgesBoundingBox()
            return (
                self._nm_to_mm(bb.GetLeft()),
                self._nm_to_mm(bb.GetTop()),
                self._nm_to_mm(bb.GetRight()),
                self._nm_to_mm(bb.GetBottom()),
            )
        except Exception:
            return None

    def _footprint_courtyard_bbox(self, fp, override_pos):
        """Return courtyard bbox in mm, optionally relocated to a virtual position.

        Strategy:
          1. Use F.Courtyard or B.Courtyard polygon if present.
          2. Otherwise fall back to footprint.GetBoundingBox() (includes pads,
             excludes text by default).
          3. If override_pos is given, translate (and optionally rotate) the
             bbox to land at the virtual position — preserving the bbox's
             extents relative to the new anchor.
        """
        bbox_nm = None
        # Try the courtyard polygons first (front then back)
        for layer in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
            try:
                ct = fp.GetCourtyard(layer)
                if ct is not None and ct.OutlineCount() > 0:
                    box = ct.BBox()
                    bbox_nm = (box.GetLeft(), box.GetTop(), box.GetRight(), box.GetBottom())
                    break
            except Exception:
                continue
        if bbox_nm is None:
            try:
                box = fp.GetBoundingBox()
                bbox_nm = (box.GetLeft(), box.GetTop(), box.GetRight(), box.GetBottom())
            except Exception:
                return None

        x1, y1, x2, y2 = (self._nm_to_mm(v) for v in bbox_nm)

        if override_pos is None:
            return (x1, y1, x2, y2)

        # Re-anchor at the virtual position. We do this by translating the
        # bbox by (new_pos - current_pos). Rotation override is honoured by
        # rotating the *local* bbox (relative to the current anchor) by the
        # delta between the override rotation and the current rotation, then
        # re-anchoring. This is conservative for non-square parts: the AABB
        # of a rotated bbox is larger than the rotated polygon, but never
        # smaller — so an overlap report is still correct (never false-negative).
        cur = fp.GetPosition()
        cur_x_mm = self._nm_to_mm(cur.x)
        cur_y_mm = self._nm_to_mm(cur.y)
        new_x = float(override_pos[0])
        new_y = float(override_pos[1])
        new_rot = float(override_pos[2]) if len(override_pos) == 3 else None

        # Local bbox (relative to current anchor)
        lx1, ly1, lx2, ly2 = x1 - cur_x_mm, y1 - cur_y_mm, x2 - cur_x_mm, y2 - cur_y_mm

        if new_rot is not None:
            cur_rot = fp.GetOrientationDegrees()
            delta = new_rot - cur_rot
            if abs(delta) > 0.01:
                lx1, ly1, lx2, ly2 = self._rotate_aabb(lx1, ly1, lx2, ly2, delta)

        return (new_x + lx1, new_y + ly1, new_x + lx2, new_y + ly2)

    @staticmethod
    def _rotate_aabb(x1, y1, x2, y2, angle_deg):
        """Rotate the four AABB corners around origin and return the new
        axis-aligned bounding box. KiCad uses Y-down screen coords."""
        import math

        rad = math.radians(angle_deg)
        c, s = math.cos(rad), math.sin(rad)
        # Note: screen Y-down means rotation CCW visually requires the
        # standard math rotation with y negated; but for AABB extents this
        # is symmetric — we end up with the same xmin/ymin/xmax/ymax.
        corners = [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]
        rotated = [(x * c - y * s, x * s + y * c) for x, y in corners]
        xs = [p[0] for p in rotated]
        ys = [p[1] for p in rotated]
        return min(xs), min(ys), max(xs), max(ys)
