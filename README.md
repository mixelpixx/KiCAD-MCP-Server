
# KiCAD MCP Server

A Model Context Protocol (MCP) server that enables AI assistants like Claude to interact with KiCAD for PCB design automation. Built on the MCP 2025-06-18 specification, this server provides comprehensive tool schemas and real-time project state access for intelligent PCB design workflows.

## Overview

The [Model Context Protocol](https://modelcontextprotocol.io/) is an open standard from Anthropic that allows AI assistants to securely connect to external tools and data sources. This implementation provides a standardized bridge between AI assistants and KiCAD, enabling natural language control of PCB design operations.

**Key Capabilities:**
- 64 fully-documented tools with JSON Schema validation
- Smart tool discovery with router pattern (reduces AI context by 70%)
- 8 dynamic resources exposing project state
- JLCPCB parts integration with 100k+ component catalog and local library search
- Full MCP 2025-06-18 protocol compliance
- Cross-platform support (Linux, Windows, macOS)
- Real-time KiCAD UI integration via IPC API (experimental)
- Comprehensive error handling and logging

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

See [Dynamic Loading Status](docs/DYNAMIC_LOADING_STATUS.md) and [Wiring Implementation Plan](docs/SCHEMATIC_WIRING_PLAN.md) for technical details.

### IPC Backend (Experimental)
We are currently implementing and testing the KiCAD 9.0 IPC API for real-time UI synchronization:
- Changes made via MCP tools appear immediately in the KiCAD UI
- No manual reload required when IPC is active
- Hybrid backend: uses IPC when available, falls back to SWIG API
- 20+ commands now support IPC including routing, component placement, and zone operations

Note: IPC features are under active development and testing. Enable IPC in KiCAD via Preferences > Plugins > Enable IPC API Server.

### Tool Discovery & Router Pattern
We've implemented an intelligent tool router to keep AI context efficient while maintaining full functionality:
- **12 direct tools** always visible for high-frequency operations
- **47 routed tools** organized into 7 categories (board, component, export, drc, schematic, library, routing)
- **4 router tools** for discovery and execution:
  - `list_tool_categories` - Browse all available categories
  - `get_category_tools` - View tools in a specific category
  - `search_tools` - Find tools by keyword
  - `execute_tool` - Run any tool with parameters

**Why this matters:** By organizing tools into discoverable categories, Claude can intelligently find and use the right tool for your task without loading all 64 tool schemas into every conversation. This reduces context consumption by up to 70% while maintaining full access to all functionality.

**Usage is seamless:** Just ask naturally - "export gerber files" or "add mounting holes" - and Claude will discover and execute the appropriate tools automatically.


### NEEDS TESTING - REPORT ISSUES
### JLCPCB Parts Integration (New!)
Complete integration with JLCPCB's parts catalog, providing two complementary approaches for component selection:

**Dual-Mode Architecture:**
1. **Local Symbol Libraries** - Search JLCPCB libraries installed via KiCAD Plugin and Content Manager (contributed by [@l3wi](https://github.com/l3wi))
2. **JLCPCB API Integration** - Access the complete 100k+ parts catalog with real-time pricing and stock data

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

The server provides 64 tools organized into functional categories. With the new router pattern, tools are automatically discovered as needed - just ask Claude what you want to accomplish!

### Project Management (4 tools)
- `create_project` - Initialize new KiCAD projects
- `open_project` - Load existing project files
- `save_project` - Save current project state
- `get_project_info` - Retrieve project metadata

### Board Operations (9 tools)
- `set_board_size` - Configure PCB dimensions
- `add_board_outline` - Create board edge (rectangle, circle, polygon)
- `add_layer` - Add custom layers to stack
- `set_active_layer` - Switch working layer
- `get_layer_list` - List all board layers
- `get_board_info` - Retrieve board properties
- `get_board_2d_view` - Generate board preview image
- `add_mounting_hole` - Place mounting holes
- `add_board_text` - Add text annotations

### Component Placement (10 tools)
- `place_component` - Place single component with footprint
- `move_component` - Reposition existing component
- `rotate_component` - Rotate component by angle
- `delete_component` - Remove component from board
- `edit_component` - Modify component properties
- `get_component_properties` - Query component details
- `get_component_list` - List all placed components
- `place_component_array` - Create component grids/patterns
- `align_components` - Align multiple components
- `duplicate_component` - Copy existing component

### Routing & Nets (8 tools)
- `add_net` - Create electrical net
- `route_trace` - Route copper traces
- `add_via` - Place vias for layer transitions
- `delete_trace` - Remove traces
- `get_nets_list` - List all nets
- `create_netclass` - Define net class with rules
- `add_copper_pour` - Create copper zones/pours
- `route_differential_pair` - Route differential signals

### Library Management (4 tools)
- `list_libraries` - List available footprint libraries
- `search_footprints` - Search for footprints
- `list_library_footprints` - List footprints in library
- `get_footprint_info` - Get footprint details

### JLCPCB Integration (5 tools)
- `download_jlcpcb_database` - Download complete JLCPCB parts catalog (one-time setup)
- `search_jlcpcb_parts` - Search 100k+ parts with parametric filters
- `get_jlcpcb_part` - Get detailed part info with pricing and footprints
- `get_jlcpcb_database_stats` - View database statistics and coverage
- `suggest_jlcpcb_alternatives` - Find cheaper or more available alternatives

### Design Rules (4 tools)
- `set_design_rules` - Configure DRC parameters
- `get_design_rules` - Retrieve current rules
- `run_drc` - Execute design rule check
- `get_drc_violations` - Get DRC error report

### Export (5 tools)
- `export_gerber` - Generate Gerber fabrication files
- `export_pdf` - Export PDF documentation
- `export_svg` - Create SVG vector graphics
- `export_3d` - Generate 3D models (STEP/VRML)
- `export_bom` - Produce bill of materials

### Schematic Design (9 tools)
**Now fully functional with DYNAMIC SYMBOL LOADING + INTELLIGENT WIRING!** (Fixed in v2.1.0 - see Issue #26)

**Component Placement:**
- `create_schematic` - Initialize new schematic from template
- `load_schematic` - Open existing schematic
- `add_schematic_component` - Place symbols with automatic dynamic loading from KiCad libraries
- `list_schematic_libraries` - List symbol libraries
- `export_schematic_pdf` - Export schematic PDF

**Wiring & Connections:** NEW in v2.1.0
- `add_schematic_wire` - Create wires between points with customizable stroke
- `add_schematic_connection` - Auto-connect pins with intelligent routing (direct, orthogonal)
- `add_schematic_net_label` - Add net labels (VCC, GND, signals) with orientation control
- `connect_to_net` - Connect component pins to named nets

**Major Enhancements:**

1. **Dynamic Symbol Loading** - Access to **ALL ~10,000 KiCad symbols**! Specify any `library` and `type` (e.g., `"library": "MCU_ST_STM32F1", "type": "STM32F103C8Tx"`) and the system automatically:
   - Searches KiCad symbol libraries
   - Injects symbol definition into your schematic
   - Creates cloneable template instance
   - Places component seamlessly
   - Fallback to 13 static templates (R, C, L, LED, etc.) when needed

2. **Intelligent Wiring System** - Professional schematic wiring with automation:
   - **Automatic pin discovery** - rotation-aware (0°, 90°, 180°, 270°)
   - **Smart routing** - direct lines or orthogonal (right-angle) paths
   - **Power symbol support** - VCC, GND, +3V3, +5V, etc.
   - **Wire graph analysis** - geometric tracing for accurate net connectivity
   - **Net label management** - local, global, and hierarchical labels
   - **Netlist generation** - accurate component/pin connection tracking
   - **S-expression precision** - guaranteed KiCad format compliance

### UI Management (2 tools)
- `check_kicad_ui` - Check if KiCAD is running
- `launch_kicad_ui` - Launch KiCAD application

## Prerequisites

### Required Software

**KiCAD 9.0 or Higher**
- Download from [kicad.org/download](https://www.kicad.org/download/)
- Must include Python module (pcbnew)
- Verify installation:
  ```bash
  python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"
  ```

**Node.js 18 or Higher**
- Download from [nodejs.org](https://nodejs.org/)
- Verify: `node --version` and `npm --version`

**Python 3.10 or Higher**
- Usually included with KiCAD
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

### Supported Platforms
- **Linux** (Ubuntu 22.04+, Fedora, Arch) - Primary platform, fully tested
- **Windows 10/11** - Fully supported with automated setup
- **macOS** - Experimental support

## Installation

### Linux (Ubuntu/Debian)

```bash
# Install KiCAD 9.0
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
- Detect KiCAD installation
- Verify prerequisites
- Install dependencies
- Build project
- Generate configuration
- Run diagnostics

**Manual Setup:**
See [Windows Installation Guide](docs/WINDOWS_SETUP.md) for detailed instructions.

### macOS

```bash
# Install KiCAD 9.0 from kicad.org/download/macos

# Install Node.js
brew install node@20

# Clone and build
git clone https://github.com/mixelpixx/KiCAD-MCP-Server.git
cd KiCAD-MCP-Server
npm install
pip3 install -r requirements.txt
npm run build
```

## Configuration

### Claude Desktop

Edit configuration file:
- **Linux/macOS:** `~/.config/Claude/claude_desktop_config.json`
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
- **Windows:** `C:\Program Files\KiCad\9.0\lib\python3\dist-packages`
- **macOS:** `/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.11/lib/python3.11/site-packages`

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

### Cline (VSCode)

Edit: `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`

Use the same configuration format as Claude Desktop above.

### Claude Code

Claude Code automatically detects MCP servers in the current directory. No additional configuration needed.

### JLCPCB Integration Setup (Optional)

The JLCPCB integration provides two modes that can be used independently or together:

**Mode 1: Local Symbol Libraries (No Setup Required)**

Install JLCPCB libraries via KiCAD's Plugin and Content Manager:
1. Open KiCAD
2. Go to Tools > Plugin and Content Manager
3. Search for "JLCPCB" or "JLC"
4. Install libraries like `JLCPCB-KiCAD-Library` or `EDA_MCP`
5. Use `search_symbols` to find components with pre-configured footprints and LCSC IDs

**Mode 2: JLCPCB API (Complete Catalog Access)**

For access to the full 100k+ parts catalog with pricing:

1. **Get API Credentials**
   - Log in to [JLCPCB](https://jlcpcb.com/)
   - Navigate to Account > API Management
   - Create API credentials and save your `appId`, `appKey`, and `appSecret`

2. **Configure Environment Variables**

   Add to your shell profile (`~/.bashrc`, `~/.zshrc`, or `~/.profile`):
   ```bash
   export JLCPCB_APP_ID="your_app_id_here"
   export JLCPCB_API_KEY="your_app_key_here"
   export JLCPCB_API_SECRET="your_app_secret_here"
   ```

   Or create a `.env` file in the project root:
   ```
   JLCPCB_APP_ID=your_app_id_here
   JLCPCB_API_KEY=your_app_key_here
   JLCPCB_API_SECRET=your_app_secret_here
   ```

3. **Download Parts Database (One-time setup, takes 5-10 minutes)**
   ```
   Ask Claude: "Download the JLCPCB parts database"
   ```
   This creates a local SQLite database at `data/jlcpcb_parts.db` with ~100k parts.

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
- **Capabilities:** Tools (59), Resources (8)
- **Tool Router:** Intelligent discovery system with 7 categories
- **Error Handling:** Standard JSON-RPC error codes

### TypeScript Server (`src/`)
- Implements MCP protocol specification
- Manages Python subprocess lifecycle
- Handles message routing and validation
- Provides logging and error recovery
- **Router System:**
  - `src/tools/registry.ts` - Tool categorization and lookup
  - `src/tools/router.ts` - Discovery and execution tools
  - Reduces AI context usage by 70% while maintaining full functionality

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
1. Check server logs: `~/.kicad-mcp/logs/kicad_interface.log`
2. Verify a project is loaded before running board operations
3. Ensure file paths are absolute, not relative
4. Check tool parameter types match schema requirements

### Windows-Specific Issues

**Symptoms:** Server fails to start on Windows

**Solutions:**
1. Run automated diagnostics: `.\setup-windows.ps1`
2. Verify Python path uses double backslashes: `C:\\Program Files\\KiCad\\9.0`
3. Check Windows Event Viewer for Node.js errors
4. See [Windows Troubleshooting Guide](docs/WINDOWS_TROUBLESHOOTING.md)

### Getting Help

1. Check the [GitHub Issues](https://github.com/mixelpixx/KiCAD-MCP-Server/issues)
2. Review server logs: `~/.kicad-mcp/logs/kicad_interface.log`
3. Open a new issue with:
   - Operating system and version
   - KiCAD version (`python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"`)
   - Node.js version (`node --version`)
   - Full error message and stack trace
   - Relevant log excerpts

## Project Status

**Current Version:** 2.1.0-alpha

**Working Features:**
- Project creation and management (PCB + Schematic)
- Board outline and sizing
- Layer management
- Component placement with footprint library loading
- Mounting holes and text annotations
- Design rule checking
- Export to Gerber, PDF, SVG, 3D
- **Schematic creation and editing (Issue #26 RESOLVED - fully functional!)**
- **DYNAMIC SYMBOL LOADING - Access to ALL ~10,000 KiCad symbols! 🚀**
- Template-based schematic workflow with automatic dynamic injection
- Symbol cloning from static templates (13 types) and dynamic libraries
- UI auto-launch
- Full MCP protocol compliance
- JLCPCB parts integration (local libraries + JLCSearch API)
- Cost optimization and component selection with 100k+ parts catalog

**Under Active Development (IPC Backend):**
- Real-time UI synchronization via KiCAD 9.0 IPC API
- IPC-enabled commands: route_trace, add_via, place_component, move_component, delete_component, add_copper_pour, refill_zones, add_board_outline, add_mounting_hole, and more
- Hybrid footprint loading (SWIG for library access, IPC for placement)
- Zone/copper pour support via IPC

Note: IPC features are experimental and under testing. Some commands may not work as expected in all scenarios.

**Planned:**
- Digikey API integration
- Mouser API integration
- Advanced routing algorithms
- Smart BOM management with real-time pricing
- AI-assisted component selection and optimization
- Design pattern library (Arduino shields, RPi HATs)
- Panelization support

See [ROADMAP.md](docs/ROADMAP.md) for detailed development timeline.

## What Do You Want to See Next?

We're actively developing new features and tools for the KiCAD MCP Server. **Your input matters!**

**We'd love to hear from you:**
- What PCB design workflows could be automated?
- Which component suppliers should we integrate next (Digikey, Mouser, Arrow, etc.)?
- What export formats or manufacturing outputs do you need?
- Are there specific routing algorithms or design patterns you want?
- What pain points in your KiCAD workflow could AI help solve?
- How can we improve the JLCPCB integration?

**Share your ideas:**
1. 💡 [Open a feature request](https://github.com/mixelpixx/KiCAD-MCP-Server/issues/new?labels=enhancement&template=feature_request.md)
2. 💬 [Join the discussion](https://github.com/mixelpixx/KiCAD-MCP-Server/discussions)
3. ⭐ Star the repo if you find it useful!

Your feedback directly shapes our development priorities. Whether it's a small quality-of-life improvement or a major new capability, we want to hear about it.

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
- JLCPCB local library search contributed by [@l3wi](https://github.com/l3wi) - [PR #25](https://github.com/mixelpixx/KiCAD-MCP-Server/pull/25)
- [JLCSearch API](https://jlcsearch.tscircuit.com/) by [@tscircuit](https://github.com/tscircuit/jlcsearch) - Public JLCPCB parts API
- [JLCParts Database](https://github.com/yaqwsx/jlcparts) by [@yaqwsx](https://github.com/yaqwsx) - JLCPCB parts data

## Citation

If you use this project in your research or publication, please cite:

```bibtex
@software{kicad_mcp_server,
  title = {KiCAD MCP Server: AI-Assisted PCB Design},
  author = {mixelpixx},
  year = {2025},
  url = {https://github.com/mixelpixx/KiCAD-MCP-Server},
  version = {2.1.0-alpha}
}
```




