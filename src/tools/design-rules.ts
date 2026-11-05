/**
 * Design rules tools for KiCAD MCP server
 *
 * These tools handle design rule checking and configuration
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { logger } from "../logger.js";
import { formatKicadResult } from "./tool-response.js";

// Command function type for KiCAD script calls
type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

/**
 * Register design rule tools with the MCP server
 *
 * @param server MCP server instance
 * @param callKicadScript Function to call KiCAD script commands
 */
export function registerDesignRuleTools(server: McpServer, callKicadScript: CommandFunction): void {
  logger.info("Registering design rule tools");

  // ------------------------------------------------------
  // Set Design Rules Tool
  // ------------------------------------------------------
  server.tool(
    "set_design_rules",
    "Configure PCB design rules: clearance, track width, via dimensions and courtyard requirements.",
    {
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
  server.tool(
    "get_design_rules",
    "Return the current PCB design rules (clearance, track width, via sizes, courtyard settings).",
    {},
    async () => {
      logger.debug("Getting design rules");
      const result = await callKicadScript("get_design_rules", {});

      return formatKicadResult(result);
    },
  );

  // ------------------------------------------------------
  // Run DRC Tool
  // ------------------------------------------------------
  server.tool(
    "run_drc",
    "Run the KiCAD Design Rule Check (DRC) on the current PCB and return violations. Optionally save the report to a file.",
    {
      reportPath: z.string().optional().describe("Optional path to save the DRC report"),
    },
    async ({ reportPath }) => {
      logger.debug("Running DRC check");
      const result = await callKicadScript("run_drc", { reportPath });

      return formatKicadResult(result);
    },
  );

  // ------------------------------------------------------
  // Assign Net to Class Tool
  // ------------------------------------------------------
  server.tool(
    "assign_net_to_class",
    "Assign a net to an existing net class to apply its specific design rules.",
    {
      net: z.string().describe("Name of the net"),
      netClass: z.string().describe("Name of the net class"),
    },
    async ({ net, netClass }) => {
      logger.debug(`Assigning net ${net} to class ${netClass}`);
      const result = await callKicadScript("assign_net_to_class", {
        net,
        netClass,
      });

      return formatKicadResult(result);
    },
  );

  // ------------------------------------------------------
  // Set Layer Constraints Tool
  // ------------------------------------------------------
  server.tool(
    "set_layer_constraints",
    "Set per-layer design rule constraints (minimum track width, clearance and via dimensions).",
    {
      layer: z.string().describe("Layer name (e.g., 'F.Cu')"),
      minTrackWidth: z.number().optional().describe("Minimum track width for this layer (mm)"),
      minClearance: z.number().optional().describe("Minimum clearance for this layer (mm)"),
      minViaDiameter: z.number().optional().describe("Minimum via diameter for this layer (mm)"),
      minViaDrill: z.number().optional().describe("Minimum via drill size for this layer (mm)"),
    },
    async ({ layer, minTrackWidth, minClearance, minViaDiameter, minViaDrill }) => {
      logger.debug(`Setting constraints for layer: ${layer}`);
      const result = await callKicadScript("set_layer_constraints", {
        layer,
        minTrackWidth,
        minClearance,
        minViaDiameter,
        minViaDrill,
      });

      return formatKicadResult(result);
    },
  );

  // ------------------------------------------------------
  // Voltage-graded clearance / creepage rules
  // ------------------------------------------------------
  server.tool(
    "set_voltage_clearance_rules",
    `Write clearance and creepage rules graded by the working voltage between net classes, as a managed block in the board's .kicad_dru.

Give each net class its worst-case voltage against one shared reference. The working voltage between two classes is then |Va - Vb|. Use 'pairs' to override that for classes in separate domains, for example across an isolation barrier. 'spacing' maps working voltage to the required clearance and (optionally) creepage. Choose its values from your standard (e.g. IPC-2221 or IEC 60664) and your coating or potting; the tool does not supply them.

One rule is written per pair of classes, plus one per class against all other nets (at otherNetsVoltage, default 0 V). A re-run replaces the block and leaves other rules alone. The write is refused if the rest of the .kicad_dru does not parse, because KiCad silently ignores every rule in a file it cannot parse. Classes not defined in the project are reported in warnings. Rules apply from the next DRC run.`,
    {
      classes: z
        .array(
          z.object({
            name: z.string().describe("Net class name (must exist in the project)"),
            voltage: z.number().describe("Worst-case potential (V) against the shared reference"),
          }),
        )
        .min(1)
        .describe("Net classes and their voltages"),
      spacing: z
        .array(
          z.object({
            upTo: z.number().describe("Working voltage (V) this row covers, up to and including"),
            clearance: z.number().describe("Minimum clearance (mm)"),
            creepage: z.number().optional().describe("Minimum creepage (mm)"),
          }),
        )
        .min(1)
        .describe("Spacing table; spacing must not fall as voltage rises"),
      pairs: z
        .array(z.object({ a: z.string(), b: z.string(), voltage: z.number() }))
        .optional()
        .describe("Explicit working voltage (V) between two classes, overriding |Va - Vb|"),
      otherNetsVoltage: z
        .number()
        .nullable()
        .optional()
        .describe("Potential of nets in none of the classes (default 0); null skips those rules"),
      boardPath: z.string().optional().describe("Board .kicad_pcb (default: the loaded board)"),
      dryRun: z.boolean().optional().describe("Return the planned rules without writing"),
    },
    async (args) => {
      const result = await callKicadScript("set_voltage_clearance_rules", args);
      return formatKicadResult(result);
    },
  );

  // ------------------------------------------------------
  // Check Clearance Tool
  // ------------------------------------------------------
  server.tool(
    "check_clearance",
    "Check the actual clearance between two PCB items (track, via, pad, zone or component) and report whether it meets the design rules.",
    {
      item1: z
        .object({
          type: z
            .enum(["track", "via", "pad", "zone", "component"])
            .describe("Type of the first item"),
          id: z.string().optional().describe("ID of the first item (if applicable)"),
          reference: z.string().optional().describe("Reference designator (for component)"),
          position: z
            .object({
              x: z.number().optional(),
              y: z.number().optional(),
              unit: z.enum(["mm", "mil", "inch"]).optional(),
            })
            .optional()
            .describe("Position to check (if ID not provided)"),
        })
        .describe("First item to check"),
      item2: z
        .object({
          type: z
            .enum(["track", "via", "pad", "zone", "component"])
            .describe("Type of the second item"),
          id: z.string().optional().describe("ID of the second item (if applicable)"),
          reference: z.string().optional().describe("Reference designator (for component)"),
          position: z
            .object({
              x: z.number().optional(),
              y: z.number().optional(),
              unit: z.enum(["mm", "mil", "inch"]).optional(),
            })
            .optional()
            .describe("Position to check (if ID not provided)"),
        })
        .describe("Second item to check"),
    },
    async ({ item1, item2 }) => {
      logger.debug(`Checking clearance between ${item1.type} and ${item2.type}`);
      const result = await callKicadScript("check_clearance", {
        item1,
        item2,
      });

      return formatKicadResult(result);
    },
  );

  // ------------------------------------------------------
  // Get DRC Violations Tool
  // ------------------------------------------------------
  server.tool(
    "get_drc_violations",
    "Return the list of current DRC violations on the PCB, optionally filtered by severity (error, warning).",
    {
      severity: z
        .enum(["error", "warning", "all"])
        .optional()
        .describe("Filter violations by severity"),
    },
    async ({ severity }) => {
      logger.debug("Getting DRC violations");
      const result = await callKicadScript("get_drc_violations", { severity });

      return formatKicadResult(result);
    },
  );

  logger.info("Design rule tools registered");
}
