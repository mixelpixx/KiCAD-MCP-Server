#!/usr/bin/env python3
"""
KiCAD Python Interface Script for Model Context Protocol

This script handles communication between the MCP TypeScript server
and KiCAD's Python API (pcbnew). It receives commands via stdin as
JSON and returns responses via stdout also as JSON.
"""

import hashlib
import json
import logging
import os
import shutil
import sys
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Fix cairo DLL loading on Windows before any cairocffi import.
# cairocffi uses cffi's ffi.dlopen('cairo-2') which needs the DLL on PATH.
if sys.platform == "win32":
    for _bin_dir in [
        os.environ.get("PYTHONPATH", ""),
        os.path.dirname(sys.executable),
        r"C:\Program Files\KiCad\9.0\bin",
        r"C:\Program Files\KiCad\8.0\bin",
    ]:
        if _bin_dir and os.path.isfile(os.path.join(_bin_dir, "cairo-2.dll")):
            _current_path = os.environ.get("PATH", "")
            if _bin_dir not in _current_path:
                os.environ["PATH"] = _bin_dir + os.pathsep + _current_path
            break

import sexpdata
from annotations import AnnotationLoader
from commands.wire_manager import WireManager
from commands.schematic_handlers import SchematicHandlersMixin
from resources.resource_definitions import RESOURCE_DEFINITIONS, handle_resource_read

# Import tool schemas, resource definitions, and IPC API annotations
from schemas.tool_schemas import TOOL_SCHEMAS

_annotation_loader = AnnotationLoader()


def _parse_log_level() -> int:
    """Return the configured Python log level from the MCP environment.

    Honors KICAD_MCP_LOG_LEVEL (preferred) or LOG_LEVEL; defaults to INFO.
    Accepts common aliases (WARN, FATAL) and an OFF/NONE/0 kill switch.
    """
    raw_level = os.environ.get("KICAD_MCP_LOG_LEVEL") or os.environ.get("LOG_LEVEL") or "INFO"
    normalized = raw_level.strip().upper()
    aliases = {
        "WARN": "WARNING",
        "FATAL": "CRITICAL",
        "OFF": "OFF",
        "NONE": "OFF",
        "FALSE": "OFF",
        "0": "OFF",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized == "OFF":
        return logging.CRITICAL + 1
    return {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
    }.get(normalized, logging.INFO)


def _parse_positive_int_env(name: str, default: int) -> int:
    """Return a non-negative int from env var ``name``, or ``default``."""
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value >= 0 else default


def _env_flag_enabled(name: str) -> bool:
    """Return True when env var ``name`` is a truthy flag (1/true/yes/on)."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


_LOG_LEVEL = _parse_log_level()

# Configure logging.
# The file handler rotates (default 10 MB x 3 backups) so the log can never
# grow without bound (issue #181); the level honors the environment instead of
# being hardcoded to DEBUG. If ~/.kicad-mcp/logs isn't writable (sandboxed test
# envs, restricted CI runners) we fall back to console-only logging so importing
# this module never crashes.
try:
    log_dir = os.path.join(os.path.expanduser("~"), ".kicad-mcp", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "kicad_interface.log")
    max_log_bytes = _parse_positive_int_env("KICAD_MCP_LOG_MAX_BYTES", 10 * 1024 * 1024)
    backup_count = _parse_positive_int_env("KICAD_MCP_LOG_BACKUP_COUNT", 3)
    if max_log_bytes:
        log_handler: logging.Handler = RotatingFileHandler(
            log_file,
            maxBytes=max_log_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
    else:
        log_handler = logging.FileHandler(log_file, encoding="utf-8")
    logging.basicConfig(
        level=_LOG_LEVEL,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[log_handler],
        force=True,
    )
except (OSError, PermissionError):
    logging.basicConfig(
        level=_LOG_LEVEL,
        format="%(asctime)s [%(levelname)s] %(message)s",
        force=True,
    )
logger = logging.getLogger("kicad_interface")

# kicad-skip's S-expression parser emits per-node DEBUG logs that can fill disks
# during hierarchy traversal (issue #181). Keep those quiet unless explicitly
# enabled via KICAD_MCP_DEBUG_SKIP.
_SKIP_LOG_LEVEL = logging.DEBUG if _env_flag_enabled("KICAD_MCP_DEBUG_SKIP") else logging.WARNING
for _skip_logger_name in ("skip", "skip.sexp", "skip.sexp.parser", "skip.sexp.sourcefile"):
    logging.getLogger(_skip_logger_name).setLevel(_SKIP_LOG_LEVEL)

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
        # Deferred — GetBuildVersion() triggers 55-65 s wxApp init on macOS.
        # The _warmup handler pays this cost during startup (not on first tool call).
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
    from commands.schematic_batch import SchematicBatchCommands
    from commands.schematic_field_layout import SchematicFieldLayoutCommands
    from commands.schematic_hierarchy import SchematicHierarchyCommands
    from commands.symbol_creator import SymbolCreator
    from commands.symbol_pins import SymbolPinCommands

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


class KiCADInterface(SchematicHandlersMixin):
    """Main interface class to handle KiCAD operations"""

    def __init__(self) -> None:
        """Initialize the interface and command handlers"""
        self.board = None
        self.project_filename = None
        # On-disk signature (mtime_ns, sha256_hex) of self.board's file as of
        # last load or successful auto-save.  Used by _auto_save_board() to
        # detect external modifications and refuse to clobber them.
        self._board_disk_signature: Optional[Tuple[int, str]] = None
        self._last_auto_save_status: Optional[Dict[str, Any]] = None
        # Number of timestamped backups to keep in .mcp-backups/ per board file.
        self._auto_save_backup_keep = 20
        self.use_ipc = USE_IPC_BACKEND
        self.ipc_backend = ipc_backend
        self.ipc_board_api = None
        # Session backend pin (issue #223): once a project is loaded, every
        # board command runs on the backend that owns that load ("swig" or
        # "ipc") until the project is closed or reopened. None = no project
        # loaded yet; commands then follow connectivity-based routing.
        self.session_backend: Optional[str] = None
        self.session_board_path: Optional[str] = None

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

        # Symbol pin discovery commands (read-only pin lookup from symbol libraries)
        self.symbol_pin_commands = SymbolPinCommands()
        # Schematic hierarchy commands (insert sheets, scaffold sub-sheets)
        self.hierarchy_commands = SchematicHierarchyCommands(self)
        # Schematic field placement / layout-check commands
        self.field_layout_commands = SchematicFieldLayoutCommands()
        # Batch schematic authoring commands (need an interface back-reference for the
        # single-item add/edit/get handlers, footprint library, and sub-sheet fixer)
        self.batch_commands = SchematicBatchCommands(self)

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
            "create_project": self._handle_create_project,
            "open_project": self._handle_open_project,
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
            "check_courtyard_overlaps": self.component_commands.check_courtyard_overlaps,
            "duplicate_component": self.component_commands.duplicate_component,
            "set_footprint_type": self.component_commands.set_footprint_type,
            # Routing commands
            "add_net": self.routing_commands.add_net,
            "route_trace": self.routing_commands.route_trace,
            "route_arc_trace": self.routing_commands.route_arc_trace,
            "add_via": self.routing_commands.add_via,
            "delete_trace": self.routing_commands.delete_trace,
            "query_traces": self.routing_commands.query_traces,
            "query_zones": self.routing_commands.query_zones,
            "add_gnd_stitching_vias": self.routing_commands.add_gnd_stitching_vias,
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
            # Symbol pin discovery commands (read pins straight from symbol libraries)
            "list_symbol_pins": self.symbol_pin_commands.list_symbol_pins,
            "batch_list_symbol_pins": self.symbol_pin_commands.batch_list_symbol_pins,
            # Schematic hierarchy commands (sheet insertion + subsheet scaffolding)
            "add_hierarchical_sheet": self.hierarchy_commands.add_hierarchical_sheet,
            "create_hierarchical_subsheet": self.hierarchy_commands.create_hierarchical_subsheet,
            # Schematic field placement commands
            "set_schematic_property_position": self.field_layout_commands.set_schematic_property_position,
            "batch_set_schematic_property_positions": self.field_layout_commands.batch_set_schematic_property_positions,
            "autoplace_schematic_fields": self.field_layout_commands.autoplace_schematic_fields,
            # Batch schematic authoring commands
            "batch_add_components": self.batch_commands.batch_add_components,
            "batch_edit_schematic_components": self.batch_commands.batch_edit_schematic_components,
            "replace_schematic_component": self.batch_commands.replace_schematic_component,
            "batch_add_no_connects": self.batch_commands.batch_add_no_connects,
            "batch_connect": self.batch_commands.batch_connect,
            "batch_add_and_connect": self.batch_commands.batch_add_and_connect,
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
            "add_no_connect": self._handle_add_no_connect,
            "connect_to_net": self._handle_connect_to_net,
            "connect_passthrough": self._handle_connect_passthrough,
            "get_schematic_pin_locations": self._handle_get_schematic_pin_locations,
            "get_net_connections": self._handle_get_net_connections,
            "get_wire_connections": self._handle_get_wire_connections,
            "get_net_at_point": self._handle_get_net_at_point,
            "run_erc": self._handle_run_erc,
            "export_netlist": self._handle_export_netlist,
            "export_gerbers": self._handle_export_gerbers,
            "export_drill": self._handle_export_drill,
            "export_ipc2581": self._handle_export_ipc2581,
            "export_odb": self._handle_export_odb,
            "export_ipcd356": self._handle_export_ipcd356,
            "export_gencad": self._handle_export_gencad,
            "export_pos": self._handle_export_pos,
            "export_pcb_pdf": self._handle_export_pcb_pdf,
            "export_pcb_svg": self._handle_export_pcb_svg,
            "export_pcb_dxf": self._handle_export_pcb_dxf,
            "export_gerber_single": self._handle_export_gerber_single,
            "export_3d_cli": self._handle_export_3d_cli,
            "export_sch_bom": self._handle_export_sch_bom,
            "export_sch_pdf": self._handle_export_sch_pdf,
            "export_sch_svg": self._handle_export_sch_svg,
            "export_sch_dxf": self._handle_export_sch_dxf,
            "export_sch_hpgl": self._handle_export_sch_hpgl,
            "export_sch_ps": self._handle_export_sch_ps,
            "export_sch_python_bom": self._handle_export_sch_python_bom,
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
            "get_backend_state": self._handle_get_backend_state,
            "check_kicad_ui": self._handle_check_kicad_ui,
            "launch_kicad_ui": self._handle_launch_kicad_ui,
            # Internal warm-up (pays wxApp init cost during startup)
            "_warmup": self._handle_warmup,
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
            "add_footprint_3d_model": self._handle_add_footprint_3d_model,
            "add_component_3d_model": self._handle_add_component_3d_model,
            "import_3d_model": self._handle_import_3d_model,
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
        "route_arc_trace": "_ipc_route_arc_trace",
        "add_via": "_ipc_add_via",
        "add_net": "_ipc_add_net",
        "delete_trace": "_ipc_delete_trace",
        "query_traces": "_ipc_query_traces",
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
        "set_footprint_type": "_ipc_set_footprint_type",
        "add_component_3d_model": "_ipc_add_component_3d_model",
        # Save command
        "save_project": "_ipc_save_project",
    }

    # Commands that are implemented by the explicit IPC command handlers in
    # command_routes, rather than by the generic IPC_CAPABLE_COMMANDS fast path.
    IPC_DIRECT_COMMANDS = {
        "ipc_add_track",
        "ipc_add_via",
        "ipc_add_text",
        "ipc_list_components",
        "ipc_get_tracks",
        "ipc_get_vias",
        "ipc_save_board",
    }

    @staticmethod
    def _normalize_board_path(path: Any) -> Optional[str]:
        """Normalize a board file path for cross-backend comparison."""
        if not path:
            return None
        return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))

    def _ipc_board_path_matches(self, path: Any) -> bool:
        """True when the live KiCad GUI has the same .kicad_pcb open as `path`."""
        target = self._normalize_board_path(path)
        if not target:
            return False
        backend = getattr(self, "ipc_backend", None)
        if not backend:
            return False
        try:
            open_path = backend.get_open_board_path()
        except Exception as e:
            logger.debug(f"Could not compare IPC board path: {e}")
            return False
        return self._normalize_board_path(open_path) == target

    def _pin_session_backend(self, board_path: Any) -> None:
        """Pin the loaded project's lifecycle to one backend (issue #223).

        Called after a successful create_project/open_project. Pins "ipc" only
        when the live GUI provably has the SAME board open; otherwise "swig".
        Once pinned to "swig", the session never silently upgrades to IPC —
        the GUI's in-memory board may be stale relative to our edits, so an
        IPC save could clobber them (the exact lost-edits bug in #223).
        """
        self.session_board_path = self._normalize_board_path(board_path)
        # Give IPC a chance even if the startup probe ran before the GUI did.
        self._try_enable_ipc_backend()
        backend = getattr(self, "ipc_backend", None)
        if (
            self.use_ipc
            and backend
            and backend.is_connected()
            and self._ipc_board_path_matches(self.session_board_path)
        ):
            self.session_backend = "ipc"
            self._refresh_ipc_board_api()
        else:
            self.session_backend = "swig"
        logger.info(
            "Session backend pinned to %s for %s", self.session_backend, self.session_board_path
        )

    def _session_allows_ipc(self) -> bool:
        """Whether the session pin permits routing board commands over IPC."""
        return getattr(self, "session_backend", None) != "swig"

    def _ipc_session_alive(self) -> bool:
        backend = getattr(self, "ipc_backend", None)
        return bool(backend and backend.is_connected())

    def _downgrade_session_to_swig(self) -> None:
        """Fall back to SWIG when an IPC-pinned session loses its connection.

        Reloads the board from disk so SWIG operates on the last-saved state
        rather than a stale pre-IPC copy.
        """
        logger.warning(
            "IPC connection lost for the pinned session; falling back to SWIG " "for %s",
            self.session_board_path,
        )
        path = self.session_board_path
        if path and os.path.exists(path):
            recovered = self._safe_load_board(path)
            if recovered is not None:
                self.board = recovered
                project_commands = getattr(self, "project_commands", None)
                if project_commands is not None:
                    project_commands.board = recovered
                self._update_command_handlers()
                self._record_board_signature()
            else:
                logger.error(
                    "Downgrade to SWIG could not reload the board from %s — "
                    "subsequent SWIG commands operate on the pre-IPC in-memory "
                    "state, which may be stale",
                    path,
                )
        elif path:
            logger.warning("Downgrade to SWIG: board file is no longer accessible at %s", path)
        self.session_backend = "swig"
        self.ipc_board_api = None

    def _refresh_ipc_board_api(self) -> bool:
        """Refresh the IPC board API after KiCAD or a board becomes available."""
        ipc_backend = getattr(self, "ipc_backend", None)
        if not ipc_backend or not ipc_backend.is_connected():
            self.ipc_board_api = None
            return False

        try:
            self.ipc_board_api = ipc_backend.get_board()
            return True
        except Exception as e:
            logger.warning(f"Connected to KiCAD IPC, but no board API is available yet: {e}")
            self.ipc_board_api = None
            return False

    def _try_enable_ipc_backend(self, force: bool = False) -> bool:
        """Try to switch an already-running interface to IPC when KiCAD is available."""
        if KICAD_BACKEND == "swig":
            return False

        ipc_backend = getattr(self, "ipc_backend", None)
        if self.use_ipc and ipc_backend and ipc_backend.is_connected():
            self._refresh_ipc_board_api()
            return True

        if not force and not KiCADProcessManager.is_running():
            return False

        try:
            from kicad_api.ipc_backend import IPCBackend

            backend = ipc_backend or IPCBackend()
            if not backend.is_connected():
                backend.connect()

            self.ipc_backend = backend
            self.use_ipc = True
            self._refresh_ipc_board_api()
            logger.info("Switched to IPC backend after KiCAD became available")
            return True
        except Exception as e:
            logger.info(f"Runtime IPC connection not available: {e}")
            return False

    def _backend_status(self) -> Dict[str, Any]:
        """Return backend status fields for command responses.

        When a project is loaded, the session pin is the truth about which
        backend serves board commands — reporting connectivity alone misled
        users in #223 (get_backend_state said "ipc" while every project
        command actually ran on SWIG).
        """
        ipc_backend = getattr(self, "ipc_backend", None)
        ipc_connected = ipc_backend.is_connected() if ipc_backend else False
        session = getattr(self, "session_backend", None)
        backend = session or ("ipc" if self.use_ipc and ipc_connected else "swig")
        return {
            "backend": backend,
            "realtime_sync": backend == "ipc" and ipc_connected,
            "ipc_connected": ipc_connected,
        }

    @staticmethod
    def _normalize_ipc_layer_name(layer: Any) -> str:
        """Convert KiCad IPC layer enum strings to common layer names."""
        layer_name = str(layer)
        if layer_name.startswith("BL_"):
            return layer_name[3:].replace("_", ".")
        return layer_name

    def _result_backend_for_command(self, command: str, result: Dict[str, Any]) -> str:
        """Return the backend label for a command result."""
        if command in {
            "get_backend_info",
            "get_backend_state",
            "check_kicad_ui",
            "launch_kicad_ui",
        }:
            return result.get("backend", "ipc" if self.use_ipc else "swig")

        if command in self.IPC_DIRECT_COMMANDS:
            return "ipc" if self.use_ipc else "unavailable"

        return "swig"

    def handle_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route command to appropriate handler, preferring IPC when available"""
        logger.info(f"Handling command: {command}")
        logger.debug(f"Command parameters: {params}")

        try:
            if command in self.IPC_CAPABLE_COMMANDS and self._session_allows_ipc():
                self._try_enable_ipc_backend()
                # An IPC-pinned session whose connection died (GUI closed)
                # falls back to SWIG on the last-saved on-disk state.
                if (
                    getattr(self, "session_backend", None) == "ipc"
                    and not self._ipc_session_alive()
                ):
                    self._downgrade_session_to_swig()

            # Check if we can use IPC for this command (real-time UI sync).
            # A session pinned to SWIG never routes board commands over IPC,
            # even when IPC is connected — the GUI may hold a stale copy of
            # the board and an IPC save would clobber our edits (#223).
            if (
                self.use_ipc
                and self.ipc_board_api
                and command in self.IPC_CAPABLE_COMMANDS
                and self._session_allows_ipc()
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
            if self.use_ipc and command in self.IPC_CAPABLE_COMMANDS and self._session_allows_ipc():
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
                    backend = self._result_backend_for_command(command, result)
                    result["_backend"] = backend
                    result["_realtime"] = bool(
                        backend == "ipc" and result.get("realtime", self.use_ipc)
                    )
                    # Explain why an IPC-capable command ran on SWIG while IPC
                    # was connected: the session is pinned (#223).
                    if (
                        command in self.IPC_CAPABLE_COMMANDS
                        and getattr(self, "session_backend", None) == "swig"
                        and self.use_ipc
                        and self._ipc_session_alive()
                    ):
                        result["_backend_note"] = (
                            "session pinned to swig: the project was loaded via SWIG "
                            "and the live KiCad GUI does not hold this board, so IPC "
                            "is not used to avoid divergent board state (issue #223). "
                            "Reopen the project while it is open in the GUI to pin IPC."
                        )

                # Update board reference if command was successful
                if result.get("success", False):
                    if command == "create_project" or command == "open_project":
                        logger.info("Updating board reference...")
                        # Get board from the project commands handler
                        self.board = self.project_commands.board

                        # Detect SWIG dehydration before claiming success.
                        # Without this, every later board op sees a raw
                        # SwigPyObject and raises AttributeError, while the
                        # MCP keeps reporting "Opened project" — the exact
                        # symptom users hit on KiCAD nightlies.
                        if not self._is_board_healthy():
                            board_path = (result.get("project") or {}).get("boardPath")
                            recovered = None
                            if board_path:
                                logger.warning(
                                    "Board after %s is SWIG-dehydrated; attempting recovery",
                                    command,
                                )
                                recovered = self._safe_load_board(board_path)
                            if recovered is not None:
                                self.board = recovered
                                self.project_commands.board = recovered
                                result.setdefault("warnings", []).append(
                                    "SWIG board proxy was dehydrated on load; "
                                    "recovered via pcbnew module reload"
                                )
                            else:
                                # The load failed for good — drop any pin left
                                # over from a previously loaded project so a
                                # stale "ipc" pin can't route later commands
                                # to the old board's IPC context (#223).
                                self.session_backend = None
                                self.session_board_path = None
                                # Surface the truth — never claim success when
                                # the board is unusable.
                                return {
                                    "success": False,
                                    "message": (
                                        f"{command} loaded the board but the SWIG "
                                        "proxy is dehydrated and recovery failed"
                                    ),
                                    "errorDetails": (
                                        "pcbnew.LoadBoard returned a BOARD whose "
                                        "method dispatch is missing (raw SwigPyObject). "
                                        "This indicates SWIG state corruption in the "
                                        "current Python process — restart the MCP "
                                        "server to recover."
                                    ),
                                    "_backend": "swig",
                                    "_realtime": False,
                                }
                        self._update_command_handlers()
                        # Record the file's signature so subsequent auto-saves
                        # can detect external modifications and refuse to
                        # overwrite them.
                        self._record_board_signature()
                        self._last_auto_save_status = None
                        # Pin the session to one backend for this project's
                        # lifetime (#223). Reports the pin on the result so
                        # callers can see which backend owns the session.
                        self._pin_session_backend(self._current_board_path())
                        result["_backend"] = self.session_backend
                        result["_realtime"] = self.session_backend == "ipc"
                        result["sessionBackend"] = self.session_backend
                    elif command == "save_project":
                        self._record_board_signature()
                        self._last_auto_save_status = None
                    elif command in self._BOARD_MUTATING_COMMANDS:
                        # Auto-save after every board mutation via SWIG.
                        # Prevents data loss if Claude hits context limit before
                        # an explicit save_project call.  When auto-save refuses
                        # because the on-disk file changed externally, surface
                        # a warning to the caller so they don't believe their
                        # mutation was persisted.
                        save_status = self._auto_save_board()
                        self._last_auto_save_status = save_status
                        if isinstance(result, dict) and not save_status.get("saved"):
                            if save_status.get("warning"):
                                result.setdefault("warnings", []).append(save_status["warning"])
                            result["autoSave"] = save_status

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
        "route_arc_trace",
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
        "connect_to_net",
        "set_footprint_type",
    }

    @staticmethod
    def _disk_signature(path: str) -> Optional[Tuple[int, str]]:
        """Return (mtime_ns, sha256_hex) for the file, or None if missing/unreadable.

        The sha256 is always recomputed from disk: the conflict guard in
        ``_auto_save_board`` compares hashes (content), not mtime, so we
        cannot use mtime as a cache key without re-introducing the bug
        where two writes inside one mtime tick on a coarse-resolution
        filesystem (FAT32, network mounts, etc.) would mask a real
        content change.
        """
        try:
            st = os.stat(path)
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return (st.st_mtime_ns, h.hexdigest())
        except OSError:
            return None

    def _record_board_signature(self) -> None:
        """Record the current on-disk signature of self.board's file.

        Call this after a fresh load (open_project / create_project) or after
        any save we perform ourselves, so that _auto_save_board() can detect
        when an external actor has modified the file in between.
        """
        if not self.board:
            self._board_disk_signature = None
            return
        try:
            path = self.board.GetFileName()
        except Exception:
            path = None
        self._board_disk_signature = self._disk_signature(path) if path else None

    def _current_board_path(self) -> Optional[str]:
        """Return the current board file path, if a healthy board is loaded."""
        board = getattr(self, "board", None)
        if not board or not self._is_board_healthy(board):
            return None
        try:
            path = board.GetFileName()
        except Exception:
            return None
        return os.path.abspath(path) if path else None

    def _current_project_file_path(self, board_path: Optional[str]) -> Optional[str]:
        """Best-effort project file path for the currently loaded board."""
        candidates = []
        project_path = getattr(self, "_current_project_path", None)

        if project_path:
            project_path = Path(project_path)
            if project_path.suffix == ".kicad_pro":
                candidates.append(project_path)
            elif board_path:
                candidates.append(project_path / (Path(board_path).stem + ".kicad_pro"))
            elif project_path.is_dir():
                candidates.extend(project_path.glob("*.kicad_pro"))

        if board_path and board_path.endswith(".kicad_pcb"):
            candidates.append(Path(board_path).with_suffix(".kicad_pro"))

        for candidate in candidates:
            if candidate.exists():
                return str(candidate.resolve())

        return str(Path(candidates[0]).resolve()) if candidates else None

    def _dirty_state(self, board_path: Optional[str]) -> Dict[str, Any]:
        """Return the best-known dirty state for the loaded board.

        dirty is intentionally tri-state: True/False when the MCP has evidence,
        None when no reliable disk signature exists.
        """
        if not board_path:
            return {
                "dirty": False,
                "dirtyReason": "No board is loaded",
                "diskChangedExternally": False,
            }

        last_auto_save = getattr(self, "_last_auto_save_status", None) or {}
        if last_auto_save.get("memChangesUnsaved"):
            return {
                "dirty": True,
                "dirtyReason": "Auto-save refused after a board mutation; memory changes are not saved",
                "diskChangedExternally": bool(last_auto_save.get("diskChangedExternally")),
            }

        expected = getattr(self, "_board_disk_signature", None)
        current = self._disk_signature(board_path)

        if expected is None:
            return {
                "dirty": None,
                "dirtyReason": "No recorded disk signature for the loaded board",
                "diskChangedExternally": False,
            }

        if current is None:
            return {
                "dirty": None,
                "dirtyReason": "Board file is missing or unreadable on disk",
                "diskChangedExternally": False,
            }

        if expected[1] != current[1]:
            return {
                "dirty": True,
                "dirtyReason": "Board file contents changed on disk since this MCP session loaded it",
                "diskChangedExternally": True,
            }

        return {
            "dirty": False,
            "dirtyReason": "Board file matches the MCP recorded disk signature",
            "diskChangedExternally": False,
        }

    def _prune_auto_save_backups(self, backup_dir: str, base_name: str) -> None:
        """Keep only the most recent `_auto_save_backup_keep` backups for `base_name`."""
        try:
            entries = [
                os.path.join(backup_dir, f)
                for f in os.listdir(backup_dir)
                if f.startswith(base_name + ".")
            ]
            entries.sort(key=os.path.getmtime, reverse=True)
            for old in entries[self._auto_save_backup_keep :]:
                try:
                    os.remove(old)
                except OSError:
                    pass
        except OSError as e:
            logger.debug(f"Backup pruning skipped: {e}")

    def _auto_save_board(self) -> Dict[str, Any]:
        """Save the in-memory board to disk after a SWIG-path mutation.

        Behaviour:
          * If the file's on-disk signature has diverged from the one we
            recorded at load (or at our last successful save), refuse to
            overwrite — an external actor (KiCad GUI, another process, git)
            has touched the file and saving would clobber their changes.
          * Otherwise, copy the existing file to ``<dir>/.mcp-backups/<name>.<ts>``
            (rotating, keeps the most recent `_auto_save_backup_keep`),
            then call pcbnew.SaveBoard().
          * Update the recorded signature on success.
          * If SaveBoard leaves the in-memory BOARD dehydrated (observed on
            KiCAD nightlies after delete_trace + auto-save), reload from disk
            so the next command sees a usable proxy instead of a SwigPyObject.

        Returns a status dict that handle_command merges into the caller's
        response so warnings about refused saves are visible:
          {"saved": True,  "boardPath": ..., "backup": <path-or-None>}
          {"saved": False, "skipped": <reason>}                      -- nothing to save
          {"saved": False, "warning": ..., "diskChangedExternally": True, ...}
          {"saved": False, "error": ...}                             -- pcbnew error
        """
        if not self.board:
            return {"saved": False, "skipped": "no board loaded"}

        try:
            board_path = self.board.GetFileName()
        except Exception as e:
            return {"saved": False, "skipped": f"GetFileName failed: {e}"}

        if not board_path:
            return {"saved": False, "skipped": "no board path"}

        expected = self._board_disk_signature
        current = self._disk_signature(board_path)

        # Only refuse if the file's CONTENT (sha256) has actually diverged
        # from what we recorded. mtime alone is not a conflict signal —
        # `touch`, atime-driven backups, or even some MCP read paths can
        # advance mtime without changing content, and refusing on that
        # basis traps users in a state where every write needs an explicit
        # save_project workaround.
        #
        # If expected is None, treat this as "first save" and proceed —
        # otherwise pre-existing setups (open_project ran before this guard
        # was introduced) would never be able to save.
        if expected is not None and current is not None and expected[1] != current[1]:
            warning = (
                "Auto-save refused: the on-disk PCB file's contents changed "
                "externally since this MCP session loaded it. To avoid "
                "clobbering those changes, the in-memory mutation has NOT "
                "been written to disk. Reload via open_project to refresh, "
                "then re-apply the change."
            )
            logger.warning(f"{warning} ({board_path})")
            logger.warning(f"  expected sha256={expected[1][:12]}… mtime_ns={expected[0]}")
            logger.warning(f"  current  sha256={current[1][:12]}… mtime_ns={current[0]}")
            return {
                "saved": False,
                "warning": warning,
                "boardPath": board_path,
                "diskChangedExternally": True,
                "expectedMtimeNs": expected[0],
                "currentMtimeNs": current[0],
                "memChangesUnsaved": True,
            }

        # Content matches but mtime advanced (e.g. external `touch`): refresh
        # the recorded mtime so we don't re-hash on every subsequent call.
        if expected is not None and current is not None and expected != current:
            self._board_disk_signature = current

        # Make a rotating backup of the existing file (best-effort).
        backup_path: Optional[str] = None
        if current is not None:
            try:
                backup_dir = os.path.join(os.path.dirname(board_path) or ".", ".mcp-backups")
                os.makedirs(backup_dir, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
                base = os.path.basename(board_path)
                backup_path = os.path.join(backup_dir, f"{base}.{stamp}")
                shutil.copy2(board_path, backup_path)
                self._prune_auto_save_backups(backup_dir, base)
            except OSError as e:
                logger.warning(f"Auto-save backup failed (continuing): {e}")
                backup_path = None

        # Write the board.
        try:
            pcbnew.SaveBoard(board_path, self.board)
            logger.debug(f"Auto-saved board to: {board_path}")
            self._board_disk_signature = self._disk_signature(board_path)
        except Exception as e:
            logger.warning(f"Auto-save failed: {e}")
            return {"saved": False, "error": str(e), "backup": backup_path}

        # Post-save dehydration check. If the BOARD lost its bindings during
        # save, reload from disk while we still know the path. board_path is
        # guaranteed non-empty here (we returned early above otherwise).
        if not self._is_board_healthy():
            logger.warning(
                "Board became dehydrated during auto-save; reloading from %s",
                board_path,
            )
            recovered = self._safe_load_board(board_path)
            if recovered is not None:
                self.board = recovered
                self._update_command_handlers()
            else:
                logger.error(
                    "Board dehydration after auto-save is unrecoverable — "
                    "subsequent commands will fail until MCP restart"
                )

        return {"saved": True, "boardPath": board_path, "backup": backup_path}

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

    # Stable BOARD methods used to detect SWIG dehydration. Newer KiCAD nightly
    # builds occasionally return a raw SwigPyObject from pcbnew.LoadBoard after
    # certain mutating sequences (delete_trace, refill_zones, …) — the proxy
    # type-checks but every method access raises AttributeError. Probing for
    # these methods catches that state without segfaulting.
    _BOARD_HEALTH_METHODS = (
        "GetDesignSettings",
        "GetBoardEdgesBoundingBox",
        "GetFileName",
    )

    def _is_board_healthy(self, board: Optional[Any] = None) -> bool:
        """Return True if the board (default self.board) has live SWIG dispatch."""
        target = board if board is not None else self.board
        if target is None:
            return False
        return all(hasattr(target, m) for m in self._BOARD_HEALTH_METHODS)

    def _safe_load_board(self, path: str) -> Optional[Any]:
        """Load a board from disk, recovering from SWIG dehydration if pcbnew is broken.

        If pcbnew.LoadBoard returns a dehydrated proxy, reload the pcbnew
        module once and retry. Returns the new board, or None if recovery
        is impossible (caller must surface a real failure rather than fake
        success).
        """
        global pcbnew
        try:
            board = pcbnew.LoadBoard(path)
        except Exception as e:
            logger.error(f"LoadBoard({path!r}) raised: {e}")
            return None

        if self._is_board_healthy(board):
            return board

        logger.warning(
            f"LoadBoard({path!r}) returned a dehydrated SWIG proxy; "
            "reloading pcbnew module and retrying"
        )
        try:
            import importlib

            pcbnew = importlib.reload(pcbnew)
        except Exception as e:
            logger.error(f"pcbnew module reload failed: {e}")
            return None

        try:
            board = pcbnew.LoadBoard(path)
        except Exception as e:
            logger.error(f"LoadBoard retry after pcbnew reload failed: {e}")
            return None

        if not self._is_board_healthy(board):
            logger.error(
                "Board still dehydrated after pcbnew reload; SWIG state is "
                "unrecoverable in this process — restart the MCP server"
            )
            return None

        logger.info("Recovered from SWIG dehydration via pcbnew reload")
        return board

    # Schematic command handlers

    def _project_path_from_filename(self, filename: Optional[str]) -> Optional[Path]:
        """Resolve a project directory from a filename param.

        Accepts a .kicad_pro file, a .kicad_pcb file, or a directory.
        """
        if not filename:
            return None
        try:
            p = Path(filename).expanduser()
        except Exception:
            return None
        if p.is_file() or p.suffix in (".kicad_pro", ".kicad_pcb", ".kicad_sch"):
            return p.parent
        return p

    def _refresh_symbol_library_for_project(self, project_path: Optional[Path]) -> None:
        """Rebuild SymbolLibraryCommands' manager so project-scope sym-lib-table
        is visible to subsequent search/list/info calls. No-op if unchanged."""
        if project_path is None:
            return
        self._current_project_path = project_path
        try:
            self.symbol_library_commands.use_project(project_path)
        except Exception as e:
            logger.warning(f"Failed to refresh symbol library for project {project_path}: {e}")

    def _handle_open_project(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Wrap project_commands.open_project so project-scope symbol libraries
        become visible to subsequent search_symbols / list_symbol_libraries /
        get_symbol_info calls."""
        result = self.project_commands.open_project(params)
        if result.get("success"):
            project_info = result.get("project") or {}
            project_path = self._project_path_from_filename(
                project_info.get("path") or project_info.get("boardPath") or params.get("filename")
            )
            self._refresh_symbol_library_for_project(project_path)
        return result

    def _handle_create_project(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Wrap project_commands.create_project for the same reason as open_project."""
        result = self.project_commands.create_project(params)
        if result.get("success"):
            project_info = result.get("project") or {}
            project_path = self._project_path_from_filename(
                project_info.get("path")
                or project_info.get("boardPath")
                or params.get("path")
                or params.get("filename")
            )
            self._refresh_symbol_library_for_project(project_path)
        return result

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
                reloaded = self._safe_load_board(board_path)
                if reloaded is None:
                    return {
                        "success": False,
                        "message": f"Could not load board from boardPath: {board_path}",
                        "errorDetails": (
                            "pcbnew.LoadBoard failed or returned a dehydrated "
                            "SWIG proxy that could not be recovered"
                        ),
                    }
                self.board = reloaded
                self._update_command_handlers()
                logger.info("Board reloaded from boardPath")

            project_path = Path(board_path).parent
            if project_path != getattr(self, "_current_project_path", None):
                self._current_project_path = project_path
                local_lib = FootprintLibraryManager(project_path=project_path)
                self.component_commands = ComponentCommands(self.board, local_lib)
                logger.info(f"Reloaded FootprintLibraryManager with project_path={project_path}")

        return self.component_commands.place_component(params)

    # Built-in property names that have dedicated parameters and cannot be removed
    # via the generic removeProperties path. They are also written by KiCad on every
    # save, so deleting them produces an invalid schematic.
    _PROTECTED_PROPERTY_FIELDS = frozenset({"Reference", "Value", "Footprint", "Datasheet"})

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
            spec: Dict that may contain keys: value, x, y, angle, hide, fontSize,
                justify.  ``justify`` is a space-separated string of KiCad
                alignment keywords (e.g. "left", "right top"). "center" removes
                the directive (KiCad default).
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
        new_justify = spec.get("justify")
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

            if new_justify is not None:
                block = self._set_justify_on_property(block, name, str(new_justify))

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

        # Build optional (justify ...) token for the effects block.
        justify_str = ""
        if new_justify is not None:
            tokens = str(new_justify).strip().split()
            if not all(t == "center" for t in tokens):
                justify_str = f" (justify {str(new_justify).strip()})"

        new_prop = (
            f'    (property "{escaped_name}" "{escaped}" (at {cx} {cy} {ca})\n'
            f"      (effects (font (size {font_size} {font_size})){justify_str} {hide_str})\n"
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

    def _set_justify_on_property(self, block: str, name: str, justify: str) -> str:
        """Set or clear the (justify ...) directive on a named property's effects clause.

        ``justify`` is a space-separated string of KiCad alignment keywords:
            horizontal: "left" | "right" | "center"
            vertical:   "top"  | "bottom" | "center"
        Any combination of one or two tokens is accepted, e.g. "left", "right top".
        Passing "center" (the KiCad default) removes the (justify ...) directive
        entirely, which is how KiCad represents centered alignment.

        Handles effects clauses that already contain a (justify ...) token, and
        those that do not.
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

        prop_segment = block[prop_start : prop_end + 1]
        eff_match = re.search(r"\(effects\b", prop_segment)
        if not eff_match:
            return block
        eff_start = prop_start + eff_match.start()
        eff_end = self._find_matching_paren(block, eff_start)
        if eff_end < 0:
            return block

        eff_inner = block[eff_start + 1 : eff_end]  # 'effects (font ...) ...'
        # Remove any pre-existing (justify ...) token
        eff_inner = re.sub(r"\s*\(justify\b[^)]*\)", "", eff_inner)
        # "center" is the KiCad default — omitting the directive means centered
        tokens = justify.strip().split()
        is_center_only = all(t == "center" for t in tokens)
        if not is_center_only:
            eff_inner = eff_inner.rstrip() + f" (justify {justify.strip()})"

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

    def _handle_add_footprint_3d_model(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add or replace a 3D model (model ...) block in a .kicad_mod file."""
        logger.info(
            f"add_footprint_3d_model: {params.get('modelPath')} -> {params.get('footprintPath')}"
        )
        try:
            creator = FootprintCreator()
            return creator.add_3d_model(
                footprint_path=params.get("footprintPath", ""),
                model_path=params.get("modelPath", ""),
                offset=params.get("offset"),
                scale=params.get("scale"),
                rotate=params.get("rotate"),
                replace=params.get("replace", True),
            )
        except Exception as e:
            logger.error(f"add_footprint_3d_model error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_import_3d_model(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Copy a 3D model into the project's *.3dshapes and return a ${KIPRJMOD} path."""
        logger.info(
            f"import_3d_model: {params.get('modelPath')} -> project {params.get('projectPath')}"
        )
        try:
            creator = FootprintCreator()
            return creator.import_3d_model(
                model_path=params.get("modelPath", ""),
                project_path=params.get("projectPath", ""),
                library_dir=params.get("libraryDir"),
                new_name=params.get("newName"),
                overwrite=params.get("overwrite", False),
            )
        except Exception as e:
            logger.error(f"import_3d_model error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_add_component_3d_model(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a 3D model to a placed footprint on the board.

        Prefers the live IPC path; if IPC is unavailable this returns a clear
        message (live board editing requires KiCAD running with the IPC API).
        """
        if self.use_ipc and getattr(self, "ipc_board_api", None):
            return self._ipc_add_component_3d_model(params)
        return {
            "success": False,
            "message": (
                "add_component_3d_model requires the live IPC backend "
                "(KiCAD running with Preferences > Plugins > Enable IPC API Server). "
                "To edit a library footprint file instead, use add_footprint_3d_model."
            ),
        }

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

    def _handle_add_no_connect(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a no-connect flag (X marker) to an unconnected pin in the schematic."""
        logger.info("Adding no-connect flag to schematic")
        try:
            from pathlib import Path

            from commands.pin_locator import PinLocator
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            position = params.get("position")
            component_ref = params.get("componentRef")
            pin_number = params.get("pinNumber")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            # Snap to pin endpoint when componentRef + pinNumber are provided
            snapped_to_pin = None
            if component_ref and pin_number is not None:
                locator = PinLocator()
                pin_loc = locator.get_pin_location(
                    Path(schematic_path), component_ref, str(pin_number)
                )
                if pin_loc is None:
                    return {
                        "success": False,
                        "message": f"Could not locate pin {pin_number} on {component_ref}",
                    }
                position = pin_loc
                snapped_to_pin = {"component": component_ref, "pin": str(pin_number)}
            elif position is None:
                return {
                    "success": False,
                    "message": "Provide either position [x, y] or componentRef + pinNumber",
                }

            success = WireManager.add_no_connect(Path(schematic_path), position)
            if success:
                result = {
                    "success": True,
                    "message": f"Added no-connect flag at {position}",
                    "actual_position": position,
                }
                if snapped_to_pin:
                    result["snapped_to_pin"] = snapped_to_pin
                return result
            else:
                return {"success": False, "message": "Failed to add no-connect flag"}

        except Exception as e:
            import traceback

            logger.error(f"Error adding no-connect: {e}")
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_connect_to_net(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Connect a component pin to a named net using wire stub and label,
        and also assign the net to the corresponding pad on the PCB board so
        that save_project persists the net (pcbnew.SaveBoard only writes nets
        that are referenced by at least one board element).
        """
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

            # Also assign the net to the pad on the PCB board
            if self.board and isinstance(result, dict) and result.get("success"):
                try:
                    if self._assign_net_to_pad(component_ref, pin_name, net_name):
                        msg = result.get("message", "")
                        result["message"] = (msg + " (PCB pad also updated)").strip()
                except Exception as pcb_err:
                    logger.warning(f"Could not assign net to PCB pad: {pcb_err}")

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

            # Also assign nets to PCB pads for each successfully connected pin
            pcb_assigned = 0
            if self.board:
                import re as _re

                for conn_info in result.get("connected", []):
                    # Expected format: "{src_ref}/{pin} <-> {tgt_ref}/{pin} [{net}]"
                    try:
                        parts = conn_info.split(" <-> ")
                        if len(parts) != 2:
                            continue
                        src_part = parts[0]
                        rest = parts[1]
                        bracket_match = _re.search(r"\[(.+)\]", rest)
                        tgt_part = rest.split(" [")[0] if " [" in rest else rest
                        net_name = bracket_match.group(1) if bracket_match else None
                        if not net_name:
                            continue

                        src_ref_pin = src_part.split("/")
                        tgt_ref_pin = tgt_part.split("/")
                        if len(src_ref_pin) == 2 and self._assign_net_to_pad(
                            src_ref_pin[0], src_ref_pin[1], net_name
                        ):
                            pcb_assigned += 1
                        if len(tgt_ref_pin) == 2 and self._assign_net_to_pad(
                            tgt_ref_pin[0], tgt_ref_pin[1], net_name
                        ):
                            pcb_assigned += 1
                    except Exception as parse_err:
                        logger.debug(
                            f"Could not parse passthrough result for PCB assignment: {parse_err}"
                        )

            n_ok = len(result["connected"])
            n_fail = len(result["failed"])
            msg = f"Passthrough complete: {n_ok} connected, {n_fail} failed"
            if pcb_assigned:
                msg += f" ({pcb_assigned} PCB pads updated)"
            return {
                "success": n_fail == 0,
                "message": msg,
                "connected": result["connected"],
                "failed": result["failed"],
            }
        except Exception as e:
            logger.error(f"Error in connect_passthrough: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _assign_net_to_pad(self, component_ref: str, pin_name: str, net_name: str) -> bool:
        """Assign a net to a specific pad on the PCB board.

        Ensures the net exists on the board and sets it on the matching pad.
        Needed because pcbnew.SaveBoard() drops nets that are not referenced
        by any board element (pad/track/via/zone).
        Returns True if the pad was found and updated.
        """
        board = self.board
        if not board:
            return False

        netinfo = board.GetNetInfo()
        nets_map = netinfo.NetsByName()
        if not nets_map.has_key(net_name):
            net_item = pcbnew.NETINFO_ITEM(board, net_name)
            board.Add(net_item)
            netinfo = board.GetNetInfo()
            nets_map = netinfo.NetsByName()

        if not nets_map.has_key(net_name):
            logger.warning(f"Net '{net_name}' could not be created on board")
            return False

        net_obj = nets_map[net_name]

        for fp in board.GetFootprints():
            if fp.GetReference() == component_ref:
                for pad in fp.Pads():
                    if str(pad.GetNumber()) == str(pin_name):
                        pad.SetNet(net_obj)
                        logger.info(
                            f"Assigned net '{net_name}' to pad {component_ref}/{pin_name} on PCB"
                        )
                        return True
                logger.warning(f"Pad '{pin_name}' not found on footprint '{component_ref}'")
                return False

        logger.warning(f"Footprint '{component_ref}' not found on board")
        return False

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

    def _handle_export_gerbers(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Plot multiple Gerbers for a PCB via kicad-cli (`pcb export gerbers`).

        Exposes the full Plot-dialog option set. Reads the board from disk, so it
        reflects the last *saved* state of the .kicad_pcb. Pass ``boardPath`` to
        target a specific file; otherwise the current board path is used.
        """
        import subprocess

        logger.info("Exporting Gerbers via kicad-cli")
        try:
            board_path = params.get("boardPath") or self._current_board_path()
            output_dir = params.get("outputDir")

            if not board_path:
                return {
                    "success": False,
                    "message": "boardPath is required (no current board could be resolved)",
                }
            if not Path(board_path).exists():
                return {"success": False, "message": f"Board not found: {board_path}"}
            if not output_dir:
                return {"success": False, "message": "outputDir is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_dir = str(Path(output_dir).expanduser().resolve())
            Path(output_dir).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "pcb", "export", "gerbers", "--output", output_dir]

            # Layer selection (accept list or comma string)
            layers = params.get("layers")
            if layers:
                cmd += ["--layers", ",".join(layers) if isinstance(layers, list) else str(layers)]
            common_layers = params.get("commonLayers")
            if common_layers:
                cmd += [
                    "--common-layers",
                    (
                        ",".join(common_layers)
                        if isinstance(common_layers, list)
                        else str(common_layers)
                    ),
                ]

            if params.get("drawingSheet"):
                cmd += ["--drawing-sheet", params["drawingSheet"]]
            for kv in params.get("defineVar", []) or []:
                cmd += ["--define-var", kv]

            # Boolean flags (omit to leave at kicad-cli default)
            flag_map = {
                "excludeRefdes": "--exclude-refdes",
                "excludeValue": "--exclude-value",
                "includeBorderTitle": "--include-border-title",
                "sketchPadsOnFabLayers": "--sketch-pads-on-fab-layers",
                "hideDnpFootprintsOnFabLayers": "--hide-DNP-footprints-on-fab-layers",
                "sketchDnpFootprintsOnFabLayers": "--sketch-DNP-footprints-on-fab-layers",
                "crossoutDnpFootprintsOnFabLayers": "--crossout-DNP-footprints-on-fab-layers",
                "noX2": "--no-x2",
                "noNetlist": "--no-netlist",
                "subtractSoldermask": "--subtract-soldermask",
                "disableApertureMacros": "--disable-aperture-macros",
                "useDrillFileOrigin": "--use-drill-file-origin",
                "noProtelExt": "--no-protel-ext",
                "boardPlotParams": "--board-plot-params",
            }
            for key, flag in flag_map.items():
                if params.get(key):
                    cmd.append(flag)

            precision = params.get("precision")
            if precision is not None:
                cmd += ["--precision", str(precision)]

            cmd.append(board_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }

            files = sorted(p.name for p in Path(output_dir).iterdir() if p.is_file())
            return {"success": True, "outputDir": output_dir, "files": files}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 180 seconds"}
        except Exception as e:
            logger.error(f"Error exporting Gerbers: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_drill(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate drill files via kicad-cli (`pcb export drill`).

        Exposes the full Excellon/Gerber drill option set. Reads the saved
        .kicad_pcb on disk.
        """
        import subprocess

        logger.info("Exporting drill files via kicad-cli")
        try:
            board_path = params.get("boardPath") or self._current_board_path()
            output_dir = params.get("outputDir")

            if not board_path:
                return {
                    "success": False,
                    "message": "boardPath is required (no current board could be resolved)",
                }
            if not Path(board_path).exists():
                return {"success": False, "message": f"Board not found: {board_path}"}
            if not output_dir:
                return {"success": False, "message": "outputDir is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_dir = str(Path(output_dir).expanduser().resolve())
            # kicad-cli drill requires the output dir path to end with a separator
            Path(output_dir).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "pcb", "export", "drill", "--output", output_dir + os.sep]

            # Valued options (omit to use kicad-cli defaults)
            value_map = {
                "format": "--format",
                "drillOrigin": "--drill-origin",
                "excellonZerosFormat": "--excellon-zeros-format",
                "excellonOvalFormat": "--excellon-oval-format",
                "excellonUnits": "--excellon-units",
                "mapFormat": "--map-format",
                "gerberPrecision": "--gerber-precision",
            }
            for key, flag in value_map.items():
                val = params.get(key)
                if val is not None:
                    cmd += [flag, str(val)]

            # Boolean flags
            flag_map = {
                "excellonMirrorY": "--excellon-mirror-y",
                "excellonMinHeader": "--excellon-min-header",
                "excellonSeparateTh": "--excellon-separate-th",
                "generateMap": "--generate-map",
            }
            for key, flag in flag_map.items():
                if params.get(key):
                    cmd.append(flag)

            cmd.append(board_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }

            files = sorted(p.name for p in Path(output_dir).iterdir() if p.is_file())
            return {"success": True, "outputDir": output_dir, "files": files}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 120 seconds"}
        except Exception as e:
            logger.error(f"Error exporting drill files: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_ipc2581(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export the PCB in IPC-2581 format via kicad-cli (`pcb export ipc2581`).

        IPC-2581 is a single-file MES/CAD interchange format carrying placement,
        nets, and BOM part data inline. The bom-col-* params map schematic fields
        to the BOM columns embedded in the file. Reads the saved .kicad_pcb.
        """
        import subprocess

        logger.info("Exporting IPC-2581 via kicad-cli")
        try:
            board_path = params.get("boardPath") or self._current_board_path()
            output_path = params.get("outputPath")

            if not board_path:
                return {
                    "success": False,
                    "message": "boardPath is required (no current board could be resolved)",
                }
            if not Path(board_path).exists():
                return {"success": False, "message": f"Board not found: {board_path}"}
            if not output_path:
                return {"success": False, "message": "outputPath is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_path = str(Path(output_path).expanduser().resolve())
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "pcb", "export", "ipc2581", "--output", output_path]

            if params.get("drawingSheet"):
                cmd += ["--drawing-sheet", params["drawingSheet"]]
            for kv in params.get("defineVar", []) or []:
                cmd += ["--define-var", kv]

            value_map = {
                "precision": "--precision",
                "version": "--version",
                "units": "--units",
                "bomColIntId": "--bom-col-int-id",
                "bomColMfgPn": "--bom-col-mfg-pn",
                "bomColMfg": "--bom-col-mfg",
                "bomColDistPn": "--bom-col-dist-pn",
                "bomColDist": "--bom-col-dist",
            }
            for key, flag in value_map.items():
                val = params.get(key)
                if val is not None and val != "":
                    cmd += [flag, str(val)]

            if params.get("compress"):
                cmd.append("--compress")

            cmd.append(board_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }
            return {"success": True, "outputPath": output_path}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 180 seconds"}
        except Exception as e:
            logger.error(f"Error exporting IPC-2581: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_odb(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export the PCB in ODB++ format via kicad-cli (`pcb export odb`).

        ODB++ is a fab/assembly job archive. ``compression`` selects the output
        container (zip / tgz / none). Reads the saved .kicad_pcb.
        """
        import subprocess

        logger.info("Exporting ODB++ via kicad-cli")
        try:
            board_path = params.get("boardPath") or self._current_board_path()
            output_path = params.get("outputPath")

            if not board_path:
                return {
                    "success": False,
                    "message": "boardPath is required (no current board could be resolved)",
                }
            if not Path(board_path).exists():
                return {"success": False, "message": f"Board not found: {board_path}"}
            if not output_path:
                return {"success": False, "message": "outputPath is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_path = str(Path(output_path).expanduser().resolve())
            parent = Path(output_path).parent
            if parent:
                Path(parent).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "pcb", "export", "odb", "--output", output_path]

            if params.get("drawingSheet"):
                cmd += ["--drawing-sheet", params["drawingSheet"]]
            for kv in params.get("defineVar", []) or []:
                cmd += ["--define-var", kv]
            for key, flag in {
                "precision": "--precision",
                "compression": "--compression",
                "units": "--units",
            }.items():
                val = params.get(key)
                if val is not None and val != "":
                    cmd += [flag, str(val)]

            cmd.append(board_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }
            return {"success": True, "outputPath": output_path}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 180 seconds"}
        except Exception as e:
            logger.error(f"Error exporting ODB++: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_ipcd356(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate an IPC-D-356 netlist file via kicad-cli (`pcb export ipcd356`).

        IPC-D-356 is a bare-board electrical-test netlist consumed by flying-probe
        and bed-of-nails testers. Minimal option set (output + input only). Reads
        the saved .kicad_pcb.
        """
        import subprocess

        logger.info("Exporting IPC-D-356 netlist via kicad-cli")
        try:
            board_path = params.get("boardPath") or self._current_board_path()
            output_path = params.get("outputPath")

            if not board_path:
                return {
                    "success": False,
                    "message": "boardPath is required (no current board could be resolved)",
                }
            if not Path(board_path).exists():
                return {"success": False, "message": f"Board not found: {board_path}"}
            if not output_path:
                return {"success": False, "message": "outputPath is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_path = str(Path(output_path).expanduser().resolve())
            parent = Path(output_path).parent
            if parent:
                Path(parent).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "pcb", "export", "ipcd356", "--output", output_path]
            cmd.append(board_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }
            return {"success": True, "outputPath": output_path}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 180 seconds"}
        except Exception as e:
            logger.error(f"Error exporting IPC-D-356: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_gencad(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export the PCB in GenCAD format via kicad-cli (`pcb export gencad`).

        GenCAD is an assembly/test interchange format. Exposes the padstack-flip,
        unique-pin/footprint, drill-origin, and store-origin flags. Reads the
        saved .kicad_pcb.
        """
        import subprocess

        logger.info("Exporting GenCAD via kicad-cli")
        try:
            board_path = params.get("boardPath") or self._current_board_path()
            output_path = params.get("outputPath")

            if not board_path:
                return {
                    "success": False,
                    "message": "boardPath is required (no current board could be resolved)",
                }
            if not Path(board_path).exists():
                return {"success": False, "message": f"Board not found: {board_path}"}
            if not output_path:
                return {"success": False, "message": "outputPath is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_path = str(Path(output_path).expanduser().resolve())
            parent = Path(output_path).parent
            if parent:
                Path(parent).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "pcb", "export", "gencad", "--output", output_path]

            for kv in params.get("defineVar", []) or []:
                cmd += ["--define-var", kv]

            flag_map = {
                "flipBottomPads": "--flip-bottom-pads",
                "uniquePins": "--unique-pins",
                "uniqueFootprints": "--unique-footprints",
                "useDrillOrigin": "--use-drill-origin",
                "storeOriginCoord": "--store-origin-coord",
            }
            for key, flag in flag_map.items():
                if params.get(key):
                    cmd.append(flag)

            cmd.append(board_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }
            return {"success": True, "outputPath": output_path}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 180 seconds"}
        except Exception as e:
            logger.error(f"Error exporting GenCAD: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_pos(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a component placement (position) file via kicad-cli
        (`pcb export pos`).

        This is the rich CLI sibling of export_position_file: full option set
        (side, format, units, bottom-negate-X, drill origin, SMD-only, TH/DNP
        exclusion, gerber board edge). Reads the saved .kicad_pcb.
        """
        import subprocess

        logger.info("Exporting position file via kicad-cli")
        try:
            board_path = params.get("boardPath") or self._current_board_path()
            output_path = params.get("outputPath")

            if not board_path:
                return {
                    "success": False,
                    "message": "boardPath is required (no current board could be resolved)",
                }
            if not Path(board_path).exists():
                return {"success": False, "message": f"Board not found: {board_path}"}
            if not output_path:
                return {"success": False, "message": "outputPath is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_path = str(Path(output_path).expanduser().resolve())
            parent = Path(output_path).parent
            if parent:
                Path(parent).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "pcb", "export", "pos", "--output", output_path]

            value_map = {
                "side": "--side",
                "format": "--format",
                "units": "--units",
            }
            for key, flag in value_map.items():
                val = params.get(key)
                if val is not None and val != "":
                    cmd += [flag, str(val)]

            flag_map = {
                "bottomNegateX": "--bottom-negate-x",
                "useDrillFileOrigin": "--use-drill-file-origin",
                "smdOnly": "--smd-only",
                "excludeFpTh": "--exclude-fp-th",
                "excludeDnp": "--exclude-dnp",
                "gerberBoardEdge": "--gerber-board-edge",
            }
            for key, flag in flag_map.items():
                if params.get(key):
                    cmd.append(flag)

            cmd.append(board_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }
            return {"success": True, "outputPath": output_path}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 180 seconds"}
        except Exception as e:
            logger.error(f"Error exporting position file: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_pcb_pdf(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Plot the PCB to PDF via kicad-cli (`pcb export pdf`).

        Exposes the full layer-plot option set: layer lists, mirror, refdes/value
        exclusion, border+title, soldermask subtraction, DNP fab-layer modes,
        negative/B&W, theme, drill-shape, and the single/separate/multipage
        output modes. Reads the saved .kicad_pcb.
        """
        import subprocess

        logger.info("Exporting PCB PDF via kicad-cli")
        try:
            board_path = params.get("boardPath") or self._current_board_path()
            output_path = params.get("outputPath")

            if not board_path:
                return {
                    "success": False,
                    "message": "boardPath is required (no current board could be resolved)",
                }
            if not Path(board_path).exists():
                return {"success": False, "message": f"Board not found: {board_path}"}
            if not output_path:
                return {"success": False, "message": "outputPath is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_path = str(Path(output_path).expanduser().resolve())
            parent = Path(output_path).parent
            if parent:
                Path(parent).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "pcb", "export", "pdf", "--output", output_path]

            layers = params.get("layers")
            if layers:
                cmd += ["--layers", ",".join(layers) if isinstance(layers, list) else str(layers)]
            common_layers = params.get("commonLayers")
            if common_layers:
                cmd += [
                    "--common-layers",
                    (
                        ",".join(common_layers)
                        if isinstance(common_layers, list)
                        else str(common_layers)
                    ),
                ]

            if params.get("drawingSheet"):
                cmd += ["--drawing-sheet", params["drawingSheet"]]
            for kv in params.get("defineVar", []) or []:
                cmd += ["--define-var", kv]

            value_map = {
                "theme": "--theme",
                "drillShapeOpt": "--drill-shape-opt",
            }
            for key, flag in value_map.items():
                val = params.get(key)
                if val is not None and val != "":
                    cmd += [flag, str(val)]

            flag_map = {
                "mirror": "--mirror",
                "excludeRefdes": "--exclude-refdes",
                "excludeValue": "--exclude-value",
                "includeBorderTitle": "--include-border-title",
                "subtractSoldermask": "--subtract-soldermask",
                "sketchPadsOnFabLayers": "--sketch-pads-on-fab-layers",
                "hideDnpFootprintsOnFabLayers": "--hide-DNP-footprints-on-fab-layers",
                "sketchDnpFootprintsOnFabLayers": "--sketch-DNP-footprints-on-fab-layers",
                "crossoutDnpFootprintsOnFabLayers": "--crossout-DNP-footprints-on-fab-layers",
                "negative": "--negative",
                "blackAndWhite": "--black-and-white",
                "modeSingle": "--mode-single",
                "modeSeparate": "--mode-separate",
                "modeMultipage": "--mode-multipage",
            }
            for key, flag in flag_map.items():
                if params.get(key):
                    cmd.append(flag)

            cmd.append(board_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }
            return {"success": True, "outputPath": output_path}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 180 seconds"}
        except Exception as e:
            logger.error(f"Error exporting PCB PDF: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_pcb_svg(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Plot the PCB to SVG via kicad-cli (`pcb export svg`).

        Exposes the full layer-plot option set: layer lists, mirror, soldermask
        subtraction, negative/B&W, theme, DNP fab-layer modes, page-size mode,
        fit-page, drill-shape, and single/multi output modes. Reads the saved
        .kicad_pcb.
        """
        import subprocess

        logger.info("Exporting PCB SVG via kicad-cli")
        try:
            board_path = params.get("boardPath") or self._current_board_path()
            output_path = params.get("outputPath")

            if not board_path:
                return {
                    "success": False,
                    "message": "boardPath is required (no current board could be resolved)",
                }
            if not Path(board_path).exists():
                return {"success": False, "message": f"Board not found: {board_path}"}
            if not output_path:
                return {"success": False, "message": "outputPath is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_path = str(Path(output_path).expanduser().resolve())
            parent = Path(output_path).parent
            if parent:
                Path(parent).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "pcb", "export", "svg", "--output", output_path]

            layers = params.get("layers")
            if layers:
                cmd += ["--layers", ",".join(layers) if isinstance(layers, list) else str(layers)]
            common_layers = params.get("commonLayers")
            if common_layers:
                cmd += [
                    "--common-layers",
                    (
                        ",".join(common_layers)
                        if isinstance(common_layers, list)
                        else str(common_layers)
                    ),
                ]

            if params.get("drawingSheet"):
                cmd += ["--drawing-sheet", params["drawingSheet"]]
            for kv in params.get("defineVar", []) or []:
                cmd += ["--define-var", kv]

            value_map = {
                "theme": "--theme",
                "pageSizeMode": "--page-size-mode",
                "drillShapeOpt": "--drill-shape-opt",
            }
            for key, flag in value_map.items():
                val = params.get(key)
                if val is not None and val != "":
                    cmd += [flag, str(val)]

            flag_map = {
                "subtractSoldermask": "--subtract-soldermask",
                "mirror": "--mirror",
                "negative": "--negative",
                "blackAndWhite": "--black-and-white",
                "sketchPadsOnFabLayers": "--sketch-pads-on-fab-layers",
                "hideDnpFootprintsOnFabLayers": "--hide-DNP-footprints-on-fab-layers",
                "sketchDnpFootprintsOnFabLayers": "--sketch-DNP-footprints-on-fab-layers",
                "crossoutDnpFootprintsOnFabLayers": "--crossout-DNP-footprints-on-fab-layers",
                "fitPageToBoard": "--fit-page-to-board",
                "excludeDrawingSheet": "--exclude-drawing-sheet",
                "modeSingle": "--mode-single",
                "modeMulti": "--mode-multi",
            }
            for key, flag in flag_map.items():
                if params.get(key):
                    cmd.append(flag)

            cmd.append(board_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }
            return {"success": True, "outputPath": output_path}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 180 seconds"}
        except Exception as e:
            logger.error(f"Error exporting PCB SVG: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_pcb_dxf(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Plot the PCB to DXF via kicad-cli (`pcb export dxf`).

        Exposes the full layer-plot option set: layer lists, refdes/value
        exclusion, soldermask subtraction, contours, drill origin, border+title,
        output units, DNP fab-layer modes, drill-shape, and single/multi output
        modes. Reads the saved .kicad_pcb.
        """
        import subprocess

        logger.info("Exporting PCB DXF via kicad-cli")
        try:
            board_path = params.get("boardPath") or self._current_board_path()
            output_path = params.get("outputPath")

            if not board_path:
                return {
                    "success": False,
                    "message": "boardPath is required (no current board could be resolved)",
                }
            if not Path(board_path).exists():
                return {"success": False, "message": f"Board not found: {board_path}"}
            if not output_path:
                return {"success": False, "message": "outputPath is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_path = str(Path(output_path).expanduser().resolve())
            parent = Path(output_path).parent
            if parent:
                Path(parent).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "pcb", "export", "dxf", "--output", output_path]

            layers = params.get("layers")
            if layers:
                cmd += ["--layers", ",".join(layers) if isinstance(layers, list) else str(layers)]
            common_layers = params.get("commonLayers")
            if common_layers:
                cmd += [
                    "--common-layers",
                    (
                        ",".join(common_layers)
                        if isinstance(common_layers, list)
                        else str(common_layers)
                    ),
                ]

            if params.get("drawingSheet"):
                cmd += ["--drawing-sheet", params["drawingSheet"]]
            for kv in params.get("defineVar", []) or []:
                cmd += ["--define-var", kv]

            value_map = {
                "outputUnits": "--output-units",
                "drillShapeOpt": "--drill-shape-opt",
            }
            for key, flag in value_map.items():
                val = params.get(key)
                if val is not None and val != "":
                    cmd += [flag, str(val)]

            flag_map = {
                "excludeRefdes": "--exclude-refdes",
                "excludeValue": "--exclude-value",
                "sketchPadsOnFabLayers": "--sketch-pads-on-fab-layers",
                "hideDnpFootprintsOnFabLayers": "--hide-DNP-footprints-on-fab-layers",
                "sketchDnpFootprintsOnFabLayers": "--sketch-DNP-footprints-on-fab-layers",
                "crossoutDnpFootprintsOnFabLayers": "--crossout-DNP-footprints-on-fab-layers",
                "subtractSoldermask": "--subtract-soldermask",
                "useContours": "--use-contours",
                "useDrillOrigin": "--use-drill-origin",
                "includeBorderTitle": "--include-border-title",
                "modeSingle": "--mode-single",
                "modeMulti": "--mode-multi",
            }
            for key, flag in flag_map.items():
                if params.get(key):
                    cmd.append(flag)

            cmd.append(board_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }
            return {"success": True, "outputPath": output_path}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 180 seconds"}
        except Exception as e:
            logger.error(f"Error exporting PCB DXF: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_gerber_single(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Plot the given layers to a single Gerber file via kicad-cli
        (`pcb export gerber`).

        Singular sibling of export_gerbers: emits ONE Gerber file containing the
        selected layers. Exposes the full single-file Plot option set (X2,
        netlist attributes, DNP fab-layer modes, soldermask subtraction, aperture
        macros, drill-file origin, precision, Protel extension). Reads the saved
        .kicad_pcb.
        """
        import subprocess

        logger.info("Exporting single Gerber via kicad-cli")
        try:
            board_path = params.get("boardPath") or self._current_board_path()
            output_path = params.get("outputPath")

            if not board_path:
                return {
                    "success": False,
                    "message": "boardPath is required (no current board could be resolved)",
                }
            if not Path(board_path).exists():
                return {"success": False, "message": f"Board not found: {board_path}"}
            if not output_path:
                return {"success": False, "message": "outputPath is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_path = str(Path(output_path).expanduser().resolve())
            parent = Path(output_path).parent
            if parent:
                Path(parent).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "pcb", "export", "gerber", "--output", output_path]

            layers = params.get("layers")
            if layers:
                cmd += ["--layers", ",".join(layers) if isinstance(layers, list) else str(layers)]
            common_layers = params.get("commonLayers")
            if common_layers:
                cmd += [
                    "--common-layers",
                    (
                        ",".join(common_layers)
                        if isinstance(common_layers, list)
                        else str(common_layers)
                    ),
                ]

            if params.get("drawingSheet"):
                cmd += ["--drawing-sheet", params["drawingSheet"]]
            for kv in params.get("defineVar", []) or []:
                cmd += ["--define-var", kv]

            flag_map = {
                "excludeRefdes": "--exclude-refdes",
                "excludeValue": "--exclude-value",
                "includeBorderTitle": "--include-border-title",
                "sketchPadsOnFabLayers": "--sketch-pads-on-fab-layers",
                "hideDnpFootprintsOnFabLayers": "--hide-DNP-footprints-on-fab-layers",
                "sketchDnpFootprintsOnFabLayers": "--sketch-DNP-footprints-on-fab-layers",
                "crossoutDnpFootprintsOnFabLayers": "--crossout-DNP-footprints-on-fab-layers",
                "noX2": "--no-x2",
                "noNetlist": "--no-netlist",
                "subtractSoldermask": "--subtract-soldermask",
                "disableApertureMacros": "--disable-aperture-macros",
                "useDrillFileOrigin": "--use-drill-file-origin",
                "noProtelExt": "--no-protel-ext",
            }
            for key, flag in flag_map.items():
                if params.get(key):
                    cmd.append(flag)

            precision = params.get("precision")
            if precision is not None:
                cmd += ["--precision", str(precision)]

            cmd.append(board_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }
            return {"success": True, "outputPath": output_path}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 180 seconds"}
        except Exception as e:
            logger.error(f"Error exporting single Gerber: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_3d_cli(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export a 3D model of the PCB via kicad-cli (`pcb export <fmt>`).

        Rich CLI sibling of export_3d / export_vrml. The ``format`` param selects
        the subcommand (step, glb, stl, ply, brep, xao, vrml) and only flags valid
        for that subcommand are forwarded. STEP/glb/stl/ply/brep/xao share the
        geometry/include flag set; vrml uses units + models-dir instead. Reads the
        saved .kicad_pcb.
        """
        import subprocess

        logger.info("Exporting 3D model via kicad-cli")
        try:
            board_path = params.get("boardPath") or self._current_board_path()
            output_path = params.get("outputPath")
            fmt = params.get("format")

            if not board_path:
                return {
                    "success": False,
                    "message": "boardPath is required (no current board could be resolved)",
                }
            if not Path(board_path).exists():
                return {"success": False, "message": f"Board not found: {board_path}"}
            if not output_path:
                return {"success": False, "message": "outputPath is required"}
            valid_formats = ("step", "glb", "stl", "ply", "brep", "xao", "vrml")
            if fmt not in valid_formats:
                return {
                    "success": False,
                    "message": f"format must be one of {valid_formats}",
                }

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_path = str(Path(output_path).expanduser().resolve())
            parent = Path(output_path).parent
            if parent:
                Path(parent).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "pcb", "export", fmt, "--output", output_path]

            for kv in params.get("defineVar", []) or []:
                cmd += ["--define-var", kv]

            # Flags common to ALL 3D subcommands
            common_flags = {
                "force": "--force",
                "noUnspecified": "--no-unspecified",
                "noDnp": "--no-dnp",
            }
            # Flags shared by step/glb/stl/ply/brep/xao (NOT vrml)
            mesh_flags = {
                "gridOrigin": "--grid-origin",
                "drillOrigin": "--drill-origin",
                "substModels": "--subst-models",
                "boardOnly": "--board-only",
                "cutViasInBody": "--cut-vias-in-body",
                "noBoardBody": "--no-board-body",
                "noComponents": "--no-components",
                "includeTracks": "--include-tracks",
                "includePads": "--include-pads",
                "includeZones": "--include-zones",
                "includeInnerCopper": "--include-inner-copper",
                "includeSilkscreen": "--include-silkscreen",
                "includeSoldermask": "--include-soldermask",
                "fuseShapes": "--fuse-shapes",
                "fillAllVias": "--fill-all-vias",
            }
            # STEP-only flag
            step_flags = {
                "noOptimizeStep": "--no-optimize-step",
            }

            flag_map = dict(common_flags)
            if fmt != "vrml":
                flag_map.update(mesh_flags)
            if fmt == "step":
                flag_map.update(step_flags)
            for key, flag in flag_map.items():
                if params.get(key):
                    cmd.append(flag)

            # Valued flags common to all: user-origin
            if params.get("userOrigin") is not None and params.get("userOrigin") != "":
                cmd += ["--user-origin", str(params["userOrigin"])]
            # Component filter + net filter + min distance: mesh subcommands only
            if fmt != "vrml":
                if params.get("componentFilter") is not None and params["componentFilter"] != "":
                    cmd += ["--component-filter", str(params["componentFilter"])]
                if params.get("netFilter") is not None and params["netFilter"] != "":
                    cmd += ["--net-filter", str(params["netFilter"])]
                if params.get("minDistance") is not None and params["minDistance"] != "":
                    cmd += ["--min-distance", str(params["minDistance"])]
            # VRML-only valued flags
            if fmt == "vrml":
                if params.get("units") is not None and params["units"] != "":
                    cmd += ["--units", str(params["units"])]
                if params.get("modelsDir") is not None and params["modelsDir"] != "":
                    cmd += ["--models-dir", str(params["modelsDir"])]
                if params.get("modelsRelative"):
                    cmd.append("--models-relative")

            cmd.append(board_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }
            return {"success": True, "outputPath": output_path}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 300 seconds"}
        except Exception as e:
            logger.error(f"Error exporting 3D model: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_sch_bom(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a Bill of Materials from a schematic via kicad-cli
        (`sch export bom`).

        Exposes the full BOM option set: presets, field/label lists, grouping,
        sorting, filtering, DNP/excluded handling, and the field/string/ref
        delimiters. schematicPath is required (no current-schematic resolver).
        """
        import subprocess

        logger.info("Exporting schematic BOM via kicad-cli")
        try:
            schematic_path = params.get("schematicPath")
            output_path = params.get("outputPath")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not Path(schematic_path).exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}
            if not output_path:
                return {"success": False, "message": "outputPath is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_path = str(Path(output_path).expanduser().resolve())
            parent = Path(output_path).parent
            if parent:
                Path(parent).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "sch", "export", "bom", "--output", output_path]

            value_map = {
                "preset": "--preset",
                "formatPreset": "--format-preset",
                "fields": "--fields",
                "labels": "--labels",
                "groupBy": "--group-by",
                "sortField": "--sort-field",
                "sortAsc": "--sort-asc",
                "filter": "--filter",
                "fieldDelimiter": "--field-delimiter",
                "stringDelimiter": "--string-delimiter",
                "refDelimiter": "--ref-delimiter",
                "refRangeDelimiter": "--ref-range-delimiter",
            }
            for key, flag in value_map.items():
                val = params.get(key)
                if val is not None and val != "":
                    cmd += [flag, str(val)]

            flag_map = {
                "excludeDnp": "--exclude-dnp",
                "includeExcludedFromBom": "--include-excluded-from-bom",
                "keepTabs": "--keep-tabs",
                "keepLineBreaks": "--keep-line-breaks",
            }
            for key, flag in flag_map.items():
                if params.get(key):
                    cmd.append(flag)

            cmd.append(schematic_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }
            return {"success": True, "outputPath": output_path}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 180 seconds"}
        except Exception as e:
            logger.error(f"Error exporting schematic BOM: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_sch_pdf(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export a schematic to PDF via kicad-cli (`sch export pdf`).

        Exposes the full option set: drawing-sheet override, theme, B&W,
        exclude-drawing-sheet, default-font, the PDF popup/link/metadata
        excludes, no-background-color, and page selection. schematicPath is
        required.
        """
        import subprocess

        logger.info("Exporting schematic PDF via kicad-cli")
        try:
            schematic_path = params.get("schematicPath")
            output_path = params.get("outputPath")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not Path(schematic_path).exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}
            if not output_path:
                return {"success": False, "message": "outputPath is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_path = str(Path(output_path).expanduser().resolve())
            parent = Path(output_path).parent
            if parent:
                Path(parent).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "sch", "export", "pdf", "--output", output_path]

            if params.get("drawingSheet"):
                cmd += ["--drawing-sheet", params["drawingSheet"]]
            for kv in params.get("defineVar", []) or []:
                cmd += ["--define-var", kv]

            value_map = {
                "theme": "--theme",
                "defaultFont": "--default-font",
                "pages": "--pages",
            }
            for key, flag in value_map.items():
                val = params.get(key)
                if val is not None and val != "":
                    cmd += [flag, str(val)]

            flag_map = {
                "blackAndWhite": "--black-and-white",
                "excludeDrawingSheet": "--exclude-drawing-sheet",
                "excludePdfPropertyPopups": "--exclude-pdf-property-popups",
                "excludePdfHierarchicalLinks": "--exclude-pdf-hierarchical-links",
                "excludePdfMetadata": "--exclude-pdf-metadata",
                "noBackgroundColor": "--no-background-color",
            }
            for key, flag in flag_map.items():
                if params.get(key):
                    cmd.append(flag)

            cmd.append(schematic_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }
            return {"success": True, "outputPath": output_path}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 180 seconds"}
        except Exception as e:
            logger.error(f"Error exporting schematic PDF: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_sch_svg(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export a schematic to SVG via kicad-cli (`sch export svg`).

        Output is a directory (one SVG per page). Exposes drawing-sheet override,
        theme, B&W, exclude-drawing-sheet, default-font, no-background-color, and
        page selection. schematicPath is required.
        """
        import subprocess

        logger.info("Exporting schematic SVG via kicad-cli")
        try:
            schematic_path = params.get("schematicPath")
            output_dir = params.get("outputDir")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not Path(schematic_path).exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}
            if not output_dir:
                return {"success": False, "message": "outputDir is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_dir = str(Path(output_dir).expanduser().resolve())
            Path(output_dir).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "sch", "export", "svg", "--output", output_dir]

            if params.get("drawingSheet"):
                cmd += ["--drawing-sheet", params["drawingSheet"]]
            for kv in params.get("defineVar", []) or []:
                cmd += ["--define-var", kv]

            value_map = {
                "theme": "--theme",
                "defaultFont": "--default-font",
                "pages": "--pages",
            }
            for key, flag in value_map.items():
                val = params.get(key)
                if val is not None and val != "":
                    cmd += [flag, str(val)]

            flag_map = {
                "blackAndWhite": "--black-and-white",
                "excludeDrawingSheet": "--exclude-drawing-sheet",
                "noBackgroundColor": "--no-background-color",
            }
            for key, flag in flag_map.items():
                if params.get(key):
                    cmd.append(flag)

            cmd.append(schematic_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }

            files = sorted(p.name for p in Path(output_dir).iterdir() if p.is_file())
            return {"success": True, "outputDir": output_dir, "files": files}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 180 seconds"}
        except Exception as e:
            logger.error(f"Error exporting schematic SVG: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_sch_dxf(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export a schematic to DXF via kicad-cli (`sch export dxf`).

        Output is a directory (one DXF per page). Exposes drawing-sheet override,
        theme, B&W, exclude-drawing-sheet, default-font, and page selection.
        schematicPath is required.
        """
        import subprocess

        logger.info("Exporting schematic DXF via kicad-cli")
        try:
            schematic_path = params.get("schematicPath")
            output_dir = params.get("outputDir")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not Path(schematic_path).exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}
            if not output_dir:
                return {"success": False, "message": "outputDir is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_dir = str(Path(output_dir).expanduser().resolve())
            Path(output_dir).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "sch", "export", "dxf", "--output", output_dir]

            if params.get("drawingSheet"):
                cmd += ["--drawing-sheet", params["drawingSheet"]]
            for kv in params.get("defineVar", []) or []:
                cmd += ["--define-var", kv]

            value_map = {
                "theme": "--theme",
                "defaultFont": "--default-font",
                "pages": "--pages",
            }
            for key, flag in value_map.items():
                val = params.get(key)
                if val is not None and val != "":
                    cmd += [flag, str(val)]

            flag_map = {
                "blackAndWhite": "--black-and-white",
                "excludeDrawingSheet": "--exclude-drawing-sheet",
            }
            for key, flag in flag_map.items():
                if params.get(key):
                    cmd.append(flag)

            cmd.append(schematic_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }

            files = sorted(p.name for p in Path(output_dir).iterdir() if p.is_file())
            return {"success": True, "outputDir": output_dir, "files": files}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 180 seconds"}
        except Exception as e:
            logger.error(f"Error exporting schematic DXF: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_sch_hpgl(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export a schematic to HPGL via kicad-cli (`sch export hpgl`).

        Output is a directory (one plot per page). Exposes drawing-sheet
        override, exclude-drawing-sheet, default-font, page selection, pen size,
        and the origin/scale mode. schematicPath is required.
        """
        import subprocess

        logger.info("Exporting schematic HPGL via kicad-cli")
        try:
            schematic_path = params.get("schematicPath")
            output_dir = params.get("outputDir")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not Path(schematic_path).exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}
            if not output_dir:
                return {"success": False, "message": "outputDir is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_dir = str(Path(output_dir).expanduser().resolve())
            Path(output_dir).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "sch", "export", "hpgl", "--output", output_dir]

            if params.get("drawingSheet"):
                cmd += ["--drawing-sheet", params["drawingSheet"]]
            for kv in params.get("defineVar", []) or []:
                cmd += ["--define-var", kv]

            value_map = {
                "defaultFont": "--default-font",
                "pages": "--pages",
                "penSize": "--pen-size",
                "origin": "--origin",
            }
            for key, flag in value_map.items():
                val = params.get(key)
                if val is not None and val != "":
                    cmd += [flag, str(val)]

            if params.get("excludeDrawingSheet"):
                cmd.append("--exclude-drawing-sheet")

            cmd.append(schematic_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }

            files = sorted(p.name for p in Path(output_dir).iterdir() if p.is_file())
            return {"success": True, "outputDir": output_dir, "files": files}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 180 seconds"}
        except Exception as e:
            logger.error(f"Error exporting schematic HPGL: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_sch_ps(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export a schematic to PostScript via kicad-cli (`sch export ps`).

        Output is a directory (one PS per page). Exposes drawing-sheet override,
        theme, B&W, exclude-drawing-sheet, default-font, no-background-color, and
        page selection. schematicPath is required.
        """
        import subprocess

        logger.info("Exporting schematic PostScript via kicad-cli")
        try:
            schematic_path = params.get("schematicPath")
            output_dir = params.get("outputDir")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not Path(schematic_path).exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}
            if not output_dir:
                return {"success": False, "message": "outputDir is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_dir = str(Path(output_dir).expanduser().resolve())
            Path(output_dir).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "sch", "export", "ps", "--output", output_dir]

            if params.get("drawingSheet"):
                cmd += ["--drawing-sheet", params["drawingSheet"]]
            for kv in params.get("defineVar", []) or []:
                cmd += ["--define-var", kv]

            value_map = {
                "theme": "--theme",
                "defaultFont": "--default-font",
                "pages": "--pages",
            }
            for key, flag in value_map.items():
                val = params.get(key)
                if val is not None and val != "":
                    cmd += [flag, str(val)]

            flag_map = {
                "blackAndWhite": "--black-and-white",
                "excludeDrawingSheet": "--exclude-drawing-sheet",
                "noBackgroundColor": "--no-background-color",
            }
            for key, flag in flag_map.items():
                if params.get(key):
                    cmd.append(flag)

            cmd.append(schematic_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }

            files = sorted(p.name for p in Path(output_dir).iterdir() if p.is_file())
            return {"success": True, "outputDir": output_dir, "files": files}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 180 seconds"}
        except Exception as e:
            logger.error(f"Error exporting schematic PostScript: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_sch_python_bom(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export the legacy Python-BOM XML from a schematic via kicad-cli
        (`sch export python-bom`).

        Emits the legacy intermediate XML netlist consumed by the schematic
        editor's Python BOM scripts. Minimal option set (output + input only).
        schematicPath is required.
        """
        import subprocess

        logger.info("Exporting schematic Python-BOM via kicad-cli")
        try:
            schematic_path = params.get("schematicPath")
            output_path = params.get("outputPath")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not Path(schematic_path).exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}
            if not output_path:
                return {"success": False, "message": "outputPath is required"}

            kicad_cli = self._find_kicad_cli_static()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found in PATH"}

            output_path = str(Path(output_path).expanduser().resolve())
            parent = Path(output_path).parent
            if parent:
                Path(parent).mkdir(parents=True, exist_ok=True)

            cmd = [kicad_cli, "sch", "export", "python-bom", "--output", output_path]
            cmd.append(schematic_path)

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                }
            return {"success": True, "outputPath": output_path}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "kicad-cli timed out after 180 seconds"}
        except Exception as e:
            logger.error(f"Error exporting schematic Python-BOM: {e}")
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

    # ===================================================================
    # Schematic analysis tools (read-only)
    # ===================================================================

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
                reloaded = self._safe_load_board(pcb_path)
                if reloaded is not None:
                    self.board = reloaded
                    self._update_command_handlers()
                    logger.info("Reloaded board into pcbnew after SVG logo import")
                else:
                    logger.warning(
                        "Board reload after SVG import failed (non-fatal); "
                        "next mutation may operate on stale in-memory state"
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
        """Check if KiCAD UI is running.

        `processes` is the single source of truth — `running` is derived from
        its length so the two fields cannot disagree. Previously they came
        from separate detection methods (pgrep regex vs. ps-aux substring) and
        could race or use different filters, producing the confusing
        `running=True, processes=[]` state users hit after quitting KiCAD.
        """
        logger.info("Checking if KiCAD UI is running")
        try:
            manager = KiCADProcessManager()
            # `processes` is the single source of truth (from #173) so
            # `running` can't disagree with it; and if KiCAD is up, opportunistically
            # (re)connect the IPC backend (#140) so a session that started before
            # KiCAD launched can fall up from SWIG to IPC.
            processes = manager.get_process_info()
            is_running = len(processes) > 0
            if is_running:
                self._try_enable_ipc_backend()

            return {
                "success": True,
                "running": is_running,
                "processes": processes,
                "message": "KiCAD is running" if is_running else "KiCAD is not running",
                **self._backend_status(),
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
            if result.get("running"):
                self._try_enable_ipc_backend(force=True)

            return {"success": True, **result, **self._backend_status()}
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
                    reloaded = self._safe_load_board(board_path)
                    if reloaded is None:
                        return {
                            "success": False,
                            "message": (
                                "Zone fill subprocess succeeded but the board "
                                "could not be reloaded into pcbnew (SWIG state "
                                "is corrupt — restart the MCP server)"
                            ),
                            "zoneCount": zone_count,
                        }
                    self.board = reloaded
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

    def _ipc_route_arc_trace(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """IPC handler for route_arc_trace - adds copper arc with real-time UI update"""
        try:
            start = params.get("start", {})
            mid = params.get("mid", {})
            end = params.get("end", {})
            layer = params.get("layer", "F.Cu")
            width = params.get("width", 0.25)
            net = params.get("net")

            start_x = start.get("x", 0)
            start_y = start.get("y", 0)
            mid_x = mid.get("x", 0)
            mid_y = mid.get("y", 0)
            end_x = end.get("x", 0)
            end_y = end.get("y", 0)

            if not hasattr(self.ipc_board_api, "add_arc_track"):
                return {
                    "success": False,
                    "message": "IPC backend does not support arc track on this installation",
                }

            success = self.ipc_board_api.add_arc_track(
                start_x=start_x,
                start_y=start_y,
                mid_x=mid_x,
                mid_y=mid_y,
                end_x=end_x,
                end_y=end_y,
                width=width,
                layer=layer,
                net_name=net,
            )

            return {
                "success": success,
                "message": (
                    "Added arc trace (visible in KiCAD UI)"
                    if success
                    else "Failed to add arc trace"
                ),
                "arc": {
                    "start": {"x": start_x, "y": start_y, "unit": "mm"},
                    "mid": {"x": mid_x, "y": mid_y, "unit": "mm"},
                    "end": {"x": end_x, "y": end_y, "unit": "mm"},
                    "layer": layer,
                    "width": width,
                    "net": net,
                },
            }
        except Exception as e:
            logger.error(f"IPC route_arc_trace error: {e}")
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
            unit = position.get("unit", "mm") if isinstance(position, dict) else "mm"
            rotation = params.get("rotation", 0)
            layer = params.get("layer", "F.Cu")
            value = params.get("value", "")

            # Convert to mm since ipc_backend expects mm
            if unit == "inch":
                x = x * 25.4
                y = y * 25.4
            elif unit == "mil":
                x = x * 0.0254
                y = y * 0.0254

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
            unit = position.get("unit", "mm") if isinstance(position, dict) else "mm"
            rotation = params.get("rotation")

            # Convert to mm since ipc_backend.move_component expects mm
            if unit == "inch":
                x = x * 25.4
                y = y * 25.4
            elif unit == "mil":
                x = x * 0.0254
                y = y * 0.0254

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

            # If IPC didn't provide bounding boxes, enrich from SWIG backend
            if self.board and components and not components[0].get("boundingBox"):
                try:
                    swig_result = self.component_commands.get_component_list(params)
                    if swig_result.get("success"):
                        swig_map = {c["reference"]: c for c in swig_result.get("components", [])}
                        for comp in components:
                            swig_comp = swig_map.get(comp.get("reference"))
                            if swig_comp and swig_comp.get("boundingBox"):
                                comp["boundingBox"] = swig_comp["boundingBox"]
                except Exception:
                    pass

            return {"success": True, "components": components, "count": len(components)}
        except Exception as e:
            logger.error(f"IPC get_component_list error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_add_component_3d_model(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """IPC handler for add_component_3d_model — live edit of placed footprints."""
        try:
            references = params.get("reference", params.get("references"))
            if references is None:
                return {"success": False, "message": "reference (or references) is required"}
            return self.ipc_board_api.add_3d_model(
                references=references,
                model_path=params.get("modelPath", ""),
                offset=params.get("offset"),
                scale=params.get("scale"),
                rotate=params.get("rotate"),
                replace=params.get("replace", True),
            )
        except Exception as e:
            logger.error(f"IPC add_component_3d_model error: {e}")
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

    def _ipc_query_traces(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """IPC handler for query_traces - reads traces from the live KiCAD board."""
        try:
            net_name = params.get("net")
            layer_filter = params.get("layer")
            bbox = params.get("boundingBox")
            include_vias = params.get("includeVias", False)

            def point_in_bbox(point: Dict[str, Any]) -> bool:
                if not bbox:
                    return True
                unit_scale = 25.4 if bbox.get("unit", "mm") == "inch" else 1.0
                x1 = bbox.get("x1", 0) * unit_scale
                y1 = bbox.get("y1", 0) * unit_scale
                x2 = bbox.get("x2", 0) * unit_scale
                y2 = bbox.get("y2", 0) * unit_scale
                low_x, high_x = sorted((x1, x2))
                low_y, high_y = sorted((y1, y2))
                return low_x <= point.get("x", 0) <= high_x and low_y <= point.get("y", 0) <= high_y

            traces = []
            for track in self.ipc_board_api.get_tracks():
                if net_name and track.get("net") != net_name:
                    continue

                layer = self._normalize_ipc_layer_name(track.get("layer", ""))
                if layer_filter and layer != layer_filter:
                    continue

                start = track.get("start", {})
                end = track.get("end", {})
                if bbox and not (point_in_bbox(start) or point_in_bbox(end)):
                    continue

                start_with_unit = {**start, "unit": "mm"}
                end_with_unit = {**end, "unit": "mm"}
                dx = end.get("x", 0) - start.get("x", 0)
                dy = end.get("y", 0) - start.get("y", 0)
                traces.append(
                    {
                        "uuid": track.get("id", ""),
                        "net": track.get("net", ""),
                        "netCode": track.get("netCode", 0),
                        "layer": layer,
                        "width": track.get("width", 0),
                        "start": start_with_unit,
                        "end": end_with_unit,
                        "length": (dx**2 + dy**2) ** 0.5,
                    }
                )

            result = {"success": True, "traceCount": len(traces), "traces": traces}

            if include_vias:
                vias = []
                for via in self.ipc_board_api.get_vias():
                    if net_name and via.get("net") != net_name:
                        continue
                    position = via.get("position", {})
                    if bbox and not point_in_bbox(position):
                        continue
                    vias.append(
                        {
                            "uuid": via.get("id", ""),
                            "position": {**position, "unit": "mm"},
                            "net": via.get("net", ""),
                            "netCode": via.get("netCode", 0),
                            "diameter": via.get("diameter", 0),
                            "drill": via.get("drill", 0),
                        }
                    )
                result["viaCount"] = len(vias)
                result["vias"] = vias

            return result
        except Exception as e:
            logger.error(f"IPC query_traces error: {e}")
            return {"success": False, "message": str(e)}

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
            circle.radius = from_mm(diameter / 2)  # type: ignore[assignment,method-assign]
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

            # Use angle as absolute rotation (matches schema description)
            new_rotation = angle % 360

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

            # If IPC didn't provide bounding box, try SWIG backend as fallback
            if not target.get("boundingBox") and self.board:
                try:
                    swig_result = self.component_commands.get_component_properties(params)
                    if swig_result.get("success"):
                        swig_comp = swig_result.get("component", {})
                        target["boundingBox"] = swig_comp.get("boundingBox")
                        target["courtyard"] = swig_comp.get("courtyard")
                except Exception:
                    pass

            return {"success": True, "component": target}
        except Exception as e:
            logger.error(f"IPC get_component_properties error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_set_footprint_type(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """IPC handler for set_footprint_type.

        Sets the placement type (through_hole / smd / unspecified) and optional
        exclusion flags on a footprint via the kipy proto API, so the change is
        visible in the KiCAD UI without a manual reload.

        Falls back to the SWIG path if the IPC footprint lookup fails, because
        kipy's Footprint wrapper does not always expose a ``not_in_schematic``
        setter depending on the installed kipy version.
        """
        try:
            reference = params.get("reference", params.get("componentId", ""))
            fp_type = params.get("type")

            if fp_type not in ("smd", "through_hole", "unspecified"):
                return {
                    "success": False,
                    "message": "Invalid type",
                    "errorDetails": "type must be one of: smd, through_hole, unspecified",
                }

            board = self.ipc_board_api._get_board()
            footprints = board.get_footprints()

            target_fp = None
            for fp in footprints:
                if fp.reference_field and fp.reference_field.text.value == reference:
                    target_fp = fp
                    break

            if not target_fp:
                return {"success": False, "message": f"Component {reference} not found"}

            try:
                from kipy.proto.board.board_types_pb2 import FootprintMountingStyle

                style_map = {
                    "through_hole": FootprintMountingStyle.FMS_THROUGH_HOLE,
                    "smd": FootprintMountingStyle.FMS_SMD,
                    "unspecified": FootprintMountingStyle.FMS_UNSPECIFIED,
                }
                target_fp.proto.attributes.mounting_style = style_map[fp_type]

                if "exclude_from_pos_files" in params:
                    target_fp.proto.attributes.exclude_from_position_files = bool(
                        params["exclude_from_pos_files"]
                    )
                if "exclude_from_bom" in params:
                    target_fp.proto.attributes.exclude_from_bill_of_materials = bool(
                        params["exclude_from_bom"]
                    )
                if "not_in_schematic" in params:
                    target_fp.proto.attributes.not_in_schematic = bool(params["not_in_schematic"])

                commit = board.begin_commit()
                board.update_items([target_fp])
                board.push_commit(commit, f"Set footprint type for {reference}")

                return {
                    "success": True,
                    "message": f"Updated footprint type for {reference} (visible in KiCAD UI)",
                    "component": {
                        "reference": reference,
                        "type": fp_type,
                        "exclude_from_pos_files": target_fp.proto.attributes.exclude_from_position_files,  # noqa: E501
                        "exclude_from_bom": target_fp.proto.attributes.exclude_from_bill_of_materials,
                        "not_in_schematic": target_fp.proto.attributes.not_in_schematic,
                    },
                    "_backend": "ipc",
                    "_realtime": True,
                }

            except Exception as ipc_err:
                # IPC proto manipulation failed; fall back to SWIG for the write.
                logger.warning(
                    f"_ipc_set_footprint_type: IPC proto update failed ({ipc_err}), "
                    "falling back to SWIG"
                )
                if self.board:
                    result = self.component_commands.set_footprint_type(params)
                    if isinstance(result, dict):
                        result["_backend"] = "swig"
                        result["_realtime"] = False
                    return result
                raise

        except Exception as e:
            logger.error(f"IPC set_footprint_type error: {e}")
            return {"success": False, "message": str(e)}

    # =========================================================================
    # Legacy IPC command handlers (explicit ipc_* commands)

    def _handle_warmup(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Force full pcbnew/wxApp initialisation.

        On macOS the wxApp singleton is created lazily on the first
        pcbnew operation that needs it (not on ``import pcbnew``).
        That first call can take 55-65 s outside the KiCad GUI, which
        exceeds the 30 s default MCP-client tool-call timeout.

        This handler is called by the TypeScript server during startup
        (with a 120 s timeout) so the cost is paid before any user
        tools are registered with the MCP client.
        """
        import time

        start = time.monotonic()
        try:
            # pcbnew.BOARD() triggers wxApp creation on macOS.
            # GetBuildVersion() alone is too cheap — it doesn't
            # force the wxWidgets event loop to materialise.
            board = pcbnew.BOARD()
            del board
            ver = pcbnew.GetBuildVersion()
            elapsed = time.monotonic() - start
            logger.info(f"Warm-up complete: pcbnew {ver} ({elapsed:.1f}s)")
            return {"success": True, "version": ver, "elapsed_s": round(elapsed, 1)}
        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.error(f"Warm-up failed after {elapsed:.1f}s: {exc}")
            return {"success": False, "message": str(exc), "elapsed_s": round(elapsed, 1)}

    # =========================================================================

    def _handle_get_backend_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get information about the current backend"""
        if KiCADProcessManager.is_running():
            self._try_enable_ipc_backend()
        status = self._backend_status()
        ipc_backend = getattr(self, "ipc_backend", None)
        return {
            "success": True,
            **status,
            "version": ipc_backend.get_version() if ipc_backend else "N/A",
            "message": (
                "Using IPC backend with real-time UI sync"
                if status["backend"] == "ipc"
                else "Using SWIG backend (requires manual reload)"
            ),
        }

    def _handle_get_backend_state(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return the MCP/KiCad backend state and currently loaded file state."""
        if KiCADProcessManager.is_running():
            self._try_enable_ipc_backend()

        status = self._backend_status()
        board_path = self._current_board_path()
        project_path = self._current_project_file_path(board_path)
        dirty_state = self._dirty_state(board_path)
        loaded_board = board_path is not None
        loaded_project = project_path is not None

        return {
            "success": True,
            "backend": status["backend"],
            "realtime": status["realtime_sync"],
            "realtime_sync": status["realtime_sync"],
            "ipcConnected": status["ipc_connected"],
            "ipc_connected": status["ipc_connected"],
            "loadedProject": loaded_project,
            "loadedBoard": loaded_board,
            "projectPath": project_path,
            "boardPath": board_path,
            "sessionBackend": getattr(self, "session_backend", None),
            "sessionBoardPath": getattr(self, "session_board_path", None),
            "dirty": dirty_state["dirty"],
            "dirtyReason": dirty_state["dirtyReason"],
            "diskChangedExternally": dirty_state["diskChangedExternally"],
            "message": (
                f"{status['backend']} backend; "
                f"{'board loaded' if loaded_board else 'no board loaded'}"
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
        """Save board using IPC backend.

        Explicit ipc_* commands deliberately bypass the session pin (#223) —
        the caller is asking for IPC by name. In a SWIG-pinned session this
        can overwrite SWIG-side edits with the GUI's board state, so warn.
        """
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        result_note = None
        if getattr(self, "session_backend", None) == "swig":
            logger.warning(
                "ipc_save_board called in a SWIG-pinned session — this bypasses "
                "the session pin and may overwrite SWIG edits with the GUI "
                "board state (#223)"
            )
            result_note = (
                "session is pinned to swig; ipc_save_board bypassed the pin and "
                "saved the GUI's board state, which may not include SWIG-side edits"
            )

        try:
            success = self.ipc_board_api.save()
            result = {
                "success": success,
                "message": "Board saved" if success else "Failed to save board",
            }
            if result_note:
                result.setdefault("warnings", []).append(result_note)
            return result
        except Exception as e:
            logger.error(f"Error saving board via IPC: {e}")
            return {"success": False, "message": str(e)}

    # JLCPCB API handlers

    def _handle_download_jlcpcb_database(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Download the JLCPCB parts catalog from a prebuilt source (issue #199).

        Layered strategy (see commands.jlcpcb_downloader): CDFER single-file
        SQLite (primary, no 7z) -> yaqwsx split-7z (fallback) -> official JLCPCB
        API (optional, if credentials set). Replaces the broken JLCSearch
        offset-pagination download.
        """
        from commands import jlcpcb_downloader

        try:
            force = params.get("force", False)
            prefer_source = params.get("source")  # optional: cdfer|yaqwsx|official

            stats = self.jlcpcb_parts.get_database_stats()
            if stats["total_parts"] > 0 and not force:
                return {
                    "success": False,
                    "message": "Database already exists. Use force=true to re-download.",
                    "stats": stats,
                }

            # The prebuilt paths recreate jlcpcb_parts.db on disk, so the open
            # manager connection must be released first (Windows file locking),
            # then reopened on the freshly written database.
            self.jlcpcb_parts.close()

            result = jlcpcb_downloader.download_database(
                force=force,
                prefer_source=prefer_source,
                progress=lambda msg: logger.info(msg),
            )

            # Reopen the manager on the new database regardless of outcome.
            self.jlcpcb_parts = JLCPCBPartsManager()

            if not result.get("success"):
                return result

            # Refresh counts from the reopened manager (authoritative).
            stats = self.jlcpcb_parts.get_database_stats()
            result["total_parts"] = stats["total_parts"]
            result["basic_parts"] = stats["basic_parts"]
            result["extended_parts"] = stats["extended_parts"]
            result["db_path"] = stats["db_path"]
            return result

        except Exception as e:
            logger.error(f"Error downloading JLCPCB database: {e}", exc_info=True)
            # Best-effort: ensure the manager is usable after a failure.
            try:
                self.jlcpcb_parts = JLCPCBPartsManager()
            except Exception:
                pass
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
    # Signal to the TypeScript server that the stdin loop is live.
    _write_response(_response_fd, {"type": "ready"})

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
