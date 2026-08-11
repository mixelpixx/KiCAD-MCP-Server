/**
 * Design rules tools for KiCAD MCP server
 *
 * These tools handle design rule checking and configuration
 */
import { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";
import { logger } from "../logger.js";
import { formatKicadResult } from "./tool-response.js";
import { registerKiCadTool, type CommandFunction, withToolSignal } from "./tool-registration.js";

// Command function type for KiCAD script calls

/**
 * Register design rule tools with the MCP server
 *
 * @param server MCP server instance
 * @param callKicadScript Function to call KiCAD script commands
 */
export function registerDesignRuleTools(server: McpServer, callKicadScript: CommandFunction): void {
  callKicadScript = withToolSignal(callKicadScript);
  logger.info("Registering design rule tools");

  // ------------------------------------------------------
  // Set Design Rules Tool
  // ------------------------------------------------------
  registerKiCadTool(
    server,
    "design_rules",
    "set_design_rules",
    {
      description:
        "Configure PCB design rules: clearance, track width, via dimensions and courtyard requirements.",
      inputSchema: z.object({
        clearance: z.number().optional().describe("Minimum clearance between copper items (mm)"),
        trackWidth: z.number().optional().describe("Default track width (mm)"),
        viaDiameter: z.number().optional().describe("Default via diameter (mm)"),
        viaDrill: z.number().optional().describe("Default via drill size (mm)"),
        microViaDiameter: z.number().optional().describe("Default micro via diameter (mm)"),
        microViaDrill: z.number().optional().describe("Default micro via drill size (mm)"),
        minTrackWidth: z.number().optional().describe("Minimum track width (mm)"),
        minViaDiameter: z.number().optional().describe("Minimum via diameter (mm)"),
        minViaDrill: z.number().optional().describe("Minimum via drill size (mm)"),
        minMicroViaDiameter: z.number().optional().describe("Minimum micro via diameter (mm)"),
        minMicroViaDrill: z.number().optional().describe("Minimum micro via drill size (mm)"),
        minHoleDiameter: z.number().optional().describe("Minimum hole diameter (mm)"),
        requireCourtyard: z
          .boolean()
          .optional()
          .describe("Whether to require courtyards for all footprints"),
        courtyardClearance: z
          .number()
          .optional()
          .describe("Minimum clearance between courtyards (mm)"),
      }),
    },
    async (params) => {
      logger.debug("Setting design rules");
      const result = await callKicadScript("set_design_rules", params);

      return formatKicadResult(result);
    },
  );

  // ------------------------------------------------------
  // Get Design Rules Tool
  // ------------------------------------------------------
  registerKiCadTool(
    server,
    "design_rules",
    "get_design_rules",
    {
      description:
        "Return the current PCB design rules (clearance, track width, via sizes, courtyard settings).",
      inputSchema: z.object({}),
    },
    async () => {
      logger.debug("Getting design rules");
      const result = await callKicadScript("get_design_rules", {});

      return formatKicadResult(result);
    },
  );

  // ------------------------------------------------------
  // Run DRC Tool
  // ------------------------------------------------------
  registerKiCadTool(
    server,
    "design_rules",
    "run_drc",
    {
      description:
        "Run the KiCAD Design Rule Check (DRC) on the current PCB and return violations. Optionally save the report to a file.",
      inputSchema: z.object({
        reportPath: z.string().optional().describe("Optional path to save the DRC report"),
      }),
    },
    async ({ reportPath }) => {
      logger.debug("Running DRC check");
      const result = await callKicadScript("run_drc", { reportPath });

      return formatKicadResult(result);
    },
  );

  // ------------------------------------------------------
  // Add Net Class Tool
  // ------------------------------------------------------
  registerKiCadTool(
    server,
    "design_rules",
    "add_net_class",
    {
      description:
        "Create a named net class with specific clearance, track-width, via, and differential-pair rules.",
      inputSchema: z.object({
        name: z.string().describe("Name of the net class"),
        clearance: z.number().describe("Clearance for this net class (mm)"),
        trackWidth: z.number().describe("Track width for this net class (mm)"),
        viaDiameter: z.number().describe("Via diameter for this net class (mm)"),
        viaDrill: z.number().describe("Via drill size for this net class (mm)"),
        uvia_diameter: z.number().optional().describe("Micro via diameter for this net class (mm)"),
        uvia_drill: z.number().optional().describe("Micro via drill size for this net class (mm)"),
        diff_pair_width: z
          .number()
          .optional()
          .describe("Differential pair width for this net class (mm)"),
        diff_pair_gap: z
          .number()
          .optional()
          .describe("Differential pair gap for this net class (mm)"),
      }),
    },
    async ({
      name,
      clearance,
      trackWidth,
      viaDiameter,
      viaDrill,
      uvia_diameter,
      uvia_drill,
      diff_pair_width,
      diff_pair_gap,
    }) => {
      logger.debug(`Adding net class: ${name}`);
      const result = await callKicadScript("create_netclass", {
        name,
        clearance,
        trackWidth,
        viaDiameter,
        viaDrill,
        uviaDiameter: uvia_diameter,
        uviaDrill: uvia_drill,
        diffPairWidth: diff_pair_width,
        diffPairGap: diff_pair_gap,
      });

      return formatKicadResult(result);
    },
  );

  // ------------------------------------------------------
  // Get DRC Violations Tool
  // ------------------------------------------------------
  registerKiCadTool(
    server,
    "design_rules",
    "get_drc_violations",
    {
      description:
        "Return the list of current DRC violations on the PCB, optionally filtered by severity (error, warning).",
      inputSchema: z.object({
        severity: z
          .enum(["error", "warning", "all"])
          .optional()
          .describe("Filter violations by severity"),
      }),
    },
    async ({ severity }) => {
      logger.debug("Getting DRC violations");
      const result = await callKicadScript("get_drc_violations", { severity });

      return formatKicadResult(result);
    },
  );

  logger.info("Design rule tools registered");
}
