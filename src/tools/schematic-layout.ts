/**
 * Schematic field-placement & layout-check tools.
 *
 * Move Reference/Value field labels, audit a schematic for layout problems, and
 * auto-position fields so they don't overlap bodies, wires, or net labels.
 */
import { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";
import { registerKiCadTool, type CommandFunction, withToolSignal } from "./tool-registration.js";

export function registerSchematicLayoutTools(server: McpServer, callKicadScript: CommandFunction) {
  callKicadScript = withToolSignal(callKicadScript);
  // Move a single Reference/Value field
  registerKiCadTool(
    server,
    "schematic_layout",
    "set_schematic_property_position",
    {
      description:
        "Move a component's Reference or Value field label to an absolute (x, y) coordinate (mm), optionally rotating or hiding it. Only 'Reference' and 'Value' are supported. Use autoplace_schematic_fields to place all of them automatically.",
      inputSchema: z.object({
        schematicPath: z.string().describe("Path to the .kicad_sch file"),
        reference: z.string().describe("Component reference designator (e.g., R1, U2)"),
        property: z.enum(["Reference", "Value"]).describe("Which field to move"),
        x: z.number().describe("New X position in mm (absolute schematic coordinate)"),
        y: z.number().describe("New Y position in mm (absolute schematic coordinate)"),
        angle: z.number().optional().default(0).describe("Text angle in degrees (default 0)"),
        visible: z
          .boolean()
          .optional()
          .default(true)
          .describe("Whether the field is visible (default true)"),
      }),
    },
    async (args: any) => {
      const result = await callKicadScript("set_schematic_property_position", args);
      return {
        content: [
          {
            type: "text",
            text: result.success ? result.message : `Failed: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // Move many fields in one file read/write
  registerKiCadTool(
    server,
    "schematic_layout",
    "batch_set_schematic_property_positions",
    {
      description:
        "Move many Reference/Value field labels in a single file read/write — far faster than repeated set_schematic_property_position calls. Pass an 'updates' array; each item is {reference, property:'Reference'|'Value', x, y, angle?, visible?}. Returns per-item applied/failed lists.",
      inputSchema: z.object({
        schematicPath: z.string().describe("Path to the .kicad_sch file"),
        updates: z
          .array(
            z.object({
              reference: z.string(),
              property: z.enum(["Reference", "Value"]),
              x: z.number(),
              y: z.number(),
              angle: z.number().optional().default(0),
              visible: z.boolean().optional().default(true),
            }),
          )
          .describe("List of field moves to apply"),
      }),
    },
    async (args: any) => {
      const result = await callKicadScript("batch_set_schematic_property_positions", args);
      if (result.success === false && result.message) {
        return { content: [{ type: "text", text: `Failed: ${result.message}` }] };
      }
      const lines = [
        `Applied ${result.applied_count} field move(s), ${result.failed_count} failed.`,
      ];
      for (const f of result.failed || []) {
        lines.push(`  ✗ ${f.reference}.${f.property}: ${f.reason}`);
      }
      return { content: [{ type: "text", text: lines.join("\n") }] };
    },
  );

  // Auto-position all Ref/Value fields
  registerKiCadTool(
    server,
    "schematic_layout",
    "autoplace_schematic_fields",
    {
      description:
        "Automatically reposition every component's Reference and Value field so they sit outside the component body AND outside any net labels attached to its pins, avoiding collisions with other components and already-placed fields. Like KiCAD's built-in field auto-placement but net-label aware. Optionally limit to specific references.",
      inputSchema: z.object({
        schematicPath: z.string().describe("Path to the .kicad_sch file"),
        references: z
          .array(z.string())
          .optional()
          .describe("Only reposition these references (default: all components)"),
        clearance: z
          .number()
          .optional()
          .describe(
            "Gap in mm between the body/label extent and field text (default one 1.27mm grid unit)",
          ),
      }),
    },
    async (args: any) => {
      const result = await callKicadScript("autoplace_schematic_fields", args);
      return {
        content: [
          {
            type: "text",
            text: result.success ? result.message : `Failed: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // Netlist-safe cosmetic lint: hide pin names, orient labels pin-side-aware
  registerKiCadTool(
    server,
    "schematic_layout",
    "lint_schematic_cosmetic",
    {
      description:
        "Netlist-safe cosmetic cleanup of a .kicad_sch, applied as raw-text edits that never " +
        "move a symbol, pin, wire, junction, or label anchor. Pass hide_pin_names gives every " +
        "top-level embedded lib_symbol a (pin_names ... (hide yes)) directive — in label-driven " +
        "schematics the internal pin names duplicate the net label on the same pin. Pass " +
        "orient_labels sets each net/global/hierarchical label's text angle and justify from " +
        "the sheet-space outward side of the pin it sits on (rotation/mirror aware), so text " +
        "reads away from the symbol body; labels not on a pin are left untouched. " +
        "Complements autoplace_schematic_fields (which handles Reference/Value fields).",
      inputSchema: z.object({
        schematicPath: z.string().describe("Path to the .kicad_sch file"),
        passes: z
          .array(z.enum(["hide_pin_names", "orient_labels"]))
          .optional()
          .describe("Passes to run, in order (default: both)"),
        dryRun: z
          .boolean()
          .optional()
          .describe("Report change counts without writing (default false)"),
      }),
    },
    async (args: any) => {
      const result = await callKicadScript("lint_schematic_cosmetic", args);
      return {
        content: [
          {
            type: "text",
            text: result.success ? result.message : `Failed: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  registerKiCadTool(
    server,
    "schematic_layout",
    "suggest_schematic_declutter",
    {
      description:
        "Re-orient overlapping net/global labels so their text lands in free space and becomes readable. Each label's (at x,y) anchor is its electrical connection point, so it is held FIXED — only the orientation (0/90/180/270) and justification change, throwing the text away from component bodies and other labels. Connectivity is never altered. DRY RUN by default: returns proposals [{name, at, from_angle, to_angle}] plus an overlap score (before/after) WITHOUT modifying the schematic. Set apply=true to rewrite the label orientations. (Phase 1: labels only; symbol spreading + wire reroute is a separate future capability.)",
      inputSchema: z.object({
        schematicPath: z.string().describe("Path to the .kicad_sch file"),
        margin: z
          .number()
          .optional()
          .describe("Extra clearance in mm when testing label overlap (default 0.3)."),
        references: z
          .array(z.string())
          .optional()
          .describe(
            "Limit which component bodies count as obstacles (default: every component on the sheet).",
          ),
        apply: z
          .boolean()
          .optional()
          .describe(
            "If true, rewrite the label orientations. Default false (dry run — schematic untouched, proposals only).",
          ),
      }),
    },
    async (args: any) => {
      const result = await callKicadScript("suggest_schematic_declutter", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );
}
