"""
Component-related command implementations for KiCAD interface
"""

import os
import pcbnew
import logging
import math
from typing import Dict, Any, Optional, List, Tuple
import base64

logger = logging.getLogger('kicad_interface')

class ComponentCommands:
    """Handles component-related KiCAD operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

    def place_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Place a component on the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
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
                    "errorDetails": "componentId and position are required"
                }

            # Create new module (footprint)
            module = pcbnew.FootprintLoad(self.board.GetLibraryPath(), component_id)
            if not module:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component: {component_id}"
                }

            # Set position
            scale = 1000000 if position["unit"] == "mm" else 25400000  # mm or inch to nm
            x_nm = int(position["x"] * scale)
            y_nm = int(position["y"] * scale)
            module.SetPosition(pcbnew.VECTOR2I(x_nm, y_nm))

            # Set reference if provided
            if reference:
                module.SetReference(reference)

            # Set value if provided
            if value:
                module.SetValue(value)

            # Set footprint if provided
            if footprint:
                module.SetFootprintName(footprint)

            # Set rotation
            module.SetOrientation(rotation * 10)  # KiCAD uses decidegrees

            # Set layer
            layer_id = self.board.GetLayerID(layer)
            if layer_id >= 0:
                module.SetLayer(layer_id)

            # Add to board
            self.board.Add(module)

            return {
                "success": True,
                "message": f"Placed component: {component_id}",
                "component": {
                    "reference": module.GetReference(),
                    "value": module.GetValue(),
                    "position": {
                        "x": position["x"],
                        "y": position["y"],
                        "unit": position["unit"]
                    },
                    "rotation": rotation,
                    "layer": layer
                }
            }

        except Exception as e:
            logger.error(f"Error placing component: {str(e)}")
            return {
                "success": False,
                "message": "Failed to place component",
                "errorDetails": str(e)
            }

    def move_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Move an existing component to a new position"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            reference = params.get("reference")
            position = params.get("position")
            rotation = params.get("rotation")

            if not reference or not position:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "reference and position are required"
                }

            # Find the component
            module = self.board.FindFootprintByReference(reference)
            if not module:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component: {reference}"
                }

            # Set new position
            scale = 1000000 if position["unit"] == "mm" else 25400000  # mm or inch to nm
            x_nm = int(position["x"] * scale)
            y_nm = int(position["y"] * scale)
            module.SetPosition(pcbnew.VECTOR2I(x_nm, y_nm))

            # Set new rotation if provided
            if rotation is not None:
                module.SetOrientation(rotation * 10)  # KiCAD uses decidegrees

            return {
                "success": True,
                "message": f"Moved component: {reference}",
                "component": {
                    "reference": reference,
                    "position": {
                        "x": position["x"],
                        "y": position["y"],
                        "unit": position["unit"]
                    },
                    "rotation": rotation if rotation is not None else module.GetOrientation() / 10
                }
            }

        except Exception as e:
            logger.error(f"Error moving component: {str(e)}")
            return {
                "success": False,
                "message": "Failed to move component",
                "errorDetails": str(e)
            }

    def rotate_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Rotate an existing component"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            reference = params.get("reference")
            angle = params.get("angle")

            if not reference or angle is None:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "reference and angle are required"
                }

            # Find the component
            module = self.board.FindFootprintByReference(reference)
            if not module:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component: {reference}"
                }

            # Set rotation
            module.SetOrientation(angle * 10)  # KiCAD uses decidegrees

            return {
                "success": True,
                "message": f"Rotated component: {reference}",
                "component": {
                    "reference": reference,
                    "rotation": angle
                }
            }

        except Exception as e:
            logger.error(f"Error rotating component: {str(e)}")
            return {
                "success": False,
                "message": "Failed to rotate component",
                "errorDetails": str(e)
            }

    def delete_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a component from the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            reference = params.get("reference")
            if not reference:
                return {
                    "success": False,
                    "message": "Missing reference",
                    "errorDetails": "reference parameter is required"
                }

            # Find the component
            module = self.board.FindFootprintByReference(reference)
            if not module:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component: {reference}"
                }

            # Remove from board
            self.board.Remove(module)

            return {
                "success": True,
                "message": f"Deleted component: {reference}"
            }

        except Exception as e:
            logger.error(f"Error deleting component: {str(e)}")
            return {
                "success": False,
                "message": "Failed to delete component",
                "errorDetails": str(e)
            }

    def edit_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Edit the properties of an existing component"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            reference = params.get("reference")
            new_reference = params.get("newReference")
            value = params.get("value")
            footprint = params.get("footprint")

            if not reference:
                return {
                    "success": False,
                    "message": "Missing reference",
                    "errorDetails": "reference parameter is required"
                }

            # Find the component
            module = self.board.FindFootprintByReference(reference)
            if not module:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component: {reference}"
                }

            # Update properties
            if new_reference:
                module.SetReference(new_reference)
            if value:
                module.SetValue(value)
            if footprint:
                module.SetFootprintName(footprint)

            return {
                "success": True,
                "message": f"Updated component: {reference}",
                "component": {
                    "reference": new_reference or reference,
                    "value": value or module.GetValue(),
                    "footprint": footprint or module.GetFootprintName()
                }
            }

        except Exception as e:
            logger.error(f"Error editing component: {str(e)}")
            return {
                "success": False,
                "message": "Failed to edit component",
                "errorDetails": str(e)
            }

    def get_component_properties(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get detailed properties of a component"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            reference = params.get("reference")
            if not reference:
                return {
                    "success": False,
                    "message": "Missing reference",
                    "errorDetails": "reference parameter is required"
                }

            # Find the component
            module = self.board.FindFootprintByReference(reference)
            if not module:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component: {reference}"
                }

            # Get position in mm
            pos = module.GetPosition()
            x_mm = pos.x / 1000000
            y_mm = pos.y / 1000000

            return {
                "success": True,
                "component": {
                    "reference": module.GetReference(),
                    "value": module.GetValue(),
                    "footprint": module.GetFootprintName(),
                    "position": {
                        "x": x_mm,
                        "y": y_mm,
                        "unit": "mm"
                    },
                    "rotation": module.GetOrientation() / 10,
                    "layer": self.board.GetLayerName(module.GetLayer()),
                    "attributes": {
                        "smd": module.GetAttributes() & pcbnew.FP_SMD,
                        "through_hole": module.GetAttributes() & pcbnew.FP_THROUGH_HOLE,
                        "virtual": module.GetAttributes() & pcbnew.FP_VIRTUAL
                    }
                }
            }

        except Exception as e:
            logger.error(f"Error getting component properties: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get component properties",
                "errorDetails": str(e)
            }

    def get_component_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a list of all components on the board"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            components = []
            for module in self.board.GetFootprints():
                pos = module.GetPosition()
                x_mm = pos.x / 1000000
                y_mm = pos.y / 1000000

                components.append({
                    "reference": module.GetReference(),
                    "value": module.GetValue(),
                    "footprint": module.GetFootprintName(),
                    "position": {
                        "x": x_mm,
                        "y": y_mm,
                        "unit": "mm"
                    },
                    "rotation": module.GetOrientation() / 10,
                    "layer": self.board.GetLayerName(module.GetLayer())
                })

            return {
                "success": True,
                "components": components
            }

        except Exception as e:
            logger.error(f"Error getting component list: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get component list",
                "errorDetails": str(e)
            }
            
    def place_component_array(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Place an array of components in a grid or circular pattern"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
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
                    "errorDetails": "componentId and count are required"
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
                        "errorDetails": "For grid pattern, startPosition, rows, columns, spacingX, and spacingY are required"
                    }
                    
                if rows * columns != count:
                    return {
                        "success": False,
                        "message": "Invalid grid parameters",
                        "errorDetails": "rows * columns must equal count"
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
                    layer
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
                        "errorDetails": "For circular pattern, center, radius, and angleStep are required"
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
                    layer
                )
                
            else:
                return {
                    "success": False,
                    "message": "Invalid pattern",
                    "errorDetails": "Pattern must be 'grid' or 'circular'"
                }

            return {
                "success": True,
                "message": f"Placed {count} components in {pattern} pattern",
                "components": placed_components
            }

        except Exception as e:
            logger.error(f"Error placing component array: {str(e)}")
            return {
                "success": False,
                "message": "Failed to place component array",
                "errorDetails": str(e)
            }
            
    def align_components(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Align multiple components along a line or distribute them evenly"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            references = params.get("references", [])
            alignment = params.get("alignment", "horizontal")  # horizontal, vertical, or edge
            distribution = params.get("distribution", "none")  # none, equal, or spacing
            spacing = params.get("spacing")
            
            if not references or len(references) < 2:
                return {
                    "success": False,
                    "message": "Missing references",
                    "errorDetails": "At least two component references are required"
                }
                
            # Find all referenced components
            components = []
            for ref in references:
                module = self.board.FindFootprintByReference(ref)
                if not module:
                    return {
                        "success": False,
                        "message": "Component not found",
                        "errorDetails": f"Could not find component: {ref}"
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
                        "errorDetails": "Edge parameter is required for edge alignment"
                    }
                self._align_components_to_edge(components, edge)
            else:
                return {
                    "success": False,
                    "message": "Invalid alignment option",
                    "errorDetails": "Alignment must be 'horizontal', 'vertical', or 'edge'"
                }

            # Prepare result data
            aligned_components = []
            for module in components:
                pos = module.GetPosition()
                aligned_components.append({
                    "reference": module.GetReference(),
                    "position": {
                        "x": pos.x / 1000000,
                        "y": pos.y / 1000000,
                        "unit": "mm"
                    },
                    "rotation": module.GetOrientation() / 10
                })

            return {
                "success": True,
                "message": f"Aligned {len(components)} components",
                "alignment": alignment,
                "distribution": distribution,
                "components": aligned_components
            }

        except Exception as e:
            logger.error(f"Error aligning components: {str(e)}")
            return {
                "success": False,
                "message": "Failed to align components",
                "errorDetails": str(e)
            }
            
    def duplicate_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Duplicate an existing component"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            reference = params.get("reference")
            new_reference = params.get("newReference")
            position = params.get("position")
            rotation = params.get("rotation")
            
            if not reference or not new_reference:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "reference and newReference are required"
                }
                
            # Find the source component
            source = self.board.FindFootprintByReference(reference)
            if not source:
                return {
                    "success": False,
                    "message": "Component not found",
                    "errorDetails": f"Could not find component: {reference}"
                }
                
            # Check if new reference already exists
            if self.board.FindFootprintByReference(new_reference):
                return {
                    "success": False,
                    "message": "Reference already exists",
                    "errorDetails": f"A component with reference {new_reference} already exists"
                }
                
            # Create new footprint with the same properties
            new_module = pcbnew.FOOTPRINT(self.board)
            new_module.SetFootprintName(source.GetFootprintName())
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
                scale = 1000000 if position.get("unit", "mm") == "mm" else 25400000
                x_nm = int(position["x"] * scale)
                y_nm = int(position["y"] * scale)
                new_module.SetPosition(pcbnew.VECTOR2I(x_nm, y_nm))
            else:
                # Offset by 5mm
                source_pos = source.GetPosition()
                new_module.SetPosition(pcbnew.VECTOR2I(source_pos.x + 5000000, source_pos.y))
                
            # Set rotation if provided, otherwise use same as original
            if rotation is not None:
                new_module.SetOrientation(rotation * 10)  # KiCAD uses decidegrees
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
                    "footprint": new_module.GetFootprintName(),
                    "position": {
                        "x": pos.x / 1000000,
                        "y": pos.y / 1000000,
                        "unit": "mm"
                    },
                    "rotation": new_module.GetOrientation() / 10,
                    "layer": self.board.GetLayerName(new_module.GetLayer())
                }
            }

        except Exception as e:
            logger.error(f"Error duplicating component: {str(e)}")
            return {
                "success": False,
                "message": "Failed to duplicate component",
                "errorDetails": str(e)
            }
            
    def _place_grid_array(self, component_id: str, start_position: Dict[str, Any], 
                       rows: int, columns: int, spacing_x: float, spacing_y: float,
                       reference_prefix: str, value: str, rotation: float, layer: str) -> List[Dict[str, Any]]:
        """Place components in a grid pattern and return the list of placed components"""
        placed = []
        
        # Convert spacing to nm
        unit = start_position.get("unit", "mm")
        scale = 1000000 if unit == "mm" else 25400000  # mm or inch to nm
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
                result = self.place_component({
                    "componentId": component_id,
                    "position": {"x": x, "y": y, "unit": unit},
                    "reference": component_reference,
                    "value": value,
                    "rotation": rotation,
                    "layer": layer
                })
                
                if result["success"]:
                    placed.append(result["component"])
                
        return placed
        
    def _place_circular_array(self, component_id: str, center: Dict[str, Any], 
                          radius: float, count: int, angle_start: float, 
                          angle_step: float, reference_prefix: str, 
                          value: str, rotation_offset: float, layer: str) -> List[Dict[str, Any]]:
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
            result = self.place_component({
                "componentId": component_id,
                "position": {"x": x, "y": y, "unit": unit},
                "reference": component_reference,
                "value": value,
                "rotation": component_rotation,
                "layer": layer
            })
            
            if result["success"]:
                placed.append(result["component"])
                
        return placed
        
    def _align_components_horizontally(self, components: List[pcbnew.FOOTPRINT], 
                                   distribution: str, spacing: Optional[float]) -> None:
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
                
    def _align_components_vertically(self, components: List[pcbnew.FOOTPRINT], 
                                 distribution: str, spacing: Optional[float]) -> None:
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
