import { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";
import { registerKiCadTool, type CommandFunction, withToolSignal } from "./tool-registration.js";

export function registerPcbImportTools(server: McpServer, callKicadScript: CommandFunction): void {
  callKicadScript = withToolSignal(callKicadScript);
  registerKiCadTool(
    server,
    "pcb_import",
    "import_pcb",
    {
      description:
        "Import a vendor PCB file (PADS, Altium, Eagle, CADSTAR, Fabmaster, P-CAD, SolidWorks PCB, " +
        "or a binary Cadence Allegro .brd) and convert it to a KiCad .kicad_pcb file via kicad-cli's " +
        "native pcb importer. Binary Cadence Allegro .brd files must use format 'auto' (kicad-cli " +
        "auto-detects the Allegro binary format; there is no 'allegro' format literal). This only " +
        "imports PCB/layout data — it does not import schematics.",
      inputSchema: z.object({
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
      }),
      annotations: {
        readOnlyHint: false,
        destructiveHint: true,
        idempotentHint: false,
        openWorldHint: false,
      },
    },
    async (args: {
      inputFile: string;
      outputFile?: string;
      format?: string;
      reportFormat?: string;
    }) => {
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
