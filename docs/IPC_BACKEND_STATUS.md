# KiCAD IPC Backend Implementation Status

**Status:** Under Active Development and Testing
**Date:** 2025-12-02
**KiCAD Version:** 9.0.6
**kicad-python Version:** 0.5.0

---

## Overview

The IPC backend provides real-time UI synchronization with KiCAD 9.0+ via the official IPC API. When KiCAD is running with IPC enabled, commands can update the KiCAD UI immediately without requiring manual reload.

This feature is experimental and under active testing. The server uses a hybrid approach: IPC when available, automatic fallback to SWIG when IPC is not connected.

## Key Differences

| Feature | SWIG | IPC |
|---------|------|-----|
| UI Updates | Manual reload required | Immediate (when working) |
| Undo/Redo | Not supported | Transaction support |
| API Stability | Deprecated in KiCAD 9 | Official, versioned |
| Connection | File-based | Live socket connection |
| KiCAD Required | No (file operations) | Yes (must be running) |

## Implemented IPC Commands

The following MCP commands have IPC handlers:

| Command | IPC Handler | Status |
|---------|-------------|--------|
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
| `place_component` | `_ipc_place_component` | Implemented (hybrid) |
| `move_component` | `_ipc_move_component` | Implemented |
| `rotate_component` | `_ipc_rotate_component` | Implemented |
| `delete_component` | `_ipc_delete_component` | Implemented |
| `get_component_list` | `_ipc_get_component_list` | Implemented |
| `get_component_properties` | `_ipc_get_component_properties` | Implemented |
| `save_project` | `_ipc_save_project` | Implemented |

### Implemented Backend Features

**Core Connection:**
- Connect to running KiCAD instance
- Auto-detect socket path (`/tmp/kicad/api.sock`)
- Version checking and validation
- Auto-fallback to SWIG when IPC unavailable
- Change notification callbacks

**Board Operations:**
- Get board reference
- Get/Set board size
- List enabled layers
- Save board
- Add board outline segments
- Add mounting holes

**Component Operations:**
- List all components
- Place component (hybrid: SWIG for library loading, IPC for placement)
- Move component
- Rotate component
- Delete component
- Get component properties

**Routing Operations:**
- Add track
- Add via
- Get all tracks
- Get all vias
- Get all nets

**Zone Operations:**
- Add copper pour zones
- Get zones list
- Refill zones

**UI Integration:**
- Add text to board
- Get current selection
- Clear selection

**Transaction Support:**
- Begin transaction
- Commit transaction (with description for undo)
- Rollback transaction

## Usage

### Prerequisites

1. **KiCAD 9.0+** must be running
2. **IPC API must be enabled**: `Preferences > Plugins > Enable IPC API Server`
3. A board must be open in the PCB editor

### Installation

```bash
pip install kicad-python
```

### Testing

Run the test script to verify IPC functionality:

```bash
# Make sure KiCAD is running with IPC enabled and a board open
./venv/bin/python python/test_ipc_backend.py
```

## Architecture

```
+-------------------------------------------------------------+
|              MCP Server (TypeScript/Node.js)                |
+---------------------------+---------------------------------+
                            | JSON commands
+---------------------------v---------------------------------+
|              Python Interface Layer                         |
|  +--------------------------------------------------------+ |
|  |  kicad_interface.py                                    | |
|  |  - Routes commands to IPC or SWIG handlers             | |
|  |  - IPC_CAPABLE_COMMANDS dict defines routing           | |
|  +--------------------------------------------------------+ |
|  +--------------------------------------------------------+ |
|  |  kicad_api/ipc_backend.py                              | |
|  |  - IPCBackend (connection management)                  | |
|  |  - IPCBoardAPI (board operations)                      | |
|  +--------------------------------------------------------+ |
+---------------------------+---------------------------------+
                            | kicad-python (kipy) library
+---------------------------v---------------------------------+
|          Protocol Buffers over UNIX Sockets                 |
+---------------------------+---------------------------------+
                            |
+---------------------------v---------------------------------+
|              KiCAD 9.0+ (IPC Server)                        |
+-------------------------------------------------------------+
```

## Known Limitations

1. **KiCAD must be running**: Unlike SWIG, IPC requires KiCAD to be open
2. **Project creation**: Not supported via IPC, uses file system
3. **Footprint library access**: Uses hybrid approach (SWIG loads from library, IPC places)
4. **Delete trace**: Falls back to SWIG (IPC API doesn't support direct deletion)
5. **Some operations may not work as expected**: This is experimental code

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
├── ipc_backend.py       # IPC implementation
└── swig_backend.py      # Legacy SWIG wrapper

python/
└── test_ipc_backend.py  # IPC test script
```

## Future Work

1. More comprehensive testing of all IPC commands
2. Footprint library integration via IPC (when kipy supports it)
3. Schematic IPC support (when available in kicad-python)
4. Event subscriptions to react to changes made in KiCAD UI
5. Multi-board support

## Related Documentation

- [ROADMAP.md](./ROADMAP.md) - Project roadmap
- [IPC_API_MIGRATION_PLAN.md](./IPC_API_MIGRATION_PLAN.md) - Migration details
- [REALTIME_WORKFLOW.md](./REALTIME_WORKFLOW.md) - Collaboration workflows
- [kicad-python docs](https://docs.kicad.org/kicad-python-main/) - Official API docs

---

**Last Updated:** 2025-12-02
