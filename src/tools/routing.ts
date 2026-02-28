/**
 * Routing tools for KiCAD MCP server
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerRoutingTools(
  server: McpServer,
  callKicadScript: Function,
) {
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
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  // Route trace tool
  server.tool(
    "route_trace",
    "Route a trace between two points",
    {
      start: z
        .object({
          x: z.number(),
          y: z.number(),
          unit: z.string().optional(),
        })
        .describe("Start position"),
      end: z
        .object({
          x: z.number(),
          y: z.number(),
          unit: z.string().optional(),
        })
        .describe("End position"),
      layer: z.string().describe("PCB layer"),
      width: z.number().describe("Trace width in mm"),
      net: z.string().describe("Net name"),
    },
    async (args: any) => {
      const result = await callKicadScript("route_trace", args);
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

  // Add via tool
  server.tool(
    "add_via",
    "Add a via to the PCB",
    {
      position: z
        .object({
          x: z.number(),
          y: z.number(),
          unit: z.string().optional(),
        })
        .describe("Via position"),
      net: z.string().describe("Net name"),
      viaType: z
        .string()
        .optional()
        .describe("Via type (through, blind, buried)"),
    },
    async (args: any) => {
      const result = await callKicadScript("add_via", args);
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
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  // Delete trace tool
  server.tool(
    "delete_trace",
    "Delete traces from the PCB. Can delete by UUID, position, or bulk-delete all traces on a net.",
    {
      traceUuid: z
        .string()
        .optional()
        .describe("UUID of a specific trace to delete"),
      position: z
        .object({
          x: z.number(),
          y: z.number(),
          unit: z.enum(["mm", "inch"]).optional(),
        })
        .optional()
        .describe("Delete trace nearest to this position"),
      net: z
        .string()
        .optional()
        .describe("Delete all traces on this net (bulk delete)"),
      layer: z
        .string()
        .optional()
        .describe("Filter by layer when using net-based deletion"),
      includeVias: z
        .boolean()
        .optional()
        .describe("Include vias in net-based deletion"),
    },
    async (args: any) => {
      const result = await callKicadScript("delete_trace", args);
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

  // Query traces tool
  server.tool(
    "query_traces",
    "Query traces on the board with optional filters by net, layer, or bounding box.",
    {
      net: z.string().optional().describe("Filter by net name"),
      layer: z.string().optional().describe("Filter by layer name"),
      boundingBox: z
        .object({
          x1: z.number(),
          y1: z.number(),
          x2: z.number(),
          y2: z.number(),
          unit: z.enum(["mm", "inch"]).optional(),
        })
        .optional()
        .describe("Filter by bounding box region"),
      unit: z.enum(["mm", "inch"]).optional().describe("Unit for coordinates"),
    },
    async (args: any) => {
      const result = await callKicadScript("query_traces", args);
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

  // Get nets list tool
  server.tool(
    "get_nets_list",
    "Get a list of all nets in the PCB with optional statistics.",
    {
      includeStats: z
        .boolean()
        .optional()
        .describe("Include statistics (track count, total length, etc.)"),
      unit: z
        .enum(["mm", "inch"])
        .optional()
        .describe("Unit for length measurements"),
    },
    async (args: any) => {
      const result = await callKicadScript("get_nets_list", args);
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

  // Modify trace tool
  server.tool(
    "modify_trace",
    "Modify an existing trace (change width, layer, or net).",
    {
      traceUuid: z.string().describe("UUID of the trace to modify"),
      width: z.number().optional().describe("New trace width in mm"),
      layer: z.string().optional().describe("New layer name"),
      net: z.string().optional().describe("New net name"),
    },
    async (args: any) => {
      const result = await callKicadScript("modify_trace", args);
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

  // Create netclass tool
  server.tool(
    "create_netclass",
    "Create a new net class with custom design rules.",
    {
      name: z.string().describe("Net class name"),
      traceWidth: z.number().optional().describe("Default trace width in mm"),
      clearance: z.number().optional().describe("Clearance in mm"),
      viaDiameter: z.number().optional().describe("Via diameter in mm"),
      viaDrill: z.number().optional().describe("Via drill size in mm"),
    },
    async (args: any) => {
      const result = await callKicadScript("create_netclass", args);
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

  // Route differential pair tool
  server.tool(
    "route_differential_pair",
    "Route a differential pair between two sets of points.",
    {
      positivePad: z
        .object({
          reference: z.string(),
          pad: z.string(),
        })
        .describe("Positive pad (component and pad number)"),
      negativePad: z
        .object({
          reference: z.string(),
          pad: z.string(),
        })
        .describe("Negative pad (component and pad number)"),
      layer: z.string().describe("PCB layer"),
      width: z.number().describe("Trace width in mm"),
      gap: z.number().describe("Gap between traces in mm"),
      positiveNet: z.string().describe("Positive net name"),
      negativeNet: z.string().describe("Negative net name"),
    },
    async (args: any) => {
      const result = await callKicadScript("route_differential_pair", args);
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

  // Refill zones tool
  server.tool(
    "refill_zones",
    "Refill all copper zones on the board. WARNING: SWIG path has known segfault risk (see KNOWN_ISSUES.md). Prefer using IPC backend (KiCAD open) or triggering zone fill via KiCAD UI instead.",
    {},
    async (args: any) => {
      const result = await callKicadScript("refill_zones", args);
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
