#!/usr/bin/env python3
"""
KiCAD Python Interface Script for Model Context Protocol

This script handles communication between the MCP TypeScript server
and KiCAD's Python API (pcbnew). It receives commands via stdin as
JSON and returns responses via stdout also as JSON.
"""

import sys
import json
import traceback
import logging
import os
from typing import Dict, Any, Optional

# Import tool schemas and resource definitions
from schemas.tool_schemas import TOOL_SCHEMAS
from resources.resource_definitions import RESOURCE_DEFINITIONS, handle_resource_read

# Configure logging
log_dir = os.path.join(os.path.expanduser("~"), ".kicad-mcp", "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "kicad_interface.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_file)],
)
logger = logging.getLogger("kicad_interface")

# Log Python environment details
logger.info(f"Python version: {sys.version}")
logger.info(f"Python executable: {sys.executable}")
logger.info(f"Platform: {sys.platform}")
logger.info(f"Working directory: {os.getcwd()}")

# Windows-specific diagnostics
if sys.platform == "win32":
    logger.info("=== Windows Environment Diagnostics ===")
    logger.info(f"PYTHONPATH: {os.environ.get('PYTHONPATH', 'NOT SET')}")
    logger.info(f"PATH: {os.environ.get('PATH', 'NOT SET')[:200]}...")  # Truncate PATH

    # Check for common KiCAD installations
    common_kicad_paths = [r"C:\Program Files\KiCad", r"C:\Program Files (x86)\KiCad"]

    found_kicad = False
    for base_path in common_kicad_paths:
        if os.path.exists(base_path):
            logger.info(f"Found KiCAD installation at: {base_path}")
            # List versions
            try:
                versions = [
                    d
                    for d in os.listdir(base_path)
                    if os.path.isdir(os.path.join(base_path, d))
                ]
                logger.info(f"  Versions found: {', '.join(versions)}")
                for version in versions:
                    python_path = os.path.join(
                        base_path, version, "lib", "python3", "dist-packages"
                    )
                    if os.path.exists(python_path):
                        logger.info(f"  ✓ Python path exists: {python_path}")
                        found_kicad = True
                    else:
                        logger.warning(f"  ✗ Python path missing: {python_path}")
            except Exception as e:
                logger.warning(f"  Could not list versions: {e}")

    if not found_kicad:
        logger.warning("No KiCAD installations found in standard locations!")
        logger.warning(
            "Please ensure KiCAD 9.0+ is installed from https://www.kicad.org/download/windows/"
        )

    logger.info("========================================")

# Add utils directory to path for imports
utils_dir = os.path.join(os.path.dirname(__file__))
if utils_dir not in sys.path:
    sys.path.insert(0, utils_dir)

# Import platform helper and add KiCAD paths
from utils.platform_helper import PlatformHelper
from utils.kicad_process import check_and_launch_kicad, KiCADProcessManager

logger.info(f"Detecting KiCAD Python paths for {PlatformHelper.get_platform_name()}...")
paths_added = PlatformHelper.add_kicad_to_python_path()

if paths_added:
    logger.info("Successfully added KiCAD Python paths to sys.path")
else:
    logger.warning(
        "No KiCAD Python paths found - attempting to import pcbnew from system path"
    )

logger.info(f"Current Python path: {sys.path}")

# Check if auto-launch is enabled
AUTO_LAUNCH_KICAD = os.environ.get("KICAD_AUTO_LAUNCH", "false").lower() == "true"
if AUTO_LAUNCH_KICAD:
    logger.info("KiCAD auto-launch enabled")

# Check which backend to use
# KICAD_BACKEND can be: 'auto', 'ipc', or 'swig'
KICAD_BACKEND = os.environ.get("KICAD_BACKEND", "auto").lower()
logger.info(f"KiCAD backend preference: {KICAD_BACKEND}")

# Try to use IPC backend first if available and preferred
USE_IPC_BACKEND = False
ipc_backend = None

if KICAD_BACKEND in ("auto", "ipc"):
    try:
        logger.info("Checking IPC backend availability...")
        from kicad_api.ipc_backend import IPCBackend

        # Try to connect to running KiCAD
        ipc_backend = IPCBackend()
        if ipc_backend.connect():
            USE_IPC_BACKEND = True
            logger.info(f"✓ Using IPC backend - real-time UI sync enabled!")
            logger.info(f"  KiCAD version: {ipc_backend.get_version()}")
        else:
            logger.info("IPC backend available but KiCAD not running with IPC enabled")
            ipc_backend = None
    except ImportError:
        logger.info("IPC backend not available (kicad-python not installed)")
    except Exception as e:
        logger.info(f"IPC backend connection failed: {e}")
        ipc_backend = None

# Fall back to SWIG backend if IPC not available
if not USE_IPC_BACKEND and KICAD_BACKEND != "ipc":
    # Import KiCAD's Python API (SWIG)
    try:
        logger.info("Attempting to import pcbnew module (SWIG backend)...")
        import pcbnew  # type: ignore

        logger.info(f"Successfully imported pcbnew module from: {pcbnew.__file__}")
        logger.info(f"pcbnew version: {pcbnew.GetBuildVersion()}")
        logger.warning("Using SWIG backend - changes require manual reload in KiCAD UI")
    except ImportError as e:
        logger.error(f"Failed to import pcbnew module: {e}")
        logger.error(f"Current sys.path: {sys.path}")

        # Platform-specific help message
        help_message = ""
        if sys.platform == "win32":
            help_message = """
Windows Troubleshooting:
1. Verify KiCAD is installed: C:\\Program Files\\KiCad\\9.0
2. Check PYTHONPATH environment variable points to:
   C:\\Program Files\\KiCad\\9.0\\lib\\python3\\dist-packages
3. Test with: "C:\\Program Files\\KiCad\\9.0\\bin\\python.exe" -c "import pcbnew"
4. Log file location: %USERPROFILE%\\.kicad-mcp\\logs\\kicad_interface.log
5. Run setup-windows.ps1 for automatic configuration
"""
        elif sys.platform == "darwin":
            help_message = """
macOS Troubleshooting:
1. Verify KiCAD is installed: /Applications/KiCad/KiCad.app
2. Check PYTHONPATH points to KiCAD's Python packages
3. Run: python3 -c "import pcbnew" to test
"""
        else:  # Linux
            help_message = """
Linux Troubleshooting:
1. Verify KiCAD is installed: apt list --installed | grep kicad
2. Check: /usr/lib/kicad/lib/python3/dist-packages exists
3. Test: python3 -c "import pcbnew"
"""

        logger.error(help_message)

        error_response = {
            "success": False,
            "message": "Failed to import pcbnew module - KiCAD Python API not found",
            "errorDetails": f"Error: {str(e)}\n\n{help_message}\n\nPython sys.path:\n{chr(10).join(sys.path)}",
        }
        print(json.dumps(error_response))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error importing pcbnew: {e}")
        logger.error(traceback.format_exc())
        error_response = {
            "success": False,
            "message": "Error importing pcbnew module",
            "errorDetails": str(e),
        }
        print(json.dumps(error_response))
        sys.exit(1)

# If IPC-only mode requested but not available, exit with error
elif KICAD_BACKEND == "ipc" and not USE_IPC_BACKEND:
    error_response = {
        "success": False,
        "message": "IPC backend requested but not available",
        "errorDetails": "KiCAD must be running with IPC API enabled. Enable at: Preferences > Plugins > Enable IPC API Server",
    }
    print(json.dumps(error_response))
    sys.exit(1)

# Import command handlers
try:
    logger.info("Importing command handlers...")
    from commands.project import ProjectCommands
    from commands.board import BoardCommands
    from commands.component import ComponentCommands
    from commands.routing import RoutingCommands
    from commands.design_rules import DesignRuleCommands
    from commands.export import ExportCommands
    from commands.schematic import SchematicManager
    from commands.component_schematic import ComponentManager
    from commands.connection_schematic import ConnectionManager
    from commands.library_schematic import LibraryManager as SchematicLibraryManager
    from commands.library import (
        LibraryManager as FootprintLibraryManager,
        LibraryCommands,
    )
    from commands.library_symbol import SymbolLibraryManager, SymbolLibraryCommands
    from commands.jlcpcb import JLCPCBClient, test_jlcpcb_connection
    from commands.jlcpcb_parts import JLCPCBPartsManager
    from commands.datasheet_manager import DatasheetManager
    from commands.footprint import FootprintCreator
    from commands.symbol_creator import SymbolCreator
    from commands.freerouting import FreeroutingCommands

    logger.info("Successfully imported all command handlers")
except ImportError as e:
    logger.error(f"Failed to import command handlers: {e}")
    error_response = {
        "success": False,
        "message": "Failed to import command handlers",
        "errorDetails": str(e),
    }
    print(json.dumps(error_response))
    sys.exit(1)


def _point_on_wire_segment(px, py, wx1, wy1, wx2, wy2, tolerance=0.01):
    """Check if point (px,py) lies on wire segment (wx1,wy1)->(wx2,wy2).

    KiCad wires are strictly horizontal or vertical.
    Returns True if the point is on the segment (not just at endpoints).
    """
    px, py = float(px), float(py)
    wx1, wy1, wx2, wy2 = float(wx1), float(wy1), float(wx2), float(wy2)

    # Horizontal wire
    if abs(wy1 - wy2) < tolerance:
        if abs(py - wy1) < tolerance:
            min_x = min(wx1, wx2)
            max_x = max(wx1, wx2)
            if min_x - tolerance < px < max_x + tolerance:
                # Exclude exact endpoints (those are handled by normal endpoint matching)
                if abs(px - wx1) > tolerance and abs(px - wx2) > tolerance:
                    return True

    # Vertical wire
    if abs(wx1 - wx2) < tolerance:
        if abs(px - wx1) < tolerance:
            min_y = min(wy1, wy2)
            max_y = max(wy1, wy2)
            if min_y - tolerance < py < max_y + tolerance:
                if abs(py - wy1) > tolerance and abs(py - wy2) > tolerance:
                    return True

    return False


def _find_connected_wires(px, py, wires, tolerance=0.01):
    """Find all wires connected to point (px,py), including T-junctions.

    Args:
        px, py: Point coordinates.
        wires: List of (x1, y1, x2, y2) tuples.
        tolerance: Matching tolerance in mm.

    Returns list of (wire_index, 'start'|'end'|'mid') tuples indicating
    which wires connect and at which position.
    """
    px, py = float(px), float(py)
    connections = []
    for i, wire in enumerate(wires):
        x1, y1 = float(wire[0]), float(wire[1])
        x2, y2 = float(wire[2]), float(wire[3])

        # Endpoint match
        if abs(px - x1) < tolerance and abs(py - y1) < tolerance:
            connections.append((i, 'start'))
        elif abs(px - x2) < tolerance and abs(py - y2) < tolerance:
            connections.append((i, 'end'))
        # T-junction: point on middle of wire
        elif _point_on_wire_segment(px, py, x1, y1, x2, y2, tolerance):
            connections.append((i, 'mid'))

    return connections


class KiCADInterface:
    """Main interface class to handle KiCAD operations"""

    def __init__(self):
        """Initialize the interface and command handlers"""
        self.board = None
        self.project_filename = None
        self.use_ipc = USE_IPC_BACKEND
        self.ipc_backend = ipc_backend
        self.ipc_board_api = None

        if self.use_ipc:
            logger.info("Initializing with IPC backend (real-time UI sync enabled)")
            try:
                self.ipc_board_api = self.ipc_backend.get_board()
                logger.info("✓ Got IPC board API")
            except Exception as e:
                logger.warning(f"Could not get IPC board API: {e}")
        else:
            logger.info("Initializing with SWIG backend")

        logger.info("Initializing command handlers...")

        # Initialize footprint library manager
        self.footprint_library = FootprintLibraryManager()

        # Initialize command handlers
        self.project_commands = ProjectCommands(self.board)
        self.board_commands = BoardCommands(self.board)
        self.component_commands = ComponentCommands(self.board, self.footprint_library)
        self.routing_commands = RoutingCommands(self.board)
        self.design_rule_commands = DesignRuleCommands(self.board)
        self.export_commands = ExportCommands(self.board)
        self.library_commands = LibraryCommands(self.footprint_library)
        self._current_project_path: Optional[Path] = None  # set when boardPath is known

        # Initialize symbol library manager (for searching local KiCad symbol libraries)
        self.symbol_library_commands = SymbolLibraryCommands()

        # Initialize JLCPCB API integration
        self.jlcpcb_client = JLCPCBClient()  # Official API (requires auth)
        from commands.jlcsearch import JLCSearchClient

        self.jlcsearch_client = JLCSearchClient()  # Public API (no auth required)
        self.jlcpcb_parts = JLCPCBPartsManager()

        # Initialize Freerouting integration
        self.freerouting_commands = FreeroutingCommands(self.board)

        # Schematic-related classes don't need board reference
        # as they operate directly on schematic files

        # Shared PinLocator instance (preserves pin definition cache across calls)
        from commands.pin_locator import PinLocator
        self.pin_locator = PinLocator()

        # Command routing dictionary
        self.command_routes = {
            # Project commands
            "create_project": self.project_commands.create_project,
            "open_project": self.project_commands.open_project,
            "save_project": self.project_commands.save_project,
            "snapshot_project": self._handle_snapshot_project,
            "get_project_info": self.project_commands.get_project_info,
            # Board commands
            "set_board_size": self.board_commands.set_board_size,
            "add_layer": self.board_commands.add_layer,
            "set_active_layer": self.board_commands.set_active_layer,
            "get_board_info": self.board_commands.get_board_info,
            "get_layer_list": self.board_commands.get_layer_list,
            "get_board_2d_view": self.board_commands.get_board_2d_view,
            "get_board_extents": self.board_commands.get_board_extents,
            "add_board_outline": self.board_commands.add_board_outline,
            "add_mounting_hole": self.board_commands.add_mounting_hole,
            "add_text": self.board_commands.add_text,
            "add_board_text": self.board_commands.add_text,  # Alias for TypeScript tool
            # Component commands
            "route_pad_to_pad": self.routing_commands.route_pad_to_pad,
            "place_component": self._handle_place_component,
            "move_component": self.component_commands.move_component,
            "rotate_component": self.component_commands.rotate_component,
            "delete_component": self.component_commands.delete_component,
            "edit_component": self.component_commands.edit_component,
            "get_component_properties": self.component_commands.get_component_properties,
            "get_component_list": self.component_commands.get_component_list,
            "find_component": self.component_commands.find_component,
            "get_component_pads": self.component_commands.get_component_pads,
            "get_pad_position": self.component_commands.get_pad_position,
            "place_component_array": self.component_commands.place_component_array,
            "align_components": self.component_commands.align_components,
            "duplicate_component": self.component_commands.duplicate_component,
            # Routing commands
            "add_net": self.routing_commands.add_net,
            "route_trace": self.routing_commands.route_trace,
            "add_via": self.routing_commands.add_via,
            "delete_trace": self.routing_commands.delete_trace,
            "query_traces": self.routing_commands.query_traces,
            "modify_trace": self.routing_commands.modify_trace,
            "copy_routing_pattern": self.routing_commands.copy_routing_pattern,
            "get_nets_list": self.routing_commands.get_nets_list,
            "create_netclass": self.routing_commands.create_netclass,
            "add_copper_pour": self.routing_commands.add_copper_pour,
            "add_zone": self.routing_commands.add_copper_pour,  # alias — same implementation
            "route_differential_pair": self.routing_commands.route_differential_pair,
            "refill_zones": self._handle_refill_zones,
            # Design rule commands
            "set_design_rules": self.design_rule_commands.set_design_rules,
            "get_design_rules": self.design_rule_commands.get_design_rules,
            "run_drc": self.design_rule_commands.run_drc,
            "get_drc_violations": self.design_rule_commands.get_drc_violations,
            "add_net_class": self.routing_commands.create_netclass,  # alias
            "assign_net_to_class": self._handle_assign_net_to_class,
            "set_layer_constraints": self._handle_set_layer_constraints,
            "check_clearance": self._handle_check_clearance,
            # Component annotation/grouping
            "add_component_annotation": self._handle_add_component_annotation,
            "group_components": self._handle_group_components,
            "replace_component": self._handle_replace_component,
            # Export commands
            "export_gerber": self.export_commands.export_gerber,
            "export_pdf": self.export_commands.export_pdf,
            "export_svg": self.export_commands.export_svg,
            "export_3d": self.export_commands.export_3d,
            "export_bom": self.export_commands.export_bom,
            "export_netlist": self._handle_export_netlist,
            "export_position_file": self._handle_export_position_file,
            "export_vrml": self._handle_export_vrml,
            # Library commands (footprint management)
            "list_libraries": self.library_commands.list_libraries,
            "search_footprints": self.library_commands.search_footprints,
            "list_library_footprints": self.library_commands.list_library_footprints,
            "get_footprint_info": self.library_commands.get_footprint_info,
            # Symbol library commands (local KiCad symbol library search)
            "list_symbol_libraries": self.symbol_library_commands.list_symbol_libraries,
            "search_symbols": self.symbol_library_commands.search_symbols,
            "list_library_symbols": self.symbol_library_commands.list_library_symbols,
            "get_symbol_info": self.symbol_library_commands.get_symbol_info,
            # JLCPCB API commands (complete parts catalog via API)
            "download_jlcpcb_database": self._handle_download_jlcpcb_database,
            "search_jlcpcb_parts": self._handle_search_jlcpcb_parts,
            "get_jlcpcb_part": self._handle_get_jlcpcb_part,
            "get_jlcpcb_database_stats": self._handle_get_jlcpcb_database_stats,
            "suggest_jlcpcb_alternatives": self._handle_suggest_jlcpcb_alternatives,
            # Datasheet commands
            "enrich_datasheets": self._handle_enrich_datasheets,
            "get_datasheet_url": self._handle_get_datasheet_url,
            # Schematic commands
            "create_schematic": self._handle_create_schematic,
            "load_schematic": self._handle_load_schematic,
            "add_schematic_component": self._handle_add_schematic_component,
            "delete_schematic_component": self._handle_delete_schematic_component,
            "edit_schematic_component": self._handle_edit_schematic_component,
            "get_schematic_component": self._handle_get_schematic_component,
            "add_schematic_wire": self._handle_add_schematic_wire,
            "add_schematic_connection": self._handle_add_schematic_connection,
            "add_schematic_net_label": self._handle_add_schematic_net_label,
            "connect_to_net": self._handle_connect_to_net,
            "connect_passthrough": self._handle_connect_passthrough,
            "get_schematic_pin_locations": self._handle_get_schematic_pin_locations,
            "get_net_connections": self._handle_get_net_connections,
            "run_erc": self._handle_run_erc,
            "generate_netlist": self._handle_generate_netlist,
            "sync_schematic_to_board": self._handle_sync_schematic_to_board,
            "list_schematic_libraries": self._handle_list_schematic_libraries,
            "get_schematic_view": self._handle_get_schematic_view,
            "list_schematic_components": self._handle_list_schematic_components,
            "list_schematic_nets": self._handle_list_schematic_nets,
            "list_schematic_wires": self._handle_list_schematic_wires,
            "list_schematic_labels": self._handle_list_schematic_labels,
            "move_schematic_component": self._handle_move_schematic_component,
            "move_connected": self._handle_move_connected,
            "rotate_schematic_component": self._handle_rotate_schematic_component,
            "annotate_schematic": self._handle_annotate_schematic,
            "delete_schematic_wire": self._handle_delete_schematic_wire,
            "batch_delete_schematic_wire": self._handle_batch_delete_schematic_wire,
            "delete_schematic_net_label": self._handle_delete_schematic_net_label,
            "delete_no_connect": self._handle_delete_no_connect,
            "batch_delete_no_connect": self._handle_batch_delete_no_connect,
            "export_schematic_pdf": self._handle_export_schematic_pdf,
            "export_schematic_svg": self._handle_export_schematic_svg,
            "import_svg_logo": self._handle_import_svg_logo,
            # New batch/power tools
            "add_power_symbol": self._handle_add_power_symbol,
            "batch_connect_to_net": self._handle_batch_connect_to_net,
            "bulk_move_schematic_components": self._handle_bulk_move_schematic_components,
            "batch_get_schematic_pin_locations": self._handle_batch_get_schematic_pin_locations,
            "move_region": self._handle_move_region,
            "batch_add_wire": self._handle_batch_add_wire,
            "get_connected_items": self._handle_get_connected_items,
            "batch_delete": self._handle_batch_delete,
            "move_labels_by_offset": self._handle_move_labels_by_offset,
            "batch_edit_schematic_components": self._handle_batch_edit_schematic_components,
            "batch_delete_schematic_components": self._handle_batch_delete_schematic_components,
            "add_no_connect": self._handle_add_no_connect,
            "add_junction": self._handle_add_junction,
            "batch_add_junction": self._handle_batch_add_junction,
            "add_schematic_text": self._handle_add_schematic_text,
            "rotate_schematic_label": self._handle_rotate_schematic_label,
            "batch_rotate_labels": self._handle_batch_rotate_labels,
            "find_orphan_items": self._handle_find_orphan_items,
            "check_schematic_overlaps": self._handle_check_schematic_overlaps,
            "get_schematic_layout": self._handle_get_schematic_layout,
            "get_pin_connections": self._handle_get_pin_connections,
            "get_net_connectivity": self._handle_get_net_connectivity,
            "validate_wire_connections": self._handle_validate_wire_connections,
            "trace_from_point": self._handle_trace_from_point,
            "split_wire_at_point": self._handle_split_wire_at_point,
            # Net analysis commands
            "get_component_nets": self._handle_get_component_nets,
            "get_net_components": self._handle_get_net_components,
            "get_pin_net_name": self._handle_get_pin_net_name,
            "export_netlist_summary": self._handle_export_netlist_summary,
            "validate_component_connections": self._handle_validate_component_connections,
            "find_shorted_nets": self._handle_find_shorted_nets,
            "find_single_pin_nets": self._handle_find_single_pin_nets,
            "fix_connectivity": self._handle_fix_connectivity,
            # UI/Process management commands
            "check_kicad_ui": self._handle_check_kicad_ui,
            "launch_kicad_ui": self._handle_launch_kicad_ui,
            # Freerouting autoroute commands
            "autoroute": self.freerouting_commands.autoroute,
            "export_dsn": self.freerouting_commands.export_dsn,
            "import_ses": self.freerouting_commands.import_ses,
            "check_freerouting": self.freerouting_commands.check_freerouting,
            # IPC-specific commands (real-time operations)
            "get_backend_info": self._handle_get_backend_info,
            "ipc_add_track": self._handle_ipc_add_track,
            "ipc_add_via": self._handle_ipc_add_via,
            "ipc_add_text": self._handle_ipc_add_text,
            "ipc_list_components": self._handle_ipc_list_components,
            "ipc_get_tracks": self._handle_ipc_get_tracks,
            "ipc_get_vias": self._handle_ipc_get_vias,
            "ipc_save_board": self._handle_ipc_save_board,
            # Footprint commands
            "create_footprint": self._handle_create_footprint,
            "edit_footprint_pad": self._handle_edit_footprint_pad,
            "list_footprint_libraries": self._handle_list_footprint_libraries,
            "register_footprint_library": self._handle_register_footprint_library,
            # Symbol creator commands
            "create_symbol": self._handle_create_symbol,
            "delete_symbol": self._handle_delete_symbol,
            "list_symbols_in_library": self._handle_list_symbols_in_library,
            "register_symbol_library": self._handle_register_symbol_library,
        }

        logger.info(
            f"KiCAD interface initialized (backend: {'IPC' if self.use_ipc else 'SWIG'})"
        )

    # Commands that can be handled via IPC for real-time updates
    IPC_CAPABLE_COMMANDS = {
        # Routing commands
        "route_trace": "_ipc_route_trace",
        "add_via": "_ipc_add_via",
        "add_net": "_ipc_add_net",
        "delete_trace": "_ipc_delete_trace",
        "get_nets_list": "_ipc_get_nets_list",
        # Zone commands
        "add_copper_pour": "_ipc_add_copper_pour",
        "refill_zones": "_ipc_refill_zones",
        # Board commands
        "add_text": "_ipc_add_text",
        "add_board_text": "_ipc_add_text",
        "set_board_size": "_ipc_set_board_size",
        "get_board_info": "_ipc_get_board_info",
        "add_board_outline": "_ipc_add_board_outline",
        "add_mounting_hole": "_ipc_add_mounting_hole",
        "get_layer_list": "_ipc_get_layer_list",
        # Component commands
        "place_component": "_ipc_place_component",
        "move_component": "_ipc_move_component",
        "rotate_component": "_ipc_rotate_component",
        "delete_component": "_ipc_delete_component",
        "get_component_list": "_ipc_get_component_list",
        "get_component_properties": "_ipc_get_component_properties",
        # Save command
        "save_project": "_ipc_save_project",
    }

    def handle_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route command to appropriate handler, preferring IPC when available"""
        logger.info(f"Handling command: {command}")
        logger.debug(f"Command parameters: {params}")

        try:
            # Check if we can use IPC for this command (real-time UI sync)
            if (
                self.use_ipc
                and self.ipc_board_api
                and command in self.IPC_CAPABLE_COMMANDS
            ):
                ipc_handler_name = self.IPC_CAPABLE_COMMANDS[command]
                ipc_handler = getattr(self, ipc_handler_name, None)

                if ipc_handler:
                    logger.info(f"Using IPC backend for {command} (real-time sync)")
                    result = ipc_handler(params)

                    # Add indicator that IPC was used
                    if isinstance(result, dict):
                        result["_backend"] = "ipc"
                        result["_realtime"] = True

                    logger.debug(f"IPC command result: {result}")
                    return result

            # Fall back to SWIG-based handler
            if self.use_ipc and command in self.IPC_CAPABLE_COMMANDS:
                logger.warning(
                    f"IPC handler not available for {command}, falling back to SWIG (deprecated)"
                )

            # Get the handler for the command
            handler = self.command_routes.get(command)

            if handler:
                # Execute the command
                result = handler(params)
                logger.debug(f"Command result: {result}")

                # Add backend indicator
                if isinstance(result, dict):
                    result["_backend"] = "swig"
                    result["_realtime"] = False

                # Update board reference if command was successful
                if result.get("success", False):
                    if command == "create_project" or command == "open_project":
                        logger.info("Updating board reference...")
                        # Get board from the project commands handler
                        self.board = self.project_commands.board
                        self._update_command_handlers()
                    elif command in self._BOARD_MUTATING_COMMANDS:
                        # Auto-save after every board mutation via SWIG.
                        # Prevents data loss if Claude hits context limit before
                        # an explicit save_project call.
                        self._auto_save_board()

                return result
            else:
                logger.error(f"Unknown command: {command}")
                return {
                    "success": False,
                    "message": f"Unknown command: {command}",
                    "errorDetails": "The specified command is not supported",
                }

        except Exception as e:
            # Get the full traceback
            traceback_str = traceback.format_exc()
            logger.error(f"Error handling command {command}: {str(e)}\n{traceback_str}")
            return {
                "success": False,
                "message": f"Error handling command: {command}",
                "errorDetails": f"{str(e)}\n{traceback_str}",
            }

    # Board-mutating commands that trigger auto-save on SWIG path
    _BOARD_MUTATING_COMMANDS = {
        "place_component",
        "move_component",
        "rotate_component",
        "delete_component",
        "route_trace",
        "route_pad_to_pad",
        "add_via",
        "delete_trace",
        "add_net",
        "add_board_outline",
        "add_mounting_hole",
        "add_text",
        "add_board_text",
        "add_copper_pour",
        "refill_zones",
        "import_svg_logo",
        "sync_schematic_to_board",
        "connect_passthrough",
    }

    def _auto_save_board(self):
        """Save board to disk after SWIG mutations.
        Called automatically after every board-mutating SWIG command so that
        data is not lost if Claude hits the context limit before save_project.
        """
        try:
            if self.board:
                board_path = self.board.GetFileName()
                if board_path:
                    pcbnew.SaveBoard(board_path, self.board)
                    logger.debug(f"Auto-saved board to: {board_path}")
        except Exception as e:
            logger.warning(f"Auto-save failed: {e}")

    def _update_command_handlers(self):
        """Update board reference in all command handlers"""
        logger.debug("Updating board reference in command handlers")
        self.project_commands.board = self.board
        self.board_commands.board = self.board
        self.component_commands.board = self.board
        self.routing_commands.board = self.board
        self.design_rule_commands.board = self.board
        self.export_commands.board = self.board
        self.freerouting_commands.board = self.board

    # Schematic command handlers
    def _handle_create_schematic(self, params):
        """Create a new schematic"""
        logger.info("Creating schematic")
        try:
            # Support multiple parameter naming conventions for compatibility:
            # - TypeScript tools use: name, path
            # - Python schema uses: filename, title
            # - Legacy uses: projectName, path, metadata
            project_name = (
                params.get("projectName") or params.get("name") or params.get("title")
            )

            # Handle filename parameter - it may contain full path
            filename = params.get("filename")
            if filename:
                # If filename provided, extract name and path from it
                if filename.endswith(".kicad_sch"):
                    filename = filename[:-10]  # Remove .kicad_sch extension
                path = os.path.dirname(filename) or "."
                project_name = project_name or os.path.basename(filename)
            else:
                path = params.get("path", ".")
            metadata = params.get("metadata", {})

            if not project_name:
                return {
                    "success": False,
                    "message": "Schematic name is required. Provide 'name', 'projectName', or 'filename' parameter.",
                }

            schematic = SchematicManager.create_schematic(project_name, metadata)
            file_path = f"{path}/{project_name}.kicad_sch"
            success = SchematicManager.save_schematic(schematic, file_path)

            # Apply paper/sheet size if specified
            paper_size = params.get("paperSize")
            if paper_size and success:
                try:
                    import re
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    # Replace (paper "A4") or similar with the requested size
                    content = re.sub(
                        r'\(paper\s+"[^"]*"\)',
                        f'(paper "{paper_size}")',
                        content,
                    )
                    with open(file_path, "w", encoding="utf-8", newline="\n") as f:
                        f.write(content)
                        f.flush()
                        os.fsync(f.fileno())
                    logger.info(f"Set paper size to {paper_size}")
                except Exception as paper_err:
                    logger.warning(f"Failed to set paper size: {paper_err}")

            return {"success": success, "file_path": file_path}
        except Exception as e:
            logger.error(f"Error creating schematic: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_load_schematic(self, params):
        """Load an existing schematic"""
        logger.info("Loading schematic")
        try:
            filename = params.get("filename")

            if not filename:
                return {"success": False, "message": "Filename is required"}

            schematic = SchematicManager.load_schematic(filename)
            success = schematic is not None

            if success:
                metadata = SchematicManager.get_schematic_metadata(schematic)
                return {"success": success, "metadata": metadata}
            else:
                return {"success": False, "message": "Failed to load schematic"}
        except Exception as e:
            logger.error(f"Error loading schematic: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_place_component(self, params):
        """Place a component on the PCB, with project-local fp-lib-table support.
        If boardPath is given and differs from the currently loaded board, the
        board is reloaded from boardPath before placing — prevents silent failures
        when Claude provides a boardPath that was not yet loaded.
        """
        from pathlib import Path

        board_path = params.get("boardPath")
        if board_path:
            board_path_norm = str(Path(board_path).resolve())
            current_board_file = (
                str(Path(self.board.GetFileName()).resolve()) if self.board else ""
            )
            if board_path_norm != current_board_file:
                logger.info(
                    f"boardPath differs from current board — reloading: {board_path}"
                )
                try:
                    self.board = pcbnew.LoadBoard(board_path)
                    self._update_command_handlers()
                    logger.info("Board reloaded from boardPath")
                except Exception as e:
                    logger.error(f"Failed to reload board from boardPath: {e}")
                    return {
                        "success": False,
                        "message": f"Could not load board from boardPath: {board_path}",
                        "errorDetails": str(e),
                    }

            project_path = Path(board_path).parent
            if project_path != getattr(self, "_current_project_path", None):
                self._current_project_path = project_path
                local_lib = FootprintLibraryManager(project_path=project_path)
                self.component_commands = ComponentCommands(self.board, local_lib)
                logger.info(
                    f"Reloaded FootprintLibraryManager with project_path={project_path}"
                )

        return self.component_commands.place_component(params)

    def _handle_add_schematic_component(self, params):
        """Add a component to a schematic using text-based injection (no sexpdata)"""
        logger.info("Adding component to schematic")
        try:
            from pathlib import Path
            from commands.dynamic_symbol_loader import DynamicSymbolLoader

            schematic_path = params.get("schematicPath")
            component = params.get("component", {})

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not component:
                return {"success": False, "message": "Component definition is required"}

            comp_type = component.get("type", "R")
            library = component.get("library", "Device")
            reference = component.get("reference", "X?")
            value = component.get("value", comp_type)
            footprint = component.get("footprint", "")
            x = component.get("x", 0)
            y = component.get("y", 0)
            rotation = component.get("rotation", 0)

            # Derive project path from schematic path for project-local library resolution
            schematic_file = Path(schematic_path)
            derived_project_path = schematic_file.parent

            loader = DynamicSymbolLoader(project_path=derived_project_path)
            loader.add_component(
                schematic_file,
                library,
                comp_type,
                reference=reference,
                value=value,
                footprint=footprint,
                x=x,
                y=y,
                rotation=rotation,
                project_path=derived_project_path,
            )

            return {
                "success": True,
                "component_reference": reference,
                "symbol_source": f"{library}:{comp_type}",
            }
        except Exception as e:
            logger.error(f"Error adding component to schematic: {str(e)}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    @staticmethod
    def _delete_component_from_content(content, reference):
        """Remove a placed symbol from schematic content string by reference.
        Returns (modified_content, deleted_count) or (None, 0) if not found."""
        import re

        def find_matching_paren(s, start):
            depth = 0
            i = start
            while i < len(s):
                if s[i] == "(":
                    depth += 1
                elif s[i] == ")":
                    depth -= 1
                    if depth == 0:
                        return i
                i += 1
            return -1

        lib_sym_pos = content.find("(lib_symbols")
        lib_sym_end = (
            find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1
        )

        blocks_to_delete = []
        search_start = 0
        pattern = re.compile(r'\(symbol\s+\(lib_id\s+"')
        while True:
            m = pattern.search(content, search_start)
            if not m:
                break
            pos = m.start()
            if lib_sym_pos >= 0 and lib_sym_pos <= pos <= lib_sym_end:
                search_start = lib_sym_end + 1
                continue
            end = find_matching_paren(content, pos)
            if end < 0:
                search_start = pos + 1
                continue
            block_text = content[pos : end + 1]
            if re.search(
                r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"',
                block_text,
            ):
                blocks_to_delete.append((pos, end))
            search_start = end + 1

        if not blocks_to_delete:
            return None, 0

        for b_start, b_end in sorted(blocks_to_delete, reverse=True):
            trim_start = b_start
            while trim_start > 0 and content[trim_start - 1] in (" ", "\t"):
                trim_start -= 1
            if trim_start > 0 and content[trim_start - 1] == "\n":
                trim_start -= 1
            content = content[:trim_start] + content[b_end + 1:]

        return content, len(blocks_to_delete)

    def _handle_delete_schematic_component(self, params):
        """Remove a placed symbol from a schematic using text-based manipulation (no skip writes)"""
        logger.info("Deleting schematic component")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            content, deleted_count = self._delete_component_from_content(content, reference)
            if content is None:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic (note: this tool removes schematic symbols, use delete_component for PCB footprints)",
                }

            with open(sch_file, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            logger.info(
                f"Deleted {deleted_count} instance(s) of {reference} from {sch_file.name}"
            )
            return {
                "success": True,
                "reference": reference,
                "deleted_count": deleted_count,
                "schematic": str(sch_file),
            }

        except Exception as e:
            logger.error(f"Error deleting schematic component: {e}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    @staticmethod
    def _edit_component_in_content(content, reference, new_footprint=None, new_value=None,
                                    new_reference=None, field_positions=None, hidden_fields=None):
        """Edit a component's properties within schematic content string.
        Returns modified content, or None if component not found."""
        import re

        def find_matching_paren(s, start):
            depth = 0
            i = start
            while i < len(s):
                if s[i] == "(":
                    depth += 1
                elif s[i] == ")":
                    depth -= 1
                    if depth == 0:
                        return i
                i += 1
            return -1

        lib_sym_pos = content.find("(lib_symbols")
        lib_sym_end = (
            find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1
        )

        block_start = block_end = None
        search_start = 0
        pattern = re.compile(r'\(symbol\s+\(lib_id\s+"')
        while True:
            m = pattern.search(content, search_start)
            if not m:
                break
            pos = m.start()
            if lib_sym_pos >= 0 and lib_sym_pos <= pos <= lib_sym_end:
                search_start = lib_sym_end + 1
                continue
            end = find_matching_paren(content, pos)
            if end < 0:
                search_start = pos + 1
                continue
            block_text = content[pos : end + 1]
            if re.search(
                r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"',
                block_text,
            ):
                block_start, block_end = pos, end
                break
            search_start = end + 1

        if block_start is None:
            return None

        block_text = content[block_start : block_end + 1]
        if new_footprint is not None:
            block_text = re.sub(
                r'(\(property\s+"Footprint"\s+)"[^"]*"',
                rf'\1"{new_footprint}"',
                block_text,
            )
        if new_value is not None:
            block_text = re.sub(
                r'(\(property\s+"Value"\s+)"[^"]*"', rf'\1"{new_value}"', block_text
            )
        if new_reference is not None:
            block_text = re.sub(
                r'(\(property\s+"Reference"\s+)"[^"]*"',
                rf'\1"{new_reference}"',
                block_text,
            )
        if field_positions is not None:
            for field_name, pos in field_positions.items():
                x = pos.get("x", 0)
                y = pos.get("y", 0)
                angle = pos.get("angle", 0)
                block_text = re.sub(
                    r'(\(property\s+"'
                    + re.escape(field_name)
                    + r'"\s+"[^"]*"\s+)\(at\s+[\d\.\-]+\s+[\d\.\-]+\s+[\d\.\-]+\s*\)',
                    rf"\1(at {x} {y} {angle})",
                    block_text,
                )

        if hidden_fields is not None:
            for field_name, should_hide in hidden_fields.items():
                prop_start = block_text.find(f'(property "{field_name}"')
                if prop_start < 0:
                    continue

                depth = 0
                pi = prop_start
                while pi < len(block_text):
                    if block_text[pi] == "(": depth += 1
                    elif block_text[pi] == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    pi += 1
                prop_block = block_text[prop_start:pi + 1]

                clean = re.sub(r'\s*\(hide\s+yes\)', '', prop_block)
                clean = re.sub(r'\)\s+hide\b', ')', clean)
                clean = re.sub(r'  +', ' ', clean)

                if should_hide:
                    effects_pos = clean.find('(effects')
                    if effects_pos >= 0:
                        ed = effects_pos
                        edepth = 0
                        while ed < len(clean):
                            if clean[ed] == "(": edepth += 1
                            elif clean[ed] == ")":
                                edepth -= 1
                                if edepth == 0:
                                    break
                            ed += 1
                        clean = clean[:ed] + " (hide yes)" + clean[ed:]

                block_text = block_text[:prop_start] + clean + block_text[pi + 1:]

        return content[:block_start] + block_text + content[block_end + 1:]

    def _handle_edit_schematic_component(self, params):
        """Update properties of a placed symbol in a schematic (footprint, value, reference).
        Uses text-based in-place editing – preserves position, UUID and all other fields.
        """
        logger.info("Editing schematic component")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            new_footprint = params.get("footprint")
            new_value = params.get("value")
            new_reference = params.get("newReference")
            field_positions = params.get("fieldPositions")
            hidden_fields = params.get("hiddenFields")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}
            if not any(
                [
                    new_footprint is not None,
                    new_value is not None,
                    new_reference is not None,
                    field_positions is not None,
                    hidden_fields is not None,
                ]
            ):
                return {
                    "success": False,
                    "message": "At least one of footprint, value, newReference, fieldPositions, or hiddenFields must be provided",
                }

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            result = self._edit_component_in_content(
                content, reference, new_footprint, new_value,
                new_reference, field_positions, hidden_fields,
            )
            if result is None:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic",
                }

            with open(sch_file, "w", encoding="utf-8") as f:
                f.write(result)
                f.flush()
                os.fsync(f.fileno())

            changes = {
                k: v
                for k, v in {
                    "footprint": new_footprint,
                    "value": new_value,
                    "reference": new_reference,
                }.items()
                if v is not None
            }
            if field_positions is not None:
                changes["fieldPositions"] = field_positions
            if hidden_fields is not None:
                changes["hiddenFields"] = hidden_fields
            logger.info(f"Edited schematic component {reference}: {changes}")
            return {"success": True, "reference": reference, "updated": changes}

        except Exception as e:
            logger.error(f"Error editing schematic component: {e}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_batch_edit_schematic_components(self, params):
        """Apply the same field edits to multiple components in one call. Single read/write cycle.

        Useful for bulk operations like hiding Reference on all power symbols.
        """
        logger.info("Batch editing schematic components")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            references = params.get("references", [])
            edits = params.get("edits", {})

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not references:
                return {"success": False, "message": "references array is required"}
            if not edits:
                return {"success": False, "message": "edits object is required"}

            sch_file = Path(schematic_path)
            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            results = {"edited": [], "failed": []}
            for ref in references:
                result = self._edit_component_in_content(
                    content, ref,
                    new_footprint=edits.get("footprint"),
                    new_value=edits.get("value"),
                    new_reference=edits.get("newReference"),
                    field_positions=edits.get("fieldPositions"),
                    hidden_fields=edits.get("hiddenFields"),
                )
                if result is not None:
                    content = result
                    results["edited"].append(ref)
                else:
                    results["failed"].append(f"{ref}: not found")

            with open(sch_file, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            n_ok = len(results["edited"])
            n_fail = len(results["failed"])
            return {
                "success": n_fail == 0,
                "message": f"Batch edit: {n_ok} edited, {n_fail} failed",
                "edited": results["edited"],
                "failed": results["failed"],
            }

        except Exception as e:
            logger.error(f"Error in batch_edit_schematic_components: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_add_no_connect(self, params):
        """Add a no-connect (X) flag at a position, typically on an unused pin."""
        logger.info("Adding no-connect flag")
        try:
            from pathlib import Path
            from commands.sexp_writer import add_no_connect

            schematic_path = params.get("schematicPath")
            position = params.get("position", {})

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            x = position.get("x", 0) if isinstance(position, dict) else 0
            y = position.get("y", 0) if isinstance(position, dict) else 0

            success = add_no_connect(Path(schematic_path), [x, y])
            if success:
                return {"success": True, "message": f"Added no-connect at ({x}, {y})"}
            return {"success": False, "message": "Failed to add no-connect"}
        except Exception as e:
            logger.error(f"Error adding no-connect: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_add_junction(self, params):
        """Add a junction dot at a position (T-connections on wires)."""
        logger.info("Adding junction")
        try:
            from pathlib import Path
            from commands.sexp_writer import add_junction

            schematic_path = params.get("schematicPath")
            position = params.get("position", {})

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            x = position.get("x", 0) if isinstance(position, dict) else position[0]
            y = position.get("y", 0) if isinstance(position, dict) else position[1]
            diameter = float(params.get("diameter", 0))

            success = add_junction(Path(schematic_path), [x, y], diameter=diameter)
            if success:
                return {"success": True, "message": f"Added junction at ({x}, {y})"}
            return {"success": False, "message": "Failed to add junction"}
        except Exception as e:
            logger.error(f"Error adding junction: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_batch_add_junction(self, params):
        """Add multiple junction dots in one call. Single read/write cycle.
        Verifies each junction lies on a wire intersection and warns about misplacements."""
        logger.info("Batch adding junctions")
        try:
            import re
            from commands.sexp_writer import add_junction_to_content, _read_schematic, _write_schematic
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            positions = params.get("positions", [])

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not positions:
                return {"success": False, "message": "positions array is required"}

            content = _read_schematic(Path(schematic_path))

            # Collect junction positions for verification
            added_positions = []
            added = 0
            for pos in positions:
                x = pos.get("x", 0) if isinstance(pos, dict) else pos[0]
                y = pos.get("y", 0) if isinstance(pos, dict) else pos[1]
                content = add_junction_to_content(content, [x, y])
                added_positions.append((float(x), float(y)))
                added += 1

            _write_schematic(Path(schematic_path), content)

            # Verification: re-read file and parse wires to check junction placement
            verification_content = _read_schematic(Path(schematic_path))
            wire_segments = []
            wire_pat = re.compile(r'\(wire\b')
            xy_pat = re.compile(r'\(xy\s+([\d.e+-]+)\s+([\d.e+-]+)\)')
            for wm in wire_pat.finditer(verification_content):
                depth = 0
                i = wm.start()
                block_end = i
                while i < len(verification_content):
                    if verification_content[i] == '(':
                        depth += 1
                    elif verification_content[i] == ')':
                        depth -= 1
                        if depth == 0:
                            block_end = i + 1
                            break
                    i += 1
                block = verification_content[wm.start():block_end]
                xys = xy_pat.findall(block)
                if len(xys) >= 2:
                    wire_segments.append((
                        float(xys[0][0]), float(xys[0][1]),
                        float(xys[-1][0]), float(xys[-1][1]),
                    ))

            tolerance = 0.5
            warnings = []
            valid_placements = []
            for jx, jy in added_positions:
                on_wire = False
                for wx1, wy1, wx2, wy2 in wire_segments:
                    # Check endpoints
                    if (abs(jx - wx1) < tolerance and abs(jy - wy1) < tolerance) or \
                       (abs(jx - wx2) < tolerance and abs(jy - wy2) < tolerance):
                        on_wire = True
                        break
                    # Check mid-segment (T-junction)
                    if _point_on_wire_segment(jx, jy, wx1, wy1, wx2, wy2, tolerance):
                        on_wire = True
                        break
                if on_wire:
                    valid_placements.append({"x": jx, "y": jy})
                else:
                    warnings.append(f"Junction at ({jx}, {jy}) does not lie on any wire segment")

            result = {
                "success": True,
                "message": f"Added {added}/{len(positions)} junctions",
                "added": added,
                "failed": [],
                "valid_placements": len(valid_placements),
                "misplaced": len(warnings),
            }
            if warnings:
                result["warnings"] = warnings
            return result
        except Exception as e:
            logger.error(f"Error in batch_add_junction: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_batch_rotate_labels(self, params):
        """Rotate multiple labels in one call. Single read/write cycle."""
        logger.info("Batch rotating labels")
        try:
            import re

            schematic_path = params.get("schematicPath")
            rotations = params.get("rotations", [])

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not rotations:
                return {"success": False, "message": "rotations array is required"}

            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            tolerance = 0.5
            results = []
            justify_pat = re.compile(r'\(justify\s+\w+\)')

            for rot in rotations:
                net_name = rot.get("netName")
                angle = rot.get("angle", 0)
                position = rot.get("position")
                escaped = re.escape(net_name)
                found = False
                found_label_type = None
                label_x, label_y = 0.0, 0.0

                for label_type in ["label", "global_label", "hierarchical_label"]:
                    pat = re.compile(
                        rf'(\({label_type}\s+"{escaped}"(?:\s+\(shape\s+[^)]*\))?\s+\(at\s+)([\d.e+-]+)\s+([\d.e+-]+)\s+[\d.e+-]+'
                    )
                    for m in pat.finditer(content):
                        lx, ly = float(m.group(2)), float(m.group(3))
                        if position:
                            px = position.get("x", 0)
                            py = position.get("y", 0)
                            if abs(lx - px) >= tolerance or abs(ly - py) >= tolerance:
                                continue

                        old = m.group(0)
                        new = f"{m.group(1)}{m.group(2)} {m.group(3)} {angle}"
                        content = content.replace(old, new, 1)
                        found = True
                        found_label_type = label_type
                        label_x, label_y = lx, ly
                        break
                    if found:
                        break

                if not found:
                    results.append({"netName": net_name, "success": False, "message": "Not found"})
                    continue

                # Update justify
                norm_angle = int(angle) % 360
                new_justify = "right" if norm_angle in (180, 270) else "left"

                if found_label_type in ("global_label", "hierarchical_label"):
                    label_start_pat = re.compile(
                        rf'\({found_label_type}\s+"{escaped}"(?:\s+\(shape\s+[^)]*\))?\s+\(at\s+{re.escape(str(label_x))}\s+{re.escape(str(label_y))}\s+'
                    )
                    lm = label_start_pat.search(content)
                    if lm:
                        depth = 0
                        i = lm.start()
                        block_end = i
                        while i < len(content):
                            if content[i] == '(':
                                depth += 1
                            elif content[i] == ')':
                                depth -= 1
                                if depth == 0:
                                    block_end = i + 1
                                    break
                            i += 1
                        block = content[lm.start():block_end]

                        # Update justify in first (effects ...) block
                        effects_match = re.search(r'\(effects\b', block)
                        if effects_match:
                            ed = 0
                            ei = effects_match.start()
                            effects_end = ei
                            while ei < len(block):
                                if block[ei] == '(':
                                    ed += 1
                                elif block[ei] == ')':
                                    ed -= 1
                                    if ed == 0:
                                        effects_end = ei + 1
                                        break
                                ei += 1
                            effects_block = block[effects_match.start():effects_end]

                            if justify_pat.search(effects_block):
                                new_effects = justify_pat.sub(f'(justify {new_justify})', effects_block, count=1)
                            else:
                                insert_pos = effects_block.rfind(')')
                                indent = "\n\t\t\t" if "\n" in effects_block else " "
                                new_effects = effects_block[:insert_pos] + f'{indent}(justify {new_justify})' + effects_block[insert_pos:]

                            if new_effects != effects_block:
                                new_block = block[:effects_match.start()] + new_effects + block[effects_end:]
                                content = content[:lm.start()] + new_block + content[block_end:]

                        # Update Intersheetrefs position
                        char_w = 0.75
                        text_len = len(net_name) * char_w
                        total_w = 3.0 + text_len

                        if norm_angle == 0:
                            isr_x, isr_y = label_x, label_y
                        elif norm_angle == 180:
                            isr_x, isr_y = round(label_x - total_w, 4), label_y
                        elif norm_angle == 90:
                            isr_x, isr_y = label_x, label_y
                        else:
                            isr_x, isr_y = label_x, round(label_y - total_w, 4)

                        # Re-search (content may have changed)
                        lm2 = label_start_pat.search(content)
                        if lm2:
                            depth2 = 0
                            i2 = lm2.start()
                            block_end2 = i2
                            while i2 < len(content):
                                if content[i2] == '(':
                                    depth2 += 1
                                elif content[i2] == ')':
                                    depth2 -= 1
                                    if depth2 == 0:
                                        block_end2 = i2 + 1
                                        break
                                i2 += 1
                            block2 = content[lm2.start():block_end2]

                            isr_at_pat = re.compile(
                                r'(\(property\s+"Intersheetrefs"\s+"[^"]*"\s+\(at\s+)[\d.e+-]+\s+[\d.e+-]+\s+[\d.e+-]+'
                            )
                            isr_m = isr_at_pat.search(block2)
                            if isr_m:
                                old_isr = isr_m.group(0)
                                new_isr = f"{isr_m.group(1)}{isr_x} {isr_y} {angle}"
                                new_block2 = block2.replace(old_isr, new_isr, 1)

                                isr_prop_start = new_block2.find('(property "Intersheetrefs"')
                                if isr_prop_start >= 0:
                                    pd = 0
                                    pi = isr_prop_start
                                    prop_end = pi
                                    while pi < len(new_block2):
                                        if new_block2[pi] == '(':
                                            pd += 1
                                        elif new_block2[pi] == ')':
                                            pd -= 1
                                            if pd == 0:
                                                prop_end = pi + 1
                                                break
                                        pi += 1
                                    isr_prop = new_block2[isr_prop_start:prop_end]
                                    new_isr_prop = justify_pat.sub(f'(justify {new_justify})', isr_prop)
                                    if new_isr_prop != isr_prop:
                                        new_block2 = new_block2[:isr_prop_start] + new_isr_prop + new_block2[prop_end:]

                                content = content[:lm2.start()] + new_block2 + content[block_end2:]

                results.append({"netName": net_name, "success": True, "message": f"Rotated to {angle}° (justify {new_justify})"})

            with open(schematic_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            succeeded = sum(1 for r in results if r["success"])
            return {
                "success": True,
                "message": f"Rotated {succeeded}/{len(rotations)} labels",
                "results": results,
            }
        except Exception as e:
            logger.error(f"Error in batch_rotate_labels: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_net_connectivity(self, params):
        """Get everything connected to a named net: pins, labels, wires, power symbols."""
        logger.info("Getting net connectivity")
        try:
            import re
            import math
            from pathlib import Path
            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not net_name:
                return {"success": False, "message": "netName is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            sch_file = Path(schematic_path)
            locator = self.pin_locator

            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            # ── Collect label positions for this net ──
            labels = []
            for lt in ["label", "global_label", "hierarchical_label"]:
                escaped = re.escape(net_name)
                pat = re.compile(
                    rf'\({lt}\s+"{escaped}"(?:\s+\(shape\s+[^)]*\))?\s+\(at\s+([\d.e+-]+)\s+([\d.e+-]+)\s*([\d.e+-]*)'
                )
                for m in pat.finditer(content):
                    lx, ly = float(m.group(1)), float(m.group(2))
                    angle = float(m.group(3)) if m.group(3) else 0
                    labels.append({
                        "type": lt,
                        "at": [lx, ly],
                        "angle": angle,
                    })

            # ── Collect power symbols for this net ──
            power_labels = []
            if hasattr(schematic, "symbol"):
                for symbol in schematic.symbol:
                    if not hasattr(symbol.property, "Reference"):
                        continue
                    ref = symbol.property.Reference.value
                    if not ref.startswith("#PWR"):
                        continue
                    val = symbol.property.Value.value if hasattr(symbol.property, "Value") else ""
                    if val != net_name:
                        continue
                    pos = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                    power_labels.append({
                        "type": "power",
                        "reference": ref,
                        "at": [float(pos[0]), float(pos[1])],
                    })

            # ── All net points (label positions + power positions) ──
            net_points = set()
            for lb in labels:
                net_points.add((lb["at"][0], lb["at"][1]))
            for pw in power_labels:
                net_points.add((pw["at"][0], pw["at"][1]))

            # ── Collect ALL wires ──
            all_wires = []
            wire_pat = re.compile(r'\(wire\b')
            xy_pat = re.compile(r'\(xy\s+([\d.e+-]+)\s+([\d.e+-]+)\)')
            for wm in wire_pat.finditer(content):
                depth = 0
                i = wm.start()
                block_end = i
                while i < len(content):
                    if content[i] == '(':
                        depth += 1
                    elif content[i] == ')':
                        depth -= 1
                        if depth == 0:
                            block_end = i + 1
                            break
                    i += 1
                block = content[wm.start():block_end]
                xys = xy_pat.findall(block)
                if len(xys) >= 2:
                    all_wires.append((
                        float(xys[0][0]), float(xys[0][1]),
                        float(xys[-1][0]), float(xys[-1][1]),
                    ))

            # ── Find component pins that match net_points via wire tracing ──
            # Build wire adjacency: which points are connected by wires
            # Includes T-junction detection (point on mid-segment of another wire)
            eps = 0.5
            connected_points = set(net_points)
            changed = True
            while changed:
                changed = False
                for wx1, wy1, wx2, wy2 in all_wires:
                    p1 = (wx1, wy1)
                    p2 = (wx2, wy2)
                    p1_in = any(abs(p1[0] - cp[0]) < eps and abs(p1[1] - cp[1]) < eps for cp in connected_points)
                    p2_in = any(abs(p2[0] - cp[0]) < eps and abs(p2[1] - cp[1]) < eps for cp in connected_points)
                    if p1_in and not p2_in:
                        connected_points.add(p2)
                        changed = True
                    elif p2_in and not p1_in:
                        connected_points.add(p1)
                        changed = True
                    elif not p1_in and not p2_in:
                        # T-junction check: does any connected point land on this wire's mid-segment?
                        for cp in list(connected_points):
                            if _point_on_wire_segment(cp[0], cp[1], wx1, wy1, wx2, wy2, eps):
                                connected_points.add(p1)
                                connected_points.add(p2)
                                changed = True
                                break
                    # Also check: does either endpoint of this wire land on the mid-segment of
                    # any already-connected wire? (reverse T-junction direction)
                    if not p1_in:
                        for owx1, owy1, owx2, owy2 in all_wires:
                            if (owx1, owy1, owx2, owy2) == (wx1, wy1, wx2, wy2):
                                continue
                            o1_in = any(abs(owx1 - cp[0]) < eps and abs(owy1 - cp[1]) < eps for cp in connected_points)
                            o2_in = any(abs(owx2 - cp[0]) < eps and abs(owy2 - cp[1]) < eps for cp in connected_points)
                            if (o1_in or o2_in) and _point_on_wire_segment(p1[0], p1[1], owx1, owy1, owx2, owy2, eps):
                                connected_points.add(p1)
                                connected_points.add(p2)
                                changed = True
                                break
                    if not p2_in:
                        for owx1, owy1, owx2, owy2 in all_wires:
                            if (owx1, owy1, owx2, owy2) == (wx1, wy1, wx2, wy2):
                                continue
                            o1_in = any(abs(owx1 - cp[0]) < eps and abs(owy1 - cp[1]) < eps for cp in connected_points)
                            o2_in = any(abs(owx2 - cp[0]) < eps and abs(owy2 - cp[1]) < eps for cp in connected_points)
                            if (o1_in or o2_in) and _point_on_wire_segment(p2[0], p2[1], owx1, owy1, owx2, owy2, eps):
                                connected_points.add(p1)
                                connected_points.add(p2)
                                changed = True
                                break

            # ── Wires on this net ──
            net_wires = []
            for wx1, wy1, wx2, wy2 in all_wires:
                p1_in = any(abs(wx1 - cp[0]) < eps and abs(wy1 - cp[1]) < eps for cp in connected_points)
                p2_in = any(abs(wx2 - cp[0]) < eps and abs(wy2 - cp[1]) < eps for cp in connected_points)
                # Also check if any connected point lands on this wire mid-segment (T-junction)
                mid_hit = any(_point_on_wire_segment(cp[0], cp[1], wx1, wy1, wx2, wy2, eps) for cp in connected_points)
                if p1_in or p2_in or mid_hit:
                    net_wires.append({"start": [wx1, wy1], "end": [wx2, wy2]})

            # ── Component pins on this net ──
            pins = []
            if hasattr(schematic, "symbol"):
                for symbol in schematic.symbol:
                    if not hasattr(symbol.property, "Reference"):
                        continue
                    ref = symbol.property.Reference.value
                    if ref.startswith("_TEMPLATE") or ref.startswith("#PWR"):
                        continue
                    lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else ""
                    position = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                    sym_x, sym_y = float(position[0]), float(position[1])
                    sym_rot = float(position[2]) if len(position) > 2 else 0.0

                    mirror_x = False
                    mirror_y = False
                    if hasattr(symbol, "mirror"):
                        mirror_val = str(symbol.mirror.value) if hasattr(symbol.mirror, "value") else str(symbol.mirror)
                        mirror_x = "x" in mirror_val
                        mirror_y = "y" in mirror_val

                    pins_def = locator.get_symbol_pins(sch_file, lib_id)
                    if not pins_def:
                        continue

                    for pin_name, pd in pins_def.items():
                        import math as _math
                        pin_rel_x = pd["x"]
                        pin_rel_y = -pd["y"]  # Y-up to Y-down
                        if mirror_x:
                            pin_rel_y = -pin_rel_y
                        if mirror_y:
                            pin_rel_x = -pin_rel_x
                        rad = _math.radians(sym_rot)
                        cos_r, sin_r = _math.cos(rad), _math.sin(rad)
                        rot_x = pin_rel_x * cos_r - pin_rel_y * sin_r
                        rot_y = -pin_rel_x * sin_r + pin_rel_y * cos_r
                        pin_x = sym_x + rot_x
                        pin_y = sym_y + rot_y

                        if any(abs(pin_x - cp[0]) < eps and abs(pin_y - cp[1]) < eps for cp in connected_points):
                            pins.append({
                                "ref": ref,
                                "pin": pin_name,
                                "at": [round(pin_x, 2), round(pin_y, 2)],
                            })

            return {
                "success": True,
                "netName": net_name,
                "pins": pins,
                "labels": labels + power_labels,
                "wires": net_wires,
                "connected": len(pins) > 0 or len(labels) > 0,
                "counts": {
                    "pins": len(pins),
                    "labels": len(labels),
                    "powerSymbols": len(power_labels),
                    "wires": len(net_wires),
                },
            }
        except Exception as e:
            logger.error(f"Error getting net connectivity: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_validate_wire_connections(self, params):
        """Check if specific pins are electrically connected. Targeted alternative to full ERC."""
        logger.info("Validating wire connections")
        try:
            import re
            import math
            from pathlib import Path
            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            checks = params.get("checks", [])

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not checks:
                return {"success": False, "message": "checks array is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            sch_file = Path(schematic_path)
            locator = self.pin_locator

            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Build all wire segments
            all_wires = []
            wire_pat = re.compile(r'\(wire\b')
            xy_pat = re.compile(r'\(xy\s+([\d.e+-]+)\s+([\d.e+-]+)\)')
            for wm in wire_pat.finditer(content):
                depth = 0
                i = wm.start()
                block_end = i
                while i < len(content):
                    if content[i] == '(':
                        depth += 1
                    elif content[i] == ')':
                        depth -= 1
                        if depth == 0:
                            block_end = i + 1
                            break
                    i += 1
                block = content[wm.start():block_end]
                xys = xy_pat.findall(block)
                if len(xys) >= 2:
                    all_wires.append((
                        float(xys[0][0]), float(xys[0][1]),
                        float(xys[-1][0]), float(xys[-1][1]),
                    ))

            # Collect all label positions → net name mapping
            label_net_map = {}  # (x, y) → net_name
            for lt in ["label", "global_label", "hierarchical_label"]:
                lp = re.compile(
                    rf'\({lt}\s+"([^"]*)"(?:\s+\(shape\s+[^)]*\))?\s+\(at\s+([\d.e+-]+)\s+([\d.e+-]+)'
                )
                for m in lp.finditer(content):
                    name, lx, ly = m.group(1), float(m.group(2)), float(m.group(3))
                    label_net_map[(lx, ly)] = name

            # Collect power symbol positions → net name
            if hasattr(schematic, "symbol"):
                for symbol in schematic.symbol:
                    if not hasattr(symbol.property, "Reference"):
                        continue
                    ref = symbol.property.Reference.value
                    if not ref.startswith("#PWR"):
                        continue
                    val = symbol.property.Value.value if hasattr(symbol.property, "Value") else ""
                    pos = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                    label_net_map[(float(pos[0]), float(pos[1]))] = val

            eps = 0.5

            def find_pin_position(reference, pin_name):
                """Find schematic position of a specific pin."""
                for symbol in schematic.symbol:
                    if not hasattr(symbol.property, "Reference"):
                        continue
                    if symbol.property.Reference.value != reference:
                        continue
                    lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else ""
                    position = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                    sym_x, sym_y = float(position[0]), float(position[1])
                    sym_rot = float(position[2]) if len(position) > 2 else 0.0

                    mirror_x = False
                    mirror_y = False
                    if hasattr(symbol, "mirror"):
                        mirror_val = str(symbol.mirror.value) if hasattr(symbol.mirror, "value") else str(symbol.mirror)
                        mirror_x = "x" in mirror_val
                        mirror_y = "y" in mirror_val

                    pins_def = locator.get_symbol_pins(sch_file, lib_id)
                    if pin_name not in pins_def:
                        return None
                    pd = pins_def[pin_name]
                    pin_rel_x = pd["x"]
                    pin_rel_y = -pd["y"]
                    if mirror_x:
                        pin_rel_y = -pin_rel_y
                    if mirror_y:
                        pin_rel_x = -pin_rel_x
                    rad = math.radians(sym_rot)
                    cos_r, sin_r = math.cos(rad), math.sin(rad)
                    rot_x = pin_rel_x * cos_r - pin_rel_y * sin_r
                    rot_y = -pin_rel_x * sin_r + pin_rel_y * cos_r
                    return (sym_x + rot_x, sym_y + rot_y)
                return None

            def trace_connectivity(start_point):
                """Trace wire connectivity from a point, return all reachable points.
                Includes T-junction detection (point on mid-segment of another wire)."""
                reached = {start_point}
                changed = True
                while changed:
                    changed = False
                    for wx1, wy1, wx2, wy2 in all_wires:
                        p1 = (wx1, wy1)
                        p2 = (wx2, wy2)
                        p1_in = any(abs(p1[0] - r[0]) < eps and abs(p1[1] - r[1]) < eps for r in reached)
                        p2_in = any(abs(p2[0] - r[0]) < eps and abs(p2[1] - r[1]) < eps for r in reached)
                        if p1_in and not p2_in:
                            reached.add(p2)
                            changed = True
                        elif p2_in and not p1_in:
                            reached.add(p1)
                            changed = True
                        elif not p1_in and not p2_in:
                            # T-junction: does a reached point lie on this wire's mid-segment?
                            for rp in list(reached):
                                if _point_on_wire_segment(rp[0], rp[1], wx1, wy1, wx2, wy2, eps):
                                    reached.add(p1)
                                    reached.add(p2)
                                    changed = True
                                    break
                        # Reverse T-junction: does this wire's endpoint lie on a connected wire?
                        if not p1_in:
                            for owx1, owy1, owx2, owy2 in all_wires:
                                if (owx1, owy1, owx2, owy2) == (wx1, wy1, wx2, wy2):
                                    continue
                                o1_in = any(abs(owx1 - r[0]) < eps and abs(owy1 - r[1]) < eps for r in reached)
                                o2_in = any(abs(owx2 - r[0]) < eps and abs(owy2 - r[1]) < eps for r in reached)
                                if (o1_in or o2_in) and _point_on_wire_segment(p1[0], p1[1], owx1, owy1, owx2, owy2, eps):
                                    reached.add(p1)
                                    reached.add(p2)
                                    changed = True
                                    break
                        if not p2_in:
                            for owx1, owy1, owx2, owy2 in all_wires:
                                if (owx1, owy1, owx2, owy2) == (wx1, wy1, wx2, wy2):
                                    continue
                                o1_in = any(abs(owx1 - r[0]) < eps and abs(owy1 - r[1]) < eps for r in reached)
                                o2_in = any(abs(owx2 - r[0]) < eps and abs(owy2 - r[1]) < eps for r in reached)
                                if (o1_in or o2_in) and _point_on_wire_segment(p2[0], p2[1], owx1, owy1, owx2, owy2, eps):
                                    reached.add(p1)
                                    reached.add(p2)
                                    changed = True
                                    break
                return reached

            results = []
            for check in checks:
                ref = check.get("reference")
                pin = check.get("pin")
                expected_net = check.get("expectedNet")

                pin_pos = find_pin_position(ref, pin)
                if pin_pos is None:
                    results.append({
                        "reference": ref, "pin": pin,
                        "connected": False,
                        "message": f"Pin {pin} not found on {ref}",
                    })
                    continue

                reachable = trace_connectivity(pin_pos)

                # Find what net this connects to
                found_net = None
                for pt in reachable:
                    for (lx, ly), net in label_net_map.items():
                        if abs(pt[0] - lx) < eps and abs(pt[1] - ly) < eps:
                            found_net = net
                            break
                    if found_net:
                        break

                r = {
                    "reference": ref, "pin": pin,
                    "pinPosition": [round(pin_pos[0], 2), round(pin_pos[1], 2)],
                    "connected": found_net is not None,
                    "netName": found_net,
                }
                if expected_net:
                    r["expectedNet"] = expected_net
                    r["match"] = found_net == expected_net
                results.append(r)

            all_ok = all(r.get("connected", False) for r in results)
            if any("match" in r for r in results):
                all_ok = all(r.get("match", r.get("connected", False)) for r in results)

            return {
                "success": True,
                "allConnected": all_ok,
                "results": results,
                "summary": f"{sum(1 for r in results if r.get('connected'))} of {len(results)} pins connected",
            }
        except Exception as e:
            logger.error(f"Error validating wire connections: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_add_schematic_text(self, params):
        """Add a text annotation to the schematic."""
        logger.info("Adding schematic text")
        try:
            from pathlib import Path
            import uuid as _uuid

            schematic_path = params.get("schematicPath")
            text = params.get("text")
            position = params.get("position", {})
            size = params.get("size", 2.54)
            angle = params.get("angle", 0)

            if not schematic_path or not text:
                return {"success": False, "message": "schematicPath and text are required"}

            x = position.get("x", 0) if isinstance(position, dict) else 0
            y = position.get("y", 0) if isinstance(position, dict) else 0

            from commands.sexp_writer import _read_schematic, _write_schematic, _find_insert_position

            content = _read_schematic(Path(schematic_path))
            text_uuid = str(_uuid.uuid4())

            text_block = (
                f'  (text "{text}" (at {x} {y} {angle})\n'
                f"    (effects (font (size {size} {size})))\n"
                f'    (uuid "{text_uuid}")\n'
                f"  )\n\n"
            )

            insert_at = _find_insert_position(content)
            content = content[:insert_at] + text_block + content[insert_at:]
            _write_schematic(Path(schematic_path), content)

            return {"success": True, "message": f"Added text at ({x}, {y})"}
        except Exception as e:
            logger.error(f"Error adding schematic text: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_rotate_schematic_label(self, params):
        """Rotate a net label to a new angle, updating justify and Intersheetrefs position."""
        logger.info("Rotating schematic label")
        try:
            import re

            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")
            position = params.get("position")
            angle = params.get("angle", 0)

            if not schematic_path or not net_name:
                return {"success": False, "message": "schematicPath and netName are required"}

            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            tolerance = 0.5
            escaped = re.escape(net_name)
            found = False
            found_label_type = None
            label_x, label_y = 0.0, 0.0

            for label_type in ["label", "global_label", "hierarchical_label"]:
                # Allow optional (shape ...) between label name and (at ...) for global labels
                pat = re.compile(
                    rf'(\({label_type}\s+"{escaped}"(?:\s+\(shape\s+[^)]*\))?\s+\(at\s+)([\d.e+-]+)\s+([\d.e+-]+)\s+[\d.e+-]+'
                )
                for m in pat.finditer(content):
                    lx, ly = float(m.group(2)), float(m.group(3))
                    if position:
                        px = position.get("x", 0)
                        py = position.get("y", 0)
                        if abs(lx - px) >= tolerance or abs(ly - py) >= tolerance:
                            continue

                    # Replace the angle in (at X Y ANGLE
                    old = m.group(0)
                    new = f"{m.group(1)}{m.group(2)} {m.group(3)} {angle}"
                    content = content.replace(old, new, 1)
                    found = True
                    found_label_type = label_type
                    label_x, label_y = lx, ly
                    break
                if found:
                    break

            if not found:
                return {"success": False, "message": f"Label '{net_name}' not found"}

            # Update justify for global_label and hierarchical_label.
            # KiCad uses: 0°/90° → justify left, 180°/270° → justify right.
            # The justify controls which direction the flag shape extends.
            norm_angle = int(angle) % 360
            new_justify = "right" if norm_angle in (180, 270) else "left"

            if found_label_type in ("global_label", "hierarchical_label"):
                # Find the label block and update its (justify ...) in (effects ...)
                # Strategy: find the specific label occurrence, then find/replace
                # justify within a bounded region after it.
                label_start_pat = re.compile(
                    rf'\({found_label_type}\s+"{escaped}"(?:\s+\(shape\s+[^)]*\))?\s+\(at\s+{re.escape(str(label_x))}\s+{re.escape(str(label_y))}\s+'
                )
                lm = label_start_pat.search(content)
                if lm:
                    # Find the label block end (balanced parens)
                    depth = 0
                    i = lm.start()
                    block_end = i
                    while i < len(content):
                        if content[i] == '(':
                            depth += 1
                        elif content[i] == ')':
                            depth -= 1
                            if depth == 0:
                                block_end = i + 1
                                break
                        i += 1
                    block = content[lm.start():block_end]

                    # Update justify in the FIRST (effects ...) block (the label's own effects,
                    # not the Intersheetrefs property effects)
                    effects_match = re.search(r'\(effects\b', block)
                    if effects_match:
                        # Find the closing paren of this effects block
                        ed = 0
                        ei = effects_match.start()
                        effects_end = ei
                        while ei < len(block):
                            if block[ei] == '(':
                                ed += 1
                            elif block[ei] == ')':
                                ed -= 1
                                if ed == 0:
                                    effects_end = ei + 1
                                    break
                            ei += 1
                        effects_block = block[effects_match.start():effects_end]

                        # Replace or insert justify
                        justify_pat = re.compile(r'\(justify\s+\w+\)')
                        if justify_pat.search(effects_block):
                            new_effects = justify_pat.sub(f'(justify {new_justify})', effects_block, count=1)
                        else:
                            # Insert justify before closing paren of effects
                            insert_pos = effects_block.rfind(')')
                            indent = "\n\t\t\t" if "\n" in effects_block else " "
                            new_effects = effects_block[:insert_pos] + f'{indent}(justify {new_justify})' + effects_block[insert_pos:]

                        if new_effects != effects_block:
                            new_block = block[:effects_match.start()] + new_effects + block[effects_end:]
                            content = content[:lm.start()] + new_block + content[block_end:]

                    # Update Intersheetrefs position.
                    # Recompute flag width for positioning.
                    char_w = 0.75
                    text_len = len(net_name) * char_w
                    body = 3.0  # global/hierarchical flag body
                    total_w = body + text_len

                    # Intersheetrefs (at) position depends on angle+justify:
                    # At 0° (left): at label position (right end is connection pt)
                    # At 180° (right): at label.x - total_w (flag extends left)
                    # At 90° (left): at label position (bottom is connection pt)
                    # At 270° (right): at label.y - total_w (flag extends up)
                    if norm_angle == 0:
                        isr_x, isr_y = label_x, label_y
                    elif norm_angle == 180:
                        isr_x, isr_y = round(label_x - total_w, 4), label_y
                    elif norm_angle == 90:
                        isr_x, isr_y = label_x, label_y
                    else:  # 270
                        isr_x, isr_y = label_x, round(label_y - total_w, 4)

                    # Find and update Intersheetrefs property within this label block
                    # Re-search since content may have changed
                    lm2 = label_start_pat.search(content)
                    if lm2:
                        depth2 = 0
                        i2 = lm2.start()
                        block_end2 = i2
                        while i2 < len(content):
                            if content[i2] == '(':
                                depth2 += 1
                            elif content[i2] == ')':
                                depth2 -= 1
                                if depth2 == 0:
                                    block_end2 = i2 + 1
                                    break
                            i2 += 1
                        block2 = content[lm2.start():block_end2]

                        # Update Intersheetrefs (at X Y angle)
                        isr_at_pat = re.compile(
                            r'(\(property\s+"Intersheetrefs"\s+"[^"]*"\s+\(at\s+)[\d.e+-]+\s+[\d.e+-]+\s+[\d.e+-]+'
                        )
                        isr_m = isr_at_pat.search(block2)
                        if isr_m:
                            old_isr = isr_m.group(0)
                            new_isr = f"{isr_m.group(1)}{isr_x} {isr_y} {angle}"
                            new_block2 = block2.replace(old_isr, new_isr, 1)

                            # Also update justify in Intersheetrefs effects
                            # Find the Intersheetrefs property block
                            isr_prop_start = new_block2.find('(property "Intersheetrefs"')
                            if isr_prop_start >= 0:
                                # Find the end of this property block
                                pd = 0
                                pi = isr_prop_start
                                prop_end = pi
                                while pi < len(new_block2):
                                    if new_block2[pi] == '(':
                                        pd += 1
                                    elif new_block2[pi] == ')':
                                        pd -= 1
                                        if pd == 0:
                                            prop_end = pi + 1
                                            break
                                    pi += 1
                                isr_prop = new_block2[isr_prop_start:prop_end]
                                new_isr_prop = justify_pat.sub(f'(justify {new_justify})', isr_prop)
                                if new_isr_prop != isr_prop:
                                    new_block2 = new_block2[:isr_prop_start] + new_isr_prop + new_block2[prop_end:]

                            content = content[:lm2.start()] + new_block2 + content[block_end2:]

            with open(schematic_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            return {"success": True, "message": f"Rotated label '{net_name}' to {angle}° (justify {new_justify})"}
        except Exception as e:
            logger.error(f"Error rotating label: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_batch_delete_schematic_components(self, params):
        """Delete multiple schematic components in a single call. Single read/write cycle."""
        logger.info("Batch deleting schematic components")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            references = params.get("references", [])

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not references:
                return {"success": False, "message": "references array is required"}

            sch_file = Path(schematic_path)
            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            deleted = []
            failed = []
            for ref in references:
                result, count = self._delete_component_from_content(content, ref)
                if result is not None:
                    content = result
                    deleted.append(ref)
                else:
                    failed.append(f"{ref}: not found")

            with open(sch_file, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            return {
                "success": len(failed) == 0,
                "message": f"Deleted {len(deleted)}, failed {len(failed)}",
                "deleted": deleted,
                "failed": failed,
            }
        except Exception as e:
            logger.error(f"Error in batch_delete_schematic_components: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_schematic_component(self, params):
        """Return full component info: position and all field values with their (at x y angle) positions."""
        logger.info("Getting schematic component info")
        try:
            from pathlib import Path
            import re

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            def find_matching_paren(s, start):
                depth = 0
                i = start
                while i < len(s):
                    if s[i] == "(":
                        depth += 1
                    elif s[i] == ")":
                        depth -= 1
                        if depth == 0:
                            return i
                    i += 1
                return -1

            # Skip lib_symbols section
            lib_sym_pos = content.find("(lib_symbols")
            lib_sym_end = (
                find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1
            )

            # Find the placed symbol block for this reference
            block_start = block_end = None
            search_start = 0
            pattern = re.compile(r'\(symbol\s+\(lib_id\s+"')
            while True:
                m = pattern.search(content, search_start)
                if not m:
                    break
                pos = m.start()
                if lib_sym_pos >= 0 and lib_sym_pos <= pos <= lib_sym_end:
                    search_start = lib_sym_end + 1
                    continue
                end = find_matching_paren(content, pos)
                if end < 0:
                    search_start = pos + 1
                    continue
                block_text = content[pos : end + 1]
                if re.search(
                    r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"',
                    block_text,
                ):
                    block_start, block_end = pos, end
                    break
                search_start = end + 1

            if block_start is None:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic",
                }

            block_text = content[block_start : block_end + 1]

            # Extract component position: first (at x y angle) in the symbol header line
            comp_at = re.search(
                r'\(symbol\s+\(lib_id\s+"[^"]*"\s*\)\s+\(at\s+([\d\.\-]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s*\)',
                block_text,
            )
            if comp_at:
                comp_pos = {
                    "x": float(comp_at.group(1)),
                    "y": float(comp_at.group(2)),
                    "angle": float(comp_at.group(3)),
                }
            else:
                comp_pos = None

            # Extract all properties with their at positions
            prop_pattern = re.compile(
                r'\(property\s+"([^"]*)"\s+"([^"]*)"\s+\(at\s+([\d\.\-]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s*\)'
            )
            fields = {}
            for m in prop_pattern.finditer(block_text):
                name, value, x, y, angle = (
                    m.group(1),
                    m.group(2),
                    m.group(3),
                    m.group(4),
                    m.group(5),
                )
                fields[name] = {
                    "value": value,
                    "x": float(x),
                    "y": float(y),
                    "angle": float(angle),
                }

            return {
                "success": True,
                "reference": reference,
                "position": comp_pos,
                "fields": fields,
            }

        except Exception as e:
            logger.error(f"Error getting schematic component: {e}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_add_schematic_wire(self, params):
        """Add a wire to a schematic using WireManager"""
        logger.info("Adding wire to schematic")
        try:
            from pathlib import Path
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            # Accept both "startPoint"/"endPoint" (legacy) and "start"/"end" (TS tool)
            start_point = params.get("startPoint") or params.get("start")
            end_point = params.get("endPoint") or params.get("end")
            properties = params.get("properties", {})

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not start_point or not end_point:
                return {
                    "success": False,
                    "message": "Start and end points are required",
                }

            # Normalize {x, y} objects to [x, y] arrays
            if isinstance(start_point, dict):
                start_point = [start_point.get("x", 0), start_point.get("y", 0)]
            if isinstance(end_point, dict):
                end_point = [end_point.get("x", 0), end_point.get("y", 0)]

            # Extract wire properties
            stroke_width = properties.get("stroke_width", 0)
            stroke_type = properties.get("stroke_type", "default")

            # Use WireManager for S-expression manipulation
            success = WireManager.add_wire(
                Path(schematic_path),
                start_point,
                end_point,
                stroke_width=stroke_width,
                stroke_type=stroke_type,
            )

            if success:
                return {"success": True, "message": "Wire added successfully"}
            else:
                return {"success": False, "message": "Failed to add wire"}
        except Exception as e:
            logger.error(f"Error adding wire to schematic: {str(e)}")


            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_list_schematic_libraries(self, params):
        """List available symbol libraries"""
        logger.info("Listing schematic libraries")
        try:
            search_paths = params.get("searchPaths")

            libraries = LibraryManager.list_available_libraries(search_paths)
            return {"success": True, "libraries": libraries}
        except Exception as e:
            logger.error(f"Error listing schematic libraries: {str(e)}")
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------ #
    #  Footprint handlers                                                  #
    # ------------------------------------------------------------------ #

    def _handle_create_footprint(self, params):
        """Create a new .kicad_mod footprint file in a .pretty library."""
        logger.info(
            f"create_footprint: {params.get('name')} in {params.get('libraryPath')}"
        )
        try:
            creator = FootprintCreator()
            return creator.create_footprint(
                library_path=params.get("libraryPath", ""),
                name=params.get("name", ""),
                description=params.get("description", ""),
                tags=params.get("tags", ""),
                pads=params.get("pads", []),
                courtyard=params.get("courtyard"),
                silkscreen=params.get("silkscreen"),
                fab_layer=params.get("fabLayer"),
                ref_position=params.get("refPosition"),
                value_position=params.get("valuePosition"),
                overwrite=params.get("overwrite", False),
            )
        except Exception as e:
            logger.error(f"create_footprint error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_edit_footprint_pad(self, params):
        """Edit an existing pad in a .kicad_mod file."""
        logger.info(
            f"edit_footprint_pad: pad {params.get('padNumber')} in {params.get('footprintPath')}"
        )
        try:
            creator = FootprintCreator()
            return creator.edit_footprint_pad(
                footprint_path=params.get("footprintPath", ""),
                pad_number=str(params.get("padNumber", "1")),
                size=params.get("size"),
                at=params.get("at"),
                drill=params.get("drill"),
                shape=params.get("shape"),
            )
        except Exception as e:
            logger.error(f"edit_footprint_pad error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_list_footprint_libraries(self, params):
        """List .pretty footprint libraries and their contents."""
        logger.info("list_footprint_libraries")
        try:
            creator = FootprintCreator()
            return creator.list_footprint_libraries(
                search_paths=params.get("searchPaths")
            )
        except Exception as e:
            logger.error(f"list_footprint_libraries error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_register_footprint_library(self, params):
        """Register a .pretty library in KiCAD's fp-lib-table."""
        logger.info(f"register_footprint_library: {params.get('libraryPath')}")
        try:
            creator = FootprintCreator()
            return creator.register_footprint_library(
                library_path=params.get("libraryPath", ""),
                library_name=params.get("libraryName"),
                description=params.get("description", ""),
                scope=params.get("scope", "project"),
                project_path=params.get("projectPath"),
            )
        except Exception as e:
            logger.error(f"register_footprint_library error: {e}")
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------ #
    #  Symbol creator handlers                                             #
    # ------------------------------------------------------------------ #

    def _handle_create_symbol(self, params):
        """Create a new symbol in a .kicad_sym library."""
        logger.info(
            f"create_symbol: {params.get('name')} in {params.get('libraryPath')}"
        )
        try:
            creator = SymbolCreator()
            return creator.create_symbol(
                library_path=params.get("libraryPath", ""),
                name=params.get("name", ""),
                reference_prefix=params.get("referencePrefix", "U"),
                description=params.get("description", ""),
                keywords=params.get("keywords", ""),
                datasheet=params.get("datasheet", "~"),
                footprint=params.get("footprint", ""),
                in_bom=params.get("inBom", True),
                on_board=params.get("onBoard", True),
                pins=params.get("pins", []),
                rectangles=params.get("rectangles", []),
                polylines=params.get("polylines", []),
                overwrite=params.get("overwrite", False),
            )
        except Exception as e:
            logger.error(f"create_symbol error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_delete_symbol(self, params):
        """Delete a symbol from a .kicad_sym library."""
        logger.info(
            f"delete_symbol: {params.get('name')} from {params.get('libraryPath')}"
        )
        try:
            creator = SymbolCreator()
            return creator.delete_symbol(
                library_path=params.get("libraryPath", ""),
                name=params.get("name", ""),
            )
        except Exception as e:
            logger.error(f"delete_symbol error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_list_symbols_in_library(self, params):
        """List all symbols in a .kicad_sym file."""
        logger.info(f"list_symbols_in_library: {params.get('libraryPath')}")
        try:
            creator = SymbolCreator()
            return creator.list_symbols(
                library_path=params.get("libraryPath", ""),
            )
        except Exception as e:
            logger.error(f"list_symbols_in_library error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_register_symbol_library(self, params):
        """Register a .kicad_sym library in KiCAD's sym-lib-table."""
        logger.info(f"register_symbol_library: {params.get('libraryPath')}")
        try:
            creator = SymbolCreator()
            return creator.register_symbol_library(
                library_path=params.get("libraryPath", ""),
                library_name=params.get("libraryName"),
                description=params.get("description", ""),
                scope=params.get("scope", "project"),
                project_path=params.get("projectPath"),
            )
        except Exception as e:
            logger.error(f"register_symbol_library error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_export_schematic_pdf(self, params):
        """Export schematic to PDF"""
        logger.info("Exporting schematic to PDF")
        try:
            schematic_path = params.get("schematicPath")
            output_path = params.get("outputPath")

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not output_path:
                return {"success": False, "message": "Output path is required"}

            if not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            import subprocess

            cmd = [
                "kicad-cli",
                "sch",
                "export",
                "pdf",
                "--output",
                output_path,
                schematic_path,
            ]

            if params.get("blackAndWhite"):
                cmd.insert(-1, "--black-and-white")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode == 0:
                return {"success": True, "file": {"path": output_path}}
            else:
                return {
                    "success": False,
                    "message": f"kicad-cli failed: {result.stderr}",
                }

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except Exception as e:
            logger.error(f"Error exporting schematic to PDF: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_add_schematic_connection(self, params):
        """Add a pin-to-pin connection in schematic with automatic pin discovery and routing"""
        logger.info("Adding pin-to-pin connection in schematic")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            source_ref = params.get("sourceRef")
            source_pin = params.get("sourcePin")
            target_ref = params.get("targetRef")
            target_pin = params.get("targetPin")
            routing = params.get(
                "routing", "direct"
            )  # 'direct', 'orthogonal_h', 'orthogonal_v'

            if not all(
                [schematic_path, source_ref, source_pin, target_ref, target_pin]
            ):
                return {"success": False, "message": "Missing required parameters"}

            # Use ConnectionManager with new PinLocator and WireManager integration
            success = ConnectionManager.add_connection(
                Path(schematic_path),
                source_ref,
                source_pin,
                target_ref,
                target_pin,
                routing=routing,
            )

            if success:
                return {
                    "success": True,
                    "message": f"Connected {source_ref}/{source_pin} to {target_ref}/{target_pin} (routing: {routing})",
                }
            else:
                return {"success": False, "message": "Failed to add connection"}
        except Exception as e:
            logger.error(f"Error adding schematic connection: {str(e)}")


            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_add_schematic_net_label(self, params):
        """Add a net label to schematic using WireManager"""
        logger.info("Adding net label to schematic")
        try:
            from pathlib import Path
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")
            position = params.get("position")
            label_type = params.get(
                "labelType", "label"
            )  # 'label', 'global_label', 'hierarchical_label'
            orientation = params.get("orientation", 0)  # 0, 90, 180, 270
            shape = params.get("shape")  # For global_label: input, output, bidirectional, passive

            if not all([schematic_path, net_name, position]):
                return {"success": False, "message": "Missing required parameters"}

            # Normalize position: accept both [x,y] array and {x,y} object
            if isinstance(position, dict):
                position = [position.get("x", 0), position.get("y", 0)]

            # Use WireManager for S-expression manipulation
            success = WireManager.add_label(
                Path(schematic_path),
                net_name,
                position,
                label_type=label_type,
                orientation=orientation,
                shape=shape,
            )

            if success:
                return {
                    "success": True,
                    "message": f"Added net label '{net_name}' at {position}",
                }
            else:
                return {"success": False, "message": "Failed to add net label"}
        except Exception as e:
            logger.error(f"Error adding net label: {str(e)}")


            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_connect_to_net(self, params):
        """Connect a component pin to a named net using wire stub and label.

        Supports power nets (GND, +3V3, +5V, VCC, etc.) — automatically places
        a power symbol instead of a net label when a power net is detected.
        Also supports global labels via labelType parameter.
        """
        logger.info("Connecting component pin to net")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            component_ref = params.get("componentRef")
            pin_name = params.get("pinName")
            net_name = params.get("netName")
            label_type = params.get("labelType")  # None, "label", "global_label"
            shape = params.get("shape")  # For global_label: input, output, etc.

            if not all([schematic_path, component_ref, pin_name, net_name]):
                return {"success": False, "message": "Missing required parameters"}

            # Use ConnectionManager with power-net awareness
            success = ConnectionManager.connect_to_net(
                Path(schematic_path), component_ref, pin_name, net_name,
                label_type=label_type, shape=shape,
            )

            if success:
                return {
                    "success": True,
                    "message": f"Connected {component_ref}/{pin_name} to net '{net_name}'",
                }
            else:
                return {"success": False, "message": "Failed to connect to net"}
        except Exception as e:
            logger.error(f"Error connecting to net: {str(e)}")


            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_connect_passthrough(self, params):
        """Connect all pins of source connector to matching pins of target connector"""
        logger.info("Connecting passthrough between two connectors")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            source_ref = params.get("sourceRef")
            target_ref = params.get("targetRef")
            net_prefix = params.get("netPrefix", "PIN")
            pin_offset = int(params.get("pinOffset", 0))

            if not all([schematic_path, source_ref, target_ref]):
                return {
                    "success": False,
                    "message": "Missing required parameters: schematicPath, sourceRef, targetRef",
                }

            result = ConnectionManager.connect_passthrough(
                Path(schematic_path), source_ref, target_ref, net_prefix, pin_offset
            )

            n_ok = len(result["connected"])
            n_fail = len(result["failed"])
            return {
                "success": n_fail == 0,
                "message": f"Passthrough complete: {n_ok} connected, {n_fail} failed",
                "connected": result["connected"],
                "failed": result["failed"],
            }
        except Exception as e:
            logger.error(f"Error in connect_passthrough: {str(e)}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_schematic_pin_locations(self, params):
        """Return exact pin endpoint coordinates for a schematic component"""
        logger.info("Getting schematic pin locations")
        try:
            from pathlib import Path
            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")

            if not all([schematic_path, reference]):
                return {
                    "success": False,
                    "message": "Missing required parameters: schematicPath, reference",
                }

            locator = self.pin_locator
            all_pins = locator.get_all_symbol_pins(Path(schematic_path), reference)

            if not all_pins:
                return {
                    "success": False,
                    "message": f"No pins found for {reference} — check reference and schematic path",
                }

            # Enrich with pin names and angles from the symbol definition
            pins_def = (
                locator.get_symbol_pins(
                    Path(schematic_path),
                    locator._get_lib_id(Path(schematic_path), reference),
                )
                if hasattr(locator, "_get_lib_id")
                else {}
            )

            result = {}
            for pin_num, coords in all_pins.items():
                entry = {"x": coords[0], "y": coords[1]}
                if pin_num in pins_def:
                    entry["name"] = pins_def[pin_num].get("name", pin_num)
                    entry["angle"] = (
                        locator.get_pin_angle(Path(schematic_path), reference, pin_num)
                        or 0
                    )
                result[pin_num] = entry

            return {"success": True, "reference": reference, "pins": result}

        except Exception as e:
            logger.error(f"Error getting pin locations: {e}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_batch_get_schematic_pin_locations(self, params):
        """Return pin endpoint coordinates for multiple components in one call.

        Reads the schematic once and computes pin positions for all requested
        references using cached pin definitions.
        """
        logger.info("Batch getting schematic pin locations")
        try:
            from pathlib import Path
            from commands.pin_locator import PinLocator
            import math

            schematic_path = params.get("schematicPath")
            references = params.get("references", [])

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not references:
                return {"success": False, "message": "references array is required"}

            sch_file = Path(schematic_path)
            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            locator = self.pin_locator
            ref_set = set(references)
            results = {}

            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                if ref not in ref_set:
                    continue

                lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else ""
                if not lib_id:
                    results[ref] = {"error": "no lib_id"}
                    continue

                position = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                sym_x = float(position[0])
                sym_y = float(position[1])
                sym_rot = float(position[2]) if len(position) > 2 else 0.0

                pins_def = locator.get_symbol_pins(sch_file, lib_id)
                if not pins_def:
                    results[ref] = {"error": "no pin definitions"}
                    continue

                # Extract mirror transforms
                mirror_x = False
                mirror_y = False
                if hasattr(symbol, "mirror"):
                    mirror_val = str(symbol.mirror.value) if hasattr(symbol.mirror, 'value') else str(symbol.mirror)
                    mirror_x = "x" in mirror_val
                    mirror_y = "y" in mirror_val

                pins = {}
                for pin_num, pin_data in pins_def.items():
                    pin_rel_x = pin_data["x"]
                    pin_rel_y = -pin_data["y"]  # Y-negate: symbol-local Y-up → schematic Y-down
                    if mirror_x:
                        pin_rel_y = -pin_rel_y
                    if mirror_y:
                        pin_rel_x = -pin_rel_x
                    if sym_rot != 0:
                        pin_rel_x, pin_rel_y = PinLocator.rotate_point(
                            pin_rel_x, pin_rel_y, sym_rot
                        )
                    # Pin (at) IS the connectable endpoint — no length math needed
                    ep_x = round(sym_x + pin_rel_x, 4)
                    ep_y = round(sym_y + pin_rel_y, 4)

                    pins[pin_num] = {
                        "x": ep_x,
                        "y": ep_y,
                        "name": pin_data.get("name", pin_num),
                        "angle": (pin_data.get("angle", 0) + sym_rot) % 360,
                    }

                results[ref] = {"pins": pins}

            # Report any references not found
            for ref in references:
                if ref not in results:
                    results[ref] = {"error": "not found"}

            return {"success": True, "components": results}

        except Exception as e:
            logger.error(f"Error in batch pin locations: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    # ── Region / batch tools ────────────────────────────────────────────

    def _handle_move_region(self, params):
        """Move everything (components, wires, labels) within a bounding box by an offset.

        This is the block-select + move equivalent from KiCad's GUI.
        Collects all edits first, then applies them in reverse order to
        avoid corrupting string positions.
        """
        logger.info("Moving region in schematic")
        try:
            import re
            schematic_path = params.get("schematicPath")
            bbox = params.get("bbox", {})
            offset = params.get("offset", {})

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            x1, y1 = float(bbox.get("x1", 0)), float(bbox.get("y1", 0))
            x2, y2 = float(bbox.get("x2", 0)), float(bbox.get("y2", 0))
            dx, dy = float(offset.get("dx", 0)), float(offset.get("dy", 0))

            if x1 > x2: x1, x2 = x2, x1
            if y1 > y2: y1, y2 = y2, y1

            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            def in_bbox(x, y):
                return x1 <= x <= x2 and y1 <= y <= y2

            def find_block_end(s, start):
                """Find end of balanced paren block starting at s[start]='('."""
                depth = 0
                i = start
                while i < len(s):
                    if s[i] == "(": depth += 1
                    elif s[i] == ")":
                        depth -= 1
                        if depth == 0:
                            return i + 1
                    i += 1
                return len(s)

            # Skip lib_symbols section
            lib_sym_start = content.find("(lib_symbols")
            lib_sym_end = find_block_end(content, lib_sym_start) if lib_sym_start >= 0 else -1

            moved = {"components": 0, "wires": 0, "labels": 0}
            # Collect replacements as (start, end, new_text) — apply in reverse later
            replacements = []

            # --- Collect component replacements ---
            symbol_pattern = re.compile(r'\(symbol\s+\(lib_id\s+"')
            for m in symbol_pattern.finditer(content):
                pos = m.start()
                if lib_sym_start >= 0 and lib_sym_start <= pos < lib_sym_end:
                    continue

                end = find_block_end(content, pos)
                block = content[pos:end]

                # Get the FIRST (at X Y ...) which is the symbol position
                at_m = re.search(r'\(at\s+([\d.e+-]+)\s+([\d.e+-]+)', block)
                if not at_m:
                    continue
                sx, sy = float(at_m.group(1)), float(at_m.group(2))
                if not in_bbox(sx, sy):
                    continue

                # Shift all (at X Y ...) in this block (symbol pos + field positions)
                def _shift_at(match, _dx=dx, _dy=dy):
                    ax = float(match.group(1)) + _dx
                    ay = float(match.group(2)) + _dy
                    rest = match.group(3)
                    return f"(at {ax} {ay}{rest}"

                new_block = re.sub(
                    r'\(at\s+([\d.e+-]+)\s+([\d.e+-]+)([\s\d.e+-]*\))',
                    _shift_at, block
                )
                replacements.append((pos, end, new_block))
                moved["components"] += 1

            # --- Collect wire replacements ---
            wire_pattern = re.compile(r'\(wire\b')
            for m in wire_pattern.finditer(content):
                pos = m.start()
                end = find_block_end(content, pos)
                block = content[pos:end]

                xy_matches = re.findall(r'\(xy\s+([\d.e+-]+)\s+([\d.e+-]+)\)', block)
                if not xy_matches:
                    continue

                # Check if ANY point is in bbox
                if not any(in_bbox(float(xm[0]), float(xm[1])) for xm in xy_matches):
                    continue

                def _shift_xy(match, _dx=dx, _dy=dy):
                    return f"(xy {float(match.group(1)) + _dx} {float(match.group(2)) + _dy})"

                new_block = re.sub(r'\(xy\s+([\d.e+-]+)\s+([\d.e+-]+)\)', _shift_xy, block)
                replacements.append((pos, end, new_block))
                moved["wires"] += 1

            # --- Collect label replacements ---
            for label_type in ["label", "global_label", "hierarchical_label"]:
                label_pat = re.compile(rf'\({label_type}\s+"[^"]*"(?:\s+\(shape\s+[^)]*\))?\s+\(at\s+([\d.e+-]+)\s+([\d.e+-]+)')
                for m in label_pat.finditer(content):
                    lx, ly = float(m.group(1)), float(m.group(2))
                    if not in_bbox(lx, ly):
                        continue

                    pos = m.start()
                    end = find_block_end(content, pos)
                    block = content[pos:end]

                    def _shift_at_label(match, _dx=dx, _dy=dy):
                        ax = float(match.group(1)) + _dx
                        ay = float(match.group(2)) + _dy
                        rest = match.group(3)
                        return f"(at {ax} {ay}{rest}"

                    # Only shift the FIRST (at ...) in the label block (the label position)
                    new_block = re.sub(
                        r'\(at\s+([\d.e+-]+)\s+([\d.e+-]+)([\s\d.e+-]*\))',
                        _shift_at_label, block, count=1
                    )
                    replacements.append((pos, end, new_block))
                    moved["labels"] += 1

            # Apply all replacements in REVERSE order so positions stay valid
            replacements.sort(key=lambda r: r[0], reverse=True)
            for start, end, new_text in replacements:
                content = content[:start] + new_text + content[end:]

            with open(schematic_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            total = moved["components"] + moved["wires"] + moved["labels"]
            return {
                "success": True,
                "message": f"Moved {total} items (dx={dx}, dy={dy})",
                "moved": moved,
            }

        except Exception as e:
            logger.error(f"Error in move_region: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_batch_add_wire(self, params):
        """Add multiple wires in a single call. Single read/write cycle."""
        logger.info("Batch adding wires")
        try:
            from pathlib import Path
            from commands.sexp_writer import add_wire_to_content, _read_schematic, _write_schematic

            schematic_path = params.get("schematicPath")
            wires = params.get("wires", [])

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not wires:
                return {"success": False, "message": "wires array is required"}

            content = _read_schematic(Path(schematic_path))
            added = 0
            all_new_endpoints = []
            for w in wires:
                start = w.get("start", {})
                end = w.get("end", {})
                sp = [start.get("x", 0), start.get("y", 0)]
                ep = [end.get("x", 0), end.get("y", 0)]
                content = add_wire_to_content(content, sp, ep)
                all_new_endpoints.append((sp[0], sp[1]))
                all_new_endpoints.append((ep[0], ep[1]))
                added += 1

            # Auto-detect and fix T-junctions for all new wire endpoints
            from commands.sexp_writer import auto_add_t_junctions
            content, n_junctions = auto_add_t_junctions(content, all_new_endpoints)
            _write_schematic(Path(schematic_path), content)

            msg = f"Added {added} wires, 0 failed"
            if n_junctions:
                msg += f" (auto-added {n_junctions} junction(s))"
            return {
                "success": True,
                "message": msg,
                "added": added,
                "failed": 0,
                "junctionsAdded": n_junctions,
            }
        except Exception as e:
            logger.error(f"Error in batch_add_wire: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_connected_items(self, params):
        """Given a component reference, return all wires and labels connected to its pins."""
        logger.info("Getting connected items")
        try:
            from pathlib import Path
            from commands.pin_locator import PinLocator
            import re

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")

            if not schematic_path or not reference:
                return {"success": False, "message": "schematicPath and reference are required"}

            sch_file = Path(schematic_path)

            # Get pin endpoints for this component
            locator = self.pin_locator
            all_pins = locator.get_all_symbol_pins(sch_file, reference)
            if not all_pins:
                return {"success": False, "message": f"No pins found for {reference}"}

            # Read schematic to find wires and labels at pin positions
            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            tolerance = 0.5
            connected_wires = []
            connected_labels = []

            pin_positions = list(all_pins.values())

            def near_any_pin(x, y):
                for pp in pin_positions:
                    if abs(x - pp[0]) < tolerance and abs(y - pp[1]) < tolerance:
                        return True
                return False

            # Find wires touching any pin
            wire_pat = re.compile(r'\(wire\b')
            for m in wire_pat.finditer(content):
                pos = m.start()
                depth = 0
                end = pos
                while end < len(content):
                    if content[end] == "(": depth += 1
                    elif content[end] == ")":
                        depth -= 1
                        if depth == 0:
                            end += 1
                            break
                    end += 1
                block = content[pos:end]
                xy_matches = re.findall(r'\(xy\s+([\d.e+-]+)\s+([\d.e+-]+)\)', block)
                for xm in xy_matches:
                    if near_any_pin(float(xm[0]), float(xm[1])):
                        pts = [{"x": float(p[0]), "y": float(p[1])} for p in xy_matches]
                        connected_wires.append({"start": pts[0], "end": pts[-1]})
                        break

            # Find labels touching any pin or wire endpoint
            for label_type in ["label", "global_label", "hierarchical_label"]:
                label_pat = re.compile(rf'\({label_type}\s+"([^"]*)"(?:\s+\(shape\s+[^)]*\))?\s+\(at\s+([\d.e+-]+)\s+([\d.e+-]+)')
                for m in label_pat.finditer(content):
                    name = m.group(1)
                    lx, ly = float(m.group(2)), float(m.group(3))
                    if near_any_pin(lx, ly):
                        connected_labels.append({"netName": name, "position": {"x": lx, "y": ly}, "type": label_type})

            return {
                "success": True,
                "reference": reference,
                "pins": {pn: {"x": pv[0], "y": pv[1]} for pn, pv in all_pins.items()},
                "connectedWires": connected_wires,
                "connectedLabels": connected_labels,
            }

        except Exception as e:
            logger.error(f"Error in get_connected_items: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_batch_delete(self, params):
        """Delete multiple wires and/or labels in a single call. Single read/write cycle."""
        logger.info("Batch deleting items")
        try:
            from pathlib import Path
            from commands.sexp_writer import (
                delete_wire_from_content, delete_label_from_content,
                _read_schematic, _write_schematic,
            )

            schematic_path = params.get("schematicPath")
            wires = params.get("wires", [])
            labels = params.get("labels", [])

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            content = _read_schematic(Path(schematic_path))
            deleted_wires = 0
            deleted_labels = 0
            failed = []

            for w in wires:
                start = w.get("start", {})
                end = w.get("end", {})
                sp = [start.get("x", 0), start.get("y", 0)]
                ep = [end.get("x", 0), end.get("y", 0)]
                result = delete_wire_from_content(content, sp, ep)
                if result is not None:
                    content = result
                    deleted_wires += 1
                else:
                    failed.append(f"wire {sp}->{ep}")

            for l in labels:
                net = l.get("netName")
                pos = l.get("position")
                pos_list = [pos.get("x", 0), pos.get("y", 0)] if pos else None
                result = delete_label_from_content(content, net, pos_list)
                if result is not None:
                    content = result
                    deleted_labels += 1
                else:
                    failed.append(f"label '{net}'")

            _write_schematic(Path(schematic_path), content)

            return {
                "success": len(failed) == 0,
                "message": f"Deleted {deleted_wires} wires, {deleted_labels} labels",
                "deletedWires": deleted_wires,
                "deletedLabels": deleted_labels,
                "failed": failed,
            }

        except Exception as e:
            logger.error(f"Error in batch_delete: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_move_labels_by_offset(self, params):
        """Move a set of labels by an x,y offset."""
        logger.info("Moving labels by offset")
        try:
            import re

            schematic_path = params.get("schematicPath")
            labels = params.get("labels", [])
            offset = params.get("offset", {})
            dx = float(offset.get("dx", 0))
            dy = float(offset.get("dy", 0))

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not labels:
                return {"success": False, "message": "labels array is required"}

            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            tolerance = 0.5
            moved = 0

            for label_spec in labels:
                net_name = label_spec.get("netName")
                pos = label_spec.get("position", {})
                target_x = float(pos.get("x", 0))
                target_y = float(pos.get("y", 0))

                # Find this label in content
                escaped = re.escape(net_name)
                for label_type in ["label", "global_label", "hierarchical_label"]:
                    pat = re.compile(
                        rf'\({label_type}\s+"{escaped}"(?:\s+\(shape\s+[^)]*\))?\s+\(at\s+([\d.e+-]+)\s+([\d.e+-]+)'
                    )
                    for m in pat.finditer(content):
                        lx, ly = float(m.group(1)), float(m.group(2))
                        if abs(lx - target_x) < tolerance and abs(ly - target_y) < tolerance:
                            # Found it — replace (at X Y with shifted values
                            new_x = lx + dx
                            new_y = ly + dy
                            old_at = f"(at {m.group(1)} {m.group(2)}"
                            new_at = f"(at {new_x} {new_y}"
                            # Replace just this occurrence
                            start = m.start()
                            at_pos = content.find(old_at, start)
                            if at_pos >= 0:
                                content = content[:at_pos] + new_at + content[at_pos + len(old_at):]
                                moved += 1
                            break

            with open(schematic_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            return {
                "success": True,
                "message": f"Moved {moved} labels by ({dx}, {dy})",
                "moved": moved,
            }

        except Exception as e:
            logger.error(f"Error in move_labels_by_offset: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    # ── Diagnostic tools ────────────────────────────────────────────────

    def _handle_find_orphan_items(self, params):
        """Find dangling wires, orphan labels, and unconnected pins in a schematic."""
        logger.info("Finding orphan items")
        try:
            import re
            from pathlib import Path
            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_file = Path(schematic_path)
            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            tolerance = 0.5
            locator = self.pin_locator

            # Collect all connectable points: pin endpoints, wire endpoints, label positions, junctions
            pin_points = []  # [(x, y, ref, pin_num)]
            wire_endpoints = []  # [(x, y)]
            label_points = []  # [(x, y, name, type)]
            junction_points = []  # [(x, y)]

            # Get all pin endpoints
            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                if ref.startswith("_TEMPLATE"):
                    continue
                lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else ""
                if not lib_id:
                    continue
                position = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                sx, sy = float(position[0]), float(position[1])
                sym_rot = float(position[2]) if len(position) > 2 else 0.0
                import math
                pins_def = locator.get_symbol_pins(sch_file, lib_id)
                _mirror_x = False
                _mirror_y = False
                if hasattr(symbol, "mirror"):
                    _mv = str(symbol.mirror.value) if hasattr(symbol.mirror, 'value') else str(symbol.mirror)
                    _mirror_x = "x" in _mv
                    _mirror_y = "y" in _mv
                for pin_num, pd in (pins_def or {}).items():
                    prx, pry = pd["x"], -pd["y"]
                    if _mirror_x:
                        pry = -pry
                    if _mirror_y:
                        prx = -prx
                    if sym_rot != 0:
                        prx, pry = PinLocator.rotate_point(prx, pry, sym_rot)
                    # Pin (at) IS the endpoint — no length math
                    ex = round(sx + prx, 4)
                    ey = round(sy + pry, 4)
                    pin_points.append((ex, ey, ref, pin_num))

            # Get wire endpoints and wire segments
            wire_segments = []  # [(x1, y1, x2, y2)] for T-junction detection
            wire_pat = re.compile(r'\(wire\b')
            for m in wire_pat.finditer(content):
                pos = m.start()
                depth = 0
                end = pos
                while end < len(content):
                    if content[end] == "(": depth += 1
                    elif content[end] == ")":
                        depth -= 1
                        if depth == 0: end += 1; break
                    end += 1
                block = content[pos:end]
                xy_ms = re.findall(r'\(xy\s+([\d.e+-]+)\s+([\d.e+-]+)\)', block)
                if len(xy_ms) >= 2:
                    x1, y1 = float(xy_ms[0][0]), float(xy_ms[0][1])
                    x2, y2 = float(xy_ms[-1][0]), float(xy_ms[-1][1])
                    wire_endpoints.append((x1, y1))
                    wire_endpoints.append((x2, y2))
                    wire_segments.append((x1, y1, x2, y2))

            # Get label positions
            for lt in ["label", "global_label", "hierarchical_label"]:
                lp = re.compile(rf'\({lt}\s+"([^"]*)"(?:\s+\(shape\s+[^)]*\))?\s+\(at\s+([\d.e+-]+)\s+([\d.e+-]+)')
                for m in lp.finditer(content):
                    label_points.append((float(m.group(2)), float(m.group(3)), m.group(1), lt))

            # Get junctions
            jp = re.compile(r'\(junction\s+\(at\s+([\d.e+-]+)\s+([\d.e+-]+)')
            for m in jp.finditer(content):
                junction_points.append((float(m.group(1)), float(m.group(2))))

            tolerance = 0.05  # 0.05mm tolerance — tight enough to avoid false matches

            def point_near(x1, y1, x2, y2):
                return abs(x1 - x2) < tolerance and abs(y1 - y2) < tolerance

            def touches_any(px, py, point_lists):
                """Check if (px, py) is near any point in the given lists of (x, y, ...) tuples."""
                for pts in point_lists:
                    for pt in pts:
                        if point_near(px, py, pt[0], pt[1]):
                            return True
                return False

            def point_on_any_wire_segment(px, py):
                """Check if (px, py) lies on the mid-segment of any wire (T-junction)."""
                for wx1, wy1, wx2, wy2 in wire_segments:
                    if _point_on_wire_segment(px, py, wx1, wy1, wx2, wy2, tolerance):
                        return True
                return False

            # All non-wire connection points (pins, labels, junctions)
            non_wire_points = [(x, y) for x, y, _, _ in pin_points]
            non_wire_points += [(x, y) for x, y, _, _ in label_points]
            non_wire_points += list(junction_points)

            # Find dangling wire endpoints (not touching a pin, label, junction, or other wire endpoint)
            # Also checks T-junctions: an endpoint that lands on another wire's mid-segment is connected
            dangling_wires = []
            seen = set()
            for wx, wy in wire_endpoints:
                key = (round(wx, 1), round(wy, 1))
                if key in seen:
                    continue
                seen.add(key)
                # Check against pins, labels, junctions
                connected = False
                for cx, cy in non_wire_points:
                    if point_near(wx, wy, cx, cy):
                        connected = True
                        break
                if not connected:
                    # Check against OTHER wire endpoints (wire-to-wire at shared endpoint)
                    other_count = 0
                    for ox, oy in wire_endpoints:
                        if point_near(wx, wy, ox, oy):
                            other_count += 1
                    if other_count > 1:  # more than just itself
                        connected = True
                if not connected:
                    # T-junction: does this endpoint land on another wire's mid-segment?
                    for sx1, sy1, sx2, sy2 in wire_segments:
                        # Skip the wire this endpoint belongs to
                        if (point_near(wx, wy, sx1, sy1) or point_near(wx, wy, sx2, sy2)):
                            continue
                        if _point_on_wire_segment(wx, wy, sx1, sy1, sx2, sy2, tolerance):
                            connected = True
                            break
                if not connected:
                    dangling_wires.append({"x": wx, "y": wy})

            # Find orphan labels (not touching a wire endpoint, wire mid-segment, or pin)
            orphan_labels = []
            for lx, ly, name, lt in label_points:
                touching = False
                for wx, wy in wire_endpoints:
                    if point_near(lx, ly, wx, wy):
                        touching = True
                        break
                if not touching:
                    # T-junction: label on a wire mid-segment
                    if point_on_any_wire_segment(lx, ly):
                        touching = True
                if not touching:
                    for px, py, _, _ in pin_points:
                        if point_near(lx, ly, px, py):
                            touching = True
                            break
                if not touching:
                    orphan_labels.append({"netName": name, "x": lx, "y": ly, "type": lt})

            # Find unconnected pins (check wires, labels, AND other pin endpoints for power symbols)
            # Also checks T-junctions: pin on wire mid-segment
            unconnected_pins = []
            for px, py, ref, pnum in pin_points:
                connected = False
                for wx, wy in wire_endpoints:
                    if point_near(px, py, wx, wy):
                        connected = True
                        break
                if not connected:
                    # T-junction: pin endpoint on a wire mid-segment
                    if point_on_any_wire_segment(px, py):
                        connected = True
                if not connected:
                    for lx, ly, _, _ in label_points:
                        if point_near(px, py, lx, ly):
                            connected = True
                            break
                if not connected:
                    # Check if touching another component's pin (e.g. power symbol)
                    for opx, opy, oref, _ in pin_points:
                        if oref != ref and point_near(px, py, opx, opy):
                            connected = True
                            break
                if not connected:
                    unconnected_pins.append({"reference": ref, "pin": pnum, "x": px, "y": py})

            return {
                "success": True,
                "danglingWires": dangling_wires,
                "orphanLabels": orphan_labels,
                "unconnectedPins": unconnected_pins,
                "summary": {
                    "danglingWires": len(dangling_wires),
                    "orphanLabels": len(orphan_labels),
                    "unconnectedPins": len(unconnected_pins),
                },
            }

        except Exception as e:
            logger.error(f"Error in find_orphan_items: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _parse_schematic_geometry(self, schematic_path, compute_pin_endpoints=True):
        """Parse schematic file and return all geometry as structured data.

        Returns dict with keys: components, labels, wires, junctions, no_connects, content.
        Each component includes pin_endpoints (if compute_pin_endpoints=True) and body rect.
        Each label includes bounding box, connection point, and flag_width.
        """
        from pathlib import Path
        from commands.pin_locator import PinLocator
        import re
        import math

        schematic = SchematicManager.load_schematic(schematic_path)
        if not schematic:
            return None

        locator = self.pin_locator
        sch_file = Path(schematic_path)

        with open(schematic_path, "r", encoding="utf-8") as f:
            content = f.read()

        # ── Helper: extract body rectangle from lib_symbol ──
        def _get_body_rect(content_str, lib_id_str):
            """Find the body rectangle (fill background) for a lib_symbol.
            Returns (half_width, half_height) in symbol-local coords, or None."""
            escaped = re.escape(lib_id_str)
            sym_match = re.search(rf'\(symbol\s+"{escaped}"\s', content_str)
            if not sym_match:
                return None
            depth = 0
            i = sym_match.start()
            block_end = i
            while i < len(content_str):
                if content_str[i] == '(':
                    depth += 1
                elif content_str[i] == ')':
                    depth -= 1
                    if depth == 0:
                        block_end = i + 1
                        break
                i += 1
            block = content_str[sym_match.start():block_end]

            rect_pat = re.compile(
                r'\(rectangle\s+\(start\s+([\d.e+-]+)\s+([\d.e+-]+)\)\s+\(end\s+([\d.e+-]+)\s+([\d.e+-]+)\)'
                r'[^)]*\(fill\s+\(type\s+background\)\)'
            )
            best = None
            best_area = 0
            for rm in rect_pat.finditer(block):
                x1, y1 = float(rm.group(1)), float(rm.group(2))
                x2, y2 = float(rm.group(3)), float(rm.group(4))
                area = abs(x2 - x1) * abs(y2 - y1)
                if area > best_area:
                    best_area = area
                    best = (x1, y1, x2, y2)
            if best:
                x1, y1, x2, y2 = best
                hw = max(abs(x1), abs(x2))
                hh = max(abs(y1), abs(y2))
                return (hw, hh)
            return None

        # ── Build component bounding boxes ──
        components = []

        for symbol in schematic.symbol:
            if not hasattr(symbol.property, "Reference"):
                continue
            ref = symbol.property.Reference.value
            if ref.startswith("_TEMPLATE"):
                continue

            lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else ""
            position = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
            cx, cy = float(position[0]), float(position[1])
            sym_rot = float(position[2]) if len(position) > 2 else 0.0

            pins_def = locator.get_symbol_pins(sch_file, lib_id) if lib_id else {}
            pin_endpoints = []
            if pins_def:
                xs = [pd["x"] for pd in pins_def.values()]
                ys = [pd["y"] for pd in pins_def.values()]
                hw = max(abs(max(xs, default=0)), abs(min(xs, default=0)), 2.54)
                hh = max(abs(max(ys, default=0)), abs(min(ys, default=0)), 2.54)
                if sym_rot in (90, 270):
                    hw, hh = hh, hw

                if compute_pin_endpoints:
                    mirror_x = False
                    mirror_y = False
                    if hasattr(symbol, "mirror"):
                        mv = str(symbol.mirror.value) if hasattr(symbol.mirror, "value") else str(symbol.mirror)
                        mirror_x = "x" in mv
                        mirror_y = "y" in mv
                    for pd in pins_def.values():
                        prx = pd["x"]
                        pry = -pd["y"]
                        if mirror_x:
                            pry = -pry
                        if mirror_y:
                            prx = -prx
                        if sym_rot != 0:
                            rad = math.radians(sym_rot)
                            cr, sr = math.cos(rad), math.sin(rad)
                            prx, pry = prx * cr - pry * sr, prx * sr + pry * cr
                        pin_endpoints.append((round(cx + prx, 2), round(cy + pry, 2)))
            else:
                hw, hh = 2.54, 2.54

            body_hw, body_hh = hw, hh
            body_rect = _get_body_rect(content, lib_id) if lib_id else None
            if body_rect:
                body_hw, body_hh = body_rect
                if sym_rot in (90, 270):
                    body_hw, body_hh = body_hh, body_hw

            components.append({
                "ref": ref, "cx": cx, "cy": cy,
                "hw": hw, "hh": hh,
                "body_hw": body_hw, "body_hh": body_hh,
                "lib_id": lib_id,
                "pin_endpoints": pin_endpoints,
            })

        # ── Build label bounding boxes ──
        label_boxes = []
        for lt in ["label", "global_label", "hierarchical_label"]:
            lp = re.compile(
                rf'\({lt}\s+"([^"]*)"(?:\s+\(shape\s+[^)]*\))?\s+\(at\s+([\d.e+-]+)\s+([\d.e+-]+)\s*([\d.e+-]*)'
            )
            for m in lp.finditer(content):
                name = m.group(1)
                lx, ly = float(m.group(2)), float(m.group(3))
                angle = float(m.group(4)) if m.group(4) else 0

                char_w = 0.75
                text_len = len(name) * char_w
                body = 3.0 if lt != "label" else 0.5
                total_w = body + text_len
                total_h = 1.8

                norm_angle = int(angle) % 360
                if norm_angle in (0, 180):
                    x1 = lx
                    x2 = lx + total_w
                    y1 = ly - total_h / 2
                    y2 = ly + total_h / 2
                else:
                    x1 = lx - total_h / 2
                    x2 = lx + total_h / 2
                    y1 = ly
                    y2 = ly + total_w

                if norm_angle == 0:
                    conn_x, conn_y = lx + total_w, ly
                elif norm_angle == 180:
                    conn_x, conn_y = lx, ly
                elif norm_angle == 90:
                    conn_x, conn_y = lx, ly + total_w
                else:
                    conn_x, conn_y = lx, ly

                label_boxes.append({
                    "name": name, "type": lt,
                    "x": lx, "y": ly, "angle": angle,
                    "conn_x": conn_x, "conn_y": conn_y,
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "hw": (x2 - x1) / 2, "hh": (y2 - y1) / 2,
                    "mx": (x1 + x2) / 2, "my": (y1 + y2) / 2,
                    "flag_width": total_w,
                })

        # ── Collect wire segments ──
        wires = []
        wire_pat = re.compile(r'\(wire\b')
        xy_pat = re.compile(r'\(xy\s+([\d.e+-]+)\s+([\d.e+-]+)\)')
        for wm in wire_pat.finditer(content):
            depth = 0
            i = wm.start()
            block_end = i
            while i < len(content):
                if content[i] == '(':
                    depth += 1
                elif content[i] == ')':
                    depth -= 1
                    if depth == 0:
                        block_end = i + 1
                        break
                i += 1
            block = content[wm.start():block_end]
            xys = xy_pat.findall(block)
            if len(xys) >= 2:
                wires.append({
                    "x1": float(xys[0][0]), "y1": float(xys[0][1]),
                    "x2": float(xys[-1][0]), "y2": float(xys[-1][1]),
                })

        # ── Collect junctions ──
        junctions = []
        junc_pat = re.compile(r'\(junction\s+\(at\s+([\d.e+-]+)\s+([\d.e+-]+)\)')
        for jm in junc_pat.finditer(content):
            junctions.append({
                "x": float(jm.group(1)), "y": float(jm.group(2)),
            })

        # ── Collect no_connects ──
        no_connects = []
        nc_pat = re.compile(r'\(no_connect\s+\(at\s+([\d.e+-]+)\s+([\d.e+-]+)\)')
        for nm in nc_pat.finditer(content):
            no_connects.append({
                "x": float(nm.group(1)), "y": float(nm.group(2)),
            })

        return {
            "components": components,
            "labels": label_boxes,
            "wires": wires,
            "junctions": junctions,
            "no_connects": no_connects,
            "content": content,
        }

    def _handle_check_schematic_overlaps(self, params):
        """Check for visual overlaps: component-component, label-component,
        wire-label, and label-label. Returns structured results grouped by type."""
        logger.info("Checking schematic overlaps")
        try:
            schematic_path = params.get("schematicPath")
            clearance = float(params.get("clearance", 2.0))  # mm
            check_types = params.get("checkTypes") or [
                "component_component", "label_component", "wire_label", "label_label"
            ]
            suppress_pin_labels = params.get("suppressPinLabels", True)

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            import math

            geo = self._parse_schematic_geometry(schematic_path, compute_pin_endpoints=suppress_pin_labels)
            if geo is None:
                return {"success": False, "message": "Failed to load schematic"}

            components = geo["components"]
            label_boxes = geo["labels"]
            wires = geo["wires"]

            # ── Helper: AABB overlap test ──
            def aabb_overlap(ax1, ay1, ax2, ay2, bx1, by1, bx2, by2):
                """Returns overlap amount (negative = overlapping, positive = gap)."""
                gap_x = max(ax1, bx1) - min(ax2, bx2)
                gap_y = max(ay1, by1) - min(ay2, by2)
                return max(gap_x, gap_y)

            # ── Helper: does a wire segment intersect an AABB? ──
            def wire_intersects_aabb(wx1, wy1, wx2, wy2, bx1, by1, bx2, by2):
                """Test if wire segment intersects axis-aligned bounding box."""
                wire_x1, wire_x2 = min(wx1, wx2), max(wx1, wx2)
                wire_y1, wire_y2 = min(wy1, wy2), max(wy1, wy2)
                if wire_x2 < bx1 or wire_x1 > bx2 or wire_y2 < by1 or wire_y1 > by2:
                    return False

                if abs(wy1 - wy2) < 0.01:
                    return by1 <= wy1 <= by2 and wire_x1 <= bx2 and wire_x2 >= bx1
                if abs(wx1 - wx2) < 0.01:
                    return bx1 <= wx1 <= bx2 and wire_y1 <= by2 and wire_y2 >= by1

                return True

            overlaps = []

            # ── 1. Component vs component ──
            if "component_component" in check_types:
                for i in range(len(components)):
                    for j in range(i + 1, len(components)):
                        c1, c2 = components[i], components[j]
                        if c1["ref"].startswith("#PWR") or c2["ref"].startswith("#PWR"):
                            continue
                        if abs(c1["cx"] - c2["cx"]) < 0.01 and abs(c1["cy"] - c2["cy"]) < 0.01:
                            continue

                        gap = aabb_overlap(
                            c1["cx"] - c1["hw"], c1["cy"] - c1["hh"],
                            c1["cx"] + c1["hw"], c1["cy"] + c1["hh"],
                            c2["cx"] - c2["hw"], c2["cy"] - c2["hh"],
                            c2["cx"] + c2["hw"], c2["cy"] + c2["hh"],
                        )

                        if gap < clearance:
                            overlaps.append({
                                "type": "component_component",
                                "severity": "critical" if gap < 0 else "warning",
                                "gap_mm": round(gap, 1),
                                "component_a": {"ref": c1["ref"], "at": [c1["cx"], c1["cy"]]},
                                "component_b": {"ref": c2["ref"], "at": [c2["cx"], c2["cy"]]},
                            })

            # ── 2. Label vs component ──
            if "label_component" in check_types:
                pin_suppress_dist = 5.5
                for lb in label_boxes:
                    for comp in components:
                        if comp["ref"].startswith("#PWR"):
                            continue

                        # Step 1: Check label vs FULL bbox (pins + body).
                        # If no overlap with full bbox, skip entirely.
                        full_gap = aabb_overlap(
                            lb["x1"], lb["y1"], lb["x2"], lb["y2"],
                            comp["cx"] - comp["hw"], comp["cy"] - comp["hh"],
                            comp["cx"] + comp["hw"], comp["cy"] + comp["hh"],
                        )
                        if full_gap >= 0:
                            continue

                        # Step 2: Check label vs BODY rectangle (artwork outline).
                        bhw = comp["body_hw"]
                        bhh = comp["body_hh"]
                        body_gap = aabb_overlap(
                            lb["x1"], lb["y1"], lb["x2"], lb["y2"],
                            comp["cx"] - bhw, comp["cy"] - bhh,
                            comp["cx"] + bhw, comp["cy"] + bhh,
                        )

                        # Step 3: Decide suppress vs report.
                        # - Overlaps body rect → real overlap, always report
                        # - Overlaps only pin-stub area (outside body) → suppress
                        #   if near a pin endpoint (standard pin-endpoint label)
                        if body_gap >= 0:
                            # Label overlaps full bbox but NOT body — pin-stub area only
                            if suppress_pin_labels and comp.get("pin_endpoints"):
                                lx, ly = lb["x"], lb["y"]
                                is_pin_label = any(
                                    abs(lx - px) <= pin_suppress_dist and abs(ly - py) <= pin_suppress_dist
                                    for px, py in comp["pin_endpoints"]
                                )
                                if is_pin_label:
                                    continue

                        # Report: either overlaps body, or pin-stub overlap that
                        # wasn't suppressed
                        gap = body_gap if body_gap < 0 else full_gap
                        overlaps.append({
                                "type": "label_component",
                                "severity": "overlap" if body_gap < 0 else "pin_stub_overlap",
                                "gap_mm": round(gap, 1),
                                "label": {
                                    "netName": lb["name"], "labelType": lb["type"],
                                    "at": [lb["x"], lb["y"]], "angle": lb["angle"],
                                    "boundingBox": {"x1": round(lb["x1"], 2), "y1": round(lb["y1"], 2),
                                                    "x2": round(lb["x2"], 2), "y2": round(lb["y2"], 2)},
                                },
                                "component": {"ref": comp["ref"], "at": [comp["cx"], comp["cy"]]},
                            })

            # ── 3. Wire vs label ──
            if "wire_label" in check_types:
                for lb in label_boxes:
                    for w in wires:
                        # Skip wires that touch the label's electrical CONNECTION
                        # point (not the "at" position, which is the arrow tip).
                        lc_x, lc_y = lb["conn_x"], lb["conn_y"]
                        eps = 0.5
                        touches_start = abs(w["x1"] - lc_x) < eps and abs(w["y1"] - lc_y) < eps
                        touches_end = abs(w["x2"] - lc_x) < eps and abs(w["y2"] - lc_y) < eps
                        if touches_start or touches_end:
                            continue

                        if wire_intersects_aabb(
                            w["x1"], w["y1"], w["x2"], w["y2"],
                            lb["x1"], lb["y1"], lb["x2"], lb["y2"],
                        ):
                            # Compare wire length against label flag width.
                            # Standard pin stubs (2.54mm) are hidden under the flag
                            # body — suppress those. Longer wires that visibly exit
                            # both sides of the flag are real problems to report.
                            wire_len = math.sqrt(
                                (w["x2"] - w["x1"]) ** 2 + (w["y2"] - w["y1"]) ** 2
                            )
                            flag_w = lb.get("flag_width", 5.0)

                            if suppress_pin_labels and wire_len <= flag_w * 0.5:
                                # Wire shorter than half the flag — hidden pin stub, suppress
                                continue

                            overlaps.append({
                                "type": "wire_label",
                                "severity": "wire_through_label",
                                "wire_length_mm": round(wire_len, 1),
                                "flag_width_mm": round(flag_w, 1),
                                "label": {
                                    "netName": lb["name"], "labelType": lb["type"],
                                    "at": [lb["x"], lb["y"]], "angle": lb["angle"],
                                },
                                "wire": {
                                    "start": [w["x1"], w["y1"]],
                                    "end": [w["x2"], w["y2"]],
                                },
                            })

            # ── 4. Label vs label ──
            if "label_label" in check_types:
                for i in range(len(label_boxes)):
                    for j in range(i + 1, len(label_boxes)):
                        la, lb2 = label_boxes[i], label_boxes[j]
                        gap = aabb_overlap(
                            la["x1"], la["y1"], la["x2"], la["y2"],
                            lb2["x1"], lb2["y1"], lb2["x2"], lb2["y2"],
                        )
                        if gap < 0:
                            overlaps.append({
                                "type": "label_label",
                                "severity": "overlap",
                                "gap_mm": round(gap, 1),
                                "label_a": {
                                    "netName": la["name"], "labelType": la["type"],
                                    "at": [la["x"], la["y"]], "angle": la["angle"],
                                },
                                "label_b": {
                                    "netName": lb2["name"], "labelType": lb2["type"],
                                    "at": [lb2["x"], lb2["y"]], "angle": lb2["angle"],
                                },
                            })

            # ── Sort and cap output ──
            # Sort: critical first, then by gap
            severity_order = {"critical": 0, "overlap": 1, "wire_through_label": 2, "warning": 3}
            overlaps.sort(key=lambda x: (severity_order.get(x["severity"], 9), x.get("gap_mm", 0)))

            max_results = 50
            total = len(overlaps)
            suppressed = max(0, total - max_results)
            overlaps = overlaps[:max_results]

            # Count by type
            counts = {}
            for o in overlaps:
                t = o["type"]
                counts[t] = counts.get(t, 0) + 1

            summary_parts = [f"{v} {k.replace('_', '-')}" for k, v in counts.items()]
            summary = ", ".join(summary_parts) if summary_parts else "no overlaps"
            if suppressed > 0:
                summary += f" (+{suppressed} suppressed)"

            return {
                "success": True,
                "summary": summary,
                "overlaps": overlaps,
                "counts": counts,
                "total": total,
                "suppressed": suppressed,
            }

        except Exception as e:
            logger.error(f"Error checking overlaps: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_schematic_layout(self, params):
        """Return structured geometry for a region of the schematic: components
        (with body rects and pin endpoints), labels (with bounding boxes and
        connection points), wires, junctions, no-connects, and pre-computed
        overlaps within the region."""
        logger.info("Getting schematic layout")
        try:
            import math

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            region = params.get("region")  # {x, y, width, height} or None for full
            suppress_pin_labels = params.get("suppressPinLabels", True)

            geo = self._parse_schematic_geometry(schematic_path, compute_pin_endpoints=True)
            if geo is None:
                return {"success": False, "message": "Failed to load schematic"}

            # Region filter
            if region:
                rx = float(region.get("x", 0))
                ry = float(region.get("y", 0))
                rw = float(region.get("width", 100))
                rh = float(region.get("height", 100))
                rx2, ry2 = rx + rw, ry + rh
            else:
                rx, ry, rx2, ry2 = -1e9, -1e9, 1e9, 1e9

            def in_region_pt(x, y):
                return rx <= x <= rx2 and ry <= y <= ry2

            def aabb_intersects_region(x1, y1, x2, y2):
                return x1 <= rx2 and x2 >= rx and y1 <= ry2 and y2 >= ry

            # Filter components
            out_components = []
            for c in geo["components"]:
                cx, cy, hw, hh = c["cx"], c["cy"], c["hw"], c["hh"]
                if not aabb_intersects_region(cx - hw, cy - hh, cx + hw, cy + hh):
                    continue
                bhw, bhh = c["body_hw"], c["body_hh"]
                out_components.append({
                    "ref": c["ref"],
                    "at": [round(cx, 2), round(cy, 2)],
                    "lib_id": c["lib_id"],
                    "boundingBox": {
                        "x1": round(cx - hw, 2), "y1": round(cy - hh, 2),
                        "x2": round(cx + hw, 2), "y2": round(cy + hh, 2),
                    },
                    "bodyRect": {
                        "x1": round(cx - bhw, 2), "y1": round(cy - bhh, 2),
                        "x2": round(cx + bhw, 2), "y2": round(cy + bhh, 2),
                    },
                    "pinEndpoints": [
                        {"x": round(px, 2), "y": round(py, 2)}
                        for px, py in c["pin_endpoints"]
                    ],
                })

            # Filter labels
            out_labels = []
            for lb in geo["labels"]:
                if not aabb_intersects_region(lb["x1"], lb["y1"], lb["x2"], lb["y2"]):
                    continue
                out_labels.append({
                    "netName": lb["name"],
                    "labelType": lb["type"],
                    "at": [round(lb["x"], 2), round(lb["y"], 2)],
                    "angle": lb["angle"],
                    "connectionPoint": {
                        "x": round(lb["conn_x"], 2), "y": round(lb["conn_y"], 2),
                    },
                    "boundingBox": {
                        "x1": round(lb["x1"], 2), "y1": round(lb["y1"], 2),
                        "x2": round(lb["x2"], 2), "y2": round(lb["y2"], 2),
                    },
                    "flagWidth": round(lb["flag_width"], 2),
                })

            # Filter wires
            out_wires = []
            for w in geo["wires"]:
                wx1, wy1, wx2, wy2 = w["x1"], w["y1"], w["x2"], w["y2"]
                wmx1, wmx2 = min(wx1, wx2), max(wx1, wx2)
                wmy1, wmy2 = min(wy1, wy2), max(wy1, wy2)
                if not aabb_intersects_region(wmx1, wmy1, wmx2, wmy2):
                    continue
                wire_len = math.sqrt((wx2 - wx1) ** 2 + (wy2 - wy1) ** 2)
                out_wires.append({
                    "start": [round(wx1, 2), round(wy1, 2)],
                    "end": [round(wx2, 2), round(wy2, 2)],
                    "length_mm": round(wire_len, 2),
                })

            # Filter junctions
            out_junctions = [
                {"x": round(j["x"], 2), "y": round(j["y"], 2)}
                for j in geo["junctions"]
                if in_region_pt(j["x"], j["y"])
            ]

            # Filter no_connects
            out_no_connects = [
                {"x": round(nc["x"], 2), "y": round(nc["y"], 2)}
                for nc in geo["no_connects"]
                if in_region_pt(nc["x"], nc["y"])
            ]

            # ── Compute overlaps within region ──
            # Reuse the same overlap logic from check_schematic_overlaps
            # but only for items within the region.
            def aabb_overlap(ax1, ay1, ax2, ay2, bx1, by1, bx2, by2):
                gap_x = max(ax1, bx1) - min(ax2, bx2)
                gap_y = max(ay1, by1) - min(ay2, by2)
                return max(gap_x, gap_y)

            def wire_intersects_aabb(wx1, wy1, wx2, wy2, bx1, by1, bx2, by2):
                wmx1, wmx2 = min(wx1, wx2), max(wx1, wx2)
                wmy1, wmy2 = min(wy1, wy2), max(wy1, wy2)
                if wmx2 < bx1 or wmx1 > bx2 or wmy2 < by1 or wmy1 > by2:
                    return False
                if abs(wy1 - wy2) < 0.01:
                    return by1 <= wy1 <= by2 and wmx1 <= bx2 and wmx2 >= bx1
                if abs(wx1 - wx2) < 0.01:
                    return bx1 <= wx1 <= bx2 and wmy1 <= by2 and wmy2 >= by1
                return True

            overlaps = []

            # Filter geo data to region for overlap checks
            r_comps = [c for c in geo["components"]
                       if aabb_intersects_region(c["cx"] - c["hw"], c["cy"] - c["hh"],
                                                 c["cx"] + c["hw"], c["cy"] + c["hh"])]
            r_labels = [lb for lb in geo["labels"]
                        if aabb_intersects_region(lb["x1"], lb["y1"], lb["x2"], lb["y2"])]
            r_wires = geo["wires"]  # check all wires — they may cross into region

            # Wire vs label overlaps
            for lb in r_labels:
                for w in r_wires:
                    lc_x, lc_y = lb["conn_x"], lb["conn_y"]
                    eps = 0.5
                    if (abs(w["x1"] - lc_x) < eps and abs(w["y1"] - lc_y) < eps) or \
                       (abs(w["x2"] - lc_x) < eps and abs(w["y2"] - lc_y) < eps):
                        continue

                    if wire_intersects_aabb(
                        w["x1"], w["y1"], w["x2"], w["y2"],
                        lb["x1"], lb["y1"], lb["x2"], lb["y2"],
                    ):
                        wire_len = math.sqrt(
                            (w["x2"] - w["x1"]) ** 2 + (w["y2"] - w["y1"]) ** 2
                        )
                        flag_w = lb.get("flag_width", 5.0)

                        if suppress_pin_labels and wire_len <= flag_w * 0.5:
                            continue

                        overlaps.append({
                            "type": "wire_through_label",
                            "wire_length_mm": round(wire_len, 1),
                            "flag_width_mm": round(flag_w, 1),
                            "label": lb["name"],
                            "wire": {
                                "start": [w["x1"], w["y1"]],
                                "end": [w["x2"], w["y2"]],
                            },
                        })

            # Label vs component overlaps
            pin_suppress_dist = 5.5
            for lb in r_labels:
                for comp in r_comps:
                    if comp["ref"].startswith("#PWR"):
                        continue
                    full_gap = aabb_overlap(
                        lb["x1"], lb["y1"], lb["x2"], lb["y2"],
                        comp["cx"] - comp["hw"], comp["cy"] - comp["hh"],
                        comp["cx"] + comp["hw"], comp["cy"] + comp["hh"],
                    )
                    if full_gap >= 0:
                        continue
                    bhw, bhh = comp["body_hw"], comp["body_hh"]
                    body_gap = aabb_overlap(
                        lb["x1"], lb["y1"], lb["x2"], lb["y2"],
                        comp["cx"] - bhw, comp["cy"] - bhh,
                        comp["cx"] + bhw, comp["cy"] + bhh,
                    )
                    if body_gap >= 0 and suppress_pin_labels and comp.get("pin_endpoints"):
                        lx, ly = lb["x"], lb["y"]
                        if any(abs(lx - px) <= pin_suppress_dist and abs(ly - py) <= pin_suppress_dist
                               for px, py in comp["pin_endpoints"]):
                            continue
                    overlaps.append({
                        "type": "label_component_overlap",
                        "label": lb["name"],
                        "component": comp["ref"],
                        "overlaps_body": body_gap < 0,
                    })

            return {
                "success": True,
                "region": {"x": rx, "y": ry, "x2": rx2, "y2": ry2} if region else "full",
                "components": out_components,
                "labels": out_labels,
                "wires": out_wires,
                "junctions": out_junctions,
                "no_connects": out_no_connects,
                "overlaps": overlaps,
                "counts": {
                    "components": len(out_components),
                    "labels": len(out_labels),
                    "wires": len(out_wires),
                    "junctions": len(out_junctions),
                    "no_connects": len(out_no_connects),
                    "overlaps": len(overlaps),
                },
            }

        except Exception as e:
            logger.error(f"Error getting schematic layout: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_pin_connections(self, params):
        """For a given component, show each pin and what it's connected to."""
        logger.info("Getting pin connections")
        try:
            import re
            from pathlib import Path
            from commands.pin_locator import PinLocator
            import math

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")

            if not schematic_path or not reference:
                return {"success": False, "message": "schematicPath and reference are required"}

            sch_file = Path(schematic_path)
            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            locator = self.pin_locator
            tolerance = 0.5

            # Find the symbol
            target = None
            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                if symbol.property.Reference.value == reference:
                    target = symbol
                    break
            if not target:
                return {"success": False, "message": f"Component {reference} not found"}

            lib_id = target.lib_id.value if hasattr(target, "lib_id") else ""
            position = target.at.value if hasattr(target, "at") else [0, 0, 0]
            sx, sy = float(position[0]), float(position[1])
            sym_rot = float(position[2]) if len(position) > 2 else 0.0

            pins_def = locator.get_symbol_pins(sch_file, lib_id) if lib_id else {}

            # Extract mirror transforms for pin math
            mirror_x = False
            mirror_y = False
            if hasattr(target, "mirror"):
                mirror_val = str(target.mirror.value) if hasattr(target.mirror, 'value') else str(target.mirror)
                mirror_x = "x" in mirror_val
                mirror_y = "y" in mirror_val

            # Get wire endpoints and labels from file
            wire_endpoints = []
            wire_pat = re.compile(r'\(wire\b')
            for m in wire_pat.finditer(content):
                pos = m.start()
                depth = 0
                end = pos
                while end < len(content):
                    if content[end] == "(": depth += 1
                    elif content[end] == ")":
                        depth -= 1
                        if depth == 0: end += 1; break
                    end += 1
                block = content[pos:end]
                xy_ms = re.findall(r'\(xy\s+([\d.e+-]+)\s+([\d.e+-]+)\)', block)
                for xm in xy_ms:
                    wire_endpoints.append((float(xm[0]), float(xm[1])))

            label_map = []
            for lt in ["label", "global_label", "hierarchical_label"]:
                lp = re.compile(rf'\({lt}\s+"([^"]*)"(?:\s+\(shape\s+[^)]*\))?\s+\(at\s+([\d.e+-]+)\s+([\d.e+-]+)')
                for m in lp.finditer(content):
                    label_map.append((float(m.group(2)), float(m.group(3)), m.group(1), lt))

            # Collect power symbol pin positions (these act as net sources)
            # Power symbols have lib_id "power:XXX" — their Value is the net name
            power_pins = []  # [(x, y, net_name)]
            lib_sym_start = content.find("(lib_symbols")
            lib_sym_end_pos = -1
            if lib_sym_start >= 0:
                depth_ls = 0
                for _i in range(lib_sym_start, len(content)):
                    if content[_i] == "(": depth_ls += 1
                    elif content[_i] == ")":
                        depth_ls -= 1
                        if depth_ls == 0:
                            lib_sym_end_pos = _i
                            break

            pwr_sym_pat = re.compile(r'\(symbol\s+\(lib_id\s+"power:([^"]+)"\)')
            for pm in pwr_sym_pat.finditer(content):
                ppos = pm.start()
                # Skip if inside lib_symbols
                if lib_sym_start >= 0 and lib_sym_start <= ppos <= lib_sym_end_pos:
                    continue
                # Find the (at X Y ...) of this power symbol
                pend = ppos + 200  # power symbol blocks are small
                if pend > len(content): pend = len(content)
                snippet = content[ppos:pend]
                at_m = re.search(r'\(at\s+([\d.e+-]+)\s+([\d.e+-]+)', snippet)
                val_m = re.search(r'\(property\s+"Value"\s+"([^"]*)"', snippet)
                if at_m:
                    px, py = float(at_m.group(1)), float(at_m.group(2))
                    pnet = val_m.group(1) if val_m else pm.group(1)
                    power_pins.append((px, py, pnet))

            # For each pin, determine connection status
            pin_results = []
            for pin_num, pd in (pins_def or {}).items():
                prx, pry = pd["x"], -pd["y"]
                if mirror_x:
                    pry = -pry
                if mirror_y:
                    prx = -prx
                if sym_rot != 0:
                    prx, pry = PinLocator.rotate_point(prx, pry, sym_rot)
                # Pin (at) IS the endpoint — no length math
                ex = round(sx + prx, 4)
                ey = round(sy + pry, 4)

                # Check what's at this endpoint and along connected wires
                net_name = None
                has_wire = False

                # Collect all wire points reachable from this pin endpoint
                connected_points = set()
                connected_points.add((round(ex, 1), round(ey, 1)))
                for wx, wy in wire_endpoints:
                    if abs(ex - wx) < tolerance and abs(ey - wy) < tolerance:
                        has_wire = True
                        connected_points.add((round(wx, 1), round(wy, 1)))

                # Also check T-junctions: pin endpoint on mid-segment of a wire
                if not has_wire:
                    for wi in range(0, len(wire_endpoints), 2):
                        if wi + 1 >= len(wire_endpoints):
                            break
                        w1x, w1y = wire_endpoints[wi]
                        w2x, w2y = wire_endpoints[wi + 1]
                        if _point_on_wire_segment(ex, ey, w1x, w1y, w2x, w2y, tolerance):
                            has_wire = True
                            connected_points.add((round(w1x, 1), round(w1y, 1)))
                            connected_points.add((round(w2x, 1), round(w2y, 1)))

                # Follow wires transitively to find all connected points
                # Includes T-junction detection
                if has_wire:
                    changed = True
                    while changed:
                        changed = False
                        for wi in range(0, len(wire_endpoints), 2):
                            if wi + 1 >= len(wire_endpoints):
                                break
                            w1 = (round(wire_endpoints[wi][0], 1), round(wire_endpoints[wi][1], 1))
                            w2 = (round(wire_endpoints[wi+1][0], 1), round(wire_endpoints[wi+1][1], 1))
                            w1_in = w1 in connected_points
                            w2_in = w2 in connected_points
                            if w1_in and not w2_in:
                                connected_points.add(w2)
                                changed = True
                            elif w2_in and not w1_in:
                                connected_points.add(w1)
                                changed = True
                            elif not w1_in and not w2_in:
                                # Forward T-junction: does a connected point lie on this wire mid-segment?
                                w1x, w1y = wire_endpoints[wi]
                                w2x, w2y = wire_endpoints[wi + 1]
                                for cp in list(connected_points):
                                    if _point_on_wire_segment(cp[0], cp[1], w1x, w1y, w2x, w2y, tolerance):
                                        connected_points.add(w1)
                                        connected_points.add(w2)
                                        changed = True
                                        break
                            # Reverse T-junction: does this wire's endpoint land on a connected wire's mid-segment?
                            if not changed and (w1_in or w2_in):
                                pass  # Already handled above
                            elif not changed:
                                w1x, w1y = wire_endpoints[wi]
                                w2x, w2y = wire_endpoints[wi + 1]
                                for wj in range(0, len(wire_endpoints), 2):
                                    if wj == wi or wj + 1 >= len(wire_endpoints):
                                        continue
                                    cw1 = (round(wire_endpoints[wj][0], 1), round(wire_endpoints[wj][1], 1))
                                    cw2 = (round(wire_endpoints[wj+1][0], 1), round(wire_endpoints[wj+1][1], 1))
                                    if cw1 not in connected_points and cw2 not in connected_points:
                                        continue
                                    cw1x, cw1y = wire_endpoints[wj]
                                    cw2x, cw2y = wire_endpoints[wj + 1]
                                    if _point_on_wire_segment(w1x, w1y, cw1x, cw1y, cw2x, cw2y, tolerance) or \
                                       _point_on_wire_segment(w2x, w2y, cw1x, cw1y, cw2x, cw2y, tolerance):
                                        connected_points.add(w1)
                                        connected_points.add(w2)
                                        changed = True
                                        break

                # Check labels at any connected point
                for lx, ly, name, lt in label_map:
                    lkey = (round(lx, 1), round(ly, 1))
                    if lkey in connected_points or (abs(ex - lx) < tolerance and abs(ey - ly) < tolerance):
                        net_name = name
                        break

                # Check power symbols at any connected point
                if not net_name:
                    for ppx, ppy, pnet in power_pins:
                        pkey = (round(ppx, 1), round(ppy, 1))
                        if pkey in connected_points or (abs(ex - ppx) < tolerance and abs(ey - ppy) < tolerance):
                            net_name = pnet
                            break

                status = "unconnected"
                if net_name:
                    status = f"net:{net_name}"
                elif has_wire:
                    status = "wire (no label)"

                pin_results.append({
                    "pin": pin_num,
                    "name": pd.get("name", pin_num),
                    "endpoint": {"x": ex, "y": ey},
                    "status": status,
                    "netName": net_name,
                })

            return {
                "success": True,
                "reference": reference,
                "pins": pin_results,
            }

        except Exception as e:
            logger.error(f"Error in get_pin_connections: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_trace_from_point(self, params):
        """Trace all electrically connected elements from a coordinate."""
        logger.info("Tracing from point")
        try:
            schematic_path = params.get("schematicPath")
            x = float(params.get("x", 0))
            y = float(params.get("y", 0))
            tolerance = float(params.get("tolerance", 0.05))

            if not schematic_path or not os.path.exists(schematic_path):
                return {"success": False, "message": "schematicPath is required and must exist"}

            # Parse geometry using existing helper
            geometry = self._parse_schematic_geometry(schematic_path)
            if geometry is None:
                return {"success": False, "message": "Failed to load schematic"}

            wires = geometry.get("wires", [])
            junctions = geometry.get("junctions", [])
            labels = geometry.get("labels", [])
            components = geometry.get("components", [])

            # Build wire list as (x1, y1, x2, y2) tuples
            wire_segments = []
            for w in wires:
                if isinstance(w, dict):
                    wire_segments.append((w["x1"], w["y1"], w["x2"], w["y2"]))
                elif isinstance(w, (list, tuple)) and len(w) >= 4:
                    wire_segments.append((w[0], w[1], w[2], w[3]))

            # Build pin list from components' pin_endpoints
            all_pins = []  # [(x, y, ref)]
            for comp in components:
                ref = comp.get("ref", "")
                for ep in comp.get("pin_endpoints", []):
                    if isinstance(ep, (list, tuple)) and len(ep) >= 2:
                        all_pins.append((float(ep[0]), float(ep[1]), ref))

            # Flood fill from starting point
            visited_points = set()
            queue = [(x, y)]
            traced_wires = []
            traced_junctions = []
            traced_labels = []
            traced_pins = []
            dead_ends = []

            while queue:
                px, py = queue.pop(0)
                # Round for set membership
                key = (round(px, 2), round(py, 2))
                if key in visited_points:
                    continue
                visited_points.add(key)

                # Find connected wires (endpoints + T-junctions)
                connections = _find_connected_wires(px, py, wire_segments, tolerance)

                if not connections:
                    # Check if this point is a pin, label, or junction
                    is_something = False
                    for pin_x, pin_y, _ref in all_pins:
                        if abs(px - pin_x) < tolerance and abs(py - pin_y) < tolerance:
                            is_something = True
                            break
                    if not is_something:
                        for lbl in labels:
                            lx = float(lbl.get("x", 0))
                            ly = float(lbl.get("y", 0))
                            if abs(px - lx) < tolerance and abs(py - ly) < tolerance:
                                is_something = True
                                break
                    if not is_something:
                        dead_ends.append({"x": px, "y": py})
                    continue

                for wire_idx, pos_type in connections:
                    w = wire_segments[wire_idx]
                    wire_info = {"x1": w[0], "y1": w[1], "x2": w[2], "y2": w[3], "connection": pos_type}
                    if wire_info not in traced_wires:
                        traced_wires.append(wire_info)

                    # Add the other endpoint(s) to queue
                    if pos_type == 'start':
                        queue.append((float(w[2]), float(w[3])))
                    elif pos_type == 'end':
                        queue.append((float(w[0]), float(w[1])))
                    elif pos_type == 'mid':
                        # T-junction: trace to both endpoints
                        queue.append((float(w[0]), float(w[1])))
                        queue.append((float(w[2]), float(w[3])))

                # Check for labels at this point
                for lbl in labels:
                    lx = float(lbl.get("x", 0))
                    ly = float(lbl.get("y", 0))
                    if abs(px - lx) < tolerance and abs(py - ly) < tolerance:
                        lbl_info = {"name": lbl.get("name", ""), "type": lbl.get("type", ""), "x": lx, "y": ly}
                        if lbl_info not in traced_labels:
                            traced_labels.append(lbl_info)

                # Check for pins at this point
                for pin_x, pin_y, pin_ref in all_pins:
                    if abs(px - pin_x) < tolerance and abs(py - pin_y) < tolerance:
                        pin_info = {"ref": pin_ref, "x": pin_x, "y": pin_y}
                        if pin_info not in traced_pins:
                            traced_pins.append(pin_info)

                # Check for junctions at this point
                for junc in junctions:
                    jx = float(junc.get("x", 0))
                    jy = float(junc.get("y", 0))
                    if abs(px - jx) < tolerance and abs(py - jy) < tolerance:
                        junc_info = {"x": jx, "y": jy}
                        if junc_info not in traced_junctions:
                            traced_junctions.append(junc_info)

            return {
                "success": True,
                "start": {"x": x, "y": y},
                "wires": traced_wires,
                "junctions": traced_junctions,
                "labels": traced_labels,
                "pins": traced_pins,
                "dead_ends": dead_ends,
                "total_points_visited": len(visited_points),
            }
        except Exception as e:
            logger.error(f"Error in trace_from_point: {e}")
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_split_wire_at_point(self, params):
        """Split a wire at a given point, creating two wire segments."""
        logger.info("Splitting wire at point")
        try:
            schematic_path = params.get("schematicPath")
            split_x = float(params.get("x", 0))
            split_y = float(params.get("y", 0))
            add_junction = params.get("addJunction", True)
            tolerance = float(params.get("tolerance", 0.05))

            if not schematic_path or not os.path.exists(schematic_path):
                return {"success": False, "message": "schematicPath is required and must exist"}

            from commands.sexp_writer import split_wire_at_point
            result = split_wire_at_point(schematic_path, split_x, split_y, add_junction, tolerance)
            if result:
                return {
                    "success": True,
                    "message": f"Wire split at ({split_x}, {split_y})",
                    "split_point": {"x": split_x, "y": split_y},
                }
            else:
                return {"success": False, "message": f"No wire found at ({split_x}, {split_y}) to split"}
        except Exception as e:
            logger.error(f"Error in split_wire_at_point: {e}")
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_schematic_view(self, params):
        """Get a rasterised image of the schematic (SVG export → optional PNG conversion)"""
        logger.info("Getting schematic view")
        import subprocess
        import tempfile
        import base64

        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path or not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            fmt = params.get("format", "png")
            width = params.get("width", 1200)
            height = params.get("height", 900)
            region = params.get("region")  # {x, y, width, height} in schematic mm

            # Step 1: Export schematic to SVG via kicad-cli
            with tempfile.TemporaryDirectory() as tmpdir:
                svg_path = os.path.join(tmpdir, "schematic.svg")
                cmd = [
                    "kicad-cli",
                    "sch",
                    "export",
                    "svg",
                    "--output",
                    tmpdir,
                    "--no-background-color",
                    schematic_path,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

                if result.returncode != 0:
                    return {
                        "success": False,
                        "message": f"kicad-cli SVG export failed: {result.stderr}",
                    }

                # kicad-cli may name the file after the schematic, find it
                import glob

                svg_files = glob.glob(os.path.join(tmpdir, "*.svg"))
                if not svg_files:
                    return {
                        "success": False,
                        "message": "No SVG file produced by kicad-cli",
                    }
                svg_path = svg_files[0]

                # Step 1.5: If region specified, crop SVG by modifying viewBox
                if region:
                    import re as _re
                    with open(svg_path, "r", encoding="utf-8") as f:
                        svg_content = f.read()

                    rx = float(region.get("x", 0))
                    ry = float(region.get("y", 0))
                    rw = float(region.get("width", 50))
                    rh = float(region.get("height", 50))

                    # KiCad SVG uses mm units with a scale factor (typically 1 SVG unit = 1mm,
                    # but the viewBox may have an offset). Parse existing viewBox to find the
                    # coordinate system, then replace with our region.
                    # KiCad SVGs use style="...; width:NNmm; height:NNmm" and viewBox="x y w h"
                    # The viewBox coordinates are in internal units (mils or mm depending on version).
                    # KiCad 9 SVGs use mm in viewBox directly.

                    # Replace viewBox with our region
                    svg_content = _re.sub(
                        r'viewBox="[^"]*"',
                        f'viewBox="{rx} {ry} {rw} {rh}"',
                        svg_content,
                    )
                    # Also update width/height attributes to match aspect ratio
                    svg_content = _re.sub(
                        r'width="[^"]*"',
                        f'width="{rw}mm"',
                        svg_content,
                        count=1,
                    )
                    svg_content = _re.sub(
                        r'height="[^"]*"',
                        f'height="{rh}mm"',
                        svg_content,
                        count=1,
                    )

                    with open(svg_path, "w", encoding="utf-8") as f:
                        f.write(svg_content)

                if fmt == "svg":
                    with open(svg_path, "r", encoding="utf-8") as f:
                        svg_data = f.read()
                    return {"success": True, "imageData": svg_data, "format": "svg"}

                # Step 2: Convert SVG to PNG using cairosvg
                try:
                    from cairosvg import svg2png
                except ImportError:
                    # Fallback: return SVG data with a note
                    with open(svg_path, "r", encoding="utf-8") as f:
                        svg_data = f.read()
                    return {
                        "success": True,
                        "imageData": svg_data,
                        "format": "svg",
                        "message": "cairosvg not installed — returning SVG instead of PNG. Install with: pip install cairosvg",
                    }

                png_data = svg2png(
                    url=svg_path, output_width=width, output_height=height
                )

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
            logger.error(f"Error getting schematic view: {e}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_components(self, params):
        """List all components in a schematic"""
        logger.info("Listing schematic components")
        try:
            from pathlib import Path
            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Optional filters
            filter_params = params.get("filter", {})
            lib_id_filter = filter_params.get("libId", "")
            ref_prefix_filter = filter_params.get("referencePrefix", "")

            # Create PinLocator once; pin_definition_cache is shared across calls
            # so get_symbol_pins only parses the file once per lib_id.
            locator = self.pin_locator
            components = []

            # Pre-cache: parse pin definitions from the schematic file once
            # (get_symbol_pins reads the file but caches by lib_id, so subsequent
            # calls for the same lib_id are free)
            import math

            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                # Skip template symbols
                if ref.startswith("_TEMPLATE"):
                    continue

                lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else ""

                # Apply filters
                if lib_id_filter and lib_id_filter not in lib_id:
                    continue
                if ref_prefix_filter and not ref.startswith(ref_prefix_filter):
                    continue

                value = (
                    symbol.property.Value.value
                    if hasattr(symbol.property, "Value")
                    else ""
                )
                footprint = (
                    symbol.property.Footprint.value
                    if hasattr(symbol.property, "Footprint")
                    else ""
                )
                position = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                uuid_val = symbol.uuid.value if hasattr(symbol, "uuid") else ""

                sym_x = float(position[0])
                sym_y = float(position[1])
                sym_rot = float(position[2]) if len(position) > 2 else 0.0

                comp = {
                    "reference": ref,
                    "libId": lib_id,
                    "value": value,
                    "footprint": footprint,
                    "position": {"x": sym_x, "y": sym_y},
                    "rotation": sym_rot,
                    "uuid": str(uuid_val),
                }

                # Compute pin positions inline using cached pin definitions
                # (avoids re-reading the schematic file for every component)
                try:
                    pins_def = locator.get_symbol_pins(sch_file, lib_id) if lib_id else {}
                    if pins_def:
                        # Extract mirror transforms
                        _mirror_x = False
                        _mirror_y = False
                        if hasattr(symbol, "mirror"):
                            _mv = str(symbol.mirror.value) if hasattr(symbol.mirror, 'value') else str(symbol.mirror)
                            _mirror_x = "x" in _mv
                            _mirror_y = "y" in _mv
                        pin_list = []
                        for pin_num, pin_data in pins_def.items():
                            pin_rel_x = pin_data["x"]
                            pin_rel_y = -pin_data["y"]  # Y-negate: symbol-local Y-up → schematic Y-down
                            if _mirror_x:
                                pin_rel_y = -pin_rel_y
                            if _mirror_y:
                                pin_rel_x = -pin_rel_x
                            # Apply symbol rotation
                            if sym_rot != 0:
                                pin_rel_x, pin_rel_y = PinLocator.rotate_point(
                                    pin_rel_x, pin_rel_y, sym_rot
                                )
                            # Pin (at) IS the endpoint — no length math
                            ep_x = round(sym_x + pin_rel_x, 4)
                            ep_y = round(sym_y + pin_rel_y, 4)

                            pin_info = {
                                "number": pin_num,
                                "name": pin_data.get("name", pin_num),
                                "position": {"x": ep_x, "y": ep_y},
                            }
                            pin_list.append(pin_info)
                        comp["pins"] = pin_list
                except Exception:
                    pass  # Pin lookup is best-effort

                components.append(comp)

            return {"success": True, "components": components, "count": len(components)}

        except Exception as e:
            logger.error(f"Error listing schematic components: {e}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_nets(self, params):
        """List all nets in a schematic with label positions.

        This is a fast operation that only collects net names and their label
        locations.  For detailed connection tracing use get_net_connections
        on individual nets.
        """
        logger.info("Listing schematic nets")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Collect net names and their label positions (fast — no wire tracing)
            net_labels = {}  # net_name -> list of {x, y, type}
            if hasattr(schematic, "label"):
                for label in schematic.label:
                    if hasattr(label, "value"):
                        name = label.value
                        pos = {}
                        if hasattr(label, "at") and hasattr(label.at, "value"):
                            p = label.at.value
                            pos = {"x": float(p[0]), "y": float(p[1])}
                        if name not in net_labels:
                            net_labels[name] = []
                        net_labels[name].append({**pos, "type": "label"})
            if hasattr(schematic, "global_label"):
                for label in schematic.global_label:
                    if hasattr(label, "value"):
                        name = label.value
                        pos = {}
                        if hasattr(label, "at") and hasattr(label.at, "value"):
                            p = label.at.value
                            pos = {"x": float(p[0]), "y": float(p[1])}
                        if name not in net_labels:
                            net_labels[name] = []
                        net_labels[name].append({**pos, "type": "global_label"})

            nets = []
            for net_name in sorted(net_labels):
                nets.append(
                    {
                        "name": net_name,
                        "labelCount": len(net_labels[net_name]),
                        "labels": net_labels[net_name],
                    }
                )

            return {"success": True, "nets": nets, "count": len(nets)}

        except Exception as e:
            logger.error(f"Error listing schematic nets: {e}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_wires(self, params):
        """List all wires in a schematic"""
        logger.info("Listing schematic wires")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            wires = []
            if hasattr(schematic, "wire"):
                for wire in schematic.wire:
                    if hasattr(wire, "pts") and hasattr(wire.pts, "xy"):
                        points = []
                        for point in wire.pts.xy:
                            if hasattr(point, "value"):
                                points.append(
                                    {
                                        "x": float(point.value[0]),
                                        "y": float(point.value[1]),
                                    }
                                )

                        if len(points) >= 2:
                            wires.append(
                                {
                                    "start": points[0],
                                    "end": points[-1],
                                }
                            )

            return {"success": True, "wires": wires, "count": len(wires)}

        except Exception as e:
            logger.error(f"Error listing schematic wires: {e}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_labels(self, params):
        """List all net labels and power flags in a schematic, with geometry."""
        logger.info("Listing schematic labels")
        try:
            import math

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            def _label_geometry(name, lx, ly, angle, label_type):
                """Compute connectionPoint and boundingBox for a label."""
                # Compute bounding box from position + angle + text length
                char_w = 0.75  # mm per char
                text_len = len(name) * char_w
                if label_type == "global":
                    body = 3.0
                elif label_type == "hierarchical":
                    body = 3.0
                else:
                    body = 0.5
                total_w = body + text_len
                total_h = 1.8

                # KiCad renders labels with (at) as top-left of the shape.
                # Body always extends RIGHT (+x) for horizontal, DOWN (+y) for vertical.
                norm_angle = int(angle) % 360
                if norm_angle in (0, 180):
                    x1 = lx
                    x2 = lx + total_w
                    y1 = ly - total_h / 2
                    y2 = ly + total_h / 2
                else:
                    x1 = lx - total_h / 2
                    x2 = lx + total_h / 2
                    y1 = ly
                    y2 = ly + total_w

                # Connection point: electrical end where wires attach.
                # 0°: right end. 180°: left end (=at). 90°: bottom. 270°: top (=at).
                if norm_angle == 0:
                    conn = {"x": round(lx + total_w, 2), "y": ly}
                elif norm_angle == 90:
                    conn = {"x": lx, "y": round(ly + total_w, 2)}
                else:  # 180, 270
                    conn = {"x": lx, "y": ly}

                corners_x = [x1, x2]
                corners_y = [y1, y2]
                bbox = {
                    "x1": round(min(corners_x), 2),
                    "y1": round(min(corners_y), 2),
                    "x2": round(max(corners_x), 2),
                    "y2": round(max(corners_y), 2),
                }
                return conn, bbox

            labels = []

            # Regular labels
            if hasattr(schematic, "label"):
                for label in schematic.label:
                    if hasattr(label, "value"):
                        pos = (
                            label.at.value
                            if hasattr(label, "at") and hasattr(label.at, "value")
                            else [0, 0, 0]
                        )
                        lx, ly = float(pos[0]), float(pos[1])
                        angle = float(pos[2]) if len(pos) > 2 else 0
                        conn, bbox = _label_geometry(label.value, lx, ly, angle, "net")
                        labels.append(
                            {
                                "name": label.value,
                                "type": "net",
                                "position": {"x": lx, "y": ly},
                                "angle": angle,
                                "connectionPoint": conn,
                                "boundingBox": bbox,
                            }
                        )

            # Global labels
            if hasattr(schematic, "global_label"):
                for label in schematic.global_label:
                    if hasattr(label, "value"):
                        pos = (
                            label.at.value
                            if hasattr(label, "at") and hasattr(label.at, "value")
                            else [0, 0, 0]
                        )
                        lx, ly = float(pos[0]), float(pos[1])
                        angle = float(pos[2]) if len(pos) > 2 else 0
                        conn, bbox = _label_geometry(label.value, lx, ly, angle, "global")
                        labels.append(
                            {
                                "name": label.value,
                                "type": "global",
                                "position": {"x": lx, "y": ly},
                                "angle": angle,
                                "connectionPoint": conn,
                                "boundingBox": bbox,
                            }
                        )

            # Power symbols (components with power flag)
            if hasattr(schematic, "symbol"):
                for symbol in schematic.symbol:
                    if not hasattr(symbol.property, "Reference"):
                        continue
                    ref = symbol.property.Reference.value
                    if ref.startswith("_TEMPLATE"):
                        continue
                    if not ref.startswith("#PWR"):
                        continue
                    value = (
                        symbol.property.Value.value
                        if hasattr(symbol.property, "Value")
                        else ref
                    )
                    pos = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                    lx, ly = float(pos[0]), float(pos[1])
                    angle = float(pos[2]) if len(pos) > 2 else 0
                    labels.append(
                        {
                            "name": value,
                            "type": "power",
                            "position": {"x": lx, "y": ly},
                            "angle": angle,
                            "connectionPoint": {"x": lx, "y": ly},
                        }
                    )

            return {"success": True, "labels": labels, "count": len(labels)}

        except Exception as e:
            logger.error(f"Error listing schematic labels: {e}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_move_schematic_component(self, params):
        """Move a schematic component to a new position"""
        logger.info("Moving schematic component")
        try:
            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            position = params.get("position", {})
            new_x = position.get("x")
            new_y = position.get("y")

            if not schematic_path or not reference:
                return {
                    "success": False,
                    "message": "schematicPath and reference are required",
                }
            if new_x is None or new_y is None:
                return {
                    "success": False,
                    "message": "position with x and y is required",
                }

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Find the symbol
            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                if symbol.property.Reference.value == reference:
                    old_pos = list(symbol.at.value)
                    old_position = {"x": float(old_pos[0]), "y": float(old_pos[1])}

                    # Preserve rotation (third element)
                    rotation = float(old_pos[2]) if len(old_pos) > 2 else 0

                    # Calculate delta between old and new positions
                    dx = new_x - float(old_pos[0])
                    dy = new_y - float(old_pos[1])

                    # Move the symbol itself
                    symbol.at.value = [new_x, new_y, rotation]

                    # Move all property fields by the same delta
                    for prop_name in ["Reference", "Value", "Footprint", "Datasheet"]:
                        if hasattr(symbol.property, prop_name):
                            prop = getattr(symbol.property, prop_name)
                            if hasattr(prop, "at") and hasattr(prop.at, "value"):
                                try:
                                    prop_pos = list(prop.at.value)
                                    prop_pos[0] = float(prop_pos[0]) + dx
                                    prop_pos[1] = float(prop_pos[1]) + dy
                                    prop.at.value = prop_pos
                                except (TypeError, IndexError):
                                    pass

                    SchematicManager.save_schematic(schematic, schematic_path)
                    return {
                        "success": True,
                        "oldPosition": old_position,
                        "newPosition": {"x": new_x, "y": new_y},
                    }

            return {"success": False, "message": f"Component {reference} not found"}

        except Exception as e:
            logger.error(f"Error moving schematic component: {e}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_move_connected(self, params):
        """Move a component and everything directly connected to its pins.

        Moves the component by (dx, dy), then for each pin:
        - Moves wire endpoints that touch the OLD pin position to the NEW pin position
        - Moves labels/junctions at those wire endpoints by the same offset
        - Leaves the "far end" of wires anchored (stretching them)
        """
        logger.info("Moving component with connected items")
        try:
            import re
            import math
            import os
            from pathlib import Path
            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            offset = params.get("offset", {})
            dx = float(offset.get("x", 0) if isinstance(offset, dict) else 0)
            dy = float(offset.get("y", 0) if isinstance(offset, dict) else 0)

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}
            if dx == 0 and dy == 0:
                return {"success": False, "message": "offset with non-zero x or y is required"}

            sch_file = Path(schematic_path)
            locator = self.pin_locator

            # 1. Get OLD pin positions before moving
            old_pins = locator.get_all_symbol_pins(sch_file, reference)
            if not old_pins:
                return {"success": False, "message": f"No pins found for {reference}"}

            old_pin_positions = set()
            for pos in old_pins.values():
                old_pin_positions.add((round(pos[0], 2), round(pos[1], 2)))

            # 2. Read raw file content
            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            eps = 0.5
            moved_items = {"component": False, "wire_endpoints": 0, "labels": 0, "junctions": 0}

            # Build list of (old_point, new_point) for pin moves
            pin_moves = []
            for pos in old_pins.values():
                ox, oy = round(pos[0], 2), round(pos[1], 2)
                pin_moves.append((ox, oy, round(ox + dx, 2), round(oy + dy, 2)))

            # 3. Find all points connected to old pin positions via wires
            # First pass: collect wire endpoints touching pins
            wire_pat = re.compile(r'\(wire\b')
            xy_pat = re.compile(r'\(xy\s+([\d.e+-]+)\s+([\d.e+-]+)\)')

            connected_points = set(old_pin_positions)
            # Also trace one hop through wires to find labels/junctions
            all_wires_parsed = []
            for wm in wire_pat.finditer(content):
                depth = 0
                i = wm.start()
                block_end = i
                while i < len(content):
                    if content[i] == '(':
                        depth += 1
                    elif content[i] == ')':
                        depth -= 1
                        if depth == 0:
                            block_end = i + 1
                            break
                    i += 1
                block = content[wm.start():block_end]
                xys = xy_pat.findall(block)
                if len(xys) >= 2:
                    p1 = (float(xys[0][0]), float(xys[0][1]))
                    p2 = (float(xys[-1][0]), float(xys[-1][1]))
                    all_wires_parsed.append((wm.start(), block_end, p1, p2))

            # Find wire endpoints that touch pin positions (these get moved)
            # And their far endpoints (these are "connected points" for label search)
            wire_far_endpoints = set()
            for ws, we, p1, p2 in all_wires_parsed:
                p1_at_pin = any(abs(p1[0] - px) < eps and abs(p1[1] - py) < eps for px, py in old_pin_positions)
                p2_at_pin = any(abs(p2[0] - px) < eps and abs(p2[1] - py) < eps for px, py in old_pin_positions)
                if p1_at_pin:
                    wire_far_endpoints.add(p2)
                if p2_at_pin:
                    wire_far_endpoints.add(p1)

            # Points to move = pin positions + far endpoints of wires touching pins
            # (far endpoints have labels/junctions we should also move)
            label_junction_move_points = wire_far_endpoints - old_pin_positions

            # 4. Collect all edits (position, old_text, new_text)
            edits = []  # [(start_pos, end_pos, new_text)]

            # 4a. Move the component symbol block — find (symbol (lib_id ...) ... (property "Reference" "U1" ...) ... (at X Y R))
            # Use kicad-skip via SchematicManager for the component move
            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                if symbol.property.Reference.value == reference:
                    old_pos = list(symbol.at.value)
                    rotation = float(old_pos[2]) if len(old_pos) > 2 else 0
                    new_x = float(old_pos[0]) + dx
                    new_y = float(old_pos[1]) + dy
                    symbol.at.value = [new_x, new_y, rotation]

                    # Move property fields
                    for prop_name in ["Reference", "Value", "Footprint", "Datasheet"]:
                        if hasattr(symbol.property, prop_name):
                            prop = getattr(symbol.property, prop_name)
                            if hasattr(prop, "at") and hasattr(prop.at, "value"):
                                try:
                                    pp = list(prop.at.value)
                                    pp[0] = float(pp[0]) + dx
                                    pp[1] = float(pp[1]) + dy
                                    prop.at.value = pp
                                except (TypeError, IndexError):
                                    pass

                    moved_items["component"] = True
                    break

            if not moved_items["component"]:
                return {"success": False, "message": f"Component {reference} not found"}

            # Save the component move via kicad-skip
            SchematicManager.save_schematic(schematic, schematic_path)

            # Re-read content after component move
            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 4b. Move wire endpoints touching old pin positions
            # Collect replacements in reverse order
            replacements = []
            for wm in wire_pat.finditer(content):
                depth = 0
                i = wm.start()
                block_end = i
                while i < len(content):
                    if content[i] == '(':
                        depth += 1
                    elif content[i] == ')':
                        depth -= 1
                        if depth == 0:
                            block_end = i + 1
                            break
                    i += 1
                block = content[wm.start():block_end]

                new_block = block
                modified = False
                for ox, oy, nx, ny in pin_moves:
                    # Replace (xy ox oy) with (xy nx ny) if it matches a pin position
                    for m in xy_pat.finditer(new_block):
                        mx, my = float(m.group(1)), float(m.group(2))
                        if abs(mx - ox) < eps and abs(my - oy) < eps:
                            from commands.sexp_writer import _fmt
                            old_xy = m.group(0)
                            new_xy = f"(xy {_fmt(nx)} {_fmt(ny)})"
                            new_block = new_block[:m.start()] + new_xy + new_block[m.end():]
                            modified = True
                            moved_items["wire_endpoints"] += 1
                            break  # one replacement per pin per wire

                if modified:
                    replacements.append((wm.start(), block_end, new_block))

            # 4c. Move labels at far endpoints of connected wires
            for lt in ["label", "global_label", "hierarchical_label"]:
                lp = re.compile(
                    rf'\({lt}\s+"([^"]*)"(?:\s+\(shape\s+[^)]*\))?\s+\(at\s+([\d.e+-]+)\s+([\d.e+-]+)'
                )
                for m in lp.finditer(content):
                    lx, ly = float(m.group(2)), float(m.group(3))
                    if any(abs(lx - fp[0]) < eps and abs(ly - fp[1]) < eps for fp in label_junction_move_points):
                        from commands.sexp_writer import _fmt
                        old_at = f"(at {m.group(2)} {m.group(3)}"
                        new_at = f"(at {_fmt(lx + dx)} {_fmt(ly + dy)}"
                        at_pos = content.find(old_at, m.start())
                        if at_pos >= 0:
                            replacements.append((at_pos, at_pos + len(old_at), new_at))
                            moved_items["labels"] += 1

            # 4d. Move junctions at far endpoints
            junc_pat = re.compile(r'\(junction\s+\(at\s+([\d.e+-]+)\s+([\d.e+-]+)\)')
            for m in junc_pat.finditer(content):
                jx, jy = float(m.group(1)), float(m.group(2))
                if any(abs(jx - fp[0]) < eps and abs(jy - fp[1]) < eps for fp in label_junction_move_points):
                    from commands.sexp_writer import _fmt
                    old_at = f"(at {m.group(1)} {m.group(2)})"
                    new_at = f"(at {_fmt(jx + dx)} {_fmt(jy + dy)})"
                    at_pos = content.find(old_at, m.start())
                    if at_pos >= 0:
                        replacements.append((at_pos, at_pos + len(old_at), new_at))
                        moved_items["junctions"] += 1

            # Apply all replacements in reverse order
            replacements.sort(key=lambda r: r[0], reverse=True)
            for start, end, new_text in replacements:
                content = content[:start] + new_text + content[end:]

            with open(schematic_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            total = moved_items["wire_endpoints"] + moved_items["labels"] + moved_items["junctions"]
            return {
                "success": True,
                "message": f"Moved {reference} by ({dx}, {dy}) with {total} connected items",
                "moved": moved_items,
                "offset": {"x": dx, "y": dy},
            }
        except Exception as e:
            logger.error(f"Error in move_connected: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_rotate_schematic_component(self, params):
        """Rotate a schematic component"""
        logger.info("Rotating schematic component")
        try:
            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            angle = params.get("angle", 0)
            mirror = params.get("mirror")

            if not schematic_path or not reference:
                return {
                    "success": False,
                    "message": "schematicPath and reference are required",
                }

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                if symbol.property.Reference.value == reference:
                    pos = list(symbol.at.value)
                    pos[2] = angle if len(pos) > 2 else angle
                    while len(pos) < 3:
                        pos.append(0)
                    pos[2] = angle
                    symbol.at.value = pos

                    # Handle mirror if specified
                    if mirror:
                        if hasattr(symbol, "mirror"):
                            symbol.mirror.value = mirror
                        else:
                            logger.warning(
                                f"Mirror '{mirror}' requested for {reference}, "
                                f"but symbol does not have a 'mirror' attribute; "
                                f"mirror not applied"
                            )

                    SchematicManager.save_schematic(schematic, schematic_path)
                    return {"success": True, "reference": reference, "angle": angle}

            return {"success": False, "message": f"Component {reference} not found"}

        except Exception as e:
            logger.error(f"Error rotating schematic component: {e}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_annotate_schematic(self, params):
        """Annotate unannotated components in schematic (R? -> R1, R2, ...)"""
        logger.info("Annotating schematic")
        try:
            import re

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Collect existing references by prefix
            existing_refs = {}  # prefix -> set of numbers
            unannotated = []  # (symbol, prefix)

            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                if ref.startswith("_TEMPLATE"):
                    continue

                # Split reference into prefix and number
                match = re.match(r"^([A-Za-z_]+)(\d+)$", ref)
                if match:
                    prefix = match.group(1)
                    num = int(match.group(2))
                    if prefix not in existing_refs:
                        existing_refs[prefix] = set()
                    existing_refs[prefix].add(num)
                elif ref.endswith("?"):
                    prefix = ref[:-1]
                    unannotated.append((symbol, prefix))

            if not unannotated:
                return {
                    "success": True,
                    "annotated": [],
                    "message": "All components already annotated",
                }

            annotated = []
            for symbol, prefix in unannotated:
                if prefix not in existing_refs:
                    existing_refs[prefix] = set()

                # Find next available number
                next_num = 1
                while next_num in existing_refs[prefix]:
                    next_num += 1

                old_ref = symbol.property.Reference.value
                new_ref = f"{prefix}{next_num}"
                symbol.property.Reference.value = new_ref
                existing_refs[prefix].add(next_num)

                uuid_val = str(symbol.uuid.value) if hasattr(symbol, "uuid") else ""
                annotated.append(
                    {
                        "uuid": uuid_val,
                        "oldReference": old_ref,
                        "newReference": new_ref,
                    }
                )

            SchematicManager.save_schematic(schematic, schematic_path)

            # After annotation, fix missing (instances) blocks for all components
            # KiCad 9 requires (instances ...) for reference designators to display
            from pathlib import Path
            from commands.sexp_writer import add_instances_block

            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            instances_added = 0
            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                if ref.startswith("_TEMPLATE") or ref.endswith("?"):
                    continue
                uuid_val = str(symbol.uuid.value) if hasattr(symbol, "uuid") else ""
                if not uuid_val:
                    continue

                # Check if THIS symbol already has (instances by finding its
                # block via balanced-paren search (works on single-line files)
                uuid_pos = content.find(uuid_val)
                if uuid_pos >= 0:
                    # Walk backwards to find the (symbol that owns this UUID
                    sym_start = content.rfind("(symbol", 0, uuid_pos)
                    if sym_start >= 0:
                        # Find end of this symbol block
                        depth = 0
                        si = sym_start
                        while si < len(content):
                            if content[si] == "(": depth += 1
                            elif content[si] == ")":
                                depth -= 1
                                if depth == 0:
                                    break
                            si += 1
                        sym_block = content[sym_start:si + 1]
                        if "(instances" in sym_block:
                            continue  # Already has instances

                # Add instances block
                try:
                    add_instances_block(Path(schematic_path), uuid_val, ref)
                    instances_added += 1
                    # Re-read content since add_instances_block modifies the file
                    with open(schematic_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception as inst_err:
                    logger.warning(f"Failed to add instances for {ref}: {inst_err}")

            if instances_added > 0:
                logger.info(f"Added (instances) blocks for {instances_added} components")
                for entry in annotated:
                    entry["instancesAdded"] = True

            return {"success": True, "annotated": annotated, "instancesFixed": instances_added}

        except Exception as e:
            logger.error(f"Error annotating schematic: {e}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_delete_schematic_wire(self, params):
        """Delete a wire from the schematic matching start/end points"""
        logger.info("Deleting schematic wire")
        try:
            schematic_path = params.get("schematicPath")
            start = params.get("start", {})
            end = params.get("end", {})

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            from pathlib import Path
            from commands.wire_manager import WireManager

            start_point = [start.get("x", 0), start.get("y", 0)]
            end_point = [end.get("x", 0), end.get("y", 0)]

            deleted = WireManager.delete_wire(
                Path(schematic_path), start_point, end_point
            )
            if deleted:
                return {"success": True}
            else:
                return {"success": False, "message": "No matching wire found"}

        except Exception as e:
            logger.error(f"Error deleting schematic wire: {e}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_batch_delete_schematic_wire(self, params):
        """Delete multiple wires in a single call. Single read/write cycle."""
        logger.info("Batch deleting schematic wires")
        try:
            from pathlib import Path
            from commands.sexp_writer import delete_wire_from_content, _read_schematic, _write_schematic

            schematic_path = params.get("schematicPath")
            wires = params.get("wires", [])

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not wires:
                return {"success": False, "message": "wires array is required"}

            content = _read_schematic(Path(schematic_path))
            deleted = 0
            failed = []
            for w in wires:
                start = w.get("start", {})
                end = w.get("end", {})
                sp = [start.get("x", 0), start.get("y", 0)]
                ep = [end.get("x", 0), end.get("y", 0)]
                result = delete_wire_from_content(content, sp, ep)
                if result is not None:
                    content = result
                    deleted += 1
                else:
                    failed.append({"start": start, "end": end})

            _write_schematic(Path(schematic_path), content)

            return {
                "success": True,
                "message": f"Deleted {deleted}/{len(wires)} wires",
                "deleted": deleted,
                "failed": failed,
            }
        except Exception as e:
            logger.error(f"Error in batch_delete_schematic_wire: {e}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_delete_schematic_net_label(self, params):
        """Delete a net label from the schematic"""
        logger.info("Deleting schematic net label")
        try:
            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")
            position = params.get("position")

            if not schematic_path or not net_name:
                return {
                    "success": False,
                    "message": "schematicPath and netName are required",
                }

            from pathlib import Path
            from commands.wire_manager import WireManager

            pos_list = None
            if position:
                pos_list = [position.get("x", 0), position.get("y", 0)]

            deleted = WireManager.delete_label(Path(schematic_path), net_name, pos_list)
            if deleted:
                return {"success": True}
            else:
                return {"success": False, "message": f"Label '{net_name}' not found"}

        except Exception as e:
            logger.error(f"Error deleting schematic net label: {e}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_delete_no_connect(self, params):
        """Delete a no-connect flag from the schematic at a given position"""
        logger.info("Deleting no-connect")
        try:
            schematic_path = params.get("schematicPath")
            position = params.get("position", {})

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not position:
                return {"success": False, "message": "position is required"}

            from pathlib import Path
            from commands.sexp_writer import delete_no_connect

            pos = [position.get("x", 0), position.get("y", 0)]
            deleted = delete_no_connect(Path(schematic_path), pos)
            if deleted:
                return {"success": True, "message": f"Deleted no-connect at ({pos[0]}, {pos[1]})"}
            else:
                return {"success": False, "message": f"No matching no-connect found at ({pos[0]}, {pos[1]})"}

        except Exception as e:
            logger.error(f"Error deleting no-connect: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_batch_delete_no_connect(self, params):
        """Delete multiple no-connect flags in a single call. Single read/write cycle."""
        logger.info("Batch deleting no-connects")
        try:
            from pathlib import Path
            from commands.sexp_writer import delete_no_connect_from_content, _read_schematic, _write_schematic

            schematic_path = params.get("schematicPath")
            positions = params.get("positions", [])

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not positions:
                return {"success": False, "message": "positions array is required"}

            content = _read_schematic(Path(schematic_path))
            deleted = 0
            failed = []
            for p in positions:
                pos = [p.get("x", 0), p.get("y", 0)]
                result = delete_no_connect_from_content(content, pos)
                if result is not None:
                    content = result
                    deleted += 1
                else:
                    failed.append({"x": pos[0], "y": pos[1]})

            _write_schematic(Path(schematic_path), content)

            return {
                "success": True,
                "message": f"Deleted {deleted}/{len(positions)} no-connects",
                "deleted": deleted,
                "failed": failed,
            }
        except Exception as e:
            logger.error(f"Error in batch_delete_no_connect: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_export_schematic_svg(self, params):
        """Export schematic to SVG using kicad-cli"""
        logger.info("Exporting schematic SVG")
        import subprocess
        import glob
        import shutil

        try:
            schematic_path = params.get("schematicPath")
            output_path = params.get("outputPath")

            if not schematic_path or not output_path:
                return {
                    "success": False,
                    "message": "schematicPath and outputPath are required",
                }

            if not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            # kicad-cli's --output flag for SVG export expects a directory, not a file path.
            # The output file is auto-named based on the schematic name.
            output_dir = os.path.dirname(output_path)
            if not output_dir:
                output_dir = "."

            os.makedirs(output_dir, exist_ok=True)

            cmd = [
                "kicad-cli",
                "sch",
                "export",
                "svg",
                schematic_path,
                "-o",
                output_dir,
            ]

            if params.get("blackAndWhite"):
                cmd.append("--black-and-white")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed: {result.stderr}",
                }

            # kicad-cli names the file after the schematic, so find the generated SVG
            svg_files = glob.glob(os.path.join(output_dir, "*.svg"))
            if not svg_files:
                return {
                    "success": False,
                    "message": "No SVG file produced by kicad-cli",
                }

            generated_svg = svg_files[0]

            # Move/rename to the user-specified output path if it differs
            if os.path.abspath(generated_svg) != os.path.abspath(output_path):
                shutil.move(generated_svg, output_path)

            return {"success": True, "file": {"path": output_path}}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except Exception as e:
            logger.error(f"Error exporting schematic SVG: {e}")
            return {"success": False, "message": str(e)}

    def _handle_get_net_connections(self, params):
        """Get all connections for a named net (supports labels AND power symbols)"""
        logger.info("Getting net connections")
        try:
            import re
            from pathlib import Path
            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")

            if not all([schematic_path, net_name]):
                return {"success": False, "message": "Missing required parameters"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Try the standard label-based approach first
            connections = ConnectionManager.get_net_connections(
                schematic, net_name, Path(schematic_path)
            )

            # Also search for power symbols with matching Value
            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Skip lib_symbols
            lib_sym_start = content.find("(lib_symbols")
            lib_sym_end = -1
            if lib_sym_start >= 0:
                d = 0
                for i in range(lib_sym_start, len(content)):
                    if content[i] == "(": d += 1
                    elif content[i] == ")":
                        d -= 1
                        if d == 0: lib_sym_end = i; break

            pwr_refs = []
            pwr_pat = re.compile(r'\(symbol\s+\(lib_id\s+"power:[^"]*"\)')
            for m in pwr_pat.finditer(content):
                pos = m.start()
                if lib_sym_start >= 0 and lib_sym_start <= pos <= lib_sym_end:
                    continue
                # Check if Value matches net_name
                snippet = content[pos:pos+500]
                val_m = re.search(r'\(property\s+"Value"\s+"([^"]*)"', snippet)
                ref_m = re.search(r'\(property\s+"Reference"\s+"([^"]*)"', snippet)
                if val_m and val_m.group(1) == net_name:
                    pwr_ref = ref_m.group(1) if ref_m else "?"
                    at_m = re.search(r'\(at\s+([\d.e+-]+)\s+([\d.e+-]+)', snippet)
                    if at_m:
                        pwr_refs.append({
                            "component": pwr_ref,
                            "pin": "1",
                            "type": "power_symbol",
                            "position": {"x": float(at_m.group(1)), "y": float(at_m.group(2))},
                        })

            all_connections = connections + pwr_refs
            return {"success": True, "connections": all_connections}
        except Exception as e:
            logger.error(f"Error getting net connections: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_run_erc(self, params):
        """Run Electrical Rules Check on a schematic via kicad-cli"""
        logger.info("Running ERC on schematic")
        import subprocess
        import tempfile
        import os

        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path or not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": "Schematic file not found",
                    "errorDetails": f"Path does not exist: {schematic_path}",
                }

            kicad_cli = self.design_rule_commands._find_kicad_cli()
            if not kicad_cli:
                return {
                    "success": False,
                    "message": "kicad-cli not found",
                    "errorDetails": "Install KiCAD 8.0+ or add kicad-cli to PATH.",
                }

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tmp:
                json_output = tmp.name

            try:
                cmd = [
                    kicad_cli,
                    "sch",
                    "erc",
                    "--format",
                    "json",
                    "--severity-all",
                    "--output",
                    json_output,
                    schematic_path,
                ]
                logger.info(f"Running ERC command: {' '.join(cmd)}")

                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=120
                )

                # kicad-cli returns non-zero when violations are found — that's normal.
                # Only treat as failure if the JSON output file wasn't created.
                if not os.path.exists(json_output) or os.path.getsize(json_output) == 0:
                    logger.error(f"ERC command produced no output: {result.stderr}")
                    return {
                        "success": False,
                        "message": "ERC command failed to produce output",
                        "errorDetails": result.stderr,
                        "returnCode": result.returncode,
                    }

                with open(json_output, "r", encoding="utf-8") as f:
                    erc_data = json.load(f)

                violations = []
                severity_counts = {"error": 0, "warning": 0, "info": 0}

                # KiCad 9 nests violations under sheets[*].violations
                all_raw_violations = []
                for sheet in erc_data.get("sheets", []):
                    all_raw_violations.extend(sheet.get("violations", []))
                # Also check top-level for older formats
                all_raw_violations.extend(erc_data.get("violations", []))

                # Detect coordinate scale: kicad-cli may output coords
                # in internal units (1/100mm) instead of mm. If the first
                # coordinate is very small relative to typical schematic
                # positions (< 10mm), assume it's 1/100mm and scale up.
                coord_scale = 1.0
                for v in all_raw_violations:
                    items = v.get("items", [])
                    if items and "pos" in items[0]:
                        test_x = abs(items[0]["pos"].get("x", 0))
                        test_y = abs(items[0]["pos"].get("y", 0))
                        # Typical schematic coords are 20-300mm.
                        # If both are < 5mm, they're probably in 1/100mm.
                        if test_x > 0 and test_x < 5 and test_y < 5:
                            coord_scale = 100.0
                            logger.info(f"ERC coords appear scaled down, applying {coord_scale}x correction")
                        break

                for v in all_raw_violations:
                    vseverity = v.get("severity", "error")
                    items = v.get("items", [])
                    loc = {}
                    if items and "pos" in items[0]:
                        raw_x = items[0]["pos"].get("x", 0)
                        raw_y = items[0]["pos"].get("y", 0)
                        loc = {
                            "x": round(raw_x * coord_scale, 2),
                            "y": round(raw_y * coord_scale, 2),
                        }
                    violations.append(
                        {
                            "type": v.get("type", "unknown"),
                            "severity": vseverity,
                            "message": v.get("description", ""),
                            "location": loc,
                        }
                    )
                    if vseverity in severity_counts:
                        severity_counts[vseverity] += 1

                return {
                    "success": True,
                    "message": f"ERC complete: {len(violations)} violation(s)",
                    "summary": {
                        "total": len(violations),
                        "by_severity": severity_counts,
                    },
                    "violations": violations,
                }

            finally:
                if os.path.exists(json_output):
                    os.unlink(json_output)

        except subprocess.TimeoutExpired:
            return {"success": False, "message": "ERC timed out after 120 seconds"}
        except Exception as e:
            logger.error(f"Error running ERC: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_generate_netlist(self, params):
        """Generate netlist from schematic"""
        logger.info("Generating netlist from schematic")
        try:
            schematic_path = params.get("schematicPath")

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            netlist = ConnectionManager.generate_netlist(
                schematic, schematic_path=schematic_path
            )
            return {"success": True, "netlist": netlist}
        except Exception as e:
            logger.error(f"Error generating netlist: {str(e)}")
            return {"success": False, "message": str(e)}

    # ── Net analysis tools (delegate to commands/net_analysis.py) ──

    def _handle_get_component_nets(self, params):
        """Return pin-to-net mapping for every pin of a component."""
        logger.info("Getting component nets")
        try:
            from commands.net_analysis import get_component_nets

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            result, error = get_component_nets(
                schematic, schematic_path, self.pin_locator, reference
            )
            if error:
                return {"success": False, "message": error}
            return {"success": True, **result}
        except Exception as e:
            logger.error(f"Error in get_component_nets: {e}")
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_net_components(self, params):
        """Return all component pins connected to a named net."""
        logger.info("Getting net components")
        try:
            from commands.net_analysis import get_net_components

            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not net_name:
                return {"success": False, "message": "netName is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            result, error = get_net_components(
                schematic, schematic_path, self.pin_locator, net_name
            )
            if error:
                return {"success": False, "message": error}
            return {"success": True, **result}
        except Exception as e:
            logger.error(f"Error in get_net_components: {e}")
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_pin_net_name(self, params):
        """Return just the net name for a single component pin."""
        logger.info("Getting pin net name")
        try:
            from commands.net_analysis import get_pin_net_name

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            pin = params.get("pin")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}
            if not pin:
                return {"success": False, "message": "pin is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            result, error = get_pin_net_name(
                schematic, schematic_path, self.pin_locator, reference, str(pin)
            )
            if error:
                return {"success": False, "message": error}
            return {"success": True, **result}
        except Exception as e:
            logger.error(f"Error in get_pin_net_name: {e}")
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_export_netlist_summary(self, params):
        """Dump the complete netlist as simple text: component->pin->net."""
        logger.info("Exporting netlist summary")
        try:
            from commands.net_analysis import export_netlist_summary

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            text, error = export_netlist_summary(
                schematic, schematic_path, self.pin_locator
            )
            if error:
                return {"success": False, "message": error}
            return {"success": True, "summary": text}
        except Exception as e:
            logger.error(f"Error in export_netlist_summary: {e}")
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_validate_component_connections(self, params):
        """Validate a component's pin-net mapping against expected values."""
        logger.info("Validating component connections")
        try:
            from commands.net_analysis import validate_component_connections

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            expected = params.get("expected")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}
            if not expected or not isinstance(expected, dict):
                return {
                    "success": False,
                    "message": "expected is required (dict of pin->net)",
                }

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            result, error = validate_component_connections(
                schematic, schematic_path, self.pin_locator, reference, expected
            )
            if error:
                return {"success": False, "message": error}
            return {"success": True, **result}
        except Exception as e:
            logger.error(f"Error in validate_component_connections: {e}")
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_find_shorted_nets(self, params):
        """Detect accidentally merged nets (two+ named nets on same wire)."""
        logger.info("Finding shorted nets")
        try:
            from commands.net_analysis import find_shorted_nets

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            result, error = find_shorted_nets(
                schematic, schematic_path, self.pin_locator
            )
            if error:
                return {"success": False, "message": error}
            return {"success": True, **result}
        except Exception as e:
            logger.error(f"Error in find_shorted_nets: {e}")
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_find_single_pin_nets(self, params):
        """Find nets with only one component pin (likely broken connection)."""
        logger.info("Finding single-pin nets")
        try:
            from commands.net_analysis import find_single_pin_nets

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            exclude_nc = params.get("excludeNoConnect", True)

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            result, error = find_single_pin_nets(
                schematic, schematic_path, self.pin_locator, exclude_nc
            )
            if error:
                return {"success": False, "message": error}
            return {"success": True, **result}
        except Exception as e:
            logger.error(f"Error in find_single_pin_nets: {e}")
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_fix_connectivity(self, params):
        """Run kicad-cli ERC, parse violations, auto-fix T-junctions and report."""
        logger.info("Running fix_connectivity")
        try:
            import subprocess
            import json as _json
            import tempfile
            import re
            from pathlib import Path
            from commands.sexp_writer import (
                _read_schematic, _write_schematic, _parse_wire_segments,
                _point_on_wire_mid, add_junction_to_content,
                _parse_existing_junctions, auto_add_t_junctions,
            )

            schematic_path = params.get("schematicPath")
            dry_run = params.get("dryRun", False)

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {"success": False, "message": f"File not found: {schematic_path}"}

            # Step 1: Run kicad-cli ERC
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                erc_output = tmp.name

            try:
                result = subprocess.run(
                    [
                        "kicad-cli", "sch", "erc",
                        "--severity-all",
                        "--format", "json",
                        "-o", erc_output,
                        str(schematic_path),
                    ],
                    capture_output=True, text=True, timeout=120,
                )
            except FileNotFoundError:
                return {"success": False, "message": "kicad-cli not found on PATH"}
            except subprocess.TimeoutExpired:
                return {"success": False, "message": "kicad-cli ERC timed out"}

            # Step 2: Parse ERC output
            try:
                with open(erc_output, "r") as f:
                    erc_data = _json.load(f)
            except Exception:
                return {"success": False, "message": "Failed to parse ERC output"}
            finally:
                try:
                    os.unlink(erc_output)
                except Exception:
                    pass

            # Extract violations from sheets
            violations = []
            if "sheets" in erc_data:
                for sheet in erc_data["sheets"]:
                    for v in sheet.get("violations", []):
                        violations.append(v)
            elif "violations" in erc_data:
                violations = erc_data["violations"]

            # Step 3: Categorize violations
            pin_not_connected = []
            wire_not_connected = []
            other_violations = []

            for v in violations:
                vtype = v.get("type", "")
                severity = v.get("severity", "")
                desc = v.get("description", "")
                items = v.get("items", [])

                # Extract coordinates from violation items
                coords = []
                for item in items:
                    pos = item.get("pos", {})
                    if "x" in pos and "y" in pos:
                        x = float(pos["x"])
                        y = float(pos["y"])
                        # Auto-detect 1/100mm scale (kicad-cli quirk)
                        if x > 1000 or y > 1000:
                            x /= 100.0
                            y /= 100.0
                        coords.append((x, y))

                entry = {
                    "type": vtype,
                    "severity": severity,
                    "description": desc,
                    "coords": coords,
                }

                if vtype == "pin_not_connected":
                    pin_not_connected.append(entry)
                elif vtype == "wire_not_connected" or "unconnected" in vtype:
                    wire_not_connected.append(entry)
                else:
                    other_violations.append(entry)

            # Step 4: Auto-fix — find T-junctions at violation coordinates
            content = _read_schematic(sch_file)
            all_wires = _parse_wire_segments(content)
            existing_junctions = _parse_existing_junctions(content)

            fixes = []
            unfixable = []
            fix_points = []

            # Check each violation coordinate for T-junction
            for v in pin_not_connected + wire_not_connected:
                for cx, cy in v["coords"]:
                    # Is this point on the mid-segment of any wire?
                    is_t_junction = False
                    for wx1, wy1, wx2, wy2 in all_wires:
                        if _point_on_wire_mid(cx, cy, wx1, wy1, wx2, wy2, 0.5):
                            is_t_junction = True
                            break

                    # Also check if any wire endpoint near this coord is a T-junction
                    if not is_t_junction:
                        for wx1, wy1, wx2, wy2 in all_wires:
                            for px, py in [(wx1, wy1), (wx2, wy2)]:
                                if abs(px - cx) < 0.5 and abs(py - cy) < 0.5:
                                    # This wire endpoint is near the violation.
                                    # Check if it's on mid-segment of another wire.
                                    for owx1, owy1, owx2, owy2 in all_wires:
                                        if (owx1, owy1, owx2, owy2) == (wx1, wy1, wx2, wy2):
                                            continue
                                        if _point_on_wire_mid(px, py, owx1, owy1, owx2, owy2, 0.5):
                                            is_t_junction = True
                                            cx, cy = px, py
                                            break
                                    if is_t_junction:
                                        break
                            if is_t_junction:
                                break

                    pt = (round(cx, 4), round(cy, 4))
                    if is_t_junction and pt not in existing_junctions:
                        fix_points.append(pt)
                        fixes.append({
                            "action": "add_junction",
                            "at": [pt[0], pt[1]],
                            "reason": v["description"],
                        })
                    elif not is_t_junction:
                        unfixable.append(v)

            # Step 5: Apply fixes
            actually_fixed = 0
            if not dry_run and fix_points:
                seen = set()
                for pt in fix_points:
                    if pt in seen:
                        continue
                    seen.add(pt)
                    content = add_junction_to_content(content, [pt[0], pt[1]])
                    actually_fixed += 1
                _write_schematic(sch_file, content)

            return {
                "success": True,
                "erc_total": len(violations),
                "pin_not_connected": len(pin_not_connected),
                "wire_not_connected": len(wire_not_connected),
                "other_violations": len(other_violations),
                "fixes_applied": actually_fixed if not dry_run else 0,
                "fixes_available": len(set(fix_points)),
                "fixes": fixes,
                "unfixable": [
                    {"type": v["type"], "description": v["description"], "coords": v["coords"]}
                    for v in unfixable
                ],
                "remaining_other": [
                    {"type": v["type"], "severity": v["severity"], "description": v["description"]}
                    for v in other_violations
                ],
                "dryRun": dry_run,
            }

        except Exception as e:
            logger.error(f"Error in fix_connectivity: {e}")
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_sync_schematic_to_board(self, params):
        """Sync schematic netlist to PCB board (equivalent to KiCAD F8 'Update PCB from Schematic').
        Reads net connections from the schematic and assigns them to the matching pads in the PCB.
        """
        logger.info("Syncing schematic to board")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            board_path = params.get("boardPath")

            # Determine board to work with
            board = None
            if board_path:
                board = pcbnew.LoadBoard(board_path)
            elif self.board:
                board = self.board
                board_path = board.GetFileName() if not board_path else board_path
            else:
                return {
                    "success": False,
                    "message": "No board loaded. Use open_project first or provide boardPath.",
                }

            if not board_path:
                board_path = board.GetFileName()

            # Determine schematic path if not provided
            if not schematic_path:
                sch = Path(board_path).with_suffix(".kicad_sch")
                if sch.exists():
                    schematic_path = str(sch)
                else:
                    project_dir = Path(board_path).parent
                    sch_files = list(project_dir.glob("*.kicad_sch"))
                    if sch_files:
                        schematic_path = str(sch_files[0])

            if not schematic_path or not Path(schematic_path).exists():
                return {
                    "success": False,
                    "message": f"Schematic not found. Provide schematicPath. Tried: {schematic_path}",
                }

            # Generate netlist from schematic
            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            netlist = ConnectionManager.generate_netlist(
                schematic, schematic_path=schematic_path
            )

            # Build (reference, pad_number) -> net_name map
            pad_net_map = {}  # {(ref, pin_str): net_name}
            net_names = set()
            for net_entry in netlist.get("nets", []):
                net_name = net_entry["name"]
                net_names.add(net_name)
                for conn in net_entry.get("connections", []):
                    ref = conn.get("component", "")
                    pin = str(conn.get("pin", ""))
                    if ref and pin and pin != "unknown":
                        pad_net_map[(ref, pin)] = net_name

            # Add all nets to board
            netinfo = board.GetNetInfo()
            nets_by_name = netinfo.NetsByName()
            added_nets = []
            for net_name in net_names:
                if not nets_by_name.has_key(net_name):
                    net_item = pcbnew.NETINFO_ITEM(board, net_name)
                    board.Add(net_item)
                    added_nets.append(net_name)

            # Refresh nets map after additions
            netinfo = board.GetNetInfo()
            nets_by_name = netinfo.NetsByName()

            # Assign nets to pads
            assigned_pads = 0
            unmatched = []
            for fp in board.GetFootprints():
                ref = fp.GetReference()
                for pad in fp.Pads():
                    pad_num = pad.GetNumber()
                    key = (ref, str(pad_num))
                    if key in pad_net_map:
                        net_name = pad_net_map[key]
                        if nets_by_name.has_key(net_name):
                            pad.SetNet(nets_by_name[net_name])
                            assigned_pads += 1
                    else:
                        unmatched.append(f"{ref}/{pad_num}")

            board.Save(board_path)

            # If board was loaded fresh, update internal reference
            if params.get("boardPath"):
                self.board = board
                self._update_command_handlers()

            logger.info(
                f"sync_schematic_to_board: {len(added_nets)} nets added, {assigned_pads} pads assigned"
            )
            return {
                "success": True,
                "message": f"PCB nets synced from schematic: {len(added_nets)} nets added, {assigned_pads} pads assigned",
                "nets_added": added_nets,
                "nets_total": len(net_names),
                "pads_assigned": assigned_pads,
                "unmatched_pads_sample": unmatched[:10],
            }

        except Exception as e:
            logger.error(f"Error in sync_schematic_to_board: {e}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_import_svg_logo(self, params):
        """Import an SVG file as PCB graphic polygons on the silkscreen"""
        logger.info("Importing SVG logo into PCB")
        try:
            from commands.svg_import import import_svg_to_pcb

            pcb_path = params.get("pcbPath")
            svg_path = params.get("svgPath")
            x = float(params.get("x", 0))
            y = float(params.get("y", 0))
            width = float(params.get("width", 10))
            layer = params.get("layer", "F.SilkS")
            stroke_width = float(params.get("strokeWidth", 0))
            filled = bool(params.get("filled", True))

            if not pcb_path or not svg_path:
                return {
                    "success": False,
                    "message": "Missing required parameters: pcbPath, svgPath",
                }

            result = import_svg_to_pcb(
                pcb_path, svg_path, x, y, width, layer, stroke_width, filled
            )

            # import_svg_to_pcb writes gr_poly entries directly to the .kicad_pcb file,
            # bypassing the pcbnew in-memory board object.  Any subsequent board.Save()
            # call would overwrite the file with the stale in-memory state, erasing the
            # logo.  Reload the board from disk so pcbnew's memory matches the file.
            if result.get("success") and self.board:
                try:
                    self.board = pcbnew.LoadBoard(pcb_path)
                    # Propagate updated board reference to all command handlers
                    self._update_command_handlers()
                    logger.info("Reloaded board into pcbnew after SVG logo import")
                except Exception as reload_err:
                    logger.warning(
                        f"Board reload after SVG import failed (non-fatal): {reload_err}"
                    )

            return result

        except Exception as e:
            logger.error(f"Error importing SVG logo: {str(e)}")


            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    # ── New batch / power tools ──────────────────────────────────────────

    def _handle_add_power_symbol(self, params):
        """Place a power port symbol (GND, +3V3, +5V, VCC, etc.) from the power library"""
        logger.info("Adding power symbol to schematic")
        try:
            from pathlib import Path
            from commands.dynamic_symbol_loader import DynamicSymbolLoader

            schematic_path = params.get("schematicPath")
            symbol_name = params.get("symbol")  # e.g. "GND", "+3V3", "+5V"
            position = params.get("position", {})
            orientation = params.get("orientation", 0)
            x = position.get("x", 0) if isinstance(position, dict) else 0
            y = position.get("y", 0) if isinstance(position, dict) else 0

            if not schematic_path or not symbol_name:
                return {"success": False, "message": "schematicPath and symbol are required"}

            schematic_file = Path(schematic_path)
            derived_project_path = schematic_file.parent
            loader = DynamicSymbolLoader(project_path=derived_project_path)

            # Auto-number #PWR reference: find highest existing #PWR number
            import re as _re
            with open(schematic_file, "r", encoding="utf-8") as _f:
                _content = _f.read()
            existing_pwr = _re.findall(r'#PWR(\d+)', _content)
            next_pwr = max((int(n) for n in existing_pwr), default=0) + 1
            reference = f"#PWR{next_pwr:03d}"
            loader.add_component(
                schematic_file,
                "power",
                symbol_name,
                reference=reference,
                value=symbol_name,
                footprint="",
                x=x,
                y=y,
                rotation=orientation,
                project_path=derived_project_path,
            )

            # Auto-hide the #PWR Reference field (matches KiCad's default behavior)
            import re
            with open(schematic_file, "r", encoding="utf-8") as f:
                content = f.read()

            # Find the last placed symbol with #PWR? reference and hide its Reference field
            # Look for (property "Reference" "#PWR?" ... (effects (font ...))) and add (hide yes)
            pwr_pattern = re.compile(
                r'(\(property\s+"Reference"\s+"#PWR\?"\s+\(at[^)]*\)\s*\(effects\s+\(font[^)]*\))(\s*\))',
            )
            # Replace only the LAST occurrence (the one we just added)
            matches = list(pwr_pattern.finditer(content))
            if matches:
                m = matches[-1]
                content = content[:m.start()] + m.group(1) + " (hide yes)" + m.group(2) + content[m.end():]
                with open(schematic_file, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())

            return {
                "success": True,
                "message": f"Placed power symbol {symbol_name} at ({x}, {y})",
                "symbol": f"power:{symbol_name}",
            }
        except Exception as e:
            logger.error(f"Error adding power symbol: {str(e)}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_batch_connect_to_net(self, params):
        """Connect multiple component pins to named nets in a single call"""
        logger.info("Batch connecting pins to nets")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            connections = params.get("connections", [])

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not connections:
                return {"success": False, "message": "connections array is required"}

            results = {"connected": [], "failed": []}
            for conn in connections:
                ref = conn.get("componentRef")
                pin = conn.get("pinName")
                net = conn.get("netName")
                label_type = conn.get("labelType")
                shape = conn.get("shape")

                if not all([ref, pin, net]):
                    results["failed"].append(f"Missing fields in {conn}")
                    continue

                try:
                    success = ConnectionManager.connect_to_net(
                        Path(schematic_path), ref, pin, net,
                        label_type=label_type, shape=shape,
                    )
                    if success:
                        results["connected"].append(f"{ref}/{pin} -> {net}")
                    else:
                        results["failed"].append(f"{ref}/{pin} -> {net}")
                except Exception as e:
                    results["failed"].append(f"{ref}/{pin} -> {net}: {e}")

            n_ok = len(results["connected"])
            n_fail = len(results["failed"])
            return {
                "success": n_fail == 0,
                "message": f"Batch connect: {n_ok} connected, {n_fail} failed",
                "connected": results["connected"],
                "failed": results["failed"],
            }
        except Exception as e:
            logger.error(f"Error in batch connect_to_net: {str(e)}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_bulk_move_schematic_components(self, params):
        """Move multiple schematic components to new positions in a single call"""
        logger.info("Bulk moving schematic components")
        try:
            schematic_path = params.get("schematicPath")
            moves = params.get("moves", {})

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not moves:
                return {"success": False, "message": "moves dict is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            moved = []
            failed = []

            for reference, pos in moves.items():
                new_x = pos.get("x")
                new_y = pos.get("y")
                if new_x is None or new_y is None:
                    failed.append(f"{reference}: missing x or y")
                    continue

                found = False
                for symbol in schematic.symbol:
                    if not hasattr(symbol.property, "Reference"):
                        continue
                    if symbol.property.Reference.value == reference:
                        old_pos = list(symbol.at.value)
                        dx = new_x - float(old_pos[0])
                        dy = new_y - float(old_pos[1])
                        rotation = float(old_pos[2]) if len(old_pos) > 2 else 0
                        symbol.at.value = [new_x, new_y, rotation]

                        # Move all property fields by the same delta
                        for prop_name in ["Reference", "Value", "Footprint", "Datasheet"]:
                            try:
                                if hasattr(symbol.property, prop_name):
                                    prop = getattr(symbol.property, prop_name)
                                    if hasattr(prop, "at") and hasattr(prop.at, "value"):
                                        prop_pos = list(prop.at.value)
                                        prop_pos[0] = float(prop_pos[0]) + dx
                                        prop_pos[1] = float(prop_pos[1]) + dy
                                        prop.at.value = prop_pos
                            except Exception:
                                pass

                        moved.append(reference)
                        found = True
                        break

                if not found:
                    failed.append(f"{reference}: not found")

            SchematicManager.save_schematic(schematic, schematic_path)

            return {
                "success": len(failed) == 0,
                "message": f"Bulk move: {len(moved)} moved, {len(failed)} failed",
                "moved": moved,
                "failed": failed,
            }
        except Exception as e:
            logger.error(f"Error in bulk move: {str(e)}")

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_snapshot_project(self, params):
        """Copy the entire project folder to a snapshot directory for checkpoint/resume."""
        import shutil
        from datetime import datetime
        from pathlib import Path

        try:
            step = params.get("step", "")
            label = params.get("label", "")
            prompt_text = params.get("prompt", "")
            # Determine project directory from loaded board or explicit path
            project_dir = None
            if self.board:
                board_file = self.board.GetFileName()
                if board_file:
                    project_dir = str(Path(board_file).parent)
            if not project_dir:
                project_dir = params.get("projectPath")
            if not project_dir or not os.path.isdir(project_dir):
                return {
                    "success": False,
                    "message": "Could not determine project directory for snapshot",
                }

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Save prompt + log into logs/ subdirectory before snapshotting
            logs_dir = Path(project_dir) / "logs"
            logs_dir.mkdir(exist_ok=True)

            prompt_file = None
            if prompt_text:
                prompt_filename = (
                    f"PROMPT_step{step}_{ts}.md" if step else f"PROMPT_{ts}.md"
                )
                prompt_file = logs_dir / prompt_filename
                prompt_file.write_text(prompt_text, encoding="utf-8")
                logger.info(f"Prompt saved: {prompt_file}")

            # Copy current MCP session log into logs/ before snapshotting
            import platform

            system = platform.system()
            if system == "Windows":
                mcp_log_dir = os.path.join(
                    os.environ.get("APPDATA", ""), "Claude", "logs"
                )
            elif system == "Darwin":
                mcp_log_dir = os.path.expanduser("~/Library/Logs/Claude")
            else:
                mcp_log_dir = os.path.expanduser("~/.config/Claude/logs")
            mcp_log_src = os.path.join(mcp_log_dir, "mcp-server-kicad.log")
            mcp_log_dest = None
            if os.path.exists(mcp_log_src):
                with open(mcp_log_src, "r", encoding="utf-8", errors="replace") as f:
                    all_lines = f.readlines()
                session_start = 0
                for i, line in enumerate(all_lines):
                    if "Initializing server" in line:
                        session_start = i
                session_lines = all_lines[session_start:]
                log_filename = (
                    f"mcp_log_step{step}_{ts}.txt" if step else f"mcp_log_{ts}.txt"
                )
                mcp_log_dest = logs_dir / log_filename
                with open(mcp_log_dest, "w", encoding="utf-8") as f:
                    f.writelines(session_lines)
                logger.info(
                    f"MCP session log saved: {mcp_log_dest} ({len(session_lines)} lines)"
                )

            base_name = Path(project_dir).name
            suffix_parts = [p for p in [f"step{step}" if step else "", label, ts] if p]
            snapshot_name = base_name + "_snapshot_" + "_".join(suffix_parts)
            snapshots_base = Path(project_dir) / "snapshots"
            snapshots_base.mkdir(exist_ok=True)
            snapshot_dir = str(snapshots_base / snapshot_name)

            shutil.copytree(
                project_dir, snapshot_dir, ignore=shutil.ignore_patterns("snapshots")
            )
            logger.info(f"Project snapshot saved: {snapshot_dir}")
            return {
                "success": True,
                "message": f"Snapshot saved: {snapshot_name}",
                "snapshotPath": snapshot_dir,
                "sourceDir": project_dir,
                "promptSaved": str(prompt_file) if prompt_file else None,
                "mcpLogSaved": str(mcp_log_dest) if mcp_log_dest else None,
            }
        except Exception as e:
            logger.error(f"snapshot_project error: {e}")
            return {"success": False, "message": str(e)}

    def _handle_check_kicad_ui(self, params):
        """Check if KiCAD UI is running"""
        logger.info("Checking if KiCAD UI is running")
        try:
            manager = KiCADProcessManager()
            is_running = manager.is_running()
            processes = manager.get_process_info() if is_running else []

            return {
                "success": True,
                "running": is_running,
                "processes": processes,
                "message": "KiCAD is running" if is_running else "KiCAD is not running",
            }
        except Exception as e:
            logger.error(f"Error checking KiCAD UI status: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_launch_kicad_ui(self, params):
        """Launch KiCAD UI"""
        logger.info("Launching KiCAD UI")
        try:
            project_path = params.get("projectPath")
            auto_launch = params.get("autoLaunch", AUTO_LAUNCH_KICAD)

            # Convert project path to Path object if provided
            from pathlib import Path

            path_obj = Path(project_path) if project_path else None

            result = check_and_launch_kicad(path_obj, auto_launch)

            return {"success": True, **result}
        except Exception as e:
            logger.error(f"Error launching KiCAD UI: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_refill_zones(self, params):
        """Refill all copper pour zones on the board.

        pcbnew.ZONE_FILLER.Fill() can cause a C++ access violation (0xC0000005)
        that crashes the entire Python process when called from SWIG outside KiCAD UI.
        To avoid killing the main process we run the fill in an isolated subprocess.
        If the subprocess crashes or times out, we return a non-fatal warning so the
        caller can continue — KiCAD Pcbnew will refill zones automatically when the
        board is opened (press B).
        """
        logger.info("Refilling zones (subprocess isolation)")
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # First save the board so the subprocess can load it fresh
            board_path = self.board.GetFileName()
            if not board_path:
                return {
                    "success": False,
                    "message": "Board has no file path — save first",
                }
            self.board.Save(board_path)

            zone_count = (
                self.board.GetAreaCount() if hasattr(self.board, "GetAreaCount") else 0
            )

            # Run pcbnew zone fill in an isolated subprocess to prevent crashes
            import subprocess, sys, textwrap

            script = textwrap.dedent(f"""
import pcbnew, sys
board = pcbnew.LoadBoard({repr(board_path)})
filler = pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())
board.Save({repr(board_path)})
print("ok")
""")
            try:
                result = subprocess.run(
                    [sys.executable, "-c", script],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode == 0 and "ok" in result.stdout:
                    # Reload board after subprocess modified it
                    self.board = pcbnew.LoadBoard(board_path)
                    self._update_command_handlers()
                    logger.info("Zone fill subprocess succeeded")
                    return {
                        "success": True,
                        "message": f"Zones refilled successfully ({zone_count} zones)",
                        "zoneCount": zone_count,
                    }
                else:
                    logger.warning(
                        f"Zone fill subprocess failed: rc={result.returncode} stderr={result.stderr[:200]}"
                    )
                    return {
                        "success": False,
                        "message": "Zone fill failed in subprocess — zones are defined and will fill when opened in KiCAD (press B). Continuing is safe.",
                        "zoneCount": zone_count,
                        "details": (
                            result.stderr[:300]
                            if result.stderr
                            else result.stdout[:300]
                        ),
                    }
            except subprocess.TimeoutExpired:
                logger.warning("Zone fill subprocess timed out after 60s")
                return {
                    "success": False,
                    "message": "Zone fill timed out — zones are defined and will fill when opened in KiCAD (press B). Continuing is safe.",
                    "zoneCount": zone_count,
                }

        except Exception as e:
            logger.error(f"Error refilling zones: {str(e)}")
            return {"success": False, "message": str(e)}

    # =========================================================================
    # Newly implemented tool handlers
    # =========================================================================

    def _handle_assign_net_to_class(self, params):
        """Assign a net to an existing net class"""
        try:
            if not self.board:
                return {"success": False, "message": "No board is loaded"}

            net_name = params.get("net")
            netclass_name = params.get("netClass")

            if not net_name or not netclass_name:
                return {"success": False, "message": "Missing 'net' or 'netClass' parameter"}

            netinfo = self.board.GetNetInfo()
            nets_map = netinfo.NetsByName()
            if not nets_map.has_key(net_name):
                return {"success": False, "message": f"Net '{net_name}' not found"}

            net_classes = self.board.GetNetClasses()
            netclass = net_classes.Find(netclass_name)
            if not netclass:
                return {"success": False, "message": f"Net class '{netclass_name}' not found"}

            net_obj = nets_map[net_name]
            net_obj.SetClass(netclass)

            return {
                "success": True,
                "message": f"Assigned net '{net_name}' to class '{netclass_name}'",
                "net": net_name,
                "netClass": netclass_name,
            }
        except Exception as e:
            logger.error(f"Error assigning net to class: {e}")
            return {"success": False, "message": str(e)}

    def _handle_set_layer_constraints(self, params):
        """Set design constraints (applied globally — KiCAD 9 Python API does not support per-layer rules)"""
        try:
            if not self.board:
                return {"success": False, "message": "No board is loaded"}

            min_track_width = params.get("minTrackWidth")
            min_clearance = params.get("minClearance")
            min_via_diameter = params.get("minViaDiameter")
            min_via_drill = params.get("minViaDrill")

            ds = self.board.GetDesignSettings()
            scale = 1000000  # mm to nm

            if min_track_width is not None:
                ds.m_TrackMinWidth = int(min_track_width * scale)
            if min_clearance is not None:
                ds.m_MinClearance = int(min_clearance * scale)
            if min_via_diameter is not None:
                ds.m_ViasMinSize = int(min_via_diameter * scale)
            if min_via_drill is not None:
                ds.m_MinThroughDrill = int(min_via_drill * scale)

            return {
                "success": True,
                "message": "Updated design constraints",
                "note": "KiCAD 9 Python API applies these globally, not per-layer",
                "constraints": {
                    "minTrackWidth": ds.m_TrackMinWidth / scale,
                    "minClearance": ds.m_MinClearance / scale,
                    "minViaDiameter": ds.m_ViasMinSize / scale,
                    "minViaDrill": ds.m_MinThroughDrill / scale,
                },
            }
        except Exception as e:
            logger.error(f"Error setting layer constraints: {e}")
            return {"success": False, "message": str(e)}

    def _handle_check_clearance(self, params):
        """Check clearance between two components (simplified — use run_drc for full check)"""
        try:
            if not self.board:
                return {"success": False, "message": "No board is loaded"}

            item1 = params.get("item1", {})
            item2 = params.get("item2", {})

            ref1 = item1.get("reference") or item1.get("id", "")
            ref2 = item2.get("reference") or item2.get("id", "")

            mod1 = self.board.FindFootprintByReference(ref1)
            mod2 = self.board.FindFootprintByReference(ref2)

            if not mod1:
                return {"success": False, "message": f"Component '{ref1}' not found"}
            if not mod2:
                return {"success": False, "message": f"Component '{ref2}' not found"}

            pos1 = mod1.GetPosition()
            pos2 = mod2.GetPosition()
            dx = (pos2.x - pos1.x) / 1000000.0
            dy = (pos2.y - pos1.y) / 1000000.0
            distance = (dx**2 + dy**2) ** 0.5

            min_clearance = self.board.GetDesignSettings().m_MinClearance / 1000000.0
            passes = distance >= min_clearance

            return {
                "success": True,
                "clearanceCheck": {
                    "item1": ref1,
                    "item2": ref2,
                    "distanceMm": round(distance, 4),
                    "minClearanceMm": round(min_clearance, 4),
                    "passes": passes,
                },
                "note": "Center-to-center distance check. Use run_drc for full DRC.",
            }
        except Exception as e:
            logger.error(f"Error checking clearance: {e}")
            return {"success": False, "message": str(e)}

    def _handle_add_component_annotation(self, params):
        """Add a text field annotation to a footprint"""
        try:
            if not self.board:
                return {"success": False, "message": "No board is loaded"}

            reference = params.get("reference")
            annotation = params.get("annotation")
            visible = params.get("visible", True)

            if not reference or not annotation:
                return {"success": False, "message": "Missing 'reference' or 'annotation'"}

            module = self.board.FindFootprintByReference(reference)
            if not module:
                return {"success": False, "message": f"Component '{reference}' not found"}

            field_id = module.GetNextFieldId()
            field = pcbnew.PCB_FIELD(module, field_id, "Annotation")
            field.SetText(annotation)
            field.SetVisible(visible)
            field.SetPosition(module.GetPosition())
            module.AddField(field)

            return {
                "success": True,
                "message": f"Added annotation to {reference}",
                "field": {"id": field_id, "text": annotation, "visible": visible},
            }
        except Exception as e:
            logger.error(f"Error adding component annotation: {e}")
            return {"success": False, "message": str(e)}

    def _handle_group_components(self, params):
        """Group multiple components together on the board"""
        try:
            if not self.board:
                return {"success": False, "message": "No board is loaded"}

            references = params.get("references", [])
            group_name = params.get("groupName", "Component Group")

            if not references:
                return {"success": False, "message": "No component references provided"}

            group = pcbnew.PCB_GROUP(self.board)
            group.SetName(group_name)

            added = []
            not_found = []
            for ref in references:
                module = self.board.FindFootprintByReference(ref)
                if module:
                    group.AddItem(module)
                    added.append(ref)
                else:
                    not_found.append(ref)

            if not added:
                return {"success": False, "message": "None of the specified components were found"}

            self.board.Add(group)

            result = {
                "success": True,
                "message": f"Grouped {len(added)} components as '{group_name}'",
                "group": {"name": group_name, "components": added},
            }
            if not_found:
                result["warnings"] = f"Components not found: {', '.join(not_found)}"
            return result
        except Exception as e:
            logger.error(f"Error grouping components: {e}")
            return {"success": False, "message": str(e)}

    def _handle_replace_component(self, params):
        """Replace a component's footprint on the board"""
        try:
            if not self.board:
                return {"success": False, "message": "No board is loaded"}

            reference = params.get("reference")
            new_footprint = params.get("newFootprint") or params.get("newComponentId")
            new_value = params.get("newValue")

            if not reference:
                return {"success": False, "message": "Missing 'reference' parameter"}
            if not new_footprint:
                return {"success": False, "message": "Missing 'newFootprint' or 'newComponentId'"}

            old_module = self.board.FindFootprintByReference(reference)
            if not old_module:
                return {"success": False, "message": f"Component '{reference}' not found"}

            # Save old properties
            old_pos = old_module.GetPosition()
            old_rot = old_module.GetOrientation()
            old_layer = old_module.GetLayer()
            old_value = old_module.GetValue()

            # Parse Library:Footprint format
            if ":" in new_footprint:
                lib_name, fp_name = new_footprint.split(":", 1)
            else:
                return {"success": False, "message": "newFootprint must be in 'Library:Footprint' format"}

            # Find library path
            lib_table = pcbnew.PROJECT.PcbFootprintLibs(self.board.GetProject())
            try:
                lib_row = lib_table.FindRow(lib_name)
                library_path = lib_row.GetFullURI(True)
            except Exception:
                return {"success": False, "message": f"Library '{lib_name}' not found"}

            # Load new footprint
            new_module = pcbnew.FootprintLoad(library_path, fp_name)
            if not new_module:
                return {"success": False, "message": f"Footprint '{fp_name}' not found in library '{lib_name}'"}

            # Apply old properties
            new_module.SetPosition(old_pos)
            new_module.SetOrientation(old_rot)
            new_module.SetLayer(old_layer)
            new_module.SetReference(reference)
            new_module.SetValue(new_value if new_value else old_value)

            # Set FPID
            fpid = pcbnew.LIB_ID(lib_name, fp_name)
            new_module.SetFPID(fpid)

            # Swap on board
            self.board.Remove(old_module)
            self.board.Add(new_module)

            return {
                "success": True,
                "message": f"Replaced {reference} with {new_footprint}",
                "component": {
                    "reference": reference,
                    "footprint": new_footprint,
                    "value": new_module.GetValue(),
                },
            }
        except Exception as e:
            logger.error(f"Error replacing component: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_netlist(self, params):
        """Export netlist from schematic using kicad-cli"""
        try:
            import subprocess

            output_path = params.get("outputPath")
            fmt = params.get("format", "kicadsexpr")

            if not output_path:
                return {"success": False, "message": "Missing 'outputPath' parameter"}

            # Find schematic file
            board_file = self.board.GetFileName() if self.board else None
            if not board_file:
                return {"success": False, "message": "Board must be saved first"}

            sch_file = board_file.replace(".kicad_pcb", ".kicad_sch")
            if not os.path.exists(sch_file):
                return {"success": False, "message": f"Schematic file not found: {sch_file}"}

            kicad_cli = self.export_commands._find_kicad_cli()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found"}

            output_path = os.path.abspath(os.path.expanduser(output_path))
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            cmd = [kicad_cli, "sch", "export", "netlist",
                   "--output", output_path, "--format", fmt, sch_file]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                return {"success": False, "message": "Netlist export failed",
                        "errorDetails": result.stderr[:500]}

            return {
                "success": True,
                "message": f"Exported netlist ({fmt})",
                "file": output_path,
                "format": fmt,
            }
        except Exception as e:
            logger.error(f"Error exporting netlist: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_position_file(self, params):
        """Export pick-and-place position file using kicad-cli"""
        try:
            import subprocess

            output_path = params.get("outputPath")
            fmt = params.get("format", "csv")
            units = params.get("units", "mm")
            side = params.get("side", "both")

            if not output_path:
                return {"success": False, "message": "Missing 'outputPath' parameter"}

            board_file = self.board.GetFileName() if self.board else None
            if not board_file or not os.path.exists(board_file):
                return {"success": False, "message": "Board must be saved first"}

            # Save board to ensure latest state
            self.board.Save(board_file)

            kicad_cli = self.export_commands._find_kicad_cli()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found"}

            output_path = os.path.abspath(os.path.expanduser(output_path))
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            cmd = [kicad_cli, "pcb", "export", "pos",
                   "--output", output_path,
                   "--format", fmt,
                   "--units", units,
                   "--side", side,
                   "--exclude-dnp",
                   board_file]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                return {"success": False, "message": "Position file export failed",
                        "errorDetails": result.stderr[:500]}

            return {
                "success": True,
                "message": f"Exported position file ({fmt})",
                "file": output_path,
                "format": fmt,
                "units": units,
                "side": side,
            }
        except Exception as e:
            logger.error(f"Error exporting position file: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_vrml(self, params):
        """Export PCB as VRML 3D model using kicad-cli"""
        try:
            import subprocess

            output_path = params.get("outputPath")
            include_components = params.get("includeComponents", True)
            use_relative_paths = params.get("useRelativePaths", False)

            if not output_path:
                return {"success": False, "message": "Missing 'outputPath' parameter"}

            board_file = self.board.GetFileName() if self.board else None
            if not board_file or not os.path.exists(board_file):
                return {"success": False, "message": "Board must be saved first"}

            self.board.Save(board_file)

            kicad_cli = self.export_commands._find_kicad_cli()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found"}

            output_path = os.path.abspath(os.path.expanduser(output_path))
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            cmd = [kicad_cli, "pcb", "export", "vrml",
                   "--output", output_path,
                   "--units", "mm",
                   "--force",
                   board_file]

            if not include_components:
                cmd.insert(-1, "--no-unspecified")
                cmd.insert(-1, "--no-dnp")

            if use_relative_paths:
                models_dir = os.path.join(os.path.dirname(output_path), "models")
                cmd.insert(-1, "--models-dir")
                cmd.insert(-1, models_dir)
                cmd.insert(-1, "--models-relative")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if result.returncode != 0:
                return {"success": False, "message": "VRML export failed",
                        "errorDetails": result.stderr[:500]}

            return {
                "success": True,
                "message": "Exported VRML file",
                "file": output_path,
                "includeComponents": include_components,
                "useRelativePaths": use_relative_paths,
            }
        except Exception as e:
            logger.error(f"Error exporting VRML: {e}")
            return {"success": False, "message": str(e)}

    # =========================================================================
    # IPC Backend handlers - these provide real-time UI synchronization
    # These methods are called automatically when IPC is available
    # =========================================================================

    def _ipc_route_trace(self, params):
        """IPC handler for route_trace - adds track with real-time UI update"""
        try:
            # Extract parameters matching the existing route_trace interface
            start = params.get("start", {})
            end = params.get("end", {})
            layer = params.get("layer", "F.Cu")
            width = params.get("width", 0.25)
            net = params.get("net")

            # Handle both dict format and direct x/y
            start_x = (
                start.get("x", 0)
                if isinstance(start, dict)
                else params.get("startX", 0)
            )
            start_y = (
                start.get("y", 0)
                if isinstance(start, dict)
                else params.get("startY", 0)
            )
            end_x = end.get("x", 0) if isinstance(end, dict) else params.get("endX", 0)
            end_y = end.get("y", 0) if isinstance(end, dict) else params.get("endY", 0)

            success = self.ipc_board_api.add_track(
                start_x=start_x,
                start_y=start_y,
                end_x=end_x,
                end_y=end_y,
                width=width,
                layer=layer,
                net_name=net,
            )

            return {
                "success": success,
                "message": (
                    "Added trace (visible in KiCAD UI)"
                    if success
                    else "Failed to add trace"
                ),
                "trace": {
                    "start": {"x": start_x, "y": start_y, "unit": "mm"},
                    "end": {"x": end_x, "y": end_y, "unit": "mm"},
                    "layer": layer,
                    "width": width,
                    "net": net,
                },
            }
        except Exception as e:
            logger.error(f"IPC route_trace error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_add_via(self, params):
        """IPC handler for add_via - adds via with real-time UI update"""
        try:
            position = params.get("position", {})
            x = (
                position.get("x", 0)
                if isinstance(position, dict)
                else params.get("x", 0)
            )
            y = (
                position.get("y", 0)
                if isinstance(position, dict)
                else params.get("y", 0)
            )

            size = params.get("size", 0.8)
            drill = params.get("drill", 0.4)
            net = params.get("net")
            from_layer = params.get("from_layer", "F.Cu")
            to_layer = params.get("to_layer", "B.Cu")

            success = self.ipc_board_api.add_via(
                x=x, y=y, diameter=size, drill=drill, net_name=net, via_type="through"
            )

            return {
                "success": success,
                "message": (
                    "Added via (visible in KiCAD UI)"
                    if success
                    else "Failed to add via"
                ),
                "via": {
                    "position": {"x": x, "y": y, "unit": "mm"},
                    "size": size,
                    "drill": drill,
                    "from_layer": from_layer,
                    "to_layer": to_layer,
                    "net": net,
                },
            }
        except Exception as e:
            logger.error(f"IPC add_via error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_add_net(self, params):
        """IPC handler for add_net"""
        # Note: Net creation via IPC is limited - nets are typically created
        # when components are placed. Return success for compatibility.
        name = params.get("name")
        logger.info(f"IPC add_net: {name} (nets auto-created with components)")
        return {
            "success": True,
            "message": f"Net '{name}' will be created when components are connected",
            "net": {"name": name},
        }

    def _ipc_add_copper_pour(self, params):
        """IPC handler for add_copper_pour - adds zone with real-time UI update"""
        try:
            layer = params.get("layer", "F.Cu")
            net = params.get("net")
            clearance = params.get("clearance", 0.5)
            min_width = params.get("minWidth", 0.25)
            points = params.get("points", [])
            priority = params.get("priority", 0)
            fill_type = params.get("fillType", "solid")
            name = params.get("name", "")

            if not points or len(points) < 3:
                return {
                    "success": False,
                    "message": "At least 3 points are required for copper pour outline",
                }

            # Convert points format if needed (handle both {x, y} and {x, y, unit})
            formatted_points = []
            for point in points:
                formatted_points.append(
                    {"x": point.get("x", 0), "y": point.get("y", 0)}
                )

            success = self.ipc_board_api.add_zone(
                points=formatted_points,
                layer=layer,
                net_name=net,
                clearance=clearance,
                min_thickness=min_width,
                priority=priority,
                fill_mode=fill_type,
                name=name,
            )

            return {
                "success": success,
                "message": (
                    "Added copper pour (visible in KiCAD UI)"
                    if success
                    else "Failed to add copper pour"
                ),
                "pour": {
                    "layer": layer,
                    "net": net,
                    "clearance": clearance,
                    "minWidth": min_width,
                    "priority": priority,
                    "fillType": fill_type,
                    "pointCount": len(points),
                },
            }
        except Exception as e:
            logger.error(f"IPC add_copper_pour error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_refill_zones(self, params):
        """IPC handler for refill_zones - refills all zones with real-time UI update"""
        try:
            success = self.ipc_board_api.refill_zones()

            return {
                "success": success,
                "message": (
                    "Zones refilled (visible in KiCAD UI)"
                    if success
                    else "Failed to refill zones"
                ),
            }
        except Exception as e:
            logger.error(f"IPC refill_zones error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_add_text(self, params):
        """IPC handler for add_text/add_board_text - adds text with real-time UI update"""
        try:
            text = params.get("text", "")
            position = params.get("position", {})
            x = (
                position.get("x", 0)
                if isinstance(position, dict)
                else params.get("x", 0)
            )
            y = (
                position.get("y", 0)
                if isinstance(position, dict)
                else params.get("y", 0)
            )
            layer = params.get("layer", "F.SilkS")
            size = params.get("size", 1.0)
            rotation = params.get("rotation", 0)

            success = self.ipc_board_api.add_text(
                text=text, x=x, y=y, layer=layer, size=size, rotation=rotation
            )

            return {
                "success": success,
                "message": (
                    f"Added text '{text}' (visible in KiCAD UI)"
                    if success
                    else "Failed to add text"
                ),
            }
        except Exception as e:
            logger.error(f"IPC add_text error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_set_board_size(self, params):
        """IPC handler for set_board_size"""
        try:
            width = params.get("width", 100)
            height = params.get("height", 100)
            unit = params.get("unit", "mm")

            success = self.ipc_board_api.set_size(width, height, unit)

            return {
                "success": success,
                "message": (
                    f"Board size set to {width}x{height} {unit} (visible in KiCAD UI)"
                    if success
                    else "Failed to set board size"
                ),
                "boardSize": {"width": width, "height": height, "unit": unit},
            }
        except Exception as e:
            logger.error(f"IPC set_board_size error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_get_board_info(self, params):
        """IPC handler for get_board_info"""
        try:
            size = self.ipc_board_api.get_size()
            components = self.ipc_board_api.list_components()
            tracks = self.ipc_board_api.get_tracks()
            vias = self.ipc_board_api.get_vias()
            nets = self.ipc_board_api.get_nets()

            return {
                "success": True,
                "boardInfo": {
                    "size": size,
                    "componentCount": len(components),
                    "trackCount": len(tracks),
                    "viaCount": len(vias),
                    "netCount": len(nets),
                    "backend": "ipc",
                    "realtime": True,
                },
            }
        except Exception as e:
            logger.error(f"IPC get_board_info error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_place_component(self, params):
        """IPC handler for place_component - places component with real-time UI update"""
        try:
            reference = params.get("reference", params.get("componentId", ""))
            footprint = params.get("footprint", "")
            position = params.get("position", {})
            x = (
                position.get("x", 0)
                if isinstance(position, dict)
                else params.get("x", 0)
            )
            y = (
                position.get("y", 0)
                if isinstance(position, dict)
                else params.get("y", 0)
            )
            rotation = params.get("rotation", 0)
            layer = params.get("layer", "F.Cu")
            value = params.get("value", "")

            success = self.ipc_board_api.place_component(
                reference=reference,
                footprint=footprint,
                x=x,
                y=y,
                rotation=rotation,
                layer=layer,
                value=value,
            )

            return {
                "success": success,
                "message": (
                    f"Placed component {reference} (visible in KiCAD UI)"
                    if success
                    else "Failed to place component"
                ),
                "component": {
                    "reference": reference,
                    "footprint": footprint,
                    "position": {"x": x, "y": y, "unit": "mm"},
                    "rotation": rotation,
                    "layer": layer,
                },
            }
        except Exception as e:
            logger.error(f"IPC place_component error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_move_component(self, params):
        """IPC handler for move_component - moves component with real-time UI update"""
        try:
            reference = params.get("reference", params.get("componentId", ""))
            position = params.get("position", {})
            x = (
                position.get("x", 0)
                if isinstance(position, dict)
                else params.get("x", 0)
            )
            y = (
                position.get("y", 0)
                if isinstance(position, dict)
                else params.get("y", 0)
            )
            rotation = params.get("rotation")

            success = self.ipc_board_api.move_component(
                reference=reference, x=x, y=y, rotation=rotation
            )

            return {
                "success": success,
                "message": (
                    f"Moved component {reference} (visible in KiCAD UI)"
                    if success
                    else "Failed to move component"
                ),
            }
        except Exception as e:
            logger.error(f"IPC move_component error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_delete_component(self, params):
        """IPC handler for delete_component - deletes component with real-time UI update"""
        try:
            reference = params.get("reference", params.get("componentId", ""))

            success = self.ipc_board_api.delete_component(reference=reference)

            return {
                "success": success,
                "message": (
                    f"Deleted component {reference} (visible in KiCAD UI)"
                    if success
                    else "Failed to delete component"
                ),
            }
        except Exception as e:
            logger.error(f"IPC delete_component error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_get_component_list(self, params):
        """IPC handler for get_component_list"""
        try:
            components = self.ipc_board_api.list_components()

            return {"success": True, "components": components, "count": len(components)}
        except Exception as e:
            logger.error(f"IPC get_component_list error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_save_project(self, params):
        """IPC handler for save_project"""
        try:
            success = self.ipc_board_api.save()

            return {
                "success": success,
                "message": "Project saved" if success else "Failed to save project",
            }
        except Exception as e:
            logger.error(f"IPC save_project error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_delete_trace(self, params):
        """IPC handler for delete_trace - Note: IPC doesn't support direct trace deletion yet"""
        # IPC API doesn't have a direct delete track method
        # Fall back to SWIG for this operation
        logger.info(
            "delete_trace: Falling back to SWIG (IPC doesn't support trace deletion)"
        )
        return self.routing_commands.delete_trace(params)

    def _ipc_get_nets_list(self, params):
        """IPC handler for get_nets_list - gets nets with real-time data"""
        try:
            nets = self.ipc_board_api.get_nets()

            return {"success": True, "nets": nets, "count": len(nets)}
        except Exception as e:
            logger.error(f"IPC get_nets_list error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_add_board_outline(self, params):
        """IPC handler for add_board_outline - adds board edge with real-time UI update.
        Rounded rectangles are delegated to the SWIG path because the IPC BoardSegment
        type cannot represent arcs; the SWIG path writes directly to the .kicad_pcb file
        and correctly generates PCB_SHAPE arcs for rounded corners.
        """
        shape = params.get("shape", "rectangle")
        if shape in ("rounded_rectangle", "rectangle"):
            # IPC path only supports straight segments from a points list,
            # but Claude sends rectangle/rounded_rectangle as shape+width+height.
            # Fall back to the SWIG path which correctly handles both shapes.
            logger.info(f"_ipc_add_board_outline: delegating {shape} to SWIG path")
            return self.board_commands.add_board_outline(params)

        try:
            from kipy.board_types import BoardSegment
            from kipy.geometry import Vector2
            from kipy.util.units import from_mm
            from kipy.proto.board.board_types_pb2 import BoardLayer

            board = self.ipc_board_api._get_board()

            # Unwrap nested params (Claude sends {"shape":..., "params":{...}})
            inner = params.get("params", params)
            points = inner.get("points", params.get("points", []))
            width = inner.get("width", params.get("width", 0.1))

            if len(points) < 2:
                return {
                    "success": False,
                    "message": "At least 2 points required for board outline",
                }

            commit = board.begin_commit()
            lines_created = 0

            # Create line segments connecting the points
            for i in range(len(points)):
                start = points[i]
                end = points[(i + 1) % len(points)]  # Wrap around to close the outline

                segment = BoardSegment()
                segment.start = Vector2.from_xy(
                    from_mm(start.get("x", 0)), from_mm(start.get("y", 0))
                )
                segment.end = Vector2.from_xy(
                    from_mm(end.get("x", 0)), from_mm(end.get("y", 0))
                )
                segment.layer = BoardLayer.BL_Edge_Cuts
                segment.attributes.stroke.width = from_mm(width)

                board.create_items(segment)
                lines_created += 1

            board.push_commit(commit, "Added board outline")

            return {
                "success": True,
                "message": f"Added board outline with {lines_created} segments (visible in KiCAD UI)",
                "segments": lines_created,
            }
        except Exception as e:
            logger.error(f"IPC add_board_outline error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_add_mounting_hole(self, params):
        """IPC handler for add_mounting_hole - adds mounting hole with real-time UI update"""
        try:
            from kipy.board_types import BoardCircle
            from kipy.geometry import Vector2
            from kipy.util.units import from_mm
            from kipy.proto.board.board_types_pb2 import BoardLayer

            board = self.ipc_board_api._get_board()

            x = params.get("x", 0)
            y = params.get("y", 0)
            diameter = params.get("diameter", 3.2)  # M3 hole default

            commit = board.begin_commit()

            # Create circle on Edge.Cuts layer for the hole
            circle = BoardCircle()
            circle.center = Vector2.from_xy(from_mm(x), from_mm(y))
            circle.radius = from_mm(diameter / 2)
            circle.layer = BoardLayer.BL_Edge_Cuts
            circle.attributes.stroke.width = from_mm(0.1)

            board.create_items(circle)
            board.push_commit(commit, f"Added mounting hole at ({x}, {y})")

            return {
                "success": True,
                "message": f"Added mounting hole at ({x}, {y}) mm (visible in KiCAD UI)",
                "hole": {"position": {"x": x, "y": y}, "diameter": diameter},
            }
        except Exception as e:
            logger.error(f"IPC add_mounting_hole error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_get_layer_list(self, params):
        """IPC handler for get_layer_list - gets enabled layers"""
        try:
            layers = self.ipc_board_api.get_enabled_layers()

            return {"success": True, "layers": layers, "count": len(layers)}
        except Exception as e:
            logger.error(f"IPC get_layer_list error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_rotate_component(self, params):
        """IPC handler for rotate_component - rotates component with real-time UI update"""
        try:
            reference = params.get("reference", params.get("componentId", ""))
            angle = params.get("angle", params.get("rotation", 90))

            # Get current component to find its position
            components = self.ipc_board_api.list_components()
            target = None
            for comp in components:
                if comp.get("reference") == reference:
                    target = comp
                    break

            if not target:
                return {"success": False, "message": f"Component {reference} not found"}

            # Calculate new rotation
            current_rotation = target.get("rotation", 0)
            new_rotation = (current_rotation + angle) % 360

            # Use move_component with new rotation (position stays the same)
            success = self.ipc_board_api.move_component(
                reference=reference,
                x=target.get("position", {}).get("x", 0),
                y=target.get("position", {}).get("y", 0),
                rotation=new_rotation,
            )

            return {
                "success": success,
                "message": (
                    f"Rotated component {reference} by {angle}° (visible in KiCAD UI)"
                    if success
                    else "Failed to rotate component"
                ),
                "newRotation": new_rotation,
            }
        except Exception as e:
            logger.error(f"IPC rotate_component error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_get_component_properties(self, params):
        """IPC handler for get_component_properties - gets detailed component info"""
        try:
            reference = params.get("reference", params.get("componentId", ""))

            components = self.ipc_board_api.list_components()
            target = None
            for comp in components:
                if comp.get("reference") == reference:
                    target = comp
                    break

            if not target:
                return {"success": False, "message": f"Component {reference} not found"}

            return {"success": True, "component": target}
        except Exception as e:
            logger.error(f"IPC get_component_properties error: {e}")
            return {"success": False, "message": str(e)}

    # =========================================================================
    # Legacy IPC command handlers (explicit ipc_* commands)
    # =========================================================================

    def _handle_get_backend_info(self, params):
        """Get information about the current backend"""
        return {
            "success": True,
            "backend": "ipc" if self.use_ipc else "swig",
            "realtime_sync": self.use_ipc,
            "ipc_connected": (
                self.ipc_backend.is_connected() if self.ipc_backend else False
            ),
            "version": self.ipc_backend.get_version() if self.ipc_backend else "N/A",
            "message": (
                "Using IPC backend with real-time UI sync"
                if self.use_ipc
                else "Using SWIG backend (requires manual reload)"
            ),
        }

    def _handle_ipc_add_track(self, params):
        """Add a track using IPC backend (real-time)"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            success = self.ipc_board_api.add_track(
                start_x=params.get("startX", 0),
                start_y=params.get("startY", 0),
                end_x=params.get("endX", 0),
                end_y=params.get("endY", 0),
                width=params.get("width", 0.25),
                layer=params.get("layer", "F.Cu"),
                net_name=params.get("net"),
            )
            return {
                "success": success,
                "message": (
                    "Track added (visible in KiCAD UI)"
                    if success
                    else "Failed to add track"
                ),
                "realtime": True,
            }
        except Exception as e:
            logger.error(f"Error adding track via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_add_via(self, params):
        """Add a via using IPC backend (real-time)"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            success = self.ipc_board_api.add_via(
                x=params.get("x", 0),
                y=params.get("y", 0),
                diameter=params.get("diameter", 0.8),
                drill=params.get("drill", 0.4),
                net_name=params.get("net"),
                via_type=params.get("type", "through"),
            )
            return {
                "success": success,
                "message": (
                    "Via added (visible in KiCAD UI)"
                    if success
                    else "Failed to add via"
                ),
                "realtime": True,
            }
        except Exception as e:
            logger.error(f"Error adding via via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_add_text(self, params):
        """Add text using IPC backend (real-time)"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            success = self.ipc_board_api.add_text(
                text=params.get("text", ""),
                x=params.get("x", 0),
                y=params.get("y", 0),
                layer=params.get("layer", "F.SilkS"),
                size=params.get("size", 1.0),
                rotation=params.get("rotation", 0),
            )
            return {
                "success": success,
                "message": (
                    "Text added (visible in KiCAD UI)"
                    if success
                    else "Failed to add text"
                ),
                "realtime": True,
            }
        except Exception as e:
            logger.error(f"Error adding text via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_list_components(self, params):
        """List components using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            components = self.ipc_board_api.list_components()
            return {"success": True, "components": components, "count": len(components)}
        except Exception as e:
            logger.error(f"Error listing components via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_get_tracks(self, params):
        """Get tracks using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            tracks = self.ipc_board_api.get_tracks()
            return {"success": True, "tracks": tracks, "count": len(tracks)}
        except Exception as e:
            logger.error(f"Error getting tracks via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_get_vias(self, params):
        """Get vias using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            vias = self.ipc_board_api.get_vias()
            return {"success": True, "vias": vias, "count": len(vias)}
        except Exception as e:
            logger.error(f"Error getting vias via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_save_board(self, params):
        """Save board using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            success = self.ipc_board_api.save()
            return {
                "success": success,
                "message": "Board saved" if success else "Failed to save board",
            }
        except Exception as e:
            logger.error(f"Error saving board via IPC: {e}")
            return {"success": False, "message": str(e)}

    # JLCPCB API handlers

    def _handle_download_jlcpcb_database(self, params):
        """Download JLCPCB parts database from JLCSearch API"""
        try:
            force = params.get("force", False)

            # Check if database exists
            import os

            stats = self.jlcpcb_parts.get_database_stats()
            if stats["total_parts"] > 0 and not force:
                return {
                    "success": False,
                    "message": "Database already exists. Use force=true to re-download.",
                    "stats": stats,
                }

            logger.info("Downloading JLCPCB parts database from JLCSearch...")

            # Download parts from JLCSearch public API (no auth required)
            parts = self.jlcsearch_client.download_all_components(
                callback=lambda total, msg: logger.info(f"{msg}")
            )

            # Import into database
            logger.info(f"Importing {len(parts)} parts into database...")
            self.jlcpcb_parts.import_jlcsearch_parts(
                parts, progress_callback=lambda curr, total, msg: logger.info(msg)
            )

            # Get final stats
            stats = self.jlcpcb_parts.get_database_stats()

            # Calculate database size
            db_size_mb = os.path.getsize(self.jlcpcb_parts.db_path) / (1024 * 1024)

            return {
                "success": True,
                "total_parts": stats["total_parts"],
                "basic_parts": stats["basic_parts"],
                "extended_parts": stats["extended_parts"],
                "db_size_mb": round(db_size_mb, 2),
                "db_path": stats["db_path"],
            }

        except Exception as e:
            logger.error(f"Error downloading JLCPCB database: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to download database: {str(e)}",
            }

    def _handle_search_jlcpcb_parts(self, params):
        """Search JLCPCB parts database"""
        try:
            query = params.get("query")
            category = params.get("category")
            package = params.get("package")
            library_type = params.get("library_type", "All")
            manufacturer = params.get("manufacturer")
            in_stock = params.get("in_stock", True)
            limit = params.get("limit", 20)

            # Adjust library_type filter
            if library_type == "All":
                library_type = None

            parts = self.jlcpcb_parts.search_parts(
                query=query,
                category=category,
                package=package,
                library_type=library_type,
                manufacturer=manufacturer,
                in_stock=in_stock,
                limit=limit,
            )

            # Add price breaks and footprints to each part
            for part in parts:
                if part.get("price_json"):
                    try:
                        part["price_breaks"] = json.loads(part["price_json"])
                    except:
                        part["price_breaks"] = []

            return {"success": True, "parts": parts, "count": len(parts)}

        except Exception as e:
            logger.error(f"Error searching JLCPCB parts: {e}", exc_info=True)
            return {"success": False, "message": f"Search failed: {str(e)}"}

    def _handle_get_jlcpcb_part(self, params):
        """Get detailed information for a specific JLCPCB part"""
        try:
            lcsc_number = params.get("lcsc_number")
            if not lcsc_number:
                return {"success": False, "message": "Missing lcsc_number parameter"}

            part = self.jlcpcb_parts.get_part_info(lcsc_number)
            if not part:
                return {"success": False, "message": f"Part not found: {lcsc_number}"}

            # Get suggested KiCAD footprints
            footprints = self.jlcpcb_parts.map_package_to_footprint(
                part.get("package", "")
            )

            return {"success": True, "part": part, "footprints": footprints}

        except Exception as e:
            logger.error(f"Error getting JLCPCB part: {e}", exc_info=True)
            return {"success": False, "message": f"Failed to get part info: {str(e)}"}

    def _handle_get_jlcpcb_database_stats(self, params):
        """Get statistics about JLCPCB database"""
        try:
            stats = self.jlcpcb_parts.get_database_stats()
            return {"success": True, "stats": stats}

        except Exception as e:
            logger.error(f"Error getting database stats: {e}", exc_info=True)
            return {"success": False, "message": f"Failed to get stats: {str(e)}"}

    def _handle_suggest_jlcpcb_alternatives(self, params):
        """Suggest alternative JLCPCB parts"""
        try:
            lcsc_number = params.get("lcsc_number")
            limit = params.get("limit", 5)

            if not lcsc_number:
                return {"success": False, "message": "Missing lcsc_number parameter"}

            # Get original part for price comparison
            original_part = self.jlcpcb_parts.get_part_info(lcsc_number)
            reference_price = None
            if original_part and original_part.get("price_breaks"):
                try:
                    reference_price = float(
                        original_part["price_breaks"][0].get("price", 0)
                    )
                except:
                    pass

            alternatives = self.jlcpcb_parts.suggest_alternatives(lcsc_number, limit)

            # Add price breaks to alternatives
            for part in alternatives:
                if part.get("price_json"):
                    try:
                        part["price_breaks"] = json.loads(part["price_json"])
                    except:
                        part["price_breaks"] = []

            return {
                "success": True,
                "alternatives": alternatives,
                "reference_price": reference_price,
            }

        except Exception as e:
            logger.error(f"Error suggesting alternatives: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to suggest alternatives: {str(e)}",
            }

    def _handle_enrich_datasheets(self, params):
        """Enrich schematic Datasheet fields from LCSC numbers"""
        try:
            from pathlib import Path

            schematic_path = params.get("schematic_path")
            if not schematic_path:
                return {"success": False, "message": "Missing schematic_path parameter"}
            dry_run = params.get("dry_run", False)
            manager = DatasheetManager()
            return manager.enrich_schematic(Path(schematic_path), dry_run=dry_run)
        except Exception as e:
            logger.error(f"Error enriching datasheets: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to enrich datasheets: {str(e)}",
            }

    def _handle_get_datasheet_url(self, params):
        """Return LCSC datasheet and product URLs for a part number"""
        try:
            lcsc = params.get("lcsc", "")
            if not lcsc:
                return {"success": False, "message": "Missing lcsc parameter"}
            manager = DatasheetManager()
            datasheet_url = manager.get_datasheet_url(lcsc)
            product_url = manager.get_product_url(lcsc)
            if not datasheet_url:
                return {"success": False, "message": f"Invalid LCSC number: {lcsc}"}
            norm = manager._normalize_lcsc(lcsc)
            return {
                "success": True,
                "lcsc": norm,
                "datasheet_url": datasheet_url,
                "product_url": product_url,
            }
        except Exception as e:
            logger.error(f"Error getting datasheet URL: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to get datasheet URL: {str(e)}",
            }


def main():
    """Main entry point"""
    logger.info("Starting KiCAD interface...")
    interface = KiCADInterface()

    try:
        logger.info("Processing commands from stdin...")
        # Process commands from stdin
        for line in sys.stdin:
            try:
                # Parse command
                logger.debug(f"Received input: {line.strip()}")
                command_data = json.loads(line)

                # Check if this is JSON-RPC 2.0 format
                if "jsonrpc" in command_data and command_data["jsonrpc"] == "2.0":
                    logger.info("Detected JSON-RPC 2.0 format message")
                    method = command_data.get("method")
                    params = command_data.get("params", {})
                    request_id = command_data.get("id")

                    # Handle MCP protocol methods
                    if method == "initialize":
                        logger.info("Handling MCP initialize")
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "protocolVersion": "2025-06-18",
                                "capabilities": {
                                    "tools": {"listChanged": True},
                                    "resources": {
                                        "subscribe": False,
                                        "listChanged": True,
                                    },
                                },
                                "serverInfo": {
                                    "name": "kicad-mcp-server",
                                    "title": "KiCAD PCB Design Assistant",
                                    "version": "2.1.0-alpha",
                                },
                                "instructions": "AI-assisted PCB design with KiCAD. Use tools to create projects, design boards, place components, route traces, and export manufacturing files.",
                            },
                        }
                    elif method == "tools/list":
                        logger.info("Handling MCP tools/list")
                        # Return list of available tools with proper schemas
                        tools = []
                        for cmd_name in interface.command_routes.keys():
                            # Get schema from TOOL_SCHEMAS if available
                            if cmd_name in TOOL_SCHEMAS:
                                tool_def = TOOL_SCHEMAS[cmd_name].copy()
                                tools.append(tool_def)
                            else:
                                # Fallback for tools without schemas
                                logger.warning(
                                    f"No schema defined for tool: {cmd_name}"
                                )
                                tools.append(
                                    {
                                        "name": cmd_name,
                                        "description": f"KiCAD command: {cmd_name}",
                                        "inputSchema": {
                                            "type": "object",
                                            "properties": {},
                                        },
                                    }
                                )

                        logger.info(f"Returning {len(tools)} tools")
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {"tools": tools},
                        }
                    elif method == "tools/call":
                        logger.info("Handling MCP tools/call")
                        tool_name = params.get("name")
                        tool_params = params.get("arguments", {})

                        # Execute the command
                        result = interface.handle_command(tool_name, tool_params)

                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "content": [
                                    {"type": "text", "text": json.dumps(result)}
                                ]
                            },
                        }
                    elif method == "resources/list":
                        logger.info("Handling MCP resources/list")
                        # Return list of available resources
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {"resources": RESOURCE_DEFINITIONS},
                        }
                    elif method == "resources/read":
                        logger.info("Handling MCP resources/read")
                        resource_uri = params.get("uri")

                        if not resource_uri:
                            response = {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "error": {
                                    "code": -32602,
                                    "message": "Missing required parameter: uri",
                                },
                            }
                        else:
                            # Read the resource
                            resource_data = handle_resource_read(
                                resource_uri, interface
                            )

                            response = {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "result": resource_data,
                            }
                    else:
                        logger.error(f"Unknown JSON-RPC method: {method}")
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {
                                "code": -32601,
                                "message": f"Method not found: {method}",
                            },
                        }
                else:
                    # Handle legacy custom format
                    logger.info("Detected custom format message")
                    command = command_data.get("command")
                    params = command_data.get("params", {})

                    if not command:
                        logger.error("Missing command field")
                        response = {
                            "success": False,
                            "message": "Missing command",
                            "errorDetails": "The command field is required",
                        }
                    else:
                        # Handle command
                        response = interface.handle_command(command, params)

                # Send response
                logger.debug(f"Sending response: {response}")
                print(json.dumps(response))
                sys.stdout.flush()

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON input: {str(e)}")
                response = {
                    "success": False,
                    "message": "Invalid JSON input",
                    "errorDetails": str(e),
                }
                print(json.dumps(response))
                sys.stdout.flush()

    except KeyboardInterrupt:
        logger.info("KiCAD interface stopped")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}\n{traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
