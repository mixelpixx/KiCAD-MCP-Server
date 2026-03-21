# KiCAD MCP Server Architecture

This document describes the system architecture for contributors who want to understand, modify, or extend the server.

---

## System Overview

```
AI Assistant (Claude, etc.)
        |
        | MCP Protocol (JSON-RPC 2.0 over STDIO)
        v
  TypeScript MCP Server (src/)
        |
        | Spawn Python subprocess, pass JSON commands
        v
  Python KiCAD Interface (python/)
        |
        | pcbnew SWIG API or KiCAD IPC API
        v
    KiCAD 9.0+
```

The server has two layers:

1. **TypeScript layer** -- implements the MCP protocol, registers tools with schemas, validates input, manages the Python subprocess
2. **Python layer** -- interfaces with KiCAD's pcbnew API (SWIG bindings) or IPC API for actual PCB/schematic operations

---

## Directory Structure

```
KiCAD-MCP-Server/
  src/                        # TypeScript MCP server
    server.ts                 # Main server, tool registration, Python subprocess
    logger.ts                 # Logging configuration
    tools/                    # Tool definitions (one file per category)
      registry.ts             # Tool category definitions and lookup
      router.ts               # Router tools (list/search/execute)
      project.ts              # Project management tools
      board.ts                # Board operations tools
      component.ts            # Component tools
      routing.ts              # Routing tools
      design-rules.ts         # DRC tools
      export.ts               # Export tools
      schematic.ts            # Schematic tools
      library.ts              # Footprint library tools
      library-symbol.ts       # Symbol library tools
      footprint.ts            # Footprint creator tools
      symbol-creator.ts       # Symbol creator tools
      datasheet.ts            # Datasheet tools
      jlcpcb-api.ts           # JLCPCB integration tools
      freerouting.ts          # Autorouter tools
      ui.ts                   # UI management tools
    resources/                # MCP resource definitions
    prompts/                  # MCP prompt templates
    utils/                    # Utility functions

  python/                     # Python KiCAD interface
    kicad_interface.py        # Main entry point, command router
    commands/                 # Command implementations
      project.py              # Project operations
      board.py                # Board manipulation
      component.py            # PCB component operations
      component_schematic.py  # Schematic component operations
      connection_schematic.py # Schematic wiring and connections
      schematic.py            # Schematic file management
      routing.py              # Trace routing
      design_rules.py         # DRC operations
      export.py               # File export
      library.py              # Footprint library access
      library_symbol.py       # Symbol library access
      footprint.py            # Custom footprint creation
      symbol_creator.py       # Custom symbol creation
      datasheet_manager.py    # Datasheet enrichment
      jlcpcb.py               # JLCPCB API client
      jlcsearch.py            # JLCSearch public API client
      jlcpcb_parts.py         # JLCPCB parts database
      freerouting.py          # Freerouting autorouter
      svg_import.py           # SVG to PCB polygon conversion
      dynamic_symbol_loader.py # Dynamic symbol injection
      wire_manager.py         # S-expression wire creation
      pin_locator.py          # Pin position discovery
      layers.py               # Layer utilities
      outline.py              # Board outline utilities
      size.py                 # Size/dimension utilities
      view.py                 # Board rendering utilities
    kicad_api/                # Backend abstraction
      base.py                 # Abstract base class
      factory.py              # Backend auto-detection
      swig_backend.py         # pcbnew SWIG API backend
      ipc_backend.py          # KiCAD 9.0 IPC API backend
    schemas/                  # JSON Schema definitions
      tool_schemas.py         # Tool parameter schemas
    resources/                # Resource handlers
    templates/                # Schematic/project templates
    tests/                    # Python test suite
    utils/                    # Platform detection, helpers

  docs/                       # Documentation
  config/                     # Configuration examples
```

---

## TypeScript Layer

### Server Startup (`src/server.ts`)

1. Creates an MCP server instance
2. Registers all tools from each tool file (registerProjectTools, registerBoardTools, etc.)
3. Registers resources and prompts
4. Starts the STDIO transport for MCP communication
5. On first tool call, spawns the Python subprocess

### Tool Registration

Each tool file exports a `register*Tools(server, callKicadScript)` function that:
- Defines tool name, description, and Zod schema for parameters
- Registers a handler that calls `callKicadScript(command, args)`

Example from `src/tools/project.ts`:
```typescript
server.tool(
  "create_project",
  "Create a new KiCAD project",
  { name: z.string(), path: z.string() },
  async (args) => {
    const result = await callKicadScript("create_project", args);
    return { content: [{ type: "text", text: JSON.stringify(result) }] };
  }
);
```

### Tool Router (`src/tools/router.ts` and `src/tools/registry.ts`)

The router pattern reduces AI context usage:
- `registry.ts` defines tool categories and which tools are "direct" (always visible) vs "routed" (discoverable)
- `router.ts` provides 4 meta-tools: `list_tool_categories`, `get_category_tools`, `search_tools`, `execute_tool`
- Routed tools are not registered as individual MCP tools -- they are invoked through `execute_tool`

### Python Subprocess Communication

`callKicadScript(command, args)` in `server.ts`:
1. Spawns `python3 python/kicad_interface.py` (if not already running)
2. Sends a JSON message: `{"command": "...", "params": {...}}`
3. Reads the JSON response
4. Returns the result to the MCP tool handler

---

## Python Layer

### Main Entry Point (`python/kicad_interface.py`)

- Reads JSON commands from stdin
- Routes commands to the appropriate handler
- Manages the pcbnew board object lifecycle
- Handles backend selection (SWIG vs IPC)
- Auto-saves after board-modifying operations

### Command Routing

Commands are routed by name to handler methods. The mapping is defined in `kicad_interface.py`. Each handler:
1. Receives a params dict
2. Calls the appropriate command class method
3. Returns a result dict with `success`, `message`, and any additional data

### Backend System (`python/kicad_api/`)

Two backends for interacting with KiCAD:

**SWIG Backend** (default):
- Direct Python bindings to KiCAD's C++ API via SWIG
- Operates on files -- loads .kicad_pcb, modifies in memory, saves back
- Works without KiCAD running
- Requires manual UI reload to see changes

**IPC Backend** (experimental):
- Communicates with running KiCAD via IPC API socket
- Changes appear in the UI immediately
- Requires KiCAD 9.0+ running with IPC enabled
- Falls back to SWIG when unavailable

`factory.py` auto-detects which backend to use.

### Schematic System

Schematic manipulation uses a different stack than PCB operations:
- **kicad-skip** library for reading/modifying schematic files
- **S-expression parsing** for direct file manipulation (wires, symbols)
- **DynamicSymbolLoader** for injecting any KiCad symbol into a schematic
- **WireManager** for creating wires via S-expression injection
- **PinLocator** for discovering pin positions with rotation support

---

## Adding a New Tool

### Step 1: Define the TypeScript Schema

Create or edit a file in `src/tools/`. Register the tool with `server.tool()`:

```typescript
server.tool(
  "my_new_tool",
  "Description of what the tool does",
  {
    param1: z.string().describe("Description of param1"),
    param2: z.number().optional().describe("Optional param2"),
  },
  async (args) => {
    const result = await callKicadScript("my_new_tool", args);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);
```

### Step 2: Add to Registry (if routed)

If the tool should be discoverable via the router (not always visible), add it to a category in `src/tools/registry.ts`:

```typescript
{
  name: "category_name",
  tools: ["existing_tool", "my_new_tool"]
}
```

If the tool should always be visible, add it to `directToolNames` instead.

### Step 3: Import in server.ts

Import and call the registration function in `src/server.ts`:

```typescript
import { registerMyTools } from "./tools/my-tools.js";
registerMyTools(server, callKicadScript);
```

### Step 4: Implement the Python Handler

Add a handler in `python/kicad_interface.py` or create a new command module in `python/commands/`:

```python
def handle_my_new_tool(self, params):
    # Implementation using pcbnew API
    return {"success": True, "message": "Done", "data": result}
```

Route the command in the main handler:

```python
elif command == "my_new_tool":
    return self.handle_my_new_tool(params)
```

### Step 5: Build and Test

```bash
npm run build          # Compile TypeScript
npm run test:py        # Run Python tests
```

---

## Testing

### Python Tests

Located in `python/tests/`. Run with:
```bash
pytest python/tests/ -v
```

Key test files:
- `test_schematic_tools.py` -- schematic tool tests
- `test_freerouting.py` -- autorouter tests
- `test_delete_schematic_component.py` -- component deletion tests
- `test_schematic_component_fields.py` -- field inspection tests
- `test_platform_helper.py` -- platform detection tests

### Manual Testing

1. Build the server: `npm run build`
2. Configure in Claude Desktop or Claude Code
3. Test tools interactively through your MCP client

---

## Key Design Decisions

- **TypeScript + Python split**: TypeScript handles MCP protocol (well-supported SDK), Python handles KiCAD (only available API)
- **Router pattern**: Reduces AI context from ~80K tokens (122 tools) to manageable size
- **Auto-save**: Every board-modifying SWIG operation auto-saves to prevent data loss
- **Dynamic symbol loading**: Works around kicad-skip's inability to create symbols from scratch
- **S-expression wire injection**: Works around kicad-skip's inability to create wires

---

## Source Files Reference

| File | Purpose |
|------|---------|
| `src/server.ts` | MCP server, subprocess management |
| `src/tools/registry.ts` | Tool categories and organization |
| `src/tools/router.ts` | Router meta-tools |
| `python/kicad_interface.py` | Python entry point, command routing |
| `python/kicad_api/factory.py` | Backend selection |
| `python/commands/dynamic_symbol_loader.py` | Symbol injection system |
| `python/commands/wire_manager.py` | Wire creation engine |
| `python/commands/pin_locator.py` | Pin position discovery |
