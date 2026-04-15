# Known Issues & Workarounds

**Last Updated:** 2026-03-21
**Version:** 2.2.3

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
2. Open the board in KiCAD UI -- zones fill automatically when opened
3. Use `refill_zones` tool (may still segfault in some configurations)

**Impact:** Medium - affects copper pour visualization until opened in KiCAD

---

### 3. UI Manual Reload Required (SWIG Backend)

**Status:** BY DESIGN

**Symptoms:**

- MCP makes changes via SWIG backend
- KiCAD does not show changes until file is reloaded

**Why:** SWIG-based backend modifies files directly and cannot push changes to a running UI

**Fix:** Use IPC backend for real-time updates (requires KiCAD running with IPC enabled)

**Workaround:** Click the reload prompt in KiCAD or use File > Revert

---

### 4. IPC Backend Limitations

**Status:** EXPERIMENTAL

**Known Limitations:**

- KiCAD must be running with IPC enabled (Preferences > Plugins > Enable IPC API Server)
- Some commands fall back to SWIG (e.g., delete_trace)
- Footprint loading uses hybrid approach (SWIG for library, IPC for placement)

**Workaround:** The server automatically falls back to SWIG backend when IPC is unavailable

---

### 5. package.json Version Mismatch

**Status:** KNOWN - Non-critical

**Symptoms:** package.json shows version 2.1.0-alpha while CHANGELOG documents version 2.2.3

**Impact:** Cosmetic only. CHANGELOG.md is the authoritative version reference.

---

## Recently Fixed (v2.2.0 - v2.2.3)

### B.Cu Footprint Routing (Fixed v2.2.3)

- `route_pad_to_pad` now correctly detects B.Cu footprints and inserts vias
- KiCAD 9 SWIG `pad.GetLayerName()` always returned F.Cu for flipped footprints -- fixed using `footprint.GetLayer()`

### B.Cu Placement Hang (Fixed v2.2.3)

- Placing footprints on B.Cu no longer causes ~30s freeze
- Fix: call `board.Add()` before `Flip()`

### Board Outline Rounded Corners (Fixed v2.2.3)

- `add_board_outline` now correctly applies cornerRadius for rounded_rectangle shape

### Project-Local Library Resolution (Fixed v2.2.2)

- `add_schematic_component` and `place_component` now search project-local sym-lib-table and fp-lib-table
- Previously only global KiCAD library paths were searched

### Template File Corruption (Fixed v2.2.2)

- Removed invalid `;;` comment lines from template schematics
- Restored KiCAD 9 format version (20250114) in templates

### copy_routing_pattern Empty Results (Fixed v2.2.2)

- Added geometric fallback when pads have no net assignments

### Schematic Component Corruption (Fixed v2.2.1)

- `add_schematic_component` no longer corrupts .kicad_sch files
- Rewritten to use text manipulation instead of sexpdata formatting

### SWIG/UUID Comparison Bugs (Fixed v2.2.0)

- Fixed SwigPyObject UUID comparison
- Fixed SWIG iterator invalidation after board.Remove()
- Added board.SetModified() to prevent dangling pointer crashes

---

## Reporting New Issues

If you encounter an issue not listed here:

1. **Check MCP logs:** `~/.kicad-mcp/logs/kicad_interface.log`
2. **Enable developer mode:** Set `KICAD_MCP_DEV=1` to capture session logs
3. **Check KiCAD version:** `python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"` (must be 9.0+)
4. **Try the operation in KiCAD directly** -- is it a KiCAD issue?
5. **Open a GitHub issue** with:
   - Error message and log excerpt
   - Steps to reproduce
   - KiCAD version and OS
   - MCP session log (from `logs/` folder if dev mode is enabled)

---

## General Workarounds

### Server Will Not Start

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

### KiCAD UI Does Not Show Changes (SWIG Mode)

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
- Check logs: `~/.kicad-mcp/logs/kicad_interface.log`
- Open an issue on GitHub
