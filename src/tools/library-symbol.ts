/**
 * Symbol Library tools for KiCAD MCP server
 * Provides search/browse access to local KiCad symbol libraries
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';

export function registerSymbolLibraryTools(server: McpServer, callKicadScript: Function) {
  // List available symbol libraries
  server.tool(
    "list_symbol_libraries",
    "List all available KiCAD symbol libraries from global sym-lib-table",
    {},
    async () => {
      const result = await callKicadScript("list_symbol_libraries", {});
      if (result.success && result.libraries) {
        return {
          content: [
            {
              type: "text",
              text: `Found ${result.count} symbol libraries:\n${result.libraries.join('\n')}`
            }
          ]
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to list symbol libraries: ${result.message || 'Unknown error'}`
          }
        ]
      };
    }
  );

  // Search for symbols across all libraries
  server.tool(
    "search_symbols",
    `Search for symbols in local KiCAD symbol libraries.

Searches by: symbol name, LCSC ID, description, manufacturer, MPN, category.
Use this to find components already in your local libraries (e.g., JLCPCB-KiCad-Library).

Returns symbol references that can be used directly in schematics.`,
    {
      query: z.string()
        .describe("Search query (e.g., 'ESP32', 'STM32F103', 'C8734' for LCSC ID)"),
      library: z.string().optional()
        .describe("Optional: filter to specific library name pattern (e.g., 'JLCPCB')"),
      limit: z.number().optional().default(20)
        .describe("Maximum number of results to return")
    },
    async (args: { query: string; library?: string; limit?: number }) => {
      const result = await callKicadScript("search_symbols", args);
      if (result.success && result.symbols) {
        if (result.symbols.length === 0) {
          return {
            content: [
              {
                type: "text",
                text: `No symbols found matching "${args.query}"${args.library ? ` in libraries matching "${args.library}"` : ''}`
              }
            ]
          };
        }

        const symbolList = result.symbols.map((s: any) => {
          const parts = [`${s.full_ref}`];
          if (s.lcsc_id) parts.push(`LCSC: ${s.lcsc_id}`);
          if (s.description) parts.push(s.description);
          else if (s.value) parts.push(s.value);
          return parts.join(' | ');
        }).join('\n');

        return {
          content: [
            {
              type: "text",
              text: `Found ${result.count} symbols matching "${args.query}":\n\n${symbolList}`
            }
          ]
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to search symbols: ${result.message || 'Unknown error'}`
          }
        ]
      };
    }
  );

  // List symbols in a specific library
  server.tool(
    "list_library_symbols",
    "List all symbols in a specific KiCAD symbol library",
    {
      library: z.string()
        .describe("Library name (e.g., 'Device', 'PCM_JLCPCB-MCUs')")
    },
    async (args: { library: string }) => {
      const result = await callKicadScript("list_library_symbols", args);
      if (result.success && result.symbols) {
        const symbolList = result.symbols.map((s: any) => {
          const parts = [`  - ${s.name}`];
          if (s.lcsc_id) parts.push(`(LCSC: ${s.lcsc_id})`);
          return parts.join(' ');
        }).join('\n');

        return {
          content: [
            {
              type: "text",
              text: `Library "${args.library}" contains ${result.count} symbols:\n${symbolList}`
            }
          ]
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to list symbols in library ${args.library}: ${result.message || 'Unknown error'}`
          }
        ]
      };
    }
  );

  // Get detailed information about a specific symbol
  server.tool(
    "get_symbol_info",
    "Get detailed information about a specific symbol",
    {
      symbol: z.string()
        .describe("Symbol specification (e.g., 'Device:R' or 'PCM_JLCPCB-MCUs:STM32F103C8T6')")
    },
    async (args: { symbol: string }) => {
      const result = await callKicadScript("get_symbol_info", args);
      if (result.success && result.symbol_info) {
        const info = result.symbol_info;
        const details = [
          `Symbol: ${info.full_ref}`,
          info.value ? `Value: ${info.value}` : '',
          info.description ? `Description: ${info.description}` : '',
          info.lcsc_id ? `LCSC: ${info.lcsc_id}` : '',
          info.manufacturer ? `Manufacturer: ${info.manufacturer}` : '',
          info.mpn ? `MPN: ${info.mpn}` : '',
          info.footprint ? `Footprint: ${info.footprint}` : '',
          info.category ? `Category: ${info.category}` : '',
          info.lib_class ? `Class: ${info.lib_class}` : '',
          info.datasheet ? `Datasheet: ${info.datasheet}` : '',
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
            text: `Failed to get symbol info: ${result.message || 'Unknown error'}`
          }
        ]
      };
    }
  );
}
