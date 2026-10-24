/**
 * Via census for PDN review. Returns counts, not every via.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

const boundingBox = z
  .object({
    x1: z.number(),
    y1: z.number(),
    x2: z.number(),
    y2: z.number(),
    unit: z.enum(["mm", "mil", "inch"]).optional(),
  })
  .describe("Rectangle. Only vias whose centre lies inside are counted.");

export function registerSummarizeViasTools(
  server: McpServer,
  callKicadScript: CommandFunction,
): void {
  server.tool(
    "summarize_vias",
    "Count vias on the board without listing them. Returns the via count, how many run from F.Cu to B.Cu, a drill histogram, and the layer spans. Filter by net, rectangle, drill, or layer name. A stitched ground net can hold thousands of vias; this summary is the census a PDN review needs.",
    {
      net: z.string().optional().describe("Only vias on this net, for example GND"),
      boundingBox: boundingBox.optional(),
      drillMin: z.number().optional().describe("Minimum drill diameter in millimetres, inclusive"),
      drillMax: z.number().optional().describe("Maximum drill diameter in millimetres, inclusive"),
      startLayer: z
        .string()
        .optional()
        .describe("Match the via start layer by the board's name or the canonical name"),
      endLayer: z
        .string()
        .optional()
        .describe("Match the via end layer by the board's name or the canonical name"),
    },
    async (args) => {
      const result = await callKicadScript("summarize_vias", args);
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
