# KiCAD MCP: AI-Assisted PCB Design

KiCAD MCP is a Model Context Protocol (MCP) implementation that enables Large Language Models (LLMs) like Claude to directly interact with KiCAD for printed circuit board design. It creates a standardized communication bridge between AI assistants and the KiCAD PCB design software, allowing for natural language control of advanced PCB design operations.

## 🎉 NEW FEATURE! Schematic Generation

**We're excited to announce the addition of schematic generation capabilities!** Now, in addition to PCB design, KiCAD MCP enables AI assistants to:

- Create and manage KiCAD schematics through natural language
- Add components like resistors, capacitors, and ICs to schematics
- Connect components with wires to create complete circuits
- Save and load schematic files in KiCAD format
- Export schematics to PDF

This powerful addition completes the PCB design workflow, allowing AI assistants to help with both schematic capture and PCB layout in a single integrated environment.

## Project Status

🚧 **This project is currently undergoing a major v2.0 rebuild!** 🚧

**Current Status (Week 1/12):**
- ✅ Cross-platform support (Linux, Windows, macOS)
- ✅ CI/CD pipeline with automated testing
- ✅ Platform-agnostic path handling
- 🔄 Migrating to KiCAD IPC API (from deprecated SWIG)
- ⏳ Adding JLCPCB parts integration
- ⏳ Adding Digikey parts integration
- ⏳ Smart BOM management system

**What Works Now:**
- Basic project management (create, open, save)
- Component placement and manipulation
- Board outline and layer management
- Routing (traces, vias, copper pours)
- Design rule checking
- Export (Gerber, PDF, SVG, 3D models)

**Coming Soon (v2.0):**
- AI-assisted component selection from JLCPCB/Digikey
- Intelligent BOM management with cost optimization
- Design pattern library for common circuits
- Guided workflows for novice users
- Visual feedback and documentation generation

See [REBUILD_STATUS.md](REBUILD_STATUS.md) for detailed progress tracking.

## What It Does

KiCAD MCP transforms how engineers and designers work with KiCAD by enabling AI assistants to:

- Create and manage KiCAD PCB projects through natural language requests
- **Create schematics** with components and connections
- Manipulate board geometry, outlines, layers, and properties
- Place and organize components in various patterns (grid, circular, aligned)
- Route traces, differential pairs, and create copper pours
- Implement design rules and perform design rule checks
- Generate exports in various formats (Gerber, PDF, SVG, 3D models)
- Provide comprehensive context about the circuit board to the AI assistant

This enables a natural language-driven PCB design workflow where complex operations can be requested in plain English, while still maintaining full engineer oversight and control.

## Core Architecture

- **TypeScript MCP Server**: Implements the Anthropic Model Context Protocol specification to communicate with Claude and other compatible AI assistants
- **Python KiCAD Interface**: Handles actual KiCAD operations via pcbnew Python API and kicad-skip library with comprehensive error handling
- **Modular Design**: Organizes functionality by domains (project, schematic, board, component, routing) for maintainability and extensibility

## System Requirements

- **KiCAD 9.0 or higher** (must be fully installed with Python module)
- **Node.js v18 or higher** and npm
- **Python 3.10 or higher** with pip
- **Cline** (VSCode extension) or another MCP-compatible client
- **Operating System**:
  - ✅ **Linux** (Ubuntu 22.04+, Fedora, Arch) - Primary platform
  - ✅ **Windows 10/11** - Fully supported
  - ⚠️ **macOS** - Experimental (untested)

## Installation

Choose your platform below for detailed installation instructions:

<details>
<summary><b>🐧 Linux (Ubuntu/Debian)</b> - Click to expand</summary>

### Step 1: Install KiCAD 9.0

```bash
# Add KiCAD 9.0 PPA (Ubuntu/Debian)
sudo add-apt-repository --yes ppa:kicad/kicad-9.0-releases
sudo apt-get update

# Install KiCAD and libraries
sudo apt-get install -y kicad kicad-libraries
```

### Step 2: Install Node.js

```bash
# Install Node.js 20.x (recommended)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Verify installation
node --version  # Should be v20.x or higher
npm --version
```

### Step 3: Clone and Build

```bash
# Clone repository
git clone https://github.com/yourusername/kicad-mcp-server.git
cd kicad-mcp-server

# Install Node.js dependencies
npm install

# Install Python dependencies
pip3 install -r requirements.txt

# Build TypeScript
npm run build
```

### Step 4: Configure Cline

1. Install VSCode and the Cline extension
2. Edit Cline MCP settings:
   ```bash
   code ~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json
   ```

3. Add this configuration (adjust paths for your system):
   ```json
   {
     "mcpServers": {
       "kicad": {
         "command": "node",
         "args": ["/home/YOUR_USERNAME/kicad-mcp-server/dist/index.js"],
         "env": {
           "NODE_ENV": "production",
           "PYTHONPATH": "/usr/lib/kicad/lib/python3/dist-packages",
           "LOG_LEVEL": "info"
         },
         "description": "KiCAD PCB Design Assistant"
       }
     }
   }
   ```

4. Restart VSCode

### Step 5: Verify Installation

```bash
# Test platform detection
python3 python/utils/platform_helper.py

# Run tests (optional)
pytest tests/
```

**Troubleshooting:**
- If KiCAD Python module not found, check: `python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"`
- For PYTHONPATH issues, see: [docs/LINUX_COMPATIBILITY_AUDIT.md](docs/LINUX_COMPATIBILITY_AUDIT.md)

</details>

<details>
<summary><b>🪟 Windows 10/11</b> - Click to expand</summary>

### Step 1: Install KiCAD 9.0

1. Download KiCAD 9.0 from [kicad.org/download/windows](https://www.kicad.org/download/windows/)
2. Run the installer with default options
3. Verify Python module is installed (included by default)

### Step 2: Install Node.js

1. Download Node.js 20.x from [nodejs.org](https://nodejs.org/)
2. Run installer with default options
3. Verify in PowerShell:
   ```powershell
   node --version
   npm --version
   ```

### Step 3: Clone and Build

```powershell
# Clone repository
git clone https://github.com/yourusername/kicad-mcp-server.git
cd kicad-mcp-server

# Install dependencies
npm install
pip install -r requirements.txt

# Build
npm run build
```

### Step 4: Configure Cline

1. Install VSCode and Cline extension
2. Edit Cline MCP settings at:
   ```
   %USERPROFILE%\AppData\Roaming\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json
   ```

3. Add configuration:
   ```json
   {
     "mcpServers": {
       "kicad": {
         "command": "C:\\Program Files\\nodejs\\node.exe",
         "args": ["C:\\path\\to\\kicad-mcp-server\\dist\\index.js"],
         "env": {
           "PYTHONPATH": "C:\\Program Files\\KiCad\\9.0\\lib\\python3\\dist-packages"
         }
       }
     }
   }
   ```

4. Restart VSCode

</details>

<details>
<summary><b>🍎 macOS</b> - Click to expand (Experimental)</summary>

### Step 1: Install KiCAD 9.0

1. Download KiCAD 9.0 from [kicad.org/download/macos](https://www.kicad.org/download/macos/)
2. Drag KiCAD.app to Applications folder

### Step 2: Install Node.js

```bash
# Using Homebrew (install from brew.sh if needed)
brew install node@20

# Verify
node --version
npm --version
```

### Step 3: Clone and Build

```bash
git clone https://github.com/yourusername/kicad-mcp-server.git
cd kicad-mcp-server
npm install
pip3 install -r requirements.txt
npm run build
```

### Step 4: Configure Cline

Edit `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`:

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["/Users/YOUR_USERNAME/kicad-mcp-server/dist/index.js"],
      "env": {
        "PYTHONPATH": "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.11/lib/python3.11/site-packages"
      }
    }
  }
}
```

**Note:** macOS support is experimental. Please report issues on GitHub.

</details>

## Quick Start

After installation, test with Cline:

1. Open VSCode with Cline extension
2. Start a conversation with Claude
3. Try these commands:

```
Create a new KiCAD project named 'TestProject' in my home directory.
```

```
Set the board size to 100mm x 80mm and add a rectangular outline.
```

```
Show me the current board properties.
```

If Claude successfully executes these commands, your installation is working! 🎉

## Usage Examples

Here are some examples of what you can ask Claude to do with KiCAD MCP:

### Project Management

```
Create a new KiCAD project named 'WiFiModule' in my Documents folder.
```

```
Open the existing KiCAD project at C:/Projects/Amplifier/Amplifier.kicad_pro
```

### Schematic Design

```
Create a new schematic named 'PowerSupply'.
```

```
Add a 10kΩ resistor and 0.1µF capacitor to the schematic.
```

```
Connect the resistor's pin 1 to the capacitor's pin 1.
```

### Board Design

```
Set the board size to 100mm x 80mm.
```

```
Add a rounded rectangle board outline with 3mm corner radius.
```

```
Add mounting holes at each corner of the board, 5mm from the edges.
```

### Component Placement

```
Place a 10uF capacitor at position x=50mm, y=30mm.
```

```
Create a grid of 8 LEDs, 4x2, starting at position x=20mm, y=10mm with 10mm spacing.
```

```
Align all resistors horizontally and distribute them evenly.
```

### Routing

```
Create a new net named 'VCC' and assign it to the power net class.
```

```
Route a trace from component U1 pin 1 to component C3 pin 2 on layer F.Cu.
```

```
Add a copper pour for GND on the bottom layer.
```

### Design Rules and Export

```
Set design rules with 0.2mm clearance and 0.25mm minimum track width.
```

```
Export Gerber files to the 'fabrication' directory.
```

## Features by Category

### Project Management
- Create new KiCAD projects with customizable settings
- Open existing KiCAD projects from file paths
- Save projects with optional new locations
- Retrieve project metadata and properties

### Schematic Design
- Create new schematics with customizable settings
- Add components from symbol libraries (resistors, capacitors, ICs, etc.)
- Connect components with wires to create circuits
- Add labels, annotations, and documentation to schematics
- Save and load schematics in KiCAD format
- Export schematics to PDF for documentation

### Board Design
- Set precise board dimensions with support for metric and imperial units
- Add custom board outlines (rectangle, rounded rectangle, circle, polygon)
- Create and manage board layers with various configurations
- Add mounting holes, text annotations, and other board features
- Visualize the current board state

### Components
- Place components with specified footprints at precise locations
- Create component arrays in grid or circular patterns
- Move, rotate, and modify existing components
- Align and distribute components evenly
- Duplicate components with customizable properties
- Get detailed component properties and listings

### Routing
- Create and manage nets with specific properties
- Route traces between component pads or arbitrary points
- Add vias, including blind and buried vias
- Create differential pair routes for high-speed signals
- Generate copper pours (ground planes, power planes)
- Define net classes with specific design rules

### Design Rules
- Set global design rules for clearance, track width, etc.
- Define specific rules for different net classes
- Run Design Rule Check (DRC) to validate the design
- View and manage DRC violations

### Export
- Generate industry-standard Gerber files for fabrication
- Export PDF documentation of the PCB
- Create SVG vector graphics of the board
- Generate 3D models in STEP or VRML format
- Produce bill of materials (BOM) in various formats

## Implementation Details

The KiCAD MCP implementation uses a modular, maintainable architecture:

### TypeScript MCP Server (Node.js)
- **kicad-server.ts**: The main server that implements the MCP protocol
- Uses STDIO transport for reliable communication with Cline
- Manages the Python process for KiCAD operations
- Handles command queuing, error recovery, and response formatting

### Python Interface
- **kicad_interface.py**: The main Python interface that:
  - Parses commands received as JSON via stdin
  - Routes commands to the appropriate specialized handlers
  - Returns results as JSON via stdout
  - Handles errors gracefully with detailed information

- **Modular Command Structure**:
  - `commands/project.py`: Project creation, opening, saving
  - `commands/schematic.py`: Schematic creation and management
  - `commands/component_schematic.py`: Schematic component operations
  - `commands/connection_schematic.py`: Wire and connection management
  - `commands/library_schematic.py`: Symbol library integration
  - `commands/board/`: Modular board manipulation functions
    - `size.py`: Board size operations
    - `layers.py`: Layer management
    - `outline.py`: Board outline creation
    - `view.py`: Visualization functions
  - `commands/component.py`: PCB component placement and manipulation
  - `commands/routing.py`: Trace routing and net management
  - `commands/design_rules.py`: DRC and rule configuration
  - `commands/export.py`: Output generation in various formats

This architecture ensures that each aspect of PCB design is handled by specialized modules while maintaining a clean, consistent interface layer.

## Troubleshooting

### Common Issues and Solutions

**Problem: KiCAD MCP isn't showing up in Claude's tools**
- Make sure VSCode is completely restarted after updating the Cline MCP settings
- Verify the paths in the config are correct for your system
- Check that the `npm run build` completed successfully

**Problem: Node.js errors when launching the server**
- Ensure you're using Node.js v18 or higher
- Try running `npm install` again to ensure all dependencies are properly installed
- Check the console output for specific error messages

**Problem: Python errors or KiCAD commands failing**
- Verify that KiCAD 9.0 is properly installed
- Check that the PYTHONPATH in the configuration points to the correct location
- Try running a simple KiCAD Python script directly to ensure the pcbnew module is accessible

**Problem: Claude can't find or load your KiCAD project**
- Use absolute paths when referring to project locations
- Ensure the user running VSCode has access permissions to the directories

### Getting Help

If you encounter issues not covered in this troubleshooting section:
1. Check the console output for error messages
2. Look for similar issues in the GitHub repository's Issues section
3. Open a new issue with detailed information about the problem

## Contributing

Contributions to this project are welcome! Here's how you can help:

1. **Report Bugs**: Open an issue describing what went wrong and how to reproduce it
2. **Suggest Features**: Have an idea? Share it via an issue
3. **Submit Pull Requests**: Fixed a bug or added a feature? Submit a PR!
4. **Improve Documentation**: Help clarify or expand the documentation

Please follow the existing code style and include tests for new features.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
