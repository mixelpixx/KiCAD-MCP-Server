/**
 * Router Tools for KiCAD MCP Server
 *
 * Provides discovery and execution of routed tools
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { logger } from '../logger.js';
import {
  getAllCategories,
  getCategory,
  getToolCategory,
  searchTools as registrySearchTools,
  getRegistryStats
} from './registry.js';

// Command function type for KiCAD script calls
type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

// Map to store tool execution handlers
// This will be populated by registerToolHandler()
const toolHandlers = new Map<string, (params: any) => Promise<any>>();

/**
 * Register a tool handler for execution via execute_tool
 * This should be called by each tool registration function
 */
export function registerToolHandler(
  toolName: string,
  handler: (params: any) => Promise<any>
): void {
  toolHandlers.set(toolName, handler);
  logger.debug(`Registered handler for routed tool: ${toolName}`);
}

/**
 * Register all router tools with the MCP server
 */
export function registerRouterTools(server: McpServer, callKicadScript: CommandFunction): void {
  logger.info('Registering router tools');

  // ============================================================================
  // list_tool_categories
  // ============================================================================
  server.tool(
    "list_tool_categories",
    {
      // No parameters
    },
    async () => {
      logger.debug('Listing tool categories');

      const stats = getRegistryStats();
      const categories = getAllCategories();

      const result = {
        total_categories: stats.total_categories,
        total_routed_tools: stats.total_routed_tools,
        total_direct_tools: stats.total_direct_tools,
        note: "Use get_category_tools to see tools in each category. Direct tools are always available.",
        categories: categories.map(c => ({
          name: c.name,
          description: c.description,
          tool_count: c.tools.length
        }))
      };

      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // ============================================================================
  // get_category_tools
  // ============================================================================
  server.tool(
    "get_category_tools",
    {
      category: z.string().describe("Category name from list_tool_categories")
    },
    async ({ category }) => {
      logger.debug(`Getting tools for category: ${category}`);

      const categoryData = getCategory(category);

      if (!categoryData) {
        const availableCategories = getAllCategories().map(c => c.name);
        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              error: `Unknown category: ${category}`,
              available_categories: availableCategories
            }, null, 2)
          }]
        };
      }

      // Return tool names and basic info
      // Full schema is available via tool introspection once tool is called
      const result = {
        category: categoryData.name,
        description: categoryData.description,
        tool_count: categoryData.tools.length,
        tools: categoryData.tools.map(toolName => ({
          name: toolName,
          description: `Use execute_tool with tool_name="${toolName}" to run this tool`
        })),
        note: "Use execute_tool to run any of these tools with appropriate parameters"
      };

      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  // ============================================================================
  // execute_tool
  // ============================================================================
  server.tool(
    "execute_tool",
    {
      tool_name: z.string().describe("Tool name from get_category_tools"),
      params: z.record(z.unknown()).optional().describe("Tool parameters (optional)")
    },
    async ({ tool_name, params }) => {
      logger.info(`Executing routed tool: ${tool_name}`);

      // Check if tool exists in registry
      const category = getToolCategory(tool_name);

      if (!category) {
        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              error: `Unknown tool: ${tool_name}`,
              hint: "Use list_tool_categories and get_category_tools to find available tools"
            }, null, 2)
          }]
        };
      }

      // Get the handler
      const handler = toolHandlers.get(tool_name);

      if (!handler) {
        // Tool is in registry but handler not registered yet
        // This means the tool exists but hasn't been migrated to router pattern yet
        // Fall back to calling KiCAD script directly
        logger.warn(`Tool ${tool_name} in registry but no handler registered, falling back to direct call`);

        try {
          const result = await callKicadScript(tool_name, params || {});
          return {
            content: [{
              type: "text",
              text: JSON.stringify({
                tool: tool_name,
                category: category,
                result: result
              }, null, 2)
            }]
          };
        } catch (error) {
          return {
            content: [{
              type: "text",
              text: JSON.stringify({
                error: `Tool execution failed: ${(error as Error).message}`,
                tool: tool_name,
                category: category
              }, null, 2)
            }]
          };
        }
      }

      // Execute the tool via its handler
      try {
        const result = await handler(params || {});

        // The handler already returns MCP-formatted response
        // Just add metadata
        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              tool: tool_name,
              category: category,
              ...result
            }, null, 2)
          }]
        };
      } catch (error) {
        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              error: `Tool execution failed: ${(error as Error).message}`,
              tool: tool_name,
              category: category
            }, null, 2)
          }]
        };
      }
    }
  );

  // ============================================================================
  // search_tools
  // ============================================================================
  server.tool(
    "search_tools",
    {
      query: z.string().describe("Search term (e.g., 'gerber', 'zone', 'export', 'drc')")
    },
    async ({ query }) => {
      logger.debug(`Searching tools for: ${query}`);

      const matches = registrySearchTools(query);

      const result = {
        query: query,
        count: matches.length,
        matches: matches,
        note: matches.length > 0
          ? "Use execute_tool with the tool name to run it"
          : "No tools found matching your query. Try list_tool_categories to browse all categories."
      };

      return {
        content: [{
          type: "text",
          text: JSON.stringify(result, null, 2)
        }]
      };
    }
  );

  logger.info('Router tools registered successfully');
}
