# Changelog - 2025-11-30

## IPC Backend Implementation - Real-time UI Synchronization

This release implements the **KiCAD IPC API backend**, enabling real-time UI synchronization between the MCP server and KiCAD. Changes made through MCP tools now appear **instantly** in the KiCAD UI without requiring manual reload.

### Major Features

#### Real-time UI Sync via IPC API
- **Instant updates**: Tracks, vias, components, and text appear immediately in KiCAD
- **No reload required**: Eliminates the manual File > Reload workflow
- **Transaction support**: Operations can be grouped for single undo/redo steps
- **Auto-detection**: Server automatically uses IPC when KiCAD is running with IPC enabled

#### Automatic Backend Selection
- IPC backend is now the **default** when available
- Transparent fallback to SWIG when IPC unavailable
- Environment variable `KICAD_BACKEND` for explicit control:
  - `auto` (default): Try IPC first, fall back to SWIG
  - `ipc`: Force IPC only
  - `swig`: Force SWIG only (deprecated)

#### Commands with IPC Support
The following commands now automatically use IPC for real-time updates:

| Command | Description |
|---------|-------------|
| `route_trace` | Add traces with instant UI update |
| `add_via` | Add vias with instant UI update |
| `add_text` / `add_board_text` | Add text with instant UI update |
| `set_board_size` | Set board size with instant outline update |
| `get_board_info` | Read live board data |
| `place_component` | Place components with instant UI update |
| `move_component` | Move components with instant UI update |
| `delete_component` | Delete components with instant UI update |
| `get_component_list` | Read live component list |
| `save_project` | Save via IPC |

### New Files

- `python/kicad_api/ipc_backend.py` - Complete IPC backend implementation (~870 lines)
- `python/test_ipc_backend.py` - Test script for IPC functionality
- `docs/IPC_BACKEND_STATUS.md` - Implementation status documentation

### Modified Files

- `python/kicad_interface.py` - Added IPC integration and automatic command routing
- `python/kicad_api/base.py` - Added routing and transaction methods to base class
- `python/kicad_api/factory.py` - Fixed kipy module detection
- `docs/ROADMAP.md` - Updated Week 3 status to complete

### Dependencies

- Added `kicad-python>=0.5.0` - Official KiCAD IPC API Python library

### Requirements

To use real-time mode:
1. KiCAD 9.0+ must be running
2. Enable IPC API: `Preferences > Plugins > Enable IPC API Server`
3. Have a board open in PCB editor

### Deprecation Notice

The **SWIG backend is now deprecated**:
- Will continue to work as fallback
- No new features will be added to SWIG path
- Will be removed when KiCAD 10.0 drops SWIG support

### Testing

Run the IPC test script:
```bash
./venv/bin/python python/test_ipc_backend.py
```

Or test individual commands:
```bash
echo '{"command": "get_backend_info", "params": {}}' | \
  PYTHONPATH=python ./venv/bin/python python/kicad_interface.py
```

### Breaking Changes

None. All existing commands continue to work. IPC is used transparently when available.

---

**Version:** 2.1.0-alpha
**Date:** 2025-11-30
