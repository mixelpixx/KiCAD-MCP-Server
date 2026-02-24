/**
 * JLCPCB API tools for KiCAD MCP server
 * Provides access to JLCPCB's complete parts catalog via their API
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';

export function registerJLCPCBApiTools(server: McpServer, callKicadScript: Function) {
  // Download JLCPCB parts database
  server.tool(
    "download_jlcpcb_database",
    `Download the complete JLCPCB parts catalog to local database.

This is a one-time setup that downloads JLCPCB parts into a local SQLite database.
Use source='official' for full-catalog download (requires JLCPCB_APP_ID, JLCPCB_API_KEY, JLCPCB_API_SECRET).
Use source='jlcsearch' as public fallback when official credentials are unavailable.

The download takes 5-10 minutes and creates a local SQLite database
for fast offline searching.`,
    {
      force: z.boolean().optional().default(false)
        .describe("Force re-download even if database exists"),
      source: z.enum(["auto", "official", "jlcsearch"]).optional().default("auto")
        .describe("Download source: auto-detect, official JLCPCB API, or JLCSearch fallback")
    },
    async (args: { force?: boolean; source?: "auto" | "official" | "jlcsearch" }) => {
      const result = await callKicadScript("download_jlcpcb_database", args);
      if (result.success) {
        const warningLine = result.warning ? `\nWarning: ${result.warning}` : '';
        return {
          content: [{
            type: "text",
            text: `✓ Successfully downloaded JLCPCB parts database\n\n` +
                  `Source: ${result.source || 'unknown'}\n` +
                  `Total parts: ${result.total_parts}\n` +
                  `Basic parts: ${result.basic_parts}\n` +
                  `Extended parts: ${result.extended_parts}\n` +
                  `Database size: ${result.db_size_mb} MB\n` +
                  `Database path: ${result.db_path}` +
                  warningLine
          }]
        };
      }
      return {
        content: [{
          type: "text",
          text: `✗ Failed to download JLCPCB database: ${result.message || 'Unknown error'}\n\n` +
                `For official source, set JLCPCB_APP_ID, JLCPCB_API_KEY, and JLCPCB_API_SECRET.`
        }]
      };
    }
  );

  // Search JLCPCB parts
  server.tool(
    "search_jlcpcb_parts",
    `Search JLCPCB parts catalog by specifications.

Searches the local JLCPCB database (must be downloaded first with download_jlcpcb_database).
Provides real pricing, stock info, and library type (Basic parts = free assembly).

Use this to find components with exact specifications and cost optimization.`,
    {
      query: z.string().optional()
        .describe("Free-text search (e.g., '10k resistor 0603', 'ESP32', 'STM32F103')"),
      category: z.string().optional()
        .describe("Filter by category (e.g., 'Resistors', 'Capacitors', 'Microcontrollers')"),
      package: z.string().optional()
        .describe("Filter by package type (e.g., '0603', 'SOT-23', 'QFN-32')"),
      library_type: z.enum(["Basic", "Extended", "Preferred", "All"]).optional().default("All")
        .describe("Filter by library type (Basic = free assembly at JLCPCB)"),
      manufacturer: z.string().optional()
        .describe("Filter by manufacturer name"),
      in_stock: z.boolean().optional().default(true)
        .describe("Only show parts with available stock"),
      limit: z.number().optional().default(20)
        .describe("Maximum number of results to return")
    },
    async (args: any) => {
      const result = await callKicadScript("search_jlcpcb_parts", args);
      if (result.success && result.parts) {
        if (result.parts.length === 0) {
          return {
            content: [{
              type: "text",
              text: `No JLCPCB parts found matching your criteria.\n\n` +
                    `Try broadening your search or check if the database is populated.`
            }]
          };
        }

        const partsList = result.parts.map((p: any) => {
          const priceInfo = p.price_breaks && p.price_breaks.length > 0
            ? ` - $${p.price_breaks[0].price}/ea`
            : '';
          const stockInfo = p.stock > 0 ? ` (${p.stock} in stock)` : ' (out of stock)';
          return `${p.lcsc}: ${p.mfr_part} - ${p.description} [${p.library_type}]${priceInfo}${stockInfo}`;
        }).join('\n');

        return {
          content: [{
            type: "text",
            text: `Found ${result.count} JLCPCB parts:\n\n${partsList}\n\n` +
                  `💡 Basic parts have free assembly. Extended parts charge $3 setup fee per unique part.`
          }]
        };
      }
      return {
        content: [{
          type: "text",
          text: `Failed to search JLCPCB parts: ${result.message || 'Unknown error'}\n\n` +
                `Make sure you've downloaded the database first using download_jlcpcb_database.`
        }]
      };
    }
  );

  // Get JLCPCB part details
  server.tool(
    "get_jlcpcb_part",
    "Get detailed information about a specific JLCPCB part by LCSC number",
    {
      lcsc_number: z.string()
        .describe("LCSC part number (e.g., 'C25804', 'C2286')")
    },
    async (args: { lcsc_number: string }) => {
      const result = await callKicadScript("get_jlcpcb_part", args);
      if (result.success && result.part) {
        const p = result.part;
        const priceTable = p.price_breaks && p.price_breaks.length > 0
          ? '\n\nPrice Breaks:\n' + p.price_breaks.map((pb: any) =>
              `  ${pb.qty}+: $${pb.price}/ea`
            ).join('\n')
          : '';

        const footprints = result.footprints && result.footprints.length > 0
          ? '\n\nSuggested KiCAD Footprints:\n' + result.footprints.map((f: string) =>
              `  - ${f}`
            ).join('\n')
          : '';

        return {
          content: [{
            type: "text",
            text: `LCSC: ${p.lcsc}\n` +
                  `MFR Part: ${p.mfr_part}\n` +
                  `Manufacturer: ${p.manufacturer}\n` +
                  `Category: ${p.category} / ${p.subcategory}\n` +
                  `Package: ${p.package}\n` +
                  `Description: ${p.description}\n` +
                  `Library Type: ${p.library_type} ${p.library_type === 'Basic' ? '(Free assembly!)' : ''}\n` +
                  `Stock: ${p.stock}\n` +
                  (p.datasheet ? `Datasheet: ${p.datasheet}\n` : '') +
                  priceTable +
                  footprints
          }]
        };
      }
      return {
        content: [{
          type: "text",
          text: `Part not found: ${args.lcsc_number}\n\n` +
                `Make sure you've downloaded the JLCPCB database first.`
        }]
      };
    }
  );

  // Get JLCPCB database statistics
  server.tool(
    "get_jlcpcb_database_stats",
    "Get statistics about the local JLCPCB parts database",
    {},
    async () => {
      const result = await callKicadScript("get_jlcpcb_database_stats", {});
      if (result.success) {
        const stats = result.stats;
        return {
          content: [{
            type: "text",
            text: `JLCPCB Database Statistics:\n\n` +
                  `Total parts: ${stats.total_parts.toLocaleString()}\n` +
                  `Basic parts: ${stats.basic_parts.toLocaleString()} (free assembly)\n` +
                  `Extended parts: ${stats.extended_parts.toLocaleString()} ($3 setup fee each)\n` +
                  `In stock: ${stats.in_stock.toLocaleString()}\n` +
                  `Database path: ${stats.db_path}`
          }]
        };
      }
      return {
        content: [{
          type: "text",
          text: `JLCPCB database not found or empty.\n\n` +
                `Run download_jlcpcb_database first to populate the database.`
        }]
      };
    }
  );

  // Suggest alternative parts
  server.tool(
    "suggest_jlcpcb_alternatives",
    `Suggest alternative JLCPCB parts for a given component.

Finds similar parts that may be cheaper, have more stock, or are Basic library type.
Useful for cost optimization and finding alternatives when parts are out of stock.`,
    {
      lcsc_number: z.string()
        .describe("Reference LCSC part number to find alternatives for"),
      limit: z.number().optional().default(5)
        .describe("Maximum number of alternatives to return")
    },
    async (args: { lcsc_number: string; limit?: number }) => {
      const result = await callKicadScript("suggest_jlcpcb_alternatives", args);
      if (result.success && result.alternatives) {
        if (result.alternatives.length === 0) {
          return {
            content: [{
              type: "text",
              text: `No alternatives found for ${args.lcsc_number}`
            }]
          };
        }

        const altsList = result.alternatives.map((p: any, i: number) => {
          const priceInfo = p.price_breaks && p.price_breaks.length > 0
            ? ` - $${p.price_breaks[0].price}/ea`
            : '';
          const savings = result.reference_price && p.price_breaks && p.price_breaks.length > 0
            ? ` (${((1 - p.price_breaks[0].price / result.reference_price) * 100).toFixed(0)}% cheaper)`
            : '';
          return `${i + 1}. ${p.lcsc}: ${p.mfr_part} [${p.library_type}]${priceInfo}${savings}\n   ${p.description}\n   Stock: ${p.stock}`;
        }).join('\n\n');

        return {
          content: [{
            type: "text",
            text: `Alternative parts for ${args.lcsc_number}:\n\n${altsList}`
          }]
        };
      }
      return {
        content: [{
          type: "text",
          text: `Failed to find alternatives: ${result.message || 'Unknown error'}`
        }]
      };
    }
  );
}
