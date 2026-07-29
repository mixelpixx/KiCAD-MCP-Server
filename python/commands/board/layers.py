"""
Board layer command implementations for KiCAD interface
"""

import logging
from typing import Any, Dict, Optional

import pcbnew

logger = logging.getLogger("kicad_interface")


class BoardLayerCommands:
    """Handles board layer operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

    # Copper layer IDs are NOT contiguous: F.Cu=0, B.Cu=2, In1.Cu=4, In2.Cu=6,
    # ... In30.Cu=62. They step by 2. Deriving an inner layer as
    # `In1_Cu + (n - 1)` therefore lands on odd IDs that are not copper layers
    # at all (#222) — n=4 gave layer 7. Step by 2 instead.
    _MAX_INNER_LAYERS = 30  # In1.Cu .. In30.Cu, i.e. MAX_CU_LAYERS (32) minus F/B

    # Copper layer types KiCad can actually store. "technical" and "user"
    # layers are a fixed set in KiCad and cannot be added; accepting them here
    # only ever retyped F.Cu (#222).
    _COPPER_TYPES = ("copper", "signal", "power", "mixed", "jumper")

    def add_layer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Enable and name a copper layer on the board.

        ``number`` is the **inner-layer ordinal**, 1-based: 1 = In1.Cu,
        2 = In2.Cu. It is not a KiCad layer ID — the response echoes the
        resolved ``canonicalName`` and ``id`` so the caller can see exactly
        which layer was touched rather than having to know the convention.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            name = params.get("name")
            layer_type = params.get("type")
            position = params.get("position")
            number = params.get("number")

            if not name or not layer_type or not position:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "name, type, and position are required",
                }

            if str(layer_type).lower() not in self._COPPER_TYPES:
                return {
                    "success": False,
                    "message": f"Unsupported layer type: {layer_type}",
                    "errorDetails": (
                        "add_layer manages copper layers only. KiCad's technical and "
                        "user layers (silkscreen, mask, courtyard, Dwgs.User, ...) are a "
                        "fixed set that always exists and cannot be added. Use "
                        f"set_active_layer or get_layer_list to work with them. "
                        f"Valid types: {', '.join(self._COPPER_TYPES)}"
                    ),
                }

            # Resolve the target copper layer.
            if position == "inner":
                if number is None:
                    return {
                        "success": False,
                        "message": "Missing layer number",
                        "errorDetails": (
                            "number is required for inner layers. It is the inner-layer "
                            "ordinal: 1 = In1.Cu, 2 = In2.Cu, ..."
                        ),
                    }
                try:
                    ordinal = int(number)
                except (TypeError, ValueError):
                    return {
                        "success": False,
                        "message": f"Invalid layer number: {number!r}",
                        "errorDetails": "number must be an integer inner-layer ordinal",
                    }
                if not 1 <= ordinal <= self._MAX_INNER_LAYERS:
                    return {
                        "success": False,
                        "message": f"Inner layer number out of range: {ordinal}",
                        "errorDetails": (
                            f"number is the inner-layer ordinal and must be 1.."
                            f"{self._MAX_INNER_LAYERS} (1 = In1.Cu). KiCad supports at most "
                            f"{self._MAX_INNER_LAYERS + 2} copper layers."
                        ),
                    }
                layer_id = pcbnew.In1_Cu + (ordinal - 1) * 2

                # SetCopperLayerCount enables the inner layers AND gives them
                # their canonical names — no manual naming needed for the
                # default case.
                needed_count = 2 + ordinal  # F.Cu + B.Cu + inner layers
                if needed_count > self.board.GetCopperLayerCount():
                    self.board.SetCopperLayerCount(needed_count)
            elif position == "top":
                layer_id = pcbnew.F_Cu
            elif position == "bottom":
                layer_id = pcbnew.B_Cu
            else:
                return {
                    "success": False,
                    "message": "Invalid layer position",
                    "errorDetails": "position must be 'top', 'bottom', or 'inner'",
                }

            canonical_name = self.board.GetStandardLayerName(layer_id)

            # A custom name is stored alongside the canonical one — KiCad writes
            # `(4 "In1.Cu" signal "PWR")`. Only set it when it actually differs,
            # so the common case leaves the file byte-identical to KiCad's own.
            if name != canonical_name:
                self.board.SetLayerName(layer_id, name)
            self.board.SetLayerType(layer_id, self._get_layer_type(layer_type))

            return {
                "success": True,
                "message": f"Enabled layer {canonical_name} (id {layer_id}) as '{name}'",
                "layer": {
                    "name": name,
                    "canonicalName": canonical_name,
                    "id": layer_id,
                    "type": layer_type,
                    "position": position,
                    "number": number,
                },
                "copperLayerCount": self.board.GetCopperLayerCount(),
            }

        except Exception as e:
            logger.error(f"Error adding layer: {str(e)}")
            return {"success": False, "message": "Failed to add layer", "errorDetails": str(e)}

    def set_active_layer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Set the active layer for PCB operations"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            layer = params.get("layer")
            if not layer:
                return {
                    "success": False,
                    "message": "No layer specified",
                    "errorDetails": "layer parameter is required",
                }

            # Find layer ID by name
            layer_id = self.board.GetLayerID(layer)
            if layer_id < 0:
                return {
                    "success": False,
                    "message": "Layer not found",
                    "errorDetails": f"Layer '{layer}' does not exist",
                }

            # Set active layer
            self.board.SetActiveLayer(layer_id)

            return {
                "success": True,
                "message": f"Set active layer to: {layer}",
                "layer": {"name": layer, "id": layer_id},
            }

        except Exception as e:
            logger.error(f"Error setting active layer: {str(e)}")
            return {
                "success": False,
                "message": "Failed to set active layer",
                "errorDetails": str(e),
            }

    def get_layer_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a list of all layers in the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            layers = []
            for layer_id in range(pcbnew.PCB_LAYER_ID_COUNT):
                if self.board.IsLayerEnabled(layer_id):
                    layers.append(
                        {
                            "name": self.board.GetLayerName(layer_id),
                            "type": self._get_layer_type_name(self.board.GetLayerType(layer_id)),
                            "id": layer_id,
                            # Note: isActive removed - GetActiveLayer() doesn't exist in KiCAD 9.0
                            # Active layer is a UI concept not applicable to headless scripting
                        }
                    )

            return {"success": True, "layers": layers}

        except Exception as e:
            logger.error(f"Error getting layer list: {str(e)}")
            return {"success": False, "message": "Failed to get layer list", "errorDetails": str(e)}

    def _get_layer_type(self, type_name: str) -> int:
        """Convert layer type name to KiCAD layer type constant"""
        type_map = {
            "copper": pcbnew.LT_SIGNAL,
            "technical": pcbnew.LT_SIGNAL,
            "user": pcbnew.LT_SIGNAL,  # LT_USER removed in KiCAD 9.0, use LT_SIGNAL instead
            "signal": pcbnew.LT_SIGNAL,
        }
        return type_map.get(type_name.lower(), pcbnew.LT_SIGNAL)

    def _get_layer_type_name(self, type_id: int) -> str:
        """Convert KiCAD layer type constant to name"""
        type_map = {
            pcbnew.LT_SIGNAL: "signal",
            pcbnew.LT_POWER: "power",
            pcbnew.LT_MIXED: "mixed",
            pcbnew.LT_JUMPER: "jumper",
        }
        # Note: LT_USER was removed in KiCAD 9.0
        return type_map.get(type_id, "unknown")
