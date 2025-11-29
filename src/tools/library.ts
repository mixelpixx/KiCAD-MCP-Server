/**
 * Library tools for KiCAD MCP server
 * Provides access to KiCAD footprint libraries and symbols
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';

export function registerLibraryTools(server: McpServer, callKicadScript: Function) {
  // List available footprint libraries
  server.tool(
    "list_libraries",
    "List all available KiCAD footprint libraries",
    {
      search_paths: z.array(z.string()).optional()
        .describe("Optional additional search paths for libraries")
    },
    async (args: { search_paths?: string[] }) => {
      const result = await callKicadScript("list_libraries", args);
      if (result.success && result.libraries) {
        return {
          content: [
            {
              type: "text",
              text: `Found ${result.libraries.length} footprint libraries:\n${result.libraries.join('\n')}`
            }
          ]
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to list libraries: ${result.message || 'Unknown error'}`
          }
        ]
      };
    }
  );

  // Search for footprints across all libraries
  server.tool(
    "search_footprints",
    "Search for footprints matching a pattern across all libraries",
    {
      search_term: z.string()
        .describe("Search term or pattern to match footprint names"),
      library: z.string().optional()
        .describe("Optional specific library to search in"),
      limit: z.number().optional().default(50)
        .describe("Maximum number of results to return")
    },
    async (args: { search_term: string; library?: string; limit?: number }) => {
      const result = await callKicadScript("search_footprints", args);
      if (result.success && result.footprints) {
        const footprintList = result.footprints.map((fp: any) =>
          `${fp.library}:${fp.name}${fp.description ? ' - ' + fp.description : ''}`
        ).join('\n');
        return {
          content: [
            {
              type: "text",
              text: `Found ${result.footprints.length} matching footprints:\n${footprintList}`
            }
          ]
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to search footprints: ${result.message || 'Unknown error'}`
          }
        ]
      };
    }
  );

  // List footprints in a specific library
  server.tool(
    "list_library_footprints",
    "List all footprints in a specific KiCAD library",
    {
      library_name: z.string()
        .describe("Name of the library to list footprints from"),
      filter: z.string().optional()
        .describe("Optional filter pattern for footprint names"),
      limit: z.number().optional().default(100)
        .describe("Maximum number of footprints to list")
    },
    async (args: { library_name: string; filter?: string; limit?: number }) => {
      const result = await callKicadScript("list_library_footprints", args);
      if (result.success && result.footprints) {
        const footprintList = result.footprints.map((fp: string) => `  - ${fp}`).join('\n');
        return {
          content: [
            {
              type: "text",
              text: `Library ${args.library_name} contains ${result.footprints.length} footprints:\n${footprintList}`
            }
          ]
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to list footprints in library ${args.library_name}: ${result.message || 'Unknown error'}`
          }
        ]
      };
    }
  );

  // Get detailed information about a specific footprint
  server.tool(
    "get_footprint_info",
    "Get detailed information about a specific footprint",
    {
      library_name: z.string()
        .describe("Name of the library containing the footprint"),
      footprint_name: z.string()
        .describe("Name of the footprint to get information about")
    },
    async (args: { library_name: string; footprint_name: string }) => {
      const result = await callKicadScript("get_footprint_info", args);
      if (result.success && result.info) {
        const info = result.info;
        const details = [
          `Footprint: ${info.name}`,
          `Library: ${info.library}`,
          info.description ? `Description: ${info.description}` : '',
          info.keywords ? `Keywords: ${info.keywords}` : '',
          info.pads ? `Number of pads: ${info.pads}` : '',
          info.layers ? `Layers used: ${info.layers.join(', ')}` : '',
          info.courtyard ? `Courtyard size: ${info.courtyard.width}mm x ${info.courtyard.height}mm` : '',
          info.attributes ? `Attributes: ${JSON.stringify(info.attributes)}` : ''
        ].filter(line => line).join('\n');

        return {
          content: [
            {
              type: "text",
              text: details
            }
          ]
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to get footprint info: ${result.message || 'Unknown error'}`
          }
        ]
      };
    }
  );
}