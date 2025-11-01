# Known Issues & Workarounds

**Last Updated:** 2025-10-26
**Version:** 2.0.0-alpha.2

This document tracks known issues and provides workarounds where available.

---

## 🐛 Current Issues

### 1. Component Placement Fails - Library Path Not Found

**Status:** 🔴 **BLOCKING** - Cannot place components

**Symptoms:**
```
Error: Could not find footprint library
```

**Root Cause:** MCP server doesn't have access to KiCAD's footprint library paths

**Workaround:** None currently - feature not usable

**Fix Plan:** Week 2 priority
- Detect KiCAD library paths from environment
- Add configuration for custom library paths
- Integrate JLCPCB/Digikey part databases

**Tracking:** High Priority - Required for any real PCB design

---

### 2. Routing Operations Untested with KiCAD 9.0

**Status:** 🟡 **UNKNOWN** - May have API compatibility issues

**Affected Commands:**
- `route_trace`
- `add_via`
- `add_copper_pour`
- `route_differential_pair`

**Symptoms:** May fail with API type mismatch errors (like set_board_size did)

**Workaround:** None - needs testing and fixes

**Fix Plan:** Week 2 priority
- Test each routing command with KiCAD 9.0
- Fix API compatibility issues
- Add comprehensive routing examples

---

### 3. `get_board_info` KiCAD 9.0 API Issue

**Status:** 🟡 **KNOWN** - Non-critical

**Symptoms:**
```
AttributeError: 'BOARD' object has no attribute 'LT_USER'
```

**Root Cause:** KiCAD 9.0 changed layer enumeration constants

**Workaround:** Use `get_project_info` instead for basic project details

**Fix Plan:** Week 2
- Update to use KiCAD 9.0 layer constants
- Add backward compatibility for KiCAD 8.x

**Impact:** Low - informational command only

---

### 4. UI Auto-Reload Requires Manual Confirmation

**Status:** 🟢 **BY DESIGN** - Will be fixed by IPC

**Symptoms:**
- MCP makes changes
- KiCAD detects file change
- User must click "Reload" button to see changes

**Current Workflow:**
```
1. Claude makes change via MCP
2. KiCAD shows: "File has been modified. Reload? [Yes] [No]"
3. User clicks "Yes"
4. Changes appear in UI
```

**Why:** SWIG-based backend requires file I/O, can't push changes to running UI

**Fix Plan:** Weeks 2-3 - IPC Backend Migration
- Connect to KiCAD via IPC socket
- Make changes directly in running instance
- No file reload needed - instant visual feedback

**Workaround:** This is the current expected behavior - just click reload!

---

## 🔧 Recently Fixed

### ✅ KiCAD Process Detection (Fixed 2025-10-26)

**Was:** `check_kicad_ui` detected MCP server's own processes
**Now:** Properly filters to only detect actual KiCAD binaries

### ✅ set_board_size KiCAD 9.0 (Fixed 2025-10-26)

**Was:** Failed with `BOX2I_SetSize` type error
**Now:** Works with KiCAD 9.0 API, backward compatible with 8.x

### ✅ add_board_text KiCAD 9.0 (Fixed 2025-10-26)

**Was:** Failed with `EDA_ANGLE` type error
**Now:** Works with KiCAD 9.0 API, backward compatible with 8.x

### ✅ Missing add_board_text Command (Fixed 2025-10-26)

**Was:** Command not found error
**Now:** Properly mapped to Python handler

---

## 📋 Reporting New Issues

If you encounter an issue not listed here:

1. **Check MCP logs:** `~/.kicad-mcp/logs/kicad_interface.log`
2. **Check KiCAD version:** `pcbnew --version` (must be 9.0+)
3. **Try the operation in KiCAD directly** - is it a KiCAD issue?
4. **Open GitHub issue** with:
   - Error message
   - Log excerpt
   - Steps to reproduce
   - KiCAD version
   - OS and version

---

## 🎯 Priority Matrix

| Issue | Priority | Impact | Effort | Status |
|-------|----------|--------|--------|--------|
| Component Library Integration | 🔴 Critical | High | Medium | Week 2 |
| Routing KiCAD 9.0 Compatibility | 🟡 High | High | Low | Week 2 |
| IPC Backend (Real-time UI) | 🟡 High | Medium | High | Week 2-3 |
| get_board_info Fix | 🟢 Low | Low | Low | Week 2 |

---

## 💡 General Workarounds

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

### KiCAD UI Doesn't Show Changes
```
# File → Revert (or click reload prompt)
# Or: Close and reopen file in KiCAD
```

---

**Need Help?**
- Check [docs/VISUAL_FEEDBACK.md](VISUAL_FEEDBACK.md) for workflow tips
- Check [docs/UI_AUTO_LAUNCH.md](UI_AUTO_LAUNCH.md) for UI setup
- Open an issue on GitHub
