# Linux Compatibility Audit Report
**Date:** 2025-10-25
**Target Platform:** Ubuntu 24.04 LTS (primary), Fedora, Arch (secondary)
**Current Status:** Windows-optimized, partial Linux support

---

## Executive Summary

The KiCAD MCP Server was originally developed for Windows and has several compatibility issues preventing smooth operation on Linux. This audit identifies all platform-specific issues and provides remediation priorities.

**Overall Status:** 🟡 **PARTIAL COMPATIBILITY**
- ✅ TypeScript server: Good cross-platform support
- 🟡 Python interface: Mixed (some hardcoded paths)
- ❌ Configuration: Windows-specific examples
- ❌ Documentation: Windows-only instructions

---

## Critical Issues (P0 - Must Fix)

### 1. Hardcoded Windows Paths in Config Examples
**File:** `config/claude-desktop-config.json`
```json
"cwd": "c:/repo/KiCAD-MCP",
"PYTHONPATH": "C:/Program Files/KiCad/9.0/lib/python3/dist-packages"
```

**Impact:** Config file won't work on Linux without manual editing
**Fix:** Create platform-specific config templates
**Priority:** P0

---

### 2. Library Search Paths (Mixed Approach)
**File:** `python/commands/library_schematic.py:16`
```python
search_paths = [
    "C:/Program Files/KiCad/*/share/kicad/symbols/*.kicad_sym",  # Windows
    "/usr/share/kicad/symbols/*.kicad_sym",                      # Linux
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/*.kicad_sym",  # macOS
]
```

**Impact:** Works but inefficient (checks all platforms)
**Fix:** Auto-detect platform and use appropriate paths
**Priority:** P0

---

### 3. Python Path Detection
**File:** `python/kicad_interface.py:38-45`
```python
kicad_paths = [
    os.path.join(os.path.dirname(sys.executable), 'Lib', 'site-packages'),
    os.path.dirname(sys.executable)
]
```

**Impact:** Paths use Windows convention ('Lib' is 'lib' on Linux)
**Fix:** Platform-specific path detection
**Priority:** P0

---

## High Priority Issues (P1)

### 4. Documentation is Windows-Only
**Files:** `README.md`, installation instructions

**Issues:**
- Installation paths reference `C:\Program Files`
- VSCode settings path is Windows format
- No Linux-specific troubleshooting

**Fix:** Add Linux installation section
**Priority:** P1

---

### 5. Missing Python Dependencies Documentation
**File:** None (no requirements.txt)

**Impact:** Users don't know what Python packages to install
**Fix:** Create `requirements.txt` and `requirements-dev.txt`
**Priority:** P1

---

### 6. Path Handling Uses os.path Instead of pathlib
**Files:** All Python files (11 files)

**Impact:** Code is less readable and more error-prone
**Fix:** Migrate to `pathlib.Path` throughout
**Priority:** P1

---

## Medium Priority Issues (P2)

### 7. No Linux-Specific Testing
**Impact:** Can't verify Linux compatibility
**Fix:** Add GitHub Actions with Ubuntu runner
**Priority:** P2

---

### 8. Log File Paths May Differ
**File:** `src/logger.ts:13`
```typescript
const DEFAULT_LOG_DIR = join(os.homedir(), '.kicad-mcp', 'logs');
```

**Impact:** `.kicad-mcp` is okay for Linux, but best practice is `~/.config/kicad-mcp`
**Fix:** Use XDG Base Directory spec on Linux
**Priority:** P2

---

### 9. No Bash/Shell Scripts for Linux
**Impact:** Manual setup is harder on Linux
**Fix:** Create `install.sh` and `run.sh` scripts
**Priority:** P2

---

## Low Priority Issues (P3)

### 10. TypeScript Build Uses Windows Conventions
**File:** `package.json`

**Impact:** Works but could be more Linux-friendly
**Fix:** Add platform-specific build scripts
**Priority:** P3

---

## Positive Findings ✅

### What's Already Good:

1. **TypeScript Path Handling** - Uses `path.join()` and `os.homedir()` correctly
2. **Node.js Dependencies** - All cross-platform
3. **JSON Communication** - Platform-agnostic
4. **Python Base** - Python 3 works identically on all platforms

---

## Recommended Fixes - Priority Order

### **Week 1 - Critical Fixes (P0)**

1. **Create Platform-Specific Config Templates**
   ```bash
   config/
   ├── linux-config.example.json
   ├── windows-config.example.json
   └── macos-config.example.json
   ```

2. **Fix Python Path Detection**
   ```python
   # Detect platform and set appropriate paths
   import platform
   import sys
   from pathlib import Path

   if platform.system() == "Windows":
       kicad_paths = [Path(sys.executable).parent / "Lib" / "site-packages"]
   else:  # Linux/Mac
       kicad_paths = [Path(sys.executable).parent / "lib" / "python3.X" / "site-packages"]
   ```

3. **Update Library Search Path Logic**
   ```python
   def get_kicad_library_paths():
       """Auto-detect KiCAD library paths based on platform"""
       system = platform.system()
       if system == "Windows":
           return ["C:/Program Files/KiCad/*/share/kicad/symbols/*.kicad_sym"]
       elif system == "Linux":
           return ["/usr/share/kicad/symbols/*.kicad_sym"]
       elif system == "Darwin":  # macOS
           return ["/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/*.kicad_sym"]
   ```

### **Week 1 - High Priority (P1)**

4. **Create requirements.txt**
   ```txt
   # requirements.txt
   kicad-skip>=0.1.0
   Pillow>=9.0.0
   cairosvg>=2.7.0
   colorlog>=6.7.0
   ```

5. **Add Linux Installation Documentation**
   - Ubuntu/Debian instructions
   - Fedora/RHEL instructions
   - Arch Linux instructions

6. **Migrate to pathlib**
   - Convert all `os.path` calls to `Path`
   - More Pythonic and readable

---

## Testing Checklist

### Ubuntu 24.04 LTS Testing
- [ ] Install KiCAD 9.0 from official PPA
- [ ] Install Node.js 18+ from NodeSource
- [ ] Clone repository
- [ ] Run `npm install`
- [ ] Run `npm run build`
- [ ] Configure MCP settings (Cline)
- [ ] Test: Create project
- [ ] Test: Place components
- [ ] Test: Export Gerbers

### Fedora Testing
- [ ] Install KiCAD from Fedora repos
- [ ] Test same workflow

### Arch Testing
- [ ] Install KiCAD from AUR
- [ ] Test same workflow

---

## Platform Detection Helper

Create `python/utils/platform_helper.py`:

```python
"""Platform detection and path utilities"""
import platform
import sys
from pathlib import Path
from typing import List

class PlatformHelper:
    @staticmethod
    def is_windows() -> bool:
        return platform.system() == "Windows"

    @staticmethod
    def is_linux() -> bool:
        return platform.system() == "Linux"

    @staticmethod
    def is_macos() -> bool:
        return platform.system() == "Darwin"

    @staticmethod
    def get_kicad_python_path() -> Path:
        """Get KiCAD Python dist-packages path"""
        if PlatformHelper.is_windows():
            return Path("C:/Program Files/KiCad/9.0/lib/python3/dist-packages")
        elif PlatformHelper.is_linux():
            # Common Linux paths
            candidates = [
                Path("/usr/lib/kicad/lib/python3/dist-packages"),
                Path("/usr/share/kicad/scripting/plugins"),
            ]
            for path in candidates:
                if path.exists():
                    return path
        elif PlatformHelper.is_macos():
            return Path("/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.X/lib/python3.X/site-packages")

        raise RuntimeError(f"Could not find KiCAD Python path for {platform.system()}")

    @staticmethod
    def get_config_dir() -> Path:
        """Get appropriate config directory"""
        if PlatformHelper.is_windows():
            return Path.home() / ".kicad-mcp"
        elif PlatformHelper.is_linux():
            # Use XDG Base Directory specification
            xdg_config = os.environ.get("XDG_CONFIG_HOME")
            if xdg_config:
                return Path(xdg_config) / "kicad-mcp"
            return Path.home() / ".config" / "kicad-mcp"
        elif PlatformHelper.is_macos():
            return Path.home() / "Library" / "Application Support" / "kicad-mcp"
```

---

## Success Criteria

✅ Server starts on Ubuntu 24.04 LTS without errors
✅ Can create and manipulate KiCAD projects
✅ CI/CD pipeline tests on Linux
✅ Documentation includes Linux setup
✅ All tests pass on Linux

---

## Next Steps

1. Implement P0 fixes (this week)
2. Set up GitHub Actions CI/CD
3. Test on Ubuntu 24.04 LTS
4. Document Linux-specific issues
5. Create installation scripts

---

**Audited by:** Claude Code
**Review Status:** ✅ Complete
