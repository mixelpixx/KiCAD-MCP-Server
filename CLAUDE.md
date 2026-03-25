# KiCAD MCP Server

## What This Project Is

An MCP (Model Context Protocol) server that enables AI assistants to design PCBs and schematics in KiCAD. It has a **TypeScript frontend** (MCP server, tool registration, STDIO transport) and a **Python backend** (KiCAD interaction via pcbnew SWIG API and kicad-skip for schematics).

## Architecture

```
AI Client (Claude, etc.)
  ↕ STDIO (MCP protocol)
TypeScript Server (src/)
  ↕ JSON over stdin/stdout (child process)
Python Backend (python/)
  ↕ pcbnew SWIG API / kicad-skip / S-expression manipulation
KiCAD files (.kicad_pcb, .kicad_sch, .kicad_pro)
```

### TypeScript Layer (`src/`)
- `index.ts` — Entry point, starts MCP server
- `server.ts` — `KiCADMcpServer` class, spawns Python child process (with auto-restart on crash), registers all tools/resources/prompts
- `config.ts` — Zod-validated config loading from `config/`
- `logger.ts` — Logger (stderr only; stdout reserved for MCP protocol)
- `tools/*.ts` — Tool registration using `@modelcontextprotocol/sdk`. Each tool calls `callKicadScript(command, args)` which sends JSON to the Python process
- `resources/*.ts` — MCP resource handlers
- `prompts/*.ts` — MCP prompt templates

### Python Layer (`python/`)
- `kicad_interface.py` — Main entry point. Reads JSON commands from stdin, dispatches to command handlers, returns JSON on stdout. Supports IPC and SWIG backends. **WARNING: This is a 7000+ line god file with duplicated pin math in 7 handlers. When fixing pin calculations, check ALL inline pin calc sites, not just `pin_locator.py`.** Contains shared geometry parser `_parse_schematic_geometry()`, content-based static helpers `_delete_component_from_content()`, `_edit_component_in_content()`, T-junction helpers `_point_on_wire_segment()` and `_find_connected_wires()`, and a shared `PinLocator` instance (`self.pin_locator`).
- `commands/` — Command handlers organized by domain:
  - `schematic.py` — `SchematicManager` (create schematic, template-based)
  - `component_schematic.py` — `ComponentManager` (add/edit/delete/move components using kicad-skip + dynamic symbol loading). `add_component` snaps to 1.27mm grid. `remove_component` uses text-based balanced-paren deletion (not kicad-skip `_elements`).
  - `connection_schematic.py` — `ConnectionManager` (wires, net labels, connections)
  - `wire_manager.py` — `WireManager` (thin delegation layer to `sexp_writer.py`)
  - `pin_locator.py` — `PinLocator` (pin position discovery via S-expr parsing, handles rotation + mirror)
  - `sexp_writer.py` — Text-based insertion/deletion for .kicad_sch files (wires, labels, junctions, no-connects, wire splitting). All writes use `f.flush()` + `os.fsync()`. Has `_to_content`/`_from_content` variants for all operations including `add_label_to_content`, `add_polyline_wire_to_content`, `split_wire_at_point_in_content`, `delete_no_connect_from_content`. **Wire placement (`add_wire`, `add_polyline_wire`) now auto-detects T-junctions and adds junction dots** via `auto_add_t_junctions()`. Also has `_parse_wire_segments()`, `_parse_existing_junctions()`, and `_point_on_wire_mid()` helpers for T-junction spatial analysis.
  - `net_analysis.py` — Net-level analysis using union-find graph. `build_net_graph()` builds complete pin→net mapping in O(W+L+P) via union-find with spatial-indexed T-junction detection. Query functions: `get_component_nets`, `get_net_components`, `get_pin_net_name`, `export_netlist_summary`, `validate_component_connections`, `find_shorted_nets`, `find_single_pin_nets`.
  - `component.py` — Board-level component operations (via pcbnew)
  - `routing.py` — Trace routing (via pcbnew)
  - `board.py`, `board/*.py` — Board operations (layers, outline, size, 2D view)
  - `project.py` — Project creation/management
  - `library.py`, `library_schematic.py`, `library_symbol.py` — Library operations
  - `dynamic_symbol_loader.py` — Loads symbols from KiCAD libraries at runtime. `_extract_symbol_block` handles both multi-line and single-line `.kicad_sym` files via balanced-paren traversal.
  - `footprint.py` — Footprint operations
  - `export.py` — Export (Gerber, PDF, SVG, BOM, 3D, etc.)
  - `design_rules.py` — DRC rules
  - `jlcpcb.py`, `jlcpcb_parts.py`, `jlcsearch.py` — JLCPCB integration
  - `datasheet_manager.py` — Datasheet URL extraction
  - `symbol_creator.py` — Custom symbol creation
  - `svg_import.py` — SVG logo import
- `kicad_api/` — Backend abstraction (SWIG vs IPC)
  - `base.py` — Abstract base class
  - `swig_backend.py` — pcbnew SWIG backend
  - `ipc_backend.py` — KiCAD IPC API backend (experimental)
  - `factory.py` — Backend factory
- `schemas/tool_schemas.py` — Python-side tool schema definitions
- `resources/` — Resource definitions
- `utils/` — Platform detection, KiCAD process management
- `templates/` — Schematic templates (used by `create_schematic`)

## Key Libraries & Dependencies

### TypeScript
- `@modelcontextprotocol/sdk` — MCP server framework
- `zod` — Schema validation for tool inputs

### Python
- `kicad-skip` — S-expression-based KiCAD schematic manipulation
- `sexpdata` — S-expression parsing (used by pin_locator, dynamic_symbol_loader)
- `pcbnew` — KiCAD's SWIG Python API (board operations, must be on PYTHONPATH)
- `Pillow` — Image processing for board rendering
- `cairosvg` — SVG rendering
- `pydantic` — Data validation

## Build & Run

```bash
# Install dependencies
npm install
pip install -r requirements.txt        # production
pip install -r requirements-dev.txt    # development (includes testing/linting)

# Build TypeScript
npm run build          # compile once
npm run build:watch    # watch mode

# Run the MCP server
npm start              # or: node dist/index.js

# Clean & rebuild
npm run rebuild
```

## Testing

```bash
# All tests
npm test               # runs both TS and Python tests

# Python tests only
pytest tests/ -v
pytest python/tests/ -v

# With coverage
pytest tests/ --cov=python --cov-report=html --cov-report=term

# Markers
pytest -m unit         # fast, no KiCAD needed
pytest -m integration  # requires KiCAD installed
```

Test paths: `tests/` (top-level) and `python/tests/`. Config in `pytest.ini`.

**Test coverage is minimal** — only 4 test files exist. None of the 65+ handlers in `kicad_interface.py` have tests. No tests for `sexp_writer.py`, `pin_locator.py`, `dynamic_symbol_loader.py`, or batch operations.

## Linting & Formatting

```bash
# Python
npm run format:py                # format with black (mutates files)
npm run lint:py                  # lint check (black --check + mypy + flake8, read-only)
mypy python/                     # type check
flake8 python/                   # lint
isort python/                    # import sorting

# TypeScript
npm run lint:ts                  # ESLint (if configured)
npx prettier --write 'src/**/*.ts'

# All
npm run format                   # prettier + black
npm run lint                     # eslint + black --check + mypy + flake8
```

Note: `npm run lint:py` uses `black --check` (read-only). Use `npm run format:py` to actually format files.

## Rules

- **ALWAYS rebuild after every change**: Run `npm run build` after any edit to TypeScript files. The MCP server runs from `dist/`, not `src/`. Forgetting to rebuild means your changes won't take effect.
- **ALWAYS commit and push after every change**: After fixing a bug or adding a feature, commit and push to `remix` remote immediately. Don't batch changes.
- **ALWAYS flush writes to disk**: Every file write to `.kicad_sch` or `.kicad_pcb` must use `f.flush()` + `os.fsync(f.fileno())` inside the `with open(...)` block. The MCP client reads the file immediately after the tool call returns — unflushed data causes stale reads.
- **ALWAYS quote UUIDs**: KiCad 9 requires UUIDs to be quoted: `(uuid "04a291d4-...")`. Unquoted UUIDs cause `kicad-cli` to reject the file. All `sexp_writer.py` functions use quoted UUIDs. When adding new s-expression generators, use `f'(uuid "{my_uuid}")'`.
- **Tool name must match across layers**: The `callKicadScript("command_name", ...)` string in TypeScript **must exactly match** the key in the `command_routes` dict in `python/kicad_interface.py`. A mismatch causes "unknown command" errors.
- **Every tool needs `schematicPath` or `pcbPath`**: All schematic/board tools must include the file path parameter in both the Zod schema (TypeScript) and the Python handler. The Python backend is stateless per-call for schematics.
- **Never use `sexpdata` round-trips for writing**: `sexpdata.loads()` → modify → `sexpdata.dumps()` collapses the entire `.kicad_sch` file to a single line, breaking git diffs and other parsers. Use text insertion via `python/commands/sexp_writer.py` instead.
- **Handle single-line .kicad_sch files**: Some schematic files may already be single-line (from prior sexpdata corruption). All regex parsers must work without `^` line-start anchoring. Use `\(label\b` not `^  \(label`.
- **No stale caches for schematic state**: Never cache loaded `Schematic` objects across operations. The file changes between calls. Pin definition caches (lib_symbols → pin data) are OK since symbol definitions don't change mid-session.
- **List/query tools must be fast**: Tools like `list_schematic_components` and `list_schematic_nets` must not call per-item functions that re-read the file. Load once, iterate in memory.
- **Parameter format normalization**: Python handlers should accept both `{x, y}` objects and `[x, y]` arrays for coordinates, since TypeScript sends objects but some internal callers use arrays.
- **Snap component positions to 1.27mm grid**: All component placements must snap to the KiCad schematic grid (1.27mm). Off-grid components = off-grid pins = broken connections. `DynamicSymbolLoader.create_component_instance` does this automatically.
- **Verify with kicad-cli, not MCP tools**: MCP's own diagnostics (get_pin_connections, etc.) use the same math as the tools that placed the components. Always verify with `kicad-cli sch erc` via Bash as the ground truth.
- **Batch operations must use single read/write cycle**: Use `_to_content` / `_from_content` variants from `sexp_writer.py` (e.g., `add_wire_to_content`, `delete_wire_from_content`) or static `_*_in_content` methods on `KiCADInterface` (e.g., `_edit_component_in_content`, `_delete_component_from_content`). Read the file once, loop over the content variants, write once. All batch handlers except `batch_connect_to_net` now follow this pattern.

## KiCad S-Expression Gotchas

These are hard-won lessons from debugging. Read before touching any schematic file manipulation code.

### Pin coordinate system
- Symbol-local pin definitions use **Y-up** coordinates. Schematic uses **Y-down**.
- **Always negate Y** when converting pin (at) to schematic coords: `pin_rel_y = -pin_data["y"]`
- **Always apply mirror transforms** after Y-negation, before rotation: `if mirror_x: pin_rel_y = -pin_rel_y` / `if mirror_y: pin_rel_x = -pin_rel_x`. Mirror handling was missing from `PinLocator` until recently — if you see wrong pin positions on mirrored symbols, check this first.
- **Rotation uses KiCad schematic transform, NOT standard CCW rotation.** After Y-negation and mirror, apply:
  ```python
  rot_x =  pin_rel_x * cos_a - pin_rel_y * sin_a   # same as standard
  rot_y = -pin_rel_x * sin_a + pin_rel_y * cos_a   # NOTE: minus sign on sin term
  ```
  The standard rotation formula (`rot_y = x*sin + y*cos`) gives WRONG pin positions at 90°/270° rotation because Y-negation and rotation don't commute. The correct transform is `F · R(θ)` (rotate in Y-up space first, then Y-flip), which produces the matrix `[[cos, -sin], [-sin, cos]]` when applied to Y-negated coordinates. `PinLocator.rotate_point()` implements this correctly.
- The `(at x y angle)` in a pin definition IS the **connectable endpoint**. The `length` extends from endpoint toward the body, NOT outward. **Do not add length to get the endpoint.**
- Pin angles in definitions point FROM endpoint TOWARD body. For wire stubs going AWAY from body, use `(angle + 180 + symbol_rotation) % 360`. For mirrored symbols, apply mirror to the pin angle before adding symbol rotation.

### Duplicated pin math (known tech debt)
Pin position calculation (Y-negate, mirror, KiCad transform) is duplicated in **7 places** inside `kicad_interface.py` plus 2 in `pin_locator.py` and 1 in `connection_schematic.py`. **All 10 sites now use the correct KiCad schematic transform** (`rot_y = -x*sin + y*cos`, not standard rotation). Sites 1-2 and 4-9 use `PinLocator.rotate_point()`; sites 3 and 10 have inline formulas. The sites:
1. `pin_locator.py:get_pin_location()` — the canonical implementation
2. `pin_locator.py:get_all_symbol_pins()` — inline for performance
3. `kicad_interface.py:_handle_list_schematic_components()` — inline
4. `kicad_interface.py:_handle_batch_get_schematic_pin_locations()` — inline
5. `kicad_interface.py:_handle_get_net_connectivity()` and `_handle_validate_wire_connections()` — inline
6. `kicad_interface.py:_parse_schematic_geometry()` — shared by `check_schematic_overlaps` and `get_schematic_layout`
7. `kicad_interface.py:_handle_find_orphan_items()` — pin endpoints for dangling wire detection
8. `kicad_interface.py:_handle_get_pin_connections()` — inline
9. `connection_schematic.py:ConnectionManager.get_pin_location()` — now delegates to PinLocator or applies full transforms

**When fixing pin math, grep for `pin_rel_y = -` to find ALL sites.** A fix in one place that misses the others will cause tools to disagree about pin positions.

### Global label format
KiCad global labels have a `(shape ...)` attribute between the name and `(at ...)`:
```
(global_label "SDA" (shape bidirectional) (at 100 50 0) ...)
```
**Every regex that matches labels must include `(?:\s+\(shape\s+[^)]*\))?` after the label name.** This is the #1 recurring bug — it was found and fixed in 7+ separate handlers. When adding new label-matching code, always use this pattern:
```python
rf'\({label_type}\s+"([^"]*)"(?:\s+\(shape\s+[^)]*\))?\s+\(at\s+([\d.e+-]+)\s+([\d.e+-]+)'
```
And always iterate `["label", "global_label", "hierarchical_label"]`, not just `["label", "global_label"]`.

### (instances) blocks
- KiCad 9 requires `(instances (project "name" (path "/uuid" (reference "R1") (unit 1))))` inside every placed symbol for annotation to work.
- `DynamicSymbolLoader.create_component_instance` already includes this in the template.
- Never add a second one. When checking if a symbol already has `(instances)`, use balanced-paren search to find the symbol block, not newline-based heuristics (single-line files have no newlines).

### (hide yes) placement
- Field visibility: `(hide yes)` goes inside `(effects ...)`, NOT inside `(font ...)`.
- Correct: `(effects (font (size 1.27 1.27)) (hide yes))`
- Wrong: `(effects (font (size 1.27 1.27) (hide yes)))` — malformed, kicad-cli rejects it.
- When toggling visibility, **always strip ALL existing (hide yes) first** (from both effects and font levels), then add one at the effects level if hiding.

### Wire connectivity
- KiCad wires must be strictly horizontal or vertical. Diagonal wires don't form electrical connections.
- Wire endpoints must exactly match label/pin positions for connectivity. Off-grid mismatches = dangling.
- When creating wire stubs from pins, snap the stub endpoint to grid **only along the pin's axis** (vertical pins snap Y only, horizontal pins snap X only).
- **T-junction auto-fix**: `sexp_writer.add_wire()` and `add_polyline_wire()` now **automatically detect T-junctions** (new wire endpoint on mid-segment of existing wire) and **add junction dots**. `batch_add_wire` also does this after all wires are placed. This prevents the invisible connectivity gap that caused "pin not connected" failures in kicad-cli ERC.
- **T-junction detection in analysis tools**: Wire tracing tools (`validate_wire_connections`, `get_net_connectivity`, `get_pin_connections`, `find_orphan_items`) detect T-junctions via `_point_on_wire_segment()` and `_find_connected_wires()` module-level helpers. The union-find graph in `net_analysis.py` uses spatial-indexed T-junction detection for O(1) per-point checks.
- T-junction connections can also be made explicit using `split_wire_at_point` (splits one wire into two at the intersection) or `add_junction` / `batch_add_junction` (adds junction dots).
- **`fix_connectivity` tool**: Runs kicad-cli ERC as ground truth, parses JSON violations, auto-fixes T-junctions that need junction dots, and reports what remains. Use as the final verification step — it uses kicad-cli's own connectivity engine, not MCP's.
- Use `trace_from_point` to debug connectivity — traces all reachable elements from any (x,y) coordinate, showing the exact path and dead ends.

### Power symbols
- Power symbols (#PWR) use `lib_id "power:GND"` etc. They're symbols, not labels.
- `get_net_connections` must search power symbols in addition to labels.
- `get_pin_connections` must detect power symbol pins at wire endpoints.
- Power symbol references must be auto-numbered (#PWR068, not #PWR?) to avoid collisions.
- Their Reference field should be hidden by default (`(hide yes)` in effects).

### Label bounding box geometry
- The label `(at x y angle)` position is the **arrow tip / top-left of rendered shape**.
- The flag body (text + shape) **always extends in the positive screen direction** from `(at)`:
  - `0°/180° (horizontal)`: body extends **RIGHT** (+x) from `(at)`
  - `90°/270° (vertical)`: body extends **DOWN** (+y) from `(at)`
- **Do NOT use trig** (`cos`/`sin`) for label bounding boxes. The direction is always the same regardless of angle. Use a simple axis-aligned model:
  ```python
  if norm_angle in (0, 180):
      x1, x2 = lx, lx + total_w        # extends right
      y1, y2 = ly - total_h/2, ly + total_h/2  # centered vertically
  else:  # 90, 270
      x1, x2 = lx - total_h/2, lx + total_h/2  # centered horizontally
      y1, y2 = ly, ly + total_w         # extends down
  ```
- **Connection point** depends on angle — this is NOT always the `(at)` position:
  - `0°` → right end: `(at.x + width, at.y)`
  - `180°` → left end: `(at.x, at.y)` (same as `at`)
  - `90°` → bottom: `(at.x, at.y + width)`
  - `270°` → top: `(at.x, at.y)` (same as `at`)
- Labels connect to component pins via **short wire stubs** (typically 2.54mm). The label's `(at)` position is NOT at the pin — it's one stub length away. `check_schematic_overlaps` uses `suppressPinLabels` (default: true) to filter out standard pin-endpoint labels.

### Label justify property
- Global/hierarchical labels have a `(justify left|right)` in their `(effects ...)` block that controls the visual flag direction.
- **Both angle AND justify must be set correctly** for the label to render properly:
  - `0°` / `90°` → `(justify left)`
  - `180°` / `270°` → `(justify right)`
- **The Intersheetrefs property** position must also match: it sits at the far end of the flag, which flips when justify changes. For `justify right` (180°): `isr_x = at.x - flag_width`.
- `rotate_schematic_label` now handles all three (angle, justify, Intersheetrefs position).
- `sexp_writer.add_label` sets correct justify on creation based on orientation.

### String replacement in loops
- **Never modify a string inside a `finditer` loop on that string.** After the first replacement changes string length, all subsequent match positions are wrong. Collect all `(start, end, new_text)` edits first, then apply in reverse order.

## Validation Checklist for New Tools

When adding or modifying a schematic tool, verify:

1. [ ] `callKicadScript` command name matches `command_routes` key exactly
2. [ ] TypeScript schema includes `schematicPath` as required parameter
3. [ ] Python handler accepts both `{x,y}` objects and `[x,y]` arrays for coordinates
4. [ ] Any label regex includes `(?:\s+\(shape\s+[^)]*\))?` for global labels
5. [ ] Label iteration covers all three types: `label`, `global_label`, `hierarchical_label`
6. [ ] Pin Y coordinate is negated when converting from symbol-local to schematic coords
7. [ ] Pin mirror transforms are applied (mirror_x → negate Y, mirror_y → negate X)
7b. [ ] Pin rotation uses KiCad transform (`rot_y = -x*sin + y*cos`), NOT standard rotation (`rot_y = x*sin + y*cos`)
7c. [ ] Generated UUIDs are quoted: `(uuid "xxx")` not `(uuid xxx)`
8. [ ] File writes use `sexp_writer.py` text insertion, not `sexpdata.dumps()`
9. [ ] File writes include `f.flush()` + `os.fsync(f.fileno())`
10. [ ] No line-start-anchored regex (`^`) — files may be single-line
11. [ ] No string modification inside `finditer` loops
12. [ ] Label rotation tools update justify (0°/90° → left, 180°/270° → right)
13. [ ] Batch handlers use `_to_content` variants for single read/write cycle
14. [ ] Wire tracing includes T-junction detection via `_point_on_wire_segment()` (both forward and reverse checks)
15. [ ] Wire placement tools auto-add junctions at T-junctions (handled by `sexp_writer.add_wire()` / `add_polyline_wire()` / `batch_add_wire`)
16. [ ] `npm run build` run after TypeScript changes
17. [ ] Commit and push to `remix` remote

## Code Patterns

### Adding a new MCP tool
1. **TypeScript** (`src/tools/<domain>.ts`): Register tool with `server.tool(name, description, zodSchema, handler)`. Handler calls `callKicadScript(command, args)`.
2. **Python handler** (`python/kicad_interface.py`): Add `_handle_<command>` method to `KiCADInterface`.
3. **Python dispatch** (`python/kicad_interface.py`): Add `"command_name": self._handle_command_name` to `command_routes` dict (~line 370).
4. **Rebuild**: Run `npm run build`.

The `callKicadScript` command string and the `command_routes` key **must match exactly**.

### Schematic file manipulation
- **Text insertion/deletion** (`python/commands/sexp_writer.py`): Preferred method for adding/removing wires, labels, junctions, no-connects, wire splitting, etc. Inserts formatted text before `(sheet_instances` (falls back to before final `)` if `(sheet_instances` is absent), preserving file formatting. Deletion uses balanced-paren block matching with position tolerance. All writes are flushed to disk with `os.fsync()`. Each function has a `_to_content` / `_from_content` variant (e.g., `add_wire_to_content`, `add_label_to_content`, `delete_no_connect_from_content`, `split_wire_at_point_in_content`) that operates on a string instead of a file — use these in batch handlers to avoid N read/write cycles. **Wire placement auto-adds junction dots at T-junctions** via `auto_add_t_junctions()` — no manual junction management needed.
- **Net analysis** (`python/commands/net_analysis.py`): Union-find based net graph builder. `build_net_graph()` computes complete pin→net mapping in a single O(W+L+P) pass. Used by 7 query tools: `get_component_nets`, `get_net_components`, `get_pin_net_name`, `export_netlist_summary`, `validate_component_connections`, `find_shorted_nets`, `find_single_pin_nets`. The graph detects shorted nets (two named nets accidentally merged) and single-pin nets (broken connections).
- **Connectivity repair** (`fix_connectivity` tool): Runs kicad-cli ERC as ground truth, parses JSON violations, auto-fixes T-junctions by adding junction dots. Use as final verification — kicad-cli's connectivity engine is independent of MCP's pin math.
- **kicad-skip** (`from skip import Schematic`): Used for reading/querying existing schematic elements (symbols, properties, wires). Good for reads, avoid for writes that go through `sexpdata.dumps()`.
- **DynamicSymbolLoader** (`python/commands/dynamic_symbol_loader.py`): Text-based symbol injection from KiCad libraries. Handles `(instances)` blocks, rotation-aware field positions. Uses text manipulation, not sexpdata.
- **PinLocator** (`python/commands/pin_locator.py`): Returns pin **endpoints** (connectable tip), not body positions. Handles rotation (via KiCad schematic transform, not standard rotation) AND mirror transforms. `rotate_point()` applies the Y-down-aware transform `[[cos,-sin],[-sin,cos]]`. `get_all_symbol_pins()` loads the file once and computes all pins inline (no per-pin re-reads). Pin definition cache is per lib_id and safe to keep. A shared `PinLocator` instance lives on `KiCADInterface` as `self.pin_locator` — handlers use this instead of creating fresh instances, preserving the cache across calls.

### Board operations
- Use `pcbnew` SWIG API directly
- Board must be loaded via `pcbnew.LoadBoard(path)`

### Error handling
- Python commands return `{"success": True/False, "message": "...", ...}`
- TypeScript wraps results in MCP content blocks

### Python process lifecycle
- The TypeScript server spawns Python as a child process via `spawnPythonProcess()`
- If the Python process crashes (non-zero exit), it auto-restarts after 1 second, rejects the pending request, and resumes the request queue
- Long-running commands (`run_erc`, `run_drc`, `fix_connectivity`, exports) get a 10-minute timeout instead of the default 30 seconds
- On timeout, the Python process is killed (`SIGTERM`) and auto-restarted to prevent stale output corruption
- On `stop()`, all queued requests are rejected before the Python process is killed

## Environment Variables

- `KICAD_PYTHON` — Override Python executable path
- `KICAD_BACKEND` — Backend selection: `auto` (default), `ipc`, or `swig`
- `KICAD_AUTO_LAUNCH` — Set to `true` to auto-launch KiCAD UI

## Configuration

Config files in `config/`:
- `default-config.json` — Default settings
- `claude-desktop-config.json` — Claude Desktop integration
- Platform-specific examples: `linux-config.example.json`, `windows-config.example.json`, `macos-config.example.json`

## Logs

Both layers log to `~/.kicad-mcp/logs/`:
- TypeScript: `kicad-mcp-YYYY-MM-DD.log`
- Python: `kicad_interface.log`

## Common Pitfalls

These are bugs that were actually encountered and fixed. If you see these symptoms, check the fix is still in place.

- **"Unknown command" error**: `callKicadScript` string in TS doesn't match `command_routes` key in Python.
- **Tool works in code but not via MCP**: Forgot `npm run build`. Server runs from `dist/`.
- **"Python process for KiCAD scripting is not running"**: Python backend crashed. Should auto-restart now (see `spawnPythonProcess()` in `server.ts`). If it persists, check Python logs at `~/.kicad-mcp/logs/kicad_interface.log`.
- **Schematic file becomes single-line**: Used `sexpdata.dumps()`. Use `sexp_writer.py` instead.
- **Pin positions wrong by ~2.5mm or pins swapped**: Forgot to negate Y (`-pin_data["y"]`), or added pin length to endpoint (the `(at)` IS the endpoint already).
- **Pin positions wrong on mirrored symbols**: Mirror transforms not applied. Check `mirror_x`/`mirror_y` handling before rotation.
- **Pin positions reflected (correct offset, wrong sign)**: Symbol-local Y-up vs schematic Y-down. Must negate Y.
- **Wires/labels placed at wrong location**: Pin angle formula wrong. Outward angle = `(pin_def_angle + 180 + symbol_rotation) % 360`.
- **Labels placed but electrically dangling**: Component off-grid (not 1.27mm aligned), or wire stub creates diagonal (must snap along pin axis only).
- **Global labels not found by tools**: Regex missing `(shape ...)` clause. This was the #1 recurring bug — fixed in 7+ places.
- **T-junction wires not connected**: Wire placement tools (`add_wire`, `add_polyline_wire`, `batch_add_wire`) now **auto-add junction dots** at T-junctions. If you still see this, run `fix_connectivity` which uses kicad-cli ERC as ground truth and auto-fixes remaining T-junctions. Manual options: `split_wire_at_point` or `add_junction` / `batch_add_junction`.
- **find_orphan_items reports 100+ false positives**: Was skipping all power symbols (`ref.startswith("#")`) — 124 power symbol pins excluded from connectivity checks. Fixed — now only skips `_TEMPLATE` symbols. Tolerance also reduced from 1.0mm to 0.05mm.
- **run_erc returns 0 violations**: Was parsing `erc_data["violations"]` but KiCad 9 puts them under `sheets[*].violations`. Also needs `--severity-all` flag.
- **run_erc coordinates don't match schematic**: kicad-cli may output coordinates in 1/100mm scale. The handler auto-detects this and scales to mm, but the heuristic (first coord < 5mm) can false-positive on small schematics.
- **run_erc times out**: Was not in the long-running commands list. Now has 10-minute timeout.
- **Duplicate (instances) blocks corrupt file**: The check for existing instances used newline-based heuristics that fail on single-line files. Must use balanced-paren search.
- **#PWR? reference collisions**: Power symbols weren't auto-numbered. Now scans for highest existing #PWR number.
- **get_net_connections empty for power nets**: Was only searching `(label)` elements, not global labels or power symbols. Now searches all label types + power symbols.
- **(hide yes) inside (font) instead of (effects)**: Malformed S-expression that kicad-cli rejects. Must strip all (hide yes) first, then add at effects level only.
- **move_region moves items outside bbox**: String was modified inside `finditer` loop, corrupting match positions. Must collect edits first, apply in reverse order.
- **Diagnostic tools report false results**: MCP tools use the same pin math as placement tools. A pin math bug makes both placement AND verification wrong in the same way — everything looks correct to itself. Always verify with `kicad-cli sch erc` as ground truth.
- **get_schematic_pin_locations timeout on large MCUs**: `get_all_symbol_pins` was re-parsing the file per pin. Fixed — now loads once, computes all pins inline.
- **Batch operations show stale state**: Fixed — all batch handlers except `batch_connect_to_net` now use single read/write cycle via `_to_content` / `_from_content` variants.
- **Schematic changes not visible immediately**: File writes were not flushed to disk. All writes now use `f.flush()` + `os.fsync()`.
- **check_schematic_overlaps reports 20+ false positives for label-component**: Labels at pin endpoints connected by wire stubs are normal. `suppressPinLabels` (default: true) filters these using a 5.5mm distance tolerance. If suppression isn't working, check that pin endpoints are computed correctly (mirror + rotation).
- **Label bounding box extends wrong direction**: Do NOT use trig for label bboxes. The flag body always extends RIGHT (horizontal) or DOWN (vertical) from `(at)`, regardless of angle. Use simple axis-aligned model, not `cos`/`sin`.
- **Label rotated but flag direction unchanged**: `rotate_schematic_label` must update `(justify left/right)` in addition to the angle. 0°/90° → left, 180°/270° → right. Also must reposition the Intersheetrefs property.
- **New global labels missing Intersheetrefs property**: `sexp_writer.add_label` now includes Intersheetrefs for global/hierarchical labels. Without it, KiCad shows no inter-sheet references.
- **Wire-through-label false positives/negatives**: Suppression uses `wire_len <= flag_width * 0.5` threshold. Standard 2.54mm pin stubs are suppressed; longer wires that visibly exit the flag are reported. The old fixed 5mm threshold missed wide labels.
- **Pin positions wrong on mirrored symbols in some tools**: Was missing mirror transforms in 4 of 7 inline pin math sites. Fixed — all 10 pin math sites now include mirror handling. If you see this again, grep for `pin_rel_y = -` and verify all sites have mirror blocks.
- **delete_label_from_content silently fails on global labels**: The regex was missing `(?:\s+\(shape\s+[^)]*\))?`. Fixed.
- **print() in component_schematic.py corrupts MCP protocol**: Was using bare `print()` in CRUD methods. Fixed — now uses `logger.debug()` / `logger.error()`.
- **component_schematic.py CRUD methods find nothing**: Was using `symbol.reference` (nonexistent) instead of `symbol.property.Reference.value`. `remove_component` was using private `_elements` API. Fixed — `remove_component` now uses text-based balanced-paren deletion.
- **PinLocator cache wasted**: Was creating `PinLocator()` fresh per handler call. Fixed — `self.pin_locator` is shared across all handlers.
- **generate_netlist returns empty nets**: Was only scanning `schematic.label`. Fixed — now scans `global_label`, `hierarchical_label`, and power symbols.
- **Prompts return raw {{variable}} placeholders**: Handler functions ignored arguments. Fixed — all 17 prompts now substitute template variables from args.
- **_extract_symbol_block fails on single-line .kicad_sym files**: Was splitting on `"\n"`. Fixed — now uses balanced-paren traversal.
- **_find_insert_position raised ValueError**: No fallback when `(sheet_instances` absent. Fixed — falls back to `content.rfind(")")`.
- **kicad-cli fails with "Failed to load schematic"**: UUIDs were written unquoted `(uuid xxx)` but KiCad 9 requires `(uuid "xxx")`. Fixed in all 13 write sites across `sexp_writer.py`, `schematic.py`, `project.py`, and `kicad_interface.py`.
- **Global labels fail to load even with quoted UUIDs**: `sexp_writer.add_label` was adding a stray `(uuid ...)` inside the Intersheetrefs property block. KiCad properties don't have UUIDs — only the parent label element does. Fixed by removing the UUID from the property block.
- **Pin positions wrong at 90°/270° rotation (Y offset inverted)**: The rotation formula used standard CCW rotation (`rot_y = x*sin + y*cos`) on Y-negated coordinates, but Y-negation and rotation don't commute. The correct formula is `rot_y = -x*sin + y*cos`. At 0°/180° both formulas give the same result (sin=0), so the bug only manifested at 90°/270°. Fixed in `PinLocator.rotate_point()` and all 3 inline sites.

## Important Notes

- **stdout is sacred**: The TypeScript server uses STDIO transport. All logging goes to stderr or files. Never `console.log()` in TS or `print()` in Python (except for JSON responses on the protocol channel).
- **KiCAD 9+ required**: The server targets KiCAD 9.0+ (schema version 20250114).
- **Cross-platform**: Supports Linux, Windows, macOS. Platform detection in `python/utils/platform_helper.py`.

## Known Technical Debt

These are known issues that haven't been fixed yet. Keep them in mind when working on the codebase.

- **`kicad_interface.py` is a 7000+ line god file**: 75+ handler methods plus static helpers and module-level T-junction helpers. Should be decomposed into domain-specific handler modules (schematic_analysis.py, schematic_crud.py, etc.), but all inline pin math sites (10 places) must stay in sync until then.
- **No TypeScript tests**: Zero tests for tool registration, request queue, JSON parsing, or Python subprocess communication.
- **Minimal Python tests**: Only 4 test files. No tests for the vast majority of handlers, sexp_writer content variants, pin_locator transforms, or batch operations. Pin math is the #1 bug source and has zero test coverage.
- **Wire connectivity tracing is O(W × P) per iteration**: `get_net_connectivity` and `validate_wire_connections` still use naive flood-fill (legacy). The newer `net_analysis.py:build_net_graph()` uses union-find O(W+L+P) — prefer it for new tools. Legacy handlers haven't been migrated yet.
- **`connect_to_net` doesn't auto-add T-junctions**: Unlike `add_wire`/`add_polyline_wire`/`batch_add_wire`, `connect_to_net` delegates to `ConnectionManager` which does 2 separate file read/write cycles (wire + label). T-junction auto-detection was added to the sexp_writer file-level functions but `connect_to_net` bypasses them via separate calls. Needs refactoring to batch operations.
- **ERC coordinate auto-detection heuristic is fragile**: Checks if first coord < 5mm to decide scaling. Can false-positive on schematics with violations near origin.
- **`batch_connect_to_net` still does N read/write cycles**: Each connection needs fresh pin positions after prior wire/label placements shift content offsets. The other 7 batch handlers have been fixed.
- **Label bounding box dimensions are estimated**: Uses `0.75mm/char` width and `1.8mm` height based on default KiCad font. Different font sizes or non-ASCII characters will have inaccurate bounding boxes.
- **`get_schematic_layout` shares geometry code with `check_schematic_overlaps`**: Both use `_parse_schematic_geometry()`, but the overlap logic in `get_schematic_layout` is a partial copy. Changes to overlap detection must be applied in both places.
- **11 MCP tools are disabled (no Python handler)**: `export_netlist`, `export_position_file`, `export_vrml`, `add_net_class`, `assign_net_to_class`, `set_layer_constraints`, `check_clearance`, `add_zone`, `add_component_annotation`, `group_components`, `replace_component`. Their TS registrations are commented out with TODO markers. Re-enable when Python handlers are implemented.
- **`router.ts` and `registry.ts` are dead code**: The router pattern was disabled due to hallucinations. ~600 lines compiled but never executed. The imports are commented out in `server.ts`.
- **Synchronous logger**: `logger.ts` uses `appendFileSync` and `existsSync` on every log message, blocking the Node.js event loop. Should use async write stream.
- **`wire_manager.py` is a zero-value wrapper**: Every method forwards to `sexp_writer` with no added logic. Could be eliminated.
- **Duplicated utilities across modules**: `_get_project_name` (in sexp_writer.py and dynamic_symbol_loader.py), `_fmt` coordinate formatter (3 slightly different implementations), mirror attribute parser (5+ locations). Should be extracted to shared utils.
