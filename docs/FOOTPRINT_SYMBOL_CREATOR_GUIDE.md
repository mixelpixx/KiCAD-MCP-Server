# Creating Custom Footprints and Symbols

Added in: v2.2.1-alpha (PRs #48, #49, contributor: @Kletternaut)

When existing KiCAD libraries don't have the component you need, these 8 tools let you create custom footprints and symbols programmatically. This enables automated part creation for custom PCB designs, specialized components, or rapid prototyping workflows where manual library editing would be time-consuming.

## Part 1: Footprint Creator

Footprints define the physical copper pads, silkscreen markings, and courtyard boundaries for PCB components. The footprint creator tools generate `.kicad_mod` files inside `.pretty` library directories.

### create_footprint

Create a new KiCAD footprint (.kicad_mod) inside a .pretty library directory. Supports SMD and THT pads, courtyard, silkscreen, and fab-layer rectangles.

| Parameter       | Type    | Required | Description                                                                                |
| --------------- | ------- | -------- | ------------------------------------------------------------------------------------------ |
| `libraryPath`   | string  | Yes      | Path to the .pretty library directory (created if missing). E.g. C:/MyProject/MyLib.pretty |
| `name`          | string  | Yes      | Footprint name, e.g. 'R_0603_Custom'                                                       |
| `description`   | string  | No       | Human-readable description                                                                 |
| `tags`          | string  | No       | Space-separated tag string, e.g. 'resistor SMD 0603'                                       |
| `pads`          | array   | No       | List of pad objects (see Pad Schema below). Can be empty for outlines-only footprints      |
| `courtyard`     | object  | No       | Courtyard rectangle on F.CrtYd (recommended: 0.25 mm clearance around pads)                |
| `silkscreen`    | object  | No       | Silkscreen rectangle on F.SilkS                                                            |
| `fabLayer`      | object  | No       | Fab-layer rectangle on F.Fab (shows component body)                                        |
| `refPosition`   | object  | No       | Position of the REF\*\* text, e.g. {x: 0, y: -1.27} (default: 0, -1.27)                    |
| `valuePosition` | object  | No       | Position of the Value text, e.g. {x: 0, y: 1.27} (default: 0, 1.27)                        |
| `overwrite`     | boolean | No       | Replace existing footprint file (default: false)                                           |

#### Pad Schema

Each pad object in the `pads` array supports:

| Parameter         | Type             | Required | Description                                                                                  |
| ----------------- | ---------------- | -------- | -------------------------------------------------------------------------------------------- |
| `number`          | string           | Yes      | Pad number / name, e.g. '1', '2', 'A1'                                                       |
| `type`            | enum             | Yes      | Pad type: `smd`, `thru_hole`, or `np_thru_hole`                                              |
| `shape`           | enum             | No       | Pad shape: `rect`, `circle`, `oval`, or `roundrect` (default: rect for SMD, circle for THT)  |
| `at`              | object           | Yes      | Pad centre position: {x: number, y: number, angle?: number} in mm                            |
| `size`            | object           | Yes      | Pad size: {w: number, h: number} in mm                                                       |
| `drill`           | number or object | No       | Round drill diameter (mm) or oval drill {w: number, h: number} (required for thru_hole pads) |
| `layers`          | array            | No       | Override default layer list, e.g. ['F.Cu','F.Paste','F.Mask']                                |
| `roundrect_ratio` | number           | No       | Corner radius ratio for roundrect shape (0.0-0.5, default 0.25)                              |

#### Rectangle Schema (courtyard, silkscreen, fabLayer)

| Parameter | Type   | Required | Description      |
| --------- | ------ | -------- | ---------------- |
| `x1`      | number | Yes      | Left X in mm     |
| `y1`      | number | Yes      | Top Y in mm      |
| `x2`      | number | Yes      | Right X in mm    |
| `y2`      | number | Yes      | Bottom Y in mm   |
| `width`   | number | No       | Line width in mm |

#### Pad Types

- **SMD (smd)**: Surface-mount pads for components that sit on top of the PCB. Default layers: F.Cu, F.Paste, F.Mask
- **THT (thru_hole)**: Through-hole pads for components with leads that pass through the PCB. Requires `drill` parameter. Default layers: \*.Cu, F.Mask, B.Mask
- **NPTH (np_thru_hole)**: Non-plated through-holes for mechanical mounting. Requires `drill` parameter. Default layers: \*.Mask

### edit_footprint_pad

Edit an existing pad inside a .kicad_mod footprint file. Updates size, position, drill, or shape without recreating the whole footprint.

| Parameter       | Type             | Required | Description                                                                  |
| --------------- | ---------------- | -------- | ---------------------------------------------------------------------------- |
| `footprintPath` | string           | Yes      | Full path to the .kicad_mod file, e.g. C:/MyLib.pretty/R_Custom.kicad_mod    |
| `padNumber`     | string or number | Yes      | Pad number to edit, e.g. '1' or 2                                            |
| `size`          | object           | No       | New pad size: {w: number, h: number} in mm                                   |
| `at`            | object           | No       | New pad position: {x: number, y: number, angle?: number} in mm               |
| `drill`         | number or object | No       | New drill size: number (round) or {w: number, h: number} (oval) for THT pads |
| `shape`         | enum             | No       | New pad shape: `rect`, `circle`, `oval`, or `roundrect`                      |

**When to use:** Use this tool when you need to adjust an existing footprint's pad dimensions or positions without recreating the entire footprint. Useful for fine-tuning after initial creation or adapting existing footprints.

### register_footprint_library

Register a .pretty footprint library in KiCAD's fp-lib-table so KiCAD can find the footprints. Run this after create_footprint when KiCAD shows 'library not found in footprint library table'.

| Parameter     | Type   | Required | Description                                                                                                                |
| ------------- | ------ | -------- | -------------------------------------------------------------------------------------------------------------------------- |
| `libraryPath` | string | Yes      | Full path to the .pretty directory to register                                                                             |
| `libraryName` | string | No       | Nickname for the library in KiCAD (default: directory name without .pretty)                                                |
| `description` | string | No       | Optional description                                                                                                       |
| `scope`       | enum   | No       | `project` = writes fp-lib-table next to the .kicad_pro file (default); `global` = writes to the user's global KiCAD config |
| `projectPath` | string | No       | Path to the .kicad_pro file or its directory (required for scope=project when the library is not in the project folder)    |

**How fp-lib-table works:** KiCAD maintains a table mapping library nicknames to filesystem paths. Project-scope tables (fp-lib-table in the project directory) take precedence over global tables. This allows project-specific libraries without polluting the global configuration.

### list_footprint_libraries

List available .pretty footprint libraries and their contents (first 20 footprints per library). Searches KiCAD standard install paths by default.

| Parameter     | Type  | Required | Description                                                                                   |
| ------------- | ----- | -------- | --------------------------------------------------------------------------------------------- |
| `searchPaths` | array | No       | Override default search paths. Each entry should be a directory that contains .pretty subdirs |

### Example: Creating a Custom SOT-23 Footprint

This example creates a simple 3-pad SMD footprint for a SOT-23 transistor package:

```javascript
// Step 1: Create the footprint
{
  "libraryPath": "/home/user/myproject/CustomParts.pretty",
  "name": "SOT-23_Custom",
  "description": "SOT-23 3-pin SMD package, custom pitch",
  "tags": "SOT-23 transistor SMD",
  "pads": [
    {
      "number": "1",
      "type": "smd",
      "shape": "rect",
      "at": {"x": -0.95, "y": 1.0},
      "size": {"w": 0.6, "h": 0.7}
    },
    {
      "number": "2",
      "type": "smd",
      "shape": "rect",
      "at": {"x": 0.95, "y": 1.0},
      "size": {"w": 0.6, "h": 0.7}
    },
    {
      "number": "3",
      "type": "smd",
      "shape": "rect",
      "at": {"x": 0, "y": -1.0},
      "size": {"w": 0.6, "h": 0.7}
    }
  ],
  "courtyard": {
    "x1": -1.5,
    "y1": -1.5,
    "x2": 1.5,
    "y2": 1.5,
    "width": 0.05
  },
  "silkscreen": {
    "x1": -1.3,
    "y1": -0.3,
    "x2": 1.3,
    "y2": 0.3,
    "width": 0.12
  },
  "fabLayer": {
    "x1": -1.25,
    "y1": -0.25,
    "x2": 1.25,
    "y2": 0.25,
    "width": 0.1
  }
}

// Step 2: Register the library so KiCAD can find it
{
  "libraryPath": "/home/user/myproject/CustomParts.pretty",
  "scope": "project",
  "projectPath": "/home/user/myproject/myproject.kicad_pro"
}
```

The footprint will be saved as `/home/user/myproject/CustomParts.pretty/SOT-23_Custom.kicad_mod` and will be available in KiCAD's footprint browser under the library name "CustomParts".

## Part 2: Symbol Creator

Symbols define the schematic representation of electronic components, including pins, graphical body shapes, and electrical properties. The symbol creator tools generate and manage `.kicad_sym` library files.

### create_symbol

Create a new schematic symbol in a .kicad_sym library file (created if missing). After creation, use register_symbol_library so KiCAD finds it.

Pin positions are where the wire connects; the symbol body is drawn between them.

**Coordinate tips:**

- Body rectangle typically spans ±2.54 to ±5.08 mm
- Pins on left side: at.x = body_left - length, angle=0 (wire goes right)
- Pins on right side: at.x = body_right + length, angle=180 (wire goes left)
- Pins on top: at.y = body_top + length, angle=270 (wire goes down)
- Pins on bottom: at.y = body_bottom - length, angle=90 (wire goes up)
- Standard pin length: 2.54 mm, standard grid: 2.54 mm

| Parameter         | Type    | Required | Description                                                                              |
| ----------------- | ------- | -------- | ---------------------------------------------------------------------------------------- |
| `libraryPath`     | string  | Yes      | Path to the .kicad_sym file (created if missing)                                         |
| `name`            | string  | Yes      | Symbol name, e.g. 'TMC2209', 'MyOpAmp'                                                   |
| `referencePrefix` | string  | No       | Schematic reference prefix: 'U' (IC), 'R' (resistor), 'J' (connector), etc. Default: 'U' |
| `description`     | string  | No       | Human-readable description                                                               |
| `keywords`        | string  | No       | Space-separated search keywords                                                          |
| `datasheet`       | string  | No       | Datasheet URL or '~'                                                                     |
| `footprint`       | string  | No       | Default footprint, e.g. 'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm'                            |
| `inBom`           | boolean | No       | Include in BOM (default true)                                                            |
| `onBoard`         | boolean | No       | Include in netlist for PCB (default true)                                                |
| `pins`            | array   | No       | List of pin objects (see Pin Schema below). Can be empty for graphical-only symbols      |
| `rectangles`      | array   | No       | Body rectangle(s). Typically one rectangle defining the IC body                          |
| `polylines`       | array   | No       | Polyline graphics for custom body shapes (op-amp triangles, etc.)                        |
| `overwrite`       | boolean | No       | Replace existing symbol with same name (default false)                                   |

#### Pin Schema

Each pin object in the `pins` array supports:

| Parameter | Type             | Required | Description                                                                                                                         |
| --------- | ---------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `name`    | string           | Yes      | Pin name, e.g. 'VCC', 'GND', 'IN+', '~' for unnamed                                                                                 |
| `number`  | string or number | Yes      | Pin number, e.g. '1', '2', 'A1'                                                                                                     |
| `type`    | enum             | Yes      | Electrical pin type (see Pin Types below)                                                                                           |
| `at`      | object           | Yes      | Pin endpoint position: {x: number, y: number, angle: number} where angle is the direction the pin wire extends FROM the symbol body |
| `length`  | number           | No       | Pin length in mm (default 2.54)                                                                                                     |
| `shape`   | enum             | No       | Pin graphic shape (default: line)                                                                                                   |

**Pin angle conventions:**

- 0 = right (wire extends to the right from the symbol body)
- 90 = up (wire extends upward)
- 180 = left (wire extends to the left)
- 270 = down (wire extends downward)

#### Pin Types (Electrical)

| Type             | Description                               |
| ---------------- | ----------------------------------------- |
| `input`          | Input pin                                 |
| `output`         | Output pin                                |
| `bidirectional`  | Bidirectional I/O                         |
| `tri_state`      | Tri-state output                          |
| `passive`        | Passive component (resistors, capacitors) |
| `free`           | Free pin (no electrical rule checking)    |
| `unspecified`    | Unspecified type                          |
| `power_in`       | Power input (VCC, VDD)                    |
| `power_out`      | Power output (regulators)                 |
| `open_collector` | Open collector output                     |
| `open_emitter`   | Open emitter output                       |
| `no_connect`     | Not connected                             |

#### Pin Shapes (Graphical)

| Shape                | Description                |
| -------------------- | -------------------------- |
| `line`               | Standard pin (default)     |
| `inverted`           | Pin with inversion bubble  |
| `clock`              | Clock input (triangle)     |
| `inverted_clock`     | Inverted clock with bubble |
| `input_low`          | Active-low input           |
| `clock_low`          | Active-low clock           |
| `output_low`         | Active-low output          |
| `falling_edge_clock` | Falling edge triggered     |
| `non_logic`          | Non-logic pin              |

#### Rectangle Schema

| Parameter | Type   | Required | Description                                                         |
| --------- | ------ | -------- | ------------------------------------------------------------------- |
| `x1`      | number | Yes      | Left X in mm                                                        |
| `y1`      | number | Yes      | Top Y in mm                                                         |
| `x2`      | number | Yes      | Right X in mm                                                       |
| `y2`      | number | Yes      | Bottom Y in mm                                                      |
| `width`   | number | No       | Stroke width in mm (default 0.254)                                  |
| `fill`    | enum   | No       | Fill type: `none`, `outline`, or `background` (default: background) |

#### Polyline Schema

| Parameter | Type   | Required | Description                                            |
| --------- | ------ | -------- | ------------------------------------------------------ |
| `points`  | array  | Yes      | List of XY points: [{x: number, y: number}, ...] in mm |
| `width`   | number | No       | Stroke width in mm (default 0.254)                     |
| `fill`    | enum   | No       | Fill type: `none`, `outline`, or `background`          |

### delete_symbol

Remove a symbol from a .kicad_sym library file.

| Parameter     | Type   | Required | Description                 |
| ------------- | ------ | -------- | --------------------------- |
| `libraryPath` | string | Yes      | Path to the .kicad_sym file |
| `name`        | string | Yes      | Symbol name to delete       |

### list_symbols_in_library

List all symbol names in a .kicad_sym library file.

| Parameter     | Type   | Required | Description                 |
| ------------- | ------ | -------- | --------------------------- |
| `libraryPath` | string | Yes      | Path to the .kicad_sym file |

### register_symbol_library

Register a .kicad_sym library in KiCAD's sym-lib-table so symbols can be used in schematics. Run this after create_symbol when KiCAD shows 'library not found'.

| Parameter     | Type   | Required | Description                                                                           |
| ------------- | ------ | -------- | ------------------------------------------------------------------------------------- |
| `libraryPath` | string | Yes      | Full path to the .kicad_sym file                                                      |
| `libraryName` | string | No       | Nickname (default: file name without extension)                                       |
| `description` | string | No       | Optional description                                                                  |
| `scope`       | enum   | No       | `project` = writes sym-lib-table next to .kicad_pro (default); `global` = user config |
| `projectPath` | string | No       | Path to .kicad_pro or its directory (for scope=project)                               |

### Example: Creating a Simple IC Symbol

This example creates a 4-pin IC symbol (VCC, GND, IN, OUT):

```javascript
// Step 1: Create the symbol
{
  "libraryPath": "/home/user/myproject/CustomSymbols.kicad_sym",
  "name": "MyRegulator",
  "referencePrefix": "U",
  "description": "Simple voltage regulator",
  "keywords": "regulator power",
  "datasheet": "~",
  "footprint": "Package_TO_SOT_SMD:SOT-23",
  "pins": [
    {
      "name": "VIN",
      "number": "1",
      "type": "power_in",
      "at": {"x": -7.62, "y": 2.54, "angle": 0},
      "length": 2.54
    },
    {
      "name": "GND",
      "number": "2",
      "type": "power_in",
      "at": {"x": 0, "y": -7.62, "angle": 90},
      "length": 2.54
    },
    {
      "name": "VOUT",
      "number": "3",
      "type": "power_out",
      "at": {"x": 7.62, "y": 2.54, "angle": 180},
      "length": 2.54
    }
  ],
  "rectangles": [
    {
      "x1": -5.08,
      "y1": -5.08,
      "x2": 5.08,
      "y2": 5.08,
      "width": 0.254,
      "fill": "background"
    }
  ]
}

// Step 2: Register the library
{
  "libraryPath": "/home/user/myproject/CustomSymbols.kicad_sym",
  "scope": "project",
  "projectPath": "/home/user/myproject/myproject.kicad_pro"
}
```

**Pin positioning explained:**

- VIN pin at (-7.62, 2.54, angle=0): Wire extends to the right, so the symbol body should be to the right. Body left edge is at -5.08, and pin length is 2.54, so -7.62 = -5.08 - 2.54
- GND pin at (0, -7.62, angle=90): Wire extends upward, body bottom is at -5.08, so -7.62 = -5.08 - 2.54
- VOUT pin at (7.62, 2.54, angle=180): Wire extends to the left, body right is at 5.08, so 7.62 = 5.08 + 2.54

## Coordinate Systems

### Footprint Coordinates

- Origin (0, 0) is typically at the component center or pin 1
- Positive X extends right, positive Y extends down (PCB view from top)
- All dimensions in millimeters
- Courtyard should extend 0.25mm beyond pads for IPC-7351 compliance
- Silkscreen should not overlap pads (typically 0.1-0.2mm clearance)

### Symbol Coordinates

- Origin (0, 0) is typically at the symbol center
- Positive X extends right, positive Y extends up (schematic convention)
- All dimensions in millimeters
- Standard grid is 2.54mm (100 mil) for pin spacing
- Pin positions define where wires connect, not where the pin graphic starts
- Body graphics are drawn independently of pin positions

### Key Difference

Footprints use a "Y-down" coordinate system (like screen coordinates), while symbols use a "Y-up" coordinate system (like mathematical graphs). This is a KiCAD convention that matches industry standards for PCB layout vs schematic capture.

## Integration with Design Workflow

### Typical Workflow

1. **Create the symbol** using `create_symbol` with pin definitions and body graphics
2. **Register the symbol library** using `register_symbol_library` so it appears in the schematic editor
3. **Create the footprint** using `create_footprint` with pad definitions and courtyard
4. **Register the footprint library** using `register_footprint_library` so it appears in the PCB editor
5. **Link symbol to footprint** by setting the `footprint` parameter in `create_symbol`, or assign it later in the schematic editor

### Library Organization

- **Project-scope libraries**: Store in the project directory, register with `scope: "project"`. Best for project-specific custom parts.
- **Global libraries**: Store in a central location, register with `scope: "global"`. Best for reusable parts across multiple projects.
- **Naming conventions**: Use descriptive names. For footprints: `PackageType_Variant`, e.g. `SOIC-8_Custom`. For symbols: `PartNumber` or `FunctionDescription`.

### Validation

After creating custom parts:

- Open KiCAD schematic editor and verify the symbol appears in the "Add Symbol" dialog
- Check pin numbers, names, and electrical types in symbol properties
- Open KiCAD PCB editor and verify the footprint appears in the footprint browser
- Use the 3D viewer to check pad positions and courtyard clearances
- Run Design Rules Check (DRC) to ensure courtyard and clearance compliance

## Source Files

- TypeScript tool definitions: `/home/chris/MCP/KiCAD-MCP-Server/src/tools/footprint.ts`
- TypeScript symbol definitions: `/home/chris/MCP/KiCAD-MCP-Server/src/tools/symbol-creator.ts`
- Python footprint implementation: `/home/chris/MCP/KiCAD-MCP-Server/python/commands/footprint.py`
- Python symbol implementation: `/home/chris/MCP/KiCAD-MCP-Server/python/commands/symbol_creator.py`
