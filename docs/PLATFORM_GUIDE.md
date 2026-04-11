# Platform Guide: Linux, macOS & Windows

This guide explains the differences between using KiCAD MCP Server on Linux, macOS, and Windows platforms.

**Last Updated:** 2026-04-11

---

## Quick Comparison

| Feature                  | Linux                     | Windows                         | macOS                   |
| ------------------------ | ------------------------- | ------------------------------- | ----------------------- |
| **Primary Support**      | Full (tested extensively) | Community tested                | Community tested        |
| **Setup Complexity**     | Moderate                  | Easy (automated script)         | Easy (automated script) |
| **Prerequisites**        | Manual package management | Automated detection             | Automated detection     |
| **KiCAD Python Access**  | System paths              | Bundled with KiCAD              | Bundled with KiCAD      |
| **Path Separators**      | Forward slash (/)         | Backslash (\\) or forward slash | Forward slash (/)       |
| **Virtual Environments** | Recommended               | Optional                        | Optional                |
| **Troubleshooting**      | Standard Linux tools      | PowerShell diagnostics          | Bash diagnostics        |

---

## Installation Differences

### Linux Installation

**Advantages:**

- Native package manager integration
- Better tested and documented
- More predictable Python environments
- Standard Unix paths

**Process:**

1. Install KiCAD 9.0 via package manager (apt, dnf, pacman)
2. Install Node.js via package manager or nvm
3. Clone repository
4. Install dependencies manually
5. Build project
6. Configure MCP client
7. Set PYTHONPATH environment variable

**Typical paths:**

```bash
KiCAD Python: /usr/lib/kicad/lib/python3/dist-packages
Node.js: /usr/bin/node
Python: /usr/bin/python3
```

**Configuration example:**

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["/home/username/KiCAD-MCP-Server/dist/index.js"],
      "env": {
        "PYTHONPATH": "/usr/lib/kicad/lib/python3/dist-packages"
      }
    }
  }
}
```

### macOS Installation

**Advantages:**

- Automated setup script (`setup-macos.sh`) handles detection and configuration
- KiCAD includes bundled Python (no system Python needed for pcbnew)
- Prerequisite checks with clear pass/fail output
- Generates and merges Claude Desktop configuration automatically

**Process:**

1. Install KiCAD 9.0 from the official `.dmg` installer
2. Install Node.js (e.g. via Homebrew or nvm)
3. Clone repository
4. Run `npm install && npm run build`
5. Run `setup-macos.sh`:
   - `bash setup-macos.sh --verify` — check prerequisites and detected paths
   - `bash setup-macos.sh --dry-run` — preview the merged Claude Desktop config
   - `bash setup-macos.sh --apply` — write the configuration

**Typical paths:**

```bash
KiCAD Python: /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
KiCAD Libraries: /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.x/lib/python3.x/site-packages
Node.js: /usr/local/bin/node  # or via nvm
```

**Configuration example:**

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["/Users/username/KiCAD-MCP-Server/dist/index.js"],
      "env": {
        "KICAD_PYTHON": "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3",
        "PYTHONPATH": "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/lib/python3.9/site-packages"
      }
    }
  }
}
```

### Windows Installation

**Advantages:**

- Automated setup script handles everything
- KiCAD includes bundled Python (no system Python needed)
- Better error diagnostics
- Comprehensive troubleshooting guide

**Process:**

1. Install KiCAD 9.0 from official installer
2. Install Node.js from official installer
3. Clone repository
4. Run `setup-windows.ps1` script
   - Auto-detects KiCAD installation
   - Auto-detects Python paths
   - Installs all dependencies
   - Builds project
   - Generates configuration
   - Validates setup

**Typical paths:**

```powershell
KiCAD Python: C:\Program Files\KiCad\9.0\bin\python.exe
KiCAD Libraries: C:\Program Files\KiCad\9.0\lib\python3\dist-packages
Node.js: C:\Program Files\nodejs\node.exe
```

**Configuration example:**

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["C:\\Users\\username\\KiCAD-MCP-Server\\dist\\index.js"],
      "env": {
        "PYTHONPATH": "C:\\Program Files\\KiCad\\9.0\\lib\\python3\\dist-packages"
      }
    }
  }
}
```

---

## Path Handling

### Linux Paths

- Use forward slashes: `/home/user/project`
- Case-sensitive filesystem
- No drive letters
- Symbolic links commonly used

**Example commands:**

```bash
cd /home/username/KiCAD-MCP-Server
export PYTHONPATH=/usr/lib/kicad/lib/python3/dist-packages
python3 -c "import pcbnew"
```

### macOS Paths

- Use forward slashes: `/Users/username/project`
- Case-insensitive but case-preserving filesystem (APFS default)
- No drive letters
- KiCAD paths are inside the `.app` bundle

**Example commands:**

```bash
cd ~/KiCAD-MCP-Server
export KICAD_PYTHON=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
"$KICAD_PYTHON" -c "import pcbnew"
```

### Windows Paths

- Use backslashes in native commands: `C:\Users\username`
- Use double backslashes in JSON: `C:\\Users\\username`
- OR use forward slashes in JSON: `C:/Users/username`
- Case-insensitive filesystem (but preserve case)
- Drive letters required (C:, D:, etc.)

**Example commands:**

```powershell
cd C:\Users\username\KiCAD-MCP-Server
$env:PYTHONPATH = "C:\Program Files\KiCad\9.0\lib\python3\dist-packages"
& "C:\Program Files\KiCad\9.0\bin\python.exe" -c "import pcbnew"
```

**JSON configuration notes:**

```json
// Wrong - single backslash will cause errors
"args": ["C:\Users\name\project"]

// Correct - double backslashes
"args": ["C:\\Users\\name\\project"]

// Also correct - forward slashes work in JSON
"args": ["C:/Users/name/project"]
```

---

## Python Environment

### Linux

**System Python:**

- Usually Python 3.10+ available system-wide
- KiCAD uses system Python with additional modules
- Virtual environments recommended for isolation

**Setup:**

```bash
# Check Python version
python3 --version

# Verify pcbnew module
python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"

# Install project dependencies
pip3 install -r requirements.txt

# Or use virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**PYTHONPATH:**

```bash
# Temporary (current session)
export PYTHONPATH=/usr/lib/kicad/lib/python3/dist-packages

# Permanent (add to ~/.bashrc or ~/.profile)
echo 'export PYTHONPATH=/usr/lib/kicad/lib/python3/dist-packages' >> ~/.bashrc
```

### macOS

**KiCAD Bundled Python:**

- KiCAD bundles Python inside the `.app` framework (versions 3.9–3.12)
- No system Python installation needed for pcbnew
- `setup-macos.sh` detects the correct path automatically

**Setup:**

```bash
# Check KiCAD Python
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 --version

# Verify pcbnew module
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"

# Or use the setup script to verify everything at once
bash setup-macos.sh --verify
```

### Windows

**KiCAD Bundled Python:**

- KiCAD 9.0 includes Python 3.11
- No system Python installation needed
- Use KiCAD's Python for all MCP operations

**Setup:**

```powershell
# Check KiCAD Python
& "C:\Program Files\KiCad\9.0\bin\python.exe" --version

# Verify pcbnew module
& "C:\Program Files\KiCad\9.0\bin\python.exe" -c "import pcbnew; print(pcbnew.GetBuildVersion())"

# Install project dependencies using KiCAD Python
& "C:\Program Files\KiCad\9.0\bin\python.exe" -m pip install -r requirements.txt
```

**PYTHONPATH:**

```powershell
# Temporary (current session)
$env:PYTHONPATH = "C:\Program Files\KiCad\9.0\lib\python3\dist-packages"

# In MCP configuration (permanent)
{
  "env": {
    "PYTHONPATH": "C:\\Program Files\\KiCad\\9.0\\lib\\python3\\dist-packages"
  }
}
```

---

## Testing and Debugging

### Linux

**Check KiCAD installation:**

```bash
which kicad
kicad --version
```

**Check Python module:**

```bash
python3 -c "import sys; print(sys.path)"
python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"
```

**Run tests:**

```bash
cd /home/username/KiCAD-MCP-Server
npm test
pytest tests/
```

**View logs:**

```bash
tail -f ~/.kicad-mcp/logs/kicad_interface.log
```

**Start server manually:**

```bash
export PYTHONPATH=/usr/lib/kicad/lib/python3/dist-packages
node dist/index.js
```

### macOS

**Check KiCAD installation:**

```bash
ls /Applications/KiCad/KiCad.app
```

**Run automated diagnostics:**

```bash
bash setup-macos.sh --verify
```

**View logs:**

```bash
tail -f ~/.kicad-mcp/logs/kicad_interface.log
```

**Start server manually:**

```bash
node dist/index.js
```

### Windows

**Check KiCAD installation:**

```powershell
Test-Path "C:\Program Files\KiCad\9.0"
& "C:\Program Files\KiCad\9.0\bin\kicad.exe" --version
```

**Check Python module:**

```powershell
& "C:\Program Files\KiCad\9.0\bin\python.exe" -c "import sys; print(sys.path)"
& "C:\Program Files\KiCad\9.0\bin\python.exe" -c "import pcbnew; print(pcbnew.GetBuildVersion())"
```

**Run automated diagnostics:**

```powershell
.\setup-windows.ps1
```

**View logs:**

```powershell
Get-Content "$env:USERPROFILE\.kicad-mcp\logs\kicad_interface.log" -Tail 50 -Wait
```

**Start server manually:**

```powershell
$env:PYTHONPATH = "C:\Program Files\KiCad\9.0\lib\python3\dist-packages"
node dist\index.js
```

---

## Common Issues

### Linux-Specific Issues

**1. Permission Errors**

```bash
# Fix file permissions
chmod +x python/kicad_interface.py

# Fix directory permissions
chmod -R 755 ~/KiCAD-MCP-Server
```

**2. PYTHONPATH Not Set**

```bash
# Check current PYTHONPATH
echo $PYTHONPATH

# Find KiCAD Python path
find /usr -name "pcbnew.py" 2>/dev/null
```

**3. KiCAD Not in PATH**

```bash
# Add to PATH temporarily
export PATH=$PATH:/usr/bin

# Or use full path to KiCAD
/usr/bin/kicad
```

**4. Library Dependencies**

```bash
# Install missing system libraries
sudo apt-get install python3-wxgtk4.0 python3-cairo

# Check library linkage
ldd /usr/lib/kicad/lib/python3/dist-packages/pcbnew.so
```

### macOS-Specific Issues

**1. KiCad Python Not Found**

```bash
# Verify the expected path exists
ls /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3

# If installed elsewhere, set the override
export KICAD_PYTHON=/path/to/your/kicad/python3
bash setup-macos.sh --verify
```

**2. pcbnew Import Fails**

- Run `bash setup-macos.sh --verify` — the Prerequisites section will show a ✗ if pcbnew can't be imported
- Reinstall KiCAD if the bundled Python is corrupted

**3. Claude Config Not Picked Up**

- Default path is `~/Library/Application Support/Claude/claude_desktop_config.json`
- Use `--claude-config` flag to point to a different location
- Fully quit and reopen Claude Desktop after changes

### Windows-Specific Issues

**1. Server Exits Immediately**

- Most common issue
- Usually means pcbnew import failed
- Solution: Run `setup-windows.ps1` for diagnostics

**2. Path Issues in Configuration**

```powershell
# Test path accessibility
Test-Path "C:\Users\name\KiCAD-MCP-Server\dist\index.js"

# Use Tab completion in PowerShell to get correct paths
cd C:\Users\[TAB]
```

**3. PowerShell Execution Policy**

```powershell
# Check current policy
Get-ExecutionPolicy

# Set policy to allow scripts (if needed)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**4. Antivirus Blocking**

```
Windows Defender may block Node.js or Python processes
Solution: Add exclusion for project directory in Windows Security
```

---

## Performance Considerations

### Linux

- Generally faster file I/O operations
- Better process management
- Lower memory overhead
- Native Unix socket support (future IPC backend)

### Windows

- Slightly slower file operations
- More memory overhead
- Extra startup validation checks (for diagnostics)
- Named pipes for IPC (future backend)

**Both platforms perform equivalently for normal PCB design operations.**

---

## Development Workflow

### Linux Development Environment

**Typical workflow:**

```bash
# Start development
cd ~/KiCAD-MCP-Server
code .  # Open in VSCode

# Watch mode for TypeScript
npm run watch

# Run tests in another terminal
npm test

# Test Python changes
python3 python/kicad_interface.py
```

**Recommended tools:**

- Terminal: GNOME Terminal, Konsole, or Alacritty
- Editor: VSCode with Python and TypeScript extensions
- Process monitoring: `htop` or `top`
- Log viewing: `tail -f` or `less +F`

### Windows Development Environment

**Typical workflow:**

```powershell
# Start development
cd C:\Users\username\KiCAD-MCP-Server
code .  # Open in VSCode

# Watch mode for TypeScript
npm run watch

# Run tests in another PowerShell window
npm test

# Test Python changes
& "C:\Program Files\KiCad\9.0\bin\python.exe" python\kicad_interface.py
```

**Recommended tools:**

- Terminal: Windows Terminal or PowerShell 7
- Editor: VSCode with Python and TypeScript extensions
- Process monitoring: Task Manager or Process Explorer
- Log viewing: `Get-Content -Wait` or Notepad++

---

## Best Practices

### Linux

1. **Use virtual environments** for Python dependencies
2. **Set PYTHONPATH** in your shell profile for persistence
3. **Use absolute paths** in MCP configuration
4. **Check file permissions** if encountering access errors
5. **Monitor system logs** with `journalctl` if needed

### macOS

1. **Run `setup-macos.sh --verify` first** — confirms all prerequisites
2. **Use `--dry-run` before `--apply`** — review the merged config before writing
3. **Use KiCAD's bundled Python** — don't rely on system or Homebrew Python for pcbnew
4. **Override with `KICAD_PYTHON` env var** if KiCAD is in a non-standard location
5. **Check logs** in `~/.kicad-mcp/logs/` when debugging

### Windows

1. **Run setup-windows.ps1 first** - saves time troubleshooting
2. **Use KiCAD's bundled Python** - don't install system Python
3. **Use forward slashes** in JSON configs to avoid escaping
4. **Check log file** when debugging - it has detailed errors
5. **Keep paths short** - avoid deeply nested directories

---

## Migration Between Platforms

### Moving from Linux to Windows

1. Clone repository on Windows machine
2. Run `setup-windows.ps1`
3. Update config file path separators (/ to \\)
4. Update PYTHONPATH to Windows format
5. No project file changes needed (KiCAD files are cross-platform)

### Moving from Windows to Linux

1. Clone repository on Linux machine
2. Follow Linux installation steps
3. Update config file path separators (\\ to /)
4. Update PYTHONPATH to Linux format
5. Set file permissions: `chmod +x python/kicad_interface.py`

### Moving to/from macOS

1. Clone repository on the target machine
2. Run `npm install && npm run build`
3. Run `bash setup-macos.sh --apply` (to macOS) or follow the target platform's setup
4. No project file changes needed

**KiCAD project files (.kicad_pro, .kicad_pcb) are identical across platforms.**

---

## Getting Help

### Linux Support

- Check: [README.md](../README.md) Linux installation section
- Read: [KNOWN_ISSUES.md](./KNOWN_ISSUES.md)
- Search: GitHub Issues filtered by `linux` label
- Community: Linux users in Discussions

### macOS Support

- Check: [README.md](../README.md) macOS installation section
- Run: `bash setup-macos.sh --verify` for automated diagnostics
- Search: GitHub Issues filtered by `macos` label
- Community: macOS users in Discussions

### Windows Support

- Check: [README.md](../README.md) Windows installation section
- Read: [WINDOWS_TROUBLESHOOTING.md](./WINDOWS_TROUBLESHOOTING.md)
- Run: `setup-windows.ps1` for automated diagnostics
- Search: GitHub Issues filtered by `windows` label
- Community: Windows users in Discussions

---

## Summary

**Choose Linux if:**

- You're comfortable with command-line tools
- You want the most stable, tested environment
- You're developing or contributing to the project
- You need maximum performance

**Choose macOS if:**

- You're already using KiCAD on macOS
- You want automated setup with `setup-macos.sh`
- You prefer a Unix-based development environment

**Choose Windows if:**

- You want automated setup and diagnostics
- You're less comfortable with terminal commands
- You need detailed troubleshooting guidance
- You're a KiCAD user new to development tools

**All platforms work well for PCB design with KiCAD MCP. Choose based on your comfort level and existing development environment.**

---

**For platform-specific installation instructions, see:**

- Linux: [README.md - Linux Installation](../README.md#linux-ubuntudebian)
- macOS: [README.md - macOS Installation](../README.md#macos)
- Windows: [README.md - Windows Installation](../README.md#windows-1011)

**For troubleshooting:**

- Linux: [KNOWN_ISSUES.md](./KNOWN_ISSUES.md)
- macOS: Run `bash setup-macos.sh --verify`
- Windows: [WINDOWS_TROUBLESHOOTING.md](./WINDOWS_TROUBLESHOOTING.md)
