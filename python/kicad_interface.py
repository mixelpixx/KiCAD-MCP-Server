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
    handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stderr)],
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
            "place_component": self.component_commands.place_component,
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
            # Schematic commands
            "create_schematic": self._handle_create_schematic,
            "load_schematic": self._handle_load_schematic,
            "add_schematic_component": self._handle_add_schematic_component,
            "add_schematic_wire": self._handle_add_schematic_wire,
            "add_schematic_connection": self._handle_add_schematic_connection,
            "add_schematic_net_label": self._handle_add_schematic_net_label,
            "connect_to_net": self._handle_connect_to_net,
            "get_net_connections": self._handle_get_net_connections,
            "generate_netlist": self._handle_generate_netlist,
            "list_schematic_libraries": self._handle_list_schematic_libraries,
            "export_schematic_pdf": self._handle_export_schematic_pdf,
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

    def _update_command_handlers(self):
        """Update board reference in all command handlers"""
        logger.debug("Updating board reference in command handlers")
        self.project_commands.board = self.board
        self.board_commands.board = self.board
        self.component_commands.board = self.board
        self.routing_commands.board = self.board
        self.design_rule_commands.board = self.board
        self.export_commands.board = self.board

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
            x = component.get("x", 0)
            y = component.get("y", 0)

            loader = DynamicSymbolLoader()
            loader.add_component(
                Path(schematic_path),
                library,
                comp_type,
                reference=reference,
                value=value,
                x=x,
                y=y,
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

    def _handle_add_schematic_wire(self, params):
        """Add a wire to a schematic using WireManager"""
        logger.info("Adding wire to schematic")
        try:
            from pathlib import Path
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            start_point = params.get("startPoint")
            end_point = params.get("endPoint")
            properties = params.get("properties", {})

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not start_point or not end_point:
                return {
                    "success": False,
                    "message": "Start and end points are required",
                }

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
            import traceback

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

            import subprocess

            result = subprocess.run(
                [
                    "kicad-cli",
                    "sch",
                    "export",
                    "pdf",
                    "--output",
                    output_path,
                    schematic_path,
                ],
                capture_output=True,
                text=True,
            )

            success = result.returncode == 0
            message = result.stderr if not success else ""

            return {"success": success, "message": message}
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
                details = (
                    ConnectionManager.get_last_error()
                    if hasattr(ConnectionManager, "get_last_error")
                    else ""
                )
                return {
                    "success": False,
                    "message": "Failed to add connection",
                    "errorDetails": details,
                }
        except Exception as e:
            logger.error(f"Error adding schematic connection: {str(e)}")
            import traceback

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

            if not all([schematic_path, net_name, position]):
                return {"success": False, "message": "Missing required parameters"}

            # Use WireManager for S-expression manipulation
            success = WireManager.add_label(
                Path(schematic_path),
                net_name,
                position,
                label_type=label_type,
                orientation=orientation,
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
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_connect_to_net(self, params):
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
            success = ConnectionManager.connect_to_net(
                Path(schematic_path), component_ref, pin_name, net_name
            )

            if success:
                return {
                    "success": True,
                    "message": f"Connected {component_ref}/{pin_name} to net '{net_name}'",
                }
            else:
                details = (
                    ConnectionManager.get_last_error()
                    if hasattr(ConnectionManager, "get_last_error")
                    else ""
                )
                return {
                    "success": False,
                    "message": "Failed to connect to net",
                    "errorDetails": details,
                }
        except Exception as e:
            logger.error(f"Error connecting to net: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_get_net_connections(self, params):
        """Get all connections for a named net"""
        logger.info("Getting net connections")
        try:
            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")

            if not all([schematic_path, net_name]):
                return {"success": False, "message": "Missing required parameters"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            connections = ConnectionManager.get_net_connections(schematic, net_name)
            return {"success": True, "connections": connections}
        except Exception as e:
            logger.error(f"Error getting net connections: {str(e)}")
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

            netlist = ConnectionManager.generate_netlist(schematic)
            return {"success": True, "netlist": netlist}
        except Exception as e:
            logger.error(f"Error generating netlist: {str(e)}")
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
        """Refill all copper pour zones on the board"""
        logger.info("Refilling zones")
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # Use pcbnew's zone filler for SWIG backend
            filler = pcbnew.ZONE_FILLER(self.board)
            zones = self.board.Zones()
            filler.Fill(zones)

            return {
                "success": True,
                "message": "Zones refilled successfully",
                "zoneCount": zones.size()
                if hasattr(zones, "size")
                else len(list(zones)),
            }
        except Exception as e:
            logger.error(f"Error refilling zones: {str(e)}")
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
                "message": "Added trace (visible in KiCAD UI)"
                if success
                else "Failed to add trace",
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
                "message": "Added via (visible in KiCAD UI)"
                if success
                else "Failed to add via",
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
                "message": "Added copper pour (visible in KiCAD UI)"
                if success
                else "Failed to add copper pour",
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
                "message": "Zones refilled (visible in KiCAD UI)"
                if success
                else "Failed to refill zones",
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
                "message": f"Added text '{text}' (visible in KiCAD UI)"
                if success
                else "Failed to add text",
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
                "message": f"Board size set to {width}x{height} {unit} (visible in KiCAD UI)"
                if success
                else "Failed to set board size",
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
                "message": f"Placed component {reference} (visible in KiCAD UI)"
                if success
                else "Failed to place component",
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
                "message": f"Moved component {reference} (visible in KiCAD UI)"
                if success
                else "Failed to move component",
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
                "message": f"Deleted component {reference} (visible in KiCAD UI)"
                if success
                else "Failed to delete component",
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
        """IPC handler for add_board_outline - adds board edge with real-time UI update"""
        try:
            from kipy.board_types import BoardSegment
            from kipy.geometry import Vector2
            from kipy.util.units import from_mm
            from kipy.proto.board.board_types_pb2 import BoardLayer

            board = self.ipc_board_api._get_board()

            points = params.get("points", [])
            width = params.get("width", 0.1)

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
                "message": f"Rotated component {reference} by {angle}° (visible in KiCAD UI)"
                if success
                else "Failed to rotate component",
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
            "ipc_connected": self.ipc_backend.is_connected()
            if self.ipc_backend
            else False,
            "version": self.ipc_backend.get_version() if self.ipc_backend else "N/A",
            "message": "Using IPC backend with real-time UI sync"
            if self.use_ipc
            else "Using SWIG backend (requires manual reload)",
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
                "message": "Track added (visible in KiCAD UI)"
                if success
                else "Failed to add track",
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
                "message": "Via added (visible in KiCAD UI)"
                if success
                else "Failed to add via",
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
                "message": "Text added (visible in KiCAD UI)"
                if success
                else "Failed to add text",
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
        """Download JLCPCB parts database from official API or JLCSearch fallback"""
        try:
            force = params.get("force", False)
            source = params.get("source", "auto")

            # Check if database exists
            import os

            stats = self.jlcpcb_parts.get_database_stats()
            if stats["total_parts"] > 0 and not force:
                return {
                    "success": False,
                    "message": "Database already exists. Use force=true to re-download.",
                    "stats": stats,
                }

            has_official_creds = all(
                [
                    os.getenv("JLCPCB_APP_ID"),
                    os.getenv("JLCPCB_API_KEY"),
                    os.getenv("JLCPCB_API_SECRET"),
                ]
            )

            selected_source = source
            if source == "auto":
                selected_source = "official" if has_official_creds else "jlcsearch"

            if selected_source == "official" and not has_official_creds:
                return {
                    "success": False,
                    "message": (
                        "Official JLCPCB source requested but credentials are incomplete. "
                        "Set JLCPCB_APP_ID, JLCPCB_API_KEY, and JLCPCB_API_SECRET."
                    ),
                }

            warning = None
            if selected_source == "official":
                logger.info(
                    "Downloading JLCPCB parts database from official JLCPCB API..."
                )
                parts = self.jlcpcb_client.download_full_database(
                    callback=lambda page, total, msg: logger.info(
                        f"[page {page}] {msg}"
                    )
                )
                logger.info(
                    f"Importing {len(parts)} official API parts into database..."
                )
                self.jlcpcb_parts.import_parts(
                    parts, progress_callback=lambda curr, total, msg: logger.info(msg)
                )
            else:
                logger.info(
                    "Downloading JLCPCB parts database from JLCSearch fallback source..."
                )
                parts = self.jlcsearch_client.download_all_components(
                    callback=lambda total, msg: logger.info(msg)
                )
                logger.info(f"Importing {len(parts)} JLCSearch parts into database...")
                self.jlcpcb_parts.import_jlcsearch_parts(
                    parts, progress_callback=lambda curr, total, msg: logger.info(msg)
                )
                warning = (
                    "Using JLCSearch fallback source. Result size depends on public endpoint limits. "
                    "For full catalog download, configure official JLCPCB credentials."
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
                "source": selected_source,
                "warning": warning,
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
