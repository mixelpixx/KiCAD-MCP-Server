# End-to-End PCB Design Workflow

This guide walks through the complete PCB design process using the KiCAD MCP Server, from project creation to manufacturing-ready output.

---

## Overview

A typical PCB design follows this flow:

```
Project Setup -> Schematic Design -> PCB Layout -> Verification -> Manufacturing Output
```

Each stage maps to specific MCP tools. You can ask your AI assistant to perform any of these steps using natural language.

---

## Stage 1: Project Setup

### Create a New Project

```
Create a new KiCAD project named "LEDBoard" in ~/Projects/
```

This uses `create_project` to generate:

- `.kicad_pro` -- project file
- `.kicad_pcb` -- PCB layout file
- `.kicad_sch` -- schematic file (with template symbols pre-loaded)

### Set Up the Board

```
Set the board size to 50mm x 50mm.
Add a rectangular board outline.
Add mounting holes at each corner, 3mm from the edges, 3mm diameter.
```

**Tools used:** `set_board_size`, `add_board_outline`, `add_mounting_hole`

---

## Stage 2: Schematic Design

### Place Components

```
Add an LED from the Device library to the schematic at position 100, 50.
Add a 1K resistor at position 100, 70.
Add a connector from the Connector_Generic library with 2 pins at position 60, 60.
```

**Tool:** `add_schematic_component`

The dynamic symbol loader provides access to all ~10,000 KiCad standard symbols. Specify any library and symbol name.

### Wire Components

```
Connect R1 pin 2 to LED1 pin 1.
Add a net label "VCC" at position 60, 50.
Connect J1 pin 1 to the VCC net.
Connect LED1 pin 2 to GND.
```

**Tools:** `add_schematic_connection`, `add_schematic_net_label`, `connect_to_net`

### FFC/Ribbon Cable Passthrough (Special Workflow)

For passthrough adapter boards (e.g., Raspberry Pi CSI adapters):

```
Connect all pins from J1 to J2 as a passthrough with net prefix "CSI_".
```

**Tool:** `connect_passthrough` -- automatically wires matching pins between two connectors

### Annotate and Validate

```
Annotate the schematic to assign reference designators.
Run an electrical rule check.
```

**Tools:** `annotate_schematic`, `run_erc`

### Preview the Schematic

```
Show me the schematic as an image.
Export the schematic to PDF.
```

**Tools:** `get_schematic_view`, `export_schematic_pdf`

---

## Stage 3: PCB Layout

### Synchronize Schematic to PCB

```
Sync the schematic to the board.
```

**Tool:** `sync_schematic_to_board` -- imports all component footprints and net assignments from the schematic into the PCB (equivalent to pressing F8 in KiCAD)

### Place Components

```
Move R1 to position x=15, y=25.
Move LED1 to position x=25, y=25.
Align all resistors horizontally.
```

**Tools:** `move_component`, `align_components`

### Route Traces

**Preferred approach -- pad-to-pad routing:**

```
Route R1 pad 2 to LED1 pad 1 with 0.3mm trace width.
```

**Tool:** `route_pad_to_pad` -- auto-detects pad positions, nets, and inserts vias when pads are on different layers

**Manual approach:**

```
Route a trace from x=15, y=25 to x=25, y=25 on the front copper layer.
```

**Tool:** `route_trace`

### Advanced Routing

**Differential pairs:**

```
Route a differential pair for USB_P and USB_N with 0.2mm width and 0.15mm gap.
```

**Copper zones:**

```
Add a GND copper pour on the bottom layer covering the entire board.
```

**Tools:** `route_differential_pair`, `add_copper_pour`

### Autorouting

For boards with many connections:

```
Check if Freerouting is available.
Autoroute the board using Freerouting.
```

**Tools:** `check_freerouting`, `autoroute`

See [Freerouting Guide](FREEROUTING_GUIDE.md) for setup details.

---

## Stage 4: Verification

### Design Rule Check

```
Set design rules with 0.15mm clearance and 0.2mm minimum track width.
Run the design rule check.
Show me all DRC violations.
```

**Tools:** `set_design_rules`, `run_drc`, `get_drc_violations`

### Visual Inspection

```
Show me a 2D view of the board.
```

**Tool:** `get_board_2d_view`

### Save a Checkpoint

```
Save a snapshot named "post-routing" with label "All traces routed, DRC clean".
```

**Tool:** `snapshot_project`

---

## Stage 5: Manufacturing Output

### Gerber Files

```
Export Gerber files to the fabrication folder.
```

**Tool:** `export_gerber`

### Bill of Materials

```
Export BOM as CSV.
```

**Tool:** `export_bom` (supports CSV, XML, HTML, JSON)

### Pick and Place

```
Export the component position file.
```

**Tool:** `export_position_file`

### 3D Preview

```
Export a 3D STEP model of the board.
```

**Tool:** `export_3d` (supports STEP, STL, VRML, OBJ)

### Documentation

```
Export a PDF of the board layout.
Export an SVG of the board.
```

**Tools:** `export_pdf`, `export_svg`

---

## Optional: JLCPCB Component Selection

Before placing components, you can search JLCPCB's catalog for optimal parts:

```
Search JLCPCB for 10K resistors in 0603 package, Basic parts only.
Show me the cheapest option with good stock.
Suggest alternatives to part C25804.
```

After selecting parts, enrich datasheets:

```
Enrich datasheets for all components in the schematic.
```

**Tools:** `search_jlcpcb_parts`, `get_jlcpcb_part`, `suggest_jlcpcb_alternatives`, `enrich_datasheets`

See [JLCPCB Integration](JLCPCB_INTEGRATION.md) for details.

---

## Optional: Custom Components

When existing libraries do not have the part you need:

```
Create a custom footprint for a 4-pin SOT-23 package.
Create a custom symbol for the XYZ IC with 8 pins.
Register the custom library so it can be used in the project.
```

**Tools:** `create_footprint`, `create_symbol`, `register_footprint_library`, `register_symbol_library`

See [Footprint and Symbol Creator Guide](FOOTPRINT_SYMBOL_CREATOR_GUIDE.md) for details.

---

## Optional: Add a Logo

```
Import our company logo from ~/logos/logo.svg onto the front silkscreen at position x=25 y=45 with width 10mm.
```

**Tool:** `import_svg_logo`

See [SVG Import Guide](SVG_IMPORT_GUIDE.md) for requirements and tips.

---

## Tips

- **Save frequently** -- use `save_project` after major changes
- **Use snapshots** -- `snapshot_project` creates named checkpoints you can return to
- **Validate early** -- run ERC after schematic changes and DRC after routing
- **Start with schematic** -- always design the schematic first, then sync to PCB
- **Use route_pad_to_pad** -- it is faster and more reliable than manual XY coordinate routing
- **Check the KiCAD UI** -- use `launch_kicad_ui` to open the design for visual verification

---

## Related Documentation

- [Tool Inventory](TOOL_INVENTORY.md) -- complete list of all 122 tools
- [Schematic Tools Reference](SCHEMATIC_TOOLS_REFERENCE.md) -- detailed schematic tool docs
- [Routing Tools Reference](ROUTING_TOOLS_REFERENCE.md) -- detailed routing tool docs
- [Freerouting Guide](FREEROUTING_GUIDE.md) -- autorouter setup and usage
- [JLCPCB Integration](JLCPCB_INTEGRATION.md) -- parts selection and cost optimization
