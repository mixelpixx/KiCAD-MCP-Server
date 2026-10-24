/**
 * Stackup query and edit for PDN and EMC work.
 *
 * Copper thickness and the dielectric gap are not in get_board_info.
 * get_stackup returns them. set_stackup_layer writes one row.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

function textResult(result: unknown) {
  return {
    content: [
      {
        type: "text" as const,
        text: JSON.stringify(result, null, 2),
      },
    ],
  };
}

export function registerStackupTools(server: McpServer, callKicadScript: CommandFunction): void {
  server.tool(
    "get_stackup",
    "Read the board stackup. Returns each copper, dielectric, mask, and silk entry with its thickness in millimetres. Layer names are the names stored on the board, so a renamed layer such as 'Top Side' is returned beside the canonical F.Cu name.",
    {},
    async (args) => textResult(await callKicadScript("get_stackup", args)),
  );

  server.tool(
    "set_stackup_layer",
    "Set the thickness of one stackup row, and for a dielectric its material, relative permittivity, and loss tangent. Identify the row by index from get_stackup or by a layer name such as F.Cu or the name stored on the board. Only the fields you pass are changed. sublayer selects a dielectric piece and defaults to 0.",
    {
      index: z.number().int().nonnegative().optional().describe("Row index from get_stackup"),
      layer: z
        .string()
        .optional()
        .describe("Canonical name such as F.Cu, or the name stored on the board"),
      sublayer: z
        .number()
        .int()
        .nonnegative()
        .optional()
        .describe("Dielectric sublayer. Defaults to 0"),
      thicknessMm: z
        .number()
        .positive()
        .optional()
        .describe("Thickness of this sublayer in millimetres"),
      epsilonR: z
        .number()
        .positive()
        .optional()
        .describe("Relative permittivity. Dielectric rows only"),
      lossTangent: z
        .number()
        .nonnegative()
        .optional()
        .describe("Loss tangent. Dielectric rows only"),
      material: z.string().optional().describe("Material name. Dielectric rows only"),
    },
    async (args) => textResult(await callKicadScript("set_stackup_layer", args)),
  );
}
