# Discussions. Get in here.

https://github.com/mixelpixx/KiCAD-MCP-Server/discussions/73

> ## 🚀 Meet Konnect — the next generation
>
> **[Konnect](https://github.com/mixelpixx/Konnect)** is this project rebuilt from
> scratch in Rust as a native KiCAD 10 plugin: a single binary with no runtime
> dependencies, built on KiCAD's official IPC API instead of SWIG, with 171 tools,
> bundled Claude skills and agents, design-review audits, and a manufacturing
> pipeline. It's where new development happens — licensed AGPL-3.0 (free for
> individuals and open source; commercial licenses available for businesses).
>
> This Python/TypeScript server remains fully open (MIT) and maintained.

# KiCAD MCP Server

A Model Context Protocol (MCP) server that enables AI assistants like Claude to interact with KiCAD for PCB design automation. Built on the MCP 2025-06-18 specification, this server provides comprehensive tool schemas and real-time project state access for intelligent PCB design workflows.

## Overview

The [Model Context Protocol](https://modelcontextprotocol.io/) is an open standard from Anthropic that allows AI assistants to securely connect to external tools and data sources. This implementation provides a standardized bridge between AI assistants and KiCAD, enabling natural language control of PCB design operations.

**Key Capabilities:**

- 233 tools registered, 173 of them indexed for keyword discovery
- 173 tools across 16 categories with JSON Schema validation
- Keyword tool discovery via `search_tools` / `get_category_tools`
- 23 dynamic resources exposing project state
- Complete schematic workflow with 65 tools (authoring, batch edits, hierarchy, layout) and dynamic symbol loading (~10,000 symbols)
- Freerouting autorouter integration (Java, Docker, or Podman)
- Custom footprint and symbol creation tools
- JLCPCB parts integration with 2.5M+ component catalog and local library search
- Datasheet enrichment via LCSC
- Full MCP 2025-06-18 protocol compliance
- Cross-platform support (Linux, Windows, macOS)
- Real-time KiCAD UI integration via IPC API (experimental)
- Comprehensive error handling and logging

## Try out Arduino MCP - now you can get Claude to help in the IDE, real time!:

https://github.com/mixelpixx/arduino-ide

## What's New in v2.7.0

### The bridge no longer crosses its wires

The Node-Python protocol had no request IDs: after one timeout, the next
command was silently resolved with the _previous_ command's late result, and
every response after that was off by one. Tool calls now carry an ID that
Python echoes back; stale responses are discarded instead of mis-delivered
(#373). The MCP transport also connects before Python spawns, so clients no
longer stack up against a silent server for up to two minutes during pcbnew
warm-up (#377).

### Two file-corruption classes fixed

`add_symbol_property` dropped a closing paren on every call and could splice
a unit symbol into a top-level sibling (#362, @karu2003). And S-expression
escaping is now symmetric: reads (#336) and writes (#324) share one
escape-aware implementation, so a property value containing `\"` survives a
round-trip — 419 of KiCad's own stock symbol files carry such values.

### 8 new tools

- **Validation**: `validate_schematic`, `validate_symbol_library` — locate
  structural damage with line/column, confirmed via `kicad-cli` on a copy.
- **Library tables**: `list_library_table`, `remove_library_table_entry`,
  `set_library_table_uri` — the missing CRUD around `register_*_library`.
- **Symbol editing**: `set_symbol_pin_type` (bulk pin type fixes with
  dry-run), `find_duplicate_symbols` (the same part stored twice).
- **Back-annotation**: `backannotate_footprints` — PCB footprint choices
  flow back to the schematic, the reverse of `sync_schematic_to_board`.

All by @karu2003. With #359 (@AmirF194) registering 15 existing symbol tools,
`search_tools` now indexes 169 tools in 15 categories.

### Quality of life

- `autoroute` stages its `.dsn`/`.ses` work files in a temp directory and
  cleans up on every exit — no more litter next to your board, no stale-SES
  imports, and a killed run says "terminated externally" instead of
  `exit code 4294967295` (#249, scoped by @Dewieinns' traces).
- Placed symbols inherit the library's default Footprint (#300,
  implementation by @stefangordon).
- `add_layer` actually adds inner copper layers (#222) — it previously wrote
  to non-copper layer IDs and renamed F.SilkS.
- `sync_schematic_to_board` matches by symbol UUID, not just refdes (#250).
- JLCPCB tools decode the new upstream `source-db-v2` schema (#352,
  @stefanobaldo) and degrade gracefully when the parts DB is unavailable
  (#264, @fage2022).
- `setup-macos.sh --verify` now fails when Python requirements are missing
  instead of passing on a server that cannot start (#350, @francisrath).

Full details in the [CHANGELOG](CHANGELOG.md).

## What's New in v2.6.0

### A session-killing bug is fixed

Deleting anything from a board — a component, a trace, a board outline —
worked exactly once. The next operation, even a pure read, failed with a
`SwigPyObject` error, and only `close_project` then `open_project` recovered.
`BOARD.Remove()` hands C++ ownership to Python, so dropping the reference ran
a destructor on an object KiCad still pointed at, corrupting SWIG state
process-wide. Six call sites were affected; all now use `BOARD.Delete()`.

### 10 new tools

- **Vendor PCB import**: `import_pcb` converts PADS, Altium, Eagle, CADSTAR,
  Fabmaster, P-CAD, SolidWorks PCB and binary Cadence Allegro `.brd` files via
  KiCad 10's native importer.
- **Hierarchical schematics**: `remove_hierarchical_sheet`,
  `set_sheet_property`, `get_sheet_properties`, and `hierarchical_place` for
  arranging footprints by schematic hierarchy.
- **Schematic lint and repair**: `lint_offgrid` finds and safely snaps
  off-grid geometry that silently breaks junction placement;
  `repair_flat_symbols` fixes SnapEDA/SamacSys symbols that crash kicad-skip;
  `lint_schematic_cosmetic` tidies pin names and label orientation.
- **Board origins**: `set_board_origin` / `get_board_origin`.

### Your `.kicad_pro` net classes stop disappearing

Board saves no longer let pcbnew serialize a stale in-memory project model
over your hand-edited net classes and `netclass_patterns`. Opening a project
no longer rewrites the file at all.

### Breaking: schematic tools fail loudly on an unparseable sheet

Tools that used to return partial or empty results now return a structured
`schematic_load_failed` error naming the offending symbols. Silently skipping
a broken sheet produced an incomplete pad-to-net map reported as success,
which is worse. `repair_flat_symbols` fixes the usual cause. See
[KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) section 7.

Full details in the [CHANGELOG](CHANGELOG.md).

## What's New in v2.5.0

### 20 new board-lifecycle and geometry tools

- **Lifecycle**: `open_board`, `reload_board`, `save_board`, `save_as`,
  `is_dirty`, `discard_or_reload`, `create_board_from_schematic`.
- **Graphics editing**: `clear_board_outline`, `replace_board_outline`,
  `list_graphics`, `delete_graphic`, `update_graphic`, `move_footprint_text`.
- **Geometry queries**: `batch_move_components`, `get_component_geometry`,
  `get_pads`, `get_net_pads`, `get_ratsnest`, `estimate_airwire_lengths`,
  `check_placement_clearance`.

All of them respect backend session pinning, so a board saved while KiCad's
GUI owns the session routes to the GUI rather than writing a stale in-memory
copy — including the awkward case where `save_as` changes the board's
identity mid-session.

### Formatting is normalized and enforced

- `pre-commit run --all-files` (black, isort, prettier, flake8, mypy, eslint)
  is now a real CI gate, which is what CONTRIBUTING has always claimed.
- `npm run lint` used to run `black` in **write** mode against whatever
  `black` was on `PATH`, silently reformatting your working tree with a
  version that disagreed with CI. It now checks only; `npm run format:py` is
  the write path.
- The README's tool count is pinned to the registry by a test, so it
  self-corrects instead of drifting.

Full details in the [CHANGELOG](CHANGELOG.md).

## What's New in v2.4.1

### Three tools that were registered but had no backend now work

- `assign_net_to_class`, `check_clearance` and `set_layer_constraints` each had
  a full schema and a router entry but no dispatch handler, so every call
  returned `Unknown command`. Found by a documentation-coverage audit.
- Per-layer constraints are written to a project-scoped `.kicad_dru`
  custom-rules file, which `kicad-cli pcb drc` and the GUI both pick up — there
  is no pcbnew API for them.

### Silent failures removed

- `autoroute` was abandoned by the Node bridge at 30 s while Freerouting was
  still running, reporting failure against a valid `.ses` that existed on disk.
  Its timeout now derives from the `timeout` and `attempts` you pass.
- `get_board_2d_view` omitted `--layers` entirely when no layers were given,
  and KiCad 9+ then refuses the export — producing no file at all.
- `create_zone` raised `AttributeError` on every call over the IPC backend.

### New part-sourcing tools

- `search_parts_registry` / `get_registry_part` / `download_registry_part`
  reuse a verified existing footprint or symbol instead of generating one.
  Downloads are host-allowlisted, extension-checked and size-capped.
- `get_jlcpcb_part` returns live stock and tiered pricing when JLCPCB Open
  Platform credentials are configured, falling back to the local snapshot.

### CI now actually runs the test suite

- The Python job had been a no-op in four independent ways, and Actions was
  disabled repo-wide — 32 failed runs and 0 successes across the project's
  whole history. All 1551 Python and 63 TypeScript tests now gate every push.

Full details in the [CHANGELOG](CHANGELOG.md).

## What's New in v2.4.0

### Symbol library management

- `import_symbol` / `export_symbol` / `rename_symbol` copy a symbol between
  `.kicad_sym` libraries, extract one to a standalone file, and rename a
  symbol including its sub-symbol shards and any `(extends ...)` references
  from derived symbols in the same library.
- `add_symbol_property` and `add_library_symbol_property` set custom BOM
  fields (Manufacturer, MPN, LCSC, ...) on a library symbol or on a
  schematic's cached definition.
- `update_symbol_from_library` refreshes cached `lib_symbols` definitions
  across one schematic, a list, or every project under a directory —
  the programmatic equivalent of KiCad's Update Symbol from Library.
- `replace_instance_lib_ids` swaps `lib_id` references per an explicit
  old-to-new mapping, for migrating a schematic between libraries.

### Faster symbol discovery

- Library directories, resolved paths, extracted symbol blocks, and parsed
  symbol lists are now cached process-wide instead of being rebuilt for every
  component add. Staleness guards revalidate paths and track source `mtime_ns`,
  and the mutating write paths clear the caches explicitly.

### Fixes that restore basic operation

- Every `.kicad_sym` and schematic write raised `TypeError` on Python 3.9, the
  project's declared floor — `Path.write_text` did not accept `newline` until
  3.10.
- JLCPCB part search could not find hyphenated MPNs.
- Eagle import wrote a KiCad 9 schematic header; it now writes the KiCad 10
  header, verified against real `kicad-cli` 10.0.
- Component placement snaps to the 1.27 mm grid, `import_ses` no longer
  creates phantom slashless nets, and `export_dsn`/`autoroute` keep
  `.kicad_pro` net classes.

Full details in the [CHANGELOG](CHANGELOG.md).

## What's New in v2.3.1

### Eagle schematic import

- `import_eagle_schematic` converts Eagle `.sch` XML designs to KiCad format
  with symbol mapping, net wires, multi-gate parts, dangling-wire pruning,
  and ground-truth ERC reporting via `kicad-cli`.

### 3D model tools and interactive reload

- `add_component_3d_model` / `remove_component_3d_model` for attaching
  STEP/WRL models to footprints.
- Opt-in `KICAD_INTERACTIVE_SCHEMATIC=1` auto-confirms KiCad's reload dialog
  on Windows after schematic writes.

### Scaffolding cluster complete

- New projects start blank (no `_TEMPLATE_*` symbols leaked into user files).
- `.kicad_pro` files match what KiCad itself writes.
- Format version `20260101` ensures all KiCad 10.0.x builds can open
  generated schematics.

### KiCad 10 compatibility

- Derived symbols in `.kicad_symdir` libraries resolve their parent from
  sibling shards.
- Unified install discovery finds relocated Windows installs via registry.
- User env-var placeholders from `kicad_common.json` are resolved in library
  paths.
- Phantom cross-unit pin reports in `get_wire_connections` are eliminated.

Full details in the [CHANGELOG](CHANGELOG.md).

## What's New in v2.3.0

### Schematic corruption on KiCad 10 — both mechanisms fixed

- **Complete instance blocks**: placed components now carry the real project
  name, root-sheet uuid path, per-pin uuid entries (ERC can bind wires to
  pins), and the full KiCad 10 field set — verified byte-equivalent to what
  eeschema itself writes. Previously, dragging or editing a placed symbol
  could crash KiCad.
- **Canonical multi-line writes**: schematic tools no longer minify the whole
  file onto one line. Tool writes now match eeschema's "Save" byte-for-byte,
  with a self-check on every write that can never corrupt data. Already-
  minified files are repairable with `scripts/kicad_sch_reformat.py`.

### Your edits are protected

- **Backend session pinning**: a loaded project stays on one backend
  (SWIG or IPC) for its whole lifecycle — saves can no longer silently route
  to a stale GUI board and lose your edits.
- **External-edit guard**: `save_project` refuses to overwrite a board file
  whose contents changed on disk since load (pass `force: true` to override).
- **`close_project`** (new tool): release the project so files can be edited
  directly, then reopen — no more restart choreography.

### Works on a stock Windows install

- `kicad-cli` and 7-Zip are resolved from their install locations even when
  not on PATH — un-breaking exports, ERC/DRC, netlists, board views, and the
  JLCPCB database download, each with actionable errors when truly missing.

### New layout tools

- `suggest_placement`: connectivity-driven PCB placement optimizer (dry-run
  by default, deterministic).
- `suggest_schematic_declutter`: re-orients overlapping net labels without
  touching connectivity.

Plus KiCad 10 compatibility fixes (sheet renames, sharded `.kicad_symdir`
libraries, IPC `Box2` board size), correct pin geometry for rotated+mirrored
and multi-unit symbols, bounded IPC connects with SWIG fallback, and a real
Vitest suite for the TypeScript layer. Full details in the
[CHANGELOG](CHANGELOG.md).

## What's New in v2.2.3

### New Tools: FFC/Ribbon Cable Passthrough Workflow

A complete workflow for designing passthrough adapter boards (e.g. Raspberry Pi CSI
cable adapters) is now supported:

1. `connect_passthrough` — wires all pins of one connector to the matching pins of
   another in the schematic (J1 pin N → J2 pin N, auto-named nets).
2. `sync_schematic_to_board` — imports the net assignments into the PCB.
3. `route_pad_to_pad` — routes each connection with automatic via insertion when
   pads are on opposite copper layers.
4. `snapshot_project` — saves a named checkpoint into `<project>/snapshots/`.

### Bug Fixes (KiCAD 9 / Windows)

- **Via insertion for B.Cu footprints** — `route_pad_to_pad` now correctly detects
  when a footprint is on B.Cu and inserts the required via. (KiCAD 9 SWIG returned
  `F.Cu` for all SMD pads regardless of layer — fixed.)
- **Board outline rounded corners** — `add_board_outline` now correctly applies
  `cornerRadius` when `shape="rounded_rectangle"`.
- **B.Cu placement hang** — placing a footprint on B.Cu no longer causes a ~30s
  freeze in KiCAD 9.

### Developer Mode

Set `KICAD_MCP_DEV=1` in your Claude Desktop MCP environment to automatically save
the MCP session log into the project's `logs/` folder on every `export_gerber` and
`snapshot_project` call. Useful for debugging and for attaching to GitHub issues.

```json
"env": {
  "KICAD_MCP_DEV": "1"
}
```

> **Privacy warning:** The session log contains your full tool call history
> (including file paths and design details). **Review or delete `logs/` before
> sharing a project directory publicly.**

See [CHANGELOG](CHANGELOG.md) for the full list of changes in this release.

---

## What's New in v2.1.0

### Critical Schematic Workflow Fix + Complete Wiring System (Issue #26)

The schematic workflow was completely broken in previous versions - **this is now fixed AND dramatically enhanced!**

**What was broken:**

- `create_project` only created PCB files, no schematics
- `add_schematic_component` called non-existent API methods
- Schematics couldn't be created or edited at all
- Only 13 component types available (severe limitation)
- No working wire/connection functionality

**Complete Implementation (3 Phases):**

**Phase 1: Component Placement Foundation**

- `create_project` now creates both .kicad_pcb and .kicad_sch files
- Added pre-configured template schematics with 13 common component types
- Rewrote component placement to use proper `clone()` API

**Phase 2: Dynamic Symbol Loading (BREAKTHROUGH!)**

- **Access to ALL ~10,000 KiCad symbols** from standard libraries
- Automatic detection and dynamic loading from `.kicad_sym` library files
- Zero configuration required - just specify library and symbol name
- Seamless integration with existing MCP tools
- Full S-expression parsing and injection system

**Phase 3: Intelligent Wiring System (NEW in v2.1.0)**

- **Automatic pin location discovery** with rotation support (0°, 90°, 180°, 270°)
- **Smart wire routing** (direct, orthogonal horizontal-first, orthogonal vertical-first)
- **Power symbol support** (VCC, GND, +3V3, +5V, etc.)
- **Wire graph analysis** - geometric tracing for net connectivity
- **Net label management** (local, global, hierarchical labels)
- **Netlist generation** with accurate component/pin connections

**Technical Architecture:**
The kicad-skip library cannot create symbols or wires from scratch. We implemented a comprehensive solution:

1. **Static Templates:** 13 pre-configured symbols (R, C, L, LED, etc.) for instant use
2. **Dynamic Loading:** On-demand injection of ANY symbol from KiCad libraries:
   - Parse `.kicad_sym` library files using S-expression parser
   - Inject symbol definition into schematic's `lib_symbols` section
   - Create offscreen template instance
   - Reload schematic so kicad-skip sees new template
   - Clone template to create actual component
3. **Wire Creation:** S-expression-based wire injection (bypasses kicad-skip API limitations)
4. **Pin Discovery:** Parse symbol definitions, apply rotation transformations, calculate absolute positions
5. **Connectivity Analysis:** Geometric wire tracing to build net connection graphs

**Example - Complete Circuit Creation:**

```python
# Load power symbols dynamically
loader.load_symbol_dynamically(sch_path, "power", "VCC")

# Place components with auto-rotation
ComponentManager.add_component(sch, {
    "type": "STM32F103C8Tx",
    "library": "MCU_ST_STM32F1",
    "reference": "U1",
    "x": 100, "y": 100, "rotation": 0
})

# Connect with intelligent routing
ConnectionManager.add_connection(sch_path, "U1", "1", "R1", "2", routing="orthogonal_h")

# Connect to power nets
ConnectionManager.connect_to_net(sch_path, "U1", "VDD", "VCC")

# Analyze connectivity
connections = ConnectionManager.get_net_connections(sch, "VCC", sch_path)
# Returns: [{"component": "U1", "pin": "VDD"}, {"component": "R1", "pin": "1"}]
```

**Test Results:**

- Component placement: 100% passing
- Dynamic symbol loading: 10,000+ symbols accessible
- Wire creation: 100% passing (8/8 connections in test circuit)
- Pin discovery: Rotation-aware, sub-millimeter accuracy
- Net connectivity: 100% accurate (VCC: 2 connections, GND: 4 connections)
- Netlist generation: Working with accurate pin-level connections

See [Schematic Tools Reference](docs/SCHEMATIC_TOOLS_REFERENCE.md) for the complete schematic tool documentation, and the [Headless Authoring Guide](docs/HEADLESS_AUTHORING.md) for field-tested practice driving these tools without the KiCad GUI.

### IPC Backend (Experimental)

We are currently implementing and testing the KiCAD 9.0 IPC API for real-time UI synchronization:

- Changes made via MCP tools appear immediately in the KiCAD UI
- No manual reload required when IPC is active
- Hybrid backend: uses IPC when available, falls back to SWIG API
- IPC runtime reconnect: if MCP has fallen back to SWIG, IPC-capable board
  tools retry IPC after KiCAD launches instead of staying on SWIG for the entire
  session
- 20+ commands now support IPC including routing, component placement, and zone operations

Note: IPC features are under active development and testing. Enable IPC in KiCAD via Preferences > Plugins > Enable IPC API Server.

For OpenCode on Windows, the backend can be configured as `auto`, `ipc`, or
`swig` during setup. See [OpenCode (Windows)](#opencode-windows) for the
configuration command and backend options.

### Tool Discovery

Every tool is registered individually, so an MCP client can call any of them by
name. On top of that, most tools are indexed so an assistant can find one by
keyword instead of guessing:

- **32 essential tools** that `search_tools` surfaces first, covering the
  operations nearly every session needs
- **173 tools indexed across 16 categories** (board, component, export, drc,
  schematic, library, symbol_library, symbol_pins, schematic_hierarchy,
  schematic_layout, schematic_batch, routing, autoroute, validation,
  parts-registry, digikey)
- **3 discovery tools**:
  - `list_tool_categories` - Browse all available categories
  - `get_category_tools` - View tools in a specific category
  - `search_tools` - Find tools by keyword

The remaining 60 registered tools are not indexed yet. They work exactly the
same when called by name; they simply do not appear in `search_tools` results.

**Why this matters:** the assistant can locate the right tool for your task by
keyword rather than inventing a name. Note that discovery does _not_ reduce
context: every tool schema is still sent to the client. An earlier design hid
tools behind an `execute_tool` dispatcher to save context; it was removed
because the model then invented schemas it had never been shown. See
[ROUTER_ARCHITECTURE.md](docs/ROUTER_ARCHITECTURE.md) for that history.

**Usage is seamless:** Just ask naturally - "export gerber files" or "add mounting holes" - and Claude will find and call the appropriate tools automatically.

### NEEDS TESTING - REPORT ISSUES

### JLCPCB Parts Integration (New!)

Complete integration with JLCPCB's parts catalog, providing two complementary approaches for component selection:

**Dual-Mode Architecture:**

1. **Local Symbol Libraries** - Search JLCPCB libraries installed via KiCAD Plugin and Content Manager (contributed by [@l3wi](https://github.com/l3wi))
2. **JLCPCB API Integration** - Access the complete 2.5M+ parts catalog with real-time pricing and stock data

**Key Features:**

- Real-time pricing with quantity breaks (1+, 10+, 100+, 1000+)
- Stock availability checking
- Basic vs Extended library type identification (Basic = free assembly)
- Intelligent cost optimization with alternative part suggestions
- Package-to-footprint mapping for KiCAD compatibility
- Parametric search by category, package, manufacturer
- Local SQLite database for fast offline searching
- No API credentials required for local library search

**Why this matters:** JLCPCB offers PCB assembly services where Basic parts have no assembly fee, while Extended parts charge $3 per unique component. This integration helps you find the cheapest components with the best availability, potentially saving hundreds of dollars on assembly costs for production runs.

See [JLCPCB Usage Guide](docs/JLCPCB_USAGE_GUIDE.md) for detailed setup and usage instructions.

### Comprehensive Tool Schemas

Every tool now includes complete JSON Schema definitions with:

- Detailed parameter descriptions and constraints
- Input validation with type checking
- Required vs. optional parameter specifications
- Enumerated values for categorical inputs
- Clear documentation of what each tool does

### Resources Capability

Access project state without executing tools:

- `kicad://project/current/info` - Project metadata
- `kicad://project/current/board` - Board properties
- `kicad://project/current/components` - Component list (JSON)
- `kicad://project/current/nets` - Electrical nets
- `kicad://project/current/layers` - Layer stack configuration
- `kicad://project/current/design-rules` - Current DRC settings
- `kicad://project/current/drc-report` - Design rule violations
- `kicad://board/preview.png` - Board visualization (PNG)

### Protocol Compliance

- Updated to MCP SDK 1.21.0 (latest)
- Full JSON-RPC 2.0 support
- Proper capability negotiation
- Standards-compliant error codes

## Available Tools

The server exposes every tool directly, so your assistant can call any of them without a discovery step -- just ask for what you want to accomplish. **173 tools** are additionally indexed into 16 functional categories, so `search_tools` and `get_category_tools` can find one by keyword.

The lists below are a curated tour of the most useful tools, not the full set.
For the complete, generated reference of all 233 tools -- including how each one
is discovered -- see [Tool Inventory](docs/TOOL_INVENTORY.md).

### Project Management (12 tools)

- `create_project` - Initialize new KiCAD projects
- `open_project` - Load existing project files
- `open_board` / `reload_board` - Open or re-read a specific `.kicad_pcb`
- `save_project` / `save_board` / `save_as` - Save current state
- `close_project` - Save (optionally) and drop in-memory state
- `is_dirty` / `discard_or_reload` - Check for and undo unsaved changes
- `get_project_info` - Retrieve project metadata
- `snapshot_project` - Save named checkpoint snapshot

### Board Operations (19 tools)

- `set_board_size` - Configure PCB dimensions
- `add_board_outline` - Create board edge (rectangle, circle, polygon, rounded rectangle)
- `add_layer` - Add custom layers to stack
- `set_active_layer` - Switch working layer
- `get_layer_list` - List all board layers
- `get_board_info` - Retrieve board properties
- `get_board_2d_view` - Generate board preview image
- `get_board_extents` - Get board bounding box
- `add_mounting_hole` - Place mounting holes
- `add_board_text` - Add text annotations
- `add_zone` - Add copper zone/pour with clearance settings
- `clear_board_outline` / `replace_board_outline` - Remove or swap the Edge.Cuts outline
- `set_board_origin` / `get_board_origin` - Read and set the drill/place and grid origins
- `list_graphics` / `update_graphic` / `delete_graphic` - Inspect and edit drawing items
- `import_svg_logo` - Import SVG file as PCB silkscreen polygons

### Component Management (28 tools)

- `place_component` - Place single component with footprint
- `move_component` - Reposition existing component
- `rotate_component` - Rotate component by angle
- `delete_component` - Remove component from board
- `edit_component` - Modify component properties
- `find_component` - Search by reference or value
- `get_component_properties` - Query component details
- `add_component_annotation` - Add annotation/comment
- `group_components` - Group multiple components
- `replace_component` - Replace with different footprint
- `get_component_pads` - Get all pad information
- `get_component_list` - List all placed components
- `get_pad_position` - Get precise pad position
- `place_component_array` - Create component grids/patterns
- `align_components` - Align multiple components
- `duplicate_component` - Copy existing component
- `batch_move_components` - Move many components in one transactional call
- `get_component_geometry` / `check_placement_clearance` - Body sizes and overlap checks
- `get_ratsnest` / `estimate_airwire_lengths` - Unrouted connection analysis

### Routing (17 tools)

- `add_net` - Create electrical net
- `route_trace` - Route copper traces between XY points
- `route_pad_to_pad` - Route between pads with auto-via insertion
- `add_via` - Place vias for layer transitions
- `delete_trace` - Remove traces (by UUID, position, or net)
- `query_traces` - Query/filter traces
- `get_nets_list` - List all nets with statistics
- `modify_trace` - Change trace width, layer, or net
- `create_netclass` - Define net class with rules
- `add_copper_pour` - Create copper zones/pours
- `route_differential_pair` - Route differential signals
- `refill_zones` - Refill all copper zones
- `copy_routing_pattern` - Replicate routing between component groups
- `set_net_color` - Set or clear a net's display color override
- `route_arc_trace` - Route a curved trace
- `add_gnd_stitching_vias` - Stitch a ground plane with vias
- `query_zones` - Inspect copper zones

### Schematic (46 tools)

Complete schematic workflow with dynamic symbol loading (~10,000 symbols) and intelligent wiring.

**Component Operations:**

- `add_schematic_component` - Place symbols from any KiCad library
- `delete_schematic_component` - Remove component
- `edit_schematic_component` - Edit footprint, value, reference, label positions, and **arbitrary custom properties** (MPN, Manufacturer, DigiKey_PN, LCSC, Voltage, Tolerance, Dielectric, …) in one batched call
- `set_schematic_component_property` - Add or update a single custom property (BOM/sourcing field) on a component
- `remove_schematic_component_property` - Delete a single custom property from a component
- `get_schematic_component` - Inspect every field on a component (built-in + custom) including label positions
- `list_schematic_components` - List all components
- `move_schematic_component` - Reposition component
- `rotate_schematic_component` - Rotate component
- `annotate_schematic` - Auto-assign reference designators

**Wiring and Connections:**

- `add_schematic_wire` - Create wire between points
- `delete_schematic_wire` - Remove wire segment
- `add_no_connect` - Mark a pin as deliberately unconnected
- `add_schematic_net_label` - Add net labels (VCC, GND, signals)
- `delete_schematic_net_label` - Remove net label
- `connect_to_net` - Connect pin to named net
- `connect_passthrough` - Wire all matching pins between connectors (FFC/ribbon)
- `get_schematic_pin_locations` - Get pin locations for component

**Analysis and Export:**

- `get_net_connections` - Trace net connectivity
- `list_schematic_nets` / `list_schematic_wires` / `list_schematic_labels`
- `create_schematic` - Create new schematic file
- `get_schematic_view` - Rasterized schematic preview
- `export_schematic_svg` / `export_schematic_pdf`
- `run_erc` - Electrical rule check
- `generate_netlist` - Generate netlist from schematic
- `sync_schematic_to_board` - Import nets/pads to PCB (F8 equivalent)
- `backannotate_footprints` - Copy footprint choices from the board back to the schematic
- `create_board_from_schematic` - Create a board populated from the schematic

**Batch, Hierarchy and Layout (19 more tools):**

- `batch_add_components` / `batch_edit_schematic_components` / `batch_connect` - Bulk authoring
- `add_hierarchical_sheet` / `create_hierarchical_subsheet` - Multi-sheet designs
- `autoplace_schematic_fields` / `lint_schematic_cosmetic` - Tidy field placement
- `lint_offgrid` / `snap_to_grid` - Find and fix off-grid coordinates

See [Schematic Tools Reference](docs/SCHEMATIC_TOOLS_REFERENCE.md) for details and examples.

### File Validation (2 tools)

Find structural damage before KiCad refuses to open a file. Both report the line
and column of every fault, and confirm the verdict with `kicad-cli` run against a
throwaway copy.

- `validate_schematic` - Check a `.kicad_sch` file
- `validate_symbol_library` - Check a `.kicad_sym` file

### Design Rules / DRC (7 tools)

- `set_design_rules` / `get_design_rules` - Configure and inspect rules
- `run_drc` - Execute design rule check
- `get_drc_violations` - Get violation list by severity
- `create_netclass` / `assign_net_to_class` - Net class management
- `set_layer_constraints` / `check_clearance` - Layer and clearance rules

### Export (27 tools)

- `export_gerber` / `export_gerbers` / `export_gerber_single` - Gerber fabrication files
- `export_drill` - Drill files
- `export_ipc2581` / `export_odb` / `export_ipcd356` / `export_gencad` - Other fabrication formats
- `export_pdf` / `export_svg` / `export_pcb_dxf` - Documentation and vector graphics
- `export_3d` - 3D models (STEP, STL, VRML, OBJ)
- `export_bom` / `export_sch_bom` - Bill of materials (CSV, XML, HTML, JSON)
- `export_netlist` - Netlist (KiCad, Spice, Cadstar, OrcadPCB2)
- `export_position_file` / `export_pos` - Component positions for pick and place
- `export_sch_pdf` / `export_sch_svg` / `export_sch_dxf` - Schematic output
- `export_vrml` - VRML 3D model

### Footprint Libraries and Symbol Libraries (16 tools)

- `list_libraries` / `list_symbol_libraries` - Browse available libraries
- `search_footprints` / `search_symbols` - Search across all libraries
- `list_library_footprints` / `list_library_symbols` - Browse specific library
- `get_footprint_info` / `get_symbol_info` - Detailed information
- `list_symbol_pins` / `batch_list_symbol_pins` - Read pins straight from a library
- `set_symbol_pin_type` - Bulk-set pin electrical types, with a dry run first
- `find_duplicate_symbols` - Find the same part stored twice under different names
- `repair_flat_symbols` - Fix vendor symbols that KiCad tolerates but tools cannot parse

**Library tables** (`sym-lib-table` / `fp-lib-table`):

- `list_library_table` - Read every registered library and check its URI resolves
- `remove_library_table_entry` - Unregister a library
- `set_library_table_uri` - Repoint a library that moved

### Footprint Creator (7 tools) and Symbol Creator (8 tools)

Create custom components when existing libraries do not have what you need.

- `create_footprint` / `create_symbol` - Build from scratch with pads/pins
- `edit_footprint_pad` - Modify pad properties
- `add_footprint_3d_model` / `add_component_3d_model` / `import_3d_model` - Attach 3D models
- `register_footprint_library` / `register_symbol_library` - Register in lib-table
- `list_footprint_libraries` / `list_symbols_in_library` - Browse custom libraries
- `add_symbol_property` - Add or update a field on a library symbol
- `import_symbol` / `export_symbol` / `rename_symbol` - Move symbols between libraries
- `delete_symbol` - Remove symbol from library

See [Footprint and Symbol Creator Guide](docs/FOOTPRINT_SYMBOL_CREATOR_GUIDE.md) for details.

### Datasheet Tools (2 tools)

- `enrich_datasheets` - Auto-populate datasheet URLs using LCSC part numbers
- `get_datasheet_url` - Get LCSC datasheet URL for a component

### JLCPCB Integration (5 tools)

- `download_jlcpcb_database` - Download 2.5M+ parts catalog (one-time setup)
- `search_jlcpcb_parts` - Search with parametric filters
- `get_jlcpcb_part` - Detailed part info with pricing
- `get_jlcpcb_database_stats` - Database statistics
- `suggest_jlcpcb_alternatives` - Find cheaper or in-stock alternatives

### Freerouting Autorouter (4 tools)

- `autoroute` - Run Freerouting autorouter (DSN export, route, SES import)
- `export_dsn` / `import_ses` - Manual Specctra DSN/SES workflow
- `check_freerouting` - Verify Java and Freerouting availability

See [Freerouting Guide](docs/FREEROUTING_GUIDE.md) for setup and usage.

### UI Management (3 tools)

- `check_kicad_ui` - Check if KiCAD is running
- `launch_kicad_ui` - Launch KiCAD application
- `get_backend_state` - Report which backend (IPC or SWIG) is in use

### Parts Registry (3 tools)

Look for a ready-made part before generating a custom one.

- `search_parts_registry` - Search the registry by name, keyword or manufacturer
- `get_registry_part` - Inspect one part in detail
- `download_registry_part` - Download its footprint, symbol or 3D model

### Import (2 tools)

- `import_eagle_project` - Convert an Eagle project
- `import_pcb` - Load an existing `.kicad_pcb` into the session

## Prerequisites

### Required Software

**KiCAD 9.0 or higher**

- Download from [kicad.org/download](https://www.kicad.org/download/)
- Must include Python module (pcbnew)
- Verify installation:
  ```bash
  python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"
  ```

**Node.js 18 or Higher**

- Download from [nodejs.org](https://nodejs.org/)
- Verify: `node --version` and `npm --version`

**Python 3.9 or Higher**

- Comes bundled with KiCAD (macOS builds ship Python 3.9; Linux/Windows builds ship Python 3.11)
- Required packages (auto-installed):
  - kicad-python (kipy) >= 0.5.0 (IPC API support, optional but recommended)
  - kicad-skip >= 0.1.0 (schematic support)
  - Pillow >= 9.0.0 (image processing)
  - cairosvg >= 2.7.0 (SVG rendering)
  - colorlog >= 6.7.0 (logging)
  - pydantic >= 2.5.0 (validation)
  - requests >= 2.32.5 (HTTP client)
  - python-dotenv >= 1.0.0 (environment)

**MCP Client**
Choose one:

- [Claude Desktop](https://claude.ai/download) - Official Anthropic desktop app
- [Claude Code](https://docs.claude.com/claude-code) - Official CLI tool
- [Cline](https://github.com/cline/cline) - VSCode extension
- [OpenCode](https://opencode.ai/) - Terminal-based AI coding agent with MCP support

### Supported Platforms

- **Linux** (Ubuntu 22.04+, Fedora, Arch) - Primary platform, fully tested
- **Windows 10/11** - Fully supported with automated setup
- **macOS** - Experimental support

## Installation

### Linux (Ubuntu/Debian)

```bash
# Install KiCAD 9.0 or higher
sudo add-apt-repository --yes ppa:kicad/kicad-9.0-releases
sudo apt-get update
sudo apt-get install -y kicad kicad-libraries

# Install Node.js
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Clone and build
git clone https://github.com/mixelpixx/KiCAD-MCP-Server.git
cd KiCAD-MCP-Server
npm install
pip3 install -r requirements.txt
npm run build

# Verify
python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"
```

### Windows 10/11

**Automated Setup (Recommended):**

```powershell
git clone https://github.com/mixelpixx/KiCAD-MCP-Server.git
cd KiCAD-MCP-Server
.\setup-windows.ps1
```

The script will:

- Detect KiCAD installations, including both machine-wide installs under
  `C:\Program Files\KiCad` and per-user installs under
  `%LOCALAPPDATA%\Programs\KiCad`
- Verify prerequisites
- Install dependencies
- Build project
- Generate configuration
- Run diagnostics

**Manual Setup:**
See [Platform Guide](docs/PLATFORM_GUIDE.md) for detailed instructions, and
[Windows Troubleshooting](docs/WINDOWS_TROUBLESHOOTING.md) if setup fails.

### macOS

**Important:** On macOS, use KiCAD's bundled Python to ensure proper access to the `pcbnew` module.

#### Manual Setup

```bash
# Install KiCAD 9.0 from kicad.org/download/macos

# Install Node.js
brew install node@20

# Clone repository
git clone https://github.com/mixelpixx/KiCAD-MCP-Server.git
cd KiCAD-MCP-Server

# Create virtual environment using KiCAD's bundled Python
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -m venv venv --system-site-packages

# Activate virtual environment
source venv/bin/activate

# Install dependencies
npm install
pip install -r requirements.txt
npm run build
```

**Note:** The `--system-site-packages` flag is required to access KiCAD's `pcbnew` module from the virtual environment.

**Note:** If you skip the virtual environment, install the requirements with KiCAD's bundled interpreter — a plain `pip3 install -r requirements.txt` goes to system Python, which the server never uses, and the server then fails to start (the MCP client times out after 30s with no visible error):

```bash
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 \
  -m pip install --user -r requirements.txt
```

#### Automated Setup

To simplify configuration with Claude Desktop, this repository provides a macOS setup script:

```bash
./setup-macos.sh
```

In case of error `zsh: permission denied: ./setup-macos.sh` you can either:

- always allow the script to be executed by running: `chmod +x setup-macos.sh`.
- alternatively explicitly run it with bash: `bash setup-macos.sh` so no chmod change needed.

This script does **not replace the manual setup above** — it assumes dependencies are already installed and the project is built. Instead, it automates:

- detection of your environment (Node.js, KiCad Python, `pcbnew`)
- resolving the correct macOS `PYTHONPATH`
- generating the correct Claude Desktop MCP configuration
- safely merging the configuration into your existing Claude config
- optionally writing the configuration with backup support

##### Basic Usage

###### Verify setup (no changes)

```bash
./setup-macos.sh --verify
```

###### Preview configuration (dry run)

```bash
./setup-macos.sh --dry-run
```

###### Apply configuration

```bash
./setup-macos.sh --apply
```

After applying, restart Claude Desktop.

##### Parameters

###### Required parameters

None. The script works out-of-the-box using sensible defaults.

###### Optional parameters

##### `--name NAME`

Specify the MCP server name in Claude Desktop.

Default:

```text
kicad
```

Example:

```bash
./setup-macos.sh --apply --name kicad-dev
```

Use this when:

- running multiple MCP configurations
- testing forks or development versions
- avoiding overwriting an existing setup

##### `--claude-config PATH`

Specify a custom Claude Desktop configuration file.

Default:

```text
~/Library/Application Support/Claude/claude_desktop_config.json
```

Example:

```bash
./setup-macos.sh --dry-run --claude-config ~/tmp/claude_config.json
```

Use this when:

- testing configurations safely
- using non-standard config locations
- debugging without modifying your main setup

##### `--yes`

Skip confirmation prompt when applying changes.

Example:

```bash
./setup-macos.sh --apply --yes
```

##### After Setup

1. Fully quit Claude Desktop
2. Reopen Claude Desktop
3. Open a new chat
4. Click **+ → Connectors**
5. Verify the server appears (e.g. `kicad` or your custom name)

Test with prompt in Claude Desktop:

```text
Use the kicad MCP server to run check_kicad_ui.
```

##### Notes

- The script only modifies the `mcpServers` section and leaves all other configuration untouched
- Existing configurations are automatically backed up before changes
- macOS support relies on KiCad’s bundled Python; system Python will not work correctly
- If KiCad is updated or moved, re-run the script to refresh paths

---

## Configuration

### Claude Desktop

Edit configuration file:

- **Linux:** `~/.config/Claude/claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

**Configuration:**

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["/path/to/KiCAD-MCP-Server/dist/index.js"],
      "env": {
        "PYTHONPATH": "/path/to/kicad/python",
        "LOG_LEVEL": "info"
      }
    }
  }
}
```

**Platform-specific PYTHONPATH:**

- **Linux:** `/usr/lib/kicad/lib/python3/dist-packages`
- **Windows:** `C:\Program Files\KiCad\10.0\lib\python3\dist-packages` or
  `%LOCALAPPDATA%\Programs\KiCad\10.0\lib\python3\dist-packages`
- **macOS:** `/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/lib/python3.9/site-packages`

#### Linux Python Detection

The server automatically detects Python on Linux in this priority order:

1. **Virtual environment** - `venv/bin/python` or `.venv/bin/python` (highest priority)
2. **KICAD_PYTHON env var** - User override for non-standard installations
3. **KiCad bundled Python** - `/usr/lib/kicad/bin/python3`, `/usr/local/lib/kicad/bin/python3`, `/opt/kicad/bin/python3`
4. **System Python via which** - Resolves `which python3` to absolute path (e.g., `/usr/bin/python3`)
5. **Common system paths** - `/usr/bin/python3`, `/bin/python3`

**For most standard Linux installations (Ubuntu, Debian, Fedora, Arch), no KICAD_PYTHON configuration is needed** - the server will automatically find your Python installation.

**Troubleshooting:**

If you see "Python executable not found: python3", you can manually specify the Python path:

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["/path/to/KiCAD-MCP-Server/dist/index.js"],
      "env": {
        "KICAD_PYTHON": "/usr/bin/python3",
        "PYTHONPATH": "/usr/lib/kicad/lib/python3/dist-packages"
      }
    }
  }
}
```

To find your Python path:

```bash
which python3  # Example output: /usr/bin/python3
python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"  # Verify pcbnew access
```

### GitHub Copilot (VS Code)

Copy the template to your workspace:

```bash
cp config/vscode-mcp.example.json .vscode/mcp.json
```

VS Code will auto-detect `.vscode/mcp.json` and register the server. The template uses `${workspaceFolder}` so no path editing is needed.

> **Note:** `.vscode/mcp.json` is listed in `.gitignore` — your local configuration won't be committed.

### Cline (VSCode)

Edit: `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`

Use the same configuration format as Claude Desktop above.

### Claude Code

Claude Code does **not** read the Claude Desktop configuration file, and it only auto-detects servers listed in a project's `.mcp.json` (this repository does not ship one). Register the server explicitly with `claude mcp add`:

```bash
# macOS example — adjust KICAD_PYTHON/PYTHONPATH per platform (see table above)
claude mcp add --scope user kicad \
  --env KICAD_PYTHON=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 \
  --env PYTHONPATH=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/lib/python3.9/site-packages \
  --env LOG_LEVEL=info \
  -- node /path/to/KiCAD-MCP-Server/dist/index.js
```

With `--scope user` the server is available in every project; use `--scope project` to write a shareable `.mcp.json` instead. On macOS, `setup-macos.sh` prints this command with the detected paths filled in.

Verify with `claude mcp list` — the server should report ✔ Connected.

### OpenCode (Windows)

OpenCode uses a different MCP configuration schema than Claude Desktop. Use
`setup-windows-opencode.ps1` to verify the local setup and write the correct
OpenCode `mcp` entry.

OpenCode project configuration is written to `opencode.json` in the target
project root. The script keeps the KiCAD MCP server repository separate from the
target project:

- `McpServerPath` is this repository, where `dist/index.js` is built
- `ProjectPath` is the project that should receive `opencode.json`

**When this is useful:**

- You use [OpenCode](https://opencode.ai/) as your MCP client on Windows
- You want a project-local MCP server available only in one project
- You want a global OpenCode MCP server available from any workspace
- You need to verify KiCAD Python (`pcbnew`), Node.js, and `dist/index.js`
  before changing OpenCode configuration

#### Backend selection

The setup script supports three KiCAD backend preferences via `-Backend`:

- `auto` - try IPC first and fall back to SWIG if IPC is unavailable (default)
- `ipc` - require KiCAD IPC for real-time UI synchronization
- `swig` - use the file-based `pcbnew` backend

Examples:

```powershell
.\setup-windows-opencode.ps1 -Apply -Scope project -Backend auto
.\setup-windows-opencode.ps1 -Apply -Scope project -Backend ipc
.\setup-windows-opencode.ps1 -Apply -Scope project -Backend swig
```

For `-Backend ipc`, KiCAD must be running with the IPC API server enabled.

#### Verify setup without changes

Use this first when diagnosing installation or path problems. It detects KiCAD,
tests `pcbnew`, checks Node.js, and verifies the built MCP entrypoint.

```powershell
.\setup-windows-opencode.ps1 -Verify -SkipInstall -SkipBuild
```

#### Preview OpenCode configuration

Use dry run mode when you want to inspect the exact JSON before writing it.

```powershell
.\setup-windows-opencode.ps1 -DryRun -SkipInstall -SkipBuild
```

Example generated OpenCode shape:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "kicad": {
      "type": "local",
      "command": ["node", "C:\\path\\to\\KiCAD-MCP-Server\\dist\\index.js"],
      "environment": {
        "NODE_ENV": "production",
        "LOG_LEVEL": "info",
        "KICAD_AUTO_LAUNCH": "false",
        "KICAD_MCP_DEV": "0",
        "KICAD_BACKEND": "auto",
        "PYTHONPATH": "C:\\Program Files\\KiCad\\10.0\\bin\\Lib\\site-packages"
      },
      "enabled": true,
      "timeout": 30000
    }
  }
}
```

A copyable template is also provided at `config/opencode.json`. Replace the
placeholder paths before using it directly.

#### Apply project-local configuration

Use this when you only want KiCAD MCP enabled for one project. The script writes
`opencode.json` in the target project root and backs up an existing file before
changing it.

```powershell
.\setup-windows-opencode.ps1 -Apply -Scope project
```

By default, `ProjectPath` is the current working directory.

To configure another project, pass `-ProjectPath`:

```powershell
.\setup-windows-opencode.ps1 -Apply -Scope project -ProjectPath "C:\path\to\your-project"
```

If the setup script is not located in the KiCAD MCP Server repository, pass
`-McpServerPath` so the generated config points to the correct `dist/index.js`:

```powershell
.\setup-windows-opencode.ps1 `
  -Apply `
  -Scope project `
  -ProjectPath "C:\path\to\your-project" `
  -McpServerPath "C:\path\to\KiCAD-MCP-Server"
```

#### Apply global OpenCode configuration

Use this when you want the KiCAD MCP server available from any OpenCode
workspace. The script writes `%USERPROFILE%\.config\opencode\opencode.json`.

```powershell
.\setup-windows-opencode.ps1 -Apply -Scope global
```

#### Use a custom MCP server name

Use this when testing multiple forks or keeping separate development and stable
KiCAD MCP entries.

```powershell
.\setup-windows-opencode.ps1 -Apply -Scope project -Name kicad-dev
```

#### Use a custom KiCAD installation path

Use this when KiCAD is installed outside the standard Windows locations.

```powershell
.\setup-windows-opencode.ps1 -Apply -Scope project -KiCadRoot "D:\Apps\KiCad\10.0"
```

#### Skip install or build steps

Use these flags when dependencies are already installed or the project is
already built.

```powershell
.\setup-windows-opencode.ps1 -Apply -Scope project -SkipInstall -SkipBuild
```

#### After applying configuration

1. Fully quit OpenCode.
2. Start OpenCode again so it reloads `opencode.json`.
3. Ask OpenCode to use the `kicad` MCP server and run `check_kicad_ui`.

#### Disable the OpenCode MCP server

To disable the server without removing the full configuration, set the entry to
`enabled: false` and restart OpenCode.

```json
{
  "mcp": {
    "kicad": {
      "enabled": false
    }
  }
}
```

If OpenCode is running, the MCP server process is managed by OpenCode and
normally stops when OpenCode exits.

### JLCPCB Integration Setup (Optional)

The JLCPCB integration provides two modes that can be used independently or together:

**Mode 1: JLCSearch Public API (Recommended - No Setup Required)**

The easiest way to access JLCPCB's parts catalog:

- No API credentials needed
- No JLCPCB account required
- Access to 2.5M+ parts with pricing and stock data
- Download time: 40-60 minutes for full catalog (100-part batches due to API limit)

To download the database:

```
Ask Claude: "Download the JLCPCB parts database"
```

This creates a local SQLite database at `data/jlcpcb_parts.db` (3-5 GB for full 2.5M+ part catalog).

**Mode 2: Local Symbol Libraries (No Setup Required)**

Install JLCPCB libraries via KiCAD's Plugin and Content Manager:

1. Open KiCAD
2. Go to Tools > Plugin and Content Manager
3. Search for "JLCPCB" or "JLC"
4. Install libraries like `JLCPCB-KiCAD-Library` or `EDA_MCP`
5. Use `search_symbols` to find components with pre-configured footprints and LCSC IDs

**Mode 3: Official JLCPCB API (Advanced - Requires Enterprise Account)**

For users with JLCPCB enterprise accounts and order history:

1. **Get API Credentials**
   - Log in to [JLCPCB](https://jlcpcb.com/)
   - Navigate to Account > API Management (requires enterprise approval)
   - Create API Key and save your `appKey` and `appSecret`
   - Note: This requires prior order history and enterprise account approval

2. **Configure Environment Variables**

   Add to your shell profile (`~/.bashrc`, `~/.zshrc`, or `~/.profile`):

   ```bash
   export JLCPCB_API_KEY="your_app_key_here"
   export JLCPCB_API_SECRET="your_app_secret_here"
   ```

   Or create a `.env` file in the project root:

   ```
   JLCPCB_API_KEY=your_app_key_here
   JLCPCB_API_SECRET=your_app_secret_here
   ```

See [JLCPCB Usage Guide](docs/JLCPCB_USAGE_GUIDE.md) for detailed documentation.

## Usage Examples

### Basic PCB Design Workflow

```text
Create a new KiCAD project named 'LEDBoard' in my Documents folder.
Set the board size to 50mm x 50mm and add a rectangular outline.
Place a mounting hole at each corner, 3mm from the edges, with 3mm diameter.
Add text 'LED Controller v1.0' on the front silkscreen at position x=25mm, y=45mm.
```

### Component Placement

```text
Place an LED at x=10mm, y=10mm using footprint LED_SMD:LED_0805_2012Metric.
Create a grid of 4 resistors (R1-R4) starting at x=20mm, y=20mm with 5mm spacing.
Align all resistors horizontally and distribute them evenly.
```

### Routing

```text
Create a net named 'LED1' and route a 0.3mm trace from R1 pad 2 to LED1 anode.
Add a copper pour for GND on the bottom layer covering the entire board.
Create a differential pair for USB_P and USB_N with 0.2mm width and 0.15mm gap.
```

### Autoroute with Freerouting

Automatically route all unconnected nets using the [Freerouting](https://github.com/freerouting/freerouting) autorouter.

**Setup (one-time):**

```bash
# 1. Download the Freerouting JAR
mkdir -p ~/.kicad-mcp
curl -L -o ~/.kicad-mcp/freerouting.jar \
  https://github.com/freerouting/freerouting/releases/download/v2.0.1/freerouting-2.0.1-executable.jar

# 2. Runtime — pick ONE:
#    Option A: Docker (recommended, no Java install needed)
docker pull eclipse-temurin:21-jre

#    Option B: Install Java 21+ locally
#    (Ubuntu/Debian) sudo apt install openjdk-21-jre
```

The autorouter auto-detects which runtime is available (Java 21+ direct, or Docker/Podman fallback).

```text
Check if Freerouting is ready on my system.
Autoroute the current board using Freerouting with a 5-minute timeout.
```

**Step-by-step workflow:**

```text
1. Open the project at ~/Projects/LEDBoard/LEDBoard.kicad_pcb
2. Check Freerouting dependencies are installed
3. Run autoroute with max 10 passes
4. Run DRC to verify the autorouted result
5. Export Gerbers to the fabrication folder
```

**Manual DSN/SES workflow** (for advanced users or external autorouters):

```text
Export the board to Specctra DSN format.
# ... run Freerouting GUI or another autorouter externally ...
Import the routed SES file from ~/Projects/LEDBoard/LEDBoard.ses
```

### Design Verification

```text
Set design rules with 0.15mm clearance and 0.2mm minimum track width.
Run a design rule check and show me any violations.
Export Gerber files to the 'fabrication' folder.
```

### Using Resources

Resources provide read-only access to project state:

```text
Show me the current component list.
What are the current design rules?
Display the board preview.
List all electrical nets.
```

### JLCPCB Component Selection

**Finding Components with Local Libraries:**

```text
Search for ESP32 modules in JLCPCB libraries.
Find a 10k resistor in 0603 package from installed libraries.
Show me details for LCSC part C2934196.
```

**Optimizing Costs with JLCPCB API:**

```text
Search for 10k ohm resistors in 0603 package, only Basic parts.
Find the cheapest capacitor 10uF 25V in 0805 package with good stock.
Show me pricing and stock for JLCPCB part C25804.
Suggest cheaper alternatives to C25804.
```

**Complete Design Workflow:**

```text
I'm designing a board with an ESP32 and need to select components for JLCPCB assembly.
Search JLCPCB for ESP32-C3 modules.
Find Basic parts for: 10k resistor 0603, 100nF capacitor 0603, LED 0805.
For each component, show me the cheapest option with good stock availability.
Place these components on my board using the suggested footprints.
```

**Database Management:**

```text
Download the JLCPCB parts database (first time setup).
Show me JLCPCB database statistics.
How many Basic parts are available?
```

## Architecture

### MCP Protocol Layer

- **JSON-RPC 2.0 Transport:** Bi-directional communication via STDIO
- **Protocol Version:** MCP 2025-06-18
- **Capabilities:** Tools (233), Resources (23)
- **Tool discovery:** keyword search catalogue indexing 173 tools in 16 categories
- **Error Handling:** Standard JSON-RPC error codes

### TypeScript Server (`src/`)

- Implements MCP protocol specification
- Manages Python subprocess lifecycle
- Handles message routing and validation
- Provides logging and error recovery
- **Discovery catalogue:**
  - `src/tools/registry.ts` - Tool categorization and lookup
  - `src/tools/router.ts` - `list_tool_categories`, `get_category_tools`, `search_tools`
  - Search and browse only. It does not gate which tools reach the client, so
    it saves no context; indirect execution was removed in 963a39c because it
    caused schema hallucination. See
    [ROUTER_ARCHITECTURE.md](docs/ROUTER_ARCHITECTURE.md).

### Python Interface (`python/`)

- **kicad_interface.py:** Main entry point, MCP message handler, command routing
- **kicad_api/:** Backend implementations
  - `base.py` - Abstract base classes for backends
  - `ipc_backend.py` - KiCAD 9.0 IPC API backend (real-time UI sync)
  - `swig_backend.py` - pcbnew SWIG API backend (file-based operations)
  - `factory.py` - Backend auto-detection and instantiation
- **schemas/tool_schemas.py:** JSON Schema definitions for all tools
- **resources/resource_definitions.py:** Resource handlers and URIs
- **commands/:** Modular command implementations
  - `project.py` - Project operations
  - `board.py` - Board manipulation
  - `component.py` - Component placement
  - `routing.py` - Trace routing and nets
  - `design_rules.py` - DRC operations
  - `export.py` - File generation
  - `schematic.py` - Schematic design
  - `library.py` - Footprint libraries
  - `library_symbol.py` - Symbol library search (local JLCPCB libraries)
  - `jlcpcb.py` - JLCPCB API client
  - `jlcpcb_parts.py` - JLCPCB parts database manager

### KiCAD Integration

- **pcbnew API (SWIG):** Direct Python bindings to KiCAD for file operations
- **IPC API (kipy):** Real-time communication with running KiCAD instance (experimental)
- **Hybrid Backend:** Automatically uses IPC when available, falls back to SWIG
- **kicad-skip:** Schematic file manipulation
- **Platform Detection:** Cross-platform path handling
- **UI Management:** Automatic KiCAD UI launch/detection

## Development

### Building from Source

```bash
# Install dependencies
npm install
pip3 install -r requirements.txt

# Build TypeScript
npm run build

# Watch mode for development
npm run dev
```

### Running Tests

```bash
# TypeScript tests
npm run test:ts

# Python tests
npm run test:py

# All tests with coverage
npm run test:coverage
```

### Linting and Formatting

```bash
# Lint TypeScript and Python
npm run lint

# Format code
npm run format
```

## Troubleshooting

### Server Not Appearing in Client

**Symptoms:** MCP server doesn't show up in Claude Desktop or Cline

**Solutions:**

1. Verify build completed: `ls dist/index.js`
2. Check configuration paths are absolute
3. Restart MCP client completely
4. Check client logs for error messages

### Python Module Import Errors

**Symptoms:** `ModuleNotFoundError: No module named 'pcbnew'`

**Solutions:**

1. Verify KiCAD installation: `python3 -c "import pcbnew"`
2. Check PYTHONPATH in configuration matches your KiCAD installation
3. Ensure KiCAD was installed with Python support

### Tool Execution Failures

**Symptoms:** Tools fail with unclear errors

**Solutions:**

1. Check server logs: `~/.kicad-mcp/logs/kicad_interface-<pid>.log` (one file per server process)
2. Verify a project is loaded before running board operations
3. Ensure file paths are absolute, not relative
4. Check tool parameter types match schema requirements

### Windows-Specific Issues

**Symptoms:** Server fails to start on Windows

**Solutions:**

1. Run automated diagnostics: `.\setup-windows.ps1`
2. Verify Python path uses double backslashes: `C:\\Program Files\\KiCad\\10.0`
3. Check Windows Event Viewer for Node.js errors
4. See [Windows Troubleshooting Guide](docs/WINDOWS_TROUBLESHOOTING.md)

### Getting Help

1. Check the [GitHub Issues](https://github.com/mixelpixx/KiCAD-MCP-Server/issues)
2. Review server logs: `~/.kicad-mcp/logs/kicad_interface-<pid>.log` (one file per server process)
3. Open a new issue with:
   - Operating system and version
   - KiCAD version (`python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"`)
   - Node.js version (`node --version`)
   - Full error message and stack trace
   - Relevant log excerpts

## Project Status

**Current Version:** 2.7.0

See [STATUS_SUMMARY.md](docs/STATUS_SUMMARY.md) for the complete status matrix and [CHANGELOG.md](CHANGELOG.md) for detailed release notes.

**Working Features (233 tools):**

- Project management with snapshot checkpointing
- Complete board design (outline, layers, zones, mounting holes, text, SVG logos)
- Component placement with arrays, alignment, and duplication
- Advanced routing (pad-to-pad with auto-via, differential pairs, pattern copying)
- Complete schematic workflow with dynamic symbol loading (~10,000 symbols)
- Intelligent wiring system with pin discovery and smart routing
- FFC/ribbon cable passthrough workflow
- Schematic-to-board synchronization, plus footprint back-annotation from the board
- Design rule checking (DRC and ERC)
- Structural validation of schematics and symbol libraries
- Export to Gerber, PDF, SVG, 3D, BOM, netlist, position file
- Custom footprint and symbol creation
- Library table maintenance (list, remove and repoint symbol/footprint entries)
- JLCPCB parts integration (2.5M+ parts catalog)
- Digi-Key Product Information V4 search and library availability sweep
- Datasheet enrichment via LCSC
- Freerouting autorouter integration (Java, Docker, Podman)
- UI auto-launch and management
- Full MCP 2025-06-18 protocol compliance

**IPC Backend (Experimental):**

- Real-time UI synchronization via the KiCAD IPC API
- 21 IPC-enabled commands with automatic SWIG fallback
- Hybrid footprint loading (SWIG for library access, IPC for placement)

**Developer Mode:**
Set `KICAD_MCP_DEV=1` to capture MCP session logs for debugging. See CHANGELOG v2.2.3 for details.

**Logging (`~/.kicad-mcp/logs/`):**
Logs default to `INFO` and the file is size-capped so it can't grow without bound. Tune via the MCP server's environment:

| Variable                            | Default            | Purpose                                                                              |
| ----------------------------------- | ------------------ | ------------------------------------------------------------------------------------ |
| `LOG_LEVEL` / `KICAD_MCP_LOG_LEVEL` | `info`             | Log verbosity (`error`/`warn`/`info`/`debug`, or `off`). `KICAD_MCP_LOG_LEVEL` wins. |
| `KICAD_MCP_LOG_MAX_BYTES`           | `10485760` (10 MB) | Max size per log file before it rotates; `0` disables rotation.                      |
| `KICAD_MCP_LOG_BACKUP_COUNT`        | `3`                | Number of rotated backups to keep.                                                   |
| `KICAD_MCP_DEBUG_SKIP`              | unset              | Set to `1` to re-enable the verbose kicad-skip parser DEBUG logs (muted by default). |

See [ROADMAP.md](docs/ROADMAP.md) for planned features.

## What Do You Want to See Next?

We are actively developing new features. Your feedback directly shapes development priorities.

**Share your ideas:**

1. [Open a feature request](https://github.com/mixelpixx/KiCAD-MCP-Server/issues/new?labels=enhancement&template=feature_request.md)
2. [Join the discussion](https://github.com/mixelpixx/KiCAD-MCP-Server/discussions)
3. Star the repo if you find it useful

## Contributing

Contributions are welcome! Please follow these guidelines:

1. **Report Bugs:** Open an issue with reproduction steps
2. **Suggest Features:** Describe use case and expected behavior
3. **Submit Pull Requests:**
   - Fork the repository
   - Create a feature branch
   - Follow existing code style
   - Add tests for new functionality
   - Update documentation
   - Submit PR with clear description

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

## Acknowledgments

- Built on the [Model Context Protocol](https://modelcontextprotocol.io/) by Anthropic
- Powered by [KiCAD](https://www.kicad.org/) open-source PCB design software
- Uses [kicad-skip](https://github.com/kicad-skip) for schematic manipulation
- [JLCSearch API](https://jlcsearch.tscircuit.com/) by [@tscircuit](https://github.com/tscircuit/jlcsearch) - Public JLCPCB parts API
- [JLCParts Database](https://github.com/yaqwsx/jlcparts) by [@yaqwsx](https://github.com/yaqwsx) - JLCPCB parts data

### Community Contributors

- [@Kletternaut](https://github.com/Kletternaut) - Routing/component tools, footprint/symbol creators, passthrough workflow, template fixes (PRs #44, #48, #49, #51, #53, #57, #59)
- [@Mehanik](https://github.com/Mehanik) - Schematic inspection/editing tools, component field positions (PRs #60, #66, #67)
- [@jflaflamme](https://github.com/jflaflamme) - Freerouting autorouter integration with Docker/Podman support (PR #68)
- [@l3wi](https://github.com/l3wi) - Local symbol library search, JLCPCB third-party library support (PR #25)
- [@gwall-ceres](https://github.com/gwall-ceres) - MCP protocol compliance, Windows compatibility (PR #10)
- [@fariouche](https://github.com/fariouche) - Bug fixes (PR #17)
- [@shuofengzhang](https://github.com/shuofengzhang) - XDG relative path handling (PR #58)
- [@sid115](https://github.com/sid115) - Windows setup script improvements (PR #13)
- [@pasrom](https://github.com/pasrom) - MCP server bug fixes (PR #50)

## Citation

If you use this project in your research or publication, please cite:

```bibtex
@software{kicad_mcp_server,
  title = {KiCAD MCP Server: AI-Assisted PCB Design},
  author = {mixelpixx},
  year = {2025},
  url = {https://github.com/mixelpixx/KiCAD-MCP-Server},
  version = {2.3.0}
}
```
