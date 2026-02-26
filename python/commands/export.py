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
                        plotter.SetLayer(layer_id)
                        plotter.PlotLayer()
                        plotted_layers.append(layer_name)
            else:
                for layer_id in range(pcbnew.PCB_LAYER_ID_COUNT):
                    if self.board.IsLayerEnabled(layer_id):
                        layer_name = self.board.GetLayerName(layer_id)
                        plotter.SetLayer(layer_id)
                        plotter.PlotLayer()
                        plotted_layers.append(layer_name)

            # Generate drill files if requested
            drill_files = []
            if generate_drill_files:
                # KiCAD 9.0: Use kicad-cli for more reliable drill file generation
                # The Python API's EXCELLON_WRITER.SetOptions() signature changed
                board_file = self.board.GetFileName()
                kicad_cli = self._find_kicad_cli()

                if kicad_cli and board_file and os.path.exists(board_file):
                    import subprocess
                    # Generate drill files using kicad-cli
                    cmd = [
                        kicad_cli,
                        'pcb', 'export', 'drill',
                        '--output', output_dir,
                        '--format', 'excellon',
                        '--drill-origin', 'absolute',
                        '--excellon-separate-th',  # Separate plated/non-plated
                        board_file
                    ]

                    try:
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                        if result.returncode == 0:
                            # Get list of generated drill files
                            for file in os.listdir(output_dir):
                                if file.endswith((".drl", ".cnc")):
                                    drill_files.append(file)
                        else:
                            logger.warning(f"Drill file generation failed: {result.stderr}")
                    except Exception as drill_error:
                        logger.warning(f"Could not generate drill files: {str(drill_error)}")
                else:
                    logger.warning("kicad-cli not available for drill file generation")

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
            plot_opts.SetBlackAndWhite(black_and_white)

            # KiCAD 9.0 page size handling:
            # - SetPageSettings() was removed in KiCAD 9.0
            # - SetA4Output(bool) forces A4 page size when True
            # - For other sizes, KiCAD auto-scales to fit the board
            # - SetAutoScale(True) enables automatic scaling to fit page
            if page_size == "A4":
                plot_opts.SetA4Output(True)
            else:
                # For non-A4 sizes, disable A4 forcing and use auto-scale
                plot_opts.SetA4Output(False)
                plot_opts.SetAutoScale(True)
                # Note: KiCAD 9.0 doesn't support explicit page size selection
                # for formats other than A4. The PDF will auto-scale to fit.
                logger.warning(f"Page size '{page_size}' requested, but KiCAD 9.0 only supports A4 explicitly. Using auto-scale instead.")

            # Open plot for writing
            # Note: For PDF, all layers are combined into a single file
            # KiCAD prepends the board filename to the plot file name
            base_name = os.path.basename(output_path).replace('.pdf', '')
            plotter.OpenPlotfile(base_name, pcbnew.PLOT_FORMAT_PDF, '')

            # Plot specified layers or all enabled layers
            plotted_layers = []
            if layers:
                for layer_name in layers:
                    layer_id = self.board.GetLayerID(layer_name)
                    if layer_id >= 0:
                        plotter.SetLayer(layer_id)
                        plotter.PlotLayer()
                        plotted_layers.append(layer_name)
            else:
                for layer_id in range(pcbnew.PCB_LAYER_ID_COUNT):
                    if self.board.IsLayerEnabled(layer_id):
                        layer_name = self.board.GetLayerName(layer_id)
                        plotter.SetLayer(layer_id)
                        plotter.PlotLayer()
                        plotted_layers.append(layer_name)

            # Close the plot file to finalize the PDF
            plotter.ClosePlot()

            # KiCAD automatically prepends the board name to the output file
            # Get the actual output filename that was created
            board_name = os.path.splitext(os.path.basename(self.board.GetFileName()))[0]
            actual_filename = f"{board_name}-{base_name}.pdf"
            actual_output_path = os.path.join(os.path.dirname(output_path), actual_filename)

            return {
                "success": True,
                "message": "Exported PDF file",
                "file": {
                    "path": actual_output_path,
                    "requestedPath": output_path,
                    "layers": plotted_layers,
                    "pageSize": page_size if page_size == "A4" else "auto-scaled"
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
            plot_opts.SetBlackAndWhite(black_and_white)

            # Open the plot file (required before PlotLayer calls)
            plotter.OpenPlotfile(
                os.path.splitext(os.path.basename(output_path))[0],
                pcbnew.PLOT_FORMAT_SVG,
                "SVG Export"
            )

            # Plot specified layers or all enabled layers
            plotted_layers = []
            if layers:
                for layer_name in layers:
                    layer_id = self.board.GetLayerID(layer_name)
                    if layer_id >= 0:
                        plotter.SetLayer(layer_id)
                        plotter.PlotLayer()
                        plotted_layers.append(layer_name)
            else:
                for layer_id in range(pcbnew.PCB_LAYER_ID_COUNT):
                    if self.board.IsLayerEnabled(layer_id):
                        layer_name = self.board.GetLayerName(layer_id)
                        plotter.SetLayer(layer_id)
                        plotter.PlotLayer()
                        plotted_layers.append(layer_name)

            # Finalize and flush the plot file to disk
            plotter.ClosePlot()

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
        """Export 3D model files using kicad-cli (KiCAD 9.0 compatible)"""
        import subprocess
        import platform
        import shutil

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

            # Get board file path
            board_file = self.board.GetFileName()
            if not board_file or not os.path.exists(board_file):
                return {
                    "success": False,
                    "message": "Board file not found",
                    "errorDetails": "Board must be saved before exporting 3D models"
                }

            # Create output directory if it doesn't exist
            output_path = os.path.abspath(os.path.expanduser(output_path))
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Find kicad-cli executable
            kicad_cli = self._find_kicad_cli()
            if not kicad_cli:
                return {
                    "success": False,
                    "message": "kicad-cli not found",
                    "errorDetails": "KiCAD CLI tool not found. Install KiCAD 8.0+ or set PATH."
                }

            # Build command based on format
            format_upper = format.upper()

            if format_upper == "STEP":
                cmd = [
                    kicad_cli,
                    'pcb', 'export', 'step',
                    '--output', output_path,
                    '--force'  # Overwrite existing file
                ]

                # Add options based on parameters
                if not include_components:
                    cmd.append('--no-components')
                if include_copper:
                    cmd.extend(['--include-tracks', '--include-pads', '--include-zones'])
                if include_silkscreen:
                    cmd.append('--include-silkscreen')
                if include_solder_mask:
                    cmd.append('--include-soldermask')

                cmd.append(board_file)

            elif format_upper == "VRML":
                cmd = [
                    kicad_cli,
                    'pcb', 'export', 'vrml',
                    '--output', output_path,
                    '--units', 'mm',  # Use mm for consistency
                    '--force'
                ]

                if not include_components:
                    # Note: VRML export doesn't have a direct --no-components flag
                    # The models will be included by default, but can be controlled via 3D settings
                    pass

                cmd.append(board_file)

            else:
                return {
                    "success": False,
                    "message": "Unsupported format",
                    "errorDetails": f"Format {format} is not supported. Use 'STEP' or 'VRML'."
                }

            # Execute kicad-cli command
            logger.info(f"Running 3D export command: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout for 3D export
            )

            if result.returncode != 0:
                logger.error(f"3D export command failed: {result.stderr}")
                return {
                    "success": False,
                    "message": "3D export command failed",
                    "errorDetails": result.stderr
                }

            return {
                "success": True,
                "message": f"Exported {format_upper} file",
                "file": {
                    "path": output_path,
                    "format": format_upper
                }
            }

        except subprocess.TimeoutExpired:
            logger.error("3D export command timed out")
            return {
                "success": False,
                "message": "3D export timed out",
                "errorDetails": "Export took longer than 5 minutes"
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
                    "footprint": str(module.GetFPID()),
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

    def _find_kicad_cli(self) -> Optional[str]:
        """Find kicad-cli executable in system PATH or common locations

        Returns:
            Path to kicad-cli executable, or None if not found
        """
        import shutil
        import platform

        # Try system PATH first
        cli_path = shutil.which("kicad-cli")
        if cli_path:
            return cli_path

        # Try platform-specific default locations
        system = platform.system()

        if system == "Windows":
            possible_paths = [
                r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
                r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe",
                r"C:\Program Files (x86)\KiCad\9.0\bin\kicad-cli.exe",
                r"C:\Program Files (x86)\KiCad\8.0\bin\kicad-cli.exe",
            ]
        elif system == "Darwin":  # macOS
            possible_paths = [
                "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
                "/usr/local/bin/kicad-cli",
            ]
        else:  # Linux
            possible_paths = [
                "/usr/bin/kicad-cli",
                "/usr/local/bin/kicad-cli",
            ]

        for path in possible_paths:
            if os.path.exists(path):
                return path

        return None
