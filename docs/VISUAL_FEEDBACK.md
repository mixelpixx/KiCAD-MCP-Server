# Visual Feedback: Seeing MCP Changes in KiCAD UI

This document explains how to see changes made by the MCP server in the KiCAD UI in real-time or near-real-time.

## Current Status

**Active Backend:** Hybrid SWIG/IPC

**Real-time Updates:** Available for IPC-backed commands when KiCAD IPC is connected

**SWIG Fallback:** File-based commands still require KiCAD to reload from disk

**IPC Re-detect:** IPC-enabled tools detect at runtime if IPC is available again and switch from SWIG to IPC.

---

## 🎯 Best Current Workflow (Hybrid IPC + SWIG)

### Setup

1. **Open your project in KiCAD PCB Editor**

   ```bash
   pcbnew /tmp/kicad_test_project/New_Project.kicad_pcb
   ```

2. **Make changes via MCP** (Claude Code, Claude Desktop, etc.)
   - Example: Add board outline, mounting holes, etc.
   - Each operation saves the file automatically

3. **Check whether reload is needed**
   - If the MCP response reports `_backend: "ipc"` and `_realtime: true`, the change should appear in KiCAD immediately.
   - If the MCP response reports `_backend: "swig"` or `_realtime: false`, reload the board from disk.
   - **Option A (Automatic):** KiCAD 8.0+ detects file changes and shows a reload prompt.
   - **Option B (Manual):** File → Revert to reload from disk.

### Workflow Example

```
┌─────────────────────────────────────────────────────────┐
│ Terminal: Claude Code                                   │
├─────────────────────────────────────────────────────────┤
│ You: "Create a 100x80mm board with 4 mounting holes"   │
│                                                          │
│ Claude: ✓ Added board outline (100x80mm)               │
│         ✓ Added mounting hole at (5,5)                  │
│         ✓ Added mounting hole at (95,5)                 │
│         ✓ Added mounting hole at (95,75)                │
│         ✓ Added mounting hole at (5,75)                 │
│         ✓ Saved project                                 │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ KiCAD PCB Editor                                        │
├─────────────────────────────────────────────────────────┤
│ [Reload prompt appears]                                 │
│ "File has been modified. Reload?"                       │
│                                                          │
│ Click "Yes" → Changes appear instantly! 🎉              │
└─────────────────────────────────────────────────────────┘
```

---

## IPC Backend: Real-Time Updates (Experimental)

When KiCAD is running with the IPC API enabled, supported MCP board tools can
use the IPC backend for **true real-time UI updates** instead of relying on
file save/reload.

### How It Works

```text
Agent → MCP → IPC connection → Running KiCAD → Instant UI Update
```

**No file reloading is required** for commands that successfully use IPC. Tool
responses include `_backend: "ipc"` and `_realtime: true` when the IPC path was
used. If IPC is unavailable, the server falls back to SWIG and the manual reload
workflow still applies. If IPC becomes available during the session,
IPC-capable tools can reconnect and use IPC without restarting the MCP server.

### IPC Setup

1. Enable IPC in KiCAD:
   - Preferences → Plugins → Enable IPC API Server
   - Restart KiCAD if required

2. Install `kicad-python`:

   ```bash
   pip install kicad-python
   ```

3. **Configure MCP Server**

   The default `auto` backend mode is recommended when you want SWIG fallback
   plus runtime reconnect. To make the setting explicit, add:

   ```json
   {
     "env": {
       "KICAD_BACKEND": "auto"
     }
   }
   ```

   Use strict `ipc` mode only when you want startup to fail if IPC is not
   available:

   ```json
   {
     "env": {
       "KICAD_BACKEND": "ipc"
     }
   }
   ```

4. Start KiCAD and open a board, or use `launch_kicad_ui`.

The MCP server **can** start before KiCAD. In `auto` backend mode, IPC-capable
board tools retry IPC at runtime after KiCAD is available, so agents can keep
using standard tools such as `get_board_info`, `get_layer_list`,
`get_component_list`, `get_nets_list`, and `query_traces`.

### Current IPC Status

| Feature                  | Status                                                        |
| ------------------------ | ------------------------------------------------------------- |
| Connection to KiCAD      | Working when KiCAD IPC is enabled                             |
| Board operations         | Partially implemented via IPC                                 |
| Component operations     | Partially implemented / hybrid                                |
| Routing operations       | Partially implemented via IPC                                 |
| SWIG fallback            | Used automatically in `auto` mode when IPC is unavailable     |
| Runtime reconnect to IPC | Used automatically in `auto` mode for IPC-capable board tools |

---

## 🛠️ Monitoring Helper (Optional)

A helper script is available to monitor file changes:

```bash
# Watch for changes and notify
./scripts/auto_refresh_kicad.sh /tmp/kicad_test_project/New_Project.kicad_pcb
```

This will print a message each time the MCP server saves changes.

---

## 💡 Tips for Best Experience

### 1. Side-by-Side Windows

```
┌──────────────────┬──────────────────┐
│  Claude Code     │   KiCAD PCB      │
│  (Terminal)      │   Editor         │
│                  │                  │
│  Making changes  │  Viewing results │
└──────────────────┴──────────────────┘
```

### 2. Quick Reload Workflow

- Keep KiCAD focused in one window
- Make changes via Claude in another
- Press Alt+Tab → Click "Reload" → See changes
- Repeat

### 3. Save Frequently

The MCP server auto-saves after each operation, so changes are immediately available for reload.

### 4. Verify Before Complex Operations

For complex changes (multiple components, routing, etc.):

1. Make the change
2. Confirm the change in KiCAD; reload only if the response used SWIG
3. Verify it looks correct
4. Proceed with next change

---

## 🔍 Troubleshooting

### KiCAD Doesn't Detect File Changes

**Cause:** Some KiCAD versions or configurations don't auto-detect
**Solution:** Use File → Revert manually

### Changes Don't Appear After Reload

**Cause:** MCP operation may have failed
**Solution:** Check the MCP response for success: true

### Changes Still Require Reload

**Cause:** The tool response reported `_backend: "swig"` or `_realtime: false`.
SWIG-backed commands write files directly and still require KiCAD to reload the board from disk.

**Solution:** Ensure KiCAD is running with IPC enabled and a board is open, then
retry the IPC-capable board tool. If IPC reconnect succeeds, the response will
report `_backend: "ipc"` and `_realtime: true`.

### File is Locked

**Cause:** KiCAD has the file open exclusively
**Solution:**

- KiCAD should allow external modifications
- If not, close the file in KiCAD, let MCP make changes, then reopen

---

**Last Updated:** 2025-10-26
**Version:** 2.0.0-alpha.1
