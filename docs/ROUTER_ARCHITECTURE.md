# Router Architecture Design

## Overview

This document describes the router pattern implementation for the KiCAD MCP Server. The router reduces context window consumption from ~40K tokens (59 tools) to ~12K tokens (16 visible tools).

## Architecture Layers

```
┌─────────────────────────────────────────────────────────────┐
│                     MCP Client (Claude)                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      KiCAD MCP Server                        │
│  ┌─────────────────────────────────────────────────────────┐│
│  │           DIRECT TOOLS (Always Visible - 12)            ││
│  │  • create_project    • open_project    • save_project   ││
│  │  • get_project_info  • place_component • move_component ││
│  │  • add_net           • route_trace     • get_board_info ││
│  │  • set_board_size    • add_board_outline • check_kicad_ui││
│  └─────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────┐│
│  │               ROUTER TOOLS (Discovery - 4)              ││
│  │  • list_tool_categories   • get_category_tools          ││
│  │  • execute_tool           • search_tools                ││
│  └─────────────────────────────────────────────────────────┘│
│                              │                               │
│                              ▼                               │
│  ┌─────────────────────────────────────────────────────────┐│
│  │            ROUTED TOOLS (Hidden - 47)                   ││
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   ││
│  │  │  board   │ │component │ │  export  │ │   drc    │   ││
│  │  │(9 tools) │ │(8 tools) │ │(8 tools) │ │(9 tools) │   ││
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘   ││
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐                ││
│  │  │schematic │ │ library  │ │ routing  │ ┌──────────┐   ││
│  │  │(9 tools) │ │(4 tools) │ │(3 tools) │ │ui (1 tool)│   ││
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘   ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

## Tool Categories

### Direct Tools (12 tools - always visible)

These cover the primary workflow (80%+ of use cases):

1. **Project Lifecycle** (4):
   - `create_project` - Create new KiCAD project
   - `open_project` - Open existing project
   - `save_project` - Save current project
   - `get_project_info` - Get project information

2. **Core PCB Operations** (6):
   - `place_component` - Place component on board
   - `move_component` - Move component to new position
   - `add_net` - Create a new net
   - `route_trace` - Route trace between points
   - `get_board_info` - Get board information
   - `set_board_size` - Set board dimensions

3. **Board Setup** (1):
   - `add_board_outline` - Add board outline

4. **UI Management** (1):
   - `check_kicad_ui` - Check if KiCAD UI is running

### Routed Categories (7 categories, 47 tools)

#### 1. `board` - Board Configuration & Layout (9 tools)
Setup and configuration operations.

**Tools:**
- `add_layer` - Add PCB layer
- `set_active_layer` - Set active layer
- `get_layer_list` - List all layers
- `add_mounting_hole` - Add mounting hole
- `add_board_text` - Add text to board
- `add_zone` - Add copper zone/pour
- `get_board_extents` - Get board boundaries
- `get_board_2d_view` - Get 2D visualization
- `launch_kicad_ui` - Launch KiCAD UI

#### 2. `component` - Advanced Component Operations (8 tools)
Beyond basic placement.

**Tools:**
- `rotate_component` - Rotate component
- `delete_component` - Delete component
- `edit_component` - Edit component properties
- `find_component` - Find component by reference/value
- `get_component_properties` - Get component properties
- `add_component_annotation` - Add component annotation
- `group_components` - Group components together
- `replace_component` - Replace component with another

#### 3. `export` - File Export & Manufacturing (8 tools)
Generate output files for fabrication and documentation.

**Tools:**
- `export_gerber` - Export Gerber files
- `export_pdf` - Export PDF
- `export_svg` - Export SVG
- `export_3d` - Export 3D model (STEP/STL/VRML/OBJ)
- `export_bom` - Export bill of materials
- `export_netlist` - Export netlist
- `export_position_file` - Export component positions
- `export_vrml` - Export VRML 3D model

#### 4. `drc` - Design Rules & Validation (9 tools)
Design rule checking and electrical validation.

**Tools:**
- `set_design_rules` - Configure design rules
- `get_design_rules` - Get current rules
- `run_drc` - Run design rule check
- `add_net_class` - Add net class
- `assign_net_to_class` - Assign net to class
- `set_layer_constraints` - Set layer constraints
- `check_clearance` - Check clearance between items
- `get_drc_violations` - Get DRC violations

#### 5. `schematic` - Schematic Operations (9 tools)
Schematic editor operations.

**Tools:**
- `create_schematic` - Create new schematic
- `add_schematic_component` - Add component to schematic
- `add_wire` - Add wire connection
- `add_schematic_connection` - Connect component pins
- `add_schematic_net_label` - Add net label
- `connect_to_net` - Connect pin to net
- `get_net_connections` - Get net connections
- `generate_netlist` - Generate netlist

#### 6. `library` - Footprint Library Access (4 tools)
Search and browse footprint libraries.

**Tools:**
- `list_libraries` - List available libraries
- `search_footprints` - Search footprints
- `list_library_footprints` - List library footprints
- `get_footprint_info` - Get footprint details

#### 7. `routing` - Advanced Routing (3 tools)
Advanced routing operations beyond basic trace routing.

**Tools:**
- `add_via` - Add via
- `add_copper_pour` - Add copper pour

**Note:** `add_net` and `route_trace` are direct tools as they're core operations.

## Router Tools

### 1. `list_tool_categories`
**Description:** List all available tool categories with descriptions and tool counts.

**Parameters:** None

**Returns:**
```json
{
  "total_categories": 7,
  "total_tools": 47,
  "categories": [
    {
      "name": "board",
      "description": "Board configuration: layers, mounting holes, zones, visualization",
      "tool_count": 9
    },
    // ... more categories
  ]
}
```

### 2. `get_category_tools`
**Description:** Get detailed information about all tools in a specific category.

**Parameters:**
- `category` (string) - Category name from `list_tool_categories`

**Returns:**
```json
{
  "category": "export",
  "description": "File export for fabrication and documentation: Gerber, PDF, BOM, 3D models",
  "tools": [
    {
      "name": "export_gerber",
      "description": "Export Gerber files for PCB fabrication",
      "parameters": { /* zod schema */ }
    },
    // ... more tools
  ]
}
```

### 3. `execute_tool`
**Description:** Execute a tool from any category.

**Parameters:**
- `tool_name` (string) - Tool name from `get_category_tools`
- `params` (object, optional) - Tool parameters

**Returns:** Tool execution result

### 4. `search_tools`
**Description:** Search for tools by keyword across all categories.

**Parameters:**
- `query` (string) - Search term (e.g., "gerber", "zone", "export")

**Returns:**
```json
{
  "query": "export",
  "count": 8,
  "matches": [
    {
      "category": "export",
      "tool": "export_gerber",
      "description": "Export Gerber files for PCB fabrication"
    },
    // ... more matches
  ]
}
```

## Implementation Files

### New Files to Create

1. **`src/tools/registry.ts`**
   - Tool category definitions
   - Tool metadata storage
   - Lookup maps (by name, by category)
   - Search functionality

2. **`src/tools/router.ts`**
   - Router tool implementations
   - `list_tool_categories` handler
   - `get_category_tools` handler
   - `execute_tool` handler
   - `search_tools` handler

3. **`src/tools/direct.ts`**
   - Export direct tool definitions
   - Keep existing tool implementations but organized

### Modified Files

1. **`src/server.ts`** or **`src/kicad-server.ts`**
   - Register only direct tools + router tools
   - Remove registration of routed tools
   - Tools still callable via `execute_tool`

## Migration Strategy

### Phase 1: Create Infrastructure
1. Create `registry.ts` with all tool definitions
2. Create `router.ts` with router tools
3. Create `direct.ts` with direct tool list

### Phase 2: Update Server
1. Modify server registration to use direct + router only
2. Keep all existing tool handlers intact
3. Route through `execute_tool`

### Phase 3: Testing
1. Test direct tools work as before
2. Test router tools (list/get/execute/search)
3. Test routed tools via `execute_tool`

### Phase 4: Optimization (Optional)
1. Add caching for tool lookups
2. Add tool usage analytics
3. Implement intelligent tool suggestions

## Benefits

1. **Context Efficiency**: 70% reduction in tokens (~28K saved)
2. **Better Organization**: Tools grouped by function
3. **Discoverability**: Easy to find the right tool
4. **Scalability**: Can add unlimited tools without bloating context
5. **Backwards Compatible**: Existing Python commands still work

## Usage Examples

### Example 1: User Wants to Export Gerbers

```
User: "Export gerbers for this board"

Claude's workflow:
1. Sees "export" keyword
2. Calls search_tools({ query: "gerber" })
   → Returns: { category: "export", tool: "export_gerber", ... }
3. Calls execute_tool({
     tool_name: "export_gerber",
     params: { outputDir: "./gerbers" }
   })
   → Returns: { success: true, files: [...] }

Claude: "I've exported the Gerber files to ./gerbers/"
```

### Example 2: User Wants to Place Component

```
User: "Add a 0805 resistor at position 10,20"

Claude's workflow:
1. Sees place_component in direct tools
2. Calls place_component({
     componentId: "R_0805",
     position: { x: 10, y: 20, unit: "mm" }
   })
   → Returns: { success: true, reference: "R1" }

Claude: "Added R1 (0805 resistor) at position (10, 20) mm"
```

### Example 3: User Wants Unknown Operation

```
User: "Check the board for design rule violations"

Claude's workflow:
1. Uncertain which tool to use
2. Calls search_tools({ query: "design rule violations" })
   → Returns: { category: "drc", tool: "run_drc", ...}
3. Calls get_category_tools({ category: "drc" })
   → Returns full DRC category tools with parameters
4. Calls execute_tool({
     tool_name: "run_drc",
     params: {}
   })
   → Returns: DRC results

Claude: "I ran the design rule check. Found 3 violations: ..."
```

## Success Metrics

- ✅ Token usage: ~12K (vs 40K before)
- ✅ Tool discovery time: <2 calls (search → execute)
- ✅ User experience: Unchanged (seamless)
- ✅ Maintainability: Improved (organized categories)
- ✅ Scalability: Can add 100+ more tools easily
