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

A Model Context Protocol (MCP) server that enables AI assistants to automate KiCad PCB design. It uses the MCP 2026-07-28 stateless protocol core while retaining the SDK's legacy 2025 compatibility path for existing desktop clients.

## Install without cloning the repository

The repository now contains a publishable npm runtime plus a universal Codex/Claude Code plugin. After the `@theavi/kicad-mcp` npm release is published, users can install the plugin from the GitHub marketplace and start designing without cloning, building, creating a virtual environment, or editing MCP configuration files.

- Codex: `codex plugin marketplace add mixelpixx/KiCAD-MCP-Server`, then install **KiCad PCB Designer** from `/plugins`.
- Claude Code: `/plugin marketplace add mixelpixx/KiCAD-MCP-Server`, then `/plugin install kicad@kicad-mcp`.

KiCad 9+ and Node.js 20+ are local prerequisites. The first launch automatically creates a private Python runtime. See [Plugin distribution and installation](docs/PLUGIN_DISTRIBUTION.md) for the complete user and publisher workflow.

## Overview

The [Model Context Protocol](https://modelcontextprotocol.io/) is an open standard for connecting AI assistants to external tools and data sources. This implementation provides a standardized bridge between MCP clients and KiCad, enabling natural-language control of PCB design operations.

**Key Capabilities:**

- 180 KiCad tools across 18 categories, plus 3 supplemental discovery tools
- Structured tool results, cancellation propagation, annotations, and MRTR confirmation for destructive operations
- 18 live resources and 18 reusable prompts
- Complete schematic workflow with 27 tools and dynamic symbol loading (~10,000 symbols)
- Freerouting autorouter integration (Java, Docker, or Podman)
- Custom footprint and symbol creation tools
- JLCPCB parts integration with 2.5M+ component catalog and local library search
- Datasheet enrichment via LCSC
- MCP 2026-07-28 discovery, deterministic cacheable catalogs, and legacy 2025 client compatibility
- Cross-platform support (Linux, Windows, macOS)
- Real-time KiCAD UI integration via IPC API (experimental)
- Comprehensive error handling and logging

## Try out Arduino MCP - now you can get Claude to help in the IDE, real time!:

https://github.com/mixelpixx/arduino-ide

## What's New in v2.7.0

### MCP 2026-07-28 migration

- Migrated the server to the MCP TypeScript SDK v2, Node.js 20+, and Zod 4.
- Added modern stateless protocol negotiation while retaining legacy 2025 client compatibility.
- Added structured tool results, output schemas, safety annotations, cacheable discovery, cancellation propagation, and confirmation for destructive operations.
- Reconciled the complete TypeScript/Python command catalog and now exposes 183 first-class tools.
- Added an installable Codex/Claude plugin and a private, hash-locked Python runtime for zero-clone installation from npm.

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

- `import_eagle_project` converts Eagle `.sch` XML designs to KiCad format
  with symbol mapping, net wires, multi-gate parts, dangling-wire pruning,
  and ground-truth ERC reporting via `kicad-cli`.

### 3D model tools and interactive reload

- `add_component_3d_model` attaches STEP/WRL models to footprints.
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

See [Schematic Tools Reference](docs/SCHEMATIC_TOOLS_REFERENCE.md) for the complete schematic tool documentation.

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

All 180 KiCad capabilities are first-class MCP tools with published input and output schemas. Three additional, backend-free tools provide a convenient catalog without inventing a second execution path:

- `list_tool_categories` - Browse all 18 capability categories
- `get_category_tools` - View the tools in one category
- `search_tools` - Search names and descriptions by keyword

The catalog is populated by the same registrations used for `tools/list`, so it cannot drift from the callable tool set. Clients may call every returned tool directly by name.

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

The server publishes 18 read-only resources and templates for project, board, component, footprint, and symbol state. Stable examples include:

- `kicad://project/info`, `kicad://project/properties`, `kicad://project/status`
- `kicad://board/info`, `kicad://board/layers`, `kicad://board/statistics`
- `kicad://components` and `kicad://components/placement`
- `kicad://board/extents{?unit}` and `kicad://board/2d-view{?format,width,height,layers}`
- `kicad://component/{reference}/details` and `/connections`
- library, footprint, and symbol lookup templates

Backend failures are returned as MCP errors rather than successful error documents.

### Protocol Compliance

- TypeScript MCP SDK v2 (`@modelcontextprotocol/server`)
- Native MCP 2026-07-28 stateless requests and optional `server/discover`
- Legacy 2025 initialization compatibility on the same stdio entrypoint
- Deterministic catalogs with `ttlMs` and `cacheScope` hints
- Structured tool results, error signaling, cancellation, and MRTR confirmations

## Available Tools

The server publishes **183 first-class tools**: 180 KiCad capabilities in 18 functional categories and 3 supplemental catalog tools. The list below highlights common operations; use `list_tool_categories`, `get_category_tools`, or `search_tools` for the live authoritative catalog.

For the complete category inventory, see [Tool Inventory](docs/TOOL_INVENTORY.md). Every listed tool is directly callable through MCP.

### Project Management (6 tools)

- `create_project` - Initialize new KiCAD projects
- `open_project` - Load existing project files
- `close_project` - Release the active project and its backend state
- `save_project` - Save current project state
- `get_project_info` - Retrieve project metadata
- `snapshot_project` - Save named checkpoint snapshot

### Board Operations (12 tools)

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
- `import_svg_logo` - Import SVG file as PCB silkscreen polygons

### Component Management (16 tools)

- `place_component` - Place single component with footprint
- `move_component` - Reposition existing component
- `rotate_component` - Rotate component by angle
- `delete_component` - Remove component from board
- `edit_component` - Modify component properties
- `find_component` - Search by reference or value
- `get_component_properties` - Query component details
- `set_footprint_type` - Change through-hole/SMD footprint type
- `get_component_pads` - Get all pad information
- `get_component_list` - List all placed components
- `get_pad_position` - Get precise pad position
- `place_component_array` - Create component grids/patterns
- `align_components` - Align multiple components
- `check_courtyard_overlaps` - Detect footprint courtyard collisions
- `suggest_placement` - Generate a deterministic placement suggestion
- `duplicate_component` - Copy existing component

### Routing (16 tools)

- `add_net` - Create electrical net
- `route_trace` - Route copper traces between XY points
- `route_arc_trace` - Route an arc-shaped trace
- `route_pad_to_pad` - Route between pads with auto-via insertion
- `add_via` - Place vias for layer transitions
- `delete_trace` - Remove traces (by UUID, position, or net)
- `query_traces` - Query/filter traces
- `query_zones` - Query/filter copper zones
- `add_gnd_stitching_vias` - Place ground stitching vias
- `get_nets_list` - List all nets with statistics
- `modify_trace` - Change trace width, layer, or net
- `create_netclass` - Define net class with rules
- `add_copper_pour` - Create copper zones/pours
- `route_differential_pair` - Route differential signals
- `refill_zones` - Refill all copper zones
- `copy_routing_pattern` - Replicate routing between component groups

### Schematic (43 tools)

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
- `batch_connect` / `batch_add_and_connect` - Connect multiple pins in one operation
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

See [Schematic Tools Reference](docs/SCHEMATIC_TOOLS_REFERENCE.md) for details and examples.

### Design Rules / DRC (5 tools)

- `set_design_rules` / `get_design_rules` - Configure and inspect rules
- `run_drc` - Execute design rule check
- `get_drc_violations` - Get violation list by severity
- `add_net_class` / `create_netclass` - Net class management (compatibility and canonical names)

### Export (27 tools; selected examples)

- `export_gerber` - Gerber fabrication files
- `export_pdf` / `export_svg` - Documentation and vector graphics
- `export_3d` - 3D models (STEP, STL, VRML, OBJ)
- `export_bom` - Bill of materials (CSV, XML, HTML, JSON)
- `export_netlist` - Netlist (KiCad, Spice, Cadstar, OrcadPCB2)
- `export_position_file` - Component positions for pick and place
- `export_vrml` - VRML 3D model

### Footprint Libraries (4 tools) and Symbol Libraries (4 tools)

- `list_libraries` / `list_symbol_libraries` - Browse available libraries
- `search_footprints` / `search_symbols` - Search across all libraries
- `list_library_footprints` / `list_library_symbols` - Browse specific library
- `get_footprint_info` / `get_symbol_info` - Detailed information

### Footprint Creator (4 tools) and Symbol Creator (4 tools)

Create custom components when existing libraries do not have what you need.

- `create_footprint` / `create_symbol` - Build from scratch with pads/pins
- `edit_footprint_pad` - Modify pad properties
- `register_footprint_library` / `register_symbol_library` - Register in lib-table
- `list_footprint_libraries` / `list_symbols_in_library` - Browse custom libraries
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

- `get_backend_state` - Inspect the active KiCad backend
- `check_kicad_ui` - Check if KiCAD is running
- `launch_kicad_ui` - Launch KiCAD application

## Prerequisites

### Required Software

**KiCAD 9.0 or higher**

- Download from [kicad.org/download](https://www.kicad.org/download/)
- Must include Python module (pcbnew)
- Verify installation:
  ```bash
  python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"
  ```

**Node.js 20 or Higher**

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

# Install Node.js 20+ using your distribution package manager or the
# instructions at https://nodejs.org/en/download, then verify the version
node --version

# Clone and build
git clone https://github.com/mixelpixx/KiCAD-MCP-Server.git
cd KiCAD-MCP-Server
npm ci
npm run build
node dist/cli.js setup

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
See [Windows Troubleshooting](docs/WINDOWS_TROUBLESHOOTING.md) for detailed setup and diagnostics.

### macOS

**Important:** On macOS, let the setup command create a private runtime that can
access KiCAD's bundled `pcbnew` module. Do not install packages into KiCAD's
bundled Python.

#### Manual Setup

```bash
# Install KiCAD 9.0 from kicad.org/download/macos

# Install Node.js
brew install node@20

# Clone repository
git clone https://github.com/mixelpixx/KiCAD-MCP-Server.git
cd KiCAD-MCP-Server

# Install the locked Node.js tree and build the private-runtime CLI
npm ci
npm run build

# Create the private, hash-locked Python runtime
KICAD_PYTHON=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 \
  node dist/cli.js setup
```

The setup command creates and maintains the isolated runtime under the user's
KiCAD MCP data directory while retaining read-only access to KiCAD's `pcbnew`
module.

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
      "args": ["/path/to/KiCAD-MCP-Server/dist/cli.js", "serve"],
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

1. **KICAD_PYTHON env var** - Explicit user or packaged-launcher override (highest priority)
2. **Virtual environment** - `venv/bin/python` or `.venv/bin/python`
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
      "args": ["/path/to/KiCAD-MCP-Server/dist/cli.js", "serve"],
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

Claude Code automatically detects MCP servers in the current directory. No additional configuration needed.

### OpenCode (Windows)

OpenCode uses a different MCP configuration schema than Claude Desktop. Use
`setup-windows-opencode.ps1` to verify the local setup and write the correct
OpenCode `mcp` entry.

OpenCode project configuration is written to `opencode.json` in the target
project root. The script keeps the KiCAD MCP server repository separate from the
target project:

- `McpServerPath` is this repository, where `dist/cli.js` is built
- `ProjectPath` is the project that should receive `opencode.json`

**When this is useful:**

- You use [OpenCode](https://opencode.ai/) as your MCP client on Windows
- You want a project-local MCP server available only in one project
- You want a global OpenCode MCP server available from any workspace
- You need to verify KiCAD Python (`pcbnew`), Node.js, and `dist/cli.js`
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
      "command": ["node", "C:\\path\\to\\KiCAD-MCP-Server\\dist\\cli.js", "serve"],
      "environment": {
        "NODE_ENV": "production",
        "LOG_LEVEL": "info",
        "KICAD_AUTO_LAUNCH": "false",
        "KICAD_MCP_DEV": "0",
        "KICAD_BACKEND": "auto",
        "PYTHONPATH": "C:\\Program Files\\KiCad\\10.0\\bin\\Lib\\site-packages"
      },
      "enabled": true,
      "timeout": 3900000
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
`-McpServerPath` so the generated config points to the correct `dist/cli.js serve` entrypoint:

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
   - Create API credentials and save the app ID, access key, and secret key
   - Note: This requires prior order history and enterprise account approval

2. **Configure Environment Variables**

   Add to your shell profile (`~/.bashrc`, `~/.zshrc`, or `~/.profile`):

   ```bash
   export JLCPCB_APP_ID="your_app_id_here"
   export JLCPCB_API_KEY="your_access_key_here"
   export JLCPCB_API_SECRET="your_secret_key_here"
   ```

   Set the same three values in the MCP launcher's `env` configuration when it
   does not inherit your shell profile. The server does not automatically load
   project-root `.env` files.

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

- **Transport:** Local stdio with SDK-managed JSON-RPC framing
- **Protocol:** MCP 2026-07-28 stateless core plus legacy 2025 initialization compatibility
- **Capabilities:** 183 tools, 18 resources/templates, and 18 prompts
- **Discovery:** Deterministic `tools/list` plus 3 supplemental catalog tools
- **Results:** Structured output, standard MCP errors, cancellation propagation, cache hints, and MRTR confirmations

### TypeScript Server (`src/`)

- Uses `@modelcontextprotocol/server` v2 and `serveStdio()` for protocol-era negotiation
- Manages Python subprocess readiness, bounded restart, request correlation, timeout, and cancellation
- Registers Zod 4 input/output schemas, resources, prompts, annotations, and structured results
- Builds `src/tools/registry.ts` from the same first-class tool registrations used by MCP
- Provides `src/tools/router.ts` only for catalog browsing and search; it is not a second execution layer

### Python Interface (`python/`)

- **kicad_interface.py:** Private newline-JSON command worker used only by the TypeScript MCP server
- **kicad_api/:** Backend implementations
  - `base.py` - Abstract base classes for backends
  - `ipc_backend.py` - KiCAD 9.0 IPC API backend (real-time UI sync)
  - `swig_backend.py` - pcbnew SWIG API backend (file-based operations)
  - `factory.py` - Backend auto-detection and instantiation
- **schemas/tool_schemas.py:** Legacy/internal Python validation schemas (not the MCP catalog)
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
# Install the locked Node.js dependency tree
npm ci

# Build TypeScript
npm run build

# Create the private runtime from requirements-lock.txt
node dist/cli.js setup

# Optional: install hash-locked Python development tools in a separate venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev-lock.txt

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

1. Verify build completed: `ls dist/cli.js`
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

1. Check the current server log: `~/.kicad-mcp/logs/kicad-mcp-YYYY-MM-DD.log`
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
2. Review the current server log: `~/.kicad-mcp/logs/kicad-mcp-YYYY-MM-DD.log`
3. Open a new issue with:
   - Operating system and version
   - KiCAD version (`python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"`)
   - Node.js version (`node --version`)
   - Full error message and stack trace
   - Relevant log excerpts

## Project Status

**Current Version:** 2.7.0

See [STATUS_SUMMARY.md](docs/STATUS_SUMMARY.md) for the complete status matrix and [CHANGELOG.md](CHANGELOG.md) for detailed release notes.

**Working Features (180 KiCad tools + 3 discovery tools):**

- Project management with snapshot checkpointing
- Complete board design (outline, layers, zones, mounting holes, text, SVG logos)
- Component placement with arrays, alignment, and duplication
- Advanced routing (pad-to-pad with auto-via, differential pairs, pattern copying)
- Complete schematic workflow with dynamic symbol loading (~10,000 symbols)
- Intelligent wiring system with pin discovery and smart routing
- FFC/ribbon cable passthrough workflow
- Schematic-to-board synchronization
- Design rule checking (DRC and ERC)
- Export to Gerber, PDF, SVG, 3D, BOM, netlist, position file
- Custom footprint and symbol creation
- JLCPCB parts integration (2.5M+ parts catalog)
- Datasheet enrichment via LCSC
- Freerouting autorouter integration (Java, Docker, Podman)
- UI auto-launch and management
- MCP 2026-07-28 support with legacy 2025 client compatibility

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
