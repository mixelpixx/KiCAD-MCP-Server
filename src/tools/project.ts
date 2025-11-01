/**
 * Project management tools for KiCAD MCP server
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';

export function registerProjectTools(server: McpServer, callKicadScript: Function) {
  // Create project tool
  server.tool(
    "create_project",
    "Create a new KiCAD project",
    {
      path: z.string().describe("Project directory path"),
      name: z.string().describe("Project name"),
    },
    async (args: { path: string; name: string }) => {
      const result = await callKicadScript("create_project", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // Open project tool
  server.tool(
    "open_project",
    "Open an existing KiCAD project",
    {
      filename: z.string().describe("Path to .kicad_pro or .kicad_pcb file"),
    },
    async (args: { filename: string }) => {
      const result = await callKicadScript("open_project", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // Save project tool
  server.tool(
    "save_project",
    "Save the current KiCAD project",
    {
      path: z.string().optional().describe("Optional new path to save to"),
    },
    async (args: { path?: string }) => {
      const result = await callKicadScript("save_project", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // Get project info tool
  server.tool(
    "get_project_info",
    "Get information about the current KiCAD project",
    {},
    async () => {
      const result = await callKicadScript("get_project_info", {});
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );
}
