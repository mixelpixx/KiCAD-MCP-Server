/**
 * Board management tools for KiCAD MCP server
 *
 * These tools handle board setup, layer management, and board properties
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { logger } from "../logger.js";

// Command function type for KiCAD script calls
type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

/**
 * Register board management tools with the MCP server
 *
 * @param server MCP server instance
 * @param callKicadScript Function to call KiCAD script commands
 */
export function registerBoardTools(server: McpServer, callKicadScript: CommandFunction): void {
  logger.info("Registering board management tools");

  // ------------------------------------------------------
  // Set Board Size Tool
  // ------------------------------------------------------
  server.tool(
    "set_board_size",
    {
      width: z.number().describe("Board width"),
      height: z.number().describe("Board height"),
      unit: z.enum(["mm", "inch"]).describe("Unit of measurement"),
    },
    async ({ width, height, unit }) => {
      logger.debug(`Setting board size to ${width}x${height} ${unit}`);
      const result = await callKicadScript("set_board_size", {
        width,
        height,
        unit,
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
  // Add Layer Tool
  // ------------------------------------------------------
  server.tool(
    "add_layer",
    {
      name: z.string().describe("Layer name"),
      type: z.enum(["copper", "technical", "user", "signal"]).describe("Layer type"),
      position: z.enum(["top", "bottom", "inner"]).describe("Layer position"),
      number: z.number().optional().describe("Layer number (for inner layers)"),
    },
    async ({ name, type, position, number }) => {
      logger.debug(`Adding ${type} layer: ${name}`);
      const result = await callKicadScript("add_layer", {
        name,
        type,
        position,
        number,
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
  // Set Active Layer Tool
  // ------------------------------------------------------
  server.tool(
    "set_active_layer",
    {
      layer: z.string().describe("Layer name to set as active"),
    },
    async ({ layer }) => {
      logger.debug(`Setting active layer to: ${layer}`);
      const result = await callKicadScript("set_active_layer", { layer });

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
  // Get Board Info Tool
  // ------------------------------------------------------
  server.tool("get_board_info", {}, async () => {
    logger.debug("Getting board information");
    const result = await callKicadScript("get_board_info", {});

    return {
      content: [
        {
          type: "text",
          text: JSON.stringify(result),
        },
      ],
    };
  });

  // ------------------------------------------------------
  // Get Layer List Tool
  // ------------------------------------------------------
  server.tool("get_layer_list", {}, async () => {
    logger.debug("Getting layer list");
    const result = await callKicadScript("get_layer_list", {});

    return {
      content: [
        {
          type: "text",
          text: JSON.stringify(result),
        },
      ],
    };
  });

  // ------------------------------------------------------
  // Add Board Outline Tool
  // ------------------------------------------------------
  server.tool(
    "add_board_outline",
    {
      shape: z
        .enum(["rectangle", "circle", "polygon", "rounded_rectangle"])
        .describe("Shape of the outline"),
      params: z
        .object({
          // For rectangle / rounded_rectangle
          width: z.number().optional().describe("Width of rectangle"),
          height: z.number().optional().describe("Height of rectangle"),
          cornerRadius: z.number().optional().describe("Corner radius for rounded_rectangle (mm)"),
          // For circle
          radius: z.number().optional().describe("Radius of circle"),
          // For polygon
          points: z
            .array(
              z.object({
                x: z.number().describe("X coordinate"),
                y: z.number().describe("Y coordinate"),
              }),
            )
            .optional()
            .describe("Points of polygon"),
          // Position: top-left corner for rectangles/rounded_rectangle, center for circle
          x: z.number().describe("X coordinate of top-left corner for rectangles (default: 0)"),
          y: z.number().describe("Y coordinate of top-left corner for rectangles (default: 0)"),
          unit: z.enum(["mm", "inch"]).describe("Unit of measurement"),
        })
        .describe("Parameters for the outline shape"),
    },
    async ({ shape, params }) => {
      logger.debug(`Adding ${shape} board outline`);
      // Pass x/y as-is to Python; outline.py treats them as top-left corner
      // and computes the center internally (center = x + width/2, y + height/2).
      const result = await callKicadScript("add_board_outline", {
        shape,
        ...params,
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
  // Add Mounting Hole Tool
  // ------------------------------------------------------
  server.tool(
    "add_mounting_hole",
    {
      position: z
        .object({
          x: z.number().describe("X coordinate"),
          y: z.number().describe("Y coordinate"),
          unit: z.enum(["mm", "inch"]).describe("Unit of measurement"),
        })
        .describe("Position of the mounting hole"),
      diameter: z.number().describe("Diameter of the hole"),
      padDiameter: z.number().optional().describe("Optional diameter of the pad around the hole"),
    },
    async ({ position, diameter, padDiameter }) => {
      logger.debug(`Adding mounting hole at (${position.x},${position.y}) ${position.unit}`);
      const result = await callKicadScript("add_mounting_hole", {
        position,
        diameter,
        padDiameter,
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
  // Add Text Tool
  // ------------------------------------------------------
  server.tool(
    "add_board_text",
    {
      text: z.string().describe("Text content"),
      position: z
        .object({
          x: z.number().describe("X coordinate"),
          y: z.number().describe("Y coordinate"),
          unit: z.enum(["mm", "inch"]).describe("Unit of measurement"),
        })
        .describe("Position of the text"),
      layer: z.string().describe("Layer to place the text on"),
      size: z.number().describe("Text size"),
      thickness: z.number().optional().describe("Line thickness"),
      rotation: z.number().optional().describe("Rotation angle in degrees"),
      style: z.enum(["normal", "italic", "bold"]).optional().describe("Text style"),
    },
    async ({ text, position, layer, size, thickness, rotation, style }) => {
      logger.debug(`Adding text "${text}" at (${position.x},${position.y}) ${position.unit}`);
      const result = await callKicadScript("add_board_text", {
        text,
        position,
        layer,
        size,
        thickness,
        rotation,
        style,
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
  // Add Zone Tool
  // ------------------------------------------------------
  server.tool(
    "add_zone",
    {
      layer: z.string().describe("Layer for the zone"),
      net: z.string().describe("Net name for the zone"),
      points: z
        .array(
          z.object({
            x: z.number().describe("X coordinate"),
            y: z.number().describe("Y coordinate"),
          }),
        )
        .describe("Points defining the zone outline"),
      unit: z.enum(["mm", "inch"]).describe("Unit of measurement"),
      clearance: z.number().optional().describe("Clearance value"),
      minWidth: z.number().optional().describe("Minimum width"),
      padConnection: z
        .enum(["thermal", "solid", "none"])
        .optional()
        .describe("Pad connection type"),
    },
    async ({ layer, net, points, unit, clearance, minWidth, padConnection }) => {
      logger.debug(`Adding zone on layer ${layer} for net ${net}`);
      const result = await callKicadScript("add_zone", {
        layer,
        net,
        points,
        unit,
        clearance,
        minWidth,
        padConnection,
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
  // Get Board Extents Tool
  // ------------------------------------------------------
  server.tool(
    "get_board_extents",
    {
      unit: z.enum(["mm", "inch"]).optional().describe("Unit of measurement for the result"),
    },
    async ({ unit }) => {
      logger.debug("Getting board extents");
      const result = await callKicadScript("get_board_extents", { unit });

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
  // Get Board 2D View Tool
  // ------------------------------------------------------
  server.tool(
    "get_board_2d_view",
    {
      layers: z.array(z.string()).optional().describe("Optional array of layer names to include"),
      width: z.number().optional().describe("Optional width of the image in pixels"),
      height: z.number().optional().describe("Optional height of the image in pixels"),
      format: z.enum(["png", "jpg", "svg"]).optional().describe("Image format"),
    },
    async ({ layers, width, height, format }) => {
      logger.debug("Getting 2D board view");
      const result = await callKicadScript("get_board_2d_view", {
        layers,
        width,
        height,
        format,
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

  logger.info("Board management tools registered");

  // Import SVG logo onto PCB layer (silkscreen)
  server.tool(
    "import_svg_logo",
    "Imports an SVG file as filled graphic polygons onto a KiCAD PCB layer (default F.SilkS / front silkscreen). Curves are linearised automatically. Ideal for placing a company or project logo on the board.",
    {
      pcbPath: z.string().describe("Path to the .kicad_pcb file"),
      svgPath: z.string().describe("Path to the SVG logo file"),
      x: z.number().describe("X position of the logo top-left corner in mm"),
      y: z.number().describe("Y position of the logo top-left corner in mm"),
      width: z
        .number()
        .describe("Target width of the logo in mm (height is scaled to preserve aspect ratio)"),
      layer: z
        .string()
        .optional()
        .describe("PCB layer name, e.g. F.SilkS or B.SilkS (default: F.SilkS)"),
      strokeWidth: z
        .number()
        .optional()
        .describe("Outline stroke width in mm (0 = no outline, default 0)"),
      filled: z.boolean().optional().describe("Fill polygons with solid colour (default true)"),
    },
    async (args: {
      pcbPath: string;
      svgPath: string;
      x: number;
      y: number;
      width: number;
      layer?: string;
      strokeWidth?: number;
      filled?: boolean;
    }) => {
      const result = await callKicadScript("import_svg_logo", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: [
                result.message,
                `Polygons: ${result.polygon_count}`,
                `Size: ${result.logo_width_mm?.toFixed(2)} × ${result.logo_height_mm?.toFixed(2)} mm`,
                `Layer: ${result.layer}`,
              ].join("\n"),
            },
          ],
        };
      } else {
        return {
          content: [
            { type: "text", text: `SVG import failed: ${result.message || "Unknown error"}` },
          ],
        };
      }
    },
  );
}
