/**
 * Footprint prompts for KiCAD MCP server
 *
 * Guides Claude in creating and editing KiCAD footprints (.kicad_mod)
 * using the create_footprint, edit_footprint_pad, and list_footprint_libraries tools.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { logger } from "../logger.js";

export function registerFootprintPrompts(server: McpServer): void {
  logger.info("Registering footprint prompts");

  // ------------------------------------------------------
  // Create Footprint Prompt
  // ------------------------------------------------------
  server.prompt(
    "create_footprint_guide",
    {
      component: z
        .string()
        .describe(
          "Component description, e.g. 'SOT-23 NPN transistor' or '2-pin JST XH 2.5mm connector'",
        ),
      libraryPath: z
        .string()
        .optional()
        .describe("Target .pretty library path (optional)"),
    },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `You are a KiCAD footprint expert. Create a correct KiCAD 9 footprint using the create_footprint tool.

## Component to footprint
{{component}}

## Library path
{{libraryPath}}

## Rules for correct footprints

### Coordinate system
- Origin (0,0) is the footprint anchor, typically the centre of the pad pattern.
- X increases to the right, Y increases downward (same as KiCAD screen).
- All values in millimetres.

### SMD pads
- type: "smd"
- Default layers: ["F.Cu", "F.Paste", "F.Mask"]
- No drill needed.
- Common shapes: "rect" for square/rectangular, "roundrect" for ICs.

### THT pads
- type: "thru_hole"
- Default layers: ["*.Cu", "*.Mask"]
- drill required (round = scalar, oval = {w, h}).
- Pad 1 is typically square (rect), remaining pads are circle.

### Courtyard (F.CrtYd)
- Add 0.25 mm clearance around the outermost extent of pads.
- Line width: 0.05 mm.

### Silkscreen (F.SilkS)
- Shows the component body outline, typically slightly inside the courtyard.
- Line width: 0.12 mm.
- Must not overlap pads.

### Fab layer (F.Fab)
- Shows the realistic component outline with pin-1 marker.
- Line width: 0.10 mm.

### Reference text
- Place "REF**" above the courtyard (negative Y = above).
- Value text below the courtyard (positive Y = below).

## Workflow
1. Calculate pad positions from datasheet pitch and land pattern.
2. Call create_footprint with pads[], courtyard, silkscreen, fabLayer.
3. Verify with edit_footprint_pad if any correction is needed.

## Common packages quick reference
| Package   | Pitch  | Pad size (SMD)   | Notes                        |
|-----------|--------|------------------|------------------------------|
| 0402      | 1.0 mm | 0.6 × 0.7 mm     | Very small, min 0.5 mm drill |
| 0603      | 1.6 mm | 1.0 × 1.0 mm     | Standard small passive       |
| 0805      | 2.0 mm | 1.4 × 1.2 mm     | Easy to hand-solder          |
| SOT-23    | 0.95 mm| 1.0 × 1.3 mm     | 3-pin, 2 on one side         |
| SOT-23-5  | 0.95 mm| 0.6 × 1.0 mm     | 5-pin                        |
| SOIC-8    | 1.27 mm| 1.6 × 0.6 mm     | 4 pins each side             |
| DIP-8     | 2.54 mm| dia 1.6, drill 0.8| THT, 100 mil grid            |

Now create the footprint for: {{component}}`,
          },
        },
      ],
    }),
  );

  // ------------------------------------------------------
  // Footprint IPC Checklist Prompt
  // ------------------------------------------------------
  server.prompt(
    "footprint_ipc_checklist",
    {
      footprintPath: z
        .string()
        .describe("Path to the .kicad_mod file to review"),
    },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `Review the footprint at {{footprintPath}} against IPC-7351 land pattern guidelines.

Check:
1. **Pad size** – is the copper area sufficient for soldering (not undersized)?
2. **Courtyard** – at least 0.25 mm clearance around all pads?
3. **Silkscreen** – does it overlap pads? (it should NOT)
4. **Pad 1 marker** – is pin 1 identifiable (square pad or triangle on silkscreen)?
5. **Drill size** – for THT: drill ≥ lead diameter + 0.3 mm?
6. **Layer assignments** – SMD pads: F.Cu/F.Paste/F.Mask; THT: *.Cu/*.Mask?
7. **Anchor** – is the origin centred on the pad pattern?

Use edit_footprint_pad to fix any issues found.`,
          },
        },
      ],
    }),
  );
}
