# KiCAD MCP Server - Client Configuration Guide

This guide shows how to configure the KiCAD MCP Server with various MCP-compatible clients.

---

## Quick Reference

| Client | Config File Location |
|--------|---------------------|
| **Claude Desktop** | Linux: `~/.config/Claude/claude_desktop_config.json`<br>macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`<br>Windows: `%APPDATA%\Claude\claude_desktop_config.json` |
| **Cline (VSCode)** | VSCode Settings → Extensions → Cline → MCP Settings |
| **Claude Code** | `~/.config/claude-code/mcp_config.json` |

---

## 1. Claude Desktop

### Linux Configuration

**File:** `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["/home/YOUR_USERNAME/MCP/KiCAD-MCP-Server/dist/index.js"],
      "env": {
        "PYTHONPATH": "/usr/lib/kicad/lib/python3/dist-packages",
        "NODE_ENV": "production"
      }
    }
  }
}
```

**Important:** Replace `/home/YOUR_USERNAME` with your actual home directory path.

### macOS Configuration

**File:** `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["/Users/YOUR_USERNAME/MCP/KiCAD-MCP-Server/dist/index.js"],
      "env": {
        "PYTHONPATH": "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/lib/python3.11/site-packages",
        "NODE_ENV": "production"
      }
    }
  }
}
```

**Note:** Adjust Python version (3.11) and KiCAD path based on your installation.

### Windows Configuration

**File:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["C:\\Users\\YOUR_USERNAME\\MCP\\KiCAD-MCP-Server\\dist\\index.js"],
      "env": {
        "PYTHONPATH": "C:\\Program Files\\KiCad\\9.0\\bin\\Lib\\site-packages",
        "NODE_ENV": "production"
      }
    }
  }
}
```

**Note:** Use double backslashes (`\\`) in Windows paths.

---

## 2. Cline (VSCode Extension)

### Configuration Steps

1. Open VSCode
2. Install Cline extension from marketplace
3. Open Settings (Ctrl+,)
4. Search for "Cline MCP"
5. Click "Edit in settings.json"

### settings.json Configuration

```json
{
  "cline.mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["/home/YOUR_USERNAME/MCP/KiCAD-MCP-Server/dist/index.js"],
      "env": {
        "PYTHONPATH": "/usr/lib/kicad/lib/python3/dist-packages"
      }
    }
  }
}
```

### Alternative: Workspace Configuration

Create `.vscode/settings.json` in your project:

```json
{
  "cline.mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["${workspaceFolder}/../KiCAD-MCP-Server/dist/index.js"],
      "env": {
        "PYTHONPATH": "/usr/lib/kicad/lib/python3/dist-packages"
      }
    }
  }
}
```

---

## 3. Claude Code CLI

### Configuration File

**File:** `~/.config/claude-code/mcp_config.json`

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["/home/YOUR_USERNAME/MCP/KiCAD-MCP-Server/dist/index.js"],
      "env": {
        "PYTHONPATH": "/usr/lib/kicad/lib/python3/dist-packages",
        "LOG_LEVEL": "info"
      }
    }
  }
}
```

### Verify Configuration

```bash
# List available MCP servers
claude-code mcp list

# Test KiCAD server connection
claude-code mcp test kicad
```

---

## 4. Generic MCP Client

For any MCP-compatible client that supports STDIO transport:

### Basic Configuration

```json
{
  "command": "node",
  "args": ["/path/to/KiCAD-MCP-Server/dist/index.js"],
  "transport": "stdio",
  "env": {
    "PYTHONPATH": "/path/to/kicad/python/packages"
  }
}
```

### With Custom Config File

```json
{
  "command": "node",
  "args": [
    "/path/to/KiCAD-MCP-Server/dist/index.js",
    "--config",
    "/path/to/custom-config.json"
  ],
  "transport": "stdio"
}
```

---

## Environment Variables

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `PYTHONPATH` | Path to KiCAD Python modules | `/usr/lib/kicad/lib/python3/dist-packages` |

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `LOG_LEVEL` | Logging verbosity | `info` |
| `NODE_ENV` | Node environment | `development` |
| `KICAD_BACKEND` | Force backend (`swig` or `ipc`) | Auto-detect |

---

## Finding KiCAD Python Path

### Linux (Ubuntu/Debian)

```bash
# Method 1: dpkg query
dpkg -L kicad | grep "site-packages" | head -1

# Method 2: Python auto-detect
python3 -c "from pathlib import Path; import sys; print([p for p in Path('/usr').rglob('pcbnew.py')])"

# Method 3: Use platform helper
cd /path/to/KiCAD-MCP-Server
PYTHONPATH=python python3 -c "from utils.platform_helper import PlatformHelper; print(PlatformHelper.get_kicad_python_paths())"
```

### macOS

```bash
# Typical location
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/lib/python3.11/site-packages

# Find dynamically
find /Applications/KiCad -name "pcbnew.py" -type f
```

### Windows

```cmd
REM Typical location (KiCAD 9.0)
C:\Program Files\KiCad\9.0\bin\Lib\site-packages

REM Search for pcbnew.py
where /r "C:\Program Files\KiCad" pcbnew.py
```

---

## Testing Your Configuration

### 1. Verify Server Starts

```bash
# Start server manually
node dist/index.js

# Should see output like:
# [INFO] Using STDIO transport for local communication
# [INFO] Registering KiCAD tools, resources, and prompts...
# [INFO] Successfully connected to STDIO transport
```

Press Ctrl+C to stop.

### 2. Test with Claude Desktop

1. Restart Claude Desktop
2. Start a new conversation
3. Look for a "hammer" icon or "Tools" indicator
4. The KiCAD tools should be listed

### 3. Test with Cline

1. Open Cline panel in VSCode
2. Start a new chat
3. Type: "List available KiCAD tools"
4. Cline should show KiCAD MCP tools are available

### 4. Test with Claude Code

```bash
# Start Claude Code with MCP
claude-code

# In the conversation, ask:
# "What KiCAD tools are available?"
```

---

## Troubleshooting

### Server Not Starting

**Error:** `Cannot find module 'pcbnew'`

**Solution:** Verify `PYTHONPATH` is correct:
```bash
python3 -c "import sys; sys.path.append('/usr/lib/kicad/lib/python3/dist-packages'); import pcbnew; print(pcbnew.GetBuildVersion())"
```

**Error:** `ENOENT: no such file or directory`

**Solution:** Check that `dist/index.js` exists:
```bash
cd /path/to/KiCAD-MCP-Server
npm run build
ls -lh dist/index.js
```

### Client Can't Connect

**Issue:** Claude Desktop doesn't show KiCAD tools

**Solutions:**
1. Restart Claude Desktop completely (quit, not just close window)
2. Check config file syntax with `jq`:
   ```bash
   jq . ~/.config/Claude/claude_desktop_config.json
   ```
3. Check Claude Desktop logs:
   - Linux: `~/.config/Claude/logs/`
   - macOS: `~/Library/Logs/Claude/`
   - Windows: `%APPDATA%\Claude\logs\`

### Python Module Errors

**Error:** `ModuleNotFoundError: No module named 'kicad_api'`

**Solution:** Server is looking for the wrong Python modules. This is an internal error. Check:
```bash
# Verify PYTHONPATH in server config includes both KiCAD and our modules
"PYTHONPATH": "/usr/lib/kicad/lib/python3/dist-packages:/path/to/KiCAD-MCP-Server/python"
```

---

## Advanced Configuration

### Multiple KiCAD Versions

If you have multiple KiCAD versions installed:

```json
{
  "mcpServers": {
    "kicad-9": {
      "command": "node",
      "args": ["/path/to/KiCAD-MCP-Server/dist/index.js"],
      "env": {
        "PYTHONPATH": "/usr/lib/kicad-9/lib/python3/dist-packages"
      }
    },
    "kicad-8": {
      "command": "node",
      "args": ["/path/to/KiCAD-MCP-Server/dist/index.js"],
      "env": {
        "PYTHONPATH": "/usr/lib/kicad-8/lib/python3/dist-packages"
      }
    }
  }
}
```

### Custom Logging

Create a custom config file `config/production.json`:

```json
{
  "logLevel": "debug",
  "python": {
    "executable": "python3",
    "timeout": 30000
  }
}
```

Then use it:

```json
{
  "command": "node",
  "args": [
    "/path/to/dist/index.js",
    "--config",
    "/path/to/config/production.json"
  ]
}
```

### Development vs Production

Development (verbose logging):
```json
{
  "env": {
    "NODE_ENV": "development",
    "LOG_LEVEL": "debug"
  }
}
```

Production (minimal logging):
```json
{
  "env": {
    "NODE_ENV": "production",
    "LOG_LEVEL": "info"
  }
}
```

---

## Platform-Specific Examples

### Ubuntu 24.04 LTS

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["/home/chris/MCP/KiCAD-MCP-Server/dist/index.js"],
      "env": {
        "PYTHONPATH": "/usr/share/kicad/scripting/plugins:/usr/lib/kicad/lib/python3/dist-packages"
      }
    }
  }
}
```

### Arch Linux

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["/home/user/KiCAD-MCP-Server/dist/index.js"],
      "env": {
        "PYTHONPATH": "/usr/lib/python3.12/site-packages"
      }
    }
  }
}
```

### Windows 11 with WSL2

Running server in WSL2, client on Windows:

```json
{
  "mcpServers": {
    "kicad": {
      "command": "wsl",
      "args": [
        "node",
        "/home/user/KiCAD-MCP-Server/dist/index.js"
      ],
      "env": {
        "PYTHONPATH": "/usr/lib/kicad/lib/python3/dist-packages"
      }
    }
  }
}
```

---

## Security Considerations

### File Permissions

Ensure config files are only readable by your user:

```bash
chmod 600 ~/.config/Claude/claude_desktop_config.json
```

### Network Isolation

The KiCAD MCP Server uses STDIO transport (no network ports), providing isolation by default.

### Code Execution

The server executes Python scripts from the `python/` directory. Only run servers from trusted sources.

---

## Next Steps

After configuration:

1. **Test Basic Functionality**
   - Ask: "Create a new KiCAD project called 'test'"
   - Ask: "What tools are available for PCB design?"

2. **Explore Resources**
   - Ask: "Show me board information"
   - Ask: "What layers are in my PCB?"

3. **Try Advanced Features**
   - Ask: "Add a resistor to my schematic"
   - Ask: "Route a trace between two points"

---

## Support

If you encounter issues:

1. Check logs in `~/.kicad-mcp/logs/` (if logging is enabled)
2. Verify KiCAD installation: `kicad-cli version`
3. Test Python modules: `python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"`
4. Review server startup logs (manual start with `node dist/index.js`)
5. Check client-specific logs (see Troubleshooting section)

For bugs or feature requests, open an issue on GitHub.

---

**Last Updated:** October 25, 2025
**Version:** 2.0.0-alpha.1
