# Schematic Tools Reference

Added in: v2.1.0, expanded in v2.2.0-v2.2.3
Contributors: @Mehanik (PRs #60, #66), @Kletternaut (PR #57)

This document provides a complete reference for the 29 schematic tools in the KiCAD MCP Server. These tools enable a complete schematic design workflow, from creating projects and adding components to wiring, validation, BOM/sourcing metadata, and synchronization with PCB boards. The dynamic symbol loading feature provides access to approximately 10,000 standard KiCad symbols.

## Component Operations (10 tools)

### add_schematic_component

Add a component to the schematic. Symbol format is 'Library:SymbolName' (e.g., 'Device:R', 'EDA-MCP:ESP32-C3').

| Parameter     | Type   | Required | Description                                                      |
| ------------- | ------ | -------- | ---------------------------------------------------------------- |
| schematicPath | string | Yes      | Path to the schematic file                                       |
| symbol        | string | Yes      | Symbol library:name reference (e.g., Device:R, EDA-MCP:ESP32-C3) |
| reference     | string | Yes      | Component reference (e.g., R1, U1)                               |
| value         | string | No       | Component value                                                  |
| footprint     | string | No       | KiCAD footprint (e.g. Resistor_SMD:R_0603_1608Metric)            |
| position      | object | No       | Position on schematic with x and y coordinates                   |

**Usage Notes:** The dynamic symbol loader provides access to ~10,000 KiCad standard symbols. If a symbol is not in the static template map, it will be loaded dynamically from the specified library.

### delete_schematic_component

Remove a placed symbol from a KiCAD schematic (.kicad_sch). This removes the symbol instance (the placed component) from the schematic. It does NOT remove the symbol definition from lib_symbols. Note: This tool operates on schematic files (.kicad_sch). To remove a footprint from a PCB, use delete_component instead.

| Parameter     | Type   | Required | Description                                                   |
| ------------- | ------ | -------- | ------------------------------------------------------------- |
| schematicPath | string | Yes      | Path to the .kicad_sch file                                   |
| reference     | string | Yes      | Reference designator of the component to remove (e.g. R1, U3) |

### edit_schematic_component

Update properties of a placed symbol in a KiCAD schematic (.kicad_sch) in-place.

Use this tool to:

- assign or update the footprint, value, or reference designator,
- reposition field labels (Reference / Value text),
- add, update, or remove **arbitrary custom properties** used by BOM and sourcing
  workflows (`MPN`, `Manufacturer`, `Manufacturer_PN`, `Distributor`, `DigiKey`,
  `DigiKey_PN`, `Mouser_PN`, `LCSC`, `JLCPCB_PN`, `Voltage`, `Tolerance`, `Power`,
  `Dielectric`, `Temperature_Coefficient`, …).

Custom properties are first-class — they survive ERC, are exported by
`export_bom`, and are picked up by the JLCPCB / Digi-Key sourcing tooling. Newly
created properties default to hidden so they do not clutter the schematic canvas.

Multiple updates can be batched in a single call: pass any combination of
`footprint`, `value`, `newReference`, `fieldPositions`, `properties`, and
`removeProperties` together. This is more efficient than delete + re-add because
it preserves the component's position and UUID. Operates on .kicad_sch files
only — to modify a PCB footprint use `edit_component` instead.

| Parameter        | Type     | Required | Description                                                                                                                                                                                                                                                      |
| ---------------- | -------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| schematicPath    | string   | Yes      | Path to the .kicad_sch file                                                                                                                                                                                                                                      |
| reference        | string   | Yes      | Current reference designator of the component (e.g. R1, U3)                                                                                                                                                                                                      |
| footprint        | string   | No       | New KiCAD footprint string (e.g. Resistor_SMD:R_0603_1608Metric)                                                                                                                                                                                                 |
| value            | string   | No       | New value string (e.g. 10k, 100nF)                                                                                                                                                                                                                               |
| newReference     | string   | No       | Rename the reference designator (e.g. R1 → R10)                                                                                                                                                                                                                  |
| fieldPositions   | object   | No       | Reposition field labels: map of field name to {x, y, angle} (e.g. {"Reference": {"x": 12.5, "y": 17.0}})                                                                                                                                                         |
| properties       | object   | No       | Add or update component properties. Map of property name to either a string value or `{value, x?, y?, angle?, hide?, fontSize?}`. Built-in fields (Reference/Value/Footprint/Datasheet) can also be set this way but the dedicated parameters above are clearer. |
| removeProperties | string[] | No       | List of custom property names to delete. Built-in fields (Reference, Value, Footprint, Datasheet) cannot be removed (clear them by setting `value` to `""` instead).                                                                                             |

**Example — attach BOM/sourcing data to a 0603 resistor:**

```json
{
  "schematicPath": "/path/to/board.kicad_sch",
  "reference": "R7",
  "value": "10k",
  "footprint": "Resistor_SMD:R_0603_1608Metric",
  "properties": {
    "MPN": "RC0603FR-0710KL",
    "Manufacturer": "Yageo",
    "DigiKey_PN": "311-10.0KHRCT-ND",
    "LCSC": "C25804",
    "Tolerance": "1%",
    "Power": "0.1W"
  }
}
```

### set_schematic_component_property

Add or update a **single** custom property on a placed schematic symbol. Convenience
wrapper around `edit_schematic_component` for the common case of attaching one
BOM / sourcing field at a time. Creates the property if it does not yet exist.

Newly created properties default to hidden — set `hide: false` plus an explicit
`x`/`y` to display the value on the schematic canvas.

| Parameter     | Type    | Required | Description                                                                                          |
| ------------- | ------- | -------- | ---------------------------------------------------------------------------------------------------- |
| schematicPath | string  | Yes      | Path to the .kicad_sch file                                                                          |
| reference     | string  | Yes      | Reference designator of the component (e.g. R1, U3)                                                  |
| name          | string  | Yes      | Property name (e.g. 'MPN', 'Manufacturer', 'DigiKey_PN', 'Voltage', 'Dielectric')                    |
| value         | string  | Yes      | Property value to write (use empty string to clear)                                                  |
| x             | number  | No       | Label X position in mm (default: component X)                                                        |
| y             | number  | No       | Label Y position in mm (default: component Y)                                                        |
| angle         | number  | No       | Label rotation in degrees (default: 0)                                                               |
| hide          | boolean | No       | Hide the property text on the schematic canvas. Defaults to true for newly created custom properties |
| fontSize      | number  | No       | Font size in mm for the label (default: 1.27)                                                        |

### remove_schematic_component_property

Remove a single custom property from a placed schematic symbol. Built-in fields
(Reference, Value, Footprint, Datasheet) cannot be removed — KiCad requires them
on every symbol. To clear a built-in field, use `edit_schematic_component` and
set its value to an empty string.

| Parameter     | Type   | Required | Description                                                               |
| ------------- | ------ | -------- | ------------------------------------------------------------------------- |
| schematicPath | string | Yes      | Path to the .kicad_sch file                                               |
| reference     | string | Yes      | Reference designator of the component (e.g. R1, U3)                       |
| name          | string | Yes      | Custom property name to remove (e.g. 'MPN', 'Distributor_PN', 'OldField') |

### get_schematic_component

Get full component info from a schematic: position, every field's value, and each
field's label position (at x/y/angle). Returns **all** properties — both built-in
fields (Reference, Value, Footprint, Datasheet) and any custom BOM/sourcing
properties present on the symbol (MPN, Manufacturer, DigiKey_PN, LCSC, Voltage,
Tolerance, Dielectric, etc.). Use this before `edit_schematic_component` /
`set_schematic_component_property` to inspect what is currently set, or to plan
a label repositioning.

| Parameter     | Type   | Required | Description                                  |
| ------------- | ------ | -------- | -------------------------------------------- |
| schematicPath | string | Yes      | Path to the .kicad_sch file                  |
| reference     | string | Yes      | Component reference designator (e.g. R1, U1) |

### list_schematic_components

List all components in a schematic with their references, values, positions, and pins. Essential for inspecting what's on the schematic before making edits.

| Parameter              | Type   | Required | Description                                               |
| ---------------------- | ------ | -------- | --------------------------------------------------------- |
| schematicPath          | string | Yes      | Path to the .kicad_sch file                               |
| filter                 | object | No       | Optional filters with libId and/or referencePrefix fields |
| filter.libId           | string | No       | Filter by library ID (e.g., 'Device:R')                   |
| filter.referencePrefix | string | No       | Filter by reference prefix (e.g., 'R', 'C', 'U')          |

### move_schematic_component

Move a placed symbol to a new position in the schematic.

| Parameter     | Type   | Required | Description                           |
| ------------- | ------ | -------- | ------------------------------------- |
| schematicPath | string | Yes      | Path to the .kicad_sch file           |
| reference     | string | Yes      | Reference designator (e.g., R1, U1)   |
| position      | object | Yes      | New position with x and y coordinates |

### rotate_schematic_component

Rotate a placed symbol in the schematic.

| Parameter     | Type   | Required | Description                                 |
| ------------- | ------ | -------- | ------------------------------------------- |
| schematicPath | string | Yes      | Path to the .kicad_sch file                 |
| reference     | string | Yes      | Reference designator (e.g., R1, U1)         |
| angle         | number | Yes      | Rotation angle in degrees (0, 90, 180, 270) |
| mirror        | enum   | No       | Optional mirror axis ("x" or "y")           |

### annotate_schematic

Assign reference designators to unannotated components (R? → R1, R2, ...). Must be called before tools that require known references.

| Parameter     | Type   | Required | Description                 |
| ------------- | ------ | -------- | --------------------------- |
| schematicPath | string | Yes      | Path to the .kicad_sch file |

## Wiring and Connections (8 tools)

### add_wire

Add a wire connection in the schematic.

| Parameter | Type   | Required | Description                             |
| --------- | ------ | -------- | --------------------------------------- |
| start     | object | Yes      | Start position with x and y coordinates |
| end       | object | Yes      | End position with x and y coordinates   |

### add_schematic_connection

Connect two component pins with a wire. Use this for individual connections between components with different pin roles (e.g. U1.SDA → J3.2). WARNING: Do NOT use this in a loop to wire N passthrough pins — use connect_passthrough instead (single call, cleaner layout, far fewer tokens).

| Parameter     | Type   | Required | Description                              |
| ------------- | ------ | -------- | ---------------------------------------- |
| schematicPath | string | Yes      | Path to the schematic file               |
| sourceRef     | string | Yes      | Source component reference (e.g., R1)    |
| sourcePin     | string | Yes      | Source pin name/number (e.g., 1, 2, GND) |
| targetRef     | string | Yes      | Target component reference (e.g., C1)    |
| targetPin     | string | Yes      | Target pin name/number (e.g., 1, 2, VCC) |

### add_schematic_net_label

Add a net label to the schematic.

**Preferred usage — snap to pin:** supply `componentRef` + `pinNumber` and the label is placed at the exact pin endpoint resolved by `PinLocator`. This guarantees an electrical connection. A 0.01 mm offset is enough to break the connection in KiCad, so this mode eliminates all guesswork.

**Alternative — explicit position:** supply `position [x, y]`. The coordinates must match a pin or wire endpoint exactly; use `get_schematic_pin_locations` first to obtain them.

| Parameter     | Type           | Required | Description                                                            |
| ------------- | -------------- | -------- | ---------------------------------------------------------------------- |
| schematicPath | string         | Yes      | Path to the schematic file                                             |
| netName       | string         | Yes      | Name of the net (e.g., VCC, GND, SIGNAL_1)                             |
| position      | array [x, y]   | No\*     | Explicit position. Required when `componentRef`/`pinNumber` not given. |
| componentRef  | string         | No\*     | Component reference to snap to (e.g. U1). Use with `pinNumber`.        |
| pinNumber     | string\|number | No\*     | Pin number or name (e.g. `"1"`, `"GND"`). Use with `componentRef`.     |
| labelType     | string         | No       | `label` (default), `global_label`, or `hierarchical_label`             |
| orientation   | number         | No       | Rotation angle: 0, 90, 180, 270 (default: 0)                           |

\* Either `position` **or** (`componentRef` + `pinNumber`) is required.

**Response fields:**

| Field           | Description                                                  |
| --------------- | ------------------------------------------------------------ |
| success         | `true` / `false`                                             |
| actual_position | `[x, y]` coordinates where the label was actually placed     |
| snapped_to_pin  | `{component, pin}` — present only when pin-snapping was used |
| message         | Human-readable status                                        |

### connect_to_net

Connect a component pin to a named net by adding a wire stub from the pin endpoint and placing a net label at the stub's far end. The exact pin coordinates are resolved internally via `PinLocator`.

| Parameter     | Type   | Required | Description                        |
| ------------- | ------ | -------- | ---------------------------------- |
| schematicPath | string | Yes      | Path to the schematic file         |
| componentRef  | string | Yes      | Component reference (e.g., U1, R1) |
| pinName       | string | Yes      | Pin name/number to connect         |
| netName       | string | Yes      | Name of the net to connect to      |

**Response fields:**

| Field          | Description                                |
| -------------- | ------------------------------------------ |
| success        | `true` / `false`                           |
| pin_location   | `[x, y]` exact pin endpoint used           |
| label_location | `[x, y]` where the net label was placed    |
| wire_stub      | `[[x1,y1],[x2,y2]]` the wire segment added |
| message        | Human-readable status                      |

**Usage Notes:** Creates a wire stub from the pin and places a net label at the stub endpoint. The stub direction follows the pin's outward angle. Default stub length is 2.54 mm (0.1 inch, standard grid spacing). Check `pin_location` in the response to confirm the correct pin was found; no separate verification call is needed.

### connect_passthrough

Connects all pins of a source connector (e.g. J1) to matching pins of a target connector (e.g. J2) via shared net labels — pin N gets net '{netPrefix}\_{N}'. Use this for FFC/ribbon cable passthrough adapters instead of calling connect_to_net for every pin.

| Parameter     | Type   | Required | Description                                               |
| ------------- | ------ | -------- | --------------------------------------------------------- |
| schematicPath | string | Yes      | Path to the schematic file                                |
| sourceRef     | string | Yes      | Source connector reference (e.g. J1)                      |
| targetRef     | string | Yes      | Target connector reference (e.g. J2)                      |
| netPrefix     | string | No       | Net name prefix, e.g. 'CSI' → CSI_1, CSI_2 (default: PIN) |
| pinOffset     | number | No       | Add to pin number when building net name (default: 0)     |

**Usage Notes:** This is the most efficient way to wire passthrough adapters. For an N-pin connector, this replaces N individual connect_to_net calls with a single operation.

### get_schematic_pin_locations

Returns the exact x/y coordinates of every pin on a schematic component. Useful for inspection or when building custom placement logic. When the goal is to connect a pin to a net, prefer `add_schematic_net_label` with `componentRef`+`pinNumber` (which calls this internally) or `connect_to_net` — both snap to the exact pin endpoint automatically.

| Parameter     | Type   | Required | Description                                      |
| ------------- | ------ | -------- | ------------------------------------------------ |
| schematicPath | string | Yes      | Path to the schematic file                       |
| reference     | string | Yes      | Component reference designator (e.g. U1, R1, J2) |

### delete_schematic_wire

Remove a wire from the schematic by start and end coordinates.

| Parameter     | Type   | Required | Description                                  |
| ------------- | ------ | -------- | -------------------------------------------- |
| schematicPath | string | Yes      | Path to the .kicad_sch file                  |
| start         | object | Yes      | Wire start position with x and y coordinates |
| end           | object | Yes      | Wire end position with x and y coordinates   |

### delete_schematic_net_label

Remove a net label from the schematic.

| Parameter     | Type   | Required | Description                                                                      |
| ------------- | ------ | -------- | -------------------------------------------------------------------------------- |
| schematicPath | string | Yes      | Path to the .kicad_sch file                                                      |
| netName       | string | Yes      | Name of the net label to remove                                                  |
| position      | object | No       | Position to disambiguate if multiple labels with same name (x and y coordinates) |

## Net Analysis (5 tools)

### get_net_connections

Get all connections for a named net.

| Parameter     | Type   | Required | Description                |
| ------------- | ------ | -------- | -------------------------- |
| schematicPath | string | Yes      | Path to the schematic file |
| netName       | string | Yes      | Name of the net to query   |

**Usage Notes:** Uses wire graph analysis to find all component pins connected to the specified net. Returns a list of {component, pin} pairs.

### list_schematic_nets

List all nets in the schematic with their connections.

| Parameter     | Type   | Required | Description                 |
| ------------- | ------ | -------- | --------------------------- |
| schematicPath | string | Yes      | Path to the .kicad_sch file |

### list_schematic_wires

List all wires in the schematic with start/end coordinates.

| Parameter     | Type   | Required | Description                 |
| ------------- | ------ | -------- | --------------------------- |
| schematicPath | string | Yes      | Path to the .kicad_sch file |

### list_schematic_labels

List all net labels, global labels, and power flags in the schematic.

| Parameter     | Type   | Required | Description                 |
| ------------- | ------ | -------- | --------------------------- |
| schematicPath | string | Yes      | Path to the .kicad_sch file |

### get_net_at_point

Return the net name at a given (x, y) coordinate, or `null` if no net label or wire endpoint is present there.

Checks net label / power symbol positions first (exact IU match), then wire endpoints. Faster than `get_wire_connections` when you only need the net name and not full pin traversal.

| Parameter     | Type   | Required | Description                           |
| ------------- | ------ | -------- | ------------------------------------- |
| schematicPath | string | Yes      | Path to the .kicad_sch schematic file |
| x             | number | Yes      | X coordinate in mm                    |
| y             | number | Yes      | Y coordinate in mm                    |

**Response fields:**

| Field    | Description                                                             |
| -------- | ----------------------------------------------------------------------- |
| net_name | Net label string, or `null` if no net found at this point               |
| position | `{"x": float, "y": float}` — echoes the query coordinates               |
| source   | `"net_label"` \| `"wire_endpoint"` \| `null` — how the net was resolved |

## Text Annotations (2 tools)

### add_schematic_text

Add a free-form text annotation (note, heading, documentation string) directly on the schematic canvas. Text annotations have no electrical significance — they are purely visual. For electrically meaningful labels, use `add_schematic_net_label` instead.

| Parameter     | Type         | Required | Description                                      |
| ------------- | ------------ | -------- | ------------------------------------------------ |
| schematicPath | string       | Yes      | Path to the .kicad_sch file                      |
| text          | string       | Yes      | Text content to display                          |
| position      | array [x, y] | Yes      | Position in schematic mm coordinates             |
| angle         | number       | No       | Rotation angle in degrees (default: 0)           |
| fontSize      | number       | No       | Font size in mm (default: 1.27 — KiCad standard) |
| bold          | boolean      | No       | Bold text (default: false)                       |
| italic        | boolean      | No       | Italic text (default: false)                     |
| justify       | string       | No       | `left` \| `center` \| `right` (default: `left`)  |

### list_schematic_texts

List all free-form text annotations in the schematic. Optionally filter by a substring of the text content.

| Parameter     | Type   | Required | Description                                                    |
| ------------- | ------ | -------- | -------------------------------------------------------------- |
| schematicPath | string | Yes      | Path to the .kicad_sch file                                    |
| text          | string | No       | Case-insensitive substring filter — only return matching texts |

**Response fields (per text entry):**

| Field     | Description                         |
| --------- | ----------------------------------- |
| text      | Text string content                 |
| position  | `{"x": float, "y": float}` in mm    |
| angle     | Rotation angle in degrees           |
| font_size | Font size in mm                     |
| bold      | `true` / `false`                    |
| italic    | `true` / `false`                    |
| justify   | `"left"` \| `"center"` \| `"right"` |
| uuid      | KiCad UUID of the element           |

## Schematic Creation and Export (6 tools)

### create_schematic

Create a new schematic.

| Parameter | Type   | Required | Description    |
| --------- | ------ | -------- | -------------- |
| name      | string | Yes      | Schematic name |
| path      | string | No       | Optional path  |

### export_schematic_svg

Export schematic to SVG format using kicad-cli.

| Parameter     | Type    | Required | Description                 |
| ------------- | ------- | -------- | --------------------------- |
| schematicPath | string  | Yes      | Path to the .kicad_sch file |
| outputPath    | string  | Yes      | Output SVG file path        |
| blackAndWhite | boolean | No       | Export in black and white   |

### export_schematic_pdf

Export schematic to PDF format using kicad-cli.

| Parameter     | Type    | Required | Description                 |
| ------------- | ------- | -------- | --------------------------- |
| schematicPath | string  | Yes      | Path to the .kicad_sch file |
| outputPath    | string  | Yes      | Output PDF file path        |
| blackAndWhite | boolean | No       | Export in black and white   |

### get_schematic_view

Return a rasterized image of the schematic (PNG by default, or SVG). Uses kicad-cli to export SVG, then converts to PNG via cairosvg. Use this for visual feedback after placing or wiring components.

| Parameter     | Type   | Required | Description                                  |
| ------------- | ------ | -------- | -------------------------------------------- |
| schematicPath | string | Yes      | Path to the .kicad_sch file                  |
| format        | enum   | No       | Output format ("png" or "svg", default: png) |
| width         | number | No       | Image width in pixels (default: 1200)        |
| height        | number | No       | Image height in pixels (default: 900)        |

### generate_netlist

Return a structured JSON netlist from the schematic for programmatic use. Uses `kicad-cli` internally — the schematic file must be saved to disk first.

| Parameter     | Type   | Required | Description                                    |
| ------------- | ------ | -------- | ---------------------------------------------- |
| schematicPath | string | Yes      | Absolute path to the .kicad_sch schematic file |

**Returns:** `{ components: [{reference, value, footprint}], nets: [{name, connections: [{component, pin}]}] }`

**Usage Notes:** Use this when you need net membership data in the conversation (e.g., to verify connectivity). For writing a netlist to a file or exporting SPICE/Cadstar/OrcadPCB2 format, use `export_netlist` instead.

### export_netlist

Export a netlist to a file in a standard EDA format using `kicad-cli`. Supports SPICE (for simulation), KiCad XML (for archiving/import), Cadstar, and OrcadPCB2.

| Parameter     | Type   | Required | Description                                                  |
| ------------- | ------ | -------- | ------------------------------------------------------------ |
| schematicPath | string | Yes      | Absolute path to the .kicad_sch schematic file               |
| outputPath    | string | Yes      | Absolute path for the output file (e.g. `/tmp/design.spice`) |
| format        | enum   | No       | `KiCad` (default), `Spice`, `Cadstar`, `OrcadPCB2`           |

**Usage Notes:** The schematic file must be saved before calling this tool. Use `Spice` format to produce a SPICE netlist for simulation or diff against a reference. The output file is created or overwritten at `outputPath`.

## Validation and Synchronization (6 tools)

### list_floating_labels

Return all net labels that are not connected to any component pin.

A label is "floating" when no component pin's coordinate falls on the wire-network reachable from the label's anchor position. Floating labels indicate misplaced or off-grid labels that will cause ERC errors. Does not require the KiCAD UI to be running.

| Parameter     | Type   | Required | Description                           |
| ------------- | ------ | -------- | ------------------------------------- |
| schematicPath | string | Yes      | Path to the .kicad_sch schematic file |

**Response fields:** list of `{"name": str, "x": float, "y": float, "type": "label" | "global_label"}`.

### find_orphaned_wires

Find wire segments with at least one dangling endpoint — not connected to a component pin, net label, or another wire. Orphaned wires cause ERC "wire end unconnected" errors. Does not require the KiCAD UI to be running.

| Parameter     | Type   | Required | Description                           |
| ------------- | ------ | -------- | ------------------------------------- |
| schematicPath | string | Yes      | Path to the .kicad_sch schematic file |

**Response fields:**

| Field          | Description                                                                  |
| -------------- | ---------------------------------------------------------------------------- |
| orphaned_wires | List of `{"start": {x,y}, "end": {x,y}, "dangling_ends": [{x,y}, ...]}` (mm) |
| count          | Total number of orphaned wire segments                                       |

### snap_to_grid

Snap schematic element coordinates to the nearest grid point. KiCAD uses exact integer matching (10 000 IU/mm) internally, so even a sub-pixel offset makes wires appear connected visually while failing ERC. Run this before `run_erc` to eliminate that class of error. Modifies the `.kicad_sch` file in place. Does not require the KiCAD UI to be running.

| Parameter     | Type            | Required | Description                                                                                                                                                                                                          |
| ------------- | --------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| schematicPath | string          | Yes      | Path to the .kicad_sch schematic file                                                                                                                                                                                |
| gridSize      | number          | No       | Grid spacing in mm (default: 2.54 — standard KiCAD schematic grid; use 1.27 for high-density)                                                                                                                        |
| elements      | array\<string\> | No       | Types to snap: `"wires"`, `"junctions"`, `"labels"`, `"components"`. Default: `["wires", "junctions", "labels"]`. `"components"` is opt-in — moving a component without re-routing its wires creates new mismatches. |

**Response fields:**

| Field           | Description                                               |
| --------------- | --------------------------------------------------------- |
| snapped         | Number of elements that had at least one coordinate moved |
| already_on_grid | Number of elements already on the grid                    |
| grid_size       | Grid spacing used (mm)                                    |

### run_erc

Runs the KiCAD Electrical Rules Check (ERC) on a schematic and returns all violations. Use after wiring to verify the schematic before generating a netlist.

| Parameter     | Type   | Required | Description                           |
| ------------- | ------ | -------- | ------------------------------------- |
| schematicPath | string | Yes      | Path to the .kicad_sch schematic file |

**Usage Notes:** Returns violations categorized by severity (error, warning, info) with location coordinates. Essential for catching design errors before PCB layout.

### sync_schematic_to_board

Import the schematic netlist into the PCB board — equivalent to pressing F8 in KiCAD (Tools → Update PCB from Schematic). MUST be called after the schematic is complete and before placing or routing components on the PCB. Without this step, the board has no footprints and no net assignments — place_component and route_pad_to_pad will produce an empty, unroutable board.

| Parameter     | Type   | Required | Description                                    |
| ------------- | ------ | -------- | ---------------------------------------------- |
| schematicPath | string | Yes      | Absolute path to the .kicad_sch schematic file |
| boardPath     | string | Yes      | Absolute path to the .kicad_pcb board file     |

**Usage Notes:** This is the F8 equivalent. It synchronizes the schematic design to the PCB, creating footprints on the board and assigning nets. This step is critical in the workflow: design in schematic → sync_schematic_to_board → place and route on PCB.

## Example Workflows

### Basic Circuit Design

1. **Create project:** Use `create_schematic` to initialize a new schematic file
2. **Add components:** Use `add_schematic_component` to place resistors, capacitors, ICs, etc.
   - Example: Add a resistor with `symbol: "Device:R"`, `reference: "R1"`, `value: "10k"`
3. **Wire components:** Use `add_schematic_connection` to connect component pins
   - Or use `connect_to_net` to connect pins to named nets (VCC, GND, etc.)
4. **Add net labels:** Use `add_schematic_net_label` to label important signals
5. **Validate:** Run `run_erc` to check for electrical rule violations
6. **Review:** Use `list_schematic_components` and `get_schematic_view` to verify the design
7. **Sync to PCB:** Use `sync_schematic_to_board` to transfer the design to the PCB layout

### FFC Passthrough Adapter

1. **Add connectors:** Place two FFC connectors using `add_schematic_component`
   - Example: J1 and J2, both 20-pin FFC connectors
2. **Connect passthrough:** Use `connect_passthrough` with `sourceRef: "J1"`, `targetRef: "J2"`, `netPrefix: "CSI"`
   - This single call connects all 20 pins (J1.1 ↔ J2.1 via CSI_1, J1.2 ↔ J2.2 via CSI_2, etc.)
3. **Sync to board:** Use `sync_schematic_to_board` to create the PCB layout
4. **Verify:** Use `list_schematic_nets` to confirm all connections are correct

## Source Files

The schematic tools are implemented across the following source files:

- **TypeScript (Tool Definitions):**
  - `/home/chris/MCP/KiCAD-MCP-Server/src/tools/schematic.ts` - All 27 schematic tool definitions with parameter schemas and handlers

- **Python (Backend Implementation):**
  - `/home/chris/MCP/KiCAD-MCP-Server/python/commands/component_schematic.py` - ComponentManager class (add, delete, edit, list components with dynamic symbol loading)
  - `/home/chris/MCP/KiCAD-MCP-Server/python/commands/connection_schematic.py` - ConnectionManager class (wiring, net labels, passthrough, netlist generation)
  - `/home/chris/MCP/KiCAD-MCP-Server/python/commands/wire_manager.py` - WireManager class (low-level wire manipulation)
  - `/home/chris/MCP/KiCAD-MCP-Server/python/commands/pin_locator.py` - PinLocator class (pin location lookup and angle calculation)
  - `/home/chris/MCP/KiCAD-MCP-Server/python/commands/dynamic_symbol_loader.py` - DynamicSymbolLoader class (runtime symbol loading from KiCad libraries)
