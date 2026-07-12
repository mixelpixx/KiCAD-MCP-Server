/**
 * Symbol creator tools for KiCAD MCP server
 *
 * create_symbol              – add a new symbol to a .kicad_sym library
 * delete_symbol              – remove a symbol from a library
 * list_symbols_in_library    – list all symbols in a .kicad_sym file
 * register_symbol_library    – add library to sym-lib-table
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

const PinSchema = z.object({
  name: z.string().describe("Pin name, e.g. 'VCC', 'GND', 'IN+', '~' for unnamed"),
  number: z.union([z.string(), z.number()]).describe("Pin number, e.g. '1', '2', 'A1'"),
  type: z
    .enum([
      "input",
      "output",
      "bidirectional",
      "tri_state",
      "passive",
      "free",
      "unspecified",
      "power_in",
      "power_out",
      "open_collector",
      "open_emitter",
      "no_connect",
    ])
    .describe("Electrical pin type"),
  at: z
    .object({
      x: z.number().describe("X position in mm"),
      y: z.number().describe("Y position in mm"),
      angle: z
        .number()
        .describe(
          "Direction the pin wire extends FROM the symbol body: 0=right, 90=up, 180=left, 270=down",
        ),
    })
    .describe("Pin endpoint position (where the wire connects)"),
  length: z.number().optional().describe("Pin length in mm (default 2.54)"),
  shape: z
    .enum([
      "line",
      "inverted",
      "clock",
      "inverted_clock",
      "input_low",
      "clock_low",
      "output_low",
      "falling_edge_clock",
      "non_logic",
    ])
    .optional()
    .describe("Pin graphic shape (default: line)"),
});

const RectSchema = z.object({
  x1: z.number(),
  y1: z.number(),
  x2: z.number(),
  y2: z.number(),
  width: z.number().optional().describe("Stroke width in mm (default 0.254)"),
  fill: z
    .enum(["none", "outline", "background"])
    .optional()
    .describe("Fill type (default: background)"),
});

const PolylineSchema = z.object({
  points: z.array(z.object({ x: z.number(), y: z.number() })).describe("List of XY points in mm"),
  width: z.number().optional().describe("Stroke width in mm (default 0.254)"),
  fill: z.enum(["none", "outline", "background"]).optional(),
});

export function registerSymbolCreatorTools(server: McpServer, callKicadScript: Function) {
  // ── create_symbol ────────────────────────────────────────────────────── //
  server.tool(
    "create_symbol",
    "Create a new schematic symbol in a .kicad_sym library file (created if missing). " +
      "After creation, use register_symbol_library so KiCAD finds it. " +
      "Pin positions are where the wire connects; the symbol body is drawn between them.\n\n" +
      "Coordinate tips:\n" +
      "- Body rectangle typically spans ±2.54 to ±5.08 mm\n" +
      "- Pins on left side: at.x = body_left - length, angle=0 (wire goes right)\n" +
      "- Pins on right side: at.x = body_right + length, angle=180 (wire goes left)\n" +
      "- Pins on top: at.y = body_top + length, angle=270 (wire goes down)\n" +
      "- Pins on bottom: at.y = body_bottom - length, angle=90 (wire goes up)\n" +
      "- Standard pin length: 2.54 mm, standard grid: 2.54 mm",
    {
      libraryPath: z.string().describe("Path to the .kicad_sym file (created if missing)"),
      name: z.string().describe("Symbol name, e.g. 'TMC2209', 'MyOpAmp'"),
      referencePrefix: z
        .string()
        .optional()
        .describe(
          "Schematic reference prefix: 'U' (IC), 'R' (resistor), 'J' (connector), etc. Default: 'U'",
        ),
      description: z.string().optional().describe("Human-readable description"),
      keywords: z.string().optional().describe("Space-separated search keywords"),
      datasheet: z.string().optional().describe("Datasheet URL or '~'"),
      footprint: z
        .string()
        .optional()
        .describe("Default footprint, e.g. 'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm'"),
      inBom: z.boolean().optional().describe("Include in BOM (default true)"),
      onBoard: z.boolean().optional().describe("Include in netlist for PCB (default true)"),
      pins: z
        .array(PinSchema)
        .optional()
        .describe("List of pins (can be empty for graphical-only symbols)"),
      rectangles: z
        .array(RectSchema)
        .optional()
        .describe("Body rectangle(s). Typically one rectangle defining the IC body."),
      polylines: z
        .array(PolylineSchema)
        .optional()
        .describe("Polyline graphics for custom body shapes (op-amp triangles, etc.)"),
      overwrite: z
        .boolean()
        .optional()
        .describe("Replace existing symbol with same name (default false)"),
    },
    async (args: {
      libraryPath: string;
      name: string;
      referencePrefix?: string;
      description?: string;
      keywords?: string;
      datasheet?: string;
      footprint?: string;
      inBom?: boolean;
      onBoard?: boolean;
      pins?: z.infer<typeof PinSchema>[];
      rectangles?: z.infer<typeof RectSchema>[];
      polylines?: z.infer<typeof PolylineSchema>[];
      overwrite?: boolean;
    }) => {
      const result = await callKicadScript("create_symbol", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ── delete_symbol ────────────────────────────────────────────────────── //
  server.tool(
    "delete_symbol",
    "Remove a symbol from a .kicad_sym library file.",
    {
      libraryPath: z.string().describe("Path to the .kicad_sym file"),
      name: z.string().describe("Symbol name to delete"),
    },
    async (args: { libraryPath: string; name: string }) => {
      const result = await callKicadScript("delete_symbol", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ── list_symbols_in_library ──────────────────────────────────────────── //
  server.tool(
    "list_symbols_in_library",
    "List all symbol names in a .kicad_sym library file.",
    {
      libraryPath: z.string().describe("Path to the .kicad_sym file"),
    },
    async (args: { libraryPath: string }) => {
      const result = await callKicadScript("list_symbols_in_library", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ── register_symbol_library ──────────────────────────────────────────── //
  server.tool(
    "register_symbol_library",
    "Register a .kicad_sym library in KiCAD's sym-lib-table so symbols can be used in schematics. " +
      "Run this after create_symbol when KiCAD shows 'library not found'.",
    {
      libraryPath: z.string().describe("Full path to the .kicad_sym file"),
      libraryName: z
        .string()
        .optional()
        .describe("Nickname (default: file name without extension)"),
      description: z.string().optional(),
      scope: z
        .enum(["project", "global"])
        .optional()
        .describe("project = writes sym-lib-table next to .kicad_pro; global = user config"),
      projectPath: z
        .string()
        .optional()
        .describe("Path to .kicad_pro or its directory (for scope=project)"),
    },
    async (args: {
      libraryPath: string;
      libraryName?: string;
      description?: string;
      scope?: "project" | "global";
      projectPath?: string;
    }) => {
      const result = await callKicadScript("register_symbol_library", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ── add_symbol_property ───────────────────────────────────────────────── //
  server.tool(
    "add_symbol_property",
    "Add or update a custom property (Manufacturer, MPN, LCSC, etc.) on a symbol in a .kicad_sym library file.",
    {
      libraryPath: z.string().describe("Path to the .kicad_sym file"),
      symbolName: z.string().describe("Symbol name"),
      propertyName: z.string().describe("Property name (e.g. Manufacturer, MPN)"),
      propertyValue: z.string().describe("Property value"),
      position: z
        .object({ x: z.number(), y: z.number() })
        .optional()
        .describe("Position {x, y} in mm (default: 0, 0)"),
      hide: z.boolean().optional().describe("Hide the property (default false)"),
    },
    async (args: any) => {
      const r = await callKicadScript("add_symbol_property", args);
      if (r.success === false)
        return { content: [{ type: "text", text: `Failed: ${r.message || "Unknown error"}` }] };
      return { content: [{ type: "text", text: r.message }] };
    },
  );

  // ── import_symbol ─────────────────────────────────────────────────────── //
  server.tool(
    "import_symbol",
    "Copy a symbol from one .kicad_sym library into another, with optional rename and overwrite. " +
      "The target library is created if missing. A derived symbol (one using (extends ...)) needs " +
      "its parent imported into the target first.",
    {
      sourceLibraryPath: z.string().describe("Path to the source .kicad_sym file"),
      symbolName: z.string().describe("Symbol to import"),
      targetLibraryPath: z.string().describe("Path to the target .kicad_sym (created if missing)"),
      newName: z.string().optional().describe("Rename the symbol on import"),
      overwrite: z
        .boolean()
        .optional()
        .default(false)
        .describe("Overwrite if the symbol already exists in the target"),
    },
    async (args: any) => {
      const result = await callKicadScript("import_symbol", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ── export_symbol ─────────────────────────────────────────────────────── //
  server.tool(
    "export_symbol",
    "Extract a single symbol from a .kicad_sym library into a standalone .kicad_sym file.",
    {
      libraryPath: z.string().describe("Path to the source .kicad_sym file"),
      symbolName: z.string().describe("Symbol to export"),
      outputPath: z.string().describe("Path for the output .kicad_sym file"),
    },
    async (args: any) => {
      const result = await callKicadScript("export_symbol", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ── rename_symbol ─────────────────────────────────────────────────────── //
  server.tool(
    "rename_symbol",
    "Rename a symbol in a .kicad_sym library, including its sub-symbol shards (name_0_1, ...) and " +
      "any (extends ...) references from derived symbols in the same library. Note: schematics that " +
      "already place the old lib_id are NOT updated — use replace_instance_lib_ids for that.",
    {
      libraryPath: z.string().describe("Path to the .kicad_sym file"),
      oldName: z.string().describe("Current symbol name"),
      newName: z.string().describe("New symbol name"),
    },
    async (args: any) => {
      const result = await callKicadScript("rename_symbol", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );
}
