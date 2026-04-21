#!/usr/bin/env python3
"""
KiCAD Python Interface Script for Model Context Protocol

This script handles communication between the MCP TypeScript server
and KiCAD's Python API (pcbnew). It receives commands via stdin as
JSON and returns responses via stdout also as JSON.
"""

import json
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from resources.resource_definitions import RESOURCE_DEFINITIONS, handle_resource_read

# Import tool schemas, resource definitions, and IPC API annotations
from schemas.tool_schemas import TOOL_SCHEMAS
from annotations import AnnotationLoader

_annotation_loader = AnnotationLoader()

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
                    d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))
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

from utils.kicad_process import KiCADProcessManager, check_and_launch_kicad

# Import platform helper and add KiCAD paths
from utils.platform_helper import PlatformHelper

logger.info(f"Detecting KiCAD Python paths for {PlatformHelper.get_platform_name()}...")
paths_added = PlatformHelper.add_kicad_to_python_path()

if paths_added:
    logger.info("Successfully added KiCAD Python paths to sys.path")
else:
    logger.warning("No KiCAD Python paths found - attempting to import pcbnew from system path")

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
    from commands.board import BoardCommands
    from commands.component import ComponentCommands
    from commands.component_schematic import ComponentManager
    from commands.connection_schematic import ConnectionManager
    from commands.datasheet_manager import DatasheetManager
    from commands.design_rules import DesignRuleCommands
    from commands.export import ExportCommands
    from commands.footprint import FootprintCreator
    from commands.freerouting import FreeroutingCommands
    from commands.jlcpcb import JLCPCBClient, test_jlcpcb_connection
    from commands.jlcpcb_parts import JLCPCBPartsManager
    from commands.library import (
        LibraryCommands,
    )
    from commands.library import LibraryManager as FootprintLibraryManager
    from commands.library_schematic import LibraryManager as SchematicLibraryManager
    from commands.library_symbol import SymbolLibraryCommands, SymbolLibraryManager
    from commands.project import ProjectCommands
    from commands.routing import RoutingCommands
    from commands.schematic import SchematicManager
    from commands.symbol_creator import SymbolCreator

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


class KiCADInterface:
    """Main interface class to handle KiCAD operations"""

    def __init__(self) -> None:
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
        self.freerouting_commands = FreeroutingCommands(self.board)
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

        # Schematic-related classes don't need board reference
        # as they operate directly on schematic files

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
            "route_differential_pair": self.routing_commands.route_differential_pair,
            "refill_zones": self._handle_refill_zones,
            # Design rule commands
            "set_design_rules": self.design_rule_commands.set_design_rules,
            "get_design_rules": self.design_rule_commands.get_design_rules,
            "run_drc": self.design_rule_commands.run_drc,
            "get_drc_violations": self.design_rule_commands.get_drc_violations,
            # Export commands
            "export_gerber": self.export_commands.export_gerber,
            "export_pdf": self.export_commands.export_pdf,
            "export_svg": self.export_commands.export_svg,
            "export_3d": self.export_commands.export_3d,
            "export_bom": self.export_commands.export_bom,
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
            "set_schematic_component_property": self._handle_set_schematic_component_property,
            "remove_schematic_component_property": self._handle_remove_schematic_component_property,
            "get_schematic_component": self._handle_get_schematic_component,
            "add_schematic_wire": self._handle_add_schematic_wire,
            "add_schematic_net_label": self._handle_add_schematic_net_label,
            "add_schematic_junction": self._handle_add_schematic_junction,
            "connect_to_net": self._handle_connect_to_net,
            "connect_passthrough": self._handle_connect_passthrough,
            "get_schematic_pin_locations": self._handle_get_schematic_pin_locations,
            "get_net_connections": self._handle_get_net_connections,
            "get_wire_connections": self._handle_get_wire_connections,
            "get_net_at_point": self._handle_get_net_at_point,
            "run_erc": self._handle_run_erc,
            "export_netlist": self._handle_export_netlist,
            "generate_netlist": self._handle_generate_netlist,
            "sync_schematic_to_board": self._handle_sync_schematic_to_board,
            "list_schematic_libraries": self._handle_list_schematic_libraries,
            "get_schematic_view": self._handle_get_schematic_view,
            "list_schematic_components": self._handle_list_schematic_components,
            "list_schematic_nets": self._handle_list_schematic_nets,
            "list_schematic_wires": self._handle_list_schematic_wires,
            "list_schematic_labels": self._handle_list_schematic_labels,
            "move_schematic_component": self._handle_move_schematic_component,
            "rotate_schematic_component": self._handle_rotate_schematic_component,
            "annotate_schematic": self._handle_annotate_schematic,
            "delete_schematic_wire": self._handle_delete_schematic_wire,
            "delete_schematic_net_label": self._handle_delete_schematic_net_label,
            "move_schematic_net_label": self._handle_move_schematic_net_label,
            "export_schematic_pdf": self._handle_export_schematic_pdf,
            "export_schematic_svg": self._handle_export_schematic_svg,
            # Schematic analysis tools (read-only)
            "get_schematic_view_region": self._handle_get_schematic_view_region,
            "find_overlapping_elements": self._handle_find_overlapping_elements,
            "get_elements_in_region": self._handle_get_elements_in_region,
            "find_wires_crossing_symbols": self._handle_find_wires_crossing_symbols,
            "find_orphaned_wires": self._handle_find_orphaned_wires,
            "list_floating_labels": self._handle_list_floating_labels,
            "snap_to_grid": self._handle_snap_to_grid,
            "add_schematic_hierarchical_label": self._handle_add_schematic_hierarchical_label,
            "add_schematic_text": self._handle_add_schematic_text,
            "list_schematic_texts": self._handle_list_schematic_texts,
            "add_sheet_pin": self._handle_add_sheet_pin,
            "import_svg_logo": self._handle_import_svg_logo,
            # UI/Process management commands
            "check_kicad_ui": self._handle_check_kicad_ui,
            "launch_kicad_ui": self._handle_launch_kicad_ui,
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
            # Freerouting autoroute commands
            "autoroute": self.freerouting_commands.autoroute,
            "export_dsn": self.freerouting_commands.export_dsn,
            "import_ses": self.freerouting_commands.import_ses,
            "check_freerouting": self.freerouting_commands.check_freerouting,
        }

        logger.info(f"KiCAD interface initialized (backend: {'IPC' if self.use_ipc else 'SWIG'})")

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
            if self.use_ipc and self.ipc_board_api and command in self.IPC_CAPABLE_COMMANDS:
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

    def _auto_save_board(self) -> None:
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

    def _update_command_handlers(self) -> None:
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
    def _handle_create_schematic(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new schematic"""
        logger.info("Creating schematic")
        try:
            # Support multiple parameter naming conventions for compatibility:
            # - TypeScript tools use: name, path
            # - Python schema uses: filename, title
            # - Legacy uses: projectName, path, metadata
            project_name = params.get("projectName") or params.get("name") or params.get("title")

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

            sch_path = path if path and path != "." else None
            schematic = SchematicManager.create_schematic(
                project_name, path=sch_path, metadata=metadata
            )
            base_name = (
                project_name if project_name.endswith(".kicad_sch") else f"{project_name}.kicad_sch"
            )
            normalized_path = path or "."
            file_path = os.path.join(normalized_path, base_name)
            success = SchematicManager.save_schematic(schematic, file_path)

            return {"success": success, "file_path": file_path}
        except Exception as e:
            logger.error(f"Error creating schematic: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_load_schematic(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _handle_place_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Place a component on the PCB, with project-local fp-lib-table support.
        If boardPath is given and differs from the currently loaded board, the
        board is reloaded from boardPath before placing — prevents silent failures
        when Claude provides a boardPath that was not yet loaded.
        """
        from pathlib import Path

        board_path = params.get("boardPath")
        if board_path:
            board_path_norm = str(Path(board_path).resolve())
            current_board_file = str(Path(self.board.GetFileName()).resolve()) if self.board else ""
            if board_path_norm != current_board_file:
                logger.info(f"boardPath differs from current board — reloading: {board_path}")
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
                logger.info(f"Reloaded FootprintLibraryManager with project_path={project_path}")

        return self.component_commands.place_component(params)

    def _handle_add_schematic_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
            unit = component.get("unit", 1)

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
                unit=unit,
                project_path=derived_project_path,
            )

            return {
                "success": True,
                "component_reference": reference,
                "symbol_source": f"{library}:{comp_type}",
            }
        except Exception as e:
            logger.error(f"Error adding component to schematic: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_delete_schematic_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Remove a placed symbol from a schematic using text-based manipulation (no skip writes)"""
        logger.info("Deleting schematic component")
        try:
            import re
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

            def find_matching_paren(s: str, start: int) -> int:
                """Find the closing paren matching the opening paren at start."""
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
            lib_sym_end = find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1

            # Find ALL placed symbol blocks matching the reference (handles duplicates).
            # Use content-string search so multi-line KiCAD format is handled correctly:
            # KiCAD writes (symbol\n\t\t(lib_id "...") across two lines, which a
            # line-by-line regex would never match.
            blocks_to_delete = []  # list of (char_start, char_end) into content
            search_start = 0
            pattern = re.compile(r'\(symbol\s+\(lib_id\s+"')
            while True:
                m = pattern.search(content, search_start)
                if not m:
                    break
                pos = m.start()
                # Skip blocks inside lib_symbols
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
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic (note: this tool removes schematic symbols, use delete_component for PCB footprints)",
                }

            # Delete from back to front to preserve character offsets
            for b_start, b_end in sorted(blocks_to_delete, reverse=True):
                # Include any leading newline/whitespace before the block
                trim_start = b_start
                while trim_start > 0 and content[trim_start - 1] in (" ", "\t"):
                    trim_start -= 1
                if trim_start > 0 and content[trim_start - 1] == "\n":
                    trim_start -= 1
                content = content[:trim_start] + content[b_end + 1 :]

            with open(sch_file, "w", encoding="utf-8") as f:
                f.write(content)

            deleted_count = len(blocks_to_delete)
            logger.info(f"Deleted {deleted_count} instance(s) of {reference} from {sch_file.name}")
            return {
                "success": True,
                "reference": reference,
                "deleted_count": deleted_count,
                "schematic": str(sch_file),
            }

        except Exception as e:
            logger.error(f"Error deleting schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    # Built-in property names that have dedicated parameters and cannot be removed
    # via the generic removeProperties path. They are also written by KiCad on every
    # save, so deleting them produces an invalid schematic.
    _PROTECTED_PROPERTY_FIELDS = frozenset({"Reference", "Value", "Footprint", "Datasheet"})

    @staticmethod
    def _escape_sexpr_string(value: str) -> str:
        """Escape a string for safe insertion into an S-expression double-quoted token."""
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _find_matching_paren(s: str, start: int) -> int:
        """Return the index of the closing paren matching the opening paren at `start`.

        Returns -1 if no match is found. Does not understand string literals — that's
        fine for KiCAD .kicad_sch files because property values cannot contain a
        bare `(` or `)` character (they would be backslash-escaped).
        """
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

    def _set_property_in_block(
        self,
        block: str,
        name: str,
        spec: Dict[str, Any],
        default_position: Tuple[float, float],
    ) -> Tuple[str, str]:
        """Add or update a property within a placed-symbol block.

        Args:
            block: The full text of the (symbol ...) block.
            name: Property name (e.g. "MPN", "Manufacturer").
            spec: Dict that may contain keys: value, x, y, angle, hide, fontSize.
            default_position: (x, y) of the parent symbol — used as the default
                location for newly-created properties so the field is anchored
                near the component, not at (0, 0).

        Returns:
            Tuple of (new_block_text, action_taken) where action is "added" or "updated".
        """
        import re

        new_value = spec.get("value")
        new_x = spec.get("x")
        new_y = spec.get("y")
        new_angle = spec.get("angle")
        new_hide = spec.get("hide")
        font_size = spec.get("fontSize", 1.27)

        existing_match = re.search(
            r'\(property\s+"' + re.escape(name) + r'"\s+"',
            block,
        )

        if existing_match:
            # Property exists — patch value / position / hide in place
            if new_value is not None:
                escaped = self._escape_sexpr_string(str(new_value))
                block = re.sub(
                    r'(\(property\s+"' + re.escape(name) + r'"\s+)"[^"]*"',
                    rf'\1"{escaped}"',
                    block,
                    count=1,
                )

            if new_x is not None or new_y is not None or new_angle is not None:
                pos_match = re.search(
                    r'(\(property\s+"'
                    + re.escape(name)
                    + r'"\s+"[^"]*"\s+\(at\s+)([\d\.\-]+)\s+([\d\.\-]+)\s+([\d\.\-]+)(\s*\))',
                    block,
                )
                if pos_match:
                    cx = new_x if new_x is not None else float(pos_match.group(2))
                    cy = new_y if new_y is not None else float(pos_match.group(3))
                    ca = new_angle if new_angle is not None else float(pos_match.group(4))
                    block = (
                        block[: pos_match.start()]
                        + pos_match.group(1)
                        + f"{cx} {cy} {ca}"
                        + pos_match.group(5)
                        + block[pos_match.end() :]
                    )

            if new_hide is not None:
                block = self._set_hide_on_property(block, name, bool(new_hide))

            return block, "updated"

        # Property does not exist — append a new one after the last existing property
        if new_value is None:
            # Adding a brand-new property requires at least a value
            raise ValueError(
                f"Property '{name}' does not exist on this component yet — supply a value to create it"
            )

        cx = new_x if new_x is not None else default_position[0]
        cy = new_y if new_y is not None else default_position[1]
        ca = new_angle if new_angle is not None else 0
        # New properties default to hidden (BOM/sourcing data normally has no
        # visible footprint on the schematic canvas).
        hide_str = "(hide yes)" if (new_hide is None or new_hide) else "(hide no)"
        escaped = self._escape_sexpr_string(str(new_value))
        escaped_name = self._escape_sexpr_string(str(name))

        new_prop = (
            f'    (property "{escaped_name}" "{escaped}" (at {cx} {cy} {ca})\n'
            f"      (effects (font (size {font_size} {font_size})) {hide_str})\n"
            f"    )"
        )

        # Find the last existing property block and insert immediately after it.
        last_prop_end = -1
        for m in re.finditer(r'\(property\s+"', block):
            end = self._find_matching_paren(block, m.start())
            if end > last_prop_end:
                last_prop_end = end

        if last_prop_end < 0:
            # No properties at all — insert just before the closing paren of the symbol
            block_close = block.rfind(")")
            if block_close < 0:
                raise ValueError("Malformed symbol block: no closing paren")
            block = block[:block_close] + "\n" + new_prop + "\n  " + block[block_close:]
        else:
            block = block[: last_prop_end + 1] + "\n" + new_prop + block[last_prop_end + 1 :]

        return block, "added"

    def _set_hide_on_property(self, block: str, name: str, hide: bool) -> str:
        """Set the (hide yes|no) flag on a named property's effects clause.

        Handles three pre-existing forms:
            (effects (font (size 1.27 1.27)))                   — no hide flag
            (effects (font (size 1.27 1.27)) hide)              — legacy bare token
            (effects (font (size 1.27 1.27)) (hide yes|no))     — KiCad 9 form
        """
        import re

        prop_match = re.search(
            r'\(property\s+"' + re.escape(name) + r'"',
            block,
        )
        if not prop_match:
            return block
        prop_start = prop_match.start()
        prop_end = self._find_matching_paren(block, prop_start)
        if prop_end < 0:
            return block

        # Locate the (effects ...) clause inside the property
        prop_segment = block[prop_start : prop_end + 1]
        eff_match = re.search(r"\(effects\b", prop_segment)
        if not eff_match:
            return block
        eff_start = prop_start + eff_match.start()
        eff_end = self._find_matching_paren(block, eff_start)
        if eff_end < 0:
            return block

        eff_inner = block[eff_start + 1 : eff_end]  # 'effects (font ...) ...'
        eff_inner = re.sub(r"\s*\(hide\s+(yes|no)\)", "", eff_inner)
        eff_inner = re.sub(r"\s+hide\b(?!\s+(yes|no))", "", eff_inner)
        eff_inner = eff_inner.rstrip() + f' (hide {"yes" if hide else "no"})'

        new_effects = "(" + eff_inner + ")"
        return block[:eff_start] + new_effects + block[eff_end + 1 :]

    def _remove_property_from_block(self, block: str, name: str) -> Tuple[str, bool]:
        """Remove a property from the symbol block. Returns (new_block, removed_bool)."""
        import re

        m = re.search(r'\(property\s+"' + re.escape(name) + r'"\s+"', block)
        if not m:
            return block, False
        start = m.start()
        end = self._find_matching_paren(block, start)
        if end < 0:
            return block, False

        # Trim surrounding whitespace (leading newline + indent) so the resulting
        # file does not develop blank lines after every removal.
        trim_start = start
        while trim_start > 0 and block[trim_start - 1] in (" ", "\t"):
            trim_start -= 1
        if trim_start > 0 and block[trim_start - 1] == "\n":
            trim_start -= 1
        return block[:trim_start] + block[end + 1 :], True

    def _handle_edit_schematic_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Update properties of a placed symbol in a schematic.

        Supports updating the standard fields (footprint / value / reference rename),
        repositioning field labels, and managing **arbitrary custom properties**
        (MPN, Manufacturer, Distributor part numbers, Voltage, Dielectric, Tolerance,
        LCSC, etc.) used by BOM/CPL exporters and JLCPCB / Digi-Key sourcing.

        Uses text-based in-place editing — preserves position, UUID, and all
        unrelated fields.
        """
        logger.info("Editing schematic component")
        try:
            import re
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            new_footprint = params.get("footprint")
            new_value = params.get("value")
            new_reference = params.get("newReference")
            # dict: {"Reference": {"x": 1, "y": 2, "angle": 0}}
            field_positions = params.get("fieldPositions")
            # dict: {"MPN": "RC0603FR-0710KL"}  OR  {"MPN": {"value": "...", "hide": true}}
            properties = params.get("properties")
            # list[str]: ["OldField"] — protected built-ins are rejected
            remove_properties = params.get("removeProperties")

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
                    properties is not None,
                    remove_properties is not None,
                ]
            ):
                return {
                    "success": False,
                    "message": (
                        "At least one of footprint, value, newReference, fieldPositions, "
                        "properties, or removeProperties must be provided"
                    ),
                }

            # Reject removal attempts targeting protected built-in fields up-front
            if remove_properties:
                blocked = [n for n in remove_properties if n in self._PROTECTED_PROPERTY_FIELDS]
                if blocked:
                    return {
                        "success": False,
                        "message": (
                            f"Cannot remove built-in field(s) {blocked}: use the dedicated "
                            "value/footprint/newReference parameters or set the value to ''"
                        ),
                    }

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            # Skip lib_symbols section
            lib_sym_pos = content.find("(lib_symbols")
            lib_sym_end = (
                self._find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1
            )

            # Find placed symbol blocks that match the reference
            # Search for (symbol (lib_id "...") ... (property "Reference" "<ref>" ...) ...)
            block_start = block_end = None
            search_start = 0
            pattern = re.compile(r'\(symbol\s+\(lib_id\s+"')
            while True:
                m = pattern.search(content, search_start)
                if not m:
                    break
                pos = m.start()
                # Skip if inside lib_symbols section
                if lib_sym_pos >= 0 and lib_sym_pos <= pos <= lib_sym_end:
                    search_start = lib_sym_end + 1
                    continue
                end = self._find_matching_paren(content, pos)
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

            if block_start is None or block_end is None:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic",
                }

            # Apply property replacements within the found block
            block_text = content[block_start : block_end + 1]

            # Determine the parent symbol position so that newly-added properties
            # default to a sensible location (anchored near the component).
            comp_at = re.search(
                r'\(symbol\s+\(lib_id\s+"[^"]*"\s*\)\s+\(at\s+([\d\.\-]+)\s+([\d\.\-]+)',
                block_text,
            )
            comp_origin: Tuple[float, float] = (
                (float(comp_at.group(1)), float(comp_at.group(2))) if comp_at else (0.0, 0.0)
            )

            if new_footprint is not None:
                escaped_fp = self._escape_sexpr_string(str(new_footprint))
                block_text = re.sub(
                    r'(\(property\s+"Footprint"\s+)"[^"]*"',
                    rf'\1"{escaped_fp}"',
                    block_text,
                )
            if new_value is not None:
                escaped_v = self._escape_sexpr_string(str(new_value))
                block_text = re.sub(
                    r'(\(property\s+"Value"\s+)"[^"]*"',
                    rf'\1"{escaped_v}"',
                    block_text,
                )
            if new_reference is not None:
                escaped_r = self._escape_sexpr_string(str(new_reference))
                block_text = re.sub(
                    r'(\(property\s+"Reference"\s+)"[^"]*"',
                    rf'\1"{escaped_r}"',
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

            properties_added: Dict[str, Any] = {}
            properties_updated: Dict[str, Any] = {}
            if properties:
                if not isinstance(properties, dict):
                    return {
                        "success": False,
                        "message": "properties must be a dict mapping property name -> value or spec",
                    }
                for name, spec in properties.items():
                    if not isinstance(name, str) or not name:
                        return {
                            "success": False,
                            "message": f"Invalid property name: {name!r}",
                        }
                    # Normalise scalar values to a spec dict with just {"value": ...}
                    if not isinstance(spec, dict):
                        spec = {"value": spec}
                    try:
                        block_text, action = self._set_property_in_block(
                            block_text, name, spec, comp_origin
                        )
                    except ValueError as ve:
                        return {"success": False, "message": str(ve)}
                    target = properties_added if action == "added" else properties_updated
                    target[name] = spec.get("value")

            properties_removed: list = []
            if remove_properties:
                if not isinstance(remove_properties, list):
                    return {
                        "success": False,
                        "message": "removeProperties must be a list of property names",
                    }
                for name in remove_properties:
                    block_text, removed = self._remove_property_from_block(block_text, name)
                    if removed:
                        properties_removed.append(name)

            content = content[:block_start] + block_text + content[block_end + 1 :]

            with open(sch_file, "w", encoding="utf-8") as f:
                f.write(content)

            changes: Dict[str, Any] = {
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
            if properties_added:
                changes["propertiesAdded"] = properties_added
            if properties_updated:
                changes["propertiesUpdated"] = properties_updated
            if properties_removed:
                changes["propertiesRemoved"] = properties_removed

            logger.info(f"Edited schematic component {reference}: {changes}")
            return {"success": True, "reference": reference, "updated": changes}

        except Exception as e:
            logger.error(f"Error editing schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_set_schematic_component_property(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add or update a single property on a placed schematic symbol.

        Convenience wrapper around `edit_schematic_component` for the very common
        case of setting one BOM/sourcing field at a time. The property is created
        if it does not already exist, otherwise its value (and optionally its
        position / visibility) is updated in place.
        """
        logger.info("Setting schematic component property")
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return {"success": False, "message": "name is required"}
        if "value" not in params:
            return {"success": False, "message": "value is required"}

        spec: Dict[str, Any] = {"value": params["value"]}
        for key in ("x", "y", "angle", "hide", "fontSize"):
            if params.get(key) is not None:
                spec[key] = params[key]

        return self._handle_edit_schematic_component(
            {
                "schematicPath": params.get("schematicPath"),
                "reference": params.get("reference"),
                "properties": {name: spec},
            }
        )

    def _handle_remove_schematic_component_property(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Remove a single custom property from a placed schematic symbol.

        Built-in fields (Reference, Value, Footprint, Datasheet) cannot be
        removed — use `edit_schematic_component` to clear them instead.
        """
        logger.info("Removing schematic component property")
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return {"success": False, "message": "name is required"}
        return self._handle_edit_schematic_component(
            {
                "schematicPath": params.get("schematicPath"),
                "reference": params.get("reference"),
                "removeProperties": [name],
            }
        )

    def _handle_get_schematic_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return full component info: position and all field values with their (at x y angle) positions."""
        logger.info("Getting schematic component info")
        try:
            import re
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

            def find_matching_paren(s: str, start: int) -> int:
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
            lib_sym_end = find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1

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

            if block_start is None or block_end is None:
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
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_add_schematic_wire(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a wire to a schematic using WireManager, with optional pin snapping"""
        logger.info("Adding wire to schematic")
        try:
            from pathlib import Path

            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            points = params.get("waypoints")
            properties = params.get("properties", {})
            snap_to_pins = params.get("snapToPins", True)
            snap_tolerance = params.get("snapTolerance", 1.0)

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not points or len(points) < 2:
                return {
                    "success": False,
                    "message": "At least 2 waypoints are required",
                }

            # Make a mutable copy of points
            points = [list(p) for p in points]

            # Pin snapping: adjust first and last endpoints to nearest pin
            snapped_info = []
            if snap_to_pins:
                from commands.pin_locator import PinLocator

                locator = PinLocator()
                sch_path = Path(schematic_path)

                # Load schematic to iterate all symbols
                from skip import Schematic as SkipSchematic

                sch = SkipSchematic(str(sch_path))

                # Collect all pin locations: list of (ref, pin_num, [x, y])
                all_pins = []
                for symbol in sch.symbol:
                    if not hasattr(symbol.property, "Reference"):
                        continue
                    ref = symbol.property.Reference.value
                    if ref.startswith("_TEMPLATE"):
                        continue
                    pin_locs = locator.get_all_symbol_pins(sch_path, ref)
                    for pin_num, coords in pin_locs.items():
                        all_pins.append((ref, pin_num, coords))

                def find_nearest_pin(point: Any, tolerance: Any) -> Any:
                    """Find the nearest pin within tolerance of a point."""
                    best = None
                    best_dist = tolerance
                    for ref, pin_num, coords in all_pins:
                        dx = point[0] - coords[0]
                        dy = point[1] - coords[1]
                        dist = (dx * dx + dy * dy) ** 0.5
                        if dist <= best_dist:
                            best_dist = dist
                            best = (ref, pin_num, coords)
                    return best

                # Snap first endpoint
                match = find_nearest_pin(points[0], snap_tolerance)
                if match:
                    ref, pin_num, coords = match
                    logger.info(
                        f"Snapped start point {points[0]} -> {coords} (pin {ref}/{pin_num})"
                    )
                    snapped_info.append(
                        f"start snapped to {ref}/{pin_num} at [{coords[0]}, {coords[1]}]"
                    )
                    points[0] = list(coords)

                # Snap last endpoint
                match = find_nearest_pin(points[-1], snap_tolerance)
                if match:
                    ref, pin_num, coords = match
                    logger.info(f"Snapped end point {points[-1]} -> {coords} (pin {ref}/{pin_num})")
                    snapped_info.append(
                        f"end snapped to {ref}/{pin_num} at [{coords[0]}, {coords[1]}]"
                    )
                    points[-1] = list(coords)

            # Extract wire properties
            stroke_width = properties.get("stroke_width", 0)
            stroke_type = properties.get("stroke_type", "default")

            # Use WireManager for S-expression manipulation
            if len(points) == 2:
                success = WireManager.add_wire(
                    Path(schematic_path),
                    points[0],
                    points[1],
                    stroke_width=stroke_width,
                    stroke_type=stroke_type,
                )
            else:
                success = WireManager.add_polyline_wire(
                    Path(schematic_path),
                    points,
                    stroke_width=stroke_width,
                    stroke_type=stroke_type,
                )

            if success:
                message = "Wire added successfully"
                if snapped_info:
                    message += "; " + "; ".join(snapped_info)
                return {"success": True, "message": message}
            else:
                return {"success": False, "message": "Failed to add wire"}
        except Exception as e:
            logger.error(f"Error adding wire to schematic: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_add_schematic_junction(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a junction (connection dot) to a schematic using WireManager"""
        logger.info("Adding junction to schematic")
        try:
            from pathlib import Path

            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            position = params.get("position")

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not position:
                return {"success": False, "message": "Position is required"}

            success = WireManager.add_junction(Path(schematic_path), position)

            if success:
                return {"success": True, "message": "Junction added successfully"}
            else:
                return {"success": False, "message": "Failed to add junction"}
        except Exception as e:
            logger.error(f"Error adding junction to schematic: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_list_schematic_libraries(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List available symbol libraries"""
        logger.info("Listing schematic libraries")
        try:
            search_paths = params.get("searchPaths")

            libraries = SchematicLibraryManager.list_available_libraries(search_paths)
            return {"success": True, "libraries": libraries}
        except Exception as e:
            logger.error(f"Error listing schematic libraries: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_find_unconnected_pins(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List component pins with no wire/label/power symbol touching them"""
        logger.info("Finding unconnected pins")
        try:
            from commands.schematic_analysis import find_unconnected_pins

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            result = find_unconnected_pins(schematic_path)
            return {"success": True, **result}
        except ImportError:
            return {
                "success": False,
                "message": "schematic_analysis module not available",
            }
        except Exception as e:
            logger.error(f"Error finding unconnected pins: {e}")
            return {"success": False, "message": str(e)}

    def _handle_check_wire_collisions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Detect wires passing through component bodies without connecting to pins"""
        logger.info("Checking wire collisions")
        try:
            from commands.schematic_analysis import check_wire_collisions

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            result = check_wire_collisions(schematic_path)
            return {"success": True, **result}
        except ImportError:
            return {
                "success": False,
                "message": "schematic_analysis module not available",
            }
        except Exception as e:
            logger.error(f"Error checking wire collisions: {e}")
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------ #
    #  Footprint handlers                                                  #
    # ------------------------------------------------------------------ #

    def _handle_create_footprint(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new .kicad_mod footprint file in a .pretty library."""
        logger.info(f"create_footprint: {params.get('name')} in {params.get('libraryPath')}")
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

    def _handle_edit_footprint_pad(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _handle_list_footprint_libraries(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List .pretty footprint libraries and their contents."""
        logger.info("list_footprint_libraries")
        try:
            creator = FootprintCreator()
            return creator.list_footprint_libraries(search_paths=params.get("searchPaths"))
        except Exception as e:
            logger.error(f"list_footprint_libraries error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_register_footprint_library(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _handle_create_symbol(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new symbol in a .kicad_sym library."""
        logger.info(f"create_symbol: {params.get('name')} in {params.get('libraryPath')}")
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

    def _handle_delete_symbol(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a symbol from a .kicad_sym library."""
        logger.info(f"delete_symbol: {params.get('name')} from {params.get('libraryPath')}")
        try:
            creator = SymbolCreator()
            return creator.delete_symbol(
                library_path=params.get("libraryPath", ""),
                name=params.get("name", ""),
            )
        except Exception as e:
            logger.error(f"delete_symbol error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_list_symbols_in_library(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _handle_register_symbol_library(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _handle_export_schematic_pdf(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _handle_add_schematic_net_label(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a net label to schematic using WireManager.

        When componentRef and pinNumber are supplied the label is placed at the
        exact pin endpoint retrieved via PinLocator, ignoring the provided
        position.  The response includes the actual coordinates used and
        whether the label landed on a pin endpoint.
        """
        logger.info("Adding net label to schematic")
        try:
            from pathlib import Path

            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")
            position = params.get("position")
            label_type = params.get("labelType", "label")
            orientation = params.get("orientation", 0)
            component_ref = params.get("componentRef")
            pin_number = params.get("pinNumber")

            if not all([schematic_path, net_name]):
                return {
                    "success": False,
                    "message": "Missing required parameters: schematicPath, netName",
                }

            snapped_to_pin: Optional[Dict[str, Any]] = None

            if component_ref and pin_number:
                # Snap position to exact pin endpoint using PinLocator
                from commands.pin_locator import PinLocator

                locator = PinLocator()
                pin_loc = locator.get_pin_location(
                    Path(schematic_path), component_ref, str(pin_number)
                )
                if pin_loc is None:
                    return {
                        "success": False,
                        "message": (
                            f"Could not locate pin {pin_number} on {component_ref}. "
                            "Check the reference and pin number."
                        ),
                    }
                position = pin_loc
                snapped_to_pin = {"component": component_ref, "pin": str(pin_number)}
                logger.info(
                    f"Snapped label '{net_name}' to pin {component_ref}/{pin_number} at {position}"
                )
            elif position is None:
                return {
                    "success": False,
                    "message": (
                        "Missing position. Either provide position [x, y] or "
                        "componentRef + pinNumber to snap to a pin endpoint."
                    ),
                }

            # Collect existing net names BEFORE adding the new label so we can
            # detect case-mismatch collisions against pre-existing nets only.
            existing_net_names: List[str] = []
            try:
                pre_schematic = SchematicManager.load_schematic(schematic_path)
                if pre_schematic is not None:
                    if hasattr(pre_schematic, "label"):
                        for lbl in pre_schematic.label:
                            if hasattr(lbl, "value"):
                                existing_net_names.append(lbl.value)
                    if hasattr(pre_schematic, "global_label"):
                        for lbl in pre_schematic.global_label:
                            if hasattr(lbl, "value"):
                                existing_net_names.append(lbl.value)
            except Exception:
                # Non-fatal: if we can't read existing nets, skip the warning
                existing_net_names = []

            # Use WireManager for S-expression manipulation
            success = WireManager.add_label(
                Path(schematic_path),
                net_name,
                position,
                label_type=label_type,
                orientation=orientation,
            )

            if not success:
                return {"success": False, "message": "Failed to add net label"}

            # Compute case-mismatch warnings against pre-existing net names.
            # A collision is: existing name != new name, but lowercases match.
            new_name_lower = net_name.lower()
            case_warnings: List[str] = [
                f"Net '{existing}' already exists — label '{net_name}' may be a case mismatch."
                for existing in existing_net_names
                if existing.lower() == new_name_lower and existing != net_name
            ]

            response: Dict[str, Any] = {
                "success": True,
                "message": f"Added net label '{net_name}' at {position}",
                "actual_position": position,
            }
            if snapped_to_pin:
                response["snapped_to_pin"] = snapped_to_pin
                response["message"] = (
                    f"Added net label '{net_name}' at exact pin endpoint "
                    f"{component_ref}/{pin_number} ({position[0]}, {position[1]})"
                )
            if case_warnings:
                response["case_warnings"] = case_warnings
            return response

        except Exception as e:
            logger.error(f"Error adding net label: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_connect_to_net(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Connect a component pin to a named net using wire stub and label"""
        logger.info("Connecting component pin to net")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            component_ref = params.get("componentRef")
            pin_name = params.get("pinName")
            net_name = params.get("netName")

            if not all([schematic_path, component_ref, pin_name, net_name]):
                return {"success": False, "message": "Missing required parameters"}

            # Use ConnectionManager with new WireManager integration
            result = ConnectionManager.connect_to_net(
                Path(schematic_path), component_ref, pin_name, net_name
            )
            return result
        except Exception as e:
            logger.error(f"Error connecting to net: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_connect_passthrough(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_schematic_pin_locations(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

            locator = PinLocator()
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
                        locator.get_pin_angle(Path(schematic_path), reference, pin_num) or 0
                    )
                result[pin_num] = entry

            return {"success": True, "reference": reference, "pins": result}

        except Exception as e:
            logger.error(f"Error getting pin locations: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_schematic_view(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a rasterised image of the schematic (SVG export → optional PNG conversion)"""
        logger.info("Getting schematic view")
        import base64
        import subprocess
        import tempfile

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
            logger.error(f"Error getting schematic view: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_components(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

            locator = PinLocator()
            components = []

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

                value = symbol.property.Value.value if hasattr(symbol.property, "Value") else ""
                footprint = (
                    symbol.property.Footprint.value if hasattr(symbol.property, "Footprint") else ""
                )
                position = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                uuid_val = symbol.uuid.value if hasattr(symbol, "uuid") else ""

                comp = {
                    "reference": ref,
                    "libId": lib_id,
                    "value": value,
                    "footprint": footprint,
                    "position": {"x": float(position[0]), "y": float(position[1])},
                    "rotation": float(position[2]) if len(position) > 2 else 0,
                    "uuid": str(uuid_val),
                }

                # Get pins if available
                try:
                    all_pins = locator.get_all_symbol_pins(sch_file, ref)
                    if all_pins:
                        pins_def = locator.get_symbol_pins(sch_file, lib_id) or {}
                        pin_list = []
                        for pin_num, coords in all_pins.items():
                            pin_info = {
                                "number": pin_num,
                                "position": {"x": coords[0], "y": coords[1]},
                            }
                            if pin_num in pins_def:
                                pin_info["name"] = pins_def[pin_num].get("name", pin_num)
                            pin_list.append(pin_info)
                        comp["pins"] = pin_list
                except Exception:
                    pass  # Pin lookup is best-effort

                components.append(comp)

            return {"success": True, "components": components, "count": len(components)}

        except Exception as e:
            logger.error(f"Error listing schematic components: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_nets(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List all nets in a schematic with their connections"""
        logger.info("Listing schematic nets")
        try:
            from commands.wire_connectivity import (
                _build_adjacency,
                _discover_sub_sheets,
                _load_sexp,
                _parse_labels_sexp,
                _parse_virtual_connections,
                _parse_wires,
                count_pins_on_net,
                get_connections_for_net,
            )

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Collect net names from the top-level sheet using sexpdata.
            # Falls back to kicad-skip's label collections when the file
            # cannot be read (e.g. mocked schematics in unit tests).
            net_names: set = set()
            sexp_loaded = False
            try:
                sexp = _load_sexp(schematic_path)
                sexp_loaded = True
                _, label_to_points = _parse_labels_sexp(sexp)
                net_names.update(label_to_points.keys())
            except Exception as e:
                logger.debug(
                    f"Could not parse labels from {schematic_path} via sexp ({e}); "
                    "falling back to kicad-skip label collections"
                )
                for attr in ("label", "global_label"):
                    if not hasattr(schematic, attr):
                        continue
                    for label in getattr(schematic, attr):
                        if hasattr(label, "value"):
                            net_names.add(label.value)

            # Collect net names from all sub-sheets (only when the parent
            # sheet was readable; fake/mock paths skip recursion entirely).
            if sexp_loaded:
                sub_sheets = _discover_sub_sheets(schematic_path)
                for sub_path in sub_sheets:
                    try:
                        sub_sexp = _load_sexp(sub_path)
                        _, sub_label_to_points = _parse_labels_sexp(sub_sexp)
                        net_names.update(sub_label_to_points.keys())
                    except Exception as e:
                        logger.warning(f"Error reading sub-sheet {sub_path}: {e}")

            # Pre-build shared wire graph structures for efficiency
            all_wires = _parse_wires(schematic)
            if all_wires:
                adjacency, iu_to_wires = _build_adjacency(all_wires)
            else:
                adjacency, iu_to_wires = [], {}
            point_to_label, label_to_points = _parse_virtual_connections(schematic, schematic_path)

            nets = []
            for net_name in sorted(net_names):
                connections = get_connections_for_net(schematic, schematic_path, net_name)
                pin_count = count_pins_on_net(
                    schematic,
                    schematic_path,
                    net_name,
                    all_wires,
                    iu_to_wires,
                    adjacency,
                    point_to_label,
                    label_to_points,
                )
                nets.append(
                    {
                        "name": net_name,
                        "connections": connections,
                        "connected_pin_count": pin_count,
                    }
                )

            return {"success": True, "nets": nets, "count": len(nets)}

        except Exception as e:
            logger.error(f"Error listing schematic nets: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_wires(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_labels(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List all net labels and power flags in a schematic"""
        logger.info("Listing schematic labels")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            net_name = params.get("netName")
            label_type = params.get("labelType")

            _valid_label_types = {"net", "global", "power"}
            if label_type is not None and label_type not in _valid_label_types:
                return {"success": False, "message": "labelType must be one of: net, global, power"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            labels = []

            # Regular labels
            if hasattr(schematic, "label"):
                for label in schematic.label:
                    if hasattr(label, "value"):
                        pos = (
                            label.at.value
                            if hasattr(label, "at") and hasattr(label.at, "value")
                            else [0, 0]
                        )
                        labels.append(
                            {
                                "name": label.value,
                                "type": "net",
                                "position": {"x": float(pos[0]), "y": float(pos[1])},
                            }
                        )

            # Global labels
            if hasattr(schematic, "global_label"):
                for label in schematic.global_label:
                    if hasattr(label, "value"):
                        pos = (
                            label.at.value
                            if hasattr(label, "at") and hasattr(label.at, "value")
                            else [0, 0]
                        )
                        labels.append(
                            {
                                "name": label.value,
                                "type": "global",
                                "position": {"x": float(pos[0]), "y": float(pos[1])},
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
                        symbol.property.Value.value if hasattr(symbol.property, "Value") else ref
                    )
                    pos = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                    labels.append(
                        {
                            "name": value,
                            "type": "power",
                            "position": {"x": float(pos[0]), "y": float(pos[1])},
                        }
                    )

            # Apply filters
            if net_name is not None:
                labels = [lbl for lbl in labels if lbl["name"] == net_name]
            if label_type is not None:
                labels = [lbl for lbl in labels if lbl["type"] == label_type]

            return {"success": True, "labels": labels, "count": len(labels)}

        except Exception as e:
            logger.error(f"Error listing schematic labels: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_move_schematic_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Move a schematic component to a new position, dragging connected wires."""
        logger.info("Moving schematic component")
        try:
            import sexpdata as _sexpdata
            from commands.wire_dragger import WireDragger

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            position = params.get("position", {})
            new_x = position.get("x")
            new_y = position.get("y")
            preserve_wires = params.get("preserveWires", True)

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

            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_data = _sexpdata.loads(f.read())

            # Find symbol and record old position
            found = WireDragger.find_symbol(sch_data, reference)
            if found is None:
                return {"success": False, "message": f"Component {reference} not found"}
            _, old_x, old_y = found[0], found[1], found[2]
            old_position = {"x": old_x, "y": old_y}

            drag_summary = {}
            if preserve_wires:
                # Compute pin world positions before and after the move
                pin_positions = WireDragger.compute_pin_positions(
                    sch_data, reference, float(new_x), float(new_y)
                )
                # Build old→new coordinate map (deduplicate coincident pins)
                old_to_new = {}
                for _pin, (old_xy, new_xy) in pin_positions.items():
                    if old_xy in old_to_new:
                        logger.warning(
                            f"move_schematic_component: pin {_pin!r} of {reference!r} "
                            f"shares old position {old_xy} with another pin; "
                            f"keeping first entry, skipping duplicate"
                        )
                        continue
                    old_to_new[old_xy] = new_xy

                drag_summary = WireDragger.drag_wires(sch_data, old_to_new)

                # Synthesize wires for touching-pin connections after dragging,
                # so drag_wires doesn't accidentally move and collapse the new wire.
                wires_synthesized = WireDragger.synthesize_touching_pin_wires(
                    sch_data, reference, pin_positions
                )
                drag_summary["wires_synthesized"] = wires_synthesized

            # Update symbol position
            WireDragger.update_symbol_position(sch_data, reference, float(new_x), float(new_y))

            with open(schematic_path, "w", encoding="utf-8") as f:
                f.write(_sexpdata.dumps(sch_data))

            return {
                "success": True,
                "oldPosition": old_position,
                "newPosition": {"x": new_x, "y": new_y},
                "wiresMoved": drag_summary.get("endpoints_moved", 0),
                "wiresRemoved": drag_summary.get("wires_removed", 0),
                "wiresSynthesized": drag_summary.get("wires_synthesized", 0),
            }

        except Exception as e:
            logger.error(f"Error moving schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_rotate_schematic_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
                    while len(pos) < 3:
                        pos.append(0)
                    pos[2] = angle
                    symbol.at.value = pos

                    if mirror:
                        if hasattr(symbol, "mirror"):
                            symbol.mirror.value = mirror
                        else:
                            logger.warning(
                                f"Mirror '{mirror}' requested for {reference}, "
                                f"but symbol has no mirror attribute; skipped"
                            )

                    SchematicManager.save_schematic(schematic, schematic_path)
                    return {"success": True, "reference": reference, "angle": angle}

            return {"success": False, "message": f"Component {reference} not found"}

        except Exception as e:
            logger.error(f"Error rotating schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_annotate_schematic(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
                symbol.setAllReferences(new_ref)
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
            return {"success": True, "annotated": annotated}

        except Exception as e:
            logger.error(f"Error annotating schematic: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_delete_schematic_wire(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

            deleted = WireManager.delete_wire(Path(schematic_path), start_point, end_point)
            if deleted:
                return {"success": True}
            else:
                return {"success": False, "message": "No matching wire found"}

        except Exception as e:
            logger.error(f"Error deleting schematic wire: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_delete_schematic_net_label(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_move_schematic_net_label(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Move a net label to a new position in the schematic."""
        logger.info("Moving schematic net label")
        try:
            import sexpdata as _sexpdata
            from sexpdata import Symbol

            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")
            new_position = params.get("newPosition", {})
            new_x = new_position.get("x")
            new_y = new_position.get("y")
            current_position = params.get("currentPosition")
            label_type = params.get("labelType")

            if not schematic_path or not net_name:
                return {"success": False, "message": "schematicPath and netName are required"}
            if new_x is None or new_y is None:
                return {"success": False, "message": "newPosition with x and y is required"}

            _valid_types = {"label", "global_label", "hierarchical_label"}
            if label_type is not None and label_type not in _valid_types:
                return {
                    "success": False,
                    "message": f"labelType must be one of: {', '.join(sorted(_valid_types))}",
                }

            _SYM_AT = Symbol("at")
            target_syms = (
                {Symbol(label_type)}
                if label_type is not None
                else {Symbol(t) for t in _valid_types}
            )

            TOLERANCE = 0.5

            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_data = _sexpdata.loads(f.read())

            for item in sch_data:
                if not (isinstance(item, list) and len(item) >= 2 and item[0] in target_syms):
                    continue
                if item[1] != net_name:
                    continue

                at_idx = next(
                    (
                        j
                        for j, p in enumerate(item)
                        if isinstance(p, list) and len(p) >= 3 and p[0] == _SYM_AT
                    ),
                    None,
                )
                if at_idx is None:
                    continue

                at_entry = item[at_idx]
                old_x, old_y = float(at_entry[1]), float(at_entry[2])

                if current_position is not None:
                    cx = current_position.get("x", 0)
                    cy = current_position.get("y", 0)
                    if not (abs(old_x - cx) < TOLERANCE and abs(old_y - cy) < TOLERANCE):
                        continue

                rotation = at_entry[3] if len(at_entry) > 3 else 0
                item[at_idx] = [_SYM_AT, float(new_x), float(new_y), rotation]

                with open(schematic_path, "w", encoding="utf-8") as f:
                    f.write(_sexpdata.dumps(sch_data))

                return {
                    "success": True,
                    "oldPosition": {"x": old_x, "y": old_y},
                    "newPosition": {"x": float(new_x), "y": float(new_y)},
                }

            return {"success": False, "message": f"Label '{net_name}' not found"}

        except Exception as e:
            logger.error(f"Error moving schematic net label: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_export_schematic_svg(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export schematic to SVG using kicad-cli"""
        logger.info("Exporting schematic SVG")
        import glob
        import shutil
        import subprocess

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

    def _handle_get_net_connections(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get all connections for a named net"""
        logger.info("Getting net connections")
        try:
            from commands.wire_connectivity import get_connections_for_net

            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")

            if not all([schematic_path, net_name]):
                return {"success": False, "message": "Missing required parameters"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            connections = get_connections_for_net(schematic, schematic_path, net_name)
            return {"success": True, "connections": connections}
        except Exception as e:
            logger.error(f"Error getting net connections: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_get_wire_connections(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Find net name and all component pins reachable from a point or component pin."""
        logger.info("Getting wire connections")
        try:
            from pathlib import Path

            from commands.pin_locator import PinLocator
            from commands.wire_connectivity import get_wire_connections

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "Missing required parameter: schematicPath"}

            reference = params.get("reference")
            pin = params.get("pin")
            x = params.get("x")
            y = params.get("y")

            has_ref_pin = reference is not None and pin is not None
            has_coords = x is not None and y is not None

            if has_ref_pin and has_coords:
                return {
                    "success": False,
                    "message": "Supply either {reference, pin} or {x, y}, not both",
                }

            if not has_ref_pin and not has_coords:
                if reference is not None or pin is not None:
                    return {
                        "success": False,
                        "message": "Both reference and pin are required together",
                    }
                return {
                    "success": False,
                    "message": "Must supply either {reference, pin} or {x, y}",
                }

            if has_ref_pin:
                location = PinLocator().get_pin_location(Path(schematic_path), reference, str(pin))
                if location is None:
                    return {
                        "success": False,
                        "message": f"Pin {pin} not found on {reference}",
                    }
                x, y = location[0], location[1]
            else:
                try:
                    x, y = float(x), float(y)
                except (TypeError, ValueError):
                    return {"success": False, "message": "Parameters x and y must be numeric"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            if not hasattr(schematic, "wire"):
                return {"success": False, "message": "Schematic has no wires"}

            result = get_wire_connections(schematic, schematic_path, x, y)
            if result is None:
                return {
                    "success": False,
                    "message": f"No wire found at ({x},{y}) — point may not be connected",
                }

            return {"success": True, **result}

        except Exception as e:
            logger.error(f"Error getting wire connections: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_net_at_point(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return the net name at a given (x, y) coordinate, or null if none found."""
        logger.info("Getting net at point")
        try:
            from commands.wire_connectivity import get_net_at_point

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "Missing required parameter: schematicPath"}

            x = params.get("x")
            y = params.get("y")
            if x is None or y is None:
                return {"success": False, "message": "Missing required parameters: x and y"}

            try:
                x, y = float(x), float(y)
            except (TypeError, ValueError):
                return {"success": False, "message": "Parameters x and y must be numeric"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            result = get_net_at_point(schematic, schematic_path, x, y)
            return {"success": True, **result}

        except Exception as e:
            logger.error(f"Error getting net at point: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_texts(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List all free-form text annotations (SCH_TEXT) in a schematic."""
        logger.info("Listing schematic text annotations")
        try:
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            texts = WireManager.list_texts(sch_file)
            if texts is None:
                return {"success": False, "message": "Failed to parse schematic"}

            # Optional text filter
            filter_text = params.get("text")
            if filter_text is not None:
                texts = [t for t in texts if filter_text.lower() in t["text"].lower()]

            return {"success": True, "texts": texts, "count": len(texts)}

        except Exception as e:
            logger.error(f"Error listing schematic texts: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_add_schematic_text(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a free-form text annotation (SCH_TEXT) to a schematic."""
        logger.info("Adding text annotation to schematic")
        try:
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            text = params.get("text")
            position = params.get("position")
            angle = params.get("angle", 0)
            font_size = params.get("fontSize", 1.27)
            bold = params.get("bold", False)
            italic = params.get("italic", False)
            justify = params.get("justify", "left")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not text:
                return {"success": False, "message": "text is required"}
            if not position or len(position) != 2:
                return {"success": False, "message": "position [x, y] is required"}
            if justify not in ("left", "center", "right"):
                return {"success": False, "message": "justify must be left, center, or right"}
            if font_size <= 0:
                return {"success": False, "message": "fontSize must be positive"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            success = WireManager.add_text(
                sch_file,
                text,
                position,
                angle=angle,
                font_size=font_size,
                bold=bold,
                italic=italic,
                justify=justify,
            )

            if success:
                return {
                    "success": True,
                    "message": f"Added text '{text}' at ({position[0]}, {position[1]})",
                    "position": {"x": position[0], "y": position[1]},
                    "angle": angle,
                }
            return {"success": False, "message": "Failed to add text annotation"}

        except Exception as e:
            logger.error(f"Error adding schematic text: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_add_schematic_hierarchical_label(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a hierarchical label to a sub-sheet schematic."""
        logger.info("Adding hierarchical label to schematic")
        try:
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            text = params.get("text")
            position = params.get("position")
            shape = params.get("shape", "bidirectional")
            orientation = params.get("orientation", 0)

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not text:
                return {"success": False, "message": "text is required"}
            if not position or len(position) != 2:
                return {"success": False, "message": "position [x, y] is required"}
            if shape not in ("input", "output", "bidirectional"):
                return {
                    "success": False,
                    "message": "shape must be input, output, or bidirectional",
                }

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            success = WireManager.add_hierarchical_label(
                sch_file, text, position, shape=shape, orientation=orientation
            )

            if success:
                return {
                    "success": True,
                    "message": (
                        f"Added hierarchical_label '{text}' " f"at {position} shape={shape}"
                    ),
                }
            return {"success": False, "message": "Failed to add hierarchical label"}

        except Exception as e:
            logger.error(f"Error adding hierarchical label: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_add_sheet_pin(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a sheet pin to a sheet block on the parent schematic."""
        logger.info("Adding sheet pin to schematic")
        try:
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            sheet_name = params.get("sheetName")
            pin_name = params.get("pinName")
            pin_type = params.get("pinType", "bidirectional")
            position = params.get("position")
            orientation = params.get("orientation", 0)

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not sheet_name:
                return {"success": False, "message": "sheetName is required"}
            if not pin_name:
                return {"success": False, "message": "pinName is required"}
            if not position or len(position) != 2:
                return {"success": False, "message": "position [x, y] is required"}
            if pin_type not in ("input", "output", "bidirectional"):
                return {
                    "success": False,
                    "message": "pinType must be input, output, or bidirectional",
                }

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            modified, success = WireManager.add_sheet_pin(
                content,
                sheet_name,
                pin_name,
                pin_type,
                position,
                orientation=orientation,
            )

            if not success:
                return {
                    "success": False,
                    "message": f"Sheet '{sheet_name}' not found in {schematic_path}",
                }

            with open(sch_file, "w", encoding="utf-8") as f:
                f.write(modified)

            return {
                "success": True,
                "message": (
                    f"Added sheet pin '{pin_name}' ({pin_type}) " f"to sheet '{sheet_name}'"
                ),
            }

        except Exception as e:
            logger.error(f"Error adding sheet pin: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_run_erc(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run Electrical Rules Check on a schematic via kicad-cli"""
        logger.info("Running ERC on schematic")
        import os
        import subprocess
        import tempfile

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

            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
                json_output = tmp.name

            try:
                cmd = [
                    kicad_cli,
                    "sch",
                    "erc",
                    "--format",
                    "json",
                    "--output",
                    json_output,
                    schematic_path,
                ]
                logger.info(f"Running ERC command: {' '.join(cmd)}")

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

                # kicad-cli returns non-zero when ERC violations are found —
                # this is normal, not an error.  Only fail when no JSON was
                # produced (genuine CLI failure).
                if not os.path.exists(json_output) or os.path.getsize(json_output) == 0:
                    logger.error(f"ERC command produced no output: {result.stderr}")
                    return {
                        "success": False,
                        "message": "ERC command failed - no output produced",
                        "errorDetails": result.stderr,
                    }

                with open(json_output, "r", encoding="utf-8") as f:
                    erc_data = json.load(f)

                violations = []
                severity_counts = {"error": 0, "warning": 0, "info": 0}

                # KiCad 9 nests violations under sheets[].violations
                # instead of (or in addition to) the top-level violations
                # array used by KiCad 8.
                all_violations = erc_data.get("violations", [])
                for sheet in erc_data.get("sheets", []):
                    all_violations.extend(sheet.get("violations", []))

                for v in all_violations:
                    vseverity = v.get("severity", "error")
                    items = v.get("items", [])
                    loc = {}
                    if items and "pos" in items[0]:
                        loc = {
                            "x": items[0]["pos"].get("x", 0),
                            "y": items[0]["pos"].get("y", 0),
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

    # ------------------------------------------------------------------
    # kicad-cli helper shared by netlist handlers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_kicad_cli_static() -> Optional[str]:
        """Return path to kicad-cli executable, or None."""
        import platform
        import shutil

        cli = shutil.which("kicad-cli")
        if cli:
            return cli

        system = platform.system()
        if system == "Windows":
            candidates = [
                r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
                r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe",
                r"C:\Program Files (x86)\KiCad\9.0\bin\kicad-cli.exe",
                r"C:\Program Files (x86)\KiCad\8.0\bin\kicad-cli.exe",
            ]
        elif system == "Darwin":
            candidates = [
                "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
                "/usr/local/bin/kicad-cli",
            ]
        else:
            candidates = [
                "/usr/bin/kicad-cli",
                "/usr/local/bin/kicad-cli",
            ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    # ------------------------------------------------------------------

    def _handle_export_netlist(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export netlist to a file using kicad-cli."""
        import subprocess

        logger.info("Exporting netlist via kicad-cli")
        try:
            schematic_path = params.get("schematicPath")
            output_path = params.get("outputPath")
            fmt = params.get("format", "KiCad")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not output_path:
                return {"success": False, "message": "outputPath is required"}
            if not os.path.exists(schematic_path):
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            fmt_map = {
                "KiCad": "kicadxml",
                "Spice": "spice",
                "Cadstar": "cadstar",
                "OrcadPCB2": "orcadpcb2",
            }
            cli_format = fmt_map.get(fmt, "kicadxml")

            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

            cmd = [
                kicad_cli,
                "sch",
                "export",
                "netlist",
                "--format",
                cli_format,
                "--output",
                output_path,
                schematic_path,
            ]
            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode == 0:
                return {"success": True, "outputPath": output_path, "format": fmt}
            else:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): {result.stderr.strip()}",
                }

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 60 seconds"}
        except Exception as e:
            logger.error(f"Error exporting netlist: {e}")
            return {"success": False, "message": str(e)}

    def _handle_generate_netlist(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate netlist from schematic and return structured JSON.

        Uses kicad-cli to export KiCad XML netlist to a temp file, then
        parses it into {components, nets} structure expected by the TS handler.
        """
        import subprocess
        import tempfile
        import xml.etree.ElementTree as ET

        logger.info("Generating netlist from schematic via kicad-cli")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not os.path.exists(schematic_path):
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                cmd = [
                    kicad_cli,
                    "sch",
                    "export",
                    "netlist",
                    "--format",
                    "kicadxml",
                    "--output",
                    tmp_path,
                    schematic_path,
                ]
                logger.info(f"Running: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

                if result.returncode != 0:
                    return {
                        "success": False,
                        "message": f"kicad-cli failed (exit {result.returncode}): {result.stderr.strip()}",
                    }

                tree = ET.parse(tmp_path)
                root = tree.getroot()

                components = []
                for comp in root.findall("./components/comp"):
                    ref = comp.get("ref", "")
                    value = comp.findtext("value", "")
                    footprint = comp.findtext("footprint", "")
                    components.append({"reference": ref, "value": value, "footprint": footprint})

                nets = []
                for net in root.findall("./nets/net"):
                    net_name = net.get("name", "")
                    connections = []
                    for node in net.findall("node"):
                        connections.append(
                            {
                                "component": node.get("ref", ""),
                                "pin": node.get("pin", ""),
                            }
                        )
                    nets.append({"name": net_name, "connections": connections})

                logger.info(f"Generated netlist: {len(components)} components, {len(nets)} nets")
                return {"success": True, "netlist": {"components": components, "nets": nets}}

            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 60 seconds"}
        except Exception as e:
            logger.error(f"Error generating netlist: {e}")
            return {"success": False, "message": str(e)}

    def _build_hierarchical_pad_net_map(self, project_sch_path: str):
        """Walk all .kicad_sch files in the project and build a {(ref, pin_num): net_name} map.

        Handles hierarchical schematics by scanning every sub-sheet file.  Net names
        from global_label / hierarchical_label / local label / power symbols are all
        collected.  Wire connectivity is traced via BFS so labels not placed directly
        on a pin endpoint still reach through wire segments.

        Returns: (pad_net_map, net_names_set)
        """
        from collections import defaultdict
        from pathlib import Path

        from commands.pin_locator import PinLocator
        from skip import Schematic

        TOLERANCE = 0.5  # mm; schematic grid is 1.27 mm so 0.5 is safe

        def snap(x, y):
            """Round to 2 dp to use exact dict lookup instead of O(n²) scan."""
            return (round(float(x), 2), round(float(y), 2))

        def nearby_net(pt, point_net, tol=TOLERANCE):
            """Return net name for the nearest occupied grid point, or None."""
            x, y = pt
            # Try exact snap first (fast path)
            key = snap(x, y)
            if key in point_net:
                return point_net[key]
            # Slow fallback for off-grid placements
            for (lx, ly), name in point_net.items():
                if abs(x - lx) < tol and abs(y - ly) < tol:
                    return name
            return None

        project_dir = Path(project_sch_path).parent
        pad_net_map: dict = {}
        all_net_names: set = set()
        pin_locator = PinLocator()

        sch_files = sorted(project_dir.rglob("*.kicad_sch"))
        logger.info(f"_build_hierarchical_pad_net_map: scanning {len(sch_files)} schematic files")

        for sch_path in sch_files:
            try:
                sch = Schematic(str(sch_path))
            except Exception as e:
                logger.warning(f"Could not load {sch_path}: {e}")
                continue

            # ── 1. Collect explicit label positions → net name ──────────────
            point_net: dict = {}  # snap(x,y) -> net_name

            for attr in ("label", "global_label", "hierarchical_label"):
                for lbl in getattr(sch, attr, None) or []:
                    try:
                        pos = lbl.at.value
                        name = lbl.value
                        if name:
                            k = snap(pos[0], pos[1])
                            point_net[k] = name
                            all_net_names.add(name)
                    except Exception:
                        pass

            # Power symbols (#PWR / #FLG): value property IS the net name; use pin 1 pos
            for sym in getattr(sch, "symbol", None) or []:
                try:
                    ref = sym.property.Reference.value
                    if not (ref.startswith("#PWR") or ref.startswith("#FLG")):
                        continue
                    net_name = sym.property.Value.value
                    if not net_name:
                        continue
                    all_pins = pin_locator.get_all_symbol_pins(sch_path, ref)
                    for _pin_num, (px, py) in all_pins.items():
                        k = snap(px, py)
                        point_net[k] = net_name
                        all_net_names.add(net_name)
                except Exception:
                    pass

            # ── 2. Build wire adjacency and BFS-propagate net names ──────────
            wire_segments = []
            for wire in getattr(sch, "wire", None) or []:
                try:
                    pts = []
                    for pt in wire.pts.xy:
                        pts.append(snap(pt.value[0], pt.value[1]))
                    if len(pts) >= 2:
                        wire_segments.append(pts)
                except Exception:
                    pass

            # Adjacency: connect endpoints of different segments that share a grid point
            point_adj: dict = defaultdict(set)
            for seg in wire_segments:
                # Connect consecutive points within the segment
                for i in range(len(seg) - 1):
                    point_adj[seg[i]].add(seg[i + 1])
                    point_adj[seg[i + 1]].add(seg[i])

            # All unique wire points
            all_wire_pts = set()
            for seg in wire_segments:
                all_wire_pts.update(seg)

            # BFS: propagate known net names through wire connections
            queue = [pt for pt in all_wire_pts if pt in point_net]
            visited = set(queue)
            while queue:
                pt = queue.pop()
                net = point_net[pt]
                for neighbor in point_adj[pt]:
                    if neighbor not in point_net:
                        point_net[neighbor] = net
                        all_net_names.add(net)
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)

            # ── 3. Match component pin positions to net names ────────────────
            for sym in getattr(sch, "symbol", None) or []:
                try:
                    ref = sym.property.Reference.value
                    if ref.startswith("#"):
                        continue
                except Exception:
                    continue

                pin_positions = pin_locator.get_all_symbol_pins(sch_path, ref)
                for pin_num, (px, py) in pin_positions.items():
                    net = nearby_net((px, py), point_net)
                    if net:
                        pad_net_map[(ref, pin_num)] = net

        logger.info(
            f"_build_hierarchical_pad_net_map: {len(pad_net_map)} pin→net assignments, "
            f"{len(all_net_names)} unique nets"
        )
        return pad_net_map, all_net_names

    def _handle_sync_schematic_to_board(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

            # Build hierarchical pad→net map (walks all sub-sheets)
            pad_net_map, net_names = self._build_hierarchical_pad_net_map(schematic_path)

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
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    # ===================================================================
    # Schematic analysis tools (read-only)
    # ===================================================================

    def _handle_get_schematic_view_region(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export a cropped region of the schematic as an image"""
        logger.info("Exporting schematic view region")
        import base64
        import os
        import subprocess
        import tempfile

        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path or not os.path.exists(schematic_path):
                return {"success": False, "message": "Schematic file not found"}

            x1 = float(params.get("x1", 0))
            y1 = float(params.get("y1", 0))
            x2 = float(params.get("x2", 297))
            y2 = float(params.get("y2", 210))
            x1, x2 = min(x1, x2), max(x1, x2)
            y1, y2 = min(y1, y2), max(y1, y2)
            out_format = params.get("format", "png")
            width = int(params.get("width", 800))
            height = int(params.get("height", 600))

            kicad_cli = self.design_rule_commands._find_kicad_cli()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found"}

            tmp_dir = tempfile.mkdtemp()
            svg_output = None

            try:
                cmd = [
                    kicad_cli,
                    "sch",
                    "export",
                    "svg",
                    "--output",
                    tmp_dir,
                    schematic_path,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

                if result.returncode != 0:
                    return {
                        "success": False,
                        "message": f"SVG export failed: {result.stderr}",
                    }

                # kicad-cli names the file after the schematic
                svg_files = [f for f in os.listdir(tmp_dir) if f.endswith(".svg")]
                if not svg_files:
                    return {
                        "success": False,
                        "message": "kicad-cli produced no SVG output",
                    }
                svg_output = os.path.join(tmp_dir, svg_files[0])

                import xml.etree.ElementTree as ET

                tree = ET.parse(svg_output)
                root = tree.getroot()

                # KiCad schematic SVGs use mm as viewBox units directly
                vb = root.get("viewBox", "")
                if vb:
                    parts = vb.split()
                    if len(parts) == 4:
                        orig_vb_x = float(parts[0])
                        orig_vb_y = float(parts[1])

                        new_x = orig_vb_x + x1
                        new_y = orig_vb_y + y1
                        new_w = x2 - x1
                        new_h = y2 - y1

                        root.set("viewBox", f"{new_x} {new_y} {new_w} {new_h}")
                        root.set("width", str(width))
                        root.set("height", str(height))

                # Write modified SVG
                cropped_svg_path = os.path.join(tmp_dir, "cropped.svg")
                tree.write(cropped_svg_path, xml_declaration=True, encoding="utf-8")

                if out_format == "svg":
                    with open(cropped_svg_path, "r", encoding="utf-8") as f:
                        svg_data = f.read()
                    return {"success": True, "imageData": svg_data, "format": "svg"}
                else:
                    try:
                        from cairosvg import svg2png
                    except ImportError:
                        return {
                            "success": False,
                            "message": "PNG export requires the 'cairosvg' package. Install it with: pip install cairosvg",
                        }
                    png_data = svg2png(
                        url=cropped_svg_path, output_width=width, output_height=height
                    )
                    return {
                        "success": True,
                        "imageData": base64.b64encode(png_data).decode("utf-8"),
                        "format": "png",
                    }
            finally:
                import shutil

                shutil.rmtree(tmp_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"Error in get_schematic_view_region: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_find_overlapping_elements(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Detect spatially overlapping symbols, wires, and labels"""
        logger.info("Finding overlapping elements in schematic")
        try:
            from pathlib import Path

            from commands.schematic_analysis import find_overlapping_elements

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            tolerance = float(params.get("tolerance", 0.5))
            result = find_overlapping_elements(Path(schematic_path), tolerance)
            return {
                "success": True,
                **result,
                "message": f"Found {result['totalOverlaps']} overlap(s)",
            }
        except Exception as e:
            logger.error(f"Error finding overlapping elements: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_elements_in_region(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List all wires, labels, and symbols within a rectangular region"""
        logger.info("Getting elements in schematic region")
        try:
            from pathlib import Path

            from commands.schematic_analysis import get_elements_in_region

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            x1 = float(params.get("x1", 0))
            y1 = float(params.get("y1", 0))
            x2 = float(params.get("x2", 0))
            y2 = float(params.get("y2", 0))

            result = get_elements_in_region(Path(schematic_path), x1, y1, x2, y2)
            return {
                "success": True,
                **result,
                "message": f"Found {result['counts']['symbols']} symbols, {result['counts']['wires']} wires, {result['counts']['labels']} labels in region",
            }
        except Exception as e:
            logger.error(f"Error getting elements in region: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_find_wires_crossing_symbols(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Find wires that cross over component symbol bodies"""
        logger.info("Finding wires crossing symbols in schematic")
        try:
            from pathlib import Path

            from commands.schematic_analysis import find_wires_crossing_symbols

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            result = find_wires_crossing_symbols(Path(schematic_path))
            return {
                "success": True,
                "collisions": result,
                "count": len(result),
                "message": f"Found {len(result)} wire(s) crossing symbols",
            }
        except Exception as e:
            logger.error(f"Error checking wire collisions: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_find_orphaned_wires(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Find wire segments with at least one dangling (unconnected) endpoint"""
        logger.info("Finding orphaned wires in schematic")
        try:
            from pathlib import Path

            from commands.schematic_analysis import find_orphaned_wires

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            result = find_orphaned_wires(Path(schematic_path))
            return {
                "success": True,
                **result,
                "message": f"Found {result['count']} orphaned wire(s)",
            }
        except Exception as e:
            logger.error(f"Error finding orphaned wires: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_floating_labels(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List net labels that are not connected to any component pin"""
        logger.info("Listing floating net labels in schematic")
        try:
            from commands.wire_connectivity import list_floating_labels

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            labels = list_floating_labels(schematic, schematic_path)
            return {
                "success": True,
                "floating_labels": labels,
                "count": len(labels),
                "message": f"Found {len(labels)} floating label(s)",
            }
        except Exception as e:
            logger.error(f"Error listing floating labels: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_snap_to_grid(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Snap schematic element coordinates to the nearest grid point"""
        logger.info("Snapping schematic elements to grid")
        try:
            from pathlib import Path

            from commands.schematic_snap import snap_to_grid

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            grid_size = float(params.get("gridSize", 1.27))
            elements = params.get("elements")  # None → defaults inside snap_to_grid

            result = snap_to_grid(Path(schematic_path), grid_size=grid_size, elements=elements)
            total = result["snapped"] + result["already_on_grid"]
            return {
                "success": True,
                **result,
                "message": (
                    f"Snapped {result['snapped']} element(s) to {grid_size} mm grid "
                    f"({result['already_on_grid']} of {total} were already on grid)"
                ),
            }
        except Exception as e:
            logger.error(f"Error snapping to grid: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_import_svg_logo(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

            result = import_svg_to_pcb(pcb_path, svg_path, x, y, width, layer, stroke_width, filled)

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
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_snapshot_project(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
                prompt_filename = f"PROMPT_step{step}_{ts}.md" if step else f"PROMPT_{ts}.md"
                prompt_file = logs_dir / prompt_filename
                prompt_file.write_text(prompt_text, encoding="utf-8")
                logger.info(f"Prompt saved: {prompt_file}")

            # Copy current MCP session log into logs/ before snapshotting
            import platform

            system = platform.system()
            if system == "Windows":
                mcp_log_dir = os.path.join(os.environ.get("APPDATA", ""), "Claude", "logs")
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
                log_filename = f"mcp_log_step{step}_{ts}.txt" if step else f"mcp_log_{ts}.txt"
                mcp_log_dest = logs_dir / log_filename
                with open(mcp_log_dest, "w", encoding="utf-8") as f:
                    f.writelines(session_lines)
                logger.info(f"MCP session log saved: {mcp_log_dest} ({len(session_lines)} lines)")

            base_name = Path(project_dir).name
            suffix_parts = [p for p in [f"step{step}" if step else "", label, ts] if p]
            snapshot_name = base_name + "_snapshot_" + "_".join(suffix_parts)
            snapshots_base = Path(project_dir) / "snapshots"
            snapshots_base.mkdir(exist_ok=True)
            snapshot_dir = str(snapshots_base / snapshot_name)

            shutil.copytree(project_dir, snapshot_dir, ignore=shutil.ignore_patterns("snapshots"))
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

    def _handle_check_kicad_ui(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _handle_launch_kicad_ui(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _handle_refill_zones(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

            zone_count = self.board.GetAreaCount() if hasattr(self.board, "GetAreaCount") else 0

            # Run pcbnew zone fill in an isolated subprocess to prevent crashes
            import subprocess
            import sys
            import textwrap

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
                        "details": (result.stderr[:300] if result.stderr else result.stdout[:300]),
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
    # IPC Backend handlers - these provide real-time UI synchronization
    # These methods are called automatically when IPC is available
    # =========================================================================

    def _ipc_route_trace(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """IPC handler for route_trace - adds track with real-time UI update"""
        try:
            # Extract parameters matching the existing route_trace interface
            start = params.get("start", {})
            end = params.get("end", {})
            layer = params.get("layer", "F.Cu")
            width = params.get("width", 0.25)
            net = params.get("net")

            # Handle both dict format and direct x/y
            start_x = start.get("x", 0) if isinstance(start, dict) else params.get("startX", 0)
            start_y = start.get("y", 0) if isinstance(start, dict) else params.get("startY", 0)
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
                    "Added trace (visible in KiCAD UI)" if success else "Failed to add trace"
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

    def _ipc_add_via(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """IPC handler for add_via - adds via with real-time UI update"""
        try:
            position = params.get("position", {})
            x = position.get("x", 0) if isinstance(position, dict) else params.get("x", 0)
            y = position.get("y", 0) if isinstance(position, dict) else params.get("y", 0)

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
                "message": ("Added via (visible in KiCAD UI)" if success else "Failed to add via"),
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

    def _ipc_add_net(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _ipc_add_copper_pour(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
                formatted_points.append({"x": point.get("x", 0), "y": point.get("y", 0)})

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

    def _ipc_refill_zones(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """IPC handler for refill_zones - refills all zones with real-time UI update"""
        try:
            success = self.ipc_board_api.refill_zones()

            return {
                "success": success,
                "message": (
                    "Zones refilled (visible in KiCAD UI)" if success else "Failed to refill zones"
                ),
            }
        except Exception as e:
            logger.error(f"IPC refill_zones error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_add_text(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """IPC handler for add_text/add_board_text - adds text with real-time UI update"""
        try:
            text = params.get("text", "")
            position = params.get("position", {})
            x = position.get("x", 0) if isinstance(position, dict) else params.get("x", 0)
            y = position.get("y", 0) if isinstance(position, dict) else params.get("y", 0)
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

    def _ipc_set_board_size(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _ipc_get_board_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _ipc_place_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """IPC handler for place_component - places component with real-time UI update"""
        try:
            reference = params.get("reference", params.get("componentId", ""))
            footprint = params.get("footprint", "")
            position = params.get("position", {})
            x = position.get("x", 0) if isinstance(position, dict) else params.get("x", 0)
            y = position.get("y", 0) if isinstance(position, dict) else params.get("y", 0)
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

    def _ipc_move_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """IPC handler for move_component - moves component with real-time UI update"""
        try:
            reference = params.get("reference", params.get("componentId", ""))
            position = params.get("position", {})
            x = position.get("x", 0) if isinstance(position, dict) else params.get("x", 0)
            y = position.get("y", 0) if isinstance(position, dict) else params.get("y", 0)
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

    def _ipc_delete_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _ipc_get_component_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """IPC handler for get_component_list"""
        try:
            components = self.ipc_board_api.list_components()

            return {"success": True, "components": components, "count": len(components)}
        except Exception as e:
            logger.error(f"IPC get_component_list error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_save_project(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _ipc_delete_trace(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """IPC handler for delete_trace - Note: IPC doesn't support direct trace deletion yet"""
        # IPC API doesn't have a direct delete track method
        # Fall back to SWIG for this operation
        logger.info("delete_trace: Falling back to SWIG (IPC doesn't support trace deletion)")
        return self.routing_commands.delete_trace(params)

    def _ipc_get_nets_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """IPC handler for get_nets_list - gets nets with real-time data"""
        try:
            nets = self.ipc_board_api.get_nets()

            return {"success": True, "nets": nets, "count": len(nets)}
        except Exception as e:
            logger.error(f"IPC get_nets_list error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_add_board_outline(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
            from kipy.proto.board.board_types_pb2 import BoardLayer
            from kipy.util.units import from_mm

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
                segment.end = Vector2.from_xy(from_mm(end.get("x", 0)), from_mm(end.get("y", 0)))
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

    def _ipc_add_mounting_hole(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """IPC handler for add_mounting_hole - adds mounting hole with real-time UI update"""
        try:
            from kipy.board_types import BoardCircle
            from kipy.geometry import Vector2
            from kipy.proto.board.board_types_pb2 import BoardLayer
            from kipy.util.units import from_mm

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

    def _ipc_get_layer_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """IPC handler for get_layer_list - gets enabled layers"""
        try:
            layers = self.ipc_board_api.get_enabled_layers()

            return {"success": True, "layers": layers, "count": len(layers)}
        except Exception as e:
            logger.error(f"IPC get_layer_list error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_rotate_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _ipc_get_component_properties(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _handle_get_backend_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get information about the current backend"""
        return {
            "success": True,
            "backend": "ipc" if self.use_ipc else "swig",
            "realtime_sync": self.use_ipc,
            "ipc_connected": (self.ipc_backend.is_connected() if self.ipc_backend else False),
            "version": self.ipc_backend.get_version() if self.ipc_backend else "N/A",
            "message": (
                "Using IPC backend with real-time UI sync"
                if self.use_ipc
                else "Using SWIG backend (requires manual reload)"
            ),
        }

    def _handle_ipc_add_track(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
                    "Track added (visible in KiCAD UI)" if success else "Failed to add track"
                ),
                "realtime": True,
            }
        except Exception as e:
            logger.error(f"Error adding track via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_add_via(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
                "message": ("Via added (visible in KiCAD UI)" if success else "Failed to add via"),
                "realtime": True,
            }
        except Exception as e:
            logger.error(f"Error adding via via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_add_text(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
                    "Text added (visible in KiCAD UI)" if success else "Failed to add text"
                ),
                "realtime": True,
            }
        except Exception as e:
            logger.error(f"Error adding text via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_list_components(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List components using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            components = self.ipc_board_api.list_components()
            return {"success": True, "components": components, "count": len(components)}
        except Exception as e:
            logger.error(f"Error listing components via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_get_tracks(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get tracks using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            tracks = self.ipc_board_api.get_tracks()
            return {"success": True, "tracks": tracks, "count": len(tracks)}
        except Exception as e:
            logger.error(f"Error getting tracks via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_get_vias(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get vias using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            vias = self.ipc_board_api.get_vias()
            return {"success": True, "vias": vias, "count": len(vias)}
        except Exception as e:
            logger.error(f"Error getting vias via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_save_board(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _handle_download_jlcpcb_database(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _handle_search_jlcpcb_parts(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _handle_get_jlcpcb_part(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get detailed information for a specific JLCPCB part"""
        try:
            lcsc_number = params.get("lcsc_number")
            if not lcsc_number:
                return {"success": False, "message": "Missing lcsc_number parameter"}

            part = self.jlcpcb_parts.get_part_info(lcsc_number)
            if not part:
                return {"success": False, "message": f"Part not found: {lcsc_number}"}

            # Get suggested KiCAD footprints
            footprints = self.jlcpcb_parts.map_package_to_footprint(part.get("package", ""))

            return {"success": True, "part": part, "footprints": footprints}

        except Exception as e:
            logger.error(f"Error getting JLCPCB part: {e}", exc_info=True)
            return {"success": False, "message": f"Failed to get part info: {str(e)}"}

    def _handle_get_jlcpcb_database_stats(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get statistics about JLCPCB database"""
        try:
            stats = self.jlcpcb_parts.get_database_stats()
            return {"success": True, "stats": stats}

        except Exception as e:
            logger.error(f"Error getting database stats: {e}", exc_info=True)
            return {"success": False, "message": f"Failed to get stats: {str(e)}"}

    def _handle_suggest_jlcpcb_alternatives(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
                    reference_price = float(original_part["price_breaks"][0].get("price", 0))
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

    def _handle_enrich_datasheets(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    def _handle_get_datasheet_url(self, params: Dict[str, Any]) -> Dict[str, Any]:
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


def _write_response(response_fd: Any, response: Any) -> None:
    """Write a JSON response to the original stdout fd.

    All response output goes through this function so that stray C-level
    writes from pcbnew (warnings, diagnostics) never corrupt the JSON
    framing seen by the TypeScript host.
    """
    payload = json.dumps(response) + "\n"
    os.write(response_fd, payload.encode("utf-8"))


def main() -> None:
    """Main entry point"""
    # --- Redirect stdout so pcbnew C++ noise never reaches the TS host ---
    # Save the real stdout fd for our exclusive JSON response channel.
    _response_fd = os.dup(1)
    # Point fd 1 (C-level stdout) at stderr so that any printf / std::cout
    # output from pcbnew or other C extensions is visible in logs but does
    # NOT corrupt the JSON stream the TypeScript side is parsing.
    os.dup2(2, 1)
    # Also redirect Python-level stdout to stderr for the same reason.
    sys.stdout = sys.stderr

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
                            if cmd_name in TOOL_SCHEMAS:
                                # Enrich the existing schema with IPC annotation data
                                # (adds description/blocking hints where the schema lacks them)
                                tool_def = _annotation_loader.enrich_schema(
                                    cmd_name, TOOL_SCHEMAS[cmd_name]
                                )
                                tools.append(tool_def)
                            else:
                                # Build a best-effort schema from IPC annotations
                                ann_desc = _annotation_loader.description(cmd_name)
                                if ann_desc:
                                    logger.debug(f"Using IPC annotation for tool: {cmd_name}")
                                else:
                                    logger.warning(f"No schema or annotation for tool: {cmd_name}")
                                tools.append(
                                    _annotation_loader.enrich_schema(
                                        cmd_name,
                                        {
                                            "name": cmd_name,
                                            "description": ann_desc or f"KiCAD command: {cmd_name}",
                                            "inputSchema": {
                                                "type": "object",
                                                "properties": {},
                                            },
                                        },
                                    )
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
                            "result": {"content": [{"type": "text", "text": json.dumps(result)}]},
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
                            resource_data = handle_resource_read(resource_uri, interface)

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

                # Send response via the clean fd (immune to pcbnew stdout noise)
                logger.debug(f"Sending response: {response}")
                _write_response(_response_fd, response)

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON input: {str(e)}")
                response = {
                    "success": False,
                    "message": "Invalid JSON input",
                    "errorDetails": str(e),
                }
                _write_response(_response_fd, response)

    except KeyboardInterrupt:
        logger.info("KiCAD interface stopped")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}\n{traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
