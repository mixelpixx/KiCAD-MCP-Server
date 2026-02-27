/**
 * Component management tools for KiCAD MCP server
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { logger } from "../logger.js";

// Command function type for KiCAD script calls
type CommandFunction = (
  command: string,
  params: Record<string, unknown>,
) => Promise<any>;

/**
 * Register component management tools with the MCP server
 *
 * @param server MCP server instance
 * @param callKicadScript Function to call KiCAD script commands
 */
export function registerComponentTools(
  server: McpServer,
  callKicadScript: CommandFunction,
): void {
  logger.info("Registering component management tools");

  // ------------------------------------------------------
  // Place Component Tool
  // ------------------------------------------------------
  server.tool(
    "place_component",
    {
      componentId: z
        .string()
        .describe("Identifier for the component to place (e.g., 'R_0603_10k')"),
      position: z
        .object({
          x: z.number().describe("X coordinate"),
          y: z.number().describe("Y coordinate"),
          unit: z.enum(["mm", "inch"]).describe("Unit of measurement"),
        })
        .describe("Position coordinates and unit"),
      reference: z
        .string()
        .optional()
        .describe("Optional desired reference (e.g., 'R5')"),
      value: z
        .string()
        .optional()
        .describe("Optional component value (e.g., '10k')"),
      footprint: z
        .string()
        .optional()
        .describe("Optional specific footprint name"),
      rotation: z.number().optional().describe("Optional rotation in degrees"),
      layer: z
        .string()
        .optional()
        .describe("Optional layer (e.g., 'F.Cu', 'B.SilkS')"),
    },
    async ({
      componentId,
      position,
      reference,
      value,
      footprint,
      rotation,
      layer,
    }) => {
      logger.debug(
        `Placing component: ${componentId} at ${position.x},${position.y} ${position.unit}`,
      );
      const result = await callKicadScript("place_component", {
        componentId,
        position,
        reference,
        value,
        footprint,
        rotation,
        layer,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Move Component Tool
  // ------------------------------------------------------
  server.tool(
    "move_component",
    {
      reference: z
        .string()
        .describe("Reference designator of the component (e.g., 'R5')"),
      position: z
        .object({
          x: z.number().describe("X coordinate"),
          y: z.number().describe("Y coordinate"),
          unit: z.enum(["mm", "inch"]).describe("Unit of measurement"),
        })
        .describe("New position coordinates and unit"),
      rotation: z
        .number()
        .optional()
        .describe("Optional new rotation in degrees"),
    },
    async ({ reference, position, rotation }) => {
      logger.debug(
        `Moving component: ${reference} to ${position.x},${position.y} ${position.unit}`,
      );
      const result = await callKicadScript("move_component", {
        reference,
        position,
        rotation,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Rotate Component Tool
  // ------------------------------------------------------
  server.tool(
    "rotate_component",
    {
      reference: z
        .string()
        .describe("Reference designator of the component (e.g., 'R5')"),
      angle: z
        .number()
        .describe("Rotation angle in degrees (absolute, not relative)"),
    },
    async ({ reference, angle }) => {
      logger.debug(`Rotating component: ${reference} to ${angle} degrees`);
      const result = await callKicadScript("rotate_component", {
        reference,
        angle,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Delete Component Tool
  // ------------------------------------------------------
  server.tool(
    "delete_component",
    {
      reference: z
        .string()
        .describe(
          "Reference designator of the component to delete (e.g., 'R5')",
        ),
    },
    async ({ reference }) => {
      logger.debug(`Deleting component: ${reference}`);
      const result = await callKicadScript("delete_component", { reference });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Edit Component Properties Tool
  // ------------------------------------------------------
  server.tool(
    "edit_component",
    {
      reference: z
        .string()
        .describe("Reference designator of the component (e.g., 'R5')"),
      newReference: z
        .string()
        .optional()
        .describe("Optional new reference designator"),
      value: z.string().optional().describe("Optional new component value"),
      footprint: z.string().optional().describe("Optional new footprint"),
    },
    async ({ reference, newReference, value, footprint }) => {
      logger.debug(`Editing component: ${reference}`);
      const result = await callKicadScript("edit_component", {
        reference,
        newReference,
        value,
        footprint,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Find Component Tool
  // ------------------------------------------------------
  server.tool(
    "find_component",
    {
      reference: z
        .string()
        .optional()
        .describe("Reference designator to search for"),
      value: z.string().optional().describe("Component value to search for"),
    },
    async ({ reference, value }) => {
      logger.debug(
        `Finding component with ${reference ? `reference: ${reference}` : `value: ${value}`}`,
      );
      const result = await callKicadScript("find_component", {
        reference,
        value,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Get Component Properties Tool
  // ------------------------------------------------------
  server.tool(
    "get_component_properties",
    {
      reference: z
        .string()
        .describe("Reference designator of the component (e.g., 'R5')"),
    },
    async ({ reference }) => {
      logger.debug(`Getting properties for component: ${reference}`);
      const result = await callKicadScript("get_component_properties", {
        reference,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Add Component Annotation Tool
  // ------------------------------------------------------
  server.tool(
    "add_component_annotation",
    {
      reference: z
        .string()
        .describe("Reference designator of the component (e.g., 'R5')"),
      annotation: z.string().describe("Annotation or comment text to add"),
      visible: z
        .boolean()
        .optional()
        .describe("Whether the annotation should be visible on the PCB"),
    },
    async ({ reference, annotation, visible }) => {
      logger.debug(`Adding annotation to component: ${reference}`);
      const result = await callKicadScript("add_component_annotation", {
        reference,
        annotation,
        visible,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Group Components Tool
  // ------------------------------------------------------
  server.tool(
    "group_components",
    {
      references: z
        .array(z.string())
        .describe("Reference designators of components to group"),
      groupName: z.string().describe("Name for the component group"),
    },
    async ({ references, groupName }) => {
      logger.debug(
        `Grouping components: ${references.join(", ")} as ${groupName}`,
      );
      const result = await callKicadScript("group_components", {
        references,
        groupName,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Replace Component Tool
  // ------------------------------------------------------
  server.tool(
    "replace_component",
    {
      reference: z
        .string()
        .describe("Reference designator of the component to replace"),
      newComponentId: z.string().describe("ID of the new component to use"),
      newFootprint: z.string().optional().describe("Optional new footprint"),
      newValue: z.string().optional().describe("Optional new component value"),
    },
    async ({ reference, newComponentId, newFootprint, newValue }) => {
      logger.debug(`Replacing component: ${reference} with ${newComponentId}`);
      const result = await callKicadScript("replace_component", {
        reference,
        newComponentId,
        newFootprint,
        newValue,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Get Component Pads Tool
  // ------------------------------------------------------
  server.tool(
    "get_component_pads",
    {
      reference: z
        .string()
        .describe("Reference designator of the component (e.g., 'U1')"),
      unit: z
        .enum(["mm", "inch"])
        .optional()
        .describe("Unit for coordinates (default: mm)"),
    },
    async ({ reference, unit }) => {
      logger.debug(`Getting pads for component: ${reference}`);
      const result = await callKicadScript("get_component_pads", {
        reference,
        unit: unit || "mm",
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Get Component List Tool
  // ------------------------------------------------------
  server.tool(
    "get_component_list",
    {
      layer: z
        .string()
        .optional()
        .describe("Filter by layer (e.g., 'F.Cu', 'B.Cu')"),
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
      unit: z
        .enum(["mm", "inch"])
        .optional()
        .describe("Unit for coordinates (default: mm)"),
    },
    async ({ layer, boundingBox, unit }) => {
      logger.debug("Getting component list");
      const result = await callKicadScript("get_component_list", {
        layer,
        boundingBox,
        unit: unit || "mm",
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Get Pad Position Tool
  // ------------------------------------------------------
  server.tool(
    "get_pad_position",
    {
      reference: z
        .string()
        .describe("Component reference designator (e.g., 'U1')"),
      pad: z.string().describe("Pad number or name (e.g., '1', 'A1')"),
      unit: z
        .enum(["mm", "inch"])
        .optional()
        .describe("Unit for coordinates (default: mm)"),
    },
    async ({ reference, pad, unit }) => {
      logger.debug(`Getting pad position for ${reference} pad ${pad}`);
      const result = await callKicadScript("get_pad_position", {
        reference,
        pad,
        unit: unit || "mm",
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Place Component Array Tool
  // ------------------------------------------------------
  server.tool(
    "place_component_array",
    {
      componentId: z.string().describe("Component identifier"),
      startPosition: z
        .object({
          x: z.number(),
          y: z.number(),
          unit: z.enum(["mm", "inch"]),
        })
        .describe("Starting position"),
      rows: z.number().describe("Number of rows"),
      columns: z.number().describe("Number of columns"),
      rowSpacing: z.number().describe("Spacing between rows"),
      columnSpacing: z.number().describe("Spacing between columns"),
      startReference: z
        .string()
        .optional()
        .describe("Starting reference (e.g., 'R1')"),
      footprint: z.string().optional().describe("Footprint name"),
      value: z.string().optional().describe("Component value"),
      rotation: z.number().optional().describe("Rotation in degrees"),
    },
    async ({
      componentId,
      startPosition,
      rows,
      columns,
      rowSpacing,
      columnSpacing,
      startReference,
      footprint,
      value,
      rotation,
    }) => {
      logger.debug(
        `Placing component array: ${rows}x${columns} of ${componentId}`,
      );
      const result = await callKicadScript("place_component_array", {
        componentId,
        startPosition,
        rows,
        columns,
        rowSpacing,
        columnSpacing,
        startReference,
        footprint,
        value,
        rotation,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Align Components Tool
  // ------------------------------------------------------
  server.tool(
    "align_components",
    {
      references: z
        .array(z.string())
        .describe("Array of component references to align"),
      alignmentType: z
        .enum(["horizontal", "vertical", "grid"])
        .describe("Type of alignment"),
      spacing: z
        .number()
        .optional()
        .describe("Spacing between components in mm"),
      referenceComponent: z
        .string()
        .optional()
        .describe("Reference component for alignment"),
    },
    async ({ references, alignmentType, spacing, referenceComponent }) => {
      logger.debug(`Aligning components: ${references.join(", ")}`);
      const result = await callKicadScript("align_components", {
        references,
        alignmentType,
        spacing,
        referenceComponent,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Duplicate Component Tool
  // ------------------------------------------------------
  server.tool(
    "duplicate_component",
    {
      reference: z.string().describe("Reference of component to duplicate"),
      offset: z
        .object({
          x: z.number(),
          y: z.number(),
          unit: z.enum(["mm", "inch"]).optional(),
        })
        .describe("Offset from original position"),
      newReference: z.string().optional().describe("New reference designator"),
      count: z
        .number()
        .optional()
        .describe("Number of duplicates (default: 1)"),
    },
    async ({ reference, offset, newReference, count }) => {
      logger.debug(`Duplicating component: ${reference}`);
      const result = await callKicadScript("duplicate_component", {
        reference,
        offset,
        newReference,
        count,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  logger.info("Component management tools registered");
}
