# Schematic Tools Reference

Added in: v2.1.0, expanded in v2.2.0-v2.2.3
Contributors: @Mehanik (PRs #60, #66), @Kletternaut (PR #57)

This document provides a complete reference for the 27 schematic tools in the KiCAD MCP Server. These tools enable a complete schematic design workflow, from creating projects and adding components to wiring, validation, and synchronization with PCB boards. The dynamic symbol loading feature provides access to approximately 10,000 standard KiCad symbols.

## Component Operations (8 tools)

### add_schematic_component
Add a component to the schematic. Symbol format is 'Library:SymbolName' (e.g., 'Device:R', 'EDA-MCP:ESP32-C3').

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the schematic file |
| symbol | string | Yes | Symbol library:name reference (e.g., Device:R, EDA-MCP:ESP32-C3) |
| reference | string | Yes | Component reference (e.g., R1, U1) |
| value | string | No | Component value |
| footprint | string | No | KiCAD footprint (e.g. Resistor_SMD:R_0603_1608Metric) |
| position | object | No | Position on schematic with x and y coordinates |

**Usage Notes:** The dynamic symbol loader provides access to ~10,000 KiCad standard symbols. If a symbol is not in the static template map, it will be loaded dynamically from the specified library.

### delete_schematic_component
Remove a placed symbol from a KiCAD schematic (.kicad_sch). This removes the symbol instance (the placed component) from the schematic. It does NOT remove the symbol definition from lib_symbols. Note: This tool operates on schematic files (.kicad_sch). To remove a footprint from a PCB, use delete_component instead.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the .kicad_sch file |
| reference | string | Yes | Reference designator of the component to remove (e.g. R1, U3) |

### edit_schematic_component
Update properties of a placed symbol in a KiCAD schematic (.kicad_sch) in-place. Use this tool to assign or update a footprint, change the value, or rename the reference of an already-placed component. This is more efficient than delete + re-add because it preserves the component's position and UUID. Note: operates on .kicad_sch files only. To modify a PCB footprint use edit_component.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the .kicad_sch file |
| reference | string | Yes | Current reference designator of the component (e.g. R1, U3) |
| footprint | string | No | New KiCAD footprint string (e.g. Resistor_SMD:R_0603_1608Metric) |
| value | string | No | New value string (e.g. 10k, 100nF) |
| newReference | string | No | Rename the reference designator (e.g. R1 → R10) |
| fieldPositions | object | No | Reposition field labels: map of field name to {x, y, angle} (e.g. {"Reference": {"x": 12.5, "y": 17.0}}) |

### get_schematic_component
Get full component info from a schematic: position, field values, and each field's label position (at x/y/angle). Use this to inspect or prepare repositioning of Reference/Value labels.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the .kicad_sch file |
| reference | string | Yes | Component reference designator (e.g. R1, U1) |

### list_schematic_components
List all components in a schematic with their references, values, positions, and pins. Essential for inspecting what's on the schematic before making edits.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the .kicad_sch file |
| filter | object | No | Optional filters with libId and/or referencePrefix fields |
| filter.libId | string | No | Filter by library ID (e.g., 'Device:R') |
| filter.referencePrefix | string | No | Filter by reference prefix (e.g., 'R', 'C', 'U') |

### move_schematic_component
Move a placed symbol to a new position in the schematic.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the .kicad_sch file |
| reference | string | Yes | Reference designator (e.g., R1, U1) |
| position | object | Yes | New position with x and y coordinates |

### rotate_schematic_component
Rotate a placed symbol in the schematic.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the .kicad_sch file |
| reference | string | Yes | Reference designator (e.g., R1, U1) |
| angle | number | Yes | Rotation angle in degrees (0, 90, 180, 270) |
| mirror | enum | No | Optional mirror axis ("x" or "y") |

### annotate_schematic
Assign reference designators to unannotated components (R? → R1, R2, ...). Must be called before tools that require known references.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the .kicad_sch file |

## Wiring and Connections (8 tools)

### add_wire
Add a wire connection in the schematic.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| start | object | Yes | Start position with x and y coordinates |
| end | object | Yes | End position with x and y coordinates |

### add_schematic_connection
Connect two component pins with a wire. Use this for individual connections between components with different pin roles (e.g. U1.SDA → J3.2). WARNING: Do NOT use this in a loop to wire N passthrough pins — use connect_passthrough instead (single call, cleaner layout, far fewer tokens).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the schematic file |
| sourceRef | string | Yes | Source component reference (e.g., R1) |
| sourcePin | string | Yes | Source pin name/number (e.g., 1, 2, GND) |
| targetRef | string | Yes | Target component reference (e.g., C1) |
| targetPin | string | Yes | Target pin name/number (e.g., 1, 2, VCC) |

### add_schematic_net_label
Add a net label to the schematic.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the schematic file |
| netName | string | Yes | Name of the net (e.g., VCC, GND, SIGNAL_1) |
| position | array | Yes | Position [x, y] for the label |

### connect_to_net
Connect a component pin to a named net.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the schematic file |
| componentRef | string | Yes | Component reference (e.g., U1, R1) |
| pinName | string | Yes | Pin name/number to connect |
| netName | string | Yes | Name of the net to connect to |

**Usage Notes:** Creates a wire stub from the pin and places a net label at the stub endpoint. The stub direction follows the pin's outward angle. Default stub length is 2.54mm (0.1 inch, standard grid spacing).

### connect_passthrough
Connects all pins of a source connector (e.g. J1) to matching pins of a target connector (e.g. J2) via shared net labels — pin N gets net '{netPrefix}_{N}'. Use this for FFC/ribbon cable passthrough adapters instead of calling connect_to_net for every pin.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the schematic file |
| sourceRef | string | Yes | Source connector reference (e.g. J1) |
| targetRef | string | Yes | Target connector reference (e.g. J2) |
| netPrefix | string | No | Net name prefix, e.g. 'CSI' → CSI_1, CSI_2 (default: PIN) |
| pinOffset | number | No | Add to pin number when building net name (default: 0) |

**Usage Notes:** This is the most efficient way to wire passthrough adapters. For an N-pin connector, this replaces N individual connect_to_net calls with a single operation.

### get_schematic_pin_locations
Returns the exact x/y coordinates of every pin on a schematic component. Use this before add_schematic_net_label to place labels correctly on pin endpoints.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the schematic file |
| reference | string | Yes | Component reference designator (e.g. U1, R1, J2) |

### delete_schematic_wire
Remove a wire from the schematic by start and end coordinates.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the .kicad_sch file |
| start | object | Yes | Wire start position with x and y coordinates |
| end | object | Yes | Wire end position with x and y coordinates |

### delete_schematic_net_label
Remove a net label from the schematic.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the .kicad_sch file |
| netName | string | Yes | Name of the net label to remove |
| position | object | No | Position to disambiguate if multiple labels with same name (x and y coordinates) |

## Net Analysis (4 tools)

### get_net_connections
Get all connections for a named net.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the schematic file |
| netName | string | Yes | Name of the net to query |

**Usage Notes:** Uses wire graph analysis to find all component pins connected to the specified net. Returns a list of {component, pin} pairs.

### list_schematic_nets
List all nets in the schematic with their connections.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the .kicad_sch file |

### list_schematic_wires
List all wires in the schematic with start/end coordinates.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the .kicad_sch file |

### list_schematic_labels
List all net labels, global labels, and power flags in the schematic.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the .kicad_sch file |

## Schematic Creation and Export (5 tools)

### create_schematic
Create a new schematic.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | string | Yes | Schematic name |
| path | string | No | Optional path |

### export_schematic_svg
Export schematic to SVG format using kicad-cli.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the .kicad_sch file |
| outputPath | string | Yes | Output SVG file path |
| blackAndWhite | boolean | No | Export in black and white |

### export_schematic_pdf
Export schematic to PDF format using kicad-cli.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the .kicad_sch file |
| outputPath | string | Yes | Output PDF file path |
| blackAndWhite | boolean | No | Export in black and white |

### get_schematic_view
Return a rasterized image of the schematic (PNG by default, or SVG). Uses kicad-cli to export SVG, then converts to PNG via cairosvg. Use this for visual feedback after placing or wiring components.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the .kicad_sch file |
| format | enum | No | Output format ("png" or "svg", default: png) |
| width | number | No | Image width in pixels (default: 1200) |
| height | number | No | Image height in pixels (default: 900) |

### generate_netlist
Generate a netlist from the schematic.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the schematic file |

**Usage Notes:** Returns a complete netlist with component information (reference, value, footprint) and net connections (net name with all connected component/pin pairs).

## Validation and Synchronization (3 tools)

### run_erc
Runs the KiCAD Electrical Rules Check (ERC) on a schematic and returns all violations. Use after wiring to verify the schematic before generating a netlist.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Path to the .kicad_sch schematic file |

**Usage Notes:** Returns violations categorized by severity (error, warning, info) with location coordinates. Essential for catching design errors before PCB layout.

### sync_schematic_to_board
Import the schematic netlist into the PCB board — equivalent to pressing F8 in KiCAD (Tools → Update PCB from Schematic). MUST be called after the schematic is complete and before placing or routing components on the PCB. Without this step, the board has no footprints and no net assignments — place_component and route_pad_to_pad will produce an empty, unroutable board.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| schematicPath | string | Yes | Absolute path to the .kicad_sch schematic file |
| boardPath | string | Yes | Absolute path to the .kicad_pcb board file |

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
