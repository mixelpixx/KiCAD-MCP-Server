/**
 * Footprints whose body anchor or a pad lies inside a board rectangle.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

export function registerFootprintsInRegionTools(
  server: McpServer,
  callKicadScript: CommandFunction,
): void {
  server.tool(
    "get_footprints_in_region",
    "List footprints inside a board rectangle. A footprint is included when its anchor or any pad centre lies inside the box. Each hit returns the reference, value, position, layer name stored on the board, and the net of every pad. This is the PCB query a shield-can review needs; the schematic region query does not see the board.",
    {
      boundingBox: z
        .object({
          x1: z.number(),
          y1: z.number(),
          x2: z.number(),
          y2: z.number(),
          unit: z.enum(["mm", "mil", "inch"]).optional(),
        })
        .describe("Inclusive rectangle in board coordinates. unit defaults to mm."),
    },
    async (args) => {
      const result = await callKicadScript("get_footprints_in_region", args);
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
