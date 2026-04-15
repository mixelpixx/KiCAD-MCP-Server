# SVG Logo Import Guide

**Added in:** v2.2.3

The `import_svg_logo` tool converts SVG vector graphics into filled polygons on a KiCAD PCB layer. This is useful for placing company logos, project branding, or custom artwork on your board's silkscreen or copper layers.

---

## Tool Reference

### `import_svg_logo`

Imports an SVG file as filled graphic polygons onto a PCB layer. Curves are linearized automatically.

**Parameters:**

| Parameter     | Type    | Required | Default | Description                                                             |
| ------------- | ------- | -------- | ------- | ----------------------------------------------------------------------- |
| `pcbPath`     | string  | Yes      | --      | Path to the .kicad_pcb file                                             |
| `svgPath`     | string  | Yes      | --      | Path to the SVG logo file                                               |
| `x`           | number  | Yes      | --      | X position of the logo top-left corner in mm                            |
| `y`           | number  | Yes      | --      | Y position of the logo top-left corner in mm                            |
| `width`       | number  | Yes      | --      | Target width of the logo in mm (height scales to preserve aspect ratio) |
| `layer`       | string  | No       | F.SilkS | PCB layer name (e.g., F.SilkS, B.SilkS, F.Cu, B.Cu)                     |
| `strokeWidth` | number  | No       | 0       | Outline stroke width in mm (0 = no outline)                             |
| `filled`      | boolean | No       | true    | Fill polygons with solid color                                          |

**Returns:**

- Polygon count
- Final dimensions (width x height in mm)
- Layer used

---

## SVG Requirements

### Supported Features

- Path elements with M, L, H, V, C, S, Q, T, A, Z commands
- Filled shapes (polygons, rectangles, circles, ellipses)
- Nested groups and transforms
- Cubic and quadratic Bezier curves (linearized automatically)

### Recommendations

- Use simple, solid shapes -- avoid complex gradients or filters
- Convert text to paths/outlines before importing
- Ensure shapes are filled (not just stroked) for best results
- Keep the SVG clean -- remove unnecessary metadata and layers

### What Will Not Work

- Raster images embedded in SVG
- CSS-based styling (inline style attributes are preferred)
- Complex SVG filters or effects
- Transparency (PCB layers are binary -- copper or no copper)

---

## Workflow

### 1. Prepare Your SVG

If starting from a raster image (PNG, JPG):

- Use a vector graphics editor (Inkscape, Illustrator, Figma) to trace the image
- In Inkscape: Path > Trace Bitmap to convert
- Export as plain SVG

If starting from a vector logo:

- Open in a vector editor
- Convert all text to paths (Object to Path / Create Outlines)
- Remove unnecessary layers and hidden elements
- Save as plain SVG

### 2. Import the Logo

```
Import my company logo from ~/logos/logo.svg onto the board at position x=25 y=40 with width 15mm on the front silkscreen.
```

### 3. Verify Placement

Use `get_board_2d_view` to preview the board with the logo, or open in KiCAD to check placement.

### 4. Adjust if Needed

Re-run `import_svg_logo` with different position, width, or layer parameters.

---

## Layer Options

| Layer     | Use Case                                              |
| --------- | ----------------------------------------------------- |
| `F.SilkS` | Front silkscreen (most common for logos)              |
| `B.SilkS` | Back silkscreen                                       |
| `F.Cu`    | Front copper (logo as exposed copper)                 |
| `B.Cu`    | Back copper                                           |
| `F.Mask`  | Front solder mask opening (exposes copper underneath) |
| `B.Mask`  | Back solder mask opening                              |

---

## Manufacturing Considerations

- **Silkscreen logos** are the safest choice -- no impact on electrical design
- **Copper logos** will be part of the copper layer and may affect DRC. Ensure adequate clearance from traces and pads
- **Minimum feature size** depends on your PCB fabricator. Most support 0.15mm (6mil) minimum line width for silkscreen
- **Logo size** should account for manufacturing tolerances -- very small details may not reproduce well

---

## Source Files

- TypeScript tool definition: `src/tools/board.ts` (import_svg_logo)
- Python implementation: `python/commands/svg_import.py`
