# Windows Troubleshooting Guide

This guide helps diagnose and fix common issues when setting up KiCAD MCP Server on Windows.

## Quick Start: Automated Setup

**Before manually troubleshooting, try the automated setup script:**

```powershell
# Open PowerShell in the KiCAD-MCP-Server directory
.\setup-windows.ps1
```

This script will:

- Detect your KiCAD installation
- Verify all prerequisites
- Install dependencies
- Build the project
- Generate configuration
- Run diagnostic tests

If the automated setup fails, continue with the manual troubleshooting below.

---

## Common Issues and Solutions

### Issue 1: Server Exits Immediately (Most Common)

**Symptom:** Claude Desktop logs show "Server transport closed unexpectedly"

**Cause:** Python process crashes during startup, usually due to missing pcbnew module

**Solution:**

1. **Check the log file** (this has the actual error):

   ```
   %USERPROFILE%\.kicad-mcp\logs\kicad-mcp-YYYY-MM-DD.log
   ```

   Open in Notepad and look at the last 50-100 lines.

2. **Test pcbnew import manually:**

   ```powershell
   & "C:\Program Files\KiCad\10.0\bin\python.exe" -c "import pcbnew; print(pcbnew.GetBuildVersion())"
   ```

   Replace `10.0` with your installed KiCAD version if needed.

   **Expected:** Prints KiCAD version like `10.0.0`

   **If it fails:**
   - KiCAD's Python module isn't installed
   - Reinstall KiCAD with default options
   - Make sure "Install Python" is checked during installation

3. **Verify PYTHONPATH in your config:**
   ```json
   {
     "mcpServers": {
       "kicad": {
         "env": {
           "PYTHONPATH": "C:\\Program Files\\KiCad\\10.0\\lib\\python3\\dist-packages"
         }
       }
     }
   }
   ```

---

### Issue 2: KiCAD Not Found

**Symptom:** Log shows "No KiCAD installations found"

The server checks common Windows install locations, including both machine-wide
and per-user KiCAD installs:

- `%LOCALAPPDATA%\Programs\KiCad`
- `C:\Program Files\KiCad`
- `C:\Program Files (x86)\KiCad`

**Solution:**

1. **Check if KiCAD is installed:**

   ```powershell
   Test-Path "C:\Program Files\KiCad\10.0"
   Test-Path "$env:LOCALAPPDATA\Programs\KiCad\10.0"
   ```

   Replace `10.0` with your installed KiCAD version if needed.

2. **If KiCAD is installed elsewhere:**
   - Find your KiCAD installation directory
   - Set `KICAD_PYTHON` to the bundled `python.exe`
   - Update `PYTHONPATH` in config to match your installation if needed
   - Example for a per-user 10.0 install:
     ```
     "KICAD_PYTHON": "C:\\Users\\YourName\\AppData\\Local\\Programs\\KiCad\\10.0\\bin\\python.exe",
     "PYTHONPATH": "C:\\Users\\YourName\\AppData\\Local\\Programs\\KiCad\\10.0\\lib\\python3\\dist-packages"
     ```

3. **If KiCAD is not installed:**
   - Download from https://www.kicad.org/download/windows/
   - Install KiCAD 9.0 or higher
   - Use default installation path

---

### Issue 3: Node.js Not Found

**Symptom:** Cannot run `npm ci` or `npm run build`

**Solution:**

1. **Check if Node.js is installed:**

   ```powershell
   node --version
   npm --version
   ```

2. **If not installed:**
   - Download Node.js 20+ from https://nodejs.org/
   - Install with default options
   - Restart PowerShell after installation

3. **If installed but not in PATH:**
   ```powershell
   # Add to PATH temporarily
   $env:PATH += ";C:\Program Files\nodejs"
   ```

---

### Issue 4: Build Fails with TypeScript Errors

**Symptom:** `npm run build` shows TypeScript compilation errors

**Solution:**

1. **Restore the locked dependency tree and rebuild:**

   ```powershell
   npm ci
   npm run build
   ```

2. **Check Node.js version:**

   ```powershell
   node --version  # Should be v20.0.0 or higher
   ```

3. **If still failing, verify the npm cache and retry the lockfile install:**
   ```powershell
   npm cache verify
   npm ci
   npm run build
   ```

---

### Issue 5: Python Dependencies Missing

**Symptom:** Log shows errors about missing Python packages (Pillow, cairosvg, etc.)

**Solution:**

1. **Rebuild and prepare the private runtime from the repository root:**

   ```powershell
   npm ci
   npm run build
   $env:KICAD_PYTHON = "C:\Program Files\KiCad\10.0\bin\python.exe"
   node .\dist\cli.js setup
   ```

2. **If setup still fails, inspect the detected runtime:**

   ```powershell
   node .\dist\cli.js doctor
   ```

   The CLI creates a separate, hash-locked environment under your user data
   directory. Never bootstrap pip or install MCP packages into KiCAD's bundled
   Python. If that interpreter itself is incomplete, repair the KiCAD
   installation and rerun setup.

---

### Issue 6: Permission Denied Errors

**Symptom:** Cannot write to Program Files or access certain directories

**Solution:**

1. **Run PowerShell as Administrator:**
   - Right-click PowerShell icon
   - Select "Run as Administrator"
   - Navigate to KiCAD-MCP-Server directory
   - Run setup again

2. **Or clone to user directory:**
   ```powershell
   cd $HOME\Documents
   git clone https://github.com/mixelpixx/KiCAD-MCP-Server.git
   cd KiCAD-MCP-Server
   .\setup-windows.ps1
   ```

---

### Issue 7: Path Issues in Configuration

**Symptom:** Config file paths not working

**Common mistakes:**

```json
// ❌ Wrong - single backslashes
"args": ["C:\Users\Name\KiCAD-MCP-Server\dist\cli.js", "serve"]

// ❌ Wrong - mixed slashes
"args": ["C:\Users/Name\KiCAD-MCP-Server/dist\cli.js", "serve"]

// ✅ Correct - double backslashes
"args": ["C:\\Users\\Name\\KiCAD-MCP-Server\\dist\\cli.js", "serve"]

// ✅ Also correct - forward slashes
"args": ["C:/Users/Name/KiCAD-MCP-Server/dist/cli.js", "serve"]
```

**Solution:** Use either double backslashes `\\` or forward slashes `/` consistently.

---

### Issue 8: Wrong Python Version

**Symptom:** Errors about Python 2.7 or Python 3.6

**Solution:**

KiCAD MCP requires Python 3.10+. KiCAD 10.0 includes a compatible bundled Python,
and KiCAD 9.0+ is supported.

**Always launch the TypeScript MCP server and point it to KiCAD's bundled Python:**

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["C:\\Users\\YourName\\KiCAD-MCP-Server\\dist\\cli.js", "serve"],
      "env": {
        "KICAD_PYTHON": "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe",
        "PYTHONPATH": "C:\\Program Files\\KiCad\\10.0\\lib\\python3\\dist-packages"
      }
    }
  }
}
```

The TypeScript entry point is the MCP server. `python/kicad_interface.py` is its
internal worker and does not accept MCP client JSON-RPC directly.

---

## Configuration Examples

### For Claude Desktop

Config location: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["C:\\Users\\YourName\\KiCAD-MCP-Server\\dist\\cli.js", "serve"],
      "env": {
        "PYTHONPATH": "C:\\Program Files\\KiCad\\10.0\\lib\\python3\\dist-packages",
        "NODE_ENV": "production",
        "LOG_LEVEL": "info"
      }
    }
  }
}
```

### For Cline (VSCode)

Config location: `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json`

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["C:\\Users\\YourName\\KiCAD-MCP-Server\\dist\\cli.js", "serve"],
      "env": {
        "PYTHONPATH": "C:\\Program Files\\KiCad\\10.0\\lib\\python3\\dist-packages"
      },
      "description": "KiCAD PCB Design Assistant"
    }
  }
}
```

### Alternative: npm package after publication

After the selected version is public on npm, a local checkout or build can be
replaced with the published package on Node.js 20+:

```json
{
  "mcpServers": {
    "kicad": {
      "command": "npx",
      "args": ["-y", "@theavi/kicad-mcp@2.7.0", "serve"],
      "env": {
        "KICAD_PYTHON": "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe",
        "PYTHONPATH": "C:\\Program Files\\KiCad\\10.0\\lib\\python3\\dist-packages"
      }
    }
  }
}
```

---

## Manual Testing Steps

### Test 1: Verify KiCAD Python

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" -c @"
import sys
print(f'Python version: {sys.version}')
import pcbnew
print(f'pcbnew version: {pcbnew.GetBuildVersion()}')
print('SUCCESS!')
"@
```

Expected output:

```
Python version: 3.11.x ...
pcbnew version: 10.0.0
SUCCESS!
```

### Test 2: Verify Node.js

```powershell
node --version  # Should be v20.0.0+
npm --version   # Should be 9.0.0+
```

### Test 3: Build Project

```powershell
cd C:\Users\YourName\KiCAD-MCP-Server
npm ci
npm run build
Test-Path .\dist\cli.js  # Should output: True
```

### Test 4: Run Server Manually

```powershell
$env:PYTHONPATH = "C:\Program Files\KiCad\10.0\lib\python3\dist-packages"
node .\dist\cli.js serve
```

Expected: Server should start and wait for input (doesn't exit immediately)

**To stop:** Press Ctrl+C

### Test 5: Check Log File

```powershell
# View log file
$log = Get-ChildItem "$env:USERPROFILE\.kicad-mcp\logs\kicad-mcp-*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Get-Content $log.FullName -Tail 50
```

Should show successful initialization with no errors.

---

## Advanced Diagnostics

### Enable Verbose Logging

Add to your MCP config:

```json
{
  "env": {
    "LOG_LEVEL": "debug",
    "PYTHONUNBUFFERED": "1"
  }
}
```

### Check Python sys.path

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" -c @"
import sys
for path in sys.path:
    print(path)
"@
```

Should include: `C:\Program Files\KiCad\10.0\lib\python3\dist-packages`

### Test MCP Communication

```powershell
# Start server
$env:PYTHONPATH = "C:\Program Files\KiCad\10.0\lib\python3\dist-packages"
$process = Start-Process -FilePath "node" -ArgumentList ".\dist\cli.js", "serve" -NoNewWindow -PassThru

# Wait 3 seconds
Start-Sleep -Seconds 3

# Check if still running
if ($process.HasExited) {
    Write-Host "Server crashed!" -ForegroundColor Red
    Write-Host "Exit code: $($process.ExitCode)"
} else {
    Write-Host "Server is running!" -ForegroundColor Green
    Stop-Process -Id $process.Id
}
```

---

## Getting Help

If none of the above solutions work:

1. **Run the diagnostic script:**

   ```powershell
   .\setup-windows.ps1
   ```

   Copy the entire output.

2. **Collect log files:**
   - MCP log: `%USERPROFILE%\.kicad-mcp\logs\kicad-mcp-YYYY-MM-DD.log`
   - Claude Desktop log: `%APPDATA%\Claude\logs\mcp*.log`

3. **Open a GitHub issue:**
   - Go to: https://github.com/mixelpixx/KiCAD-MCP-Server/issues
   - Title: "Windows Setup Issue: [brief description]"
   - Include:
     - Windows version (10 or 11)
     - Output from setup script
     - Log file contents
     - Output from manual tests above

---

## Known Limitations on Windows

1. **File paths are case-insensitive** but should match actual casing for best results

2. **Long path support** may be needed for deeply nested projects:

   ```powershell
   # Enable long paths (requires admin)
   New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
   ```

3. **Windows Defender** may slow down file operations. Add exclusion:

   ```
   Settings → Windows Security → Virus & threat protection → Exclusions
   Add: C:\Users\YourName\KiCAD-MCP-Server
   ```

4. **Antivirus software** may block Python/Node processes. Temporarily disable for testing.

---

## Success Checklist

When everything works, you should have:

- [ ] KiCAD 9.0 or higher installed under a versioned KiCAD directory such as
      `C:\Program Files\KiCad\10.0` or `%LOCALAPPDATA%\Programs\KiCad\10.0`
- [ ] Node.js 20+ installed and in PATH
- [ ] Python can import pcbnew successfully
- [ ] `npm run build` completes without errors
- [ ] `dist\cli.js` file exists
- [ ] MCP config file created with correct paths
- [ ] Server starts without immediate crash
- [ ] Log file shows successful initialization
- [ ] Claude Desktop/Cline recognizes the MCP server
- [ ] Can execute: "Create a new KiCAD project"

---

**Last Updated:** 2025-11-05
**Maintained by:** KiCAD MCP Team

For the latest updates, see: https://github.com/mixelpixx/KiCAD-MCP-Server
