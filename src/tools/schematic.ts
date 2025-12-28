/**
 * Schematic tools for KiCAD MCP server
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';

export function registerSchematicTools(server: McpServer, callKicadScript: Function) {
  // Create schematic tool
  server.tool(
    "create_schematic",
    "Create a new schematic",
    {
      name: z.string().describe("Schematic name"),
      path: z.string().optional().describe("Optional path"),
    },
    async (args: { name: string; path?: string }) => {
      const result = await callKicadScript("create_schematic", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // Add component to schematic
  server.tool(
    "add_schematic_component",
    "Add a component to the schematic",
    {
      symbol: z.string().describe("Symbol library reference"),
      reference: z.string().describe("Component reference (e.g., R1, U1)"),
      value: z.string().optional().describe("Component value"),
      position: z.object({
        x: z.number(),
        y: z.number()
      }).optional().describe("Position on schematic"),
    },
    async (args: any) => {
      const result = await callKicadScript("add_schematic_component", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // Connect components with wire
  server.tool(
    "add_wire",
    "Add a wire connection in the schematic",
    {
      start: z.object({
        x: z.number(),
        y: z.number()
      }).describe("Start position"),
      end: z.object({
        x: z.number(),
        y: z.number()
      }).describe("End position"),
    },
    async (args: any) => {
      const result = await callKicadScript("add_wire", args);
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // Add pin-to-pin connection
  server.tool(
    "add_schematic_connection",
    "Connect two component pins with a wire",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      sourceRef: z.string().describe("Source component reference (e.g., R1)"),
      sourcePin: z.string().describe("Source pin name/number (e.g., 1, 2, GND)"),
      targetRef: z.string().describe("Target component reference (e.g., C1)"),
      targetPin: z.string().describe("Target pin name/number (e.g., 1, 2, VCC)")
    },
    async (args: { schematicPath: string; sourceRef: string; sourcePin: string; targetRef: string; targetPin: string }) => {
      const result = await callKicadScript("add_schematic_connection", args);
      if (result.success) {
        return {
          content: [{
            type: "text",
            text: `Successfully connected ${args.sourceRef}/${args.sourcePin} to ${args.targetRef}/${args.targetPin}`
          }]
        };
      } else {
        return {
          content: [{
            type: "text",
            text: `Failed to add connection: ${result.message || 'Unknown error'}`
          }]
        };
      }
    }
  );

  // Add net label
  server.tool(
    "add_schematic_net_label",
    "Add a net label to the schematic",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      netName: z.string().describe("Name of the net (e.g., VCC, GND, SIGNAL_1)"),
      position: z.array(z.number()).length(2).describe("Position [x, y] for the label")
    },
    async (args: { schematicPath: string; netName: string; position: number[] }) => {
      const result = await callKicadScript("add_schematic_net_label", args);
      if (result.success) {
        return {
          content: [{
            type: "text",
            text: `Successfully added net label '${args.netName}' at position [${args.position}]`
          }]
        };
      } else {
        return {
          content: [{
            type: "text",
            text: `Failed to add net label: ${result.message || 'Unknown error'}`
          }]
        };
      }
    }
  );

  // Connect pin to net
  server.tool(
    "connect_to_net",
    "Connect a component pin to a named net",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      componentRef: z.string().describe("Component reference (e.g., U1, R1)"),
      pinName: z.string().describe("Pin name/number to connect"),
      netName: z.string().describe("Name of the net to connect to")
    },
    async (args: { schematicPath: string; componentRef: string; pinName: string; netName: string }) => {
      const result = await callKicadScript("connect_to_net", args);
      if (result.success) {
        return {
          content: [{
            type: "text",
            text: `Successfully connected ${args.componentRef}/${args.pinName} to net '${args.netName}'`
          }]
        };
      } else {
        return {
          content: [{
            type: "text",
            text: `Failed to connect to net: ${result.message || 'Unknown error'}`
          }]
        };
      }
    }
  );

  // Get net connections
  server.tool(
    "get_net_connections",
    "Get all connections for a named net",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      netName: z.string().describe("Name of the net to query")
    },
    async (args: { schematicPath: string; netName: string }) => {
      const result = await callKicadScript("get_net_connections", args);
      if (result.success && result.connections) {
        const connectionList = result.connections.map((conn: any) =>
          `  - ${conn.component}/${conn.pin}`
        ).join('\n');
        return {
          content: [{
            type: "text",
            text: `Net '${args.netName}' connections:\n${connectionList}`
          }]
        };
      } else {
        return {
          content: [{
            type: "text",
            text: `Failed to get net connections: ${result.message || 'Unknown error'}`
          }]
        };
      }
    }
  );

  // Generate netlist
  server.tool(
    "generate_netlist",
    "Generate a netlist from the schematic",
    {
      schematicPath: z.string().describe("Path to the schematic file")
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("generate_netlist", args);
      if (result.success && result.netlist) {
        const netlist = result.netlist;
        const output = [
          `=== Netlist for ${args.schematicPath} ===`,
          `\nComponents (${netlist.components.length}):`,
          ...netlist.components.map((comp: any) =>
            `  ${comp.reference}: ${comp.value} (${comp.footprint || 'No footprint'})`
          ),
          `\nNets (${netlist.nets.length}):`,
          ...netlist.nets.map((net: any) => {
            const connections = net.connections.map((conn: any) =>
              `${conn.component}/${conn.pin}`
            ).join(', ');
            return `  ${net.name}: ${connections}`;
          })
        ].join('\n');

        return {
          content: [{
            type: "text",
            text: output
          }]
        };
      } else {
        return {
          content: [{
            type: "text",
            text: `Failed to generate netlist: ${result.message || 'Unknown error'}`
          }]
        };
      }
    }
  );

  // Update PCB from schematic (like KiCad's F8)
  server.tool(
    "update_pcb_from_schematic",
    "Update PCB with components from schematic. Places all components from the schematic onto the PCB in a grid layout. Similar to KiCad's 'Update PCB from Schematic' (F8) function.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      gridSpacing: z.number().optional().describe("Spacing between components in mm (default: 10)"),
      startX: z.number().optional().describe("Starting X position in mm (default: 20)"),
      startY: z.number().optional().describe("Starting Y position in mm (default: 20)"),
      colsPerRow: z.number().optional().describe("Number of components per row (default: 20)")
    },
    async (args: { schematicPath: string; gridSpacing?: number; startX?: number; startY?: number; colsPerRow?: number }) => {
      const result = await callKicadScript("update_pcb_from_schematic", args);
      if (result.success) {
        const details = result.details || {};
        let output = [
          `=== Update PCB from Schematic ===`,
          ``,
          `Summary:`,
          `  Placed: ${result.placed || 0} components`,
          `  Skipped: ${result.skipped || 0} components`,
          `  Errors: ${result.errors || 0} components`,
          ``
        ];

        if (details.placed && details.placed.length > 0) {
          output.push(`Placed components (first 20):`);
          details.placed.forEach((p: any) => {
            output.push(`  ${p.reference}: ${p.footprint} at (${p.x}, ${p.y})`);
          });
          output.push(``);
        }

        if (details.errors && details.errors.length > 0) {
          output.push(`Errors:`);
          details.errors.forEach((e: any) => {
            output.push(`  ${e.reference}: ${e.error}`);
          });
        }

        return {
          content: [{
            type: "text",
            text: output.join('\n')
          }]
        };
      } else {
        return {
          content: [{
            type: "text",
            text: `Failed to update PCB: ${result.message || 'Unknown error'}${result.traceback ? '\n\n' + result.traceback : ''}`
          }]
        };
      }
    }
  );
}
