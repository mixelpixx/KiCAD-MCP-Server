/**
 * Routing tools for KiCAD MCP server
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';

export function registerRoutingTools(server: McpServer, callKicadScript: Function) {
  // Add net tool
  server.tool(
    "add_net",
    "Create a new net on the PCB",
    {
      name: z.string().describe("Net name"),
      netClass: z.string().optional().describe("Net class name"),
    },
    async (args: { name: string; netClass?: string }) => {
      const result = await callKicadScript("add_net", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // Route trace tool
  server.tool(
    "route_trace",
    "Route a trace between two points",
    {
      start: z.object({
        x: z.number(),
        y: z.number(),
        unit: z.string().optional()
      }).describe("Start position"),
      end: z.object({
        x: z.number(),
        y: z.number(),
        unit: z.string().optional()
      }).describe("End position"),
      layer: z.string().describe("PCB layer"),
      width: z.number().describe("Trace width in mm"),
      net: z.string().describe("Net name"),
    },
    async (args: any) => {
      const result = await callKicadScript("route_trace", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // Add via tool
  server.tool(
    "add_via",
    "Add a via to the PCB",
    {
      position: z.object({
        x: z.number(),
        y: z.number(),
        unit: z.string().optional()
      }).describe("Via position"),
      net: z.string().describe("Net name"),
      viaType: z.string().optional().describe("Via type (through, blind, buried)"),
    },
    async (args: any) => {
      const result = await callKicadScript("add_via", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // Add copper pour tool
  server.tool(
    "add_copper_pour",
    "Add a copper pour (ground/power plane) to the PCB",
    {
      layer: z.string().describe("PCB layer"),
      net: z.string().describe("Net name"),
      clearance: z.number().optional().describe("Clearance in mm"),
    },
    async (args: any) => {
      const result = await callKicadScript("add_copper_pour", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );
}
