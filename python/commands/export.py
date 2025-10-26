"""
Export command implementations for KiCAD interface
"""

import os
import pcbnew
import logging
from typing import Dict, Any, Optional, List, Tuple
import base64

logger = logging.getLogger('kicad_interface')

class ExportCommands:
    """Handles export-related KiCAD operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

    def export_gerber(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export Gerber files"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            output_dir = params.get("outputDir")
            layers = params.get("layers", [])
            use_protel_extensions = params.get("useProtelExtensions", False)
            generate_drill_files = params.get("generateDrillFiles", True)
            generate_map_file = params.get("generateMapFile", False)
            use_aux_origin = params.get("useAuxOrigin", False)

            if not output_dir:
                return {
                    "success": False,
                    "message": "Missing output directory",
                    "errorDetails": "outputDir parameter is required"
                }

            # Create output directory if it doesn't exist
            output_dir = os.path.abspath(os.path.expanduser(output_dir))
            os.makedirs(output_dir, exist_ok=True)

            # Create plot controller
            plotter = pcbnew.PLOT_CONTROLLER(self.board)
            
            # Set up plot options
            plot_opts = plotter.GetPlotOptions()
            plot_opts.SetOutputDirectory(output_dir)
            plot_opts.SetFormat(pcbnew.PLOT_FORMAT_GERBER)
            plot_opts.SetUseGerberProtelExtensions(use_protel_extensions)
            plot_opts.SetUseAuxOrigin(use_aux_origin)
            plot_opts.SetCreateGerberJobFile(generate_map_file)
            plot_opts.SetSubtractMaskFromSilk(True)

            # Plot specified layers or all copper layers
            plotted_layers = []
            if layers:
                for layer_name in layers:
                    layer_id = self.board.GetLayerID(layer_name)
                    if layer_id >= 0:
                        plotter.PlotLayer(layer_id)
                        plotted_layers.append(layer_name)
            else:
                for layer_id in range(pcbnew.PCB_LAYER_ID_COUNT):
                    if self.board.IsLayerEnabled(layer_id):
                        layer_name = self.board.GetLayerName(layer_id)
                        plotter.PlotLayer(layer_id)
                        plotted_layers.append(layer_name)

            # Generate drill files if requested
            drill_files = []
            if generate_drill_files:
                drill_writer = pcbnew.EXCELLON_WRITER(self.board)
                drill_writer.SetFormat(True)
                drill_writer.SetMapFileFormat(pcbnew.PLOT_FORMAT_GERBER)
                
                merge_npth = False  # Keep plated/non-plated holes separate
                drill_writer.SetOptions(merge_npth)
                
                drill_writer.CreateDrillandMapFilesSet(output_dir, True, generate_map_file)
                
                # Get list of generated drill files
                for file in os.listdir(output_dir):
                    if file.endswith(".drl") or file.endswith(".cnc"):
                        drill_files.append(file)

            return {
                "success": True,
                "message": "Exported Gerber files",
                "files": {
                    "gerber": plotted_layers,
                    "drill": drill_files,
                    "map": ["job.gbrjob"] if generate_map_file else []
                },
                "outputDir": output_dir
            }

        except Exception as e:
            logger.error(f"Error exporting Gerber files: {str(e)}")
            return {
                "success": False,
                "message": "Failed to export Gerber files",
                "errorDetails": str(e)
            }

    def export_pdf(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export PDF files"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            output_path = params.get("outputPath")
            layers = params.get("layers", [])
            black_and_white = params.get("blackAndWhite", False)
            frame_reference = params.get("frameReference", True)
            page_size = params.get("pageSize", "A4")

            if not output_path:
                return {
                    "success": False,
                    "message": "Missing output path",
                    "errorDetails": "outputPath parameter is required"
                }

            # Create output directory if it doesn't exist
            output_path = os.path.abspath(os.path.expanduser(output_path))
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Create plot controller
            plotter = pcbnew.PLOT_CONTROLLER(self.board)
            
            # Set up plot options
            plot_opts = plotter.GetPlotOptions()
            plot_opts.SetOutputDirectory(os.path.dirname(output_path))
            plot_opts.SetFormat(pcbnew.PLOT_FORMAT_PDF)
            plot_opts.SetPlotFrameRef(frame_reference)
            plot_opts.SetPlotValue(True)
            plot_opts.SetPlotReference(True)
            plot_opts.SetMonochrome(black_and_white)

            # Set page size
            page_sizes = {
                "A4": (297, 210),
                "A3": (420, 297),
                "A2": (594, 420),
                "A1": (841, 594),
                "A0": (1189, 841),
                "Letter": (279.4, 215.9),
                "Legal": (355.6, 215.9),
                "Tabloid": (431.8, 279.4)
            }
            if page_size in page_sizes:
                height, width = page_sizes[page_size]
                plot_opts.SetPageSettings((width, height))

            # Plot specified layers or all enabled layers
            plotted_layers = []
            if layers:
                for layer_name in layers:
                    layer_id = self.board.GetLayerID(layer_name)
                    if layer_id >= 0:
                        plotter.PlotLayer(layer_id)
                        plotted_layers.append(layer_name)
            else:
                for layer_id in range(pcbnew.PCB_LAYER_ID_COUNT):
                    if self.board.IsLayerEnabled(layer_id):
                        layer_name = self.board.GetLayerName(layer_id)
                        plotter.PlotLayer(layer_id)
                        plotted_layers.append(layer_name)

            return {
                "success": True,
                "message": "Exported PDF file",
                "file": {
                    "path": output_path,
                    "layers": plotted_layers,
                    "pageSize": page_size
                }
            }

        except Exception as e:
            logger.error(f"Error exporting PDF file: {str(e)}")
            return {
                "success": False,
                "message": "Failed to export PDF file",
                "errorDetails": str(e)
            }

    def export_svg(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export SVG files"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            output_path = params.get("outputPath")
            layers = params.get("layers", [])
            black_and_white = params.get("blackAndWhite", False)
            include_components = params.get("includeComponents", True)

            if not output_path:
                return {
                    "success": False,
                    "message": "Missing output path",
                    "errorDetails": "outputPath parameter is required"
                }

            # Create output directory if it doesn't exist
            output_path = os.path.abspath(os.path.expanduser(output_path))
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Create plot controller
            plotter = pcbnew.PLOT_CONTROLLER(self.board)
            
            # Set up plot options
            plot_opts = plotter.GetPlotOptions()
            plot_opts.SetOutputDirectory(os.path.dirname(output_path))
            plot_opts.SetFormat(pcbnew.PLOT_FORMAT_SVG)
            plot_opts.SetPlotValue(include_components)
            plot_opts.SetPlotReference(include_components)
            plot_opts.SetMonochrome(black_and_white)

            # Plot specified layers or all enabled layers
            plotted_layers = []
            if layers:
                for layer_name in layers:
                    layer_id = self.board.GetLayerID(layer_name)
                    if layer_id >= 0:
                        plotter.PlotLayer(layer_id)
                        plotted_layers.append(layer_name)
            else:
                for layer_id in range(pcbnew.PCB_LAYER_ID_COUNT):
                    if self.board.IsLayerEnabled(layer_id):
                        layer_name = self.board.GetLayerName(layer_id)
                        plotter.PlotLayer(layer_id)
                        plotted_layers.append(layer_name)

            return {
                "success": True,
                "message": "Exported SVG file",
                "file": {
                    "path": output_path,
                    "layers": plotted_layers
                }
            }

        except Exception as e:
            logger.error(f"Error exporting SVG file: {str(e)}")
            return {
                "success": False,
                "message": "Failed to export SVG file",
                "errorDetails": str(e)
            }

    def export_3d(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export 3D model files"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            output_path = params.get("outputPath")
            format = params.get("format", "STEP")
            include_components = params.get("includeComponents", True)
            include_copper = params.get("includeCopper", True)
            include_solder_mask = params.get("includeSolderMask", True)
            include_silkscreen = params.get("includeSilkscreen", True)

            if not output_path:
                return {
                    "success": False,
                    "message": "Missing output path",
                    "errorDetails": "outputPath parameter is required"
                }

            # Create output directory if it doesn't exist
            output_path = os.path.abspath(os.path.expanduser(output_path))
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Get 3D viewer
            viewer = self.board.Get3DViewer()
            if not viewer:
                return {
                    "success": False,
                    "message": "3D viewer not available",
                    "errorDetails": "Could not initialize 3D viewer"
                }

            # Set export options
            viewer.SetCopperLayersOn(include_copper)
            viewer.SetSolderMaskLayersOn(include_solder_mask)
            viewer.SetSilkScreenLayersOn(include_silkscreen)
            viewer.Set3DModelsOn(include_components)

            # Export based on format
            if format == "STEP":
                viewer.ExportSTEPFile(output_path)
            elif format == "VRML":
                viewer.ExportVRMLFile(output_path)
            else:
                return {
                    "success": False,
                    "message": "Unsupported format",
                    "errorDetails": f"Format {format} is not supported"
                }

            return {
                "success": True,
                "message": f"Exported {format} file",
                "file": {
                    "path": output_path,
                    "format": format
                }
            }

        except Exception as e:
            logger.error(f"Error exporting 3D model: {str(e)}")
            return {
                "success": False,
                "message": "Failed to export 3D model",
                "errorDetails": str(e)
            }

    def export_bom(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export Bill of Materials"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            output_path = params.get("outputPath")
            format = params.get("format", "CSV")
            group_by_value = params.get("groupByValue", True)
            include_attributes = params.get("includeAttributes", [])

            if not output_path:
                return {
                    "success": False,
                    "message": "Missing output path",
                    "errorDetails": "outputPath parameter is required"
                }

            # Create output directory if it doesn't exist
            output_path = os.path.abspath(os.path.expanduser(output_path))
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Get all components
            components = []
            for module in self.board.GetFootprints():
                component = {
                    "reference": module.GetReference(),
                    "value": module.GetValue(),
                    "footprint": module.GetFootprintName(),
                    "layer": self.board.GetLayerName(module.GetLayer())
                }

                # Add requested attributes
                for attr in include_attributes:
                    if hasattr(module, f"Get{attr}"):
                        component[attr] = getattr(module, f"Get{attr}")()

                components.append(component)

            # Group by value if requested
            if group_by_value:
                grouped = {}
                for comp in components:
                    key = f"{comp['value']}_{comp['footprint']}"
                    if key not in grouped:
                        grouped[key] = {
                            "value": comp["value"],
                            "footprint": comp["footprint"],
                            "quantity": 1,
                            "references": [comp["reference"]]
                        }
                    else:
                        grouped[key]["quantity"] += 1
                        grouped[key]["references"].append(comp["reference"])
                components = list(grouped.values())

            # Export based on format
            if format == "CSV":
                self._export_bom_csv(output_path, components)
            elif format == "XML":
                self._export_bom_xml(output_path, components)
            elif format == "HTML":
                self._export_bom_html(output_path, components)
            elif format == "JSON":
                self._export_bom_json(output_path, components)
            else:
                return {
                    "success": False,
                    "message": "Unsupported format",
                    "errorDetails": f"Format {format} is not supported"
                }

            return {
                "success": True,
                "message": f"Exported BOM to {format}",
                "file": {
                    "path": output_path,
                    "format": format,
                    "componentCount": len(components)
                }
            }

        except Exception as e:
            logger.error(f"Error exporting BOM: {str(e)}")
            return {
                "success": False,
                "message": "Failed to export BOM",
                "errorDetails": str(e)
            }

    def _export_bom_csv(self, path: str, components: List[Dict[str, Any]]) -> None:
        """Export BOM to CSV format"""
        import csv
        with open(path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=components[0].keys())
            writer.writeheader()
            writer.writerows(components)

    def _export_bom_xml(self, path: str, components: List[Dict[str, Any]]) -> None:
        """Export BOM to XML format"""
        import xml.etree.ElementTree as ET
        root = ET.Element("bom")
        for comp in components:
            comp_elem = ET.SubElement(root, "component")
            for key, value in comp.items():
                elem = ET.SubElement(comp_elem, key)
                elem.text = str(value)
        tree = ET.ElementTree(root)
        tree.write(path, encoding='utf-8', xml_declaration=True)

    def _export_bom_html(self, path: str, components: List[Dict[str, Any]]) -> None:
        """Export BOM to HTML format"""
        html = ["<html><head><title>Bill of Materials</title></head><body>"]
        html.append("<table border='1'><tr>")
        # Headers
        for key in components[0].keys():
            html.append(f"<th>{key}</th>")
        html.append("</tr>")
        # Data
        for comp in components:
            html.append("<tr>")
            for value in comp.values():
                html.append(f"<td>{value}</td>")
            html.append("</tr>")
        html.append("</table></body></html>")
        with open(path, 'w') as f:
            f.write("\n".join(html))

    def _export_bom_json(self, path: str, components: List[Dict[str, Any]]) -> None:
        """Export BOM to JSON format"""
        import json
        with open(path, 'w') as f:
            json.dump({"components": components}, f, indent=2)
