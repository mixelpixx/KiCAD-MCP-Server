"""
Board view command implementations for KiCAD interface
"""

import base64
import logging
import os
from typing import Any, Dict, List, Optional

import pcbnew

logger = logging.getLogger("kicad_interface")


class BoardViewCommands:
    """Handles board viewing operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

    def get_board_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get information about the current board"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # Get board dimensions
            board_box = self.board.GetBoardEdgesBoundingBox()
            width_nm = board_box.GetWidth()
            height_nm = board_box.GetHeight()

            # Convert to mm
            width_mm = width_nm / 1000000
            height_mm = height_nm / 1000000

            # Get layer information
            layers = []
            for layer_id in range(pcbnew.PCB_LAYER_ID_COUNT):
                if self.board.IsLayerEnabled(layer_id):
                    layers.append(
                        {
                            "name": self.board.GetLayerName(layer_id),
                            "type": self._get_layer_type_name(self.board.GetLayerType(layer_id)),
                            "id": layer_id,
                        }
                    )

            return {
                "success": True,
                "board": {
                    "filename": self.board.GetFileName(),
                    "size": {"width": width_mm, "height": height_mm, "unit": "mm"},
                    "layers": layers,
                    "title": self.board.GetTitleBlock().GetTitle(),
                    # Note: activeLayer removed - GetActiveLayer() doesn't exist in KiCAD 9.0
                    # Active layer is a UI concept not applicable to headless scripting
                },
            }

        except Exception as e:
            logger.error(f"Error getting board info: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get board information",
                "errorDetails": str(e),
            }

    def get_board_2d_view(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Render PCB to PNG/SVG via kicad-cli (no pcbnew/cffi dependency)."""
        import glob
        import subprocess
        import tempfile

        try:
            pcb_path = params.get("pcbPath")
            if not pcb_path:
                # fall back to loaded board path
                if self.board:
                    pcb_path = self.board.GetFileName()
                if not pcb_path:
                    return {"success": False, "message": "pcbPath required"}

            if not os.path.exists(pcb_path):
                return {"success": False, "message": f"PCB file not found: {pcb_path}"}

            width = params.get("width", 1600)
            height = params.get("height", 1200)
            fmt = params.get("format", "png")
            layers: List[str] = params.get("layers", [])

            with tempfile.TemporaryDirectory() as tmpdir:
                cmd = [
                    "kicad-cli",
                    "pcb",
                    "export",
                    "svg",
                    "--output",
                    tmpdir,
                    "--black-and-white",
                ]
                if layers:
                    cmd += ["--layers", ",".join(layers)]
                cmd.append(pcb_path)

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if result.returncode != 0:
                    return {
                        "success": False,
                        "message": f"kicad-cli failed: {result.stderr.strip()}",
                    }

                svg_files = glob.glob(os.path.join(tmpdir, "*.svg"))
                if not svg_files:
                    return {"success": False, "message": "kicad-cli produced no SVG output"}

                svg_path = svg_files[0]

                if fmt == "svg":
                    with open(svg_path, "r", encoding="utf-8") as f:
                        return {"success": True, "imageData": f.read(), "format": "svg"}

                # Convert SVG → PNG via cairosvg
                try:
                    from cairosvg import svg2png
                except ImportError:
                    with open(svg_path, "r", encoding="utf-8") as f:
                        return {
                            "success": True,
                            "imageData": f.read(),
                            "format": "svg",
                            "message": "cairosvg not installed — returning SVG. Install: pip install cairosvg",
                        }

                png_data = svg2png(url=svg_path, output_width=width, output_height=height)
                return {
                    "success": True,
                    "imageData": base64.b64encode(png_data).decode("utf-8"),
                    "format": "png",
                    "width": width,
                    "height": height,
                }

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except Exception as e:
            logger.error(f"Error getting board 2D view: {e}")
            return {"success": False, "message": str(e)}

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

    def get_board_extents(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get the bounding box extents of the board"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # Get unit preference (default to mm)
            unit = params.get("unit", "mm")
            scale = 1000000 if unit == "mm" else 25400000  # nm to mm or inch

            # Get board bounding box
            board_box = self.board.GetBoardEdgesBoundingBox()

            # Extract bounds in nanometers, then convert
            left = board_box.GetLeft() / scale
            top = board_box.GetTop() / scale
            right = board_box.GetRight() / scale
            bottom = board_box.GetBottom() / scale
            width = board_box.GetWidth() / scale
            height = board_box.GetHeight() / scale

            # Get center point
            center_x = board_box.GetCenter().x / scale
            center_y = board_box.GetCenter().y / scale

            return {
                "success": True,
                "extents": {
                    "left": left,
                    "top": top,
                    "right": right,
                    "bottom": bottom,
                    "width": width,
                    "height": height,
                    "center": {"x": center_x, "y": center_y},
                    "unit": unit,
                },
            }

        except Exception as e:
            logger.error(f"Error getting board extents: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get board extents",
                "errorDetails": str(e),
            }
