/**
 * Read-only stackup query for PDN and EMC work.
 *
 * Copper thickness and the dielectric gap are not in get_board_info.
 * This tool returns them with the layer name stored on the board.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

export function registerStackupTools(server: McpServer, callKicadScript: CommandFunction): void {
  server.tool(
    "get_stackup",
    "Read the board stackup. Returns each copper, dielectric, mask, and silk entry with its thickness in millimetres. Layer names are the names stored on the board, so a renamed layer such as 'Top Side' is returned beside the canonical F.Cu name.",
    {},
    async (args) => {
      const result = await callKicadScript("get_stackup", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  server.tool(
    "check_stackup",
    "Compare the board stackup with a recipe. Each expected row names a layer by index or by name and may give type, thicknessMm, and epsilonR. thicknessToleranceMm defaults to 0.001 mm and epsilonTolerance defaults to 0.01. The result lists every field that is outside its tolerance.",
    {
      expected: z
        .array(
          z.object({
            index: z.number().int().nonnegative().optional().describe("Row index from get_stackup"),
            layer: z
              .string()
              .optional()
              .describe("Canonical name such as F.Cu, or the name stored on the board"),
            type: z
              .enum(["copper", "dielectric", "soldermask", "solderpaste", "silkscreen"])
              .optional()
              .describe("Expected row type"),
            thicknessMm: z.number().optional().describe("Expected thickness in millimetres"),
            epsilonR: z.number().optional().describe("Expected relative permittivity"),
          }),
        )
        .min(1)
        .describe("Rows to compare. Each row needs index or layer"),
      thicknessToleranceMm: z
        .number()
        .nonnegative()
        .optional()
        .describe("Allowed thickness difference in millimetres. Default 0.001"),
      epsilonTolerance: z
        .number()
        .nonnegative()
        .optional()
        .describe("Allowed relative-permittivity difference. Default 0.01"),
    },
    async (args) => {
      const result = await callKicadScript("check_stackup", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );
}
