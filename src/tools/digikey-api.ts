/**
 * Digi-Key Product Information V4 tools for the KiCAD MCP server.
 *
 * Credentials are read from DIGIKEY_CLIENT_ID / DIGIKEY_CLIENT_SECRET in the
 * server's environment (or a gitignored .env) and are deliberately absent from
 * every tool schema below: a key passed as a tool argument would be recorded in
 * the conversation, in the MCP log, and in anything replaying the call.
 *
 * Absent from the schema means ignored, not rejected — zod strips unknown keys,
 * so a caller that passes `clientSecret` anyway gets a successful call with the
 * argument silently dropped. The Python side detects credential-shaped argument
 * names and returns a `warnings` entry telling the caller to rotate the value,
 * because by then it is already in the transcript. Adding the fields to the
 * schema so they could be rejected would defeat the point of leaving them out.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

const localeSchema = z
  .object({
    site: z.string().describe("Digi-Key site, e.g. US, DE, UK"),
    language: z.string().describe("Language code, e.g. en, de"),
    currency: z.string().describe("Currency code, e.g. USD, EUR"),
  })
  .partial()
  .optional()
  .describe(
    "Override the locale for this call. Digi-Key requires locale headers on every " +
      "request — without them a search returns 404 — but the values are yours to " +
      "pick. Defaults come from DIGIKEY_LOCALE_* or US/en/USD. Note the response is " +
      "localized too, so the lifecycle status and the packaging names come back in " +
      "the language you ask for; the tools compare ids rather than those strings.",
  );

export function registerDigiKeyApiTools(server: McpServer, callKicadScript: Function) {
  server.tool(
    "digikey_test_connection",
    "Verify that the server's Digi-Key credentials work: fetch a token and run one " +
      "search. Use this first when a Digi-Key tool reports an authentication problem, " +
      "since it distinguishes missing credentials from rejected ones from a locale " +
      "misconfiguration. Credentials come from DIGIKEY_CLIENT_ID and " +
      "DIGIKEY_CLIENT_SECRET in the server environment; they are never accepted as " +
      "arguments and never appear in a response.",
    { locale: localeSchema },
    async (args: { locale?: { site?: string; language?: string; currency?: string } }) => {
      const result = await callKicadScript("digikey_test_connection", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    },
  );

  server.tool(
    "digikey_search_parts",
    "Search Digi-Key by part number, manufacturer part number, or a parametric phrase " +
      "('0402 100nF 50V X7R'), returning stock, price, lifecycle status, packaging " +
      "variations and the parametric table. Two details the raw API makes easy to get " +
      "wrong are handled here: the Digi-Key part number lives on each packaging " +
      "variation rather than on the product, so reel and cut tape have different " +
      "numbers; and lifecycle is read from ProductStatus.Id rather than the status " +
      "string, which is localized. Use preferPackaging to pick which variation is " +
      "quoted as the headline part number.",
    {
      keywords: z
        .string()
        .describe("Part number, MPN, or a parametric phrase such as '0402 100nF 50V X7R'"),
      limit: z.number().optional().describe("Results to return, 1-50 (default 10)"),
      offset: z.number().optional().describe("Result offset for paging (default 0)"),
      preferPackaging: z
        .enum(["TR", "CT", "DKR"])
        .optional()
        .describe(
          "Which packaging variation to quote as the headline part number: TR (tape & " +
            "reel, production), CT (cut tape, prototypes), DKR (Digi-Reel). Matching " +
            "handles localized packaging names.",
        ),
      locale: localeSchema,
    },
    async (args: {
      keywords: string;
      limit?: number;
      offset?: number;
      preferPackaging?: string;
      locale?: { site?: string; language?: string; currency?: string };
    }) => {
      const result = await callKicadScript("digikey_search_parts", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    },
  );

  server.tool(
    "digikey_check_library_availability",
    "Look up every symbol in a .kicad_sym on Digi-Key and report which parts are " +
      "obsolete, out of stock, unfindable, or missing a part number altogether — the " +
      "check to run before a board goes to purchasing, and after inheriting a library " +
      "from an import. Each symbol is searched by its distributor part number first and " +
      "its manufacturer part number second, because retired Digi-Key numbers are the " +
      "common failure and the MPN usually still resolves; searchByMpnFirst reverses " +
      "that. Part numbers are read under any of the property spellings real libraries " +
      "use (MPN, MP, 'MANUFACTURER PART NUMBER', 'PART NUMBER', 'SUPPLIER PART NUMBER " +
      "1'). Budget up to two rate-limited requests per symbol — the fallback costs a " +
      "second one whenever the first term misses — plus one token request, so raise " +
      "maxSymbols deliberately.",
    {
      libraryPath: z.string().describe("Absolute path to the .kicad_sym library file"),
      symbols: z
        .array(z.string())
        .optional()
        .describe("Only check these symbol names (default: every symbol in the library)"),
      maxSymbols: z
        .number()
        .optional()
        .describe(
          "Stop after this many symbols (default 25). Each symbol costs one or two " +
            "rate-limited API requests and the client throttles itself between them, so " +
            "a larger sweep takes minutes; raising this past a few hundred will exhaust " +
            "even the extended timeout this tool runs under.",
        ),
      searchByMpnFirst: z
        .boolean()
        .optional()
        .describe("Search by manufacturer part number before the distributor number"),
      preferPackaging: z.enum(["TR", "CT", "DKR"]).optional().describe("Packaging to quote"),
      locale: localeSchema,
    },
    async (args: {
      libraryPath: string;
      symbols?: string[];
      maxSymbols?: number;
      searchByMpnFirst?: boolean;
      preferPackaging?: string;
      locale?: { site?: string; language?: string; currency?: string };
    }) => {
      const result = await callKicadScript("digikey_check_library_availability", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    },
  );
}
