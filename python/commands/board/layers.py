"""
Board layer command implementations for KiCAD interface
"""

import pcbnew
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger('kicad_interface')

class BoardLayerCommands:
    """Handles board layer operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

    def add_layer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new layer to the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            name = params.get("name")
            layer_type = params.get("type")
            position = params.get("position")
            number = params.get("number")

            if not name or not layer_type or not position:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "name, type, and position are required"
                }

            # Get layer stack
            layer_stack = self.board.GetLayerStack()

            # Determine layer ID based on position and number
            layer_id = None
            if position == "inner":
                if number is None:
                    return {
                        "success": False,
                        "message": "Missing layer number",
                        "errorDetails": "number is required for inner layers"
                    }
                layer_id = pcbnew.In1_Cu + (number - 1)
            elif position == "top":
                layer_id = pcbnew.F_Cu
            elif position == "bottom":
                layer_id = pcbnew.B_Cu

            if layer_id is None:
                return {
                    "success": False,
                    "message": "Invalid layer position",
                    "errorDetails": "position must be 'top', 'bottom', or 'inner'"
                }

            # Set layer properties
            layer_stack.SetLayerName(layer_id, name)
            layer_stack.SetLayerType(layer_id, self._get_layer_type(layer_type))
            
            # Enable the layer
            self.board.SetLayerEnabled(layer_id, True)

            return {
                "success": True,
                "message": f"Added layer: {name}",
                "layer": {
                    "name": name,
                    "type": layer_type,
                    "position": position,
                    "number": number
                }
            }

        except Exception as e:
            logger.error(f"Error adding layer: {str(e)}")
            return {
                "success": False,
                "message": "Failed to add layer",
                "errorDetails": str(e)
            }

    def set_active_layer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Set the active layer for PCB operations"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            layer = params.get("layer")
            if not layer:
                return {
                    "success": False,
                    "message": "No layer specified",
                    "errorDetails": "layer parameter is required"
                }

            # Find layer ID by name
            layer_id = self.board.GetLayerID(layer)
            if layer_id < 0:
                return {
                    "success": False,
                    "message": "Layer not found",
                    "errorDetails": f"Layer '{layer}' does not exist"
                }

            # Set active layer
            self.board.SetActiveLayer(layer_id)

            return {
                "success": True,
                "message": f"Set active layer to: {layer}",
                "layer": {
                    "name": layer,
                    "id": layer_id
                }
            }

        except Exception as e:
            logger.error(f"Error setting active layer: {str(e)}")
            return {
                "success": False,
                "message": "Failed to set active layer",
                "errorDetails": str(e)
            }

    def get_layer_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a list of all layers in the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            layers = []
            for layer_id in range(pcbnew.PCB_LAYER_ID_COUNT):
                if self.board.IsLayerEnabled(layer_id):
                    layers.append({
                        "name": self.board.GetLayerName(layer_id),
                        "type": self._get_layer_type_name(self.board.GetLayerType(layer_id)),
                        "id": layer_id,
                        "isActive": layer_id == self.board.GetActiveLayer()
                    })

            return {
                "success": True,
                "layers": layers
            }

        except Exception as e:
            logger.error(f"Error getting layer list: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get layer list",
                "errorDetails": str(e)
            }
    
    def _get_layer_type(self, type_name: str) -> int:
        """Convert layer type name to KiCAD layer type constant"""
        type_map = {
            "copper": pcbnew.LT_SIGNAL,
            "technical": pcbnew.LT_SIGNAL,
            "user": pcbnew.LT_USER,
            "signal": pcbnew.LT_SIGNAL
        }
        return type_map.get(type_name.lower(), pcbnew.LT_SIGNAL)

    def _get_layer_type_name(self, type_id: int) -> str:
        """Convert KiCAD layer type constant to name"""
        type_map = {
            pcbnew.LT_SIGNAL: "signal",
            pcbnew.LT_POWER: "power",
            pcbnew.LT_MIXED: "mixed",
            pcbnew.LT_JUMPER: "jumper",
            pcbnew.LT_USER: "user"
        }
        return type_map.get(type_id, "unknown")
