/**
 * Library resources for KiCAD MCP server
 * 
 * These resources provide information about KiCAD component libraries
 * to the LLM, enabling better context-aware assistance.
 */

import { McpServer, ResourceTemplate } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { logger } from '../logger.js';

// Command function type for KiCAD script calls
type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

/**
 * Register library resources with the MCP server
 * 
 * @param server MCP server instance
 * @param callKicadScript Function to call KiCAD script commands
 */
export function registerLibraryResources(server: McpServer, callKicadScript: CommandFunction): void {
  logger.info('Registering library resources');

  // ------------------------------------------------------
  // Component Library Resource
  // ------------------------------------------------------
  server.resource(
    "component_library",
    new ResourceTemplate("kicad://components/{filter?}/{library?}", {
      list: async () => ({
        resources: [
          { uri: "kicad://components", name: "All Components" }
        ]
      })
    }),
    async (uri, params) => {
      const filter = params.filter || '';
      const library = params.library || '';
      const limit = Number(params.limit) || undefined;

      logger.debug(`Retrieving component library${filter ? ` with filter: ${filter}` : ''}${library ? ` from library: ${library}` : ''}`);
      
      const result = await callKicadScript("get_component_library", {
        filter,
        library,
        limit
      });

      if (!result.success) {
        logger.error(`Failed to retrieve component library: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to retrieve component library",
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }

      logger.debug(`Successfully retrieved ${result.components?.length || 0} components from library`);
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
  // Library List Resource
  // ------------------------------------------------------
  server.resource(
    "library_list",
    "kicad://libraries",
    async (uri) => {
      logger.debug('Retrieving library list');
      const result = await callKicadScript("get_library_list", {});

      if (!result.success) {
        logger.error(`Failed to retrieve library list: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to retrieve library list",
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }

      logger.debug(`Successfully retrieved ${result.libraries?.length || 0} libraries`);
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
  // Component Details Resource
  // ------------------------------------------------------
  server.resource(
    "component_details",
    new ResourceTemplate("kicad://component/{componentId}/{library?}", {
      list: undefined
    }),
    async (uri, params) => {
      const { componentId, library } = params;
      logger.debug(`Retrieving details for component: ${componentId}${library ? ` from library: ${library}` : ''}`);
      
      const result = await callKicadScript("get_component_details", {
        componentId,
        library
      });

      if (!result.success) {
        logger.error(`Failed to retrieve component details: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: `Failed to retrieve details for component ${componentId}`,
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }

      logger.debug(`Successfully retrieved details for component: ${componentId}`);
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
  // Component Footprint Resource
  // ------------------------------------------------------
  server.resource(
    "component_footprint",
    new ResourceTemplate("kicad://footprint/{componentId}/{footprint?}", {
      list: undefined
    }),
    async (uri, params) => {
      const { componentId, footprint } = params;
      logger.debug(`Retrieving footprint for component: ${componentId}${footprint ? ` (${footprint})` : ''}`);
      
      const result = await callKicadScript("get_component_footprint", {
        componentId,
        footprint
      });

      if (!result.success) {
        logger.error(`Failed to retrieve component footprint: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: `Failed to retrieve footprint for component ${componentId}`,
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }

      logger.debug(`Successfully retrieved footprint for component: ${componentId}`);
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
  // Component Symbol Resource
  // ------------------------------------------------------
  server.resource(
    "component_symbol",
    new ResourceTemplate("kicad://symbol/{componentId}", {
      list: undefined
    }),
    async (uri, params) => {
      const { componentId } = params;
      logger.debug(`Retrieving symbol for component: ${componentId}`);
      
      const result = await callKicadScript("get_component_symbol", {
        componentId
      });

      if (!result.success) {
        logger.error(`Failed to retrieve component symbol: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: `Failed to retrieve symbol for component ${componentId}`,
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }

      logger.debug(`Successfully retrieved symbol for component: ${componentId}`);

      // If the result includes SVG data, return it as SVG
      if (result.svgData) {
        return {
          contents: [{
            uri: uri.href,
            text: result.svgData,
            mimeType: "image/svg+xml"
          }]
        };
      }

      // Otherwise return the JSON result
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
  // Component 3D Model Resource
  // ------------------------------------------------------
  server.resource(
    "component_3d_model",
    new ResourceTemplate("kicad://3d-model/{componentId}/{footprint?}", {
      list: undefined
    }),
    async (uri, params) => {
      const { componentId, footprint } = params;
      logger.debug(`Retrieving 3D model for component: ${componentId}${footprint ? ` (${footprint})` : ''}`);
      
      const result = await callKicadScript("get_component_3d_model", {
        componentId,
        footprint
      });

      if (!result.success) {
        logger.error(`Failed to retrieve component 3D model: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: `Failed to retrieve 3D model for component ${componentId}`,
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }

      logger.debug(`Successfully retrieved 3D model for component: ${componentId}`);
      return {
        contents: [{
          uri: uri.href,
          text: JSON.stringify(result),
          mimeType: "application/json"
        }]
      };
    }
  );

  logger.info('Library resources registered');
}
