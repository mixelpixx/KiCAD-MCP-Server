/**
 * Component resources for KiCAD MCP server
 * 
 * These resources provide information about components on the PCB
 * to the LLM, enabling better context-aware assistance.
 */

import { McpServer, ResourceTemplate } from '@modelcontextprotocol/sdk/server/mcp.js';
import { logger } from '../logger.js';

// Command function type for KiCAD script calls
type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

/**
 * Register component resources with the MCP server
 * 
 * @param server MCP server instance
 * @param callKicadScript Function to call KiCAD script commands
 */
export function registerComponentResources(server: McpServer, callKicadScript: CommandFunction): void {
  logger.info('Registering component resources');

  // ------------------------------------------------------
  // Component List Resource
  // ------------------------------------------------------
  server.resource(
    "component_list",
    "kicad://components",
    async (uri) => {
      logger.debug('Retrieving component list');
      const result = await callKicadScript("get_component_list", {});
      
      if (!result.success) {
        logger.error(`Failed to retrieve component list: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to retrieve component list",
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      logger.debug(`Successfully retrieved ${result.components?.length || 0} components`);
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
    new ResourceTemplate("kicad://component/{reference}/details", {
      list: undefined
    }),
    async (uri, params) => {
      const { reference } = params;
      logger.debug(`Retrieving details for component: ${reference}`);
      const result = await callKicadScript("get_component_properties", {
        reference
      });
      
      if (!result.success) {
        logger.error(`Failed to retrieve component details: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: `Failed to retrieve details for component ${reference}`,
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      logger.debug(`Successfully retrieved details for component: ${reference}`);
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
  // Component Connections Resource
  // ------------------------------------------------------
  server.resource(
    "component_connections",
    new ResourceTemplate("kicad://component/{reference}/connections", {
      list: undefined
    }),
    async (uri, params) => {
      const { reference } = params;
      logger.debug(`Retrieving connections for component: ${reference}`);
      const result = await callKicadScript("get_component_connections", {
        reference
      });
      
      if (!result.success) {
        logger.error(`Failed to retrieve component connections: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: `Failed to retrieve connections for component ${reference}`,
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      logger.debug(`Successfully retrieved connections for component: ${reference}`);
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
  // Component Placement Resource
  // ------------------------------------------------------
  server.resource(
    "component_placement",
    "kicad://components/placement",
    async (uri) => {
      logger.debug('Retrieving component placement information');
      const result = await callKicadScript("get_component_placement", {});
      
      if (!result.success) {
        logger.error(`Failed to retrieve component placement: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to retrieve component placement information",
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      logger.debug('Successfully retrieved component placement information');
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
  // Component Groups Resource
  // ------------------------------------------------------
  server.resource(
    "component_groups",
    "kicad://components/groups",
    async (uri) => {
      logger.debug('Retrieving component groups');
      const result = await callKicadScript("get_component_groups", {});
      
      if (!result.success) {
        logger.error(`Failed to retrieve component groups: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to retrieve component groups",
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      logger.debug(`Successfully retrieved ${result.groups?.length || 0} component groups`);
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
  // Component Visualization Resource
  // ------------------------------------------------------
  server.resource(
    "component_visualization",
    new ResourceTemplate("kicad://component/{reference}/visualization", {
      list: undefined
    }),
    async (uri, params) => {
      const { reference } = params;
      logger.debug(`Generating visualization for component: ${reference}`);
      const result = await callKicadScript("get_component_visualization", {
        reference
      });
      
      if (!result.success) {
        logger.error(`Failed to generate component visualization: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: `Failed to generate visualization for component ${reference}`,
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      logger.debug(`Successfully generated visualization for component: ${reference}`);
      return {
        contents: [{
          uri: uri.href,
          blob: result.imageData,  // Base64 encoded image data
          mimeType: "image/png"
        }]
      };
    }
  );

  logger.info('Component resources registered');
}
