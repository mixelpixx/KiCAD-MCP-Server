# KiCAD MCP Server

A Model Context Protocol (MCP) server that enables AI assistants like Claude to interact with KiCAD for PCB design automation. Built on the MCP 2025-06-18 specification, this server provides comprehensive tool schemas and real-time project state access for intelligent PCB design workflows.

## Overview

The [Model Context Protocol](https://modelcontextprotocol.io/) is an open standard from Anthropic that allows AI assistants to securely connect to external tools and data sources. This implementation provides a standardized bridge between AI assistants and KiCAD, enabling natural language control of PCB design operations.

**Key Capabilities:**
- 59 fully-documented tools with JSON Schema validation
- Smart tool discovery with router pattern (reduces AI context by 70%)
- 8 dynamic resources exposing project state
- Full MCP 2025-06-18 protocol compliance
- Cross-platform support (Linux, Windows, macOS)
- Real-time KiCAD UI integration via IPC API (experimental)
- Comprehensive error handling and logging

## What's New in v2.1.0

### IPC Backend (Experimental)
We are currently implementing and testing the KiCAD 9.0 IPC API for real-time UI synchronization:
- Changes made via MCP tools appear immediately in the KiCAD UI
- No manual reload required when IPC is active
- Hybrid backend: uses IPC when available, falls back to SWIG API
- 20+ commands now support IPC including routing, component placement, and zone operations

Note: IPC features are under active development and testing. Enable IPC in KiCAD via Preferences > Plugins > Enable IPC API Server.

### Tool Discovery & Router Pattern (New!)
We've implemented an intelligent tool router to keep AI context efficient while maintaining full functionality:
- **12 direct tools** always visible for high-frequency operations
- **47 routed tools** organized into 7 categories (board, component, export, drc, schematic, library, routing)
- **4 router tools** for discovery and execution:
  - `list_tool_categories` - Browse all available categories
  - `get_category_tools` - View tools in a specific category
  - `search_tools` - Find tools by keyword
  - `execute_tool` - Run any tool with parameters

**Why this matters:** By organizing tools into discoverable categories, Claude can intelligently find and use the right tool for your task without loading all 59 tool schemas into every conversation. This reduces context consumption by up to 70% while maintaining full access to all functionality.

**Usage is seamless:** Just ask naturally - "export gerber files" or "add mounting holes" - and Claude will discover and execute the appropriate tools automatically.

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

The server provides 59 tools organized into functional categories. With the new router pattern, tools are automatically discovered as needed - just ask Claude what you want to accomplish!

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

### Schematic Design (6 tools)
- `create_schematic` - Initialize new schematic
- `load_schematic` - Open existing schematic
- `add_schematic_component` - Place symbols
- `add_schematic_wire` - Connect component pins
- `list_schematic_libraries` - List symbol libraries
- `export_schematic_pdf` - Export schematic PDF

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

### Cline (VSCode)

Edit: `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`

Use the same configuration format as Claude Desktop above.

### Claude Code

Claude Code automatically detects MCP servers in the current directory. No additional configuration needed.

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
- Project creation and management
- Board outline and sizing
- Layer management
- Component placement with footprint library loading
- Mounting holes and text annotations
- Design rule checking
- Export to Gerber, PDF, SVG, 3D
- Schematic creation and editing
- UI auto-launch
- Full MCP protocol compliance

**Under Active Development (IPC Backend):**
- Real-time UI synchronization via KiCAD 9.0 IPC API
- IPC-enabled commands: route_trace, add_via, place_component, move_component, delete_component, add_copper_pour, refill_zones, add_board_outline, add_mounting_hole, and more
- Hybrid footprint loading (SWIG for library access, IPC for placement)
- Zone/copper pour support via IPC

Note: IPC features are experimental and under testing. Some commands may not work as expected in all scenarios.

**Planned:**
- JLCPCB parts integration
- Digikey API integration
- Advanced routing algorithms
- Smart BOM management
- AI-assisted component selection
- Design pattern library (Arduino shields, RPi HATs)

See [ROADMAP.md](docs/ROADMAP.md) for detailed development timeline.

## What Do You Want to See Next?

We're actively developing new features and tools for the KiCAD MCP Server. **Your input matters!**

**We'd love to hear from you:**
- What PCB design workflows could be automated?
- Which component suppliers should we integrate (JLCPCB, Digikey, Mouser, etc.)?
- What export formats or manufacturing outputs do you need?
- Are there specific routing algorithms or design patterns you want?
- What pain points in your KiCAD workflow could AI help solve?

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

