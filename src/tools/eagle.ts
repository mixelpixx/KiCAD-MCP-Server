import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerEagleTools(server: McpServer, callKicadScript: Function) {
  server.tool(
    "import_eagle_project",
    "Import an Eagle project (.brd + .sch) and convert it to a KiCad project. " +
      "Converts the PCB layout via kicad-cli and translates the schematic from Eagle XML to KiCad S-expression format.",
    {
      board_file: z.string().describe("Absolute path to the Eagle .brd board file"),
      schematic_file: z
        .string()
        .optional()
        .describe("Absolute path to the Eagle .sch schematic file (auto-detected from .brd path if omitted)"),
      output_dir: z
        .string()
        .optional()
        .describe("Output directory for the KiCad project (defaults to a subdirectory next to the .brd file)"),
      project_name: z
        .string()
        .optional()
        .describe("KiCad project name (defaults to the .brd filename without extension)"),
    },
    async (args: {
      board_file: string;
      schematic_file?: string;
      output_dir?: string;
      project_name?: string;
    }) => {
      const result = await callKicadScript("import_eagle_project", args);
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );
}
