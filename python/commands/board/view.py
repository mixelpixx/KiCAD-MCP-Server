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
                    "title": self.board.GetTitleBlock().GetTitle(),
                    "activeLayer": self.board.GetActiveLayer()
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
            plot_opts.SetExcludeEdgeLayer(False)
            plot_opts.SetPlotFrameRef(False)
            plot_opts.SetPlotValue(True)
            plot_opts.SetPlotReference(True)
            
            # Plot to SVG first (for vector output)
            temp_svg = os.path.join(os.path.dirname(self.board.GetFileName()), "temp_view.svg")
            plotter.OpenPlotfile("temp_view", pcbnew.PLOT_FORMAT_SVG, "Temporary View")
            
            # Plot specified layers or all enabled layers
            if layers:
                for layer_name in layers:
                    layer_id = self.board.GetLayerID(layer_name)
                    if layer_id >= 0 and self.board.IsLayerEnabled(layer_id):
                        plotter.PlotLayer(layer_id)
            else:
                for layer_id in range(pcbnew.PCB_LAYER_ID_COUNT):
                    if self.board.IsLayerEnabled(layer_id):
                        plotter.PlotLayer(layer_id)
            
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
            pcbnew.LT_JUMPER: "jumper",
            pcbnew.LT_USER: "user"
        }
        return type_map.get(type_id, "unknown")
