/**
 * Library tools for KiCAD MCP server
 * Provides access to KiCAD footprint libraries and symbols
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerLibraryTools(server: McpServer, callKicadScript: Function) {
  // List available footprint libraries
  server.tool(
    "list_libraries",
    "List all available KiCAD footprint libraries",
    {
      search_paths: z
        .array(z.string())
        .optional()
        .describe("Optional additional search paths for libraries"),
    },
    async (args: { search_paths?: string[] }) => {
      const result = await callKicadScript("list_libraries", args);
      if (result.success && result.libraries) {
        return {
          content: [
            {
              type: "text",
              text: `Found ${result.libraries.length} footprint libraries:\n${result.libraries.join("\n")}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to list libraries: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // Search for footprints across all libraries
  server.tool(
    "search_footprints",
    "Search for footprints matching a pattern across all libraries",
    {
      search_term: z.string().describe("Search term or pattern to match footprint names"),
      library: z.string().optional().describe("Optional specific library to search in"),
      limit: z.number().optional().default(50).describe("Maximum number of results to return"),
    },
    async (args: { search_term: string; library?: string; limit?: number }) => {
      const result = await callKicadScript("search_footprints", {
        pattern: args.search_term,
        library: args.library,
        limit: args.limit,
      });
      if (result.success && result.footprints) {
        const footprintList = result.footprints
          .map(
            (fp: any) =>
              `${fp.full_name || fp.library + ":" + fp.footprint}${fp.description ? " - " + fp.description : ""}`,
          )
          .join("\n");
        return {
          content: [
            {
              type: "text",
              text: `Found ${result.footprints.length} matching footprints:\n${footprintList}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to search footprints: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // List footprints in a specific library
  server.tool(
    "list_library_footprints",
    "List all footprints in a specific KiCAD library",
    {
      library_name: z.string().describe("Name of the library to list footprints from"),
      filter: z.string().optional().describe("Optional filter pattern for footprint names"),
      limit: z.number().optional().default(100).describe("Maximum number of footprints to list"),
    },
    async (args: { library_name: string; filter?: string; limit?: number }) => {
      const result = await callKicadScript("list_library_footprints", args);
      if (result.success && result.footprints) {
        const footprintList = result.footprints.map((fp: string) => `  - ${fp}`).join("\n");
        return {
          content: [
            {
              type: "text",
              text: `Library ${args.library_name} contains ${result.footprints.length} footprints:\n${footprintList}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to list footprints in library ${args.library_name}: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // Get detailed information about a specific footprint
  server.tool(
    "get_footprint_info",
    "Get detailed information about a specific footprint",
    {
      library_name: z.string().describe("Name of the library containing the footprint"),
      footprint_name: z.string().describe("Name of the footprint to get information about"),
    },
    async (args: { library_name: string; footprint_name: string }) => {
      const result = await callKicadScript("get_footprint_info", args);
      if (result.success && result.info) {
        const info = result.info;

        // pads is a list of {number, type, shape} objects
        const padsArray: Array<{ number: string; type: string; shape: string }> = Array.isArray(
          info.pads,
        )
          ? info.pads
          : [];
        const padsSummary = padsArray.length
          ? `${padsArray.length} pads: ${padsArray.map((p) => p.number).join(", ")}`
          : "";
        const padsDetail = padsArray.length
          ? padsArray.map((p) => `  pad ${p.number}: ${p.type} ${p.shape}`).join("\n")
          : "";

        const details = [
          `Footprint: ${info.name}`,
          `Library: ${info.library}`,
          info.description ? `Description: ${info.description}` : "",
          info.keywords ? `Keywords: ${info.keywords}` : "",
          padsSummary,
          padsDetail,
          info.layers ? `Layers used: ${info.layers.join(", ")}` : "",
          info.courtyard
            ? `Courtyard size: ${info.courtyard.width}mm x ${info.courtyard.height}mm`
            : "",
          info.attributes ? `Attributes: ${JSON.stringify(info.attributes)}` : "",
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
            text: `Failed to get footprint info: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // ── Library table maintenance (sym-lib-table / fp-lib-table) ──────────── //

  const tableType = z
    .enum(["symbol", "footprint"])
    .optional()
    .describe("Which table to edit: 'symbol' (sym-lib-table, default) or 'footprint'");
  const scope = z
    .enum(["project", "global"])
    .optional()
    .describe("'project' (default, needs projectPath) or 'global' (KiCad's user config)");
  const projectPath = z
    .string()
    .optional()
    .describe("Path to the .kicad_pro or its directory, for scope='project'");
  const tablePath = z
    .string()
    .optional()
    .describe("Path to the table file itself, bypassing scope/projectPath resolution");
  const dryRun = z
    .boolean()
    .optional()
    .describe("Report what the edit would do without writing the table");

  server.tool(
    "list_library_table",
    "Read a sym-lib-table or fp-lib-table: nickname, type, URI and description of every " +
      "registered library. Each URI is resolved through ${KIPRJMOD}, KiCad's built-in library " +
      "directories (KICAD*_SYMBOL_DIR and friends), the path variables configured in " +
      "kicad_common.json and the environment, and reported with whether the file is actually " +
      "there — which is how a stale row left over from a library migration shows itself. A " +
      '(type "Table") row is flagged as an indirection, with a count of the libraries it ' +
      "stands for.",
    { tableType, scope, projectPath, tablePath },
    async (args: any) => {
      const result = await callKicadScript("list_library_table", args);
      return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
    },
  );

  server.tool(
    "remove_library_table_entry",
    "Remove one or more entries from a sym-lib-table or fp-lib-table by nickname — the " +
      "counterpart to register_symbol_library / register_footprint_library. The table is " +
      "re-parsed before it is written, so an edit that would leave it unbalanced is refused " +
      "rather than saved; the write is atomic and the previous contents are kept in a sibling " +
      ".mcp-backups/ directory. Use dryRun first when the target is scope='global', which " +
      'every project on the machine loads. Removing a (type "Table") row unregisters every ' +
      "library in the table it points at, and the result says so.",
    {
      tableType,
      scope,
      projectPath,
      tablePath,
      dryRun,
      libraryName: z.string().optional().describe("Nickname to remove"),
      libraryNames: z
        .array(z.string())
        .optional()
        .describe("Several nicknames to remove in one pass"),
    },
    async (args: any) => {
      const result = await callKicadScript("remove_library_table_entry", args);
      return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
    },
  );

  server.tool(
    "set_library_table_uri",
    "Repoint an existing library-table entry at a different file, keeping its nickname, type " +
      "and description. Use it to move a project onto ${KIPRJMOD}-relative paths, or to follow " +
      "a library that was relocated, without unregistering and re-registering it.",
    {
      tableType,
      scope,
      projectPath,
      tablePath,
      dryRun,
      libraryName: z.string().describe("Nickname of the entry to repoint"),
      uri: z
        .string()
        .describe(
          "New URI, e.g. ${KIPRJMOD}/../FOG_components.kicad_sym. Path variables are kept " +
            "verbatim in the table and only expanded when reporting whether the file exists.",
        ),
    },
    async (args: any) => {
      const result = await callKicadScript("set_library_table_uri", args);
      return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
    },
  );
}
