# Changelog

All notable changes to the KiCAD MCP Server project are documented here.

## [2.1.0-alpha] - 2026-01-10

### Phase 2: JLCPCB Integration Complete

**Major Features:**
- ✅ Complete JLCPCB parts integration via JLCSearch public API
- ✅ Access to ~100k JLCPCB parts catalog
- ✅ Real-time stock and pricing data
- ✅ Parametric component search
- ✅ Cost optimization (Basic vs Extended library)
- ✅ KiCad footprint mapping
- ✅ Alternative part suggestions

**New Components:**
- `python/commands/jlcsearch.py` - JLCSearch API client (no auth required)
- `python/commands/jlcpcb_parts.py` - Enhanced with `import_jlcsearch_parts()`
- `docs/JLCPCB_INTEGRATION.md` - Comprehensive integration guide

**MCP Tools Available:**
- `download_jlcpcb_database` - Download full parts catalog
- `search_jlcpcb_parts` - Parametric search with filters
- `get_jlcpcb_part` - Part details + footprint suggestions
- `get_jlcpcb_database_stats` - Database statistics
- `suggest_jlcpcb_alternatives` - Find similar/cheaper parts

**Technical Improvements:**
- SQLite database with full-text search (FTS5)
- Package-to-footprint mapping for standard SMD packages
- Price comparison and cost optimization algorithms
- HMAC-SHA256 authentication support (for official JLCPCB API)

**Testing:**
- All integration tests passing
- Database operations validated
- Live API connectivity confirmed
- End-to-end MCP tool testing complete

**Documentation:**
- Complete API reference with examples
- Package mapping tables (0402, 0603, 0805, SOT-23, etc.)
- Best practices guide
- Troubleshooting section

---

## [2.1.0-alpha] - 2025-11-30

### Phase 1: Schematic Workflow Fix

**Critical Bug Fix:**
- ✅ Fixed completely broken schematic workflow (Issue #26)
- Created template-based symbol cloning approach
- All schematic tests now passing

**Root Cause:**
- kicad-skip library limitation: cannot create symbols from scratch, only clone existing ones

**Solution:**
- Template schematic with cloneable R, C, LED symbols
- Updated `create_project` to create both PCB and schematic
- Rewrote `add_schematic_component` to use `clone()` API
- Proper UUID generation and position setting

**Files Modified:**
- `python/commands/project.py` - Now creates schematic files
- `python/commands/schematic.py` - Uses template approach
- `python/commands/component_schematic.py` - Complete rewrite

**Files Created:**
- `python/templates/template_with_symbols.kicad_sch`
- `python/templates/empty.kicad_sch`
- `docs/SCHEMATIC_WORKFLOW_FIX.md`

**Testing:**
- Created comprehensive test suite
- All 7 tests passing
- KiCad CLI validation successful

---

## [2.0.0-alpha] - 2025-11-05

### Router Pattern & Tool Organization

**Major Architecture Change:**
- Implemented tool router pattern (70% context reduction)
- 12 direct tools, 47 routed tools in 7 categories
- Smart tool discovery system

**New Router Tools:**
- `list_tool_categories` - Browse available categories
- `get_category_tools` - View tools in category
- `search_tools` - Find tools by keyword
- `execute_tool` - Run any routed tool

**Benefits:**
- Dramatically reduced AI context usage
- Maintained full functionality (64 tools)
- Improved tool discoverability
- Better organization for users

---

## [2.0.0-alpha] - 2025-11-01

### IPC Backend Integration

**Experimental Feature:**
- KiCad 9.0 IPC API integration for real-time UI sync
- Changes appear immediately in KiCad (no manual reload)
- Hybrid backend: IPC + SWIG fallback
- 20+ commands with IPC support

**Implementation:**
- Routing operations (interactive push-and-shove)
- Component placement and modification
- Zone operations and fills
- DRC and verification

**Status:**
- Under active development
- Enable via KiCad: Preferences > Plugins > Enable IPC API Server
- Automatic fallback to SWIG when IPC unavailable

---

## [2.0.0-alpha] - 2025-10-26

### Initial JLCPCB Integration (Local Libraries)

**Features:**
- Local JLCPCB symbol library search
- Integration with KiCad Plugin and Content Manager
- Search by LCSC part number, manufacturer, description

**Credit:**
- Contributed by [@l3wi](https://github.com/l3wi)

**Components:**
- `python/commands/symbol_library.py`
- Basic library search functionality

---

## [1.0.0] - 2025-10-01

### Initial Release

**Core Features:**
- 64 fully-documented MCP tools
- JSON Schema validation for all tools
- 8 dynamic resources for project state
- Cross-platform support (Linux, Windows, macOS)
- Comprehensive error handling
- Detailed logging

**Tool Categories:**
- Project Management (4 tools)
- Board Operations (9 tools)
- Component Management (8 tools)
- Routing (6 tools)
- Export & Manufacturing (5 tools)
- Design Rule Checking (4 tools)
- Schematic Operations (6 tools)
- Symbol Library (3 tools)
- JLCPCB Integration (5 tools)

**Platform Support:**
- Linux (KiCad 7.x, 8.x, 9.x)
- Windows (KiCad 9.x)
- macOS (KiCad 9.x)

**Documentation:**
- Complete README with setup instructions
- Platform-specific guides
- Tool reference documentation
- Contributing guidelines

---

## Version Numbering

- **2.1.0-alpha**: Current development version with JLCPCB integration
- **2.0.0-alpha**: Router pattern and IPC backend
- **1.0.0**: Initial stable release

## Breaking Changes

### 2.1.0-alpha
- None (additive changes only)

### 2.0.0-alpha
- Tool execution now requires router for 47 tools
- Direct tool access limited to 12 high-frequency tools
- Schema validation stricter (catches errors earlier)

## Deprecations

### 2.1.0-alpha
- `docs/JLCPCB_USAGE_GUIDE.md` - Superseded by `docs/JLCPCB_INTEGRATION.md`
- `docs/JLCPCB_INTEGRATION_PLAN.md` - Implementation complete

## Migration Guide

### Upgrading to 2.1.0-alpha from 2.0.0-alpha

**New Dependencies:**
- No new system dependencies
- Python packages: `requests` (already in requirements.txt)

**Database Setup:**
1. Run `download_jlcpcb_database` tool (one-time, ~5-10 minutes)
2. Database created at `data/jlcpcb_parts.db`
3. Subsequent searches use local database (instant)

**API Changes:**
- All existing tools remain compatible
- 5 new JLCPCB tools available
- No breaking changes to existing functionality

### Upgrading to 2.0.0-alpha from 1.0.0

**Router Pattern:**
- Some tools now accessed via `execute_tool` instead of direct calls
- Use `list_tool_categories` to discover available tools
- Search with `search_tools` to find specific functionality

**IPC Backend (Optional):**
- Enable in KiCad: Preferences > Plugins > Enable IPC API Server
- Set `KICAD_BACKEND=ipc` environment variable
- Falls back to SWIG if unavailable

---

## Credits

- **JLCSearch API**: [@tscircuit](https://github.com/tscircuit/jlcsearch)
- **JLCParts Database**: [@yaqwsx](https://github.com/yaqwsx/jlcparts)
- **Local JLCPCB Search**: [@l3wi](https://github.com/l3wi)
- **KiCad**: KiCad Development Team
- **MCP Protocol**: Anthropic

## License

See LICENSE file for details.
