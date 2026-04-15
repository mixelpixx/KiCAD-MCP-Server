# KiCAD UI Auto-Launch Feature

Automatically detect and launch KiCAD UI when needed, providing seamless visual feedback for PCB design operations.

---

## 🎯 Overview

The KiCAD MCP server can now:

- ✅ Detect if KiCAD UI is running
- ✅ Launch KiCAD automatically when needed
- ✅ Open projects directly in the UI
- ✅ Work across Linux, macOS, and Windows

---

## 🚀 Quick Start

### Enable Auto-Launch

Add to your MCP configuration:

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["/path/to/KiCAD-MCP-Server/dist/index.js"],
      "env": {
        "KICAD_AUTO_LAUNCH": "true"
      }
    }
  }
}
```

### Manual Control (Default)

Without `KICAD_AUTO_LAUNCH=true`, you manually control when KiCAD launches using the new MCP tools.

---

## 🛠️ New MCP Tools

### 1. `check_kicad_ui`

Check if KiCAD is currently running.

**Parameters:** None

**Example:**

```typescript
{
  "command": "check_kicad_ui",
  "params": {}
}
```

**Response:**

```json
{
  "success": true,
  "running": true,
  "processes": [
    {
      "pid": "12345",
      "name": "pcbnew",
      "command": "/usr/bin/pcbnew /tmp/project.kicad_pcb"
    }
  ],
  "message": "KiCAD is running"
}
```

### 2. `launch_kicad_ui`

Launch KiCAD UI, optionally with a project file.

**Parameters:**

- `projectPath` (optional): Path to `.kicad_pcb` file to open
- `autoLaunch` (optional): Whether to launch if not running (default: true)

**Example:**

```typescript
{
  "command": "launch_kicad_ui",
  "params": {
    "projectPath": "/tmp/mcp_demo/New_Project.kicad_pcb"
  }
}
```

**Response:**

```json
{
  "success": true,
  "running": true,
  "launched": true,
  "message": "KiCAD launched successfully",
  "project": "/tmp/mcp_demo/New_Project.kicad_pcb",
  "processes": [...]
}
```

---

## 🔄 Workflow Examples

### Example 1: Manual Launch

```
User: "Check if KiCAD is running"
Claude: Uses check_kicad_ui → "KiCAD is not running"

User: "Launch it with the demo project"
Claude: Uses launch_kicad_ui → KiCAD opens with project loaded!
```

### Example 2: Auto-Launch Mode

With `KICAD_AUTO_LAUNCH=true`:

```
User: "Create a new Arduino shield PCB"
Claude:
  1. Creates project
  2. Detects KiCAD not running
  3. Automatically launches KiCAD with the new project
  4. You see the board in real-time as it's designed!
```

### Example 3: Side-by-Side Design

```
┌────────────────────────────────────────────────────────┐
│ Workflow: AI-Assisted PCB Design                      │
├────────────────────────────────────────────────────────┤
│                                                        │
│  1. User: "Create a 100mm square board"               │
│     → Claude creates project                          │
│     → KiCAD auto-launches if not running             │
│                                                        │
│  2. User: "Add 4 mounting holes at corners"           │
│     → Claude adds holes                               │
│     → KiCAD detects file change, prompts to reload   │
│     → User clicks "Yes" → sees holes appear!          │
│                                                        │
│  3. User: "Perfect! Now add a circular outline..."    │
│     → Iterative design continues...                   │
│                                                        │
└────────────────────────────────────────────────────────┘
```

---

## ⚙️ Configuration Options

### Environment Variables

| Variable            | Default     | Description                    |
| ------------------- | ----------- | ------------------------------ |
| `KICAD_AUTO_LAUNCH` | `false`     | Auto-launch KiCAD when needed  |
| `KICAD_EXECUTABLE`  | auto-detect | Override KiCAD executable path |

### Custom Executable Path

If KiCAD is installed in a non-standard location:

```json
{
  "env": {
    "KICAD_AUTO_LAUNCH": "true",
    "KICAD_EXECUTABLE": "/opt/kicad/bin/pcbnew"
  }
}
```

---

## 🔍 How It Works

### Process Detection

**Linux:**

```bash
pgrep -f "pcbnew|kicad"
```

**macOS:**

```bash
pgrep -f "KiCad|pcbnew"
```

**Windows:**

```powershell
tasklist /FI "IMAGENAME eq pcbnew.exe"
```

### Auto-Discovery of Executable

The system searches for KiCAD in:

**Linux:**

- `/usr/bin/pcbnew`
- `/usr/local/bin/pcbnew`
- `/usr/bin/kicad`

**macOS:**

- `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad`
- `/Applications/KiCad/pcbnew.app/Contents/MacOS/pcbnew`

**Windows:**

- `C:/Program Files/KiCad/9.0/bin/pcbnew.exe`
- `C:/Program Files/KiCad/8.0/bin/pcbnew.exe`

### Launch Process

1. Check if KiCAD is already running
2. If not, find executable path
3. Spawn process with optional project path
4. Wait up to 5 seconds for process to start
5. Verify process is running
6. Return status to MCP client

---

## 💡 Use Cases

### 1. Beginner-Friendly Workflow

User doesn't need to know how to launch KiCAD manually:

```
User: "Help me design a simple LED board"
Claude: [Auto-launches KiCAD, creates project, designs board]
```

### 2. Streamlined Iteration

For rapid prototyping with visual feedback:

```
1. Claude creates board → KiCAD opens
2. User sees board, requests changes
3. Claude modifies → KiCAD reloads
4. Repeat until satisfied
```

### 3. Batch Processing

Process multiple designs without manual intervention:

```python
for design in designs:
    create_project(design)
    # KiCAD auto-launches and loads each one
    add_components(design)
    route_board(design)
    export_gerbers(design)
```

---

## 🐛 Troubleshooting

### KiCAD Doesn't Launch

**Check executable path:**

```bash
# Linux/macOS
which pcbnew

# Windows
where pcbnew.exe
```

**Override if needed:**

```json
{
  "env": {
    "KICAD_EXECUTABLE": "/path/to/pcbnew"
  }
}
```

### Process Detection Fails

**Manual check:**

```bash
# Linux/macOS
ps aux | grep kicad

# Windows
tasklist | findstr kicad
```

**Verify permissions:**

- Ensure user can execute `pgrep` (Linux/macOS)
- Ensure user can execute `tasklist` (Windows)

### Auto-Launch Doesn't Work

1. Check `KICAD_AUTO_LAUNCH` is set to `"true"` (string, not boolean)
2. Verify KiCAD is in PATH or set `KICAD_EXECUTABLE`
3. Check MCP server logs for errors
4. Try manual launch first: `launch_kicad_ui`

---

## 📊 Implementation Details

### Files Modified/Created

**New Files:**

- `python/utils/kicad_process.py` - Process management utilities
- `src/tools/ui.ts` - MCP tool definitions
- `docs/UI_AUTO_LAUNCH.md` - This documentation

**Modified Files:**

- `python/kicad_interface.py` - Added UI command handlers
- `src/server.ts` - Registered UI tools

### API Reference

**Python:**

```python
from utils.kicad_process import KiCADProcessManager, check_and_launch_kicad

# Check if running
manager = KiCADProcessManager()
is_running = manager.is_running()

# Launch KiCAD
success = manager.launch(project_path="/path/to/file.kicad_pcb")

# Get process info
processes = manager.get_process_info()

# High-level helper
result = check_and_launch_kicad(
    project_path=Path("/path/to/file.kicad_pcb"),
    auto_launch=True
)
```

**MCP Tools:**

```typescript
// Check status
await callKicadScript("check_kicad_ui", {});

// Launch
await callKicadScript("launch_kicad_ui", {
  projectPath: "/path/to/project.kicad_pcb",
  autoLaunch: true,
});
```

---

## 🔮 Future Enhancements

### Planned Features

- **Window Management:** Bring KiCAD to front, minimize/maximize
- **Multi-Instance:** Handle multiple KiCAD instances
- **IPC Integration:** Seamless integration with IPC backend
- **Status Notifications:** Push notifications when KiCAD state changes
- **Auto-Close:** Option to close KiCAD after operations complete

### IPC Mode (Coming Weeks 2-3)

When IPC backend is fully implemented:

```
KiCAD runs in background → MCP connects via IPC → Real-time updates
No file reloading needed! Changes appear instantly.
```

---

## 📝 Summary

**Before this feature:**

```
User manually launches KiCAD
User manually opens project
Claude makes changes
User manually reloads
```

**After this feature:**

```
User: "Design a board"
→ KiCAD auto-launches with project
→ Changes appear (with quick reload)
→ Seamless AI-assisted design!
```

---

**Last Updated:** 2025-10-26
**Version:** 2.0.0-alpha.1
**Status:** ✅ Production Ready
