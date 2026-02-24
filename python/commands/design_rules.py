"""
Design rules command implementations for KiCAD interface
"""

import os
import pcbnew
import logging
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger('kicad_interface')

class DesignRuleCommands:
    """Handles design rule checking and configuration"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

    def set_design_rules(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Set design rules for the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            design_settings = self.board.GetDesignSettings()

            # Convert mm to nanometers for KiCAD internal units
            scale = 1000000  # mm to nm

            # Set clearance
            if "clearance" in params:
                design_settings.m_MinClearance = int(params["clearance"] * scale)

            # KiCAD 9.0: Use SetCustom* methods instead of SetCurrent* (which were removed)
            # Track if we set any custom track/via values
            custom_values_set = False

            if "trackWidth" in params:
                design_settings.SetCustomTrackWidth(int(params["trackWidth"] * scale))
                custom_values_set = True

            # Via settings
            if "viaDiameter" in params:
                design_settings.SetCustomViaSize(int(params["viaDiameter"] * scale))
                custom_values_set = True
            if "viaDrill" in params:
                design_settings.SetCustomViaDrill(int(params["viaDrill"] * scale))
                custom_values_set = True

            # KiCAD 9.0: Activate custom track/via values so they become the current values
            if custom_values_set:
                design_settings.UseCustomTrackViaSize(True)

            # Set micro via settings (use properties - methods removed in KiCAD 9.0)
            if "microViaDiameter" in params:
                design_settings.m_MicroViasMinSize = int(params["microViaDiameter"] * scale)
            if "microViaDrill" in params:
                design_settings.m_MicroViasMinDrill = int(params["microViaDrill"] * scale)

            # Set minimum values
            if "minTrackWidth" in params:
                design_settings.m_TrackMinWidth = int(params["minTrackWidth"] * scale)
            if "minViaDiameter" in params:
                design_settings.m_ViasMinSize = int(params["minViaDiameter"] * scale)

            # KiCAD 9.0: m_ViasMinDrill removed - use m_MinThroughDrill instead
            if "minViaDrill" in params:
                design_settings.m_MinThroughDrill = int(params["minViaDrill"] * scale)

            if "minMicroViaDiameter" in params:
                design_settings.m_MicroViasMinSize = int(params["minMicroViaDiameter"] * scale)
            if "minMicroViaDrill" in params:
                design_settings.m_MicroViasMinDrill = int(params["minMicroViaDrill"] * scale)

            # KiCAD 9.0: m_MinHoleDiameter removed - use m_MinThroughDrill
            if "minHoleDiameter" in params:
                design_settings.m_MinThroughDrill = int(params["minHoleDiameter"] * scale)

            # KiCAD 9.0: Added hole clearance settings
            if "holeClearance" in params:
                design_settings.m_HoleClearance = int(params["holeClearance"] * scale)
            if "holeToHoleMin" in params:
                design_settings.m_HoleToHoleMin = int(params["holeToHoleMin"] * scale)

            # Build response with KiCAD 9.0 compatible properties
            # After UseCustomTrackViaSize(True), GetCurrent* returns the custom values
            response_rules = {
                "clearance": design_settings.m_MinClearance / scale,
                "trackWidth": design_settings.GetCurrentTrackWidth() / scale,
                "viaDiameter": design_settings.GetCurrentViaSize() / scale,
                "viaDrill": design_settings.GetCurrentViaDrill() / scale,
                "microViaDiameter": design_settings.m_MicroViasMinSize / scale,
                "microViaDrill": design_settings.m_MicroViasMinDrill / scale,
                "minTrackWidth": design_settings.m_TrackMinWidth / scale,
                "minViaDiameter": design_settings.m_ViasMinSize / scale,
                "minThroughDrill": design_settings.m_MinThroughDrill / scale,
                "minMicroViaDiameter": design_settings.m_MicroViasMinSize / scale,
                "minMicroViaDrill": design_settings.m_MicroViasMinDrill / scale,
                "holeClearance": design_settings.m_HoleClearance / scale,
                "holeToHoleMin": design_settings.m_HoleToHoleMin / scale,
                "viasMinAnnularWidth": design_settings.m_ViasMinAnnularWidth / scale
            }

            return {
                "success": True,
                "message": "Updated design rules",
                "rules": response_rules
            }

        except Exception as e:
            logger.error(f"Error setting design rules: {str(e)}")
            return {
                "success": False,
                "message": "Failed to set design rules",
                "errorDetails": str(e)
            }

    def get_design_rules(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get current design rules - KiCAD 9.0 compatible"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            design_settings = self.board.GetDesignSettings()
            scale = 1000000  # nm to mm

            # Build rules dict with KiCAD 9.0 compatible properties
            rules = {
                # Core clearance and track settings
                "clearance": design_settings.m_MinClearance / scale,
                "trackWidth": design_settings.GetCurrentTrackWidth() / scale,
                "minTrackWidth": design_settings.m_TrackMinWidth / scale,

                # Via settings (current values from methods)
                "viaDiameter": design_settings.GetCurrentViaSize() / scale,
                "viaDrill": design_settings.GetCurrentViaDrill() / scale,

                # Via minimum values
                "minViaDiameter": design_settings.m_ViasMinSize / scale,
                "viasMinAnnularWidth": design_settings.m_ViasMinAnnularWidth / scale,

                # Micro via settings
                "microViaDiameter": design_settings.m_MicroViasMinSize / scale,
                "microViaDrill": design_settings.m_MicroViasMinDrill / scale,
                "minMicroViaDiameter": design_settings.m_MicroViasMinSize / scale,
                "minMicroViaDrill": design_settings.m_MicroViasMinDrill / scale,

                # KiCAD 9.0: Hole and drill settings (replaces removed m_ViasMinDrill and m_MinHoleDiameter)
                "minThroughDrill": design_settings.m_MinThroughDrill / scale,
                "holeClearance": design_settings.m_HoleClearance / scale,
                "holeToHoleMin": design_settings.m_HoleToHoleMin / scale,

                # Other constraints
                "copperEdgeClearance": design_settings.m_CopperEdgeClearance / scale,
                "silkClearance": design_settings.m_SilkClearance / scale,
            }

            return {
                "success": True,
                "rules": rules
            }

        except Exception as e:
            logger.error(f"Error getting design rules: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get design rules",
                "errorDetails": str(e)
            }

    def run_drc(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run Design Rule Check using kicad-cli"""
        import subprocess
        import json
        import tempfile
        import platform
        import shutil

        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            report_path = params.get("reportPath")

            # Get the board file path
            board_file = self.board.GetFileName()
            if not board_file or not os.path.exists(board_file):
                return {
                    "success": False,
                    "message": "Board file not found",
                    "errorDetails": "Cannot run DRC without a saved board file"
                }

            # Find kicad-cli executable
            kicad_cli = self._find_kicad_cli()
            if not kicad_cli:
                return {
                    "success": False,
                    "message": "kicad-cli not found",
                    "errorDetails": "KiCAD CLI tool not found in system. Install KiCAD 8.0+ or set PATH."
                }

            # Create temporary JSON output file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
                json_output = tmp.name

            try:
                # Build command
                cmd = [
                    kicad_cli,
                    'pcb',
                    'drc',
                    '--format', 'json',
                    '--output', json_output,
                    '--units', 'mm',
                    board_file
                ]

                logger.info(f"Running DRC command: {' '.join(cmd)}")

                # Run DRC
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=600  # 10 minute timeout for large boards (21MB PCB needs time)
                )

                if result.returncode != 0:
                    logger.error(f"DRC command failed: {result.stderr}")
                    return {
                        "success": False,
                        "message": "DRC command failed",
                        "errorDetails": result.stderr
                    }

                # Read JSON output
                with open(json_output, 'r', encoding='utf-8') as f:
                    drc_data = json.load(f)

                # Parse violations from kicad-cli output
                violations = []
                violation_counts = {}
                severity_counts = {"error": 0, "warning": 0, "info": 0}

                for violation in drc_data.get('violations', []):
                    vtype = violation.get("type", "unknown")
                    vseverity = violation.get("severity", "error")

                    violations.append({
                        "type": vtype,
                        "severity": vseverity,
                        "message": violation.get("description", ""),
                        "location": {
                            "x": violation.get("x", 0),
                            "y": violation.get("y", 0),
                            "unit": "mm"
                        }
                    })

                    # Count violations by type
                    violation_counts[vtype] = violation_counts.get(vtype, 0) + 1

                    # Count by severity
                    if vseverity in severity_counts:
                        severity_counts[vseverity] += 1

                # Determine where to save the violations file
                board_dir = os.path.dirname(board_file)
                board_name = os.path.splitext(os.path.basename(board_file))[0]
                violations_file = os.path.join(board_dir, f"{board_name}_drc_violations.json")

                # Always save violations to JSON file (for large result sets)
                with open(violations_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        "board": board_file,
                        "timestamp": drc_data.get("date", "unknown"),
                        "total_violations": len(violations),
                        "violation_counts": violation_counts,
                        "severity_counts": severity_counts,
                        "violations": violations
                    }, f, indent=2)

                # Save text report if requested
                if report_path:
                    report_path = os.path.abspath(os.path.expanduser(report_path))
                    cmd_report = [
                        kicad_cli,
                        'pcb',
                        'drc',
                        '--format', 'report',
                        '--output', report_path,
                        '--units', 'mm',
                        board_file
                    ]
                    subprocess.run(cmd_report, capture_output=True, timeout=600)

                # Return summary only (not full violations list)
                return {
                    "success": True,
                    "message": f"Found {len(violations)} DRC violations",
                    "summary": {
                        "total": len(violations),
                        "by_severity": severity_counts,
                        "by_type": violation_counts
                    },
                    "violationsFile": violations_file,
                    "reportPath": report_path if report_path else None
                }

            finally:
                # Clean up temp JSON file
                if os.path.exists(json_output):
                    os.unlink(json_output)

        except subprocess.TimeoutExpired:
            logger.error("DRC command timed out")
            return {
                "success": False,
                "message": "DRC command timed out",
                "errorDetails": "Command took longer than 600 seconds (10 minutes)"
            }
        except Exception as e:
            logger.error(f"Error running DRC: {str(e)}")
            return {
                "success": False,
                "message": "Failed to run DRC",
                "errorDetails": str(e)
            }

    def _find_kicad_cli(self) -> Optional[str]:
        """Find kicad-cli executable"""
        import platform
        import shutil

        # Try system PATH first
        cli_name = "kicad-cli.exe" if platform.system() == "Windows" else "kicad-cli"
        cli_path = shutil.which(cli_name)
        if cli_path:
            return cli_path

        # Try common installation paths (version-specific)
        if platform.system() == "Windows":
            common_paths = [
                r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe",
                r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
                r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe",
                r"C:\Program Files (x86)\KiCad\10.0\bin\kicad-cli.exe",
                r"C:\Program Files (x86)\KiCad\9.0\bin\kicad-cli.exe",
                r"C:\Program Files (x86)\KiCad\8.0\bin\kicad-cli.exe",
                r"C:\Program Files\KiCad\bin\kicad-cli.exe",
            ]
            for path in common_paths:
                if os.path.exists(path):
                    return path
        elif platform.system() == "Darwin":  # macOS
            common_paths = [
                "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
                "/usr/local/bin/kicad-cli",
            ]
            for path in common_paths:
                if os.path.exists(path):
                    return path
        else:  # Linux
            common_paths = [
                "/usr/bin/kicad-cli",
                "/usr/local/bin/kicad-cli",
            ]
            for path in common_paths:
                if os.path.exists(path):
                    return path

        return None

    def set_layer_constraints(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Set design constraints for a specific layer"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            layer_name = params.get("layer")
            if not layer_name:
                return {
                    "success": False,
                    "message": "Missing layer name",
                    "errorDetails": "layer parameter is required"
                }

            layer_id = self.board.GetLayerID(layer_name)
            if layer_id < 0:
                return {
                    "success": False,
                    "message": f"Invalid layer: {layer_name}",
                    "errorDetails": f"Layer '{layer_name}' does not exist on this board"
                }

            # KiCAD 9.0: Layer-specific constraints are managed through custom rules
            # We can set them via the design settings' per-layer overrides
            design_settings = self.board.GetDesignSettings()
            scale = 1000000  # mm to nm

            constraints_set = []

            # Note: KiCAD's SWIG API has limited per-layer constraint support
            # Most layer constraints are handled through custom DRC rules
            # We apply what we can through the design settings

            min_track_width = params.get("minTrackWidth")
            min_clearance = params.get("minClearance")
            min_via_diameter = params.get("minViaDiameter")
            min_via_drill = params.get("minViaDrill")

            # Apply global minimums if they're more restrictive
            if min_track_width is not None:
                current = design_settings.m_TrackMinWidth / scale
                if min_track_width > current:
                    design_settings.m_TrackMinWidth = int(min_track_width * scale)
                    constraints_set.append(f"minTrackWidth={min_track_width}mm")
                else:
                    constraints_set.append(f"minTrackWidth={min_track_width}mm (note: global min is {current}mm)")

            if min_clearance is not None:
                current = design_settings.m_MinClearance / scale
                if min_clearance > current:
                    design_settings.m_MinClearance = int(min_clearance * scale)
                    constraints_set.append(f"minClearance={min_clearance}mm")
                else:
                    constraints_set.append(f"minClearance={min_clearance}mm (note: global min is {current}mm)")

            if min_via_diameter is not None:
                current = design_settings.m_ViasMinSize / scale
                if min_via_diameter > current:
                    design_settings.m_ViasMinSize = int(min_via_diameter * scale)
                    constraints_set.append(f"minViaDiameter={min_via_diameter}mm")
                else:
                    constraints_set.append(f"minViaDiameter={min_via_diameter}mm (note: global min is {current}mm)")

            if min_via_drill is not None:
                current = design_settings.m_MinThroughDrill / scale
                if min_via_drill > current:
                    design_settings.m_MinThroughDrill = int(min_via_drill * scale)
                    constraints_set.append(f"minViaDrill={min_via_drill}mm")
                else:
                    constraints_set.append(f"minViaDrill={min_via_drill}mm (note: global min is {current}mm)")

            if not constraints_set:
                return {
                    "success": False,
                    "message": "No constraints specified",
                    "errorDetails": "Provide at least one constraint: minTrackWidth, minClearance, minViaDiameter, minViaDrill"
                }

            return {
                "success": True,
                "message": f"Set constraints for layer {layer_name}: {', '.join(constraints_set)}",
                "layer": layer_name,
                "constraints": constraints_set,
                "note": "KiCAD applies these as global minimums. For per-layer rules, use custom DRC rules."
            }

        except Exception as e:
            logger.error(f"Error setting layer constraints: {str(e)}")
            return {
                "success": False,
                "message": "Failed to set layer constraints",
                "errorDetails": str(e)
            }

    def check_clearance(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Check clearance between two items on the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            item1 = params.get("item1", {})
            item2 = params.get("item2", {})

            if not item1 or not item2:
                return {
                    "success": False,
                    "message": "Missing items",
                    "errorDetails": "Both item1 and item2 are required"
                }

            scale = 1000000  # nm to mm conversion

            # Resolve item positions
            pos1 = self._resolve_item_position(item1)
            pos2 = self._resolve_item_position(item2)

            if not pos1 or not pos2:
                return {
                    "success": False,
                    "message": "Could not resolve item positions",
                    "errorDetails": "Provide position or reference for both items"
                }

            # Calculate distance between positions
            dx = pos1.x - pos2.x
            dy = pos1.y - pos2.y
            distance_nm = (dx * dx + dy * dy) ** 0.5
            distance_mm = distance_nm / scale

            # Get minimum clearance from design rules
            design_settings = self.board.GetDesignSettings()
            min_clearance = design_settings.m_MinClearance / scale

            # Determine if clearance is adequate
            passes = distance_mm >= min_clearance

            return {
                "success": True,
                "clearance": {
                    "distance": round(distance_mm, 4),
                    "unit": "mm",
                    "minRequired": round(min_clearance, 4),
                    "passes": passes
                },
                "item1": {
                    "type": item1.get("type"),
                    "position": {"x": round(pos1.x / scale, 4), "y": round(pos1.y / scale, 4)}
                },
                "item2": {
                    "type": item2.get("type"),
                    "position": {"x": round(pos2.x / scale, 4), "y": round(pos2.y / scale, 4)}
                },
                "message": f"Clearance: {distance_mm:.4f}mm ({'PASS' if passes else 'FAIL'}, min: {min_clearance:.4f}mm)"
            }

        except Exception as e:
            logger.error(f"Error checking clearance: {str(e)}")
            return {
                "success": False,
                "message": "Failed to check clearance",
                "errorDetails": str(e)
            }

    def _resolve_item_position(self, item: Dict[str, Any]):
        """Resolve an item specification to a board position"""
        item_type = item.get("type")
        reference = item.get("reference")
        position = item.get("position")

        scale = 1000000  # mm to nm

        # If position is directly provided
        if position:
            unit = position.get("unit", "mm")
            unit_scale = scale if unit == "mm" else 25400000
            x = int(position.get("x", 0) * unit_scale)
            y = int(position.get("y", 0) * unit_scale)
            return pcbnew.VECTOR2I(x, y)

        # If reference is provided (for components)
        if reference and item_type == "component":
            fp = self.board.FindFootprintByReference(reference)
            if fp:
                return fp.GetPosition()

        # If reference is a pad
        if reference and item_type == "pad":
            # reference format: "R1:1" or just "R1" with pad in id
            pad_id = item.get("id")
            parts = reference.split(":") if ":" in reference else [reference]
            fp = self.board.FindFootprintByReference(parts[0])
            if fp:
                if len(parts) > 1:
                    pad = fp.FindPadByName(parts[1])
                elif pad_id:
                    pad = fp.FindPadByName(pad_id)
                else:
                    # Return first pad
                    pads = list(fp.Pads())
                    pad = pads[0] if pads else None
                if pad:
                    return pad.GetPosition()

        return None

    def get_drc_violations(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get list of DRC violations"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            severity = params.get("severity", "all")

            # Get DRC markers
            violations = []
            for marker in self.board.GetDRCMarkers():
                violation = {
                    "type": marker.GetErrorCode(),
                    "severity": "error",  # KiCAD DRC markers are always errors
                    "message": marker.GetDescription(),
                    "location": {
                        "x": marker.GetPos().x / 1000000,
                        "y": marker.GetPos().y / 1000000,
                        "unit": "mm"
                    }
                }

                # Filter by severity if specified
                if severity == "all" or severity == violation["severity"]:
                    violations.append(violation)

            return {
                "success": True,
                "violations": violations
            }

        except Exception as e:
            logger.error(f"Error getting DRC violations: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get DRC violations",
                "errorDetails": str(e)
            }
