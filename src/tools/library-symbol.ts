/**
 * Symbol Library tools for KiCAD MCP server
 * Provides search/browse access to local KiCad symbol libraries
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerSymbolLibraryTools(server: McpServer, callKicadScript: Function) {
  // List available symbol libraries
  server.tool(
    "list_symbol_libraries",
    "List all available KiCAD symbol libraries from global sym-lib-table, plus the project's sym-lib-table when projectPath (or any related file) is supplied or a project has been opened.",
    {
      projectPath: z
        .string()
        .optional()
        .describe(
          "Optional: project directory or .kicad_pro/.kicad_pcb/.kicad_sch path. Including this exposes project-scope sym-lib-table libraries.",
        ),
    },
    async (args: { projectPath?: string }) => {
      const result = await callKicadScript("list_symbol_libraries", args);
      if (result.success && result.libraries) {
        return {
          content: [
            {
              type: "text",
              text: `Found ${result.count} symbol libraries:\n${result.libraries.join("\n")}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to list symbol libraries: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // Repair flat vendor symbols (no _1_1 sub-unit) that break kicad-skip
  server.tool(
    "repair_flat_symbols",
    `Repair "flat" vendor symbols so schematic tools can parse the file.

SnapEDA/SamacSys .kicad_sym captures often put pins and graphics directly
under the top-level (symbol "NAME" ...) with no _1_1 sub-unit. KiCad and
kicad-cli tolerate this, but the kicad-skip parser used by the schematic
edit/inspect tools (list_schematic_components, batch_connect, ...) crashes
on it — for any sheet that uses, or embeds a snapshot of, such a symbol.

This tool wraps the drawable/pin children in a proper (symbol "NAME_1_1")
sub-unit via pure text insertion (formatting preserved, render-neutral).
Works on standalone .kicad_sym libraries and on the embedded (lib_symbols)
block of a .kicad_sch. Idempotent; already-wrapped and extends-derived
symbols are skipped. Dry-run by default — files are edited in place, so
keep them under version control before repairing.`,
    {
      path: z.string().describe(".kicad_sym library or .kicad_sch schematic to repair"),
      dryRun: z
        .boolean()
        .optional()
        .default(true)
        .describe("Report flat symbols without writing (default true)"),
    },
    async (args: { path: string; dryRun?: boolean }) => {
      const result = await callKicadScript("repair_flat_symbols", args);
      if (!result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Failed to repair: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
      const lines = [result.message];
      if (result.flat_symbols_found?.length) {
        lines.push(`Flat symbols: ${result.flat_symbols_found.join(", ")}`);
      }
      if (result.repaired?.length) {
        lines.push(`Repaired: ${result.repaired.join(", ")}`);
      } else if (result.dryRun) {
        lines.push("Dry run — pass dryRun: false to write the repair.");
      }
      return { content: [{ type: "text", text: lines.join("\n") }] };
    },
  );

  // Search for symbols across all libraries
  server.tool(
    "search_symbols",
    `Search for symbols in local KiCAD symbol libraries.

Searches by: symbol name, LCSC ID, description, manufacturer, MPN, category.
Use this to find components already in your local libraries (e.g., JLCPCB-KiCad-Library).

Returns symbol references that can be used directly in schematics.`,
    {
      query: z.string().describe("Search query (e.g., 'ESP32', 'STM32F103', 'C8734' for LCSC ID)"),
      library: z
        .string()
        .optional()
        .describe("Optional: filter to specific library name pattern (e.g., 'JLCPCB')"),
      limit: z.number().optional().default(20).describe("Maximum number of results to return"),
      rebuildIndex: z
        .boolean()
        .optional()
        .describe("Force re-parse of symbol libraries, ignoring the persistent index"),
      projectPath: z
        .string()
        .optional()
        .describe(
          "Optional: project directory or .kicad_pro/.kicad_pcb/.kicad_sch path so project-scope sym-lib-table libraries are searched too.",
        ),
    },
    async (args: {
      query: string;
      library?: string;
      limit?: number;
      projectPath?: string;
      rebuildIndex?: boolean;
    }) => {
      const result = await callKicadScript("search_symbols", args);
      if (result.success && result.symbols) {
        if (result.symbols.length === 0) {
          return {
            content: [
              {
                type: "text",
                text: `No symbols found matching "${args.query}"${args.library ? ` in libraries matching "${args.library}"` : ""}`,
              },
            ],
          };
        }

        const symbolList = result.symbols
          .map((s: any) => {
            const parts = [`${s.full_ref}`];
            if (s.lcsc_id) parts.push(`LCSC: ${s.lcsc_id}`);
            if (s.description) parts.push(s.description);
            else if (s.value) parts.push(s.value);
            return parts.join(" | ");
          })
          .join("\n");

        return {
          content: [
            {
              type: "text",
              text: `Found ${result.count} symbols matching "${args.query}":\n\n${symbolList}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to search symbols: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // List symbols in a specific library
  server.tool(
    "list_library_symbols",
    "List all symbols in a specific KiCAD symbol library (global or project-scope when projectPath is supplied or a project has been opened).",
    {
      library: z.string().describe("Library name (e.g., 'Device', 'PCM_JLCPCB-MCUs')"),
      projectPath: z
        .string()
        .optional()
        .describe(
          "Optional: project directory or .kicad_pro/.kicad_pcb/.kicad_sch path to resolve project-scope libraries.",
        ),
    },
    async (args: { library: string; projectPath?: string }) => {
      const result = await callKicadScript("list_library_symbols", args);
      if (result.success && result.symbols) {
        const symbolList = result.symbols
          .map((s: any) => {
            const parts = [`  - ${s.name}`];
            if (s.lcsc_id) parts.push(`(LCSC: ${s.lcsc_id})`);
            return parts.join(" ");
          })
          .join("\n");

        return {
          content: [
            {
              type: "text",
              text: `Library "${args.library}" contains ${result.count} symbols:\n${symbolList}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to list symbols in library ${args.library}: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // Get detailed information about a specific symbol
  server.tool(
    "get_symbol_info",
    "Get detailed information about a specific symbol (global or project-scope when projectPath is supplied or a project has been opened).",
    {
      symbol: z
        .string()
        .describe("Symbol specification (e.g., 'Device:R' or 'PCM_JLCPCB-MCUs:STM32F103C8T6')"),
      projectPath: z
        .string()
        .optional()
        .describe(
          "Optional: project directory or .kicad_pro/.kicad_pcb/.kicad_sch path so project-scope libraries are searched.",
        ),
    },
    async (args: { symbol: string; projectPath?: string }) => {
      const result = await callKicadScript("get_symbol_info", args);
      if (result.success && result.symbol_info) {
        const info = result.symbol_info;
        const details = [
          `Symbol: ${info.full_ref}`,
          info.value ? `Value: ${info.value}` : "",
          info.description ? `Description: ${info.description}` : "",
          info.lcsc_id ? `LCSC: ${info.lcsc_id}` : "",
          info.manufacturer ? `Manufacturer: ${info.manufacturer}` : "",
          info.mpn ? `MPN: ${info.mpn}` : "",
          info.footprint ? `Footprint: ${info.footprint}` : "",
          info.category ? `Category: ${info.category}` : "",
          info.lib_class ? `Class: ${info.lib_class}` : "",
          info.datasheet ? `Datasheet: ${info.datasheet}` : "",
          info.sim_pins ? `Sim.Pins: ${info.sim_pins}` : "",
        ]
          .filter((line) => line)
          .join("\n");

        return {
          content: [
            {
              type: "text",
              text: details,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to get symbol info: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // List pins for a symbol from the library (no schematic needed)
  server.tool(
    "list_symbol_pins",
    "Return pin names, numbers, and types for a symbol directly from the library — no schematic required. Use this before add_schematic_component to discover pins for connect_to_net calls. Each pin has 'number' (e.g. '1', 'A5') and 'name' (e.g. 'FB', 'GND') — connect_to_net accepts either. Pass schematicPath to resolve project-local symbols. Returns close-match suggestions if the symbol name is slightly wrong.",
    {
      symbol: z
        .string()
        .describe("Symbol in 'Library:SymbolName' format (e.g., Device:R, Connector:Conn_01x04)"),
      schematicPath: z
        .string()
        .optional()
        .describe("Path to .kicad_sch — enables project-local sym-lib-table lookup"),
    },
    async (args: { symbol: string; schematicPath?: string }) => {
      const result = await callKicadScript("list_symbol_pins", args);
      if (result.success) {
        if (result.pins.length === 0) {
          return {
            content: [{ type: "text", text: `Symbol ${result.symbol} has no pins.` }],
          };
        }
        const lines = result.pins.map(
          (p: any) => `  Pin ${p.number} (${p.name}) — type: ${p.type}`,
        );
        return {
          content: [
            {
              type: "text",
              text: `${result.symbol} — ${result.pin_count} pin(s):\n${lines.join("\n")}`,
            },
          ],
        };
      }
      const hint = result.suggestions?.length
        ? `\nDid you mean: ${result.suggestions.join(", ")}?`
        : "";
      return {
        content: [
          {
            type: "text",
            text: `Failed to list pins: ${result.message || "Unknown error"}${hint}`,
          },
        ],
      };
    },
  );

  // List pins for multiple symbols in one call
  server.tool(
    "batch_list_symbol_pins",
    "Return pin names, numbers, types, and symbol-local coordinates for multiple symbols in a single call. Use instead of calling list_symbol_pins repeatedly when placing a subcircuit — saves 5–10 round-trips. Each result includes pins (with x/y/angle in symbol-local coords, Y-up per KiCAD lib convention) and body_bbox (bounding box of pin envelope ±1.27mm, symbol-local coords). IMPORTANT: coordinates are symbol-local (Y-up, pre-rotation); after placement use get_schematic_pin_locations for post-rotation schematic coordinates. Set compact=true for simple 2-pin passives (Device:R/C/L) to get just pin_count, body_bbox, and is_symmetric.",
    {
      symbols: z
        .array(z.string())
        .describe(
          "Array of symbols in 'Library:SymbolName' format (e.g., ['Device:R', 'Device:C'])",
        ),
      schematicPath: z
        .string()
        .optional()
        .describe("Path to .kicad_sch — enables project-local sym-lib-table lookup"),
      compact: z
        .boolean()
        .optional()
        .describe("If true, omit per-pin detail for standard 2-pin symmetric passives."),
    },
    async (args: { symbols: string[]; schematicPath?: string; compact?: boolean }) => {
      const result = await callKicadScript("batch_list_symbol_pins", args);
      if (result.success !== false || (result.symbols && Object.keys(result.symbols).length > 0)) {
        const lines: string[] = [];
        for (const [sym, data] of Object.entries(result.symbols || {})) {
          const d = data as any;
          const bb = d.body_bbox;
          const bboxStr = bb ? ` | body ${bb.width.toFixed(2)}×${bb.height.toFixed(2)}mm` : "";
          if (d.is_symmetric && d.compact) {
            lines.push(`${sym} — ${d.pin_count} pin(s), symmetric${bboxStr}`);
          } else {
            const pinLines = (d.pins || []).map((p: any) => {
              const coords = p.x !== undefined ? ` at (${p.x},${p.y}) angle=${p.angle}` : "";
              return `    Pin ${p.number} (${p.name}) — type: ${p.type}${coords}`;
            });
            lines.push(`${sym} — ${d.pin_count} pin(s)${bboxStr}:`);
            lines.push(...pinLines);
          }
        }
        if (result.errors && Object.keys(result.errors).length > 0) {
          lines.push("\nErrors:");
          for (const [sym, err] of Object.entries(result.errors as Record<string, any>)) {
            const hint = err.suggestions?.length
              ? ` (did you mean: ${err.suggestions.join(", ")}?)`
              : "";
            lines.push(`  ${sym}: ${err.message || err}${hint}`);
          }
        }
        return { content: [{ type: "text", text: lines.join("\n") }] };
      }
      return {
        content: [
          { type: "text", text: `Failed to list pins: ${result.message || "Unknown error"}` },
        ],
      };
    },
  );
}
