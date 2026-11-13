/**
 * Freerouting autoroute tools for KiCAD MCP server
 *
 * Provides autorouting via Freerouting (Specctra DSN/SES workflow).
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerFreeroutingTools(server: McpServer, callKicadScript: Function) {
  // Full autoroute: export DSN -> run Freerouting -> import SES
  //
  // Best-of-N support (the `attempts` / `targetNets` / `passSchedule`
  // parameters) is ported from morningfire-pcb-automation:
  //   https://github.com/NiNjA-CodE/morningfire-pcb-automation
  //   (scripts/routing/freeroute_runner.py — `score_ses` + run loop)
  // On dense boards a single attempt regularly leaves 1–7 nets unrouted;
  // cycling through a few `--max-passes` values typically drives the
  // unrouted count to zero.
  server.tool(
    "autoroute",
    "Run Freerouting autorouter on the current PCB. Exports to Specctra DSN, runs Freerouting CLI, and imports the routed SES result. Requires freerouting.jar and the Java version it was built for (21+; Freerouting 2.4.x needs 25), or Docker/Podman (see check_freerouting). Set `attempts` > 1 to run best-of-N: Freerouting is invoked multiple times with varied `--max-passes`, each result is scored by (nets_routed * 1000 + segments, +50000 bonus when every `targetNets` entry routed), and the winning SES is imported. Single-attempt behaviour is unchanged when `attempts` is omitted.",
    {
      boardPath: z.string().optional().describe("Path to .kicad_pcb file (default: current board)"),
      freeroutingJar: z
        .string()
        .optional()
        .describe(
          "Path to freerouting.jar (default: ~/.kicad-mcp/freerouting.jar or FREEROUTING_JAR env)",
        ),
      maxPasses: z
        .number()
        .optional()
        .describe(
          "Maximum routing passes for single-attempt mode (default: 20). Ignored when `attempts` > 1; use `passSchedule` instead.",
        ),
      timeout: z.number().optional().describe("Per-attempt timeout in seconds (default: 300)"),
      attempts: z
        .number()
        .int()
        .min(1)
        .optional()
        .describe(
          "Number of Freerouting runs to try (default: 1 — backward-compatible). When > 1, runs best-of-N: scores each attempt by routing completeness and keeps the SES with the highest score. Recommended: 3–5 for dense boards.",
        ),
      targetNets: z
        .array(z.string())
        .optional()
        .describe(
          "Optional list of critical net names. An attempt that routes all of them earns a 50,000-point scoring bonus, breaking ties in favour of designs that include the must-have nets.",
        ),
      passSchedule: z
        .array(z.number())
        .optional()
        .describe(
          "Per-attempt `--max-passes` values to cycle through (default: [50, 60, 65, 70, 75, 80, 85, 90, 55, 95]). The list wraps if `attempts` exceeds its length.",
        ),
      routeNets: z
        .array(z.string())
        .optional()
        .describe(
          "Route only these nets (names or globs such as '/HV PWR/*'). Other nets stay on the board as obstacles but are left out of the routing job, so a board can be routed one isolation domain at a time.",
        ),
      excludeNets: z
        .array(z.string())
        .optional()
        .describe(
          "Leave these nets (names or globs) out of the routing job, e.g. high-current nets you will pour by hand.",
        ),
      kicadRules: z
        .boolean()
        .optional()
        .describe(
          "Pass the board's .kicad_dru (custom design rules: isolation, per-area clearances) and .kicad_pro (minimum track width) to Freerouting, which a DSN does not carry (default: true; a board without them is unaffected). Freerouting master after 2.5.0 applies them; 2.5.0 and earlier ignore them and route with net-class clearances only. The reply's kicad_rules says which: applied, ignored, and the rules Freerouting could only approximate (warnings, e.g. creepage applied as its clearance). false leaves them out.",
        ),
      keepArtifacts: z
        .boolean()
        .optional()
        .describe(
          "Keep the intermediate .dsn/.ses files next to the board after the run (default: false). Artifacts are staged in a temporary directory and removed on every exit — success, failure, or crash — unless this is set.",
        ),
      layerTraceCosts: z
        .record(z.string(), z.number())
        .optional()
        .describe(
          "Per-layer trace cost factor, e.g. {\"In1.Cu\": 5}: the layer stays usable but a track there costs more (the factor along its preferred direction, twice that against it; Freerouting's defaults are about 1 and 2), so a plane layer carries only the tracks that fit nowhere else. Keys are canonical (In1.Cu) or the board's own layer names; a name the board lacks is refused. Combines with signalLayers; written to the same Freerouting rules file.",
        ),
      signalLayers: z
        .array(z.string())
        .optional()
        .describe(
          'Copper layers tracks may use, e.g. ["F.Cu", "In2.Cu", "B.Cu"] when In1 is a plane; canonical names or the board\'s own (a renamed F.Cu is found either way), and a name the board lacks is refused. The other copper layers get (active off) in a Freerouting rules file (autoroute_settings layer_rule, passed with -dr): no tracks there, vias still pass through, so a plane is not cut into islands. Nothing else is written to the file, so Freerouting\'s own per-layer defaults stay in force. The reply lists the restricted layers by the board\'s names in tracksKeptOffLayers. Default: all layers.',
        ),
    },
    async (args: any) => {
      const result = await callKicadScript("autoroute", args);
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

  // Export DSN only
  server.tool(
    "export_dsn",
    "Export the current PCB to Specctra DSN format. Useful for manual Freerouting workflow or external autorouters.",
    {
      boardPath: z.string().optional().describe("Path to .kicad_pcb file (default: current board)"),
      outputPath: z
        .string()
        .optional()
        .describe("Output DSN file path (default: same dir as board)"),
    },
    async (args: any) => {
      const result = await callKicadScript("export_dsn", args);
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

  // Import SES
  server.tool(
    "import_ses",
    "Import a Specctra SES (session) file into the current PCB. Use after running Freerouting externally.",
    {
      sesPath: z.string().describe("Path to the .ses file to import"),
      boardPath: z.string().optional().describe("Path to .kicad_pcb file (default: current board)"),
    },
    async (args: any) => {
      const result = await callKicadScript("import_ses", args);
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

  // Check Freerouting dependencies
  server.tool(
    "check_freerouting",
    "Check if Java and Freerouting JAR are available on the system. Run this before autoroute to verify prerequisites.",
    {
      freeroutingJar: z.string().optional().describe("Path to freerouting.jar to check"),
    },
    async (args: any) => {
      const result = await callKicadScript("check_freerouting", args);
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
}
