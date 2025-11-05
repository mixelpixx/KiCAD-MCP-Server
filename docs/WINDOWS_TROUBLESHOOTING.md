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
   %USERPROFILE%\.kicad-mcp\logs\kicad_interface.log
   ```
   Open in Notepad and look at the last 50-100 lines.

2. **Test pcbnew import manually:**
   ```powershell
   & "C:\Program Files\KiCad\9.0\bin\python.exe" -c "import pcbnew; print(pcbnew.GetBuildVersion())"
   ```

   **Expected:** Prints KiCAD version like `9.0.0`

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
           "PYTHONPATH": "C:\\Program Files\\KiCad\\9.0\\lib\\python3\\dist-packages"
         }
       }
     }
   }
   ```

---

### Issue 2: KiCAD Not Found

**Symptom:** Log shows "No KiCAD installations found"

**Solution:**

1. **Check if KiCAD is installed:**
   ```powershell
   Test-Path "C:\Program Files\KiCad\9.0"
   ```

2. **If KiCAD is installed elsewhere:**
   - Find your KiCAD installation directory
   - Update PYTHONPATH in config to match your installation
   - Example for version 8.0:
     ```
     "PYTHONPATH": "C:\\Program Files\\KiCad\\8.0\\lib\\python3\\dist-packages"
     ```

3. **If KiCAD is not installed:**
   - Download from https://www.kicad.org/download/windows/
   - Install version 9.0 or higher
   - Use default installation path

---

### Issue 3: Node.js Not Found

**Symptom:** Cannot run `npm install` or `npm run build`

**Solution:**

1. **Check if Node.js is installed:**
   ```powershell
   node --version
   npm --version
   ```

2. **If not installed:**
   - Download Node.js 18+ from https://nodejs.org/
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

1. **Clean and reinstall dependencies:**
   ```powershell
   Remove-Item node_modules -Recurse -Force
   Remove-Item package-lock.json -Force
   npm install
   npm run build
   ```

2. **Check Node.js version:**
   ```powershell
   node --version  # Should be v18.0.0 or higher
   ```

3. **If still failing:**
   ```powershell
   # Try with legacy peer deps
   npm install --legacy-peer-deps
   npm run build
   ```

---

### Issue 5: Python Dependencies Missing

**Symptom:** Log shows errors about missing Python packages (Pillow, cairosvg, etc.)

**Solution:**

1. **Install with KiCAD's Python:**
   ```powershell
   & "C:\Program Files\KiCad\9.0\bin\python.exe" -m pip install -r requirements.txt
   ```

2. **If pip is not available:**
   ```powershell
   # Download get-pip.py
   Invoke-WebRequest -Uri https://bootstrap.pypa.io/get-pip.py -OutFile get-pip.py

   # Install pip
   & "C:\Program Files\KiCad\9.0\bin\python.exe" get-pip.py

   # Then install requirements
   & "C:\Program Files\KiCad\9.0\bin\python.exe" -m pip install -r requirements.txt
   ```

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
"args": ["C:\Users\Name\KiCAD-MCP-Server\dist\index.js"]

// ❌ Wrong - mixed slashes
"args": ["C:\Users/Name\KiCAD-MCP-Server/dist\index.js"]

// ✅ Correct - double backslashes
"args": ["C:\\Users\\Name\\KiCAD-MCP-Server\\dist\\index.js"]

// ✅ Also correct - forward slashes
"args": ["C:/Users/Name/KiCAD-MCP-Server/dist/index.js"]
```

**Solution:** Use either double backslashes `\\` or forward slashes `/` consistently.

---

### Issue 8: Wrong Python Version

**Symptom:** Errors about Python 2.7 or Python 3.6

**Solution:**

KiCAD MCP requires Python 3.10+. KiCAD 9.0 includes Python 3.11, which is perfect.

**Always use KiCAD's bundled Python:**
```json
{
  "mcpServers": {
    "kicad": {
      "command": "C:\\Program Files\\KiCad\\9.0\\bin\\python.exe",
      "args": ["C:\\Users\\YourName\\KiCAD-MCP-Server\\python\\kicad_interface.py"]
    }
  }
}
```

This bypasses Node.js and runs Python directly.

---

## Configuration Examples

### For Claude Desktop

Config location: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["C:\\Users\\YourName\\KiCAD-MCP-Server\\dist\\index.js"],
      "env": {
        "PYTHONPATH": "C:\\Program Files\\KiCad\\9.0\\lib\\python3\\dist-packages",
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
      "args": ["C:\\Users\\YourName\\KiCAD-MCP-Server\\dist\\index.js"],
      "env": {
        "PYTHONPATH": "C:\\Program Files\\KiCad\\9.0\\lib\\python3\\dist-packages"
      },
      "description": "KiCAD PCB Design Assistant"
    }
  }
}
```

### Alternative: Python Direct Mode

If Node.js issues persist, run Python directly:

```json
{
  "mcpServers": {
    "kicad": {
      "command": "C:\\Program Files\\KiCad\\9.0\\bin\\python.exe",
      "args": ["C:\\Users\\YourName\\KiCAD-MCP-Server\\python\\kicad_interface.py"],
      "env": {
        "PYTHONPATH": "C:\\Program Files\\KiCad\\9.0\\lib\\python3\\dist-packages"
      }
    }
  }
}
```

---

## Manual Testing Steps

### Test 1: Verify KiCAD Python

```powershell
& "C:\Program Files\KiCad\9.0\bin\python.exe" -c @"
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
pcbnew version: 9.0.0
SUCCESS!
```

### Test 2: Verify Node.js

```powershell
node --version  # Should be v18.0.0+
npm --version   # Should be 9.0.0+
```

### Test 3: Build Project

```powershell
cd C:\Users\YourName\KiCAD-MCP-Server
npm install
npm run build
Test-Path .\dist\index.js  # Should output: True
```

### Test 4: Run Server Manually

```powershell
$env:PYTHONPATH = "C:\Program Files\KiCad\9.0\lib\python3\dist-packages"
node .\dist\index.js
```

Expected: Server should start and wait for input (doesn't exit immediately)

**To stop:** Press Ctrl+C

### Test 5: Check Log File

```powershell
# View log file
Get-Content "$env:USERPROFILE\.kicad-mcp\logs\kicad_interface.log" -Tail 50
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
& "C:\Program Files\KiCad\9.0\bin\python.exe" -c @"
import sys
for path in sys.path:
    print(path)
"@
```

Should include: `C:\Program Files\KiCad\9.0\lib\python3\dist-packages`

### Test MCP Communication

```powershell
# Start server
$env:PYTHONPATH = "C:\Program Files\KiCad\9.0\lib\python3\dist-packages"
$process = Start-Process -FilePath "node" -ArgumentList ".\dist\index.js" -NoNewWindow -PassThru

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
   - MCP log: `%USERPROFILE%\.kicad-mcp\logs\kicad_interface.log`
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

- [ ] KiCAD 9.0+ installed at `C:\Program Files\KiCad\9.0`
- [ ] Node.js 18+ installed and in PATH
- [ ] Python can import pcbnew successfully
- [ ] `npm run build` completes without errors
- [ ] `dist\index.js` file exists
- [ ] MCP config file created with correct paths
- [ ] Server starts without immediate crash
- [ ] Log file shows successful initialization
- [ ] Claude Desktop/Cline recognizes the MCP server
- [ ] Can execute: "Create a new KiCAD project"

---

**Last Updated:** 2025-11-05
**Maintained by:** KiCAD MCP Team

For the latest updates, see: https://github.com/mixelpixx/KiCAD-MCP-Server
