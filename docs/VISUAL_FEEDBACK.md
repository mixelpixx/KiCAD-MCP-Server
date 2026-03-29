# Visual Feedback: Seeing MCP Changes in KiCAD UI

This document explains how to see changes made by the MCP server in the KiCAD UI in real-time or near-real-time.

## Current Status (Week 1 - SWIG Backend)

**Active Backend:** SWIG (legacy pcbnew Python API)
**Real-time Updates:** Not available yet
**IPC Backend:** Skeleton implemented, operations coming in Weeks 2-3

---

## 🎯 Best Current Workflow (SWIG + Manual Reload)

### Setup

1. **Open your project in KiCAD PCB Editor**

   ```bash
   pcbnew /tmp/kicad_test_project/New_Project.kicad_pcb
   ```

2. **Make changes via MCP** (Claude Code, Claude Desktop, etc.)
   - Example: Add board outline, mounting holes, etc.
   - Each operation saves the file automatically

3. **Reload in KiCAD UI**
   - **Option A (Automatic):** KiCAD 8.0+ detects file changes and shows a reload prompt
   - **Option B (Manual):** File → Revert to reload from disk
   - **Keyboard shortcut:** None by default (but you can assign one)

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

## 🔮 Future: IPC Backend (Weeks 2-3)

When fully implemented, the IPC backend will provide **true real-time updates**:

### How It Will Work

```
Claude MCP → IPC Socket → Running KiCAD → Instant UI Update
```

**No file reloading required** - changes appear as you make them!

### IPC Setup (When Available)

1. **Enable IPC in KiCAD**
   - Preferences → Advanced Preferences
   - Search for "IPC"
   - Enable: "Enable IPC API Server"
   - Restart KiCAD

2. **Install kicad-python** (Already installed ✓)

   ```bash
   pip install kicad-python
   ```

3. **Configure MCP Server**
   Add to your MCP config:

   ```json
   {
     "env": {
       "KICAD_BACKEND": "ipc"
     }
   }
   ```

4. **Start KiCAD first, then use MCP**
   - Changes will appear in real-time
   - No manual reloading needed

### Current IPC Status

| Feature              | Status      |
| -------------------- | ----------- |
| Connection to KiCAD  | ✅ Working  |
| Version checking     | ✅ Working  |
| Project operations   | ⏳ Week 2-3 |
| Board operations     | ⏳ Week 2-3 |
| Component operations | ⏳ Week 2-3 |
| Routing operations   | ⏳ Week 2-3 |

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
2. Reload in KiCAD
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

### File is Locked

**Cause:** KiCAD has the file open exclusively
**Solution:**

- KiCAD should allow external modifications
- If not, close the file in KiCAD, let MCP make changes, then reopen

---

## 📅 Roadmap

**Current (Week 1):** SWIG backend with manual reload
**Week 2-3:** IPC backend implementation
**Week 4+:** Real-time collaboration features

---

**Last Updated:** 2025-10-26
**Version:** 2.0.0-alpha.1
