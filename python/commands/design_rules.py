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
                design_settings.SetMinClearance(int(params["clearance"] * scale))

            # Set track width
            if "trackWidth" in params:
                design_settings.SetCurrentTrackWidth(int(params["trackWidth"] * scale))

            # Set via settings
            if "viaDiameter" in params:
                design_settings.SetCurrentViaSize(int(params["viaDiameter"] * scale))
            if "viaDrill" in params:
                design_settings.SetCurrentViaDrill(int(params["viaDrill"] * scale))

            # Set micro via settings
            if "microViaDiameter" in params:
                design_settings.SetCurrentMicroViaSize(int(params["microViaDiameter"] * scale))
            if "microViaDrill" in params:
                design_settings.SetCurrentMicroViaDrill(int(params["microViaDrill"] * scale))

            # Set minimum values
            if "minTrackWidth" in params:
                design_settings.m_TrackMinWidth = int(params["minTrackWidth"] * scale)
            if "minViaDiameter" in params:
                design_settings.m_ViasMinSize = int(params["minViaDiameter"] * scale)
            if "minViaDrill" in params:
                design_settings.m_ViasMinDrill = int(params["minViaDrill"] * scale)
            if "minMicroViaDiameter" in params:
                design_settings.m_MicroViasMinSize = int(params["minMicroViaDiameter"] * scale)
            if "minMicroViaDrill" in params:
                design_settings.m_MicroViasMinDrill = int(params["minMicroViaDrill"] * scale)

            # Set hole diameter
            if "minHoleDiameter" in params:
                design_settings.m_MinHoleDiameter = int(params["minHoleDiameter"] * scale)

            # Set courtyard settings
            if "requireCourtyard" in params:
                design_settings.m_RequireCourtyards = params["requireCourtyard"]
            if "courtyardClearance" in params:
                design_settings.m_CourtyardMinClearance = int(params["courtyardClearance"] * scale)

            return {
                "success": True,
                "message": "Updated design rules",
                "rules": {
                    "clearance": design_settings.GetMinClearance() / scale,
                    "trackWidth": design_settings.GetCurrentTrackWidth() / scale,
                    "viaDiameter": design_settings.GetCurrentViaSize() / scale,
                    "viaDrill": design_settings.GetCurrentViaDrill() / scale,
                    "microViaDiameter": design_settings.GetCurrentMicroViaSize() / scale,
                    "microViaDrill": design_settings.GetCurrentMicroViaDrill() / scale,
                    "minTrackWidth": design_settings.m_TrackMinWidth / scale,
                    "minViaDiameter": design_settings.m_ViasMinSize / scale,
                    "minViaDrill": design_settings.m_ViasMinDrill / scale,
                    "minMicroViaDiameter": design_settings.m_MicroViasMinSize / scale,
                    "minMicroViaDrill": design_settings.m_MicroViasMinDrill / scale,
                    "minHoleDiameter": design_settings.m_MinHoleDiameter / scale,
                    "requireCourtyard": design_settings.m_RequireCourtyards,
                    "courtyardClearance": design_settings.m_CourtyardMinClearance / scale
                }
            }

        except Exception as e:
            logger.error(f"Error setting design rules: {str(e)}")
            return {
                "success": False,
                "message": "Failed to set design rules",
                "errorDetails": str(e)
            }

    def get_design_rules(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get current design rules"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            design_settings = self.board.GetDesignSettings()
            scale = 1000000  # nm to mm

            return {
                "success": True,
                "rules": {
                    "clearance": design_settings.GetMinClearance() / scale,
                    "trackWidth": design_settings.GetCurrentTrackWidth() / scale,
                    "viaDiameter": design_settings.GetCurrentViaSize() / scale,
                    "viaDrill": design_settings.GetCurrentViaDrill() / scale,
                    "microViaDiameter": design_settings.GetCurrentMicroViaSize() / scale,
                    "microViaDrill": design_settings.GetCurrentMicroViaDrill() / scale,
                    "minTrackWidth": design_settings.m_TrackMinWidth / scale,
                    "minViaDiameter": design_settings.m_ViasMinSize / scale,
                    "minViaDrill": design_settings.m_ViasMinDrill / scale,
                    "minMicroViaDiameter": design_settings.m_MicroViasMinSize / scale,
                    "minMicroViaDrill": design_settings.m_MicroViasMinDrill / scale,
                    "minHoleDiameter": design_settings.m_MinHoleDiameter / scale,
                    "requireCourtyard": design_settings.m_RequireCourtyards,
                    "courtyardClearance": design_settings.m_CourtyardMinClearance / scale
                }
            }

        except Exception as e:
            logger.error(f"Error getting design rules: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get design rules",
                "errorDetails": str(e)
            }

    def run_drc(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run Design Rule Check"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            report_path = params.get("reportPath")

            # Create DRC runner
            drc = pcbnew.DRC(self.board)
            
            # Run DRC
            drc.Run()

            # Get violations
            violations = []
            for marker in drc.GetMarkers():
                violations.append({
                    "type": marker.GetErrorCode(),
                    "severity": "error",
                    "message": marker.GetDescription(),
                    "location": {
                        "x": marker.GetPos().x / 1000000,
                        "y": marker.GetPos().y / 1000000,
                        "unit": "mm"
                    }
                })

            # Save report if path provided
            if report_path:
                report_path = os.path.abspath(os.path.expanduser(report_path))
                drc.WriteReport(report_path)

            return {
                "success": True,
                "message": f"Found {len(violations)} DRC violations",
                "violations": violations,
                "reportPath": report_path if report_path else None
            }

        except Exception as e:
            logger.error(f"Error running DRC: {str(e)}")
            return {
                "success": False,
                "message": "Failed to run DRC",
                "errorDetails": str(e)
            }

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
