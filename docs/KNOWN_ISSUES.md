# Known Issues & Workarounds

**Last Updated:** 2025-12-02
**Version:** 2.1.0-alpha

This document tracks known issues and provides workarounds where available.

---

## Current Issues

### 1. `get_board_info` KiCAD 9.0 API Issue

**Status:** KNOWN - Non-critical

**Symptoms:**
```
AttributeError: 'BOARD' object has no attribute 'LT_USER'
```

**Root Cause:** KiCAD 9.0 changed layer enumeration constants

**Workaround:** Use `get_project_info` instead for basic project details

**Impact:** Low - informational command only

---

### 2. Zone Filling via SWIG Causes Segfault

**Status:** KNOWN - Workaround available

**Symptoms:**
- Copper pours created but not filled automatically when using SWIG backend
- Calling `ZONE_FILLER` via SWIG causes segfault

**Workaround Options:**
1. Use IPC backend (zones fill correctly via IPC)
2. Open the board in KiCAD UI - zones fill automatically when opened

**Impact:** Medium - affects copper pour visualization until opened in KiCAD

---

### 3. UI Manual Reload Required (SWIG Backend)

**Status:** BY DESIGN - Fixed by IPC

**Symptoms:**
- MCP makes changes via SWIG backend
- KiCAD doesn't show changes until file is reloaded

**Current Workflow:**
```
1. MCP makes change via SWIG
2. KiCAD shows: "File has been modified. Reload? [Yes] [No]"
3. User clicks "Yes"
4. Changes appear in UI
```

**Why:** SWIG-based backend requires file I/O, can't push changes to running UI

**Fix:** Use IPC backend for real-time updates (requires KiCAD to be running with IPC enabled)

**Workaround:** Click reload prompt or use File > Revert

---

### 4. IPC Backend Experimental

**Status:** UNDER DEVELOPMENT

**Description:**
The IPC backend is currently being implemented and tested. Some commands may not work as expected in all scenarios.

**Known IPC Limitations:**
- KiCAD must be running with IPC enabled
- Some commands fall back to SWIG (e.g., delete_trace)
- Footprint loading uses hybrid approach (SWIG for library, IPC for placement)
- Error handling may not be comprehensive in all cases

**Workaround:** If IPC fails, the server automatically falls back to SWIG backend

---

### 5. Schematic Support Limited

**Status:** KNOWN - Partial support

**Description:**
Schematic operations use the kicad-skip library which has some limitations with KiCAD 9.0 file format changes.

**Affected Commands:**
- `create_schematic`
- `add_schematic_component`
- `add_schematic_wire`

**Workaround:** Manual schematic creation may be more reliable for complex designs

---

## Recently Fixed

### DRC Violations API KiCAD 9.0 (Fixed 2026-02-26)

**Was:** `get_drc_violations` failed with `AttributeError: 'BOARD' object has no attribute 'GetDRCMarkers'`
**Now:** Reimplemented to use `run_drc()` internally which calls kicad-cli
**Impact:** Maintains backward compatibility while using stable kicad-cli interface

### Component Library Integration (Fixed 2025-11-01)

**Was:** Could not find footprint libraries
**Now:** Auto-discovers 153 KiCAD footprint libraries, search and list working

### Routing Operations KiCAD 9.0 (Fixed 2025-11-01)

**Was:** Multiple API compatibility issues with KiCAD 9.0
**Now:** All routing commands tested and working:
- `netinfo.FindNet()` -> `netinfo.NetsByName()[name]`
- `zone.SetPriority()` -> `zone.SetAssignedPriority()`
- `ZONE_FILL_MODE_POLYGON` -> `ZONE_FILL_MODE_POLYGONS`

### KiCAD Process Detection (Fixed 2025-10-26)

**Was:** `check_kicad_ui` detected MCP server's own processes
**Now:** Properly filters to only detect actual KiCAD binaries

### set_board_size KiCAD 9.0 (Fixed 2025-10-26)

**Was:** Failed with `BOX2I_SetSize` type error
**Now:** Works with KiCAD 9.0 API

### add_board_text KiCAD 9.0 (Fixed 2025-10-26)

**Was:** Failed with `EDA_ANGLE` type error
**Now:** Works with KiCAD 9.0 API

### Schematic Parameter Mismatch (Fixed 2025-12-02)

**Was:** `create_schematic` failed due to parameter name differences between TypeScript and Python
**Now:** Accepts multiple parameter naming conventions (`name`, `projectName`, `title`, `filename`)

---

## Reporting New Issues

If you encounter an issue not listed here:

1. **Check MCP logs:** `~/.kicad-mcp/logs/kicad_interface.log`
2. **Check KiCAD version:** `python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"` (must be 9.0+)
3. **Try the operation in KiCAD directly** - is it a KiCAD issue?
4. **Open GitHub issue** with:
   - Error message
   - Log excerpt
   - Steps to reproduce
   - KiCAD version
   - OS and version

---

## Priority Matrix

| Issue | Priority | Impact | Status |
|-------|----------|--------|--------|
| IPC Backend Testing | High | Medium | In Progress |
| get_board_info Fix | Low | Low | Known |
| Zone Filling (SWIG) | Medium | Medium | Workaround Available |
| Schematic Support | Medium | Medium | Partial |

---

## General Workarounds

### Server Won't Start
```bash
# Check Python can import pcbnew
python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"

# Check paths
python3 python/utils/platform_helper.py
```

### Commands Fail After Server Restart
```
# Board reference is lost on restart
# Always run open_project after server restart
```

### KiCAD UI Doesn't Show Changes (SWIG Mode)
```
# File > Revert (or click reload prompt)
# Or: Close and reopen file in KiCAD
# Or: Use IPC backend for automatic updates
```

### IPC Not Connecting
```
# Ensure KiCAD is running
# Enable IPC: Preferences > Plugins > Enable IPC API Server
# Have a board open in PCB editor
# Check socket exists: ls /tmp/kicad/api.sock
```

---

**Need Help?**
- Check [IPC_BACKEND_STATUS.md](IPC_BACKEND_STATUS.md) for IPC details
- Check [REALTIME_WORKFLOW.md](REALTIME_WORKFLOW.md) for workflow tips
- Check logs: `~/.kicad-mcp/logs/kicad_interface.log`
- Open an issue on GitHub
