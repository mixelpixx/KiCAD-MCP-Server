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
        """Set the size of the PCB board"""
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

            # Convert to internal units (nanometers)
            scale = 1000000 if unit == "mm" else 25400000  # mm or inch to nm
            width_nm = int(width * scale)
            height_nm = int(height * scale)

            # Set board size
            board_box = self.board.GetBoardEdgesBoundingBox()
            board_box.SetSize(pcbnew.VECTOR2I(width_nm, height_nm))
            
            # Update board outline
            self.board.SetBoardEdgesBoundingBox(board_box)

            return {
                "success": True,
                "message": f"Set board size to {width}x{height} {unit}",
                "size": {
                    "width": width,
                    "height": height,
                    "unit": unit
                }
            }

        except Exception as e:
            logger.error(f"Error setting board size: {str(e)}")
            return {
                "success": False,
                "message": "Failed to set board size",
                "errorDetails": str(e)
            }
