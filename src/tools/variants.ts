import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { formatKicadResult } from "./tool-response.js";

const projectPath = z.string().min(1).describe("Path to the saved .kicad_pro project file");
const variant = z.string().min(1).describe("Registered assembly variant name");
const component = {
  projectPath,
  schematicPath: z.string().min(1).describe("Path to the .kicad_sch containing the component"),
  reference: z.string().min(1).describe("Component reference, e.g. R1"),
  variant,
};

export function registerVariantTools(
  server: McpServer,
  callKicadScript: (command: string, args: Record<string, unknown>) => Promise<unknown>,
): void {
  server.tool(
    "list_variants",
    "List the assembly variants registered in a KiCad project.",
    { projectPath },
    async (args) => formatKicadResult(await callKicadScript("list_variants", args)),
  );
  server.tool(
    "create_variant",
    "Register a named assembly variant in a KiCad project.",
    { projectPath, name: z.string().min(1), description: z.string().optional() },
    async (args) => formatKicadResult(await callKicadScript("create_variant", args)),
  );
  server.tool(
    "get_component_variant",
    "Read a component's DNP and field overrides for an assembly variant.",
    component,
    async (args) => formatKicadResult(await callKicadScript("get_component_variant", args)),
  );
  server.tool(
    "set_component_variant",
    "Set or remove a component's DNP and field overrides for an assembly variant.",
    {
      ...component,
      dnp: z.boolean().optional().describe("Override do-not-populate for this variant"),
      fields: z
        .record(z.string().nullable())
        .optional()
        .describe("Field overrides by name; null removes that field's override"),
      reset: z.boolean().optional().describe("Remove all overrides for this component and variant"),
    },
    async (args) => formatKicadResult(await callKicadScript("set_component_variant", args)),
  );
  server.tool(
    "export_variant_bom",
    "Export the bill of materials for a named assembly variant.",
    {
      projectPath,
      variant,
      outputPath: z.string().min(1).describe("Path for the output CSV file"),
      excludeDnp: z
        .boolean()
        .optional()
        .describe("Exclude do-not-populate components from the BOM"),
    },
    async (args) => formatKicadResult(await callKicadScript("export_variant_bom", args)),
  );
}
