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
      timeout: z
        .number()
        .optional()
        .describe(
          "Per-attempt timeout in seconds (default: 300). Freerouting is killed when it is reached and nothing it routed is kept, so the router is given a shorter time budget of its own (see jobTimeout).",
        ),
      jobTimeout: z
        .number()
        .min(0)
        .optional()
        .describe(
          "Time in seconds Freerouting may spend routing before it stops by itself and writes what it has routed (--router.job_timeout). Default: `timeout` minus a tenth of it (at least 20 s, at most 120 s). The result has time_budget_reached: true when routing stopped this way; the board then holds a partial routing. 0 passes no time budget.",
        ),
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
      routerSettings: z
        .record(
          z.string(),
          z.union([
            z.string(),
            z.number(),
            z.boolean(),
            z.array(z.union([z.string(), z.number(), z.boolean()])),
          ]),
        )
        .optional()
        .describe(
          'Freerouting router settings for this run, by the names in Freerouting\'s docs/settings.md under `router`; each is passed as --router.<name>=<value>, a list joined with commas. Examples: {"autorouter.priority_net_classes": ["DIFF", "ANALOG"]} routes those net classes first and keeps other nets from ripping them; {"autorouter.plane_as_priority": true} gives each plane pad a via of its own into its plane (the plane\'s layer must be of type power); {"autorouter.ignore_net_classes": ["HV"]}. Which settings exist depends on the Freerouting version. Use maxPasses and jobTimeout for those two.',
        ),
      keepArtifacts: z
        .boolean()
        .optional()
        .describe(
          "Keep the intermediate .dsn/.ses files next to the board after the run (default: false). Artifacts are staged in a temporary directory and removed on every exit — success, failure, or crash — unless this is set.",
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
