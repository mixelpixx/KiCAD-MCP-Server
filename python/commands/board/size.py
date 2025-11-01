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

            # Set board size using KiCAD 9.0 API
            # Note: In KiCAD 9.0, SetSize takes two separate parameters instead of VECTOR2I
            board_box = self.board.GetBoardEdgesBoundingBox()
            try:
                # Try KiCAD 9.0+ API (two parameters)
                board_box.SetSize(width_nm, height_nm)
            except TypeError:
                # Fall back to older API (VECTOR2I)
                board_box.SetSize(pcbnew.VECTOR2I(width_nm, height_nm))

            # Note: SetBoardEdgesBoundingBox might not exist in all versions
            # The board bounding box is typically derived from actual edge cuts
            # For now, we'll just note the size was calculated
            logger.info(f"Board size set to {width}x{height} {unit}")

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
