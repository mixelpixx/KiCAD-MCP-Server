/**
 * Routing prompts for KiCAD MCP server
 * 
 * These prompts guide the LLM in providing assistance with routing-related tasks
 * in KiCAD PCB design.
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { logger } from '../logger.js';

/**
 * Register routing prompts with the MCP server
 * 
 * @param server MCP server instance
 */
export function registerRoutingPrompts(server: McpServer): void {
  logger.info('Registering routing prompts');

  // ------------------------------------------------------
  // Routing Strategy Prompt
  // ------------------------------------------------------
  server.prompt(
    "routing_strategy",
    {
      board_info: z.string().describe("Information about the PCB board, including dimensions, layer stack-up, and components")
    },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `You're helping to develop a routing strategy for a PCB design. Here's information about the board:

{{board_info}}

Consider the following aspects when developing your routing strategy:

1. Signal Integrity:
   - Group related signals and keep them close
   - Minimize trace length for high-speed signals
   - Consider differential pair routing for appropriate signals
   - Avoid right-angle bends in traces

2. Power Distribution:
   - Use appropriate trace widths for power and ground
   - Consider using power planes for better distribution
   - Place decoupling capacitors close to ICs

3. EMI/EMC Considerations:
   - Keep digital and analog sections separated
   - Consider ground plane partitioning
   - Minimize loop areas for sensitive signals

4. Manufacturing Constraints:
   - Adhere to minimum trace width and spacing requirements
   - Consider via size and placement restrictions
   - Account for soldermask and silkscreen limitations

5. Layer Stack-up Utilization:
   - Determine which signals go on which layers
   - Plan for layer transitions (vias)
   - Consider impedance control requirements

Provide a comprehensive routing strategy that addresses these aspects, with specific recommendations for this particular board design.`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // Differential Pair Routing Prompt
  // ------------------------------------------------------
  server.prompt(
    "differential_pair_routing",
    {
      differential_pairs: z.string().describe("Information about the differential pairs to be routed, including signal names, source and destination components, and speed/frequency requirements")
    },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `You're helping with routing differential pairs on a PCB. Here's information about the differential pairs:

{{differential_pairs}}

When routing differential pairs, follow these best practices:

1. Length Matching:
   - Keep both traces in each pair the same length
   - Maintain consistent spacing between the traces
   - Use serpentine routing (meanders) for length matching when necessary

2. Impedance Control:
   - Maintain consistent trace width and spacing to control impedance
   - Consider the layer stack-up and dielectric properties
   - Avoid changing layers if possible; when necessary, use symmetrical via pairs

3. Coupling and Crosstalk:
   - Keep differential pairs tightly coupled to each other
   - Maintain adequate spacing between different differential pairs
   - Route away from single-ended signals that could cause interference

4. Reference Planes:
   - Route over continuous reference planes
   - Avoid splits in reference planes under differential pairs
   - Consider the return path for the signals

5. Termination:
   - Plan for proper termination at the ends of the pairs
   - Consider the need for series or parallel termination resistors
   - Place termination components close to the endpoints

Based on the provided information, suggest specific routing approaches for these differential pairs, including recommended trace width, spacing, and any special considerations for this particular design.`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // High-Speed Routing Prompt
  // ------------------------------------------------------
  server.prompt(
    "high_speed_routing",
    {
      high_speed_signals: z.string().describe("Information about the high-speed signals to be routed, including signal names, source and destination components, and speed/frequency requirements")
    },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `You're helping with routing high-speed signals on a PCB. Here's information about the high-speed signals:

{{high_speed_signals}}

When routing high-speed signals, consider these critical factors:

1. Impedance Control:
   - Maintain consistent trace width to control impedance
   - Use controlled impedance calculations based on layer stack-up
   - Consider microstrip vs. stripline routing depending on signal requirements

2. Signal Integrity:
   - Minimize trace length to reduce propagation delay
   - Avoid sharp corners (use 45° angles or curves)
   - Minimize vias to reduce discontinuities
   - Consider using teardrops at pad connections

3. Crosstalk Mitigation:
   - Maintain adequate spacing between high-speed traces
   - Use ground traces or planes for isolation
   - Cross traces at 90° when traces must cross on adjacent layers

4. Return Path Management:
   - Ensure continuous return path under the signal
   - Avoid reference plane splits under high-speed signals
   - Use ground vias near signal vias for return path continuity

5. Termination and Loading:
   - Plan for proper termination (series, parallel, AC, etc.)
   - Consider transmission line effects
   - Account for capacitive loading from components and vias

Based on the provided information, suggest specific routing approaches for these high-speed signals, including recommended trace width, layer assignment, and any special considerations for this particular design.`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // Power Distribution Prompt
  // ------------------------------------------------------
  server.prompt(
    "power_distribution",
    {
      power_requirements: z.string().describe("Information about the power requirements, including voltage rails, current needs, and components requiring power")
    },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `You're helping with designing the power distribution network for a PCB. Here's information about the power requirements:

{{power_requirements}}

Consider these key aspects of power distribution network design:

1. Power Planes vs. Traces:
   - Determine when to use power planes versus wide traces
   - Consider current requirements and voltage drop
   - Plan the layer stack-up to accommodate power distribution

2. Decoupling Strategy:
   - Place decoupling capacitors close to ICs
   - Use appropriate capacitor values and types
   - Consider high-frequency and bulk decoupling needs
   - Plan for power entry filtering

3. Current Capacity:
   - Calculate trace widths based on current requirements
   - Consider thermal issues and heat dissipation
   - Plan for current return paths

4. Voltage Regulation:
   - Place regulators strategically
   - Consider thermal management for regulators
   - Plan feedback paths for regulators

5. EMI/EMC Considerations:
   - Minimize loop areas
   - Keep power and ground planes closely coupled
   - Consider filtering for noise-sensitive circuits

Based on the provided information, suggest a comprehensive power distribution strategy, including specific recommendations for plane usage, trace widths, decoupling, and any special considerations for this particular design.`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // Via Usage Prompt
  // ------------------------------------------------------
  server.prompt(
    "via_usage",
    {
      board_info: z.string().describe("Information about the PCB board, including layer count, thickness, and design requirements")
    },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `You're helping with planning via usage in a PCB design. Here's information about the board:

{{board_info}}

Consider these important aspects of via usage:

1. Via Types:
   - Through-hole vias (span all layers)
   - Blind vias (connect outer layer to inner layer)
   - Buried vias (connect inner layers only)
   - Microvias (small diameter vias for HDI designs)

2. Manufacturing Constraints:
   - Minimum via diameter and drill size
   - Aspect ratio limitations (board thickness to hole diameter)
   - Annular ring requirements
   - Via-in-pad considerations and special processing

3. Signal Integrity Impact:
   - Capacitive loading effects of vias
   - Impedance discontinuities
   - Stub effects in through-hole vias
   - Strategies to minimize via impact on high-speed signals

4. Thermal Considerations:
   - Using vias for thermal relief
   - Via patterns for heat dissipation
   - Thermal via sizing and spacing

5. Design Optimization:
   - Via fanout strategies
   - Sharing vias between signals vs. dedicated vias
   - Via placement to minimize trace length
   - Tenting and plugging options

Based on the provided information, recommend appropriate via strategies for this PCB design, including specific via types, sizes, and placement guidelines.`
          }
        }
      ]
    })
  );

  logger.info('Routing prompts registered');
}
