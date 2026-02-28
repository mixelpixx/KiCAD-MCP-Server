/**
 * Datasheet tools for KiCAD MCP server
 *
 * Enriches KiCAD schematic symbols with LCSC datasheet URLs.
 * URL schema: https://www.lcsc.com/datasheet/<LCSC#>.pdf (no API key required)
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerDatasheetTools(
  server: McpServer,
  callKicadScript: Function,
) {
  // ── enrich_datasheets ──────────────────────────────────────────────────────
  server.tool(
    "enrich_datasheets",
    `Fill in missing Datasheet URLs in a KiCAD schematic using LCSC part numbers.

For every placed symbol that has:
  • (property "LCSC" "C123456") set
  • (property "Datasheet" "~") or empty

Sets the Datasheet field to:
  https://www.lcsc.com/datasheet/C123456.pdf

The URL is then visible in KiCAD's footprint browser, symbol properties dialog,
and any tool that reads the standard KiCAD Datasheet field.
No API key or internet lookup required – the URL is constructed directly.

Use dry_run=true to preview changes without writing.`,
    {
      schematic_path: z
        .string()
        .describe("Path to the .kicad_sch file to enrich"),
      dry_run: z
        .boolean()
        .optional()
        .default(false)
        .describe(
          "If true, show what would be changed without writing to disk (default: false)",
        ),
    },
    async (args: { schematic_path: string; dry_run?: boolean }) => {
      const result = await callKicadScript("enrich_datasheets", args);
      if (result.success) {
        const lines: string[] = [];

        if (args.dry_run) {
          lines.push(`[DRY RUN] Schematic: ${result.schematic}\n`);
        } else {
          lines.push(`Schematic: ${result.schematic}\n`);
        }

        lines.push(`✓ Updated:         ${result.updated}`);
        lines.push(`  Already set:     ${result.already_set}`);
        lines.push(`  No LCSC number:  ${result.no_lcsc}`);
        lines.push(`  No field:        ${result.no_datasheet_field}`);

        if (result.details && result.details.length > 0) {
          lines.push("\nComponents updated:");
          for (const d of result.details) {
            lines.push(`  ${d.reference.padEnd(6)} ${d.lcsc.padEnd(12)} → ${d.url}`);
          }
        }

        if (result.updated === 0 && !args.dry_run) {
          lines.push(
            "\nNo changes needed – all LCSC components already have a Datasheet URL.",
          );
        }

        return { content: [{ type: "text", text: lines.join("\n") }] };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to enrich datasheets: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // ── get_datasheet_url ──────────────────────────────────────────────────────
  server.tool(
    "get_datasheet_url",
    `Get the LCSC datasheet URL for a component by LCSC number.

Returns the direct PDF URL and product page URL.
No network request – URL is constructed from the LCSC number alone.

Example: get_datasheet_url("C179739")
→ https://www.lcsc.com/datasheet/C179739.pdf`,
    {
      lcsc: z
        .string()
        .describe(
          'LCSC part number, with or without "C" prefix (e.g. "C179739" or "179739")',
        ),
    },
    async (args: { lcsc: string }) => {
      const result = await callKicadScript("get_datasheet_url", { lcsc: args.lcsc });
      if (result.success) {
        const lines = [
          `LCSC: ${result.lcsc}`,
          `Datasheet PDF:  ${result.datasheet_url}`,
          `Product page:   ${result.product_url}`,
        ];
        return { content: [{ type: "text", text: lines.join("\n") }] };
      }
      return {
        content: [
          {
            type: "text",
            text: `Invalid LCSC number: ${args.lcsc}`,
          },
        ],
      };
    },
  );
}
