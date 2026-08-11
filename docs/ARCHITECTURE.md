# KiCAD MCP Server Architecture

This document describes the system architecture for contributors who want to understand, modify, or extend the server.

---

## System Overview

```
AI Assistant (Claude, etc.)
        |
        | MCP 2026-07-28 or legacy 2025 over stdio
        v
  TypeScript MCP Server (src/)
        |
        | Correlated private JSON command envelopes
        v
  Python KiCAD Interface (python/)
        |
        | pcbnew SWIG API or KiCAD IPC API
        v
    KiCAD 9.0+
```

The server has two layers:

1. **TypeScript layer** -- implements MCP with SDK v2, registers and validates the first-class protocol surface, and manages the Python subprocess
2. **Python layer** -- executes private KiCad commands through pcbnew (SWIG bindings) or the IPC API; it is not a second MCP server

---

## Directory Structure

```
KiCAD-MCP-Server/
  src/                        # TypeScript MCP server
    server.ts                 # Main server, tool registration, Python subprocess
    logger.ts                 # Logging configuration
    tools/                    # Tool definitions (one file per category)
      tool-registration.ts    # Canonical registration/result/annotation wrapper
      registry.ts             # Runtime-derived tool categories and lookup
      router.ts               # Supplemental discovery tools (list/get/search)
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
    schemas/                  # Legacy/internal Python schema checks; not tools/list
    resources/                # Legacy resource helpers; not the live MCP catalog
    templates/                # Schematic/project templates
    tests/                    # Python test suite
    utils/                    # Platform detection, helpers

  docs/                       # Documentation
  config/                     # Configuration examples
```

---

## TypeScript Layer

### Server Startup (`src/server.ts`)

1. Calls SDK v2 `serveStdio` with a fresh-server factory.
2. Negotiates MCP 2026-07-28 through `server/discover`, with the legacy 2025 `initialize` path enabled for compatibility.
3. Creates an MCP server instance and registers all tools, resources, and prompts for the selected connection.
4. Starts Python initialization in the background so protocol discovery is available immediately.
5. Makes KiCad-dependent calls wait for backend readiness and restarts the worker after recoverable failures.

### Tool Registration

Each tool file exports a `register*Tools(server, callKicadScript)` function that:

- Defines tool name, description, and Zod schema for parameters
- Registers through `registerKiCadTool`, which also records runtime catalog metadata and attaches annotations/output handling
- Calls `callKicadScript(command, args)` when a Python backend operation is required

Example from `src/tools/project.ts`:

```typescript
registerKiCadTool(
  server,
  "project",
  "create_project",
  {
    description: "Create a new KiCad project",
    inputSchema: z.object({ name: z.string(), path: z.string() }),
  },
  async (args) => {
    const result = await callKicadScript("create_project", args);
    return { content: [{ type: "text", text: JSON.stringify(result) }] };
  },
);
```

### Tool Discovery (`src/tools/router.ts` and `src/tools/registry.ts`)

All 183 tools are first-class MCP tools returned by `tools/list`. The runtime
registry is populated from the same `registerKiCadTool` calls, preventing a
second catalog from drifting.

`router.ts` provides three supplemental read-only tools:
`list_tool_categories`, `get_category_tools`, and `search_tools`. They help a
model find a tool, but the selected tool is called directly. There is no
`execute_tool` or hidden routed subset.

### Python Subprocess Communication

`callKicadScript(command, args)` in `server.ts`:

1. Waits for the background Python worker to become ready.
2. Sends a correlated JSON envelope containing `requestId`, `command`, and `params`.
3. Matches the response by `requestId`, enforcing timeout and cancellation semantics.
4. Returns the result to the MCP tool handler or restarts the worker when its state is no longer trustworthy.

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

Create or edit a file in `src/tools/`. Register the tool through the canonical wrapper:

```typescript
registerKiCadTool(
  server,
  "category_name",
  "my_new_tool",
  {
    description: "Description of what the tool does",
    inputSchema: z.object({
      param1: z.string().describe("Description of param1"),
      param2: z.number().optional().describe("Optional param2"),
    }),
  },
  async (args) => {
    const result = await callKicadScript("my_new_tool", args);
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  },
);
```

The registration automatically adds the first-class MCP tool and its runtime
category metadata. There is no manual routed/direct registry step.

### Step 2: Import a New Module in `server.ts`

Import and call the registration function in `src/server.ts`:

```typescript
import { registerMyTools } from "./tools/my-tools.js";
registerMyTools(server, callKicadScript);
```

Skip this step when adding to an existing registered module.

### Step 3: Implement the Python Handler

Add a handler in `python/kicad_interface.py` or create a new command module in `python/commands/`:

```python
def handle_my_new_tool(self, params):
    # Implementation using pcbnew API
    return {"success": True, "message": "Done", "data": result}
```

Add the command to `KiCADInterface.command_routes`:

```python
self.command_routes["my_new_tool"] = self.handle_my_new_tool
```

### Step 4: Build and Test

```bash
npm run build          # Compile TypeScript
npm run test:ts        # Run TypeScript protocol/catalog tests
npm run test:py        # Run Python tests
```

---

## Testing

### Python Tests

Located in `tests/`. Run with:

```bash
pytest tests/ -v
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
- **First-class catalog**: All 183 tools retain individual schemas and annotations; three supplemental discovery tools provide category and keyword lookup
- **Dual-era stdio**: SDK v2 `serveStdio` negotiates MCP 2026-07-28 while retaining the legacy 2025 path
- **Auto-save**: Every board-modifying SWIG operation auto-saves to prevent data loss
- **Dynamic symbol loading**: Works around kicad-skip's inability to create symbols from scratch
- **S-expression wire injection**: Works around kicad-skip's inability to create wires

---

## Source Files Reference

| File                                       | Purpose                             |
| ------------------------------------------ | ----------------------------------- |
| `src/server.ts`                            | MCP server, subprocess management   |
| `src/tools/tool-registration.ts`           | Canonical tool registration wrapper |
| `src/tools/registry.ts`                    | Runtime-derived tool catalog        |
| `src/tools/router.ts`                      | Supplemental discovery tools        |
| `python/kicad_interface.py`                | Python entry point, command routing |
| `python/kicad_api/factory.py`              | Backend selection                   |
| `python/commands/dynamic_symbol_loader.py` | Symbol injection system             |
| `python/commands/wire_manager.py`          | Wire creation engine                |
| `python/commands/pin_locator.py`           | Pin position discovery              |
