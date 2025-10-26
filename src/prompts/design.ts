/**
 * Design prompts for KiCAD MCP server
 * 
 * These prompts guide the LLM in providing assistance with general PCB design tasks
 * in KiCAD.
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { logger } from '../logger.js';

/**
 * Register design prompts with the MCP server
 * 
 * @param server MCP server instance
 */
export function registerDesignPrompts(server: McpServer): void {
  logger.info('Registering design prompts');

  // ------------------------------------------------------
  // PCB Layout Review Prompt
  // ------------------------------------------------------
  server.prompt(
    "pcb_layout_review",
    {
      pcb_design_info: z.string().describe("Information about the current PCB design, including board dimensions, layer stack-up, component placement, and routing details")
    },
    () => ({
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

Based on the provided information, identify potential issues and suggest specific improvements to enhance the PCB design.`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // Layer Stack-up Planning Prompt
  // ------------------------------------------------------
  server.prompt(
    "layer_stackup_planning",
    {
      design_requirements: z.string().describe("Information about the PCB design requirements, including signal types, speed/frequency, power requirements, and any special considerations")
    },
    () => ({
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

Based on the provided requirements, recommend an appropriate layer stack-up, including the number of layers, their arrangement, material specifications, and thickness parameters. Explain the rationale behind your recommendations.`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // Design Rule Development Prompt
  // ------------------------------------------------------
  server.prompt(
    "design_rule_development",
    {
      project_requirements: z.string().describe("Information about the PCB project requirements, including technology, speed/frequency, manufacturing capabilities, and any special considerations")
    },
    () => ({
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

Based on the provided project requirements, recommend a comprehensive set of design rules that will ensure signal integrity, manufacturability, and reliability of the PCB. Provide specific values where appropriate and explain the rationale behind critical rules.`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // Component Selection Guidance Prompt
  // ------------------------------------------------------
  server.prompt(
    "component_selection_guidance",
    {
      circuit_requirements: z.string().describe("Information about the circuit requirements, including functionality, performance needs, operating environment, and any special considerations")
    },
    () => ({
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

Based on the provided circuit requirements, recommend appropriate component types, packages, and specific considerations for this design. Provide guidance on critical component selections and explain the rationale behind your recommendations.`
          }
        }
      ]
    })
  );

  // ------------------------------------------------------
  // PCB Design Optimization Prompt
  // ------------------------------------------------------
  server.prompt(
    "pcb_design_optimization",
    {
      design_info: z.string().describe("Information about the current PCB design, including board dimensions, layer stack-up, component placement, and routing details"),
      optimization_goals: z.string().describe("Specific goals for optimization, such as performance improvement, cost reduction, size reduction, or manufacturability enhancement")
    },
    () => ({
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

Based on the provided information and optimization goals, suggest specific, actionable improvements to the PCB design. Prioritize your recommendations based on their potential impact and implementation feasibility.`
          }
        }
      ]
    })
  );

  logger.info('Design prompts registered');
}
