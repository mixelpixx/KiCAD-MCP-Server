/**
 * Component prompts for KiCAD MCP server
 * 
 * These prompts guide the LLM in providing assistance with component-related tasks
 * in KiCAD PCB design.
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { logger } from '../logger.js';

/**
 * Register component prompts with the MCP server
 * 
 * @param server MCP server instance
 */
export function registerComponentPrompts(server: McpServer): void {
  logger.info('Registering component prompts');

  // ------------------------------------------------------
  // Component Selection Prompt
  // ------------------------------------------------------
  server.prompt(
    "component_selection",
    {
      requirements: z.string().describe("Description of the circuit requirements and constraints")
    },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `You're helping to select components for a circuit design. Given the following requirements:

{{requirements}}

Suggest appropriate components with their values, ratings, and footprints. Consider factors like:
- Power and voltage ratings
- Current handling capabilities
- Tolerance requirements
- Physical size constraints and package types
- Availability and cost considerations
- Thermal characteristics
- Performance specifications

For each component type, recommend specific values and provide a brief explanation of your recommendation. If appropriate, suggest alternatives with different trade-offs.`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // Component Placement Strategy Prompt
  // ------------------------------------------------------
  server.prompt(
    "component_placement_strategy",
    {
      components: z.string().describe("List of components to be placed on the PCB")
    },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `You're helping with component placement for a PCB layout. Here are the components to place:

{{components}}

Provide a strategy for optimal placement considering:

1. Signal Integrity:
   - Group related components to minimize signal path length
   - Keep sensitive signals away from noisy components
   - Consider appropriate placement for bypass/decoupling capacitors

2. Thermal Management:
   - Distribute heat-generating components
   - Ensure adequate spacing for cooling
   - Placement near heat sinks or vias for thermal dissipation

3. EMI/EMC Concerns:
   - Separate digital and analog sections
   - Consider ground plane partitioning
   - Shield sensitive components

4. Manufacturing and Assembly:
   - Component orientation for automated assembly
   - Adequate spacing for rework
   - Consider component height distribution

Group components functionally and suggest a logical arrangement. If possible, provide a rough sketch or description of component zones.`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // Component Replacement Analysis Prompt
  // ------------------------------------------------------
  server.prompt(
    "component_replacement_analysis",
    {
      component_info: z.string().describe("Information about the component that needs to be replaced")
    },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `You're helping to find a replacement for a component that is unavailable or needs to be updated. Here's the original component information:

{{component_info}}

Consider these factors when suggesting replacements:

1. Electrical Compatibility:
   - Match or exceed key electrical specifications
   - Ensure voltage/current/power ratings are compatible
   - Consider parametric equivalents

2. Physical Compatibility:
   - Footprint compatibility or adaptation requirements
   - Package differences and mounting considerations
   - Size and clearance requirements

3. Performance Impact:
   - How the replacement might affect circuit performance
   - Potential need for circuit adjustments

4. Availability and Cost:
   - Current market availability
   - Cost comparison with original part
   - Lead time considerations

Suggest suitable replacement options and explain the advantages and disadvantages of each. Include any circuit modifications that might be necessary.`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // Component Troubleshooting Prompt
  // ------------------------------------------------------
  server.prompt(
    "component_troubleshooting",
    {
      issue_description: z.string().describe("Description of the component or circuit issue being troubleshooted")
    },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `You're helping to troubleshoot an issue with a component or circuit section in a PCB design. Here's the issue description:

{{issue_description}}

Use the following systematic approach to diagnose the problem:

1. Component Verification:
   - Check component values, footprints, and orientation
   - Verify correct part numbers and specifications
   - Examine for potential manufacturing defects

2. Circuit Analysis:
   - Review the schematic for design errors
   - Check for proper connections and signal paths
   - Verify power and ground connections

3. Layout Review:
   - Examine component placement and orientation
   - Check for adequate clearances
   - Review trace routing and potential interference

4. Environmental Factors:
   - Consider temperature, humidity, and other environmental impacts
   - Check for potential EMI/RFI issues
   - Review mechanical stress or vibration effects

Based on the available information, suggest likely causes of the issue and recommend specific steps to diagnose and resolve the problem.`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // Component Value Calculation Prompt
  // ------------------------------------------------------
  server.prompt(
    "component_value_calculation",
    {
      circuit_requirements: z.string().describe("Description of the circuit function and performance requirements")
    },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `You're helping to calculate appropriate component values for a specific circuit function. Here's the circuit description and requirements:

{{circuit_requirements}}

Follow these steps to determine the optimal component values:

1. Identify the relevant circuit equations and design formulas
2. Consider the design constraints and performance requirements
3. Calculate initial component values based on ideal behavior
4. Adjust for real-world factors:
   - Component tolerances
   - Temperature coefficients
   - Parasitic effects
   - Available standard values

Present your calculations step-by-step, showing your work and explaining your reasoning. Recommend specific component values, explaining why they're appropriate for this application. If there are multiple valid approaches, discuss the trade-offs between them.`
          }
        }
      ]
    })
  );

  logger.info('Component prompts registered');
}
