/**
 * Board resources for KiCAD MCP server
 * 
 * These resources provide information about the PCB board
 * to the LLM, enabling better context-aware assistance.
 */

import { McpServer, ResourceTemplate } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { logger } from '../logger.js';
import { createJsonResponse, createBinaryResponse } from '../utils/resource-helpers.js';

// Command function type for KiCAD script calls
type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

/**
 * Register board resources with the MCP server
 * 
 * @param server MCP server instance
 * @param callKicadScript Function to call KiCAD script commands
 */
export function registerBoardResources(server: McpServer, callKicadScript: CommandFunction): void {
  logger.info('Registering board resources');

  // ------------------------------------------------------
  // Board Information Resource
  // ------------------------------------------------------
  server.resource(
    "board_info",
    "kicad://board/info",
    async (uri) => {
      logger.debug('Retrieving board information');
      const result = await callKicadScript("get_board_info", {});
      
      if (!result.success) {
        logger.error(`Failed to retrieve board information: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to retrieve board information",
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      logger.debug('Successfully retrieved board information');
      return {
        contents: [{
          uri: uri.href,
          text: JSON.stringify(result),
          mimeType: "application/json"
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Layer List Resource
  // ------------------------------------------------------
  server.resource(
    "layer_list",
    "kicad://board/layers",
    async (uri) => {
      logger.debug('Retrieving layer list');
      const result = await callKicadScript("get_layer_list", {});
      
      if (!result.success) {
        logger.error(`Failed to retrieve layer list: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to retrieve layer list",
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      logger.debug(`Successfully retrieved ${result.layers?.length || 0} layers`);
      return {
        contents: [{
          uri: uri.href,
          text: JSON.stringify(result),
          mimeType: "application/json"
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Board Extents Resource
  // ------------------------------------------------------
  server.resource(
    "board_extents",
    new ResourceTemplate("kicad://board/extents/{unit?}", {
      list: async () => ({
        resources: [
          { uri: "kicad://board/extents/mm", name: "Millimeters" },
          { uri: "kicad://board/extents/inch", name: "Inches" }
        ]
      })
    }),
    async (uri, params) => {
      const unit = params.unit || 'mm';
      
      logger.debug(`Retrieving board extents in ${unit}`);
      const result = await callKicadScript("get_board_extents", { unit });
      
      if (!result.success) {
        logger.error(`Failed to retrieve board extents: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to retrieve board extents",
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      logger.debug('Successfully retrieved board extents');
      return {
        contents: [{
          uri: uri.href,
          text: JSON.stringify(result),
          mimeType: "application/json"
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Board 2D View Resource
  // ------------------------------------------------------
  server.resource(
    "board_2d_view",
    new ResourceTemplate("kicad://board/2d-view/{format?}", {
      list: async () => ({
        resources: [
          { uri: "kicad://board/2d-view/png", name: "PNG Format" },
          { uri: "kicad://board/2d-view/jpg", name: "JPEG Format" },
          { uri: "kicad://board/2d-view/svg", name: "SVG Format" }
        ]
      })
    }),
    async (uri, params) => {
      const format = (params.format || 'png') as 'png' | 'jpg' | 'svg';
      const width = params.width ? parseInt(params.width as string) : undefined;
      const height = params.height ? parseInt(params.height as string) : undefined;
      // Handle layers parameter - could be string or array
      const layers = typeof params.layers === 'string' ? params.layers.split(',') : params.layers;
      
      logger.debug('Retrieving 2D board view');
      const result = await callKicadScript("get_board_2d_view", {
        layers,
        width,
        height,
        format
      });
      
      if (!result.success) {
        logger.error(`Failed to retrieve 2D board view: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to retrieve 2D board view",
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      logger.debug('Successfully retrieved 2D board view');
      
      if (format === 'svg') {
        return {
          contents: [{
            uri: uri.href,
            text: result.imageData,
            mimeType: "image/svg+xml"
          }]
        };
      } else {
        return {
          contents: [{
            uri: uri.href,
            blob: result.imageData,
            mimeType: format === "jpg" ? "image/jpeg" : "image/png"
          }]
        };
      }
    }
  );

  // ------------------------------------------------------
  // Board 3D View Resource
  // ------------------------------------------------------
  server.resource(
    "board_3d_view",
    new ResourceTemplate("kicad://board/3d-view/{angle?}", {
      list: async () => ({
        resources: [
          { uri: "kicad://board/3d-view/isometric", name: "Isometric View" },
          { uri: "kicad://board/3d-view/top", name: "Top View" },
          { uri: "kicad://board/3d-view/bottom", name: "Bottom View" }
        ]
      })
    }),
    async (uri, params) => {
      const angle = params.angle || 'isometric';
      const width = params.width ? parseInt(params.width as string) : undefined;
      const height = params.height ? parseInt(params.height as string) : undefined;
      
      logger.debug(`Retrieving 3D board view from ${angle} angle`);
      const result = await callKicadScript("get_board_3d_view", {
        width,
        height,
        angle
      });
      
      if (!result.success) {
        logger.error(`Failed to retrieve 3D board view: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to retrieve 3D board view",
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      logger.debug('Successfully retrieved 3D board view');
      return {
        contents: [{
          uri: uri.href,
          blob: result.imageData,
          mimeType: "image/png"
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Board Statistics Resource
  // ------------------------------------------------------
  server.resource(
    "board_statistics",
    "kicad://board/statistics",
    async (uri) => {
      logger.debug('Generating board statistics');
      
      // Get board info
      const boardResult = await callKicadScript("get_board_info", {});
      if (!boardResult.success) {
        logger.error(`Failed to retrieve board information: ${boardResult.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to generate board statistics",
              details: boardResult.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      // Get component list
      const componentsResult = await callKicadScript("get_component_list", {});
      if (!componentsResult.success) {
        logger.error(`Failed to retrieve component list: ${componentsResult.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to generate board statistics",
              details: componentsResult.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      // Get nets list
      const netsResult = await callKicadScript("get_nets_list", {});
      if (!netsResult.success) {
        logger.error(`Failed to retrieve nets list: ${netsResult.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to generate board statistics",
              details: netsResult.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      // Combine all information into statistics
      const statistics = {
        board: {
          size: boardResult.size,
          layers: boardResult.layers?.length || 0,
          title: boardResult.title
        },
        components: {
          count: componentsResult.components?.length || 0,
          types: countComponentTypes(componentsResult.components || [])
        },
        nets: {
          count: netsResult.nets?.length || 0
        }
      };
      
      logger.debug('Successfully generated board statistics');
      return {
        contents: [{
          uri: uri.href,
          text: JSON.stringify(statistics),
          mimeType: "application/json"
        }]
      };
    }
  );

  logger.info('Board resources registered');
}

/**
 * Helper function to count component types
 */
function countComponentTypes(components: any[]): Record<string, number> {
  const typeCounts: Record<string, number> = {};
  
  for (const component of components) {
    const type = component.value?.split(' ')[0] || 'Unknown';
    typeCounts[type] = (typeCounts[type] || 0) + 1;
  }
  
  return typeCounts;
}
