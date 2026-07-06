"""Board origin commands: set/get the auxiliary (drill/place) and grid origins.

The aux origin is the datum consumed by export_drill's drillOrigin:"plot"
option and by plot exports' useAuxOrigin, but nothing in the backend could
set it headlessly. File-based (LoadBoard -> mutate -> SaveBoard), following
the hierarchical_place pattern: pcbnew is imported inside the handler so the
module loads without KiCad installed.
"""

import logging
import os
from typing import Any, Dict

logger = logging.getLogger("kicad_interface")

_UNIT_FACTORS = {
    "mm": 1000000,
    "mil": 25400,
    "inch": 25400000,
}

_VALID_TYPES = ("aux", "grid", "both")


class BoardOriginCommands:
    """File-based handlers for the board's aux/grid origins."""

    def set_board_origin(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Set the auxiliary (drill/place) origin and/or grid origin of a
        .kicad_pcb via BOARD_DESIGN_SETTINGS and save the board."""
        try:
            board_path = params.get("boardPath")
            if not board_path:
                return {"success": False, "message": "boardPath is required"}
            if not os.path.isfile(board_path):
                return {
                    "success": False,
                    "message": f"Board file not found: {board_path}",
                }

            origin_type = params.get("type", "aux")
            if origin_type not in _VALID_TYPES:
                return {
                    "success": False,
                    "message": f"type must be one of: {', '.join(_VALID_TYPES)}",
                }

            x = params.get("x")
            y = params.get("y")
            if x is None or y is None:
                return {"success": False, "message": "x and y are required"}
            try:
                x = float(x)
                y = float(y)
            except (TypeError, ValueError):
                return {"success": False, "message": "x and y must be numeric"}

            unit = params.get("unit", "mm")
            if unit not in _UNIT_FACTORS:
                return {
                    "success": False,
                    "message": f"unit must be one of: {', '.join(_UNIT_FACTORS)}",
                }
            factor = _UNIT_FACTORS[unit]

            try:
                import pcbnew
            except ImportError as e:
                return {"success": False, "message": f"pcbnew not available: {e}"}

            from utils.project_settings_guard import preserve_project_settings

            vec = pcbnew.VECTOR2I(int(round(x * factor)), int(round(y * factor)))
            board = pcbnew.LoadBoard(board_path)
            settings = board.GetDesignSettings()
            if origin_type in ("aux", "both"):
                settings.SetAuxOrigin(vec)
            if origin_type in ("grid", "both"):
                settings.SetGridOrigin(vec)
            with preserve_project_settings(board_path):
                pcbnew.SaveBoard(board_path, board)

            x_mm = vec.x / 1000000.0
            y_mm = vec.y / 1000000.0
            label = {"aux": "aux origin", "grid": "grid origin", "both": "aux and grid origins"}[
                origin_type
            ]
            logger.info(f"Set {label} to ({x_mm}, {y_mm}) mm in {board_path}")
            return {
                "success": True,
                "message": (
                    f"Set {label} to ({x_mm}, {y_mm}) mm in "
                    f"{os.path.basename(board_path)}. Note: if this board is "
                    f"open in the KiCad GUI, a later GUI save will overwrite "
                    f"this file-based edit."
                ),
                "origin": {"type": origin_type, "x": x_mm, "y": y_mm, "unit": "mm"},
            }
        except Exception as e:
            import traceback

            logger.error(f"set_board_origin failed: {e}")
            return {
                "success": False,
                "message": f"set_board_origin failed: {e}",
                "errorDetails": traceback.format_exc(),
            }

    def get_board_origin(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Read back the aux and grid origins of a .kicad_pcb in mm."""
        try:
            board_path = params.get("boardPath")
            if not board_path:
                return {"success": False, "message": "boardPath is required"}
            if not os.path.isfile(board_path):
                return {
                    "success": False,
                    "message": f"Board file not found: {board_path}",
                }

            try:
                import pcbnew
            except ImportError as e:
                return {"success": False, "message": f"pcbnew not available: {e}"}

            board = pcbnew.LoadBoard(board_path)
            settings = board.GetDesignSettings()
            aux = settings.GetAuxOrigin()
            grid = settings.GetGridOrigin()
            return {
                "success": True,
                "aux": {"x": aux.x / 1000000.0, "y": aux.y / 1000000.0},
                "grid": {"x": grid.x / 1000000.0, "y": grid.y / 1000000.0},
                "unit": "mm",
            }
        except Exception as e:
            import traceback

            logger.error(f"get_board_origin failed: {e}")
            return {
                "success": False,
                "message": f"get_board_origin failed: {e}",
                "errorDetails": traceback.format_exc(),
            }
