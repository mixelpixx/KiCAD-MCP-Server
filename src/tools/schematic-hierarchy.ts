/**
 * Schematic hierarchy tools: insert a hierarchical sheet, scaffold a sub-sheet.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerSchematicHierarchyTools(server: McpServer, callKicadScript: Function) {
  // Link an existing sub-sheet into a parent
  server.tool(
    "add_hierarchical_sheet",
    "Insert a hierarchical-sheet reference block into a parent schematic, pointing at an existing sub-sheet file. Adds the sheet box, name/file fields, a sheet_instances path entry on the next page number, and fixes sub-sheet component instance paths so ERC resolves references.",
    {
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
  server.tool(
    "remove_hierarchical_sheet",
    "Remove a hierarchical-sheet reference from a parent schematic (the reverse of add_hierarchical_sheet). Identify the sheet by sheetName (matches the sheet's name property) or by subsheetPath (matched by basename against the sheet's file property). Deletes the (sheet ...) block and any matching (sheet_instances) page entry. Does NOT delete the sub-sheet .kicad_sch file on disk.",
    {
      schematicPath: z.string().describe("Path to the parent .kicad_sch"),
      sheetName: z
        .string()
        .optional()
        .describe("Sheet display name to remove (matches the Sheetname/Sheet name property)"),
      subsheetPath: z
        .string()
        .optional()
        .describe("Sub-sheet file to remove (matched by basename against the Sheetfile property)"),
    },
    async (args: any) => {
      const r = await callKicadScript("remove_hierarchical_sheet", args);
      if (!r.success)
        return { content: [{ type: "text", text: `Failed: ${r.message || "Unknown error"}` }] };
      return { content: [{ type: "text", text: r.message }] };
    },
  );

  // Create a sub-sheet file AND link it in one call
  server.tool(
    "create_hierarchical_subsheet",
    "Create a new sub-sheet .kicad_sch file and link it into a parent schematic in a single call (create_schematic + add_hierarchical_sheet). The fastest way to grow a hierarchical design.",
    {
      parentSchematicPath: z.string().describe("Path to the parent .kicad_sch"),
      subsheetPath: z.string().describe("Path for the new sub-sheet .kicad_sch to create"),
      sheetName: z.string().optional().default("Sheet").describe("Display name for the sheet"),
      position: z.object({ x: z.number(), y: z.number() }).optional(),
      size: z.object({ width: z.number(), height: z.number() }).optional(),
      metadata: z
        .record(z.string(), z.any())
        .optional()
        .describe("Optional metadata for the new sub-sheet (title, etc.)"),
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
