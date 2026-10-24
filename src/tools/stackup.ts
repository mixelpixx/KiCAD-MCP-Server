/**
 * Read-only stackup query for PDN and EMC work.
 *
 * Copper thickness and the dielectric gap are not in get_board_info.
 * This tool returns them with the layer name stored on the board.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

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
}
