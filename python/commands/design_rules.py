"""
Design rules command implementations for KiCAD interface
"""

import logging
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pcbnew
from commands.routing import persist_net_assignment_to_project
from utils.kicad_cli import kicad_cli_not_found_message, resolve_kicad_cli

logger = logging.getLogger("kicad_interface")


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
                    "errorDetails": "Load or create a board first",
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
                "viasMinAnnularWidth": design_settings.m_ViasMinAnnularWidth / scale,
            }

            return {
                "success": True,
                "message": "Updated design rules",
                "rules": response_rules,
            }

        except Exception as e:
            logger.error(f"Error setting design rules: {str(e)}")
            return {
                "success": False,
                "message": "Failed to set design rules",
                "errorDetails": str(e),
            }

    def get_design_rules(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get current design rules - KiCAD 9.0 compatible"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
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

            return {"success": True, "rules": rules}

        except Exception as e:
            logger.error(f"Error getting design rules: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get design rules",
                "errorDetails": str(e),
            }

    def assign_net_to_class(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Assign an existing net to an existing net class.

        Mirrors ``RoutingCommands.create_netclass``'s dual-write shape: a
        best-effort in-memory ``NETINFO_ITEM.SetClass`` for the live SWIG
        session, plus a durable write to the project's
        ``net_settings.netclass_assignments`` (KiCad 7+ net-class membership
        lives in ``.kicad_pro``, not the ``.kicad_pcb`` the SWIG board save
        writes — same reasoning as issue #302).
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            net_name = params.get("net")
            class_name = params.get("netClass")

            if not net_name or not class_name:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "net and netClass are both required",
                }

            netinfo = self.board.GetNetInfo()
            nets_map = netinfo.NetsByName()
            if not nets_map.has_key(net_name):
                return {
                    "success": False,
                    "message": f"Net not found: {net_name}",
                    "errorDetails": f"'{net_name}' does not exist on the board",
                }
            net = nets_map[net_name]

            # KiCad 6/7 returns NETCLASSES with .Find; KiCad 9/10 returns a
            # dict-like netclasses_map. Same defensive lookup as create_netclass.
            net_classes = self.board.GetNetClasses()
            resolved = None
            if hasattr(net_classes, "Find"):
                resolved = net_classes.Find(class_name)
            else:
                try:
                    if class_name in net_classes:
                        resolved = net_classes[class_name]
                except Exception:
                    resolved = None

            if resolved is None:
                return {
                    "success": False,
                    "message": f"Net class not found: {class_name}",
                    "errorDetails": f"Create it first with create_netclass (got '{class_name}')",
                }

            in_memory_warning = None
            try:
                net.SetClass(resolved)
            except Exception as exc:
                in_memory_warning = f"in-memory net class assignment failed: {exc}"
                logger.warning("assign_net_to_class: %s", in_memory_warning)

            pro_path = None
            try:
                board_path = self.board.GetFileName()
                if board_path and board_path.endswith(".kicad_pcb"):
                    pro_path = str(Path(board_path).with_suffix(".kicad_pro"))
            except Exception:
                pro_path = None

            persist = persist_net_assignment_to_project(pro_path, net_name, class_name)

            warnings = [w for w in (in_memory_warning, persist.get("warning")) if w]
            if in_memory_warning and not persist.get("persisted"):
                # Neither the live board nor the project file received the assignment.
                return {
                    "success": False,
                    "message": "Failed to assign net to class",
                    "errorDetails": "; ".join(warnings),
                }

            result = {
                "success": True,
                "message": f"Assigned net {net_name} to class {class_name}",
                "net": net_name,
                "netClass": class_name,
                "persisted": persist.get("persisted", False),
            }
            if persist.get("projectFile"):
                result["projectFile"] = persist["projectFile"]
            if warnings:
                result["warning"] = "; ".join(warnings)
            return result

        except Exception as e:
            logger.error(f"Error assigning net to class: {str(e)}")
            return {
                "success": False,
                "message": "Failed to assign net to class",
                "errorDetails": str(e),
            }

    def check_clearance(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Check the measured clearance between two PCB items against the board's
        minimum clearance design rule.

        Items resolve to an axis-aligned bounding box (``GetBoundingBox()``) —
        the same AABB approximation ``check_courtyard_overlaps`` already uses
        for footprint-to-footprint checks. This is approximate for
        non-rectangular/angled items (e.g. a circular pad's bbox is its
        bounding square, an angled track's bbox is larger than the track
        itself), so it can read closer than the true clearance never further.
        It is a fast ad-hoc check, not a substitute for a full DRC run
        (``run_drc`` / ``get_drc_violations``), which uses KiCad's exact
        polygon-based clearance resolver.

        Item resolution supports ``id`` (item UUID) for any type, and
        ``reference`` for ``type: "component"``. Position-based lookup is not
        supported in this version — callers should query the item's UUID
        first (e.g. via ``query_traces`` / ``get_component_pads``).
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            item1_spec = params.get("item1")
            item2_spec = params.get("item2")
            if not item1_spec or not item2_spec:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "item1 and item2 are both required",
                }

            item1, err1 = self._resolve_clearance_item(item1_spec)
            if err1:
                return {
                    "success": False,
                    "message": "Could not resolve item1",
                    "errorDetails": err1,
                }
            item2, err2 = self._resolve_clearance_item(item2_spec)
            if err2:
                return {
                    "success": False,
                    "message": "Could not resolve item2",
                    "errorDetails": err2,
                }

            scale = 1000000  # nm to mm
            distance_mm = self._bbox_gap_nm(item1.GetBoundingBox(), item2.GetBoundingBox()) / scale

            required_mm = self.board.GetDesignSettings().m_MinClearance / scale

            return {
                "success": True,
                "actualClearance": round(distance_mm, 6),
                "requiredClearance": round(required_mm, 6),
                "meetsRequirement": distance_mm >= required_mm,
                "unit": "mm",
            }

        except Exception as e:
            logger.error(f"Error checking clearance: {str(e)}")
            return {
                "success": False,
                "message": "Failed to check clearance",
                "errorDetails": str(e),
            }

    def _resolve_clearance_item(self, spec: Dict[str, Any]) -> Tuple[Optional[Any], Optional[str]]:
        """Resolve a ``check_clearance`` item spec to a board item.

        Returns ``(item, None)`` on success or ``(None, error_message)`` on
        failure. Supports ``id`` (UUID, any type) and ``reference``
        (``type: "component"`` only).
        """
        item_type = spec.get("type")
        item_id = spec.get("id")
        reference = spec.get("reference")

        if item_type == "component":
            if reference:
                fp = self.board.FindFootprintByReference(reference)
                if fp:
                    return fp, None
                return None, f"component '{reference}' not found"
            if item_id:
                for fp in self.board.GetFootprints():
                    if fp.m_Uuid.AsString() == item_id:
                        return fp, None
                return None, f"component with id '{item_id}' not found"
            return None, "component requires 'reference' or 'id'"

        if item_type in ("track", "via"):
            if not item_id:
                return None, f"{item_type} requires 'id' (position lookup is not supported)"
            for track in self.board.GetTracks():
                if track.m_Uuid.AsString() == item_id:
                    return track, None
            return None, f"{item_type} with id '{item_id}' not found"

        if item_type == "pad":
            if not item_id:
                return None, "pad requires 'id' (position lookup is not supported)"
            for fp in self.board.GetFootprints():
                for pad in fp.Pads():
                    if pad.m_Uuid.AsString() == item_id:
                        return pad, None
            return None, f"pad with id '{item_id}' not found"

        if item_type == "zone":
            if not item_id:
                return None, "zone requires 'id' (position lookup is not supported)"
            for zone in self.board.Zones():
                if zone.m_Uuid.AsString() == item_id:
                    return zone, None
            return None, f"zone with id '{item_id}' not found"

        return None, f"unknown item type: {item_type!r}"

    @staticmethod
    def _bbox_gap_nm(box1: Any, box2: Any) -> float:
        """Edge-to-edge gap (nm) between two pcbnew ``BOX2I`` bounding boxes.

        Returns 0 when the boxes overlap or touch.
        """
        dx = max(0, max(box1.GetLeft() - box2.GetRight(), box2.GetLeft() - box1.GetRight()))
        dy = max(0, max(box1.GetTop() - box2.GetBottom(), box2.GetTop() - box1.GetBottom()))
        return math.hypot(dx, dy)

    def run_drc(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run Design Rule Check using kicad-cli"""
        import json
        import platform
        import shutil
        import subprocess
        import tempfile

        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            report_path = params.get("reportPath")
            # Caller-overridable timeout (seconds). Defaults to 600s for big boards
            # but smaller MCP transport budgets (e.g. 120s) can lower it explicitly.
            try:
                timeout_sec = int(params.get("timeoutSec", 600))
            except (TypeError, ValueError):
                timeout_sec = 600
            timeout_sec = max(10, min(timeout_sec, 1800))  # clamp to [10, 1800]

            # Get the board file path
            board_file = self.board.GetFileName()
            if not board_file or not os.path.exists(board_file):
                return {
                    "success": False,
                    "message": "Board file not found",
                    "errorDetails": "Cannot run DRC without a saved board file",
                }

            # Find kicad-cli executable
            kicad_cli = self._find_kicad_cli()
            if not kicad_cli:
                return {
                    "success": False,
                    "message": kicad_cli_not_found_message(),
                }

            # Create temporary JSON output file
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
                json_output = tmp.name

            try:
                # Build command
                cmd = [
                    kicad_cli,
                    "pcb",
                    "drc",
                    "--format",
                    "json",
                    "--output",
                    json_output,
                    "--units",
                    "mm",
                    board_file,
                ]

                logger.info(f"Running DRC command (timeout={timeout_sec}s): {' '.join(cmd)}")

                # Run DRC. subprocess.run kills the child on TimeoutExpired.
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                )

                if result.returncode != 0:
                    logger.error(f"DRC command failed: {result.stderr}")
                    return {
                        "success": False,
                        "message": "DRC command failed",
                        "errorDetails": result.stderr,
                    }

                # Read JSON output
                with open(json_output, "r", encoding="utf-8") as f:
                    drc_data = json.load(f)

                # Parse violations from kicad-cli output
                violations = []
                violation_counts: dict[str, int] = {}
                severity_counts = {"error": 0, "warning": 0, "info": 0}

                for violation in drc_data.get("violations", []):
                    vtype = violation.get("type", "unknown")
                    vseverity = violation.get("severity", "error")

                    # Extract location from first item's pos (kicad-cli JSON format)
                    items = violation.get("items", [])
                    loc_x, loc_y = 0, 0
                    if items and "pos" in items[0]:
                        loc_x = items[0]["pos"].get("x", 0)
                        loc_y = items[0]["pos"].get("y", 0)

                    violations.append(
                        {
                            "type": vtype,
                            "severity": vseverity,
                            "message": violation.get("description", ""),
                            "location": {
                                "x": loc_x,
                                "y": loc_y,
                                "unit": "mm",
                            },
                        }
                    )

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
                with open(violations_file, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "board": board_file,
                            "timestamp": drc_data.get("date", "unknown"),
                            "total_violations": len(violations),
                            "violation_counts": violation_counts,
                            "severity_counts": severity_counts,
                            "violations": violations,
                        },
                        f,
                        indent=2,
                    )

                # Save text report if requested
                if report_path:
                    report_path = os.path.abspath(os.path.expanduser(report_path))
                    cmd_report = [
                        kicad_cli,
                        "pcb",
                        "drc",
                        "--format",
                        "report",
                        "--output",
                        report_path,
                        "--units",
                        "mm",
                        board_file,
                    ]
                    subprocess.run(cmd_report, capture_output=True, timeout=timeout_sec)

                # Return summary only (not full violations list)
                return {
                    "success": True,
                    "message": f"Found {len(violations)} DRC violations",
                    "summary": {
                        "total": len(violations),
                        "by_severity": severity_counts,
                        "by_type": violation_counts,
                    },
                    "violationsFile": violations_file,
                    "reportPath": report_path if report_path else None,
                }

            finally:
                # Clean up temp JSON file
                if os.path.exists(json_output):
                    os.unlink(json_output)

        except subprocess.TimeoutExpired:
            logger.error(f"DRC command timed out after {timeout_sec}s")
            return {
                "success": False,
                "message": "DRC command timed out",
                "errorDetails": (
                    f"Command took longer than {timeout_sec} seconds; "
                    "raise timeoutSec param for very large boards"
                ),
            }
        except Exception as e:
            logger.error(f"Error running DRC: {str(e)}")
            return {
                "success": False,
                "message": "Failed to run DRC",
                "errorDetails": str(e),
            }

    def _find_kicad_cli(self) -> Optional[str]:
        """Find kicad-cli executable via the centralized resolver.

        Resolution order: $KICAD_CLI override -> next to the running interpreter
        (KiCad's bundled python bin/) -> PATH -> known per-OS install locations.
        """
        return resolve_kicad_cli()

    def get_drc_violations(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get list of DRC violations

        Note: This command internally uses run_drc() which calls kicad-cli.
        The old BOARD.GetDRCMarkers() API was removed in KiCAD 9.0.
        This implementation provides backward compatibility by parsing kicad-cli output.
        """
        import json

        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            severity = params.get("severity", "all")

            # Run DRC using kicad-cli (this saves violations to JSON file)
            drc_result = self.run_drc({})

            if not drc_result.get("success"):
                return drc_result  # Return the error from run_drc

            # Read violations from the saved JSON file
            violations_file = drc_result.get("violationsFile")
            if not violations_file or not os.path.exists(violations_file):
                return {
                    "success": False,
                    "message": "Violations file not found",
                    "errorDetails": "run_drc did not create violations file",
                }

            # Load violations from file
            with open(violations_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            all_violations = data.get("violations", [])

            # Filter by severity if specified
            if severity != "all":
                filtered_violations = [v for v in all_violations if v.get("severity") == severity]
            else:
                filtered_violations = all_violations

            return {
                "success": True,
                "violations": filtered_violations,
                "violationsFile": violations_file,  # Include file path for reference
            }

        except Exception as e:
            logger.error(f"Error getting DRC violations: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get DRC violations",
                "errorDetails": str(e),
            }
