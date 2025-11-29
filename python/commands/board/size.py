"""
Board size command implementations for KiCAD interface
"""

import pcbnew
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger('kicad_interface')

class BoardSizeCommands:
    """Handles board size operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

    def set_board_size(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Set the size of the PCB board by creating edge cuts outline"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            width = params.get("width")
            height = params.get("height")
            unit = params.get("unit", "mm")

            if width is None or height is None:
                return {
                    "success": False,
                    "message": "Missing dimensions",
                    "errorDetails": "Both width and height are required"
                }

            # Create board outline using BoardOutlineCommands
            # This properly creates edge cuts on Edge.Cuts layer
            from commands.board.outline import BoardOutlineCommands
            outline_commands = BoardOutlineCommands(self.board)

            # Create rectangular outline centered at origin
            result = outline_commands.add_board_outline({
                "shape": "rectangle",
                "centerX": width / 2,      # Center X
                "centerY": height / 2,     # Center Y
                "width": width,
                "height": height,
                "unit": unit
            })

            if result.get("success"):
                return {
                    "success": True,
                    "message": f"Created board outline: {width}x{height} {unit}",
                    "size": {
                        "width": width,
                        "height": height,
                        "unit": unit
                    }
                }
            else:
                return result

        except Exception as e:
            logger.error(f"Error setting board size: {str(e)}")
            return {
                "success": False,
                "message": "Failed to set board size",
                "errorDetails": str(e)
            }
