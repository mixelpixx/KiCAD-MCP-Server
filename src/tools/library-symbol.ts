/**
 * Symbol Library tools for KiCAD MCP server
 * Provides search/browse access to local KiCad symbol libraries
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

// KiCAD's pin electrical types and graphic styles, mirroring
// python/utils/pin_types.py (and the enums python/schemas/tool_schemas.py
// declares). Kept as z.enum rather than z.string so a client rejects a bad
// token locally instead of learning about it from a round trip.
const PIN_TYPES = [
  "input",
  "output",
  "bidirectional",
  "tri_state",
  "passive",
  "free",
  "unspecified",
  "power_in",
  "power_out",
  "open_collector",
  "open_emitter",
  "no_connect",
] as const;

const PIN_STYLES = [
  "line",
  "inverted",
  "clock",
  "inverted_clock",
  "input_low",
  "clock_low",
  "output_low",
  "edge_clock_high",
  "non_logic",
] as const;

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
      projectPath: z
        .string()
        .optional()
        .describe(
          "Optional: project directory or .kicad_pro/.kicad_pcb/.kicad_sch path so project-scope sym-lib-table libraries are searched too.",
        ),
    },
    async (args: { query: string; library?: string; limit?: number; projectPath?: string }) => {
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

  // Change pin electrical types in a .kicad_sym library
  server.tool(
    "set_symbol_pin_type",
    "Set the electrical type (and optionally the graphic style) of pins in a .kicad_sym " +
      "library, filtered by symbol, pin number, pin name, or current type. Use this instead " +
      "of a sed/regex pass over the library: a blind substitution also rewrites matching " +
      "words inside symbol names, Descriptions and (alternate ...) pin functions, and it " +
      "cannot tell which symbol it is standing on. The replacement token is checked against " +
      "KiCAD's pin types first — an unknown one makes the whole library fail to load. " +
      "Typical use: imported or SnapEDA symbols arrive with every pin 'unspecified' or " +
      "'bidirectional', which floods ERC with conflicts on nets that are electrically fine. " +
      "Run with dryRun first to see what matches. The library is replaced atomically, keeps " +
      "its existing line endings, and is copied to a sibling '.mcp-backups/' first (path " +
      "returned in 'backupPath'). 'changes' lists at most 200 per-pin records, with " +
      "'changesTruncated' saying when it was cut; 'changeCount' always carries the true total.",
    {
      libraryPath: z.string().describe("Absolute path to the .kicad_sym library file"),
      type: z.enum(PIN_TYPES).optional().describe("New electrical type"),
      style: z.enum(PIN_STYLES).optional().describe("New graphic style"),
      symbols: z
        .array(z.string())
        .optional()
        .describe(
          "Top-level symbol names to change (not unit names like 'R_0402_1_1'). " +
            "Omit to change every symbol in the library.",
        ),
      pinNumbers: z.array(z.string()).optional().describe("Only pins with these numbers"),
      pinNames: z.array(z.string()).optional().describe("Only pins with these names"),
      fromType: z
        .enum(PIN_TYPES)
        .optional()
        .describe("Only pins currently of this electrical type — the safe way to do a bulk fix"),
      dryRun: z.boolean().optional().describe("Report what would change without writing"),
    },
    async (args) => {
      const result = await callKicadScript("set_symbol_pin_type", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // Find the same part stored twice under different names
  server.tool(
    "find_duplicate_symbols",
    "Group symbols in a .kicad_sym that are the same part stored twice under different " +
      "names — the residue of Eagle imports, SnapEDA downloads, and parts re-added because " +
      "search did not find the existing name. KiCAD reports nothing here because the names " +
      "differ, which is also why grepping does not find it. Matches on manufacturer part " +
      "number (tolerating the inconsistent property naming real libraries have: MPN, MP, " +
      "'MANUFACTURER PART NUMBER', 'PART NUMBER'), on distributor part number, on " +
      "Value+Footprint, on an identical drawn body, or on near-identical names. Pass " +
      "schematicPaths to count how many instances each duplicate actually has — that turns " +
      "the report into a decision, because the one nothing places is the one to retire.",
    {
      libraryPath: z.string().describe("Absolute path to the .kicad_sym library file"),
      matchBy: z
        .array(z.enum(["mpn", "supplier", "value_footprint", "graphics", "name"]))
        .optional()
        .describe(
          "How to decide two symbols are the same part (default: mpn, value_footprint). " +
            "'graphics' is off by default: every resistor in a library shares one body, so " +
            "on passives it groups the whole family.",
        ),
      schematicPaths: z
        .array(z.string())
        .optional()
        .describe(
          ".kicad_sch files or directories to scan for usage counts (recursive, skipping " +
            "autosave sheets and backup/history folders). Only placements of this library " +
            "count, and a sub-sheet instantiated more than once counts once per instantiation.",
        ),
      libraryNicknames: z
        .array(z.string())
        .optional()
        .describe(
          "The nickname(s) this library is registered under in a lib_id, if the file stem " +
            "and the sym-lib-table entries beside the scanned sheets do not cover it. A " +
            "bare 'R' in this library is not Device:R, so placements naming another " +
            "library are not counted towards it.",
        ),
      minGroupSize: z
        .number()
        .optional()
        .describe("Only report groups with at least this many symbols (default 2)"),
      ignoreCase: z
        .boolean()
        .optional()
        .describe("Compare part numbers and values case-insensitively (default true)"),
    },
    async (args: {
      libraryPath: string;
      matchBy?: string[];
      schematicPaths?: string[];
      libraryNicknames?: string[];
      minGroupSize?: number;
      ignoreCase?: boolean;
    }) => {
      const result = await callKicadScript("find_duplicate_symbols", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );
}
