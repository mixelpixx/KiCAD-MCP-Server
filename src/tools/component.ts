/**
 * Component management tools for KiCAD MCP server
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { logger } from "../logger.js";

// Command function type for KiCAD script calls
type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

/**
 * Register component management tools with the MCP server
 *
 * @param server MCP server instance
 * @param callKicadScript Function to call KiCAD script commands
 */
export function registerComponentTools(server: McpServer, callKicadScript: CommandFunction): void {
  logger.info("Registering component management tools");

  // ------------------------------------------------------
  // Place Component Tool
  // ------------------------------------------------------
  server.tool(
    "place_component",
    "Place a footprint component onto the PCB at the specified position. Optionally set reference, value, footprint, rotation and layer.",
    {
      componentId: z
        .string()
        .describe("Identifier for the component to place (e.g., 'R_0603_10k')"),
      position: z
        .object({
          x: z.number().describe("X coordinate"),
          y: z.number().describe("Y coordinate"),
          unit: z.enum(["mm", "inch", "mil"]).describe("Unit of measurement"),
        })
        .describe("Position coordinates and unit"),
      reference: z.string().optional().describe("Optional desired reference (e.g., 'R5')"),
      value: z.string().optional().describe("Optional component value (e.g., '10k')"),
      footprint: z.string().optional().describe("Optional specific footprint name"),
      rotation: z.number().optional().describe("Optional rotation in degrees"),
      layer: z.string().optional().describe("Optional layer (e.g., 'F.Cu', 'B.SilkS')"),
      boardPath: z
        .string()
        .optional()
        .describe(
          "Path to the .kicad_pcb file – required when using project-local footprint libraries",
        ),
    },
    async ({ componentId, position, reference, value, footprint, rotation, layer, boardPath }) => {
      logger.debug(
        `Placing component: ${componentId} at ${position.x},${position.y} ${position.unit}`,
      );
      const result = await callKicadScript("place_component", {
        componentId,
        position,
        reference,
        value,
        footprint,
        rotation,
        layer,
        boardPath,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Move Component Tool
  // ------------------------------------------------------
  server.tool(
    "move_component",
    "Move a PCB component to a new position. Optionally update rotation or flip to a different copper layer.",
    {
      reference: z.string().describe("Reference designator of the component (e.g., 'R5')"),
      position: z
        .object({
          x: z.number().describe("X coordinate"),
          y: z.number().describe("Y coordinate"),
          unit: z.enum(["mm", "inch", "mil"]).describe("Unit of measurement"),
        })
        .describe("New position coordinates and unit"),
      rotation: z.number().optional().describe("Optional new rotation in degrees"),
      layer: z
        .string()
        .optional()
        .describe("Optional target layer (e.g., 'F.Cu', 'B.Cu') - flips component if needed"),
    },
    async ({ reference, position, rotation, layer }) => {
      logger.debug(
        `Moving component: ${reference} to ${position.x},${position.y} ${position.unit}`,
      );
      const result = await callKicadScript("move_component", {
        reference,
        position,
        rotation,
        layer,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  server.tool(
    "batch_move_components",
    "Move multiple PCB components transactionally. If one reference/spec is invalid, no components are moved. Saves by default unless save=false.",
    {
      moves: z
        .record(
          z.string(),
          z.object({
            x: z.number().optional(),
            y: z.number().optional(),
            unit: z.enum(["mm", "inch", "mil"]).optional(),
            position: z
              .object({
                x: z.number(),
                y: z.number(),
                unit: z.enum(["mm", "inch", "mil"]).optional(),
              })
              .optional(),
            rotation: z.number().optional(),
            rot: z.number().optional(),
            layer: z.string().optional(),
          }),
        )
        .describe("Map of reference designator to placement spec"),
      save: z
        .boolean()
        .optional()
        .describe("Save the board after all moves succeed (default true)"),
      dryRun: z.boolean().optional().describe("Validate the batch without changing the board"),
    },
    async (args) => {
      logger.debug(`Batch moving ${Object.keys(args.moves).length} components`);
      const result = await callKicadScript("batch_move_components", args);
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    },
  );

  // ------------------------------------------------------
  // Rotate Component Tool
  // ------------------------------------------------------
  server.tool(
    "rotate_component",
    "Rotate a PCB component to an absolute angle in degrees.",
    {
      reference: z.string().describe("Reference designator of the component (e.g., 'R5')"),
      angle: z.number().describe("Rotation angle in degrees (absolute, not relative)"),
    },
    async ({ reference, angle }) => {
      logger.debug(`Rotating component: ${reference} to ${angle} degrees`);
      const result = await callKicadScript("rotate_component", {
        reference,
        angle,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Delete Component Tool
  // ------------------------------------------------------
  server.tool(
    "delete_component",
    "Remove a component from the PCB by its reference designator.",
    {
      reference: z
        .string()
        .describe("Reference designator of the component to delete (e.g., 'R5')"),
    },
    async ({ reference }) => {
      logger.debug(`Deleting component: ${reference}`);
      const result = await callKicadScript("delete_component", { reference });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Edit Component Properties Tool
  // ------------------------------------------------------
  server.tool(
    "edit_component",
    "Edit properties of an existing PCB component (reference, value, footprint).",
    {
      reference: z.string().describe("Reference designator of the component (e.g., 'R5')"),
      newReference: z.string().optional().describe("Optional new reference designator"),
      value: z.string().optional().describe("Optional new component value"),
      footprint: z.string().optional().describe("Optional new footprint"),
    },
    async ({ reference, newReference, value, footprint }) => {
      logger.debug(`Editing component: ${reference}`);
      const result = await callKicadScript("edit_component", {
        reference,
        newReference,
        value,
        footprint,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Set Footprint Type Tool
  // ------------------------------------------------------
  server.tool(
    "set_footprint_type",
    "Set the placement type (through_hole / smd / unspecified) and optional exclusion flags on a placed PCB footprint. The placement type controls whether the footprint is included in pick-and-place (.pos) output files. Use exclude_from_pos_files to suppress a footprint from .pos exports without changing its type.",
    {
      reference: z.string().describe("Reference designator of the footprint (e.g. 'R1', 'U3')"),
      type: z
        .enum(["smd", "through_hole", "unspecified"])
        .describe(
          "Placement type: 'smd' for surface-mount, 'through_hole' for PTH components, 'unspecified' to clear both bits (e.g. for board-only or mechanically-placed items)",
        ),
      exclude_from_pos_files: z
        .boolean()
        .optional()
        .describe(
          "When true, suppress this footprint from pick-and-place (.pos) exports. Omit to leave the current setting unchanged.",
        ),
      exclude_from_bom: z
        .boolean()
        .optional()
        .describe(
          "When true, suppress this footprint from BoM exports. Omit to leave the current setting unchanged.",
        ),
      not_in_schematic: z
        .boolean()
        .optional()
        .describe(
          "When true, marks the footprint as board-only (no corresponding schematic symbol). Omit to leave the current setting unchanged.",
        ),
    },
    async ({ reference, type, exclude_from_pos_files, exclude_from_bom, not_in_schematic }) => {
      logger.debug(`Setting footprint type for: ${reference} -> ${type}`);
      const result = await callKicadScript("set_footprint_type", {
        reference,
        type,
        exclude_from_pos_files,
        exclude_from_bom,
        not_in_schematic,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Find Component Tool
  // ------------------------------------------------------
  server.tool(
    "find_component",
    "Search for a PCB component by reference designator or value and return its position and properties.",
    {
      reference: z.string().optional().describe("Reference designator to search for"),
      value: z.string().optional().describe("Component value to search for"),
    },
    async ({ reference, value }) => {
      logger.debug(
        `Finding component with ${reference ? `reference: ${reference}` : `value: ${value}`}`,
      );
      const result = await callKicadScript("find_component", {
        reference,
        value,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Get Component Properties Tool
  // ------------------------------------------------------
  server.tool(
    "get_component_properties",
    "Return all properties of a PCB component (position, rotation, layer, value, footprint).",
    {
      reference: z.string().describe("Reference designator of the component (e.g., 'R5')"),
    },
    async ({ reference }) => {
      logger.debug(`Getting properties for component: ${reference}`);
      const result = await callKicadScript("get_component_properties", {
        reference,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Add Component Annotation Tool
  // ------------------------------------------------------
  server.tool(
    "add_component_annotation",
    "Add a text annotation or comment to a PCB component.",
    {
      reference: z.string().describe("Reference designator of the component (e.g., 'R5')"),
      annotation: z.string().describe("Annotation or comment text to add"),
      visible: z
        .boolean()
        .optional()
        .describe("Whether the annotation should be visible on the PCB"),
    },
    async ({ reference, annotation, visible }) => {
      logger.debug(`Adding annotation to component: ${reference}`);
      const result = await callKicadScript("add_component_annotation", {
        reference,
        annotation,
        visible,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Group Components Tool
  // ------------------------------------------------------
  server.tool(
    "group_components",
    "Group multiple PCB components together by name for easier selection and manipulation.",
    {
      references: z.array(z.string()).describe("Reference designators of components to group"),
      groupName: z.string().describe("Name for the component group"),
    },
    async ({ references, groupName }) => {
      logger.debug(`Grouping components: ${references.join(", ")} as ${groupName}`);
      const result = await callKicadScript("group_components", {
        references,
        groupName,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Replace Component Tool
  // ------------------------------------------------------
  server.tool(
    "replace_component",
    "Replace an existing PCB component with a different component type, optionally changing footprint and value.",
    {
      reference: z.string().describe("Reference designator of the component to replace"),
      newComponentId: z.string().describe("ID of the new component to use"),
      newFootprint: z.string().optional().describe("Optional new footprint"),
      newValue: z.string().optional().describe("Optional new component value"),
    },
    async ({ reference, newComponentId, newFootprint, newValue }) => {
      logger.debug(`Replacing component: ${reference} with ${newComponentId}`);
      const result = await callKicadScript("replace_component", {
        reference,
        newComponentId,
        newFootprint,
        newValue,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Get Component Pads Tool
  // ------------------------------------------------------
  server.tool(
    "get_component_pads",
    "Return all pads of a PCB component with their positions, net assignments and sizes.",
    {
      reference: z.string().describe("Reference designator of the component (e.g., 'U1')"),
      unit: z.enum(["mm", "mil", "inch"]).optional().describe("Unit for coordinates (default: mm)"),
    },
    async ({ reference, unit }) => {
      logger.debug(`Getting pads for component: ${reference}`);
      const result = await callKicadScript("get_component_pads", {
        reference,
        unit: unit || "mm",
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  server.tool(
    "get_pads",
    "Return pads for one PCB component, selected refs, or all components, including XY, layer, size and net.",
    {
      reference: z.string().optional().describe("Optional component reference designator"),
      refs: z.array(z.string()).optional().describe("Optional reference filter"),
      unit: z.enum(["mm", "mil", "inch"]).optional().describe("Unit for coordinates (default: mm)"),
    },
    async ({ reference, refs, unit }) => {
      const result = await callKicadScript("get_pads", {
        reference,
        refs,
        unit: unit || "mm",
      });
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    },
  );

  server.tool(
    "get_net_pads",
    "Return every PCB pad attached to a net name or net code.",
    {
      net: z.string().optional().describe("Net name"),
      netCode: z.number().optional().describe("KiCad net code"),
      unit: z.enum(["mm", "mil", "inch"]).optional().describe("Unit for coordinates (default: mm)"),
    },
    async ({ net, netCode, unit }) => {
      const result = await callKicadScript("get_net_pads", { net, netCode, unit: unit || "mm" });
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    },
  );

  server.tool(
    "get_component_geometry",
    "Return separated footprint geometry bboxes: body, pads, courtyard, keepout, fab, silk and text.",
    {
      reference: z.string().optional().describe("Optional single component reference"),
      refs: z.array(z.string()).optional().describe("Optional list of component references"),
    },
    async ({ reference, refs }) => {
      const result = await callKicadScript("get_component_geometry", { reference, refs });
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    },
  );

  // ------------------------------------------------------
  // Get Component List Tool
  // ------------------------------------------------------
  server.tool(
    "get_component_list",
    "Return a list of all components on the PCB, optionally filtered by layer or bounding box region.",
    {
      layer: z.string().optional().describe("Filter by layer (e.g., 'F.Cu', 'B.Cu')"),
      boundingBox: z
        .object({
          x1: z.number(),
          y1: z.number(),
          x2: z.number(),
          y2: z.number(),
          unit: z.enum(["mm", "inch", "mil"]).optional(),
        })
        .optional()
        .describe("Filter by bounding box region"),
      unit: z.enum(["mm", "mil", "inch"]).optional().describe("Unit for coordinates (default: mm)"),
    },
    async ({ layer, boundingBox, unit }) => {
      logger.debug("Getting component list");
      const result = await callKicadScript("get_component_list", {
        layer,
        boundingBox,
        unit: unit || "mm",
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Get Pad Position Tool
  // ------------------------------------------------------
  server.tool(
    "get_pad_position",
    "Return the exact XY position of a specific pad on a PCB component. Use this before routing to get accurate start/end coordinates.",
    {
      reference: z.string().describe("Component reference designator (e.g., 'U1')"),
      pad: z.string().describe("Pad number or name (e.g., '1', 'A1')"),
      unit: z.enum(["mm", "mil", "inch"]).optional().describe("Unit for coordinates (default: mm)"),
    },
    async ({ reference, pad, unit }) => {
      logger.debug(`Getting pad position for ${reference} pad ${pad}`);
      const result = await callKicadScript("get_pad_position", {
        reference,
        pad,
        unit: unit || "mm",
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  server.tool(
    "get_ratsnest",
    "Estimate ratsnest/airwire segments and lengths from current pad positions grouped by net.",
    {
      nets: z.array(z.string()).optional().describe("Optional net-name filter"),
      maxPadsPerNet: z.number().optional().describe("Skip nets above this pad count (default 128)"),
    },
    async ({ nets, maxPadsPerNet }) => {
      const result = await callKicadScript("get_ratsnest", { nets, maxPadsPerNet });
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    },
  );

  server.tool(
    "estimate_airwire_lengths",
    "Alias for get_ratsnest: estimate airwire segments and lengths by net.",
    {
      nets: z.array(z.string()).optional(),
      maxPadsPerNet: z.number().optional(),
    },
    async ({ nets, maxPadsPerNet }) => {
      const result = await callKicadScript("estimate_airwire_lengths", { nets, maxPadsPerNet });
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    },
  );

  server.tool(
    "check_placement_clearance",
    "Classify placement conflicts as body overlap, courtyard overlap, keepout violation, silk/text overlap or pad clearance.",
    {
      refs: z.array(z.string()).optional().describe("Optional component reference filter"),
      margin: z.number().optional().describe("Extra bbox margin in mm for mechanical checks"),
      padClearance: z.number().optional().describe("Extra pad bbox clearance in mm"),
    },
    async ({ refs, margin, padClearance }) => {
      const result = await callKicadScript("check_placement_clearance", {
        refs,
        margin,
        padClearance,
      });
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    },
  );

  server.tool(
    "move_footprint_text",
    "Move or update a footprint Reference/Value/user text field without moving the footprint.",
    {
      reference: z.string().describe("Component reference designator"),
      field: z.string().describe("Text field to move, e.g. reference or value"),
      x: z.number().optional().describe("New X coordinate"),
      y: z.number().optional().describe("New Y coordinate"),
      unit: z.enum(["mm", "inch", "mil"]).optional().describe("Coordinate unit"),
      rotation: z.number().optional().describe("Optional text rotation in degrees"),
      layer: z.string().optional().describe("Optional destination layer"),
      visible: z.boolean().optional().describe("Optional visibility"),
    },
    async (args) => {
      const result = await callKicadScript("move_footprint_text", args);
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    },
  );

  // ------------------------------------------------------
  // Place Component Array Tool
  // ------------------------------------------------------
  server.tool(
    "place_component_array",
    "Place a rectangular grid array of identical components on the PCB with configurable row/column spacing.",
    {
      componentId: z.string().describe("Component identifier"),
      startPosition: z
        .object({
          x: z.number(),
          y: z.number(),
          unit: z.enum(["mm", "inch", "mil"]),
        })
        .describe("Starting position"),
      rows: z.number().describe("Number of rows"),
      columns: z.number().describe("Number of columns"),
      rowSpacing: z.number().describe("Spacing between rows"),
      columnSpacing: z.number().describe("Spacing between columns"),
      startReference: z.string().optional().describe("Starting reference (e.g., 'R1')"),
      footprint: z.string().optional().describe("Footprint name"),
      value: z.string().optional().describe("Component value"),
      rotation: z.number().optional().describe("Rotation in degrees"),
    },
    async ({
      componentId,
      startPosition,
      rows,
      columns,
      rowSpacing,
      columnSpacing,
      startReference,
      footprint,
      value,
      rotation,
    }) => {
      logger.debug(`Placing component array: ${rows}x${columns} of ${componentId}`);
      const result = await callKicadScript("place_component_array", {
        componentId,
        startPosition,
        rows,
        columns,
        rowSpacing,
        columnSpacing,
        startReference,
        footprint,
        value,
        rotation,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Align Components Tool
  // ------------------------------------------------------
  server.tool(
    "align_components",
    "Align multiple PCB components horizontally, vertically or on a grid with optional spacing.",
    {
      references: z.array(z.string()).describe("Array of component references to align"),
      alignmentType: z.enum(["horizontal", "vertical", "grid"]).describe("Type of alignment"),
      spacing: z.number().optional().describe("Spacing between components in mm"),
      referenceComponent: z.string().optional().describe("Reference component for alignment"),
    },
    async ({ references, alignmentType, spacing, referenceComponent }) => {
      logger.debug(`Aligning components: ${references.join(", ")}`);
      const result = await callKicadScript("align_components", {
        references,
        alignmentType,
        spacing,
        referenceComponent,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Check Courtyard Overlaps Tool
  //
  // Lets the caller validate a placement plan before committing it. The
  // `positions` parameter accepts hypothetical {ref: [x, y]} or
  // [x, y, rotation_degrees] entries; the board file is not modified.
  //
  // Approach ported from morningfire-pcb-automation
  //   https://github.com/NiNjA-CodE/morningfire-pcb-automation
  //   (scripts/placement/check_overlaps.py)
  // ------------------------------------------------------
  server.tool(
    "check_courtyard_overlaps",
    "Detect courtyard overlaps between footprints and (optionally) flag courtyards that extend past the board outline. Accepts a `positions` dict of hypothetical placements so an AI can validate a proposed move_component / place_component before committing it. Returns overlap pairs with intersection extents (mm) and per-component boundary violations.",
    {
      positions: z
        .record(z.string(), z.array(z.number()).min(2).max(3))
        .optional()
        .describe(
          "Virtual placements: map of reference designator to [x, y] or [x, y, rotation_degrees] in mm. Each listed ref is checked AS IF it were at the given coordinates. Unspecified refs use their current board position.",
        ),
      refs: z
        .array(z.string())
        .optional()
        .describe("Limit the check to these refs (default: every footprint on the board)."),
      margin: z
        .number()
        .optional()
        .describe(
          "Extra clearance in mm added around every courtyard (default 0). Useful to enforce a manufacturing keepout wider than the symbol's declared courtyard.",
        ),
      include_boundary: z
        .boolean()
        .optional()
        .describe("Also flag courtyards that extend past the board outline (default true)."),
      board_outline: z
        .object({
          x1: z.number(),
          y1: z.number(),
          x2: z.number(),
          y2: z.number(),
          unit: z.enum(["mm", "inch"]).optional(),
        })
        .optional()
        .describe("Optional board outline bbox override. Default: derived from Edge.Cuts."),
    },
    async (args) => {
      logger.debug(
        `Checking courtyard overlaps (virtual=${
          args.positions ? Object.keys(args.positions).length : 0
        })`,
      );
      const result = await callKicadScript("check_courtyard_overlaps", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Suggest Placement Tool
  // ------------------------------------------------------
  server.tool(
    "suggest_placement",
    "Propose an optimized PCB footprint placement that shortens net length, orients parts toward their partners, and removes courtyard overlaps. Force-directed clustering pulls connected parts together (a converter's feedback divider and decoupling caps end up hugging its IC), power/high-current nets are weighted short & direct, and each part is rotated (0/90/180/270) to face neighbours so airwires stop crossing. PCB ONLY — does not touch the schematic. DRY RUN by default: returns proposals {ref:[x,y,rot]} plus a score (HPWL before/after, overlap counts) without modifying the board. Validate via check_courtyard_overlaps(positions=proposals), then re-run with apply=true before autoroute.",
    {
      refs: z
        .array(z.string())
        .optional()
        .describe("References to move (default: every non-locked footprint on the board)."),
      locked: z
        .array(z.string())
        .optional()
        .describe(
          "References to hold fixed as anchors (connectors, mounting-constrained, RF, edge parts). They still pull movable parts. KiCad-locked footprints are added automatically.",
        ),
      apply: z
        .boolean()
        .optional()
        .describe(
          "If true, move + rotate components to the proposed positions. Default false (dry run — board untouched).",
        ),
      iterations: z.number().optional().describe("Force-directed relaxation passes (default 200)."),
      grid_mm: z
        .number()
        .optional()
        .describe("Snap proposed positions to this grid (default 0.5)."),
      margin_mm: z
        .number()
        .optional()
        .describe("Extra keepout enforced between courtyards (default 0.3)."),
      rotate: z.boolean().optional().describe("Enable pin-facing rotation (default true)."),
      spread: z
        .boolean()
        .optional()
        .describe(
          "Enable density spreading (default true). Diffuses parts across free board area so a whole-board run stays legal (few/zero courtyard overlaps) instead of over-packing into a blob. Leave on for whole-board runs.",
        ),
      align: z
        .boolean()
        .optional()
        .describe(
          "Tidy the result into rows/columns (default true). Snaps near-collinear part centers onto shared row (Y) and column (X) lines so passives line up cleanly with centers aligned — like KiCad's Align Centers + Distribute. Disable for a pure shortest-wire layout.",
        ),
      align_tol_mm: z
        .number()
        .optional()
        .describe(
          "Max center spacing (mm) for parts to be pulled onto the same row/column line during align (default 1.5).",
        ),
      rotation_steps: z
        .array(z.number())
        .optional()
        .describe("Candidate orientations in degrees (default [0, 90, 180, 270])."),
      power_nets: z
        .array(z.string())
        .optional()
        .describe(
          "Net-name fragments treated as high-current and pulled short & direct (case-insensitive). Defaults to common rails (VBAT, VBUS, VCC, 3V3, 5V, ...). Pass [] to disable.",
        ),
      power_weight: z.number().optional().describe("Pull multiplier for power nets (default 3.0)."),
      decoupling_boost: z
        .number()
        .optional()
        .describe(
          "Extra pull for 2-pin-passive <-> multi-pin-IC links so caps/feedback parts hug their IC (default 2.0).",
        ),
      bounds: z
        .object({
          x1: z.number(),
          y1: z.number(),
          x2: z.number(),
          y2: z.number(),
          unit: z.enum(["mm", "mil", "inch"]).optional(),
        })
        .optional()
        .describe(
          "SCOPED REGROUP: confine movable parts to this box (mm) — e.g. the area beside one IC. Combine with `refs` (that IC's passives) to regroup one cluster at a time; unlisted parts stay as anchors. Far more reliable than a whole-board run on a dense board. Default: whole board.",
        ),
      board_outline: z
        .object({
          x1: z.number(),
          y1: z.number(),
          x2: z.number(),
          y2: z.number(),
          unit: z.enum(["mm", "mil", "inch"]).optional(),
        })
        .optional()
        .describe("Optional board containment bbox override. Default: derived from Edge.Cuts."),
    },
    async (args) => {
      logger.debug(`Suggesting placement (apply=${args.apply ? "true" : "false"})`);
      const result = await callKicadScript("suggest_placement", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Duplicate Component Tool
  // ------------------------------------------------------
  server.tool(
    "duplicate_component",
    "Duplicate an existing PCB component at an offset position, optionally with a new reference designator.",
    {
      reference: z.string().describe("Reference of component to duplicate"),
      offset: z
        .object({
          x: z.number(),
          y: z.number(),
          unit: z.enum(["mm", "inch", "mil"]).optional(),
        })
        .describe("Offset from original position"),
      newReference: z.string().optional().describe("New reference designator"),
      count: z.number().optional().describe("Number of duplicates (default: 1)"),
    },
    async ({ reference, offset, newReference, count }) => {
      logger.debug(`Duplicating component: ${reference}`);
      const result = await callKicadScript("duplicate_component", {
        reference,
        offset,
        newReference,
        count,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  logger.info("Component management tools registered");
}
