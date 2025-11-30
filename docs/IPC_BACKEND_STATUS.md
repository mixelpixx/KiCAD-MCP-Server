# KiCAD IPC Backend Implementation Status

**Status:** 🟢 **FULLY INTEGRATED**
**Date:** 2025-11-30
**KiCAD Version:** 9.0.6
**kicad-python Version:** 0.5.0

---

## Overview

The IPC backend is now **fully integrated** as the **default backend** for all MCP tools. When KiCAD is running with IPC enabled, all commands automatically use real-time UI synchronization. Changes made through the MCP tools appear **instantly** in the KiCAD UI without requiring manual reload.

**SWIG backend is deprecated** and will be removed in a future version when KiCAD removes it (KiCAD 10.0).

## Key Benefits

| Feature | SWIG (Old) | IPC (New) |
|---------|------------|-----------|
| UI Updates | Manual reload required | **Instant** |
| Undo/Redo | Not supported | **Transaction support** |
| API Stability | Deprecated, will break | **Stable, versioned** |
| Connection | File-based | **Live socket connection** |
| Future Support | Removed in KiCAD 10.0 | **Official & maintained** |

## Implemented Features

### Automatic IPC Routing
The following MCP commands **automatically use IPC** when available:

| Command | IPC Handler | Real-time |
|---------|-------------|-----------|
| `route_trace` | `_ipc_route_trace` | Yes |
| `add_via` | `_ipc_add_via` | Yes |
| `add_net` | `_ipc_add_net` | Yes |
| `add_text` | `_ipc_add_text` | Yes |
| `add_board_text` | `_ipc_add_text` | Yes |
| `set_board_size` | `_ipc_set_board_size` | Yes |
| `get_board_info` | `_ipc_get_board_info` | Yes |
| `place_component` | `_ipc_place_component` | Yes |
| `move_component` | `_ipc_move_component` | Yes |
| `delete_component` | `_ipc_delete_component` | Yes |
| `get_component_list` | `_ipc_get_component_list` | Yes |
| `save_project` | `_ipc_save_project` | Yes |

### Core Connection
- [x] Connect to running KiCAD instance
- [x] Auto-detect socket path (`/tmp/kicad/api.sock`)
- [x] Version checking and validation
- [x] Ping/health check
- [x] Auto-fallback to SWIG when IPC unavailable
- [x] Change notification callbacks

### Board Operations
- [x] Get board reference
- [x] Get/Set board size (via Edge.Cuts)
- [x] List enabled layers
- [x] Save board
- [x] Get board bounding box

### Component Operations
- [x] List all components
- [x] Place component (real-time)
- [x] Move component (real-time)
- [x] Delete component (real-time)
- [x] Get component properties

### Routing Operations
- [x] Add track (real-time)
- [x] Add via (real-time)
- [x] Get all tracks
- [x] Get all vias
- [x] Get all nets

### UI Integration
- [x] Add text to board (real-time)
- [x] Get current selection
- [x] Clear selection
- [x] Refill zones

### Transaction Support
- [x] Begin transaction
- [x] Commit transaction (with description)
- [x] Rollback transaction
- [x] Proper undo/redo in KiCAD

## Usage

### Prerequisites

1. **KiCAD 9.0+** must be running
2. **IPC API must be enabled**: `Preferences > Plugins > Enable IPC API Server`
3. A board must be open in the PCB editor

### Installation

```bash
pip install kicad-python
```

### Basic Usage

```python
from kicad_api import create_backend

# Auto-detect and connect
backend = create_backend()  # Will try IPC first, fall back to SWIG
backend.connect()

# Get board API
board = backend.get_board()

# Operations appear instantly in KiCAD UI!
board.add_track(
    start_x=100.0, start_y=100.0,
    end_x=120.0, end_y=100.0,
    width=0.25, layer="F.Cu"
)

# With transaction support for undo
board.begin_transaction("Add components")
board.place_component("R1", "Resistor_SMD:R_0603", 50, 50)
board.place_component("C1", "Capacitor_SMD:C_0603", 60, 50)
board.commit_transaction("Added R1 and C1")  # Single undo step
```

### Force Backend Selection

```python
# Force IPC backend
backend = create_backend('ipc')

# Force SWIG backend (deprecated)
backend = create_backend('swig')

# Or via environment variable
# export KICAD_BACKEND=ipc
```

## Testing

Run the test script to verify IPC functionality:

```bash
# Make sure KiCAD is running with IPC enabled and a board open
./venv/bin/python python/test_ipc_backend.py
```

The test script will:
1. Connect to KiCAD
2. List components on the board
3. Add a test track (visible instantly in UI)
4. Add a test via (visible instantly in UI)
5. Add test text (visible instantly in UI)
6. Read the current selection

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              MCP Server (TypeScript/Node.js)                 │
└──────────────────────┬──────────────────────────────────────┘
                       │ JSON commands
┌──────────────────────▼──────────────────────────────────────┐
│              Python Interface Layer                          │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  kicad_api/ipc_backend.py                              │ │
│  │  - IPCBackend (connection management)                  │ │
│  │  - IPCBoardAPI (board operations)                      │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────┬──────────────────────────────────────┘
                       │ kicad-python (kipy) library
┌──────────────────────▼──────────────────────────────────────┐
│          Protocol Buffers over UNIX Sockets                  │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│              KiCAD 9.0+ (IPC Server)                         │
│              Changes appear instantly in UI!                 │
└─────────────────────────────────────────────────────────────┘
```

## Known Limitations

1. **KiCAD must be running**: Unlike SWIG, IPC requires KiCAD to be open
2. **Project creation**: Must be done through KiCAD UI or file system
3. **Footprint library access**: Limited - best to use library management separately
4. **Layer management**: Layers are predefined in KiCAD

## Troubleshooting

### "Connection failed"
- Ensure KiCAD is running
- Enable IPC API: `Preferences > Plugins > Enable IPC API Server`
- Check if a board is open

### "kicad-python not found"
```bash
pip install kicad-python
```

### "Version mismatch"
- Update kicad-python: `pip install --upgrade kicad-python`
- Ensure KiCAD 9.0+ is installed

### "No board open"
- Open a board in KiCAD's PCB editor before connecting

## File Structure

```
python/kicad_api/
├── __init__.py          # Package exports
├── base.py              # Abstract base classes
├── factory.py           # Backend auto-detection
├── ipc_backend.py       # IPC implementation (NEW)
└── swig_backend.py      # Legacy SWIG wrapper

python/
└── test_ipc_backend.py  # IPC test script
```

## Future Enhancements

1. **Footprint library integration via IPC** - Load footprints directly
2. **Schematic IPC support** - When available in kicad-python
3. **Event subscriptions** - React to changes made in KiCAD UI
4. **Multi-board support** - Handle multiple open boards

## Related Documentation

- [ROADMAP.md](./ROADMAP.md) - Project roadmap
- [IPC_API_MIGRATION_PLAN.md](./IPC_API_MIGRATION_PLAN.md) - Migration details
- [REALTIME_WORKFLOW.md](./REALTIME_WORKFLOW.md) - Collaboration workflows
- [kicad-python docs](https://docs.kicad.org/kicad-python-main/) - Official API docs

---

**Last Updated:** 2025-11-30
**Maintained by:** KiCAD MCP Team
