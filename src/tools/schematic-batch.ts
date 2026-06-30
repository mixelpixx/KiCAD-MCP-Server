/**
 * Batch schematic authoring tools.
 *
 * Place / edit / connect many things in one call to avoid per-item round-trips.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerSchematicBatchTools(server: McpServer, callKicadScript: Function) {
  // Add many components at once
  server.tool(
    "batch_add_components",
    "Add multiple components to a schematic in one call (far fewer round-trips than add_schematic_component). Each component: {symbol:'Library:Name', reference, value?, footprint?, position:{x,y}, rotation?, includePins?}. Reference/Value fields are auto-positioned outside the body (disable with auto_position_fields=false). Returns per-component snapped position, field positions, body_bbox, and an overall placement_bbox.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      components: z
        .array(
          z.object({
            symbol: z.string().describe("'Library:SymbolName' (e.g., Device:R)"),
            reference: z.string().describe("Reference designator (e.g., R1)"),
            value: z.string().optional(),
            footprint: z.string().optional(),
            position: z.object({ x: z.number(), y: z.number() }).optional(),
            rotation: z.number().optional(),
            includePins: z.boolean().optional(),
          }),
        )
        .describe("Components to place"),
      origin_x: z.number().optional().describe("X offset added to every component position (mm)"),
      origin_y: z.number().optional().describe("Y offset added to every component position (mm)"),
      auto_position_fields: z
        .boolean()
        .optional()
        .default(true)
        .describe("Auto-place Ref/Value fields outside the body (default true)"),
    },
    async (args: any) => {
      const r = await callKicadScript("batch_add_components", args);
      if (r.success === false && r.message)
        return { content: [{ type: "text", text: `Failed: ${r.message}` }] };
      const lines = [`Added ${r.added_count} component(s), ${r.error_count} error(s).`];
      for (const e of r.errors || []) lines.push(`  ✗ ${e.reference} (${e.symbol}): ${e.error}`);
      return { content: [{ type: "text", text: lines.join("\n") }] };
    },
  );

  // Edit many components at once
  server.tool(
    "batch_edit_schematic_components",
    "Edit multiple existing components in one call. 'components' is a map {reference: {value?, footprint?, newReference?, ...}}; each entry is applied via the single-component editor. Returns per-reference updated/errors.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      components: z
        .record(z.string(), z.record(z.string(), z.any()))
        .describe("Map of reference -> fields to change"),
    },
    async (args: any) => {
      const r = await callKicadScript("batch_edit_schematic_components", args);
      if (r.success === false && r.message)
        return { content: [{ type: "text", text: `Failed: ${r.message}` }] };
      const lines = [`Updated ${r.updated_count}, ${r.error_count} error(s).`];
      for (const e of r.errors || []) lines.push(`  ✗ ${e.reference}: ${e.error}`);
      return { content: [{ type: "text", text: lines.join("\n") }] };
    },
  );

  // Swap a symbol, preserving position/fields
  server.tool(
    "replace_schematic_component",
    "Replace a placed component's symbol with a different one (e.g. Device:R -> Device:R_Potentiometer), preserving its position, rotation, and field values (Value/Footprint/custom). Optionally override rotation with newRotation. Returns the new pin positions.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Reference of the component to replace (e.g., D1)"),
      newSymbol: z.string().describe("New symbol in 'Library:Symbol' form (e.g., Device:D_Zener)"),
      newRotation: z
        .number()
        .optional()
        .describe("Override rotation in degrees (default: keep existing)"),
    },
    async (args: any) => {
      const r = await callKicadScript("replace_schematic_component", args);
      return {
        content: [
          { type: "text", text: r.success ? r.message : `Failed: ${r.message || "Unknown error"}` },
        ],
      };
    },
  );

  // No-connect flags on many pins
  server.tool(
    "batch_add_no_connects",
    "Add no-connect (X) flags to multiple pins in one call, to mark intentionally unconnected pins and silence ERC. 'pins' is a list of {componentRef, pinName}.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      pins: z
        .array(z.object({ componentRef: z.string(), pinName: z.string() }))
        .describe("Pins to mark no-connect"),
    },
    async (args: any) => {
      const r = await callKicadScript("batch_add_no_connects", args);
      if (r.success === false && r.message)
        return { content: [{ type: "text", text: `Failed: ${r.message}` }] };
      const lines = [r.message];
      for (const f of r.failed || []) lines.push(`  ✗ ${f.componentRef}/${f.pinName}: ${f.reason}`);
      return { content: [{ type: "text", text: lines.join("\n") }] };
    },
  );

  // Net labels on many pins
  server.tool(
    "batch_connect",
    "Place net labels on multiple pins in one call to wire nets quickly. 'connections' is a map {reference: {pin: netName}} where pin is a number or name. labelType selects 'label' (sheet-local, the default) or 'global_label' (connects across all sheets by name — use this for power rails and any net that spans sheets). For local labels, if a facing label for the same net is nearby a wire is drawn instead of a duplicate label; global labels are placed one-per-pin since they join their net by name. Set replace=true to clear any existing label at a pin first. Warns about power nets missing a PWR_FLAG.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      connections: z
        .record(z.string(), z.record(z.string(), z.string()))
        .describe("Map of reference -> {pin: netName}"),
      labelType: z
        .enum(["label", "global_label"])
        .optional()
        .default("label")
        .describe(
          "Label kind: 'label' = sheet-local (default); 'global_label' = connects across all sheets by name",
        ),
      replace: z
        .boolean()
        .optional()
        .default(false)
        .describe("Delete existing labels at each pin before placing (default false)"),
    },
    async (args: any) => {
      const r = await callKicadScript("batch_connect", args);
      if (r.success === false && r.message)
        return { content: [{ type: "text", text: `Failed: ${r.message}` }] };
      const lines = [r.message];
      for (const f of r.failed || []) lines.push(`  ✗ ${f.ref}/${f.pin}: ${f.reason}`);
      for (const w of r.warnings || []) lines.push(`  ⚠ ${w}`);
      return { content: [{ type: "text", text: lines.join("\n") }] };
    },
  );

  // Place + wire in one call
  server.tool(
    "batch_add_and_connect",
    "Place multiple components AND wire their nets in a single call — the fewest-round-trip way to build a subcircuit. Each component is like batch_add_components plus an optional 'nets' map {pin: netName}. Components are placed first, then nets are connected via batch_connect. labelType selects 'label' (sheet-local, default) or 'global_label' (cross-sheet by name) for all the nets wired in this call.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      components: z
        .array(
          z.object({
            symbol: z.string(),
            reference: z.string(),
            value: z.string().optional(),
            footprint: z.string().optional(),
            position: z.object({ x: z.number(), y: z.number() }).optional(),
            rotation: z.number().optional(),
            nets: z
              .record(z.string(), z.string())
              .optional()
              .describe("Map of pin -> netName to label after placement"),
          }),
        )
        .describe("Components to place and connect"),
      labelType: z
        .enum(["label", "global_label"])
        .optional()
        .default("label")
        .describe(
          "Label kind used to wire the nets: 'label' = sheet-local (default); 'global_label' = cross-sheet by name",
        ),
      origin_x: z.number().optional(),
      origin_y: z.number().optional(),
    },
    async (args: any) => {
      const r = await callKicadScript("batch_add_and_connect", args);
      if (r.success === false && r.message)
        return { content: [{ type: "text", text: `Failed: ${r.message}` }] };
      const lines = [r.message];
      for (const e of r.errors || []) lines.push(`  ✗ add ${e.reference}: ${e.error}`);
      for (const f of r.failed_connections || [])
        lines.push(`  ✗ connect ${f.ref}/${f.pin}: ${f.reason}`);
      for (const w of r.warnings || []) lines.push(`  ⚠ ${w}`);
      return { content: [{ type: "text", text: lines.join("\n") }] };
    },
  );
}
