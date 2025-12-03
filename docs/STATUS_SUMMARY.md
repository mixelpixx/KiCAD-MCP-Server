# KiCAD MCP - Current Status Summary

**Date:** 2025-12-02
**Version:** 2.1.0-alpha
**Phase:** IPC Backend Implementation and Testing

---

## Quick Stats

| Metric | Value | Status |
|--------|-------|--------|
| Core Features Working | 18/20 | 90% |
| KiCAD 9.0 Compatible | Yes | Verified |
| UI Auto-launch | Working | Verified |
| Component Placement | Working | Verified |
| Component Libraries | 153 libraries | Verified |
| Routing Operations | Working | Verified |
| IPC Backend | Under Testing | Experimental |
| Tests Passing | 18/20 | 90% |

---

## What's Working (Verified 2025-12-02)

### Project Management
- `create_project` - Create new KiCAD projects
- `open_project` - Load existing PCB files
- `save_project` - Save changes to disk
- `get_project_info` - Retrieve project metadata

### Board Design
- `set_board_size` - Set dimensions (KiCAD 9.0 fixed)
- `add_board_outline` - Rectangle, circle, polygon outlines
- `add_mounting_hole` - Mounting holes with pads
- `add_board_text` - Text annotations (KiCAD 9.0 fixed)
- `add_layer` - Custom layer creation
- `set_active_layer` - Layer switching
- `get_layer_list` - List all layers

### Component Operations
- `place_component` - Place components with library footprints (KiCAD 9.0 fixed)
- `move_component` - Move components
- `rotate_component` - Rotate components (EDA_ANGLE fixed)
- `delete_component` - Remove components
- `list_components` - Get all components on board

**Footprint Library Integration:**
- Auto-discovered 153 KiCAD footprint libraries
- Search footprints by pattern (`search_footprints`)
- List library contents (`list_library_footprints`)
- Get footprint info (`get_footprint_info`)
- Support for both `Library:Footprint` and `Footprint` formats

**KiCAD 9.0 API Fixes:**
- `SetOrientation()` uses `EDA_ANGLE(degrees, DEGREES_T)`
- `GetOrientation()` returns `EDA_ANGLE`, call `.AsDegrees()`
- `GetFootprintName()` now `GetFPIDAsString()`

### Routing Operations
- `add_net` - Create electrical nets
- `route_trace` - Add copper traces (KiCAD 9.0 fixed)
- `add_via` - Add vias between layers (KiCAD 9.0 fixed)
- `add_copper_pour` - Add copper zones/pours (KiCAD 9.0 fixed)
- `route_differential_pair` - Differential pair routing

**KiCAD 9.0 API Fixes:**
- `netinfo.FindNet()` now `netinfo.NetsByName()[name]`
- `zone.SetPriority()` now `zone.SetAssignedPriority()`
- `ZONE_FILL_MODE_POLYGON` now `ZONE_FILL_MODE_POLYGONS`
- Zone outline requires `outline.NewOutline()` first

### UI Management
- `check_kicad_ui` - Detect running KiCAD
- `launch_kicad_ui` - Auto-launch with project

### Export
- `export_gerber` - Manufacturing files
- `export_pdf` - Documentation
- `export_svg` - Vector graphics
- `export_3d` - STEP/VRML models
- `export_bom` - Bill of materials

### Design Rules
- `set_design_rules` - DRC configuration
- `get_design_rules` - Rule inspection
- `run_drc` - Design rule check

---

## IPC Backend (Under Development)

We are currently implementing and testing the KiCAD 9.0 IPC API for real-time UI synchronization. This is experimental and may not work perfectly in all scenarios.

### IPC-Capable Commands (21 total)

The following commands have IPC handlers implemented:

| Command | IPC Handler | Notes |
|---------|-------------|-------|
| `route_trace` | `_ipc_route_trace` | Implemented |
| `add_via` | `_ipc_add_via` | Implemented |
| `add_net` | `_ipc_add_net` | Implemented |
| `delete_trace` | `_ipc_delete_trace` | Falls back to SWIG |
| `get_nets_list` | `_ipc_get_nets_list` | Implemented |
| `add_copper_pour` | `_ipc_add_copper_pour` | Implemented |
| `refill_zones` | `_ipc_refill_zones` | Implemented |
| `add_text` | `_ipc_add_text` | Implemented |
| `add_board_text` | `_ipc_add_text` | Implemented |
| `set_board_size` | `_ipc_set_board_size` | Implemented |
| `get_board_info` | `_ipc_get_board_info` | Implemented |
| `add_board_outline` | `_ipc_add_board_outline` | Implemented |
| `add_mounting_hole` | `_ipc_add_mounting_hole` | Implemented |
| `get_layer_list` | `_ipc_get_layer_list` | Implemented |
| `place_component` | `_ipc_place_component` | Hybrid (SWIG+IPC) |
| `move_component` | `_ipc_move_component` | Implemented |
| `rotate_component` | `_ipc_rotate_component` | Implemented |
| `delete_component` | `_ipc_delete_component` | Implemented |
| `get_component_list` | `_ipc_get_component_list` | Implemented |
| `get_component_properties` | `_ipc_get_component_properties` | Implemented |
| `save_project` | `_ipc_save_project` | Implemented |

### How IPC Works

When KiCAD is running with IPC enabled:
1. Commands check if IPC is connected
2. If connected, use IPC handler for real-time UI updates
3. If not connected, fall back to SWIG API

**To enable IPC:**
1. KiCAD 9.0+ must be running
2. Enable IPC API: `Preferences > Plugins > Enable IPC API Server`
3. Have a board open in the PCB editor

### Known Limitations

- KiCAD must be running for IPC to work
- Some commands may not work as expected (still testing)
- Footprint loading uses hybrid approach (SWIG for library, IPC for placement)
- Delete trace falls back to SWIG (IPC API limitation)

---

## What Needs Work

### Minor Issues (NON-BLOCKING)

**1. get_board_info layer constants**
- Error: `AttributeError: 'BOARD' object has no attribute 'LT_USER'`
- Impact: Low (informational command only)
- Workaround: Use `get_project_info` or read components directly

**2. Zone filling via SWIG**
- Copper pours created but not filled automatically via SWIG
- Cause: SWIG API segfault when calling `ZONE_FILLER`
- Workaround: Use IPC backend or zones are filled when opened in KiCAD UI

**3. UI manual reload (SWIG mode)**
- User must manually reload to see MCP changes when using SWIG
- Impact: Workflow friction
- Workaround: Use IPC backend for automatic updates

---

## Architecture Status

### SWIG Backend (File-based)
- **Status:** Stable and functional
- **Pros:** No KiCAD process required, works offline, reliable
- **Cons:** Requires manual file reload for UI updates, no zone filling
- **Use Case:** Offline work, automated pipelines, batch operations

### IPC Backend (Real-time)
- **Status:** Under active development and testing
- **Pros:** Real-time UI updates, no file I/O for many operations, zone filling works
- **Cons:** Requires KiCAD running, experimental
- **Use Case:** Interactive design sessions, paired programming with AI

### Hybrid Approach
The server automatically selects the best backend:
- IPC when KiCAD is running with IPC enabled
- SWIG fallback when IPC is unavailable

---

## Feature Completion Matrix

| Feature Category | Status | Details |
|-----------------|--------|---------|
| Project Management | 100% | Create, open, save, info |
| Board Setup | 100% | Size, outline, mounting holes |
| Component Placement | 100% | Place, move, rotate, delete + 153 libraries |
| Routing | 90% | Traces, vias, copper (zone filling via IPC) |
| Design Rules | 100% | Set, get, run DRC |
| Export | 100% | Gerber, PDF, SVG, 3D, BOM |
| UI Integration | 85% | Launch, check, IPC auto-updates |
| IPC Backend | 60% | Under testing, 21 commands implemented |
| JLCPCB Integration | 0% | Planned |

---

## Developer Setup Status

### Linux - Primary Platform
- KiCAD 9.0 detection: Working
- Process management: Working
- venv support: Working
- Library discovery: Working (153 libraries)
- Testing: Working
- IPC backend: Under testing

### Windows - Supported
- Automated setup script (`setup-windows.ps1`)
- Process detection implemented
- Library paths auto-detected
- Comprehensive error diagnostics
- Startup validation with helpful errors
- Troubleshooting guide (WINDOWS_TROUBLESHOOTING.md)

### macOS - Untested
- Configuration provided
- Process detection implemented
- Library paths configured
- Needs community testing

---

## Documentation Status

### Complete
- [x] README.md
- [x] ROADMAP.md
- [x] IPC_BACKEND_STATUS.md
- [x] IPC_API_MIGRATION_PLAN.md
- [x] REALTIME_WORKFLOW.md
- [x] LIBRARY_INTEGRATION.md
- [x] KNOWN_ISSUES.md
- [x] UI_AUTO_LAUNCH.md
- [x] VISUAL_FEEDBACK.md
- [x] CLIENT_CONFIGURATION.md
- [x] BUILD_AND_TEST_SESSION.md
- [x] STATUS_SUMMARY.md (this document)
- [x] WINDOWS_SETUP.md
- [x] WINDOWS_TROUBLESHOOTING.md

### Needed
- [ ] EXAMPLE_PROJECTS.md
- [ ] CONTRIBUTING.md
- [ ] API_REFERENCE.md

---

## What's Next?

### Immediate Priorities
1. **Complete IPC Testing** - Verify all 21 IPC handlers work correctly
2. **Fix Edge Cases** - Address any issues found during testing
3. **Improve Error Handling** - Better fallback behavior

### Planned Features
- JLCPCB parts integration
- Digikey API integration
- Advanced routing algorithms
- Smart BOM management
- Design pattern library (Arduino shields, RPi HATs)

---

## Getting Help

**For Users:**
1. Check [README.md](../README.md) for installation
2. Review [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for common problems
3. Check logs: `~/.kicad-mcp/logs/kicad_interface.log`

**For Developers:**
1. Read [BUILD_AND_TEST_SESSION.md](BUILD_AND_TEST_SESSION.md)
2. Check [ROADMAP.md](ROADMAP.md) for priorities
3. Review [IPC_BACKEND_STATUS.md](IPC_BACKEND_STATUS.md) for IPC details

**Issues:**
- Open an issue on GitHub with OS, KiCAD version, and error details

---

*Last Updated: 2025-12-02*
*Maintained by: KiCAD MCP Team*
