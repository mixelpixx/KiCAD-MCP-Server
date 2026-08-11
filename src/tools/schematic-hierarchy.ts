/**
 * Schematic hierarchy tools: insert a hierarchical sheet, scaffold a sub-sheet.
 */
import { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";
import { registerKiCadTool, type CommandFunction, withToolSignal } from "./tool-registration.js";

export function registerSchematicHierarchyTools(
  server: McpServer,
  callKicadScript: CommandFunction,
) {
  callKicadScript = withToolSignal(callKicadScript);
  // Link an existing sub-sheet into a parent
  registerKiCadTool(
    server,
    "schematic_hierarchy",
    "add_hierarchical_sheet",
    {
      description:
        "Insert a hierarchical-sheet reference block into a parent schematic, pointing at an existing sub-sheet file. Adds the sheet box, name/file fields, a sheet_instances path entry on the next page number, and fixes sub-sheet component instance paths so ERC resolves references.",
      inputSchema: z.object({
        schematicPath: z.string().describe("Path to the parent .kicad_sch"),
        subsheetPath: z.string().describe("Path to the existing sub-sheet .kicad_sch to reference"),
        sheetName: z.string().optional().default("Sheet").describe("Display name for the sheet"),
        position: z
          .object({ x: z.number(), y: z.number() })
          .optional()
          .describe("Top-left of the sheet box in mm (default 50,50)"),
        size: z
          .object({ width: z.number(), height: z.number() })
          .optional()
          .describe("Sheet box size in mm (default 80x50)"),
      }),
    },
    async (args: any) => {
      const r = await callKicadScript("add_hierarchical_sheet", args);
      if (!r.success)
        return { content: [{ type: "text", text: `Failed: ${r.message || "Unknown error"}` }] };
      return {
        content: [
          {
            type: "text",
            text: `Added sheet '${r.sheet_name}' -> ${r.subsheet_path} (page ${r.page})`,
          },
        ],
      };
    },
  );

  // Remove a hierarchical sheet reference from a parent
  registerKiCadTool(
    server,
    "schematic_hierarchy",
    "remove_hierarchical_sheet",
    {
      description:
        "Remove a hierarchical-sheet reference from a parent schematic (the reverse of add_hierarchical_sheet). Identify the sheet by sheetName (matches the sheet's name property) or by subsheetPath (matched by basename against the sheet's file property). Deletes the (sheet ...) block and any matching (sheet_instances) page entry. Does NOT delete the sub-sheet .kicad_sch file on disk.",
      inputSchema: z.object({
        schematicPath: z.string().describe("Path to the parent .kicad_sch"),
        sheetName: z
          .string()
          .optional()
          .describe("Sheet display name to remove (matches the Sheetname/Sheet name property)"),
        subsheetPath: z
          .string()
          .optional()
          .describe(
            "Sub-sheet file to remove (matched by basename against the Sheetfile property)",
          ),
      }),
    },
    async (args: any) => {
      const r = await callKicadScript("remove_hierarchical_sheet", args);
      if (!r.success)
        return { content: [{ type: "text", text: `Failed: ${r.message || "Unknown error"}` }] };
      return { content: [{ type: "text", text: r.message }] };
    },
  );

  // Set a custom property on a hierarchical sheet
  registerKiCadTool(
    server,
    "schematic_hierarchy",
    "set_sheet_property",
    {
      description:
        "Add or update a custom property on a hierarchical sheet's (sheet ...) block — e.g. cell identity or generator parameters carried as sheet metadata. Identify the sheet by sheetName or sheetPath (basename match against the sheet's file property). The property is created hidden if absent, otherwise its value is updated in place; the file's formatting is preserved. The built-in 'Sheet name'/'Sheet file' properties cannot be set here — use add/remove_hierarchical_sheet to manage the sheet link.",
      inputSchema: z.object({
        schematicPath: z.string().describe("Path to the parent .kicad_sch"),
        sheetName: z
          .string()
          .optional()
          .describe("Sheet display name (matches the Sheetname/Sheet name property)"),
        sheetPath: z
          .string()
          .optional()
          .describe("Sub-sheet file (matched by basename against the Sheetfile property)"),
        key: z.string().describe("Property name (e.g. 'IS.Cell')"),
        value: z.string().describe("Property value"),
      }),
    },
    async (args: any) => {
      const r = await callKicadScript("set_sheet_property", args);
      if (!r.success)
        return { content: [{ type: "text", text: `Failed: ${r.message || "Unknown error"}` }] };
      return { content: [{ type: "text", text: r.message }] };
    },
  );

  // List hierarchical sheets and their properties
  registerKiCadTool(
    server,
    "schematic_hierarchy",
    "get_sheet_properties",
    {
      description:
        "List hierarchical sheets in a schematic with their name, file, uuid, position, and full property map (built-ins plus custom properties set via set_sheet_property). With sheetName or sheetPath, returns just that sheet.",
      inputSchema: z.object({
        schematicPath: z.string().describe("Path to the parent .kicad_sch"),
        sheetName: z.string().optional().describe("Only this sheet (by display name)"),
        sheetPath: z.string().optional().describe("Only this sheet (by file basename)"),
      }),
    },
    async (args: any) => {
      const r = await callKicadScript("get_sheet_properties", args);
      if (!r.success)
        return { content: [{ type: "text", text: `Failed: ${r.message || "Unknown error"}` }] };
      return {
        content: [{ type: "text", text: JSON.stringify(r.sheets, null, 2) }],
      };
    },
  );

  // Create a sub-sheet file AND link it in one call
  registerKiCadTool(
    server,
    "schematic_hierarchy",
    "create_hierarchical_subsheet",
    {
      description:
        "Create a new sub-sheet .kicad_sch file and link it into a parent schematic in a single call (create_schematic + add_hierarchical_sheet). The fastest way to grow a hierarchical design.",
      inputSchema: z.object({
        parentSchematicPath: z.string().describe("Path to the parent .kicad_sch"),
        subsheetPath: z.string().describe("Path for the new sub-sheet .kicad_sch to create"),
        sheetName: z.string().optional().default("Sheet").describe("Display name for the sheet"),
        position: z.object({ x: z.number(), y: z.number() }).optional(),
        size: z.object({ width: z.number(), height: z.number() }).optional(),
        metadata: z
          .record(z.string(), z.any())
          .optional()
          .describe("Optional metadata for the new sub-sheet (title, etc.)"),
      }),
    },
    async (args: any) => {
      const r = await callKicadScript("create_hierarchical_subsheet", args);
      return {
        content: [
          { type: "text", text: r.success ? r.message : `Failed: ${r.message || "Unknown error"}` },
        ],
      };
    },
  );
}
