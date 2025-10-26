/**
 * Design rules tools for KiCAD MCP server
 * 
 * These tools handle design rule checking and configuration
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { logger } from '../logger.js';

// Command function type for KiCAD script calls
type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

/**
 * Register design rule tools with the MCP server
 * 
 * @param server MCP server instance
 * @param callKicadScript Function to call KiCAD script commands
 */
export function registerDesignRuleTools(server: McpServer, callKicadScript: CommandFunction): void {
  logger.info('Registering design rule tools');
  
  // ------------------------------------------------------
  // Set Design Rules Tool
  // ------------------------------------------------------
  server.tool(
    "set_design_rules",
    {
      clearance: z.number().optional().describe("Minimum clearance between copper items (mm)"),
      trackWidth: z.number().optional().describe("Default track width (mm)"),
      viaDiameter: z.number().optional().describe("Default via diameter (mm)"),
      viaDrill: z.number().optional().describe("Default via drill size (mm)"),
      microViaDiameter: z.number().optional().describe("Default micro via diameter (mm)"),
      microViaDrill: z.number().optional().describe("Default micro via drill size (mm)"),
      minTrackWidth: z.number().optional().describe("Minimum track width (mm)"),
      minViaDiameter: z.number().optional().describe("Minimum via diameter (mm)"),
      minViaDrill: z.number().optional().describe("Minimum via drill size (mm)"),
      minMicroViaDiameter: z.number().optional().describe("Minimum micro via diameter (mm)"),
      minMicroViaDrill: z.number().optional().describe("Minimum micro via drill size (mm)"),
      minHoleDiameter: z.number().optional().describe("Minimum hole diameter (mm)"),
      requireCourtyard: z.boolean().optional().describe("Whether to require courtyards for all footprints"),
      courtyardClearance: z.number().optional().describe("Minimum clearance between courtyards (mm)")
    },
    async (params) => {
      logger.debug('Setting design rules');
      const result = await callKicadScript("set_design_rules", params);
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Get Design Rules Tool
  // ------------------------------------------------------
  server.tool(
    "get_design_rules",
    {},
    async () => {
      logger.debug('Getting design rules');
      const result = await callKicadScript("get_design_rules", {});
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Run DRC Tool
  // ------------------------------------------------------
  server.tool(
    "run_drc",
    {
      reportPath: z.string().optional().describe("Optional path to save the DRC report")
    },
    async ({ reportPath }) => {
      logger.debug('Running DRC check');
      const result = await callKicadScript("run_drc", { reportPath });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Add Net Class Tool
  // ------------------------------------------------------
  server.tool(
    "add_net_class",
    {
      name: z.string().describe("Name of the net class"),
      description: z.string().optional().describe("Optional description of the net class"),
      clearance: z.number().describe("Clearance for this net class (mm)"),
      trackWidth: z.number().describe("Track width for this net class (mm)"),
      viaDiameter: z.number().describe("Via diameter for this net class (mm)"),
      viaDrill: z.number().describe("Via drill size for this net class (mm)"),
      uvia_diameter: z.number().optional().describe("Micro via diameter for this net class (mm)"),
      uvia_drill: z.number().optional().describe("Micro via drill size for this net class (mm)"),
      diff_pair_width: z.number().optional().describe("Differential pair width for this net class (mm)"),
      diff_pair_gap: z.number().optional().describe("Differential pair gap for this net class (mm)"),
      nets: z.array(z.string()).optional().describe("Array of net names to assign to this class")
    },
    async ({ name, description, clearance, trackWidth, viaDiameter, viaDrill, uvia_diameter, uvia_drill, diff_pair_width, diff_pair_gap, nets }) => {
      logger.debug(`Adding net class: ${name}`);
      const result = await callKicadScript("add_net_class", {
        name,
        description,
        clearance,
        trackWidth,
        viaDiameter,
        viaDrill,
        uvia_diameter,
        uvia_drill,
        diff_pair_width,
        diff_pair_gap,
        nets
      });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Assign Net to Class Tool
  // ------------------------------------------------------
  server.tool(
    "assign_net_to_class",
    {
      net: z.string().describe("Name of the net"),
      netClass: z.string().describe("Name of the net class")
    },
    async ({ net, netClass }) => {
      logger.debug(`Assigning net ${net} to class ${netClass}`);
      const result = await callKicadScript("assign_net_to_class", {
        net,
        netClass
      });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Set Layer Constraints Tool
  // ------------------------------------------------------
  server.tool(
    "set_layer_constraints",
    {
      layer: z.string().describe("Layer name (e.g., 'F.Cu')"),
      minTrackWidth: z.number().optional().describe("Minimum track width for this layer (mm)"),
      minClearance: z.number().optional().describe("Minimum clearance for this layer (mm)"),
      minViaDiameter: z.number().optional().describe("Minimum via diameter for this layer (mm)"),
      minViaDrill: z.number().optional().describe("Minimum via drill size for this layer (mm)")
    },
    async ({ layer, minTrackWidth, minClearance, minViaDiameter, minViaDrill }) => {
      logger.debug(`Setting constraints for layer: ${layer}`);
      const result = await callKicadScript("set_layer_constraints", {
        layer,
        minTrackWidth,
        minClearance,
        minViaDiameter,
        minViaDrill
      });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Check Clearance Tool
  // ------------------------------------------------------
  server.tool(
    "check_clearance",
    {
      item1: z.object({
        type: z.enum(["track", "via", "pad", "zone", "component"]).describe("Type of the first item"),
        id: z.string().optional().describe("ID of the first item (if applicable)"),
        reference: z.string().optional().describe("Reference designator (for component)"),
        position: z.object({
          x: z.number().optional(),
          y: z.number().optional(),
          unit: z.enum(["mm", "inch"]).optional()
        }).optional().describe("Position to check (if ID not provided)")
      }).describe("First item to check"),
      item2: z.object({
        type: z.enum(["track", "via", "pad", "zone", "component"]).describe("Type of the second item"),
        id: z.string().optional().describe("ID of the second item (if applicable)"),
        reference: z.string().optional().describe("Reference designator (for component)"),
        position: z.object({
          x: z.number().optional(),
          y: z.number().optional(),
          unit: z.enum(["mm", "inch"]).optional()
        }).optional().describe("Position to check (if ID not provided)")
      }).describe("Second item to check")
    },
    async ({ item1, item2 }) => {
      logger.debug(`Checking clearance between ${item1.type} and ${item2.type}`);
      const result = await callKicadScript("check_clearance", {
        item1,
        item2
      });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Get DRC Violations Tool
  // ------------------------------------------------------
  server.tool(
    "get_drc_violations",
    {
      severity: z.enum(["error", "warning", "all"]).optional().describe("Filter violations by severity")
    },
    async ({ severity }) => {
      logger.debug('Getting DRC violations');
      const result = await callKicadScript("get_drc_violations", { severity });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  logger.info('Design rule tools registered');
}
