/**
 * Design prompts for KiCAD MCP server
 *
 * These prompts guide the LLM in providing assistance with general PCB design tasks
 * in KiCAD.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { logger } from "../logger.js";
import { fillTemplate } from "./template.js";

/**
 * Register design prompts with the MCP server
 *
 * @param server MCP server instance
 */
export function registerDesignPrompts(server: McpServer): void {
  logger.info("Registering design prompts");

  // ------------------------------------------------------
  // PCB Layout Review Prompt
  // ------------------------------------------------------
  server.prompt(
    "pcb_layout_review",
    {
      pcb_design_info: z
        .string()
        .describe(
          "Information about the current PCB design, including board dimensions, layer stack-up, component placement, and routing details",
        ),
    },
    (args) =>
      fillTemplate(args, {
        messages: [
          {
            role: "user",
            content: {
              type: "text",
              text: `You're helping to review a PCB layout for potential issues and improvements. Here's information about the current PCB design:

{{pcb_design_info}}

When reviewing the PCB layout, consider these key areas:

1. Component Placement:
   - Logical grouping of related components
   - Orientation for efficient routing
   - Thermal considerations for heat-generating components
   - Mechanical constraints (mounting holes, connectors at edges)
   - Accessibility for testing and rework

2. Signal Integrity:
   - Trace lengths for critical signals
   - Differential pair routing quality
   - Potential crosstalk issues
   - Return path continuity
   - Decoupling capacitor placement

3. Power Distribution:
   - Adequate copper for power rails
   - Power plane design and continuity
   - Decoupling strategy effectiveness
   - Voltage regulator thermal management

4. EMI/EMC Considerations:
   - Ground plane integrity
   - Potential antenna effects
   - Shielding requirements
   - Loop area minimization
   - Edge radiation control

5. Manufacturing and Assembly:
   - DFM (Design for Manufacturing) issues
   - DFA (Design for Assembly) considerations
   - Testability features
   - Silkscreen clarity and usefulness
   - Solder mask considerations

Based on the provided information, identify potential issues and suggest specific improvements to enhance the PCB design.`,
            },
          },
        ],
      }),
  );

  // ------------------------------------------------------
  // Layer Stack-up Planning Prompt
  // ------------------------------------------------------
  server.prompt(
    "layer_stackup_planning",
    {
      design_requirements: z
        .string()
        .describe(
          "Information about the PCB design requirements, including signal types, speed/frequency, power requirements, and any special considerations",
        ),
    },
    (args) =>
      fillTemplate(args, {
        messages: [
          {
            role: "user",
            content: {
              type: "text",
              text: `You're helping to plan an appropriate layer stack-up for a PCB design. Here's information about the design requirements:

{{design_requirements}}

When planning a PCB layer stack-up, consider these important factors:

1. Signal Integrity Requirements:
   - Controlled impedance needs
   - High-speed signal routing
   - EMI/EMC considerations
   - Crosstalk mitigation

2. Power Distribution Needs:
   - Current requirements for power rails
   - Power integrity considerations
   - Decoupling effectiveness
   - Thermal management

3. Manufacturing Constraints:
   - Fabrication capabilities and limitations
   - Cost considerations
   - Available materials and their properties
   - Standard vs. specialized processes

4. Layer Types and Arrangement:
   - Signal layers
   - Power and ground planes
   - Mixed signal/plane layers
   - Microstrip vs. stripline configurations

5. Material Selection:
   - Dielectric constant (Er) requirements
   - Loss tangent considerations for high-speed
   - Thermal properties
   - Mechanical stability

Based on the provided requirements, recommend an appropriate layer stack-up, including the number of layers, their arrangement, material specifications, and thickness parameters. Explain the rationale behind your recommendations.`,
            },
          },
        ],
      }),
  );

  // ------------------------------------------------------
  // Design Rule Development Prompt
  // ------------------------------------------------------
  server.prompt(
    "design_rule_development",
    {
      project_requirements: z
        .string()
        .describe(
          "Information about the PCB project requirements, including technology, speed/frequency, manufacturing capabilities, and any special considerations",
        ),
    },
    (args) =>
      fillTemplate(args, {
        messages: [
          {
            role: "user",
            content: {
              type: "text",
              text: `You're helping to develop appropriate design rules for a PCB project. Here's information about the project requirements:

{{project_requirements}}

When developing PCB design rules, consider these key areas:

1. Clearance Rules:
   - Minimum spacing between copper features
   - Different clearance requirements for different net classes
   - High-voltage clearance requirements
   - Polygon pour clearances

2. Width Rules:
   - Minimum trace widths for signal nets
   - Power trace width requirements based on current
   - Differential pair width and spacing
   - Net class-specific width rules

3. Via Rules:
   - Minimum via size and drill diameter
   - Via annular ring requirements
   - Microvias and buried/blind via specifications
   - Via-in-pad rules

4. Manufacturing Constraints:
   - Minimum hole size
   - Aspect ratio limitations
   - Soldermask and silkscreen constraints
   - Edge clearances

5. Special Requirements:
   - Impedance control specifications
   - High-speed routing constraints
   - Thermal relief parameters
   - Teardrop specifications

Based on the provided project requirements, recommend a comprehensive set of design rules that will ensure signal integrity, manufacturability, and reliability of the PCB. Provide specific values where appropriate and explain the rationale behind critical rules.`,
            },
          },
        ],
      }),
  );

  // ------------------------------------------------------
  // Component Selection Guidance Prompt
  // ------------------------------------------------------
  server.prompt(
    "component_selection_guidance",
    {
      circuit_requirements: z
        .string()
        .describe(
          "Information about the circuit requirements, including functionality, performance needs, operating environment, and any special considerations",
        ),
    },
    (args) =>
      fillTemplate(args, {
        messages: [
          {
            role: "user",
            content: {
              type: "text",
              text: `You're helping with component selection for a PCB design. Here's information about the circuit requirements:

{{circuit_requirements}}

When selecting components for a PCB design, consider these important factors:

1. Electrical Specifications:
   - Voltage and current ratings
   - Power handling capabilities
   - Speed/frequency requirements
   - Noise and precision considerations
   - Operating temperature range

2. Package and Footprint:
   - Space constraints on the PCB
   - Thermal dissipation requirements
   - Manual vs. automated assembly
   - Inspection and rework considerations
   - Available footprint libraries

3. Availability and Sourcing:
   - Multiple source options
   - Lead time considerations
   - Lifecycle status (new, mature, end-of-life)
   - Cost considerations
   - Minimum order quantities

4. Reliability and Quality:
   - Industrial vs. commercial vs. automotive grade
   - Expected lifetime of the product
   - Environmental conditions
   - Compliance with relevant standards

5. Special Considerations:
   - EMI/EMC performance
   - Thermal characteristics
   - Moisture sensitivity
   - RoHS/REACH compliance
   - Special handling requirements

Based on the provided circuit requirements, recommend appropriate component types, packages, and specific considerations for this design. Provide guidance on critical component selections and explain the rationale behind your recommendations.`,
            },
          },
        ],
      }),
  );

  // ------------------------------------------------------
  // PCB Design Optimization Prompt
  // ------------------------------------------------------
  server.prompt(
    "pcb_design_optimization",
    {
      design_info: z
        .string()
        .describe(
          "Information about the current PCB design, including board dimensions, layer stack-up, component placement, and routing details",
        ),
      optimization_goals: z
        .string()
        .describe(
          "Specific goals for optimization, such as performance improvement, cost reduction, size reduction, or manufacturability enhancement",
        ),
    },
    (args) =>
      fillTemplate(args, {
        messages: [
          {
            role: "user",
            content: {
              type: "text",
              text: `You're helping to optimize a PCB design. Here's information about the current design and optimization goals:

{{design_info}}
{{optimization_goals}}

When optimizing a PCB design, consider these key areas based on the stated goals:

1. Performance Optimization:
   - Critical signal path length reduction
   - Impedance control improvement
   - Decoupling strategy enhancement
   - Thermal management improvement
   - EMI/EMC reduction techniques

2. Manufacturability Optimization:
   - DFM rule compliance
   - Testability improvements
   - Assembly process simplification
   - Yield improvement opportunities
   - Tolerance and variation management

3. Cost Optimization:
   - Board size reduction opportunities
   - Layer count optimization
   - Component consolidation
   - Alternative component options
   - Panelization efficiency

4. Reliability Optimization:
   - Stress point identification and mitigation
   - Environmental robustness improvements
   - Failure mode mitigation
   - Margin analysis and improvement
   - Redundancy considerations

5. Space/Size Optimization:
   - Component placement density
   - 3D space utilization
   - Flex and rigid-flex opportunities
   - Alternative packaging approaches
   - Connector and interface optimization

Based on the provided information and optimization goals, suggest specific, actionable improvements to the PCB design. Prioritize your recommendations based on their potential impact and implementation feasibility.`,
            },
          },
        ],
      }),
  );

  // ------------------------------------------------------
  // PDN DC Review Prompt
  // ------------------------------------------------------
  server.prompt(
    "pdn_dc_review",
    {
      board_copper: z
        .string()
        .optional()
        .describe(
          "Notes already collected, if any. The review still reads the board with get_stackup, summarize_vias, and summarize_net_copper",
        ),
      load_path: z
        .string()
        .describe(
          "Rails, source pins, load pins, and the datasheet rows used to derive each current",
        ),
    },
    (args) =>
      fillTemplate(args, {
        messages: [
          {
            role: "user",
            content: {
              type: "text",
              text: `You're reviewing the DC power distribution of a board using only tools this server provides. This server does not run a DC copper solve, a mesh, or an impedance sweep. Do not invent millivolts, a current density, or a curve.

{{board_copper}}
{{load_path}}

Read the copper with these calls, and say which ones you used:

1. get_stackup for copper thickness, the dielectric gap, and the layer names stored on the board. It reads the saved file. If that tool is absent, get_layer_list returns names only: say that the thickness is unknown.
2. summarize_vias for the via count, the drill, and whether the vias run from F.Cu to B.Cu. Filter by the rail's net.
3. summarize_net_copper for each power and ground net. An unknown net is an error. Do not treat it as a net with no copper.
4. query_traces and query_zones when you need geometry those summaries do not include.

Do not report copper drop, current density, or temperature from a mesh. You may estimate only when you show the formula and the inputs you actually read.

For a plane, use IPC-2152. IPC-2221 is for an isolated trace. Applied to a plane it overstates the temperature rise, because nearby copper spreads the heat. Name the document and that limitation.

525 mA/mm is 15 A/mm² in 35 µm copper. It marks crowding. It is not a thermal limit.

Derive each load current before using it. Show the arithmetic: power, voltage, efficiency, and the datasheet row. Do not invent an efficiency or a current the datasheet does not support. Split a path into the segments that exist, such as a bead, a switcher, and a connector. Current leaves at the from-pins and returns at the to-pins.

A target impedance is Z_target = dV_allowed / dI_step, where dI_step is the load's transient step, not its DC current. A result that never meets that target is a failure: say so. A DC inspection of the copper cannot produce an impedance-versus-frequency curve, so do not draw one from these tools. Nominal microfarads on the schematic are not the effective capacitance.

The switch node is a high-dV/dt node. Keep it small and on the outer layer over unbroken ground. Loop area belongs to the hot loop, from the input capacitor to the FETs, not to the area of the switch node. Do not move the switch node onto an inner layer: that adds vias and capacitive coupling.

Lead with the worst thing you can show from the tool results, and name the number. Do not edit the board while reviewing it.`,
            },
          },
        ],
      }),
  );

  // ------------------------------------------------------
  // EMC Shield Review Prompt
  // ------------------------------------------------------
  server.prompt(
    "emc_shield_review",
    {
      shield_geometry: z
        .string()
        .describe(
          "Shield outline, clip positions, and the loop rectangle, if the caller already measured them",
        ),
      comparison: z
        .string()
        .optional()
        .describe(
          "Optional supplied comparison of two geometries. This server does not compute a field",
        ),
    },
    (args) =>
      fillTemplate(args, {
        messages: [
          {
            role: "user",
            content: {
              type: "text",
              text: `You're reviewing radiated EMC of a board shield. This server does not run a near-field solver or a chamber measurement. Do not invent a field value, a colour plot, or a CISPR number.

{{shield_geometry}}
{{comparison}}

Take the geometry from the board:

1. get_component_list with a boundingBox around the can. matchPadCenter keeps a part whose body sits outside the can but whose pad centre is inside. layer selects the side.
2. get_stackup for the copper the return path uses, and summarize_vias for the via count and drill on that net.
3. Coordinates are board millimetres. Can-local millimetres are the board position minus the can centre.

If the caller pasted a field comparison, treat it as supplied data, not as something you computed. Suppression is a field ratio, not a power ratio:

dB = 20·log10(E_old / E_new)

Positive dB means the new geometry is quieter. Negative dB means it is louder. Read the sign from 20·log10(old / new) before describing the result. Quote the numbers the caller supplied. Do not invent a median or a probe value.

Via pitch around a can matters on a real board. Do not say that a via on a ground plane has no effect. Say what summarize_vias counted.

A fitted can is not shielding by itself. A few clips can leave a slot that is louder than no can.

These are general checks:

1. Keep a switch node small and on the outer layer over unbroken ground. The hot loop is the input capacitor to the FETs. Do not move the switch node onto an inner layer.
2. Housing springs only work on bare metal.
3. Unplug debug and UART cables for a radiated test. A cable can be the remaining radiator once the seam is closed.

Do not turn one project's choices, such as an existing filter or parts on another board, into rules for every board. Do not edit the KiCad project while reviewing it.`,
            },
          },
        ],
      }),
  );

  logger.info("Design prompts registered");
}
