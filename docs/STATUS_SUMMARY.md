# KiCAD MCP - Current Status Summary

**Date:** 2026-08-11
**Version:** 2.7.0
**Phase:** Active development with community contributions

---

## Quick Stats

| Metric                      | Value                                     |
| --------------------------- | ----------------------------------------- |
| Total MCP Tools             | 183 first-class                           |
| KiCad Capability Categories | 18                                        |
| MCP Resources               | 18 registrations                          |
| MCP Prompts                 | 18                                        |
| KiCAD 9.0 Compatible        | Yes (verified)                            |
| Platforms                   | Linux, Windows, macOS                     |
| JLCPCB Parts Catalog        | 2.5M+ components                          |
| Symbol Access               | ~10,000 via dynamic loading               |
| Footprint Libraries         | 153+ auto-discovered                      |
| Contributors                | 10+                                       |
| MCP Protocol Version        | 2026-07-28 plus legacy 2025 compatibility |

---

## Feature Completion Matrix

| Feature Category         | Status   | Tool Count | Details                                                      |
| ------------------------ | -------- | ---------: | ------------------------------------------------------------ |
| Project Management       | Complete |          6 | Create, open, close, save, inspect, snapshot                 |
| Board Setup              | Complete |         12 | Size, outline, layers, mounting, zones, text, rendering      |
| Component Placement      | Complete |         16 | Place, move, inspect, edit, delete, arrays, alignment        |
| Routing                  | Complete |         16 | Traces, vias, pad routing, differential pairs, nets, zones   |
| Design Rules / DRC       | Complete |          5 | Rules, net classes, DRC execution and findings               |
| Export and Manufacturing | Complete |         27 | Gerber, drill, BOM, position, drawings, 3D and interchange   |
| Schematic                | Complete |         43 | Components, wiring, labels, ERC, inspection, export and sync |
| Schematic Batch          | Complete |          9 | Batched placement, wiring, labels and edits                  |
| Schematic Hierarchy      | Complete |          2 | Sheet creation and listing                                   |
| Schematic Layout         | Complete |          4 | Field layout, snapping and decluttering                      |
| Libraries                | Complete |         10 | Footprint and symbol library discovery                       |
| Footprints               | Complete |          7 | Creation, pads, libraries and 3D models                      |
| Symbols                  | Complete |          8 | Creation, properties, import, export and updates             |
| Datasheets               | Complete |          2 | Datasheet lookup and enrichment                              |
| JLCPCB                   | Complete |          5 | Local DB, search, part details, stats, alternatives          |
| Freerouting              | Complete |          4 | Autoroute, DSN export, SES import, availability              |
| EAGLE Import             | Complete |          1 | Project import                                               |
| UI and Backend State     | Complete |          3 | Check, launch and inspect backend state                      |
| Supplemental Discovery   | Complete |          3 | Category listing, category lookup and search                 |

---

## Architecture

### SWIG Backend (File-based) -- Default

- **Status:** Stable
- Direct pcbnew API access via KiCAD's Python bindings
- Requires manual KiCAD UI reload to see changes
- Works without KiCAD running
- Auto-saves after every board-modifying command

### IPC Backend (Real-time) -- Experimental

- **Status:** Functional, 21 commands implemented
- Real-time UI synchronization with KiCAD 9+
- Requires KiCAD running with IPC API enabled
- Automatic fallback to SWIG when unavailable

### Hybrid Approach

The server automatically selects the best backend:

- IPC when KiCAD is running with IPC enabled
- SWIG fallback when IPC is unavailable
- Some operations use both (e.g., footprint placement)

---

## Platform Support

### Linux -- Primary Platform

- KiCAD 9.0 detection: Working
- Process management: Working
- Library discovery: Working (153+ libraries)
- IPC backend: Working

### Windows -- Fully Supported

- Automated setup script (setup-windows.ps1)
- Process detection via Toolhelp32 API
- Library paths auto-detected
- Troubleshooting guide available (WINDOWS_TROUBLESHOOTING.md)

### macOS -- Community Supported

- Automated setup script (setup-macos.sh)
- Auto-detects KiCad Python and pcbnew
- Generates Claude Desktop configuration
- Process detection implemented
- Library paths auto-configured
- Needs community testing

---

## Recent Development Highlights

### v2.7.0 (2026-08-11)

- MCP TypeScript SDK v2, Node.js 20+, and Zod 4
- MCP 2026-07-28 negotiation with legacy 2025 compatibility through `serveStdio`
- Deterministic cache hints, structured results, annotations, and destructive-operation confirmation
- 183 first-class tools with runtime-derived catalog metadata
- Correlated and cancellable Python worker bridge

### v2.2.3 (2026-03-11)

- FFC/ribbon cable passthrough workflow (connect_passthrough, sync_schematic_to_board)
- Project snapshot system
- SVG logo import
- ERC validation
- Developer mode (KICAD_MCP_DEV=1)
- Critical B.Cu routing fixes

### v2.2.2-alpha (2026-03-01)

- route_pad_to_pad with auto-via insertion
- copy_routing_pattern for trace replication
- Project-local library resolution

### v2.2.1-alpha (2026-02-28)

- edit_schematic_component with field position support
- Footprint and symbol creator tools

### v2.2.0-alpha (2026-02-27)

- 13 new routing/component tools
- Datasheet enrichment tools
- SWIG/UUID bug fixes

### v2.1.0-alpha (2026-01-10)

- Complete schematic wiring system
- Dynamic symbol loading (~10,000 symbols)
- JLCPCB parts integration
- Historical router prototype (superseded by the first-class catalog)

---

## Community Contributors

| Contributor   | Key Contributions                                                              |
| ------------- | ------------------------------------------------------------------------------ |
| Kletternaut   | Routing tools, footprint/symbol creators, passthrough workflow, template fixes |
| Mehanik       | Schematic inspection/editing tools, component field positions                  |
| jflaflamme    | Freerouting autorouter integration with Docker/Podman                          |
| l3wi          | Local symbol library search, JLCPCB third-party library support                |
| gwall-ceres   | MCP protocol compliance, Windows compatibility                                 |
| fariouche     | Bug fixes                                                                      |
| shuofengzhang | XDG relative path handling                                                     |
| sid115        | Windows setup script improvements                                              |
| pasrom        | MCP server bug fixes                                                           |

---

## Getting Help

**For Users:**

1. Check [README.md](../README.md) for installation
2. Review [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for common problems
3. Check logs: `~/.kicad-mcp/logs/kicad-mcp-YYYY-MM-DD.log`

**For Contributors:**

1. Read [CONTRIBUTING.md](../CONTRIBUTING.md) for development setup
2. Check [ARCHITECTURE.md](ARCHITECTURE.md) for system design
3. Review the [Documentation Index](INDEX.md) for all available docs

**Issues:**

- Open an issue on GitHub with OS, KiCAD version, and error details

---

_Last Updated: 2026-08-11_
