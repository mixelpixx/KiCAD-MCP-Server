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

  // ============================================================
  // NEW TOOLS - Previously in Python but not exposed via MCP
  // ============================================================

  // Delete trace tool
  server.tool(
    "delete_trace",
    "Delete traces from the PCB by UUID, position, or net name. Can bulk-delete all traces on a net.",
    {
      traceUuid: z.string().optional().describe("UUID of specific trace to delete"),
      position: z.object({
        x: z.number(),
        y: z.number(),
        unit: z.enum(["mm", "inch"])
      }).optional().describe("Position to find and delete nearest trace"),
      net: z.string().optional().describe("Net name to delete all traces on (bulk delete)"),
      layer: z.string().optional().describe("Optional layer filter when deleting by net"),
      includeVias: z.boolean().optional().describe("Whether to also delete vias (default false)")
    },
    async (args: any) => {
      const result = await callKicadScript("delete_trace", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // Delete all traces tool
  server.tool(
    "delete_all_traces",
    "Delete ALL traces and optionally all vias from the PCB. Use with caution - this removes all routing.",
    {
      includeVias: z.boolean().optional().describe("Whether to also delete all vias (default true)"),
      net: z.string().optional().describe("Optional: only delete traces on this specific net")
    },
    async (args: any) => {
      const result = await callKicadScript("delete_all_traces", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // Query traces tool
  server.tool(
    "query_traces",
    "Query and list traces on the PCB, filtered by net, layer, or bounding box",
    {
      net: z.string().optional().describe("Filter by net name"),
      layer: z.string().optional().describe("Filter by layer name"),
      boundingBox: z.object({
        x1: z.number(),
        y1: z.number(),
        x2: z.number(),
        y2: z.number(),
        unit: z.enum(["mm", "inch"])
      }).optional().describe("Filter by bounding box region"),
      includeVias: z.boolean().optional().describe("Whether to include vias in results")
    },
    async (args: any) => {
      const result = await callKicadScript("query_traces", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // Modify trace tool
  server.tool(
    "modify_trace",
    "Modify properties of an existing trace (width, layer, net). Find by UUID or position.",
    {
      uuid: z.string().optional().describe("UUID of trace to modify"),
      position: z.object({
        x: z.number(),
        y: z.number(),
        unit: z.enum(["mm", "inch"])
      }).optional().describe("Position to find nearest trace"),
      width: z.number().optional().describe("New trace width in mm"),
      layer: z.string().optional().describe("New layer"),
      net: z.string().optional().describe("New net name")
    },
    async (args: any) => {
      const result = await callKicadScript("modify_trace", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // Get nets list tool
  server.tool(
    "get_nets_list",
    "Get a list of all nets in the PCB with their names, codes, and classes",
    {},
    async () => {
      const result = await callKicadScript("get_nets_list", {});
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // Refill zones tool
  server.tool(
    "refill_zones",
    "Refill all copper pour zones on the board. Equivalent to pressing 'B' in KiCAD or Edit > Fill All Zones.",
    {},
    async () => {
      const result = await callKicadScript("refill_zones", {});
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );
}
