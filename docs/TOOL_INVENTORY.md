# KiCAD MCP Server - Tool Inventory

**Total Tools: 59**
**Token Impact: ~40K+ tokens before any user interaction**

## Current Tool Categories

### Project Management (4 tools)
- `create_project` - Create a new KiCAD project
- `open_project` - Open an existing KiCAD project
- `save_project` - Save the current KiCAD project
- `get_project_info` - Get information about the current project

### Board Management (12 tools)
- `set_board_size` - Set the board dimensions
- `add_layer` - Add a new layer to the board
- `set_active_layer` - Set the active working layer
- `get_board_info` - Get board information
- `get_layer_list` - Get list of all layers
- `add_board_outline` - Add board outline shape (rectangle/circle/polygon)
- `add_mounting_hole` - Add mounting hole to the board
- `add_board_text` - Add text to the board
- `add_zone` - Add copper zone/pour
- `get_board_extents` - Get board bounding box
- `get_board_2d_view` - Get 2D visualization of board

### Component Management (10 tools)
- `place_component` - Place a component on the board
- `move_component` - Move a component to new position
- `rotate_component` - Rotate a component
- `delete_component` - Delete a component
- `edit_component` - Edit component properties
- `find_component` - Find component by reference or value
- `get_component_properties` - Get component properties
- `add_component_annotation` - Add annotation to component
- `group_components` - Group multiple components
- `replace_component` - Replace component with another

### Routing (4 tools)
- `add_net` - Create a new net
- `route_trace` - Route a trace between two points
- `add_via` - Add a via
- `add_copper_pour` - Add copper pour (ground/power plane)

### Design Rules & DRC (9 tools)
- `set_design_rules` - Configure design rules
- `get_design_rules` - Get current design rules
- `run_drc` - Run design rule check
- `add_net_class` - Add a net class with specific rules
- `assign_net_to_class` - Assign net to a net class
- `set_layer_constraints` - Set layer-specific constraints
- `check_clearance` - Check clearance between items
- `get_drc_violations` - Get DRC violation list

### Export (8 tools)
- `export_gerber` - Export Gerber files for fabrication
- `export_pdf` - Export PDF documentation
- `export_svg` - Export SVG graphics
- `export_3d` - Export 3D model (STEP/STL/VRML/OBJ)
- `export_bom` - Export bill of materials
- `export_netlist` - Export netlist
- `export_position_file` - Export component position file
- `export_vrml` - Export VRML 3D model

### Library (4 tools)
- `list_libraries` - List available footprint libraries
- `search_footprints` - Search for footprints across libraries
- `list_library_footprints` - List footprints in specific library
- `get_footprint_info` - Get detailed footprint information

### Schematic (9 tools)
- `create_schematic` - Create a new schematic
- `add_schematic_component` - Add component to schematic
- `add_wire` - Add wire connection in schematic
- `add_schematic_connection` - Connect component pins
- `add_schematic_net_label` - Add net label
- `connect_to_net` - Connect pin to named net
- `get_net_connections` - Get all connections for a net
- `generate_netlist` - Generate netlist from schematic

### UI Management (2 tools)
- `check_kicad_ui` - Check if KiCAD UI is running
- `launch_kicad_ui` - Launch KiCAD UI

## Router Implementation Plan

### Direct Tools (Always Visible) - 12 tools
High-frequency operations used in 80%+ of sessions:
- `create_project`
- `open_project`
- `save_project`
- `get_project_info`
- `place_component`
- `move_component`
- `add_net`
- `route_trace`
- `get_board_info`
- `set_board_size`
- `add_board_outline`
- `check_kicad_ui`

### Router Tools - 4 tools
Discovery and execution:
- `list_tool_categories`
- `get_category_tools`
- `execute_tool`
- `search_tools`

### Routed Tools (Hidden) - 47 tools
Organized into categories for discovery.

## Expected Impact
**Before Router**: 59 tools = ~40K+ tokens
**After Router**: 16 tools (12 direct + 4 router) = ~12K tokens
**Savings**: ~28K tokens (70% reduction)
