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
      router.ts               # Discovery tools (list categories, search)
      toolboxes.ts            # Toolbox mode: which tools a client sees
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
  },
);
```

### Tool Discovery (`src/tools/router.ts` and `src/tools/registry.ts`)

Every tool is registered individually with `server.tool()`, so any MCP client can
call any tool by name. The registry exists to help an assistant _find_ a tool it
does not already know about:

- `registry.ts` defines the categories, the small "essentials" (core) list that
  `search_tools` ranks first, and the discovery tools. It indexes every
  registered tool; `tests-ts/registry-completeness.test.ts` fails CI for a tool
  that is registered but in no category.
- `router.ts` provides `list_tool_categories`, `get_category_tools` and
  `search_tools`.
- Nothing is called through a dispatcher. An earlier design routed calls through
  an `execute_tool` meta-tool; that was rolled back because clients could not
  see the real tool schemas. See `docs/ROUTER_ARCHITECTURE.md` for that history.

### Toolboxes (`src/tools/toolboxes.ts`)

With `KICAD_MCP_TOOLBOXES` set, each category is a toolbox, and a client sees
only the core tools, `search_tools` and the toolbox controls (`list_toolboxes`,
`open_toolbox`, `close_toolbox`) plus the tools of open toolboxes. Unset, every
tool is visible.

- `ToolboxManager` wraps `server.tool()` and `server.registerTool()` before any
  tool is registered and keeps each returned `RegisteredTool`.
- Visibility is the SDK's own `enabled` flag, which it applies to `tools/list`
  and `tools/call`. Opening or closing a toolbox flips the flags and sends one
  `notifications/tools/list_changed`, so the client re-reads its list and gets
  the real schemas.
- Clients differ in when they act on that notification: Claude Code and VS Code
  Copilot from the user's next message, Claude Desktop only after a restart.
  Toolboxes named in the setting are open from the start in every client.

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
  },
);
```

### Step 2: Add to Registry (if routed)

Every tool must be in the registry: add it to the category it belongs to in `src/tools/registry.ts`, which also makes it part of that toolbox (or to `directToolNames` if it must always be visible, even in toolbox mode). `tests-ts/registry-completeness.test.ts` fails for a tool that is in neither:

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
- **Keyword discovery instead of routing**: every tool stays individually callable, and the registry indexes all of them so `search_tools` can find one without the client reading every schema
- **Toolboxes as real tools**: toolbox mode hides and shows registered tools through the SDK's `enabled` flag and `tools/list_changed`, rather than calling hidden tools through a dispatcher, so the model always sees a tool's real schema
- **Auto-save**: Every board-modifying SWIG operation auto-saves to prevent data loss
- **Dynamic symbol loading**: Works around kicad-skip's inability to create symbols from scratch
- **S-expression wire injection**: Works around kicad-skip's inability to create wires

---

## Source Files Reference

| File                                       | Purpose                             |
| ------------------------------------------ | ----------------------------------- |
| `src/server.ts`                            | MCP server, subprocess management   |
| `src/tools/registry.ts`                    | Tool categories and organization    |
| `src/tools/router.ts`                      | Discovery tools                     |
| `src/tools/toolboxes.ts`                   | Toolbox mode and its controls       |
| `python/kicad_interface.py`                | Python entry point, command routing |
| `python/kicad_api/factory.py`              | Backend selection                   |
| `python/commands/dynamic_symbol_loader.py` | Symbol injection system             |
| `python/commands/wire_manager.py`          | Wire creation engine                |
| `python/commands/pin_locator.py`           | Pin position discovery              |
