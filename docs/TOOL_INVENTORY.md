# KiCAD MCP Server - Complete Tool Inventory

**Version:** 2.1.0-alpha
**Total Tools:** 137 (verifiziert via VS Code MCP Discovery Log)
**Last Updated:** 2026-05-02

## How Tools Are Organized

Tools are registered directly via `server.tool()`

The `Access` column below uses legacy labels from when a router pattern was planned:

- **Direct** — High-frequency tools, originally intended as always-visible
- **Routed** — Originally planned for router dispatch; now also registered directly
- **Additional** — Registered directly (always visible)

---

## Project Management (5 tools)

_Source: `src/tools/project.ts`_

| Tool               | Description                                                      | Access |
| ------------------ | ---------------------------------------------------------------- | ------ |
| `create_project`   | Create a new KiCAD project (.kicad_pro, .kicad_pcb, .kicad_sch)  | Direct |
| `open_project`     | Open an existing KiCAD project                                   | Direct |
| `save_project`     | Save the current project                                         | Direct |
| `get_project_info` | Get project metadata and information                             | Direct |
| `snapshot_project` | Save a named checkpoint snapshot (renders PDF, saves step label) | Direct |

---

## Board Management (12 tools)

_Source: `src/tools/board.ts`_

| Tool                | Description                                                       | Access         |
| ------------------- | ----------------------------------------------------------------- | -------------- |
| `set_board_size`    | Set PCB dimensions (width, height, unit)                          | Direct         |
| `add_board_outline` | Add board outline (rectangle, circle, polygon, rounded_rectangle) | Direct         |
| `get_board_info`    | Get board metadata and properties                                 | Direct         |
| `add_layer`         | Add copper/technical/signal layer                                 | Routed (board) |
| `set_active_layer`  | Change the active working layer                                   | Routed (board) |
| `get_layer_list`    | List all layers on the board                                      | Routed (board) |
| `add_mounting_hole` | Add mounting hole with optional pad                               | Routed (board) |
| `add_board_text`    | Add text annotation to board                                      | Routed (board) |
| `add_zone`          | Add copper zone/pour with clearance settings                      | Routed (board) |
| `get_board_extents` | Get bounding box of board                                         | Routed (board) |
| `get_board_2d_view` | Render 2D board view (PNG/JPG/SVG)                                | Routed (board) |
| `import_svg_logo`   | Import SVG file as polygons on silkscreen layer                   | Additional     |

---

## Component Management (16 tools)

_Source: `src/tools/component.ts`_

| Tool                       | Description                                                   | Access             |
| -------------------------- | ------------------------------------------------------------- | ------------------ |
| `place_component`          | Place footprint on PCB (position, rotation, reference, value) | Direct             |
| `move_component`           | Move component to new position                                | Direct             |
| `rotate_component`         | Rotate component (absolute angle)                             | Routed (component) |
| `delete_component`         | Remove component from board                                   | Routed (component) |
| `edit_component`           | Edit component properties (reference, value, footprint)       | Routed (component) |
| `find_component`           | Search components by reference or value                       | Routed (component) |
| `get_component_properties` | Get all properties of a component                             | Routed (component) |
| `add_component_annotation` | Add annotation/comment to component                           | Routed (component) |
| `group_components`         | Group multiple components together                            | Routed (component) |
| `replace_component`        | Replace component with different footprint                    | Routed (component) |
| `get_component_pads`       | Get all pad information for a component                       | Additional         |
| `get_component_list`       | List all components with optional filters                     | Additional         |
| `get_pad_position`         | Get precise position of a specific pad                        | Additional         |
| `place_component_array`    | Place array of components (rows x columns)                    | Additional         |
| `align_components`         | Align components (horizontal, vertical, grid)                 | Additional         |
| `duplicate_component`      | Duplicate component with offset                               | Additional         |

---

## Routing (13 tools)

_Source: `src/tools/routing.ts`_

| Tool                      | Description                                          | Access           |
| ------------------------- | ---------------------------------------------------- | ---------------- |
| `add_net`                 | Create a new net on the PCB                          | Direct           |
| `route_trace`             | Route trace segment between XY points (single layer) | Direct           |
| `add_via`                 | Add via (through/blind/buried)                       | Routed (routing) |
| `add_copper_pour`         | Add copper pour / ground plane                       | Routed (routing) |
| `delete_trace`            | Delete traces by UUID, position, or bulk by net      | Additional       |
| `query_traces`            | Query/filter traces by net, layer, or bounding box   | Additional       |
| `get_nets_list`           | List all nets with statistics                        | Additional       |
| `modify_trace`            | Modify existing trace (width, layer, net)            | Additional       |
| `create_netclass`         | Create net class with design rules                   | Additional       |
| `route_differential_pair` | Route differential pair traces                       | Additional       |
| `refill_zones`            | Refill all copper zones                              | Additional       |
| `route_pad_to_pad`        | Route trace between two pads with auto-via insertion | Additional       |
| `copy_routing_pattern`    | Copy routing from source to target component groups  | Additional       |

---

## Design Rules and DRC (8 tools)

_Source: `src/tools/design-rules.ts`_

| Tool                    | Description                                                 | Access       |
| ----------------------- | ----------------------------------------------------------- | ------------ |
| `set_design_rules`      | Set global design rules (clearance, track width, via sizes) | Routed (drc) |
| `get_design_rules`      | Get current design rules                                    | Routed (drc) |
| `run_drc`               | Run design rule check                                       | Routed (drc) |
| `add_net_class`         | Add net class with custom rules                             | Routed (drc) |
| `assign_net_to_class`   | Assign net to a net class                                   | Routed (drc) |
| `set_layer_constraints` | Set layer-specific constraints                              | Routed (drc) |
| `check_clearance`       | Check clearance between two items                           | Routed (drc) |
| `get_drc_violations`    | Get DRC violation list (filter by severity)                 | Routed (drc) |

---

## Export (8 tools)

_Source: `src/tools/export.ts`_

| Tool                   | Description                                       | Access          |
| ---------------------- | ------------------------------------------------- | --------------- |
| `export_gerber`        | Export Gerber files for fabrication               | Routed (export) |
| `export_pdf`           | Export PDF with layer selection and page size     | Routed (export) |
| `export_svg`           | Export SVG vector graphics                        | Routed (export) |
| `export_3d`            | Export 3D model (STEP, STL, VRML, OBJ)            | Routed (export) |
| `export_bom`           | Export Bill of Materials (CSV, XML, HTML, JSON)   | Routed (export) |
| `export_netlist`       | Export netlist (KiCad, Spice, Cadstar, OrcadPCB2) | Routed (export) |
| `export_position_file` | Export component position file for pick and place | Routed (export) |
| `export_vrml`          | Export VRML 3D model                              | Routed (export) |

---

## Schematic (43 tools)

_Source: `src/tools/schematic.ts`_

### Component Operations (10)

| Tool                                  | Description                                                                                                        | Access             |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | ------------------ |
| `add_schematic_component`             | Add component to schematic (symbol from library)                                                                   | Direct             |
| `delete_schematic_component`          | Remove component from schematic                                                                                    | Additional         |
| `edit_schematic_component`            | Edit footprint, value, reference, label positions, and arbitrary custom properties (MPN, Manufacturer, DigiKey, …) | Additional         |
| `set_schematic_component_property`    | Add or update a single custom property (BOM/sourcing field) on a component                                         | Additional         |
| `remove_schematic_component_property` | Delete a single custom property from a component                                                                   | Additional         |
| `get_schematic_component`             | Get component info: built-in fields + all custom properties + label positions                                      | Additional         |
| `list_schematic_components`           | List all components in schematic                                                                                   | Direct             |
| `move_schematic_component`            | Move component to new position                                                                                     | Routed (schematic) |
| `rotate_schematic_component`          | Rotate component                                                                                                   | Routed (schematic) |
| `annotate_schematic`                  | Auto-annotate reference designators                                                                                | Direct             |

### Wiring and Connections (10)

| Tool                          | Description                                          | Access             |
| ----------------------------- | ---------------------------------------------------- | ------------------ |
| `add_schematic_wire`          | Add wire segment between two points                  | Routed (schematic) |
| `delete_schematic_wire`       | Delete wire segment                                  | Routed (schematic) |
| `add_schematic_net_label`     | Add net label to schematic                           | Direct             |
| `delete_schematic_net_label`  | Delete net label                                     | Routed (schematic) |
| `add_no_connect`              | Add no-connect flag (X marker) to an unconnected pin | Direct             |
| `move_schematic_net_label`    | Move net label to new position                       | Routed (schematic) |
| `connect_to_net`              | Connect component pin to named net                   | Direct             |
| `connect_passthrough`         | Connect all matching pins between two connectors     | Direct             |
| `get_schematic_pin_locations` | Get pin locations for a component                    | Additional         |
| `get_wire_connections`        | Get all connections at a wire endpoint               | Additional         |

### Hierarchical Schematics (2)

| Tool                               | Description                                        | Access             |
| ---------------------------------- | -------------------------------------------------- | ------------------ |
| `add_schematic_hierarchical_label` | Add hierarchical label for multi-sheet connections | Routed (schematic) |
| `add_sheet_pin`                    | Add a sheet pin to a hierarchical sheet symbol     | Routed (schematic) |

### Net Analysis (5)

| Tool                    | Description                          | Access             |
| ----------------------- | ------------------------------------ | ------------------ |
| `get_net_connections`   | Get all connections for a net        | Routed (schematic) |
| `get_net_at_point`      | Get the net name at an XY coordinate | Additional         |
| `list_schematic_nets`   | List all nets in schematic           | Routed (schematic) |
| `list_schematic_wires`  | List all wires in schematic          | Routed (schematic) |
| `list_schematic_labels` | List all net labels                  | Routed (schematic) |

### Text Annotations (2)

| Tool                   | Description                                      | Access             |
| ---------------------- | ------------------------------------------------ | ------------------ |
| `add_schematic_text`   | Add free-form text annotation to schematic       | Routed (schematic) |
| `list_schematic_texts` | List all text annotations (with optional filter) | Routed (schematic) |

### Visual / Geometry Helpers (8)

| Tool                          | Description                                               | Access             |
| ----------------------------- | --------------------------------------------------------- | ------------------ |
| `get_schematic_view`          | Render schematic as image (PNG/SVG)                       | Routed (schematic) |
| `get_schematic_view_region`   | Render a specific region of the schematic as image        | Additional         |
| `find_overlapping_elements`   | Find schematic elements that visually overlap             | Additional         |
| `get_elements_in_region`      | Get all elements inside an XY bounding box                | Additional         |
| `find_wires_crossing_symbols` | Find wires that cross through symbol bodies (DRC helper)  | Additional         |
| `list_floating_labels`        | List net labels not connected to any wire                 | Additional         |
| `find_orphaned_wires`         | Find wire segments not connected at one or both ends      | Additional         |
| `snap_to_grid`                | Snap an XY coordinate to the nearest schematic grid point | Additional         |

### Schematic Creation and Export (3)

| Tool                   | Description                 | Access             |
| ---------------------- | --------------------------- | ------------------ |
| `create_schematic`     | Create a new schematic file | Routed (schematic) |
| `export_schematic_svg` | Export schematic to SVG     | Routed (schematic) |
| `export_schematic_pdf` | Export schematic to PDF     | Routed (schematic) |

### Validation and Synchronization (3)

| Tool                      | Description                                           | Access             |
| ------------------------- | ----------------------------------------------------- | ------------------ |
| `run_erc`                 | Run electrical rule check                             | Additional         |
| `generate_netlist`        | Generate netlist from schematic                       | Routed (schematic) |
| `sync_schematic_to_board` | Sync schematic components/nets to PCB (F8 equivalent) | Direct             |

---

## Footprint Libraries (4 tools)

_Source: `src/tools/library.ts`_

| Tool                      | Description                           | Access           |
| ------------------------- | ------------------------------------- | ---------------- |
| `list_libraries`          | List all footprint libraries          | Routed (library) |
| `search_footprints`       | Search footprints across libraries    | Routed (library) |
| `list_library_footprints` | List footprints in a specific library | Routed (library) |
| `get_footprint_info`      | Get detailed footprint information    | Routed (library) |

---

## Symbol Libraries (4 tools)

_Source: `src/tools/library-symbol.ts`_

| Tool                    | Description                                     | Access     |
| ----------------------- | ----------------------------------------------- | ---------- |
| `list_symbol_libraries` | List all symbol libraries from sym-lib-table    | Additional |
| `search_symbols`        | Search symbols by name, LCSC ID, or description | Additional |
| `list_library_symbols`  | List symbols in a specific library              | Additional |
| `get_symbol_info`       | Get detailed symbol information                 | Additional |

---

## Footprint Creator (4 tools)

_Source: `src/tools/footprint.ts`_

| Tool                         | Description                                                              | Access     |
| ---------------------------- | ------------------------------------------------------------------------ | ---------- |
| `create_footprint`           | Create custom .kicad_mod footprint (SMD/THT pads, courtyard, silkscreen) | Additional |
| `edit_footprint_pad`         | Edit pad in existing footprint (size, position, drill, shape)            | Additional |
| `register_footprint_library` | Register .pretty library in fp-lib-table                                 | Additional |
| `list_footprint_libraries`   | List available .pretty libraries                                         | Additional |

---

## Symbol Creator (4 tools)

_Source: `src/tools/symbol-creator.ts`_

| Tool                      | Description                                                   | Access     |
| ------------------------- | ------------------------------------------------------------- | ---------- |
| `create_symbol`           | Create custom .kicad_sym symbol (pins, rectangles, polylines) | Additional |
| `delete_symbol`           | Remove symbol from library                                    | Additional |
| `list_symbols_in_library` | List all symbols in a .kicad_sym file                         | Additional |
| `register_symbol_library` | Register library in sym-lib-table                             | Additional |

---

## Datasheet Tools (2 tools)

_Source: `src/tools/datasheet.ts`_

| Tool                | Description                                         | Access     |
| ------------------- | --------------------------------------------------- | ---------- |
| `enrich_datasheets` | Fill missing datasheet URLs using LCSC part numbers | Additional |
| `get_datasheet_url` | Get LCSC datasheet URL for a component              | Additional |

---

## JLCPCB Integration (5 tools)

_Source: `src/tools/jlcpcb-api.ts`_

| Tool                          | Description                                             | Access     |
| ----------------------------- | ------------------------------------------------------- | ---------- |
| `download_jlcpcb_database`    | Download 2.5M+ parts catalog to local SQLite database   | Additional |
| `search_jlcpcb_parts`         | Search parts by specs (category, package, library type) | Additional |
| `get_jlcpcb_part`             | Get detailed part info with pricing                     | Additional |
| `get_jlcpcb_database_stats`   | Get database statistics                                 | Additional |
| `suggest_jlcpcb_alternatives` | Find cheaper or in-stock alternatives                   | Additional |

---

## Freerouting Autorouter (4 tools)

_Source: `src/tools/freerouting.ts`_

| Tool                | Description                                                | Access             |
| ------------------- | ---------------------------------------------------------- | ------------------ |
| `autoroute`         | Run Freerouting autorouter (export DSN, route, import SES) | Routed (autoroute) |
| `export_dsn`        | Export Specctra DSN file for manual routing                | Routed (autoroute) |
| `import_ses`        | Import routed SES file back into PCB                       | Routed (autoroute) |
| `check_freerouting` | Check Java and Freerouting JAR availability                | Routed (autoroute) |

---

## UI Management (2 tools)

_Source: `src/tools/ui.ts`_

| Tool              | Description                               | Access         |
| ----------------- | ----------------------------------------- | -------------- |
| `check_kicad_ui`  | Check if KiCAD UI is running              | Direct         |
| `launch_kicad_ui` | Launch KiCAD UI (optionally with project) | Routed (board) |

---

## Router / Discovery Tools (3 tools)

_Source: `src/tools/router.ts`_

Registriert via `registerRouterTools()` in `src/server.ts`. Ermöglichen Tool-Discovery durch den LLM.

| Tool                   | Description                          | Access |
| ---------------------- | ------------------------------------ | ------ |
| `list_tool_categories` | Browse all available tool categories | Direct |
| `get_category_tools`   | View tools in a specific category    | Direct |
| `search_tools`         | Find tools by keyword                | Direct |

---

## Summary by Access Type

| Access Type          | Count   | Description                              |
| -------------------- | ------- | ---------------------------------------- |
| Direct               | 21      | Always visible                           |
| Routed               | 72      | Always visible (registered directly)     |
| Additional           | 44      | Always visible, registered directly      |
| Router/Discovery     | 3       | Tool-Discovery (`router.ts`, registered) |
| **Total registered** | **137** | Verifiziert via VS Code MCP Discovery    |

## Summary by Category

| Category             | Tool Count |
| -------------------- | ---------- |
| Project Management   | 5          |
| Board Management     | 12         |
| Component Management | 16         |
| Routing              | 13         |
| Design Rules / DRC   | 8          |
| Export               | 8          |
| Schematic            | 43         |
| Footprint Libraries  | 4          |
| Symbol Libraries     | 4          |
| Footprint Creator    | 4          |
| Symbol Creator       | 4          |
| Datasheet            | 2          |
| JLCPCB Integration   | 5          |
| Freerouting          | 4          |
| UI Management        | 2          |
| Router / Discovery   | 3          |
| **Total registered** | **137**    |

> **Verified:** VS Code MCP Discovery Log meldet **137** registrierte Tools.

## Token Impact

Alle 137 registrierten Tools sind stets für den LLM sichtbar. Die Discovery-Tools in `router.ts` ermöglichen dem Modell, Tools nach Kategorie oder Stichwort zu durchsuchen.
