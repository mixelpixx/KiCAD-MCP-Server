/**
 * Component management tools for KiCAD MCP server
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { logger } from '../logger.js';

// Command function type for KiCAD script calls
type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

/**
 * Register component management tools with the MCP server
 * 
 * @param server MCP server instance
 * @param callKicadScript Function to call KiCAD script commands
 */
export function registerComponentTools(server: McpServer, callKicadScript: CommandFunction): void {
  logger.info('Registering component management tools');
  
  // ------------------------------------------------------
  // Place Component Tool
  // ------------------------------------------------------
  server.tool(
    "place_component",
    {
      componentId: z.string().describe("Identifier for the component to place (e.g., 'R_0603_10k')"),
      position: z.object({
        x: z.number().describe("X coordinate"),
        y: z.number().describe("Y coordinate"),
        unit: z.enum(["mm", "inch"]).describe("Unit of measurement")
      }).describe("Position coordinates and unit"),
      reference: z.string().optional().describe("Optional desired reference (e.g., 'R5')"),
      value: z.string().optional().describe("Optional component value (e.g., '10k')"),
      footprint: z.string().optional().describe("Optional specific footprint name"),
      rotation: z.number().optional().describe("Optional rotation in degrees"),
      layer: z.string().optional().describe("Optional layer (e.g., 'F.Cu', 'B.SilkS')")
    },
    async ({ componentId, position, reference, value, footprint, rotation, layer }) => {
      logger.debug(`Placing component: ${componentId} at ${position.x},${position.y} ${position.unit}`);
      const result = await callKicadScript("place_component", {
        componentId,
        position,
        reference,
        value,
        footprint,
        rotation,
        layer
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
  // Move Component Tool
  // ------------------------------------------------------
  server.tool(
    "move_component",
    {
      reference: z.string().describe("Reference designator of the component (e.g., 'R5')"),
      position: z.object({
        x: z.number().describe("X coordinate"),
        y: z.number().describe("Y coordinate"),
        unit: z.enum(["mm", "inch"]).describe("Unit of measurement")
      }).describe("New position coordinates and unit"),
      rotation: z.number().optional().describe("Optional new rotation in degrees")
    },
    async ({ reference, position, rotation }) => {
      logger.debug(`Moving component: ${reference} to ${position.x},${position.y} ${position.unit}`);
      const result = await callKicadScript("move_component", {
        reference,
        position,
        rotation
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
  // Rotate Component Tool
  // ------------------------------------------------------
  server.tool(
    "rotate_component",
    {
      reference: z.string().describe("Reference designator of the component (e.g., 'R5')"),
      angle: z.number().describe("Rotation angle in degrees (absolute, not relative)")
    },
    async ({ reference, angle }) => {
      logger.debug(`Rotating component: ${reference} to ${angle} degrees`);
      const result = await callKicadScript("rotate_component", {
        reference,
        angle
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
  // Delete Component Tool
  // ------------------------------------------------------
  server.tool(
    "delete_component",
    {
      reference: z.string().describe("Reference designator of the component to delete (e.g., 'R5')")
    },
    async ({ reference }) => {
      logger.debug(`Deleting component: ${reference}`);
      const result = await callKicadScript("delete_component", { reference });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Edit Component Properties Tool
  // ------------------------------------------------------
  server.tool(
    "edit_component",
    {
      reference: z.string().describe("Reference designator of the component (e.g., 'R5')"),
      newReference: z.string().optional().describe("Optional new reference designator"),
      value: z.string().optional().describe("Optional new component value"),
      footprint: z.string().optional().describe("Optional new footprint")
    },
    async ({ reference, newReference, value, footprint }) => {
      logger.debug(`Editing component: ${reference}`);
      const result = await callKicadScript("edit_component", {
        reference,
        newReference,
        value,
        footprint
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
  // Find Component Tool
  // ------------------------------------------------------
  server.tool(
    "find_component",
    {
      reference: z.string().optional().describe("Reference designator to search for"),
      value: z.string().optional().describe("Component value to search for")
    },
    async ({ reference, value }) => {
      logger.debug(`Finding component with ${reference ? `reference: ${reference}` : `value: ${value}`}`);
      const result = await callKicadScript("find_component", { reference, value });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Get Component Properties Tool
  // ------------------------------------------------------
  server.tool(
    "get_component_properties",
    {
      reference: z.string().describe("Reference designator of the component (e.g., 'R5')")
    },
    async ({ reference }) => {
      logger.debug(`Getting properties for component: ${reference}`);
      const result = await callKicadScript("get_component_properties", { reference });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Add Component Annotation Tool
  // ------------------------------------------------------
  server.tool(
    "add_component_annotation",
    {
      reference: z.string().describe("Reference designator of the component (e.g., 'R5')"),
      annotation: z.string().describe("Annotation or comment text to add"),
      visible: z.boolean().optional().describe("Whether the annotation should be visible on the PCB")
    },
    async ({ reference, annotation, visible }) => {
      logger.debug(`Adding annotation to component: ${reference}`);
      const result = await callKicadScript("add_component_annotation", {
        reference,
        annotation,
        visible
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
  // Group Components Tool
  // ------------------------------------------------------
  server.tool(
    "group_components",
    {
      references: z.array(z.string()).describe("Reference designators of components to group"),
      groupName: z.string().describe("Name for the component group")
    },
    async ({ references, groupName }) => {
      logger.debug(`Grouping components: ${references.join(', ')} as ${groupName}`);
      const result = await callKicadScript("group_components", {
        references,
        groupName
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
  // Replace Component Tool
  // ------------------------------------------------------
  server.tool(
    "replace_component",
    {
      reference: z.string().describe("Reference designator of the component to replace"),
      newComponentId: z.string().describe("ID of the new component to use"),
      newFootprint: z.string().optional().describe("Optional new footprint"),
      newValue: z.string().optional().describe("Optional new component value")
    },
    async ({ reference, newComponentId, newFootprint, newValue }) => {
      logger.debug(`Replacing component: ${reference} with ${newComponentId}`);
      const result = await callKicadScript("replace_component", {
        reference,
        newComponentId,
        newFootprint,
        newValue
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
  // Get Component Pads Tool (was in Python, not exposed)
  // ------------------------------------------------------
  server.tool(
    "get_component_pads",
    {
      reference: z.string().describe("Reference designator of the component (e.g., 'U1', 'J2')")
    },
    async ({ reference }) => {
      logger.debug(`Getting pads for component: ${reference}`);
      const result = await callKicadScript("get_component_pads", { reference });

      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Get Pad Position Tool (was in Python, not exposed)
  // ------------------------------------------------------
  server.tool(
    "get_pad_position",
    {
      reference: z.string().describe("Reference designator of the component (e.g., 'U1')"),
      padName: z.string().describe("Pad name or number (e.g., '1', 'A5', 'SH')")
    },
    async ({ reference, padName }) => {
      logger.debug(`Getting position for pad ${padName} on component: ${reference}`);
      const result = await callKicadScript("get_pad_position", { reference, padName });

      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Set Pad Net Tool (NEW - assigns a net to a component pad)
  // ------------------------------------------------------
  server.tool(
    "set_pad_net",
    {
      reference: z.string().describe("Reference designator of the component (e.g., 'J2', 'U1')"),
      padName: z.string().describe("Pad name or number (e.g., '1', 'A5', 'SH')"),
      net: z.string().describe("Net name to assign (e.g., 'GND', 'VCC_5V'). Use empty string to clear.")
    },
    async ({ reference, padName, net }) => {
      logger.debug(`Setting pad ${padName} on ${reference} to net: ${net}`);
      const result = await callKicadScript("set_pad_net", { reference, padName, net });

      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Get Component List Tool (exposes hidden Python command)
  // ------------------------------------------------------
  server.tool(
    "get_component_list",
    "Get a list of all components on the PCB with their references, values, footprints, and positions",
    {},
    async () => {
      logger.debug('Getting component list');
      const result = await callKicadScript("get_component_list", {});

      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Align Components Tool (exposes hidden Python command)
  // ------------------------------------------------------
  server.tool(
    "align_components",
    "Align multiple components horizontally, vertically, or to a board edge. Supports equal distribution and fixed spacing.",
    {
      references: z.array(z.string()).describe("Reference designators of components to align (e.g., ['R1', 'R2', 'R3'])"),
      alignment: z.enum(["horizontal", "vertical", "left", "right", "top", "bottom"]).describe("Alignment direction or edge"),
      distribution: z.enum(["none", "equal", "spacing"]).optional().describe("Distribution mode (default: none)"),
      spacing: z.number().optional().describe("Spacing in mm (required when distribution='spacing')")
    },
    async (args: any) => {
      logger.debug(`Aligning components: ${args.references.join(', ')}`);
      const result = await callKicadScript("align_components", args);

      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Duplicate Component Tool (exposes hidden Python command)
  // ------------------------------------------------------
  server.tool(
    "duplicate_component",
    "Duplicate an existing component on the PCB with a new reference designator",
    {
      reference: z.string().describe("Reference designator of the component to duplicate (e.g., 'R1')"),
      newReference: z.string().describe("Reference designator for the new component (e.g., 'R2')"),
      position: z.object({
        x: z.number(),
        y: z.number(),
        unit: z.enum(["mm", "inch"]).optional()
      }).optional().describe("Optional position for the new component"),
      rotation: z.number().optional().describe("Optional rotation in degrees")
    },
    async (args: any) => {
      logger.debug(`Duplicating component ${args.reference} to ${args.newReference}`);
      const result = await callKicadScript("duplicate_component", args);

      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Place Component Array Tool (exposes hidden Python command)
  // ------------------------------------------------------
  server.tool(
    "place_component_array",
    "Place multiple components in a grid or circular array pattern",
    {
      componentId: z.string().describe("Component/footprint identifier"),
      pattern: z.enum(["grid", "circular"]).describe("Array pattern type"),
      position: z.object({
        x: z.number(),
        y: z.number(),
        unit: z.enum(["mm", "inch"]).optional()
      }).describe("Start position (grid) or center position (circular)"),
      rows: z.number().optional().describe("Number of rows (grid pattern)"),
      columns: z.number().optional().describe("Number of columns (grid pattern)"),
      spacingX: z.number().optional().describe("X spacing in mm (grid pattern)"),
      spacingY: z.number().optional().describe("Y spacing in mm (grid pattern)"),
      count: z.number().optional().describe("Number of components (circular pattern)"),
      radius: z.number().optional().describe("Radius in mm (circular pattern)"),
      angleStart: z.number().optional().describe("Starting angle in degrees (circular pattern, default 0)"),
      angleStep: z.number().optional().describe("Angle step between components (circular pattern)"),
      referencePrefix: z.string().optional().describe("Reference prefix (e.g., 'R' for R1, R2...)"),
      value: z.string().optional().describe("Component value"),
      rotation: z.number().optional().describe("Rotation in degrees")
    },
    async (args: any) => {
      logger.debug(`Placing component array: ${args.pattern}`);
      const result = await callKicadScript("place_component_array", args);

      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  logger.info('Component management tools registered');
}
