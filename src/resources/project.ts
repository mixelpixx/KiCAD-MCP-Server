/**
 * Project resources for KiCAD MCP server
 * 
 * These resources provide information about the KiCAD project
 * to the LLM, enabling better context-aware assistance.
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { logger } from '../logger.js';

// Command function type for KiCAD script calls
type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

/**
 * Register project resources with the MCP server
 * 
 * @param server MCP server instance
 * @param callKicadScript Function to call KiCAD script commands
 */
export function registerProjectResources(server: McpServer, callKicadScript: CommandFunction): void {
  logger.info('Registering project resources');

  // ------------------------------------------------------
  // Project Information Resource
  // ------------------------------------------------------
  server.resource(
    "project_info",
    "kicad://project/info",
    async (uri) => {
      logger.debug('Retrieving project information');
      const result = await callKicadScript("get_project_info", {});
      
      if (!result.success) {
        logger.error(`Failed to retrieve project information: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to retrieve project information",
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      logger.debug('Successfully retrieved project information');
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
  // Project Properties Resource
  // ------------------------------------------------------
  server.resource(
    "project_properties",
    "kicad://project/properties",
    async (uri) => {
      logger.debug('Retrieving project properties');
      const result = await callKicadScript("get_project_properties", {});
      
      if (!result.success) {
        logger.error(`Failed to retrieve project properties: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to retrieve project properties",
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      logger.debug('Successfully retrieved project properties');
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
  // Project Files Resource
  // ------------------------------------------------------
  server.resource(
    "project_files",
    "kicad://project/files",
    async (uri) => {
      logger.debug('Retrieving project files');
      const result = await callKicadScript("get_project_files", {});
      
      if (!result.success) {
        logger.error(`Failed to retrieve project files: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to retrieve project files",
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      logger.debug(`Successfully retrieved ${result.files?.length || 0} project files`);
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
  // Project Status Resource
  // ------------------------------------------------------
  server.resource(
    "project_status",
    "kicad://project/status",
    async (uri) => {
      logger.debug('Retrieving project status');
      const result = await callKicadScript("get_project_status", {});
      
      if (!result.success) {
        logger.error(`Failed to retrieve project status: ${result.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to retrieve project status",
              details: result.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      logger.debug('Successfully retrieved project status');
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
  // Project Summary Resource
  // ------------------------------------------------------
  server.resource(
    "project_summary",
    "kicad://project/summary",
    async (uri) => {
      logger.debug('Generating project summary');
      
      // Get project info
      const infoResult = await callKicadScript("get_project_info", {});
      if (!infoResult.success) {
        logger.error(`Failed to retrieve project information: ${infoResult.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to generate project summary",
              details: infoResult.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      // Get board info
      const boardResult = await callKicadScript("get_board_info", {});
      if (!boardResult.success) {
        logger.error(`Failed to retrieve board information: ${boardResult.errorDetails}`);
        return {
          contents: [{
            uri: uri.href,
            text: JSON.stringify({
              error: "Failed to generate project summary",
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
              error: "Failed to generate project summary",
              details: componentsResult.errorDetails
            }),
            mimeType: "application/json"
          }]
        };
      }
      
      // Combine all information into a summary
      const summary = {
        project: infoResult.project,
        board: {
          size: boardResult.size,
          layers: boardResult.layers?.length || 0,
          title: boardResult.title
        },
        components: {
          count: componentsResult.components?.length || 0,
          types: countComponentTypes(componentsResult.components || [])
        }
      };
      
      logger.debug('Successfully generated project summary');
      return {
        contents: [{
          uri: uri.href,
          text: JSON.stringify(summary),
          mimeType: "application/json"
        }]
      };
    }
  );

  logger.info('Project resources registered');
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
