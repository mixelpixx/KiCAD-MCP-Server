/**
 * Router Tools for KiCAD MCP Server
 *
 * Provides supplemental discovery for the server's first-class MCP tools.
 */
import { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";
import { logger } from "../logger.js";
import {
  getAllCategories,
  getCategory,
  searchTools as registrySearchTools,
  getRegistryStats,
  getToolDefinition,
} from "./registry.js";
import { registerKiCadTool, type CommandFunction } from "./tool-registration.js";

// Command function type for KiCAD script calls

const categorySummarySchema = z.object({
  name: z.string(),
  description: z.string(),
  tool_count: z.number().int().nonnegative(),
});

const toolSummarySchema = z.object({
  name: z.string(),
  title: z.string().optional(),
  description: z.string().optional(),
});

const searchResultSchema = z.object({
  category: z.string(),
  tool: z.string(),
  description: z.string(),
});

/**
 * Register all router tools with the MCP server
 */
export function registerRouterTools(server: McpServer, _callKicadScript: CommandFunction): void {
  logger.info("Registering router tools");

  // ============================================================================
  // list_tool_categories
  // ============================================================================
  registerKiCadTool(
    server,
    "router",
    "list_tool_categories",
    {
      description:
        "List all available KiCAD tool categories with their descriptions and tool counts. Use this to discover which tools are available via the router.",
      inputSchema: z.object({
        // No parameters
      }),
      outputSchema: z.object({
        total_categories: z.number().int().nonnegative(),
        total_tools: z.number().int().nonnegative(),
        note: z.string(),
        categories: z.array(categorySummarySchema),
      }),
    },
    async () => {
      logger.debug("Listing tool categories");

      const stats = getRegistryStats();
      const categories = getAllCategories();

      const result = {
        total_categories: stats.total_categories,
        total_tools: stats.total_tools,
        note: "Use get_category_tools to browse a category. Every returned name is a first-class MCP tool and can be called directly.",
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
  registerKiCadTool(
    server,
    "router",
    "get_category_tools",
    {
      description:
        "Return all tools available in a specific category. Use list_tool_categories first to find valid category names.",
      inputSchema: z.object({
        category: z.string().describe("Category name from list_tool_categories"),
      }),
      outputSchema: z.union([
        z.object({
          category: z.string(),
          description: z.string(),
          tool_count: z.number().int().nonnegative(),
          tools: z.array(toolSummarySchema),
          note: z.string(),
        }),
        z.object({
          error: z.string(),
          available_categories: z.array(z.string()),
        }),
      ]),
    },
    async ({ category }) => {
      logger.debug(`Getting tools for category: ${category}`);

      const categoryData = getCategory(category);

      if (!categoryData) {
        const availableCategories = getAllCategories().map((c) => c.name);
        return {
          isError: true,
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

      const result = {
        category: categoryData.name,
        description: categoryData.description,
        tool_count: categoryData.tools.length,
        tools: categoryData.tools.map((toolName) => {
          const definition = getToolDefinition(toolName);
          return {
            name: toolName,
            title: definition?.title,
            description: definition?.description,
          };
        }),
        note: "Call any returned tool directly by its MCP name. Its input schema is available in tools/list.",
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
  registerKiCadTool(
    server,
    "router",
    "search_tools",
    {
      description:
        "Search all available KiCAD tools by keyword. Returns matching tool names and their categories.",
      inputSchema: z.object({
        query: z.string().describe("Search term (e.g., 'gerber', 'zone', 'export', 'drc')"),
      }),
      outputSchema: z.object({
        query: z.string(),
        count: z.number().int().nonnegative(),
        matches: z.array(searchResultSchema),
        note: z.string(),
      }),
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
            ? "Call a matching tool directly by its MCP name; its input schema is available in tools/list."
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
