"""
Board view command implementations for KiCAD interface
"""

import os
import pcbnew
import logging
from typing import Dict, Any, Optional, List, Tuple
from PIL import Image
import io
import base64

logger = logging.getLogger('kicad_interface')

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
                    "errorDetails": "Load or create a board first"
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
                    layers.append({
                        "name": self.board.GetLayerName(layer_id),
                        "type": self._get_layer_type_name(self.board.GetLayerType(layer_id)),
                        "id": layer_id
                    })

            return {
                "success": True,
                "board": {
                    "filename": self.board.GetFileName(),
                    "size": {
                        "width": width_mm,
                        "height": height_mm,
                        "unit": "mm"
                    },
                    "layers": layers,
                    "title": self.board.GetTitleBlock().GetTitle()
                    # Note: activeLayer removed - GetActiveLayer() doesn't exist in KiCAD 9.0
                    # Active layer is a UI concept not applicable to headless scripting
                }
            }

        except Exception as e:
            logger.error(f"Error getting board info: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get board information",
                "errorDetails": str(e)
            }

    def get_board_2d_view(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a 2D image of the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            # Get parameters
            width = params.get("width", 800)
            height = params.get("height", 600)
            format = params.get("format", "png")
            layers = params.get("layers", [])

            # Create plot controller
            plotter = pcbnew.PLOT_CONTROLLER(self.board)
            
            # Set up plot options
            plot_opts = plotter.GetPlotOptions()
            plot_opts.SetOutputDirectory(os.path.dirname(self.board.GetFileName()))
            plot_opts.SetScale(1)
            plot_opts.SetMirror(False)
            # Note: SetExcludeEdgeLayer() removed in KiCAD 9.0 - default behavior includes all layers
            plot_opts.SetPlotFrameRef(False)
            plot_opts.SetPlotValue(True)
            plot_opts.SetPlotReference(True)
            
            # Plot to SVG first (for vector output)
            # Note: KiCAD 9.0 prepends the project name to the filename, so we use GetPlotFileName() to get the actual path
            plotter.OpenPlotfile("temp_view", pcbnew.PLOT_FORMAT_SVG, "Temporary View")

            # Plot specified layers or all enabled layers
            # Note: In KiCAD 9.0, SetLayer() must be called before PlotLayer()
            if layers:
                for layer_name in layers:
                    layer_id = self.board.GetLayerID(layer_name)
                    if layer_id >= 0 and self.board.IsLayerEnabled(layer_id):
                        plotter.SetLayer(layer_id)
                        plotter.PlotLayer()
            else:
                for layer_id in range(pcbnew.PCB_LAYER_ID_COUNT):
                    if self.board.IsLayerEnabled(layer_id):
                        plotter.SetLayer(layer_id)
                        plotter.PlotLayer()

            # Get the actual filename that was created (includes project name prefix)
            temp_svg = plotter.GetPlotFileName()

            plotter.ClosePlot()

            # Convert SVG to requested format
            if format == "svg":
                with open(temp_svg, 'r') as f:
                    svg_data = f.read()
                os.remove(temp_svg)
                return {
                    "success": True,
                    "imageData": svg_data,
                    "format": "svg"
                }
            else:
                # Use PIL to convert SVG to PNG/JPG
                from cairosvg import svg2png
                png_data = svg2png(url=temp_svg, output_width=width, output_height=height)
                os.remove(temp_svg)
                
                if format == "jpg":
                    # Convert PNG to JPG
                    img = Image.open(io.BytesIO(png_data))
                    jpg_buffer = io.BytesIO()
                    img.convert('RGB').save(jpg_buffer, format='JPEG')
                    jpg_data = jpg_buffer.getvalue()
                    return {
                        "success": True,
                        "imageData": base64.b64encode(jpg_data).decode('utf-8'),
                        "format": "jpg"
                    }
                else:
                    return {
                        "success": True,
                        "imageData": base64.b64encode(png_data).decode('utf-8'),
                        "format": "png"
                    }

        except Exception as e:
            logger.error(f"Error getting board 2D view: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get board 2D view",
                "errorDetails": str(e)
            }
    
    def _get_layer_type_name(self, type_id: int) -> str:
        """Convert KiCAD layer type constant to name"""
        type_map = {
            pcbnew.LT_SIGNAL: "signal",
            pcbnew.LT_POWER: "power",
            pcbnew.LT_MIXED: "mixed",
            pcbnew.LT_JUMPER: "jumper"
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
                    "errorDetails": "Load or create a board first"
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
                    "center": {
                        "x": center_x,
                        "y": center_y
                    },
                    "unit": unit
                }
            }

        except Exception as e:
            logger.error(f"Error getting board extents: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get board extents",
                "errorDetails": str(e)
            }
