import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerPcbImportTools(server: McpServer, callKicadScript: Function) {
  server.tool(
    "import_pcb",
    "Import a vendor PCB file (PADS, Altium, Eagle, CADSTAR, Fabmaster, P-CAD, SolidWorks PCB, " +
      "or a binary Cadence Allegro .brd) and convert it to a KiCad .kicad_pcb file via kicad-cli's " +
      "native pcb importer. Binary Cadence Allegro .brd files must use format 'auto' (kicad-cli " +
      "auto-detects the Allegro binary format; there is no 'allegro' format literal). This only " +
      "imports PCB/layout data — it does not import schematics.",
    {
      inputFile: z.string().describe("Absolute path to the vendor PCB file to import"),
      outputFile: z
        .string()
        .optional()
        .describe("Destination .kicad_pcb path (defaults beside inputFile, same basename)"),
      format: z
        .enum(["auto", "pads", "altium", "eagle", "cadstar", "fabmaster", "pcad", "solidworks"])
        .optional()
        .describe(
          "Input format hint (default 'auto'). Use 'auto' for binary Cadence Allegro .brd files — " +
            "there is no 'allegro' literal in this enum.",
        ),
      reportFormat: z
        .enum(["none", "json", "text"])
        .optional()
        .describe("Capture a structured import report from kicad-cli (default 'none')"),
    },
    async (args: { inputFile: string; outputFile?: string; format?: string; reportFormat?: string }) => {
      const result = await callKicadScript("import_pcb", args);
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
