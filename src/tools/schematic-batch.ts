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

  // Refresh lib_symbols cache from library (Update Symbol from Library)
  server.tool(
    "update_symbol_from_library",
    "Refresh embedded lib_symbols cache entries from a KiCad symbol library (equivalent to KiCad's Update Symbol from Library). Skips mirror-cache entries (__m0, __m90, …). Flattens (power) symbols for schematic format. Pass projectsDir to update all schematics in a folder, or schematicPath for one file.",
    {
      projectsDir: z
        .string()
        .optional()
        .describe("Directory containing project subfolders with .kicad_sch files"),
      schematicPath: z.string().optional().describe("Single .kicad_sch file to update"),
      schematicPaths: z.array(z.string()).optional().describe("Multiple .kicad_sch files"),
      libraryName: z
        .string()
        .describe("Symbol library nickname from sym-lib-table (e.g. Device, project_lib)"),
      symbols: z
        .array(z.string())
        .optional()
        .describe("Optional: update only these symbol names (without Library: prefix)"),
      repairMirrorFromBackup: z
        .boolean()
        .optional()
        .default(false)
        .describe("Restore __m* mirror-cache lib_symbols blocks from backupDir first"),
      backupDir: z
        .string()
        .optional()
        .describe("Backup folder with matching .kicad_sch filenames (for repairMirrorFromBackup)"),
    },
    async (args: any) => {
      const r = await callKicadScript("update_symbol_from_library", args);
      if (r.success === false)
        return { content: [{ type: "text", text: `Failed: ${r.message || "Unknown error"}` }] };
      const lines = [r.message];
      for (const item of r.results || []) {
        const parts = [];
        if (item.updated) parts.push(`${item.updated} updated`);
        if (item.injected) parts.push(`${item.injected} injected`);
        if (item.mirror_restored) parts.push(`${item.mirror_restored} mirror restored`);
        lines.push(`  ${item.schematic}: ${parts.join(", ") || "unchanged"}`);
      }
      return { content: [{ type: "text", text: lines.join("\n") }] };
    },
  );

  // Add/update a custom property on a lib_symbols definition
  server.tool(
    "add_library_symbol_property",
    "Add or update a custom property (Manufacturer, MPN, LCSC, etc.) on a symbol definition in the lib_symbols section. This makes the property available to all instances of that symbol in the schematic.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      libraryName: z.string().describe("Symbol library nickname (e.g. Device, power)"),
      symbolName: z.string().describe("Symbol name (e.g. R, C, GND)"),
      propertyName: z.string().describe("Property name (e.g. Manufacturer, MPN)"),
      propertyValue: z.string().describe("Property value"),
      position: z
        .object({ x: z.number(), y: z.number() })
        .optional()
        .describe("Position {x, y} in mm (default: 0, 0)"),
      hide: z.boolean().optional().describe("Hide the property (default false)"),
    },
    async (args: any) => {
      const r = await callKicadScript("add_library_symbol_property", args);
      if (r.success === false)
        return { content: [{ type: "text", text: `Failed: ${r.message || "Unknown error"}` }] };
      return { content: [{ type: "text", text: r.message }] };
    },
  );

  // Replace instance lib_ids per mapping (library migration)
  server.tool(
    "replace_instance_lib_ids",
    "Replace lib_id references in schematic symbol instances per an explicit old-to-new mapping — the mechanical layer of a library migration (e.g. eagle_import symbols to curated library symbols). Mirror-variant suffixes (__m0/__m90/__m180/__m270) get automatic angle correction; each needs its own mapping entry. Only instances are rewritten; lib_symbols is preserved (use update_symbol_from_library to refresh definitions afterwards).",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      mapping: z
        .record(z.string())
        .describe(
          'Map of old full lib_id to new full lib_id, e.g. {"eagle_import:C_100n": "Device:C"}. Values are used verbatim.',
        ),
      sourceLibrary: z
        .string()
        .optional()
        .default("eagle_import")
        .describe("Library prefix whose instances are candidates"),
    },
    async (args: any) => {
      const r = await callKicadScript("replace_instance_lib_ids", args);
      if (r.success === false)
        return { content: [{ type: "text", text: `Failed: ${r.error || r.message || "Unknown error"}` }] };
      return { content: [{ type: "text", text: r.message }] };
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
