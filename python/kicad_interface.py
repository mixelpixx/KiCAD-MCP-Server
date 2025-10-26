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

# Configure logging
log_dir = os.path.join(os.path.expanduser('~'), '.kicad-mcp', 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'kicad_interface.log')

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger('kicad_interface')

# Log Python environment details
logger.info(f"Python version: {sys.version}")
logger.info(f"Python executable: {sys.executable}")
logger.info(f"Python path: {sys.path}")

# Add KiCAD Python paths
kicad_paths = [
    os.path.join(os.path.dirname(sys.executable), 'Lib', 'site-packages'),
    os.path.dirname(sys.executable)
]
for path in kicad_paths:
    if path not in sys.path:
        logger.info(f"Adding KiCAD path: {path}")
        sys.path.append(path)

# Import KiCAD's Python API
try:
    logger.info("Attempting to import pcbnew module...")
    import pcbnew  # type: ignore
    logger.info(f"Successfully imported pcbnew module from: {pcbnew.__file__}")
    logger.info(f"pcbnew version: {pcbnew.GetBuildVersion()}")
except ImportError as e:
    logger.error(f"Failed to import pcbnew module: {e}")
    logger.error(f"Current sys.path: {sys.path}")
    error_response = {
        "success": False,
        "message": "Failed to import pcbnew module",
        "errorDetails": f"Error: {str(e)}\nPython path: {sys.path}"
    }
    print(json.dumps(error_response))
    sys.exit(1)
except Exception as e:
    logger.error(f"Unexpected error importing pcbnew: {e}")
    logger.error(traceback.format_exc())
    error_response = {
        "success": False,
        "message": "Error importing pcbnew module",
        "errorDetails": str(e)
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
    from commands.library_schematic import LibraryManager
    logger.info("Successfully imported all command handlers")
except ImportError as e:
    logger.error(f"Failed to import command handlers: {e}")
    error_response = {
        "success": False,
        "message": "Failed to import command handlers",
        "errorDetails": str(e)
    }
    print(json.dumps(error_response))
    sys.exit(1)

class KiCADInterface:
    """Main interface class to handle KiCAD operations"""
    
    def __init__(self):
        """Initialize the interface and command handlers"""
        self.board = None
        self.project_filename = None
        
        logger.info("Initializing command handlers...")
        
        # Initialize command handlers
        self.project_commands = ProjectCommands(self.board)
        self.board_commands = BoardCommands(self.board)
        self.component_commands = ComponentCommands(self.board)
        self.routing_commands = RoutingCommands(self.board)
        self.design_rule_commands = DesignRuleCommands(self.board)
        self.export_commands = ExportCommands(self.board)
        
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
            "add_board_outline": self.board_commands.add_board_outline,
            "add_mounting_hole": self.board_commands.add_mounting_hole,
            "add_text": self.board_commands.add_text,
            
            # Component commands
            "place_component": self.component_commands.place_component,
            "move_component": self.component_commands.move_component,
            "rotate_component": self.component_commands.rotate_component,
            "delete_component": self.component_commands.delete_component,
            "edit_component": self.component_commands.edit_component,
            "get_component_properties": self.component_commands.get_component_properties,
            "get_component_list": self.component_commands.get_component_list,
            "place_component_array": self.component_commands.place_component_array,
            "align_components": self.component_commands.align_components,
            "duplicate_component": self.component_commands.duplicate_component,
            
            # Routing commands
            "add_net": self.routing_commands.add_net,
            "route_trace": self.routing_commands.route_trace,
            "add_via": self.routing_commands.add_via,
            "delete_trace": self.routing_commands.delete_trace,
            "get_nets_list": self.routing_commands.get_nets_list,
            "create_netclass": self.routing_commands.create_netclass,
            "add_copper_pour": self.routing_commands.add_copper_pour,
            "route_differential_pair": self.routing_commands.route_differential_pair,
            
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
            
            # Schematic commands
            "create_schematic": self._handle_create_schematic,
            "load_schematic": self._handle_load_schematic,
            "add_schematic_component": self._handle_add_schematic_component,
            "add_schematic_wire": self._handle_add_schematic_wire,
            "list_schematic_libraries": self._handle_list_schematic_libraries,
            "export_schematic_pdf": self._handle_export_schematic_pdf
        }
        
        logger.info("KiCAD interface initialized")

    def handle_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route command to appropriate handler"""
        logger.info(f"Handling command: {command}")
        logger.debug(f"Command parameters: {params}")
        
        try:
            # Get the handler for the command
            handler = self.command_routes.get(command)
            
            if handler:
                # Execute the command
                result = handler(params)
                logger.debug(f"Command result: {result}")
                
                # Update board reference if command was successful
                if result.get("success", False):
                    if command == "create_project" or command == "open_project":
                        logger.info("Updating board reference...")
                        self.board = pcbnew.GetBoard()
                        self._update_command_handlers()
                
                return result
            else:
                logger.error(f"Unknown command: {command}")
                return {
                    "success": False,
                    "message": f"Unknown command: {command}",
                    "errorDetails": "The specified command is not supported"
                }
                
        except Exception as e:
            # Get the full traceback
            traceback_str = traceback.format_exc()
            logger.error(f"Error handling command {command}: {str(e)}\n{traceback_str}")
            return {
                "success": False,
                "message": f"Error handling command: {command}",
                "errorDetails": f"{str(e)}\n{traceback_str}"
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
            project_name = params.get("projectName")
            path = params.get("path", ".")
            metadata = params.get("metadata", {})
            
            if not project_name:
                return {"success": False, "message": "Project name is required"}
            
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
        """Add a component to a schematic"""
        logger.info("Adding component to schematic")
        try:
            schematic_path = params.get("schematicPath")
            component = params.get("component", {})
            
            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not component:
                return {"success": False, "message": "Component definition is required"}
            
            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}
            
            component_obj = ComponentManager.add_component(schematic, component)
            success = component_obj is not None
            
            if success:
                SchematicManager.save_schematic(schematic, schematic_path)
                return {"success": True}
            else:
                return {"success": False, "message": "Failed to add component"}
        except Exception as e:
            logger.error(f"Error adding component to schematic: {str(e)}")
            return {"success": False, "message": str(e)}
    
    def _handle_add_schematic_wire(self, params):
        """Add a wire to a schematic"""
        logger.info("Adding wire to schematic")
        try:
            schematic_path = params.get("schematicPath")
            start_point = params.get("startPoint")
            end_point = params.get("endPoint")
            
            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not start_point or not end_point:
                return {"success": False, "message": "Start and end points are required"}
            
            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}
            
            wire = ConnectionManager.add_wire(schematic, start_point, end_point)
            success = wire is not None
            
            if success:
                SchematicManager.save_schematic(schematic, schematic_path)
                return {"success": True}
            else:
                return {"success": False, "message": "Failed to add wire"}
        except Exception as e:
            logger.error(f"Error adding wire to schematic: {str(e)}")
            return {"success": False, "message": str(e)}
    
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
                ["kicad-cli", "sch", "export", "pdf", "--output", output_path, schematic_path],
                capture_output=True, 
                text=True
            )
            
            success = result.returncode == 0
            message = result.stderr if not success else ""
            
            return {"success": success, "message": message}
        except Exception as e:
            logger.error(f"Error exporting schematic to PDF: {str(e)}")
            return {"success": False, "message": str(e)}

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
                command = command_data.get("command")
                params = command_data.get("params", {})
                
                if not command:
                    logger.error("Missing command field")
                    response = {
                        "success": False,
                        "message": "Missing command",
                        "errorDetails": "The command field is required"
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
                    "errorDetails": str(e)
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
