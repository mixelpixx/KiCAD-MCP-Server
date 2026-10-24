/**
 * Per-net copper counts: tracks, vias, and zones, without dumping them.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

export function registerNetCopperTools(server: McpServer, callKicadScript: CommandFunction): void {
  server.tool(
    "summarize_net_copper",
    "Summarize one net's copper without listing every track, via, and zone. Returns the three counts, the layers involved, the bounding box, and a shape: vias_only, tracks_only, zones_only, empty, or mixed. vias_only means the net has vias and neither tracks nor zones.",
    {
      net: z.string().describe("Net name, for example GND or NetL2_1"),
    },
    async (args) => {
      const result = await callKicadScript("summarize_net_copper", args);
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
