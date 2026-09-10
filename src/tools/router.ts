/**
 * Tool discovery for the KiCAD MCP Server.
 *
 * These three tools browse and search the registry in `registry.ts`. They do
 * not execute anything on the caller's behalf. Every tool is registered
 * directly with the server and is callable by name, so discovery is a search
 * catalogue rather than a gate.
 *
 * The original gated design routed calls through a single `execute_tool`. It
 * was disabled in 3d9497e because indirect execution made the model
 * hallucinate tool schemas, and `execute_tool` was deleted in 963a39c. Response
 * text here must therefore never tell a client to call `execute_tool`; see
 * tests-ts/no-stale-tool-references.test.ts, which enforces that.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { logger } from "../logger.js";
import {
  getAllCategories,
  getCategory,
  searchTools as registrySearchTools,
  getRegistryStats,
} from "./registry.js";

// Command function type for KiCAD script calls
type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

/**
 * Register all router tools with the MCP server
 */
export function registerRouterTools(server: McpServer, _callKicadScript: CommandFunction): void {
  logger.info("Registering router tools");

  // ============================================================================
  // list_tool_categories
  // ============================================================================
  server.tool(
    "list_tool_categories",
    "List all available KiCAD tool categories with their descriptions and tool counts. Use this to discover which tools exist; every tool can then be called directly by name.",
    {
      // No parameters
    },
    async () => {
      logger.debug("Listing tool categories");

      const stats = getRegistryStats();
      const categories = getAllCategories();

      const result = {
        total_categories: stats.total_categories,
        total_routed_tools: stats.total_routed_tools,
        total_direct_tools: stats.total_direct_tools,
        note: "Use get_category_tools to see the tools in each category. Every tool is registered directly on the server and is called by name.",
        categories: categories.map((c) => ({
          name: c.name,
          description: c.description,
          tool_count: c.tools.length,
        })),
      };

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  // ============================================================================
  // get_category_tools
  // ============================================================================
  server.tool(
    "get_category_tools",
    "Return all tools available in a specific category. Use list_tool_categories first to find valid category names.",
    {
      category: z.string().describe("Category name from list_tool_categories"),
    },
    async ({ category }) => {
      logger.debug(`Getting tools for category: ${category}`);

      const categoryData = getCategory(category);

      if (!categoryData) {
        const availableCategories = getAllCategories().map((c) => c.name);
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(
                {
                  error: `Unknown category: ${category}`,
                  available_categories: availableCategories,
                },
                null,
                2,
              ),
            },
          ],
        };
      }

      // Return tool names and basic info
      // Full schema is available via tool introspection once tool is called
      const result = {
        category: categoryData.name,
        description: categoryData.description,
        tool_count: categoryData.tools.length,
        tools: categoryData.tools.map((toolName) => ({
          name: toolName,
          description: `Call ${toolName} directly by name.`,
        })),
        note: "Call any of these tools directly by name with its own parameters.",
      };

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  // ============================================================================
  // search_tools
  // ============================================================================
  server.tool(
    "search_tools",
    "Search all available KiCAD tools by keyword. Returns matching tool names and their categories.",
    {
      query: z.string().describe("Search term (e.g., 'gerber', 'zone', 'export', 'drc')"),
    },
    async ({ query }) => {
      logger.debug(`Searching tools for: ${query}`);

      const matches = registrySearchTools(query);

      const result = {
        query: query,
        count: matches.length,
        matches: matches,
        note:
          matches.length > 0
            ? "Call a matching tool directly by name with its own parameters."
            : "No tools found matching your query. Try list_tool_categories to browse all categories.",
      };

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  logger.info("Router tools registered successfully");
}
