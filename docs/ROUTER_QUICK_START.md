# Tool Discovery Quick Start

_(File name kept as `ROUTER_QUICK_START.md` so existing links keep working. The
word "router" in the name is historical: see the note below.)_

## What is tool discovery?

The KiCAD MCP Server registers 229 tools. Your assistant can call any of them by
name at any time. To help it find the right one, 169 of those tools are indexed
into 15 categories that can be searched by keyword.

> **This is a search catalogue, not a gate.** Every tool is registered directly
> and is already visible to your assistant, so discovery saves no context. The
> original gated design (`execute_tool`) was removed in `963a39c` because
> indirect execution made the model invent tool schemas it had not been shown.
> See [ROUTER_ARCHITECTURE.md](ROUTER_ARCHITECTURE.md) for the full history.

## How it works

Alongside the tools themselves, your assistant gets three discovery tools:

- `list_tool_categories` - browse the categories
- `get_category_tools` - list the tools inside one category
- `search_tools` - find tools by keyword

When you ask for something like "export gerber files", the assistant either
already sees `export_gerber` in its tool list, or searches for it first. Either
way it then calls the real tool with the real schema. There is no intermediate
execution step.

## Tool categories

Counts below come from `getRegistryStats()` and are current for v2.7.0. The
generated [Tool Inventory](TOOL_INVENTORY.md) lists which tools are in each one.

| Category              | Tools | Covers                                                                    |
| --------------------- | ----- | ------------------------------------------------------------------------- |
| `board`               | 15    | Layers, origins, mounting holes, zones, graphics, 2D view                 |
| `component`           | 15    | Edit, delete, search, group, annotate, geometry and clearance checks      |
| `export`              | 27    | Gerber, drill, IPC-2581, ODB++, PDF, SVG, DXF, 3D, BOM, netlist, position |
| `drc`                 | 7     | Design rules, DRC runs, net classes, clearance checks                     |
| `schematic`           | 26    | Create, inspect, edit, wire, annotate, netlists, board sync               |
| `library`             | 7     | Footprint library search and browse, plus library-table maintenance       |
| `symbol_library`      | 17    | Symbol search, create, edit, rename, import, export, repair               |
| `symbol_pins`         | 3     | Read pins straight from a library and set their electrical types          |
| `schematic_hierarchy` | 5     | Insert, remove and scaffold sub-sheets; read and write sheet properties   |
| `schematic_layout`    | 5     | Field placement, autoplace, off-grid lint                                 |
| `schematic_batch`     | 6     | Bulk add, edit, replace, connect                                          |
| `routing`             | 2     | Vias and copper pours                                                     |
| `autoroute`           | 4     | Freerouting: autoroute, DSN export, SES import, availability check        |
| `validation`          | 2     | Find structural damage in schematics and symbol libraries                 |
| `parts-registry`      | 3     | Search and download parts from an open parts registry                     |

The other 60 registered tools are not indexed yet. They work exactly the same
way when called by name; they simply do not turn up in `search_tools` results.
`tests-ts/registry-completeness.test.ts` freezes that number so it can only go
down.

## Always-visible essentials

32 tools are marked as essentials in `src/tools/registry.ts`. This does not make
them more callable than any other tool - it means `search_tools` surfaces them
first, because they cover the operations almost every session needs:

**Project and board files:** `create_project`, `open_project`, `open_board`,
`reload_board`, `close_project`, `save_project`, `save_board`, `is_dirty`,
`discard_or_reload`, `snapshot_project`, `get_project_info`

**Core PCB operations:** `place_component`, `move_component`,
`batch_move_components`, `add_net`, `route_trace`, `get_board_info`,
`set_board_size`, `add_board_outline`, `replace_board_outline`,
`clear_board_outline`, `get_component_geometry`

**Core schematic operations:** `add_schematic_component`,
`list_schematic_components`, `annotate_schematic`, `connect_passthrough`,
`connect_to_net`, `add_schematic_net_label`, `sync_schematic_to_board`,
`create_board_from_schematic`

**Session state:** `get_backend_state`, `check_kicad_ui`

## Usage examples

### Natural interaction (recommended)

Just say what you want. Discovery happens on its own:

```
"Export gerber files to ./output"
"Add a mounting hole at x=10, y=10"
"Run a design rule check"
"Check that my symbol library still loads"
```

### Manual discovery (optional)

You can browse explicitly:

```
"List all tool categories"
"What export tools are available?"
"Search for tools that validate a schematic"
```

## Technical details

- **Registry:** `src/tools/registry.ts` - categories, essentials, and lookup
- **Discovery tools:** `src/tools/router.ts`
- **Server integration:** `src/server.ts` - all tools registered at startup

Related reading:

- [ROUTER_ARCHITECTURE.md](ROUTER_ARCHITECTURE.md) - the original gated design
  and why it was rolled back
- [TOOL_INVENTORY.md](TOOL_INVENTORY.md) - the generated catalogue of all 229
  tools

## A note on context usage

Earlier versions of this page claimed roughly an 80% reduction in context. That
was true only of the gated design, which no longer exists. Today every tool
schema is sent to the client, so discovery costs context rather than saving it.
The benefit it provides is accuracy: the assistant can find the right tool by
keyword instead of guessing a name.
