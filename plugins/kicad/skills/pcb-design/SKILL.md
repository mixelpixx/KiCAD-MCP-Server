---
name: pcb-design
description: Design, modify, review, validate, or export a KiCad schematic or PCB from natural-language hardware requirements. Use for circuit design, component selection, schematic capture, footprint assignment, board layout, routing, ERC/DRC, BOM, Gerbers, and manufacturing handoff through the KiCad MCP tools.
---

# KiCad PCB engineering workflow

Use the KiCad MCP tools for project state and file changes. Treat the model as an engineering assistant: make assumptions explicit, verify each stage, and never describe a board as production-ready solely because ERC or DRC passes.

## Start with an engineering brief

Before editing, identify the design's:

- purpose and operating environment;
- supply inputs, rails, current, and power budget;
- external interfaces, signal speeds, connectors, and pinouts;
- mechanical envelope, mounting, layer-count, and fabrication limits;
- compliance, isolation, temperature, test, cost, and sourcing constraints.

Ask only for missing information that would materially change the architecture or create a safety risk. For other gaps, choose conservative defaults and record them as assumptions.

## Work through gated stages

1. Inspect or create the project and summarize the current state.
2. Choose a circuit architecture and explain important tradeoffs.
3. Select real components from authoritative datasheets. Record manufacturer part numbers, ratings, tolerances, derating, lifecycle or sourcing concerns, and suitable footprints.
4. Capture the schematic in functional blocks. Add power flags, decoupling, protection, programming or debug access, test points, labels, and connector pin descriptions.
5. Run ERC. Resolve genuine errors and explain every intentional exception; do not hide problems with blanket exclusions.
6. Assign and verify footprints. Check pin numbering, polarity, package dimensions, courtyard, assembly orientation, and hand-soldering or manufacturing needs.
7. Define the board stack, outline, mounting, keepouts, net classes, clearances, widths, vias, differential pairs, impedance constraints, and high-voltage creepage before routing.
8. Place by electrical function. Prioritize return paths, decoupling loop area, switching-current loops, crystal and analog sensitivity, thermal paths, connector mechanics, and inspectability.
9. Route critical nets first, then remaining nets. Maintain continuous return paths and avoid unjustified vias or layer changes.
10. Add planes, copper pours, thermal relief, stitching vias, readable silkscreen, reference designators, polarity marks, pin-one marks, test points, and revision identification.
11. Run DRC and relevant design audits. Fix the design until remaining findings are explicitly justified.
12. Generate and inspect the requested manufacturing package: Gerbers, drill files, BOM, position files, drawings, PDFs, STEP, and source files as applicable.

Save after meaningful stages. Re-read the project after mutations instead of assuming a tool call produced the intended geometry or connectivity.

## Verification discipline

- Cross-check every symbol-to-footprint pin mapping against the datasheet.
- Check absolute maximum ratings separately from recommended operating conditions.
- Calculate regulator, resistor, capacitor, trace, via, connector, fuse, and thermal margins where relevant.
- Use ERC and DRC as necessary checks, not proof of electrical correctness, EMC performance, safety compliance, manufacturability, or firmware correctness.
- Where the tools cannot verify something, label it as a manual review item rather than inventing a result.
- For mains, batteries, high energy, medical, automotive, RF, controlled impedance, or safety-critical designs, require qualified human review and the applicable domain tests before fabrication.

## Completion report

Finish with:

- files created or changed;
- key architecture and component decisions;
- assumptions and calculated margins;
- ERC and DRC status with remaining waivers;
- manufacturing outputs generated;
- unresolved risks and exact manual checks required before ordering boards.
