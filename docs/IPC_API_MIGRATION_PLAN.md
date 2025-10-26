# KiCAD IPC API Migration Plan

**Status:** 📋 Planning
**Target Completion:** Week 2-3 (November 1-8, 2025)
**Priority:** 🔴 **CRITICAL** - Current SWIG API deprecated

---

## Executive Summary

The current KiCAD MCP Server uses SWIG-based Python bindings (`import pcbnew`) which are **deprecated as of KiCAD 9.0** and will be **removed in KiCAD 10.0**. We must migrate to the official **KiCAD IPC API** to future-proof the project.

### Why Migrate?

| SWIG API (Current) | IPC API (Future) |
|-------------------|------------------|
| ❌ Deprecated | ✅ Official & Supported |
| ❌ Will be removed in KiCAD 10.0 | ✅ Long-term stability |
| ❌ Python-only | ✅ Multi-language (Python, JS, etc.) |
| ❌ Direct linking | ✅ Inter-process communication |
| ⚠️ Synchronous only | ✅ Async support |
| ⚠️ No versioning | ✅ Protocol Buffers versioning |

**Decision: Migrate immediately to avoid technical debt**

---

## IPC API Overview

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              TypeScript MCP Server (Node.js)                 │
└──────────────────────┬──────────────────────────────────────┘
                       │ JSON over stdin/stdout
┌──────────────────────▼──────────────────────────────────────┐
│              Python Interface Layer                          │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  KiCAD API Abstraction (NEW)                          │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────┬──────────────────────────────────────┘
                       │ kicad-python library
┌──────────────────────▼──────────────────────────────────────┐
│          KiCAD IPC Server (Protocol Buffers)                 │
│          Running inside KiCAD Process                        │
└──────────────────────┬──────────────────────────────────────┘
                       │ UNIX Sockets / Named Pipes
┌──────────────────────▼──────────────────────────────────────┐
│              KiCAD 9.0+ Application                          │
└─────────────────────────────────────────────────────────────┘
```

### Key Differences

1. **KiCAD Must Be Running**
   - SWIG: Can run headless, no KiCAD GUI needed
   - IPC: Requires KiCAD running with IPC server enabled

2. **Communication Method**
   - SWIG: Direct Python module import
   - IPC: Socket-based RPC (Remote Procedure Call)

3. **API Structure**
   - SWIG: `board.SetSize(width, height)`
   - IPC: `kicad.get_board().set_size(width, height)`

---

## Migration Strategy

### Phase 1: Research & Preparation (Days 1-2)

**Goals:**
- Understand kicad-python library
- Test IPC connection
- Document API differences

**Tasks:**
```bash
# Install kicad-python
pip install kicad-python>=0.5.0

# Test basic connection
python3 << EOF
from kicad import KiCad
kicad = KiCad()
print(f"Connected to KiCAD: {kicad.check_version()}")
EOF

# Read official documentation
# https://docs.kicad.org/kicad-python-main
```

**Deliverables:**
- [ ] kicad-python installed and tested
- [ ] Connection test script
- [ ] API comparison document (SWIG vs IPC)

---

### Phase 2: Abstraction Layer (Days 3-4)

**Goal:** Create an abstraction layer to support both APIs during transition

**File Structure:**
```
python/kicad_api/
├── __init__.py
├── base.py                 # Abstract base class
├── ipc_backend.py          # NEW: IPC API implementation
├── swig_backend.py         # Legacy SWIG implementation
└── factory.py              # Backend selector
```

**Abstract Interface:**
```python
# python/kicad_api/base.py
from abc import ABC, abstractmethod
from typing import Optional
from pathlib import Path

class KiCADBackend(ABC):
    """Abstract base class for KiCAD API backends"""

    @abstractmethod
    def connect(self) -> bool:
        """Connect to KiCAD"""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from KiCAD"""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connected"""
        pass

    @abstractmethod
    def create_project(self, path: Path, name: str) -> dict:
        """Create a new KiCAD project"""
        pass

    @abstractmethod
    def open_project(self, path: Path) -> dict:
        """Open existing project"""
        pass

    @abstractmethod
    def get_board(self) -> 'BoardAPI':
        """Get board API"""
        pass

    # ... more abstract methods
```

**IPC Implementation:**
```python
# python/kicad_api/ipc_backend.py
from kicad import KiCad
from kicad_api.base import KiCADBackend

class IPCBackend(KiCADBackend):
    """KiCAD IPC API backend"""

    def __init__(self):
        self.kicad = None

    def connect(self) -> bool:
        """Connect to running KiCAD instance"""
        try:
            self.kicad = KiCad()
            # Verify connection
            version = self.kicad.check_version()
            logger.info(f"Connected to KiCAD via IPC: {version}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect via IPC: {e}")
            return False

    def create_project(self, path: Path, name: str) -> dict:
        """Create project using IPC API"""
        # Implementation here
        pass
```

**Backend Factory:**
```python
# python/kicad_api/factory.py
from typing import Optional
from kicad_api.base import KiCADBackend
from kicad_api.ipc_backend import IPCBackend
from kicad_api.swig_backend import SWIGBackend

def create_backend(backend_type: Optional[str] = None) -> KiCADBackend:
    """
    Create appropriate KiCAD backend

    Args:
        backend_type: 'ipc', 'swig', or None for auto-detect

    Returns:
        KiCADBackend instance
    """
    if backend_type == 'ipc':
        return IPCBackend()
    elif backend_type == 'swig':
        return SWIGBackend()
    else:
        # Auto-detect: Try IPC first, fall back to SWIG
        try:
            backend = IPCBackend()
            if backend.connect():
                return backend
        except ImportError:
            pass

        # Fall back to SWIG
        return SWIGBackend()
```

**Deliverables:**
- [ ] Abstract base class defined
- [ ] IPC backend implemented
- [ ] SWIG backend (wrapper around existing code)
- [ ] Factory with auto-detection

---

### Phase 3: Port Core Modules (Days 5-8)

**Migration Order** (by complexity):

1. **project.py** (Simple - good starting point)
   - Create, open, save projects
   - Estimated: 2 hours

2. **board.py** (Medium - board properties)
   - Set size, layers, outline
   - Estimated: 4 hours

3. **component.py** (Complex - many operations)
   - Place, move, rotate, delete
   - Component arrays and alignment
   - Estimated: 8 hours

4. **routing.py** (Complex - trace routing)
   - Nets, traces, vias
   - Copper pours, differential pairs
   - Estimated: 8 hours

5. **design_rules.py** (Medium - DRC)
   - Set rules, run DRC
   - Estimated: 4 hours

6. **export.py** (Medium - file exports)
   - Gerber, PDF, SVG, 3D
   - Estimated: 4 hours

**Total Estimated Time: 30 hours (~4 days)**

**Migration Template:**
```python
# OLD (SWIG)
import pcbnew
board = pcbnew.LoadBoard(filename)
board.SetBoardSize(width, height)

# NEW (IPC via abstraction)
from kicad_api import create_backend
backend = create_backend('ipc')
backend.connect()
board_api = backend.get_board()
board_api.set_size(width, height)
```

**Deliverables:**
- [ ] project.py migrated
- [ ] board.py migrated
- [ ] component.py migrated
- [ ] routing.py migrated
- [ ] design_rules.py migrated
- [ ] export.py migrated

---

### Phase 4: Testing & Validation (Days 9-10)

**Testing Strategy:**

1. **Unit Tests**
   ```python
   @pytest.mark.parametrize("backend_type", ["ipc", "swig"])
   def test_create_project(backend_type):
       backend = create_backend(backend_type)
       result = backend.create_project(Path("/tmp/test"), "TestProject")
       assert result["success"] is True
   ```

2. **Integration Tests**
   - Run side-by-side: IPC vs SWIG
   - Compare outputs for identical operations
   - Verify file compatibility

3. **Performance Benchmarks**
   ```python
   # Measure: operations/second for each backend
   # Expected: IPC slightly slower due to IPC overhead
   ```

**Deliverables:**
- [ ] 50+ unit tests passing for IPC backend
- [ ] Side-by-side comparison tests
- [ ] Performance benchmarks documented

---

## API Comparison Reference

### Project Operations

| Operation | SWIG | IPC |
|-----------|------|-----|
| Create project | Custom file creation | `kicad.create_project()` |
| Open project | `pcbnew.LoadBoard()` | `kicad.open_project()` |
| Save project | `board.Save()` | `board.save()` |

### Board Operations

| Operation | SWIG | IPC |
|-----------|------|-----|
| Get board | `pcbnew.LoadBoard()` | `kicad.get_board()` |
| Set size | `board.SetBoardSize()` | `board.set_size()` |
| Add layer | `board.GetLayerCount()` | `board.layers.add()` |

### Component Operations

| Operation | SWIG | IPC |
|-----------|------|-----|
| Place component | `pcbnew.FOOTPRINT()` | `board.add_footprint()` |
| Move component | `fp.SetPosition()` | `footprint.set_position()` |
| Rotate component | `fp.SetOrientation()` | `footprint.set_rotation()` |

### Routing Operations

| Operation | SWIG | IPC |
|-----------|------|-----|
| Add net | `board.GetNetCount()` | `board.nets.add()` |
| Route trace | `pcbnew.PCB_TRACK()` | `board.add_track()` |
| Add via | `pcbnew.PCB_VIA()` | `board.add_via()` |

---

## Configuration Changes

### Update requirements.txt

```diff
+ # KiCAD IPC API (official Python bindings)
+ kicad-python>=0.5.0

  # Legacy SWIG support (for backward compatibility)
  kicad-skip>=0.1.0
```

### Environment Variables

```bash
# Enable IPC API in KiCAD preferences
# Preferences > Plugins > Enable IPC API Server

# Set backend preference (optional)
export KICAD_BACKEND=ipc  # or 'swig' or 'auto'
```

### User Migration Guide

Create `docs/MIGRATING_TO_IPC.md`:
- How to enable IPC in KiCAD
- What changes for users
- Troubleshooting IPC connection issues

---

## Rollback Plan

If IPC migration fails:

1. **Keep SWIG backend** - Already abstracted
2. **Default to SWIG** - Change factory auto-detection
3. **Document limitations** - Note that SWIG will be removed eventually
4. **Plan retry** - Schedule IPC migration for later

---

## Success Criteria

- [ ] ✅ All existing functionality works with IPC backend
- [ ] ✅ Tests pass with both IPC and SWIG backends
- [ ] ✅ Performance acceptable (< 20% slowdown vs SWIG)
- [ ] ✅ Documentation updated
- [ ] ✅ Migration guide created
- [ ] ✅ User-facing tools work without changes

---

## Timeline

| Week | Days | Tasks |
|------|------|-------|
| **Week 2** | Mon-Tue | Research, install kicad-python, test connection |
| | Wed-Thu | Build abstraction layer |
| | Fri | Port project.py and board.py |
| **Week 3** | Mon-Tue | Port component.py and routing.py |
| | Wed | Port design_rules.py and export.py |
| | Thu-Fri | Testing, validation, documentation |

---

## Resources

- **Official Docs:** https://docs.kicad.org/kicad-python-main
- **kicad-python PyPI:** https://pypi.org/project/kicad-python/
- **IPC API Spec:** https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/
- **Protocol Buffers:** Used by IPC for message format

---

## Open Questions

1. **How to handle KiCAD not running?**
   - Option A: Auto-launch KiCAD in background
   - Option B: Require user to launch KiCAD first
   - Option C: Fall back to SWIG if IPC unavailable
   - **Decision: Option C for now, A later**

2. **Connection management**
   - Should we keep connection open or connect per-operation?
   - **Decision: Keep alive with reconnect logic**

3. **Performance vs reliability**
   - IPC has overhead but more stable
   - **Decision: Reliability > performance**

---

## Next Steps (This Week)

1. **Install kicad-python**
   ```bash
   pip install kicad-python
   ```

2. **Test IPC connection**
   ```bash
   # Launch KiCAD
   # Enable IPC in preferences
   python3 -c "from kicad import KiCad; k=KiCad(); print(k.check_version())"
   ```

3. **Create abstraction layer structure**
   ```bash
   mkdir -p python/kicad_api
   touch python/kicad_api/{__init__,base,ipc_backend,swig_backend,factory}.py
   ```

4. **Begin project.py migration**
   - Start with simplest module
   - Establish patterns for others

---

**Prepared by:** Claude Code
**Last Updated:** October 25, 2025
**Status:** 📋 Ready to execute
