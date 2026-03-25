/**
 * Schematic tools for KiCAD MCP server
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerSchematicTools(
  server: McpServer,
  callKicadScript: Function,
) {
  // Create schematic tool
  server.tool(
    "create_schematic",
    "Create a new schematic",
    {
      name: z.string().describe("Schematic name"),
      path: z.string().optional().describe("Optional path"),
      paperSize: z.string().optional().describe("Paper size: A4, A3, A2, A1, A0, letter, legal, or custom dimensions"),
    },
    async (args: { name: string; path?: string; paperSize?: string }) => {
      const result = await callKicadScript("create_schematic", args);
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

  // Add component to schematic
  server.tool(
    "add_schematic_component",
    "Add a component to the schematic. Symbol format is 'Library:SymbolName' (e.g., 'Device:R', 'EDA-MCP:ESP32-C3')",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      symbol: z
        .string()
        .describe(
          "Symbol library:name reference (e.g., Device:R, EDA-MCP:ESP32-C3)",
        ),
      reference: z.string().describe("Component reference (e.g., R1, U1)"),
      value: z.string().optional().describe("Component value"),
      footprint: z.string().optional().describe("KiCAD footprint (e.g. Resistor_SMD:R_0603_1608Metric)"),
      position: z
        .object({
          x: z.number(),
          y: z.number(),
        })
        .optional()
        .describe("Position on schematic"),
      rotation: z
        .number()
        .optional()
        .describe("Rotation in degrees (0, 90, 180, 270)"),
    },
    async (args: {
      schematicPath: string;
      symbol: string;
      reference: string;
      value?: string;
      footprint?: string;
      position?: { x: number; y: number };
      rotation?: number;
    }) => {
      // Transform to what Python backend expects
      const [library, symbolName] = args.symbol.includes(":")
        ? args.symbol.split(":")
        : ["Device", args.symbol];

      const transformed = {
        schematicPath: args.schematicPath,
        component: {
          library,
          type: symbolName,
          reference: args.reference,
          value: args.value,
          footprint: args.footprint ?? "",
          // Python expects flat x, y not nested position
          x: args.position?.x ?? 0,
          y: args.position?.y ?? 0,
          rotation: args.rotation ?? 0,
        },
      };

      const result = await callKicadScript(
        "add_schematic_component",
        transformed,
      );
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Successfully added ${args.reference} (${args.symbol}) to schematic`,
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Failed to add component: ${result.message || JSON.stringify(result)}`,
            },
          ],
        };
      }
    },
  );

  // Delete component from schematic
  server.tool(
    "delete_schematic_component",
    `Remove a placed symbol from a KiCAD schematic (.kicad_sch).

This removes the symbol instance (the placed component) from the schematic.
It does NOT remove the symbol definition from lib_symbols.

Note: This tool operates on schematic files (.kicad_sch).
To remove a footprint from a PCB, use delete_component instead.`,
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z
        .string()
        .describe("Reference designator of the component to remove (e.g. R1, U3)"),
    },
    async (args: { schematicPath: string; reference: string }) => {
      const result = await callKicadScript("delete_schematic_component", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Successfully removed ${args.reference} from schematic`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to remove component: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // Edit component properties in schematic (footprint, value, reference)
  server.tool(
    "edit_schematic_component",
    `Update properties of a placed symbol in a KiCAD schematic (.kicad_sch) in-place.

Use this tool to assign or update a footprint, change the value, or rename the reference
of an already-placed component. This is more efficient than delete + re-add because it
preserves the component's position and UUID.

Note: operates on .kicad_sch files only. To modify a PCB footprint use edit_component.`,
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Current reference designator of the component (e.g. R1, U3)"),
      footprint: z.string().optional().describe("New KiCAD footprint string (e.g. Resistor_SMD:R_0603_1608Metric)"),
      value: z.string().optional().describe("New value string (e.g. 10k, 100nF)"),
      newReference: z.string().optional().describe("Rename the reference designator (e.g. R1 → R10)"),
      fieldPositions: z.record(z.object({
        x: z.number(),
        y: z.number(),
        angle: z.number().optional().default(0),
      })).optional().describe("Reposition field labels: map of field name to {x, y, angle} (e.g. {\"Reference\": {\"x\": 12.5, \"y\": 17.0}})"),
      hiddenFields: z.record(z.boolean()).optional().describe("Set field visibility: map of field name to hidden boolean (e.g. {\"Reference\": true} hides Reference)"),
    },
    async (args: {
      schematicPath: string;
      reference: string;
      footprint?: string;
      value?: string;
      newReference?: string;
      fieldPositions?: Record<string, { x: number; y: number; angle?: number }>;
      hiddenFields?: Record<string, boolean>;
    }) => {
      const result = await callKicadScript("edit_schematic_component", args);
      if (result.success) {
        const changes = Object.entries(result.updated ?? {})
          .map(([k, v]) => `${k}=${v}`)
          .join(", ");
        return {
          content: [
            {
              type: "text" as const,
              text: `Successfully updated ${args.reference}: ${changes}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text" as const,
            text: `Failed to edit component: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // Get component properties and field positions from schematic
  server.tool(
    "get_schematic_component",
    "Get full component info from a schematic: position, field values, and each field's label position (at x/y/angle). Use this to inspect or prepare repositioning of Reference/Value labels.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Component reference designator (e.g. R1, U1)"),
    },
    async (args: { schematicPath: string; reference: string }) => {
      const result = await callKicadScript("get_schematic_component", args);
      if (result.success) {
        const pos = result.position
          ? `(${result.position.x}, ${result.position.y}, angle=${result.position.angle}°)`
          : "unknown";
        const fieldLines = Object.entries(result.fields ?? {}).map(
          ([name, f]: [string, any]) =>
            `  ${name}: "${f.value}" @ (${f.x}, ${f.y}, angle=${f.angle}°)`
        );
        return {
          content: [{
            type: "text",
            text: `Component ${result.reference} at ${pos}\nFields:\n${fieldLines.join("\n")}`,
          }],
        };
      }
      return {
        content: [{
          type: "text",
          text: `Failed to get component: ${result.message || "Unknown error"}`,
        }],
      };
    },
  );

  // Connect components with wire
  server.tool(
    "add_wire",
    "Add a wire connection in the schematic",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      start: z
        .object({
          x: z.number(),
          y: z.number(),
        })
        .describe("Start position"),
      end: z
        .object({
          x: z.number(),
          y: z.number(),
        })
        .describe("End position"),
    },
    async (args: any) => {
      const result = await callKicadScript("add_schematic_wire", args);
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

  // Add pin-to-pin connection
  server.tool(
    "add_schematic_connection",
    "Connect two component pins with a wire. Use this for individual connections between components with different pin roles (e.g. U1.SDA → J3.2). WARNING: Do NOT use this in a loop to wire N passthrough pins — use connect_passthrough instead (single call, cleaner layout, far fewer tokens).",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      sourceRef: z.string().describe("Source component reference (e.g., R1)"),
      sourcePin: z
        .string()
        .describe("Source pin name/number (e.g., 1, 2, GND)"),
      targetRef: z.string().describe("Target component reference (e.g., C1)"),
      targetPin: z
        .string()
        .describe("Target pin name/number (e.g., 1, 2, VCC)"),
    },
    async (args: {
      schematicPath: string;
      sourceRef: string;
      sourcePin: string;
      targetRef: string;
      targetPin: string;
    }) => {
      const result = await callKicadScript("add_schematic_connection", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Successfully connected ${args.sourceRef}/${args.sourcePin} to ${args.targetRef}/${args.targetPin}`,
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Failed to add connection: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // Add net label
  server.tool(
    "add_schematic_net_label",
    "Add a net label to the schematic. Labels are placed at the specified angle (default 0). Use angle to control flag direction: 0° = flag left/connection right, 180° = flag right/connection left, 90° = flag up/connection down, 270° = flag down/connection up.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      netName: z
        .string()
        .describe("Name of the net (e.g., VCC, GND, SIGNAL_1)"),
      position: z
        .array(z.number())
        .length(2)
        .describe("Position [x, y] for the label"),
      orientation: z.number().optional().describe("Label angle in degrees: 0, 90, 180, 270 (default: 0). Controls flag direction."),
      labelType: z.enum(["label", "global_label", "hierarchical_label"]).optional().describe("Label type (default: label). Use global_label for bordered labels visible across sheets."),
      shape: z.string().optional().describe("For global_label: input, output, bidirectional, passive, tri_state"),
    },
    async (args: {
      schematicPath: string;
      netName: string;
      position: number[];
      labelType?: string;
      shape?: string;
    }) => {
      const result = await callKicadScript("add_schematic_net_label", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Successfully added net label '${args.netName}' at position [${args.position}]`,
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Failed to add net label: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // Connect pin to net
  server.tool(
    "connect_to_net",
    "Connect a component pin to a named net via a 2.54mm wire stub and label. The label is placed at the default angle for the pin direction. If the flag overlaps the component body, use rotate_schematic_label afterward to flip the flag direction.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      componentRef: z.string().describe("Component reference (e.g., U1, R1)"),
      pinName: z.string().describe("Pin name/number to connect"),
      netName: z.string().describe("Name of the net to connect to"),
      labelType: z.enum(["label", "global_label"]).optional().describe("Label type (default: auto-detects power nets)"),
      shape: z.string().optional().describe("For global_label: input, output, bidirectional, passive"),
    },
    async (args: {
      schematicPath: string;
      componentRef: string;
      pinName: string;
      netName: string;
      labelType?: "label" | "global_label";
      shape?: string;
    }) => {
      const result = await callKicadScript("connect_to_net", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Successfully connected ${args.componentRef}/${args.pinName} to net '${args.netName}'`,
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Failed to connect to net: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // Get net connections
  server.tool(
    "get_net_connections",
    "Get all connections for a named net",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      netName: z.string().describe("Name of the net to query"),
    },
    async (args: { schematicPath: string; netName: string }) => {
      const result = await callKicadScript("get_net_connections", args);
      if (result.success && result.connections) {
        const connectionList = result.connections
          .map((conn: any) => `  - ${conn.component}/${conn.pin}`)
          .join("\n");
        return {
          content: [
            {
              type: "text",
              text: `Net '${args.netName}' connections:\n${connectionList}`,
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Failed to get net connections: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // Get pin locations for a schematic component
  server.tool(
    "get_schematic_pin_locations",
    "Returns the exact x/y coordinates of every pin on a schematic component. Use this before add_schematic_net_label to place labels correctly on pin endpoints.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      reference: z.string().describe("Component reference designator (e.g. U1, R1, J2)"),
    },
    async (args: { schematicPath: string; reference: string }) => {
      const result = await callKicadScript("get_schematic_pin_locations", args);
      if (result.success && result.pins) {
        const lines = Object.entries(result.pins as Record<string, any>).map(
          ([pinNum, data]: [string, any]) =>
            `  Pin ${pinNum} (${data.name || pinNum}): x=${data.x}, y=${data.y}, angle=${data.angle ?? 0}°`
        );
        return {
          content: [{
            type: "text",
            text: `Pin locations for ${args.reference}:\n${lines.join("\n")}`,
          }],
        };
      } else {
        return {
          content: [{
            type: "text",
            text: `Failed to get pin locations: ${result.message || "Unknown error"}`,
          }],
        };
      }
    },
  );

  // Connect all pins of source connector to matching pins of target connector (passthrough)
  server.tool(
    "connect_passthrough",
    "Connects all pins of a source connector (e.g. J1) to matching pins of a target connector (e.g. J2) via shared net labels — pin N gets net '{netPrefix}_{N}'. Use this for FFC/ribbon cable passthrough adapters instead of calling connect_to_net for every pin.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      sourceRef: z.string().describe("Source connector reference (e.g. J1)"),
      targetRef: z.string().describe("Target connector reference (e.g. J2)"),
      netPrefix: z.string().optional().describe("Net name prefix, e.g. 'CSI' → CSI_1, CSI_2 (default: PIN)"),
      pinOffset: z.number().optional().describe("Add to pin number when building net name (default: 0)"),
    },
    async (args: { schematicPath: string; sourceRef: string; targetRef: string; netPrefix?: string; pinOffset?: number }) => {
      const result = await callKicadScript("connect_passthrough", args);
      if (result.success !== false || (result.connected && result.connected.length > 0)) {
        const lines: string[] = [];
        if (result.connected?.length) lines.push(`Connected (${result.connected.length}): ${result.connected.slice(0, 5).join(", ")}${result.connected.length > 5 ? " ..." : ""}`);
        if (result.failed?.length) lines.push(`Failed (${result.failed.length}): ${result.failed.join(", ")}`);
        return {
          content: [{ type: "text", text: result.message + "\n" + lines.join("\n") }],
        };
      } else {
        return {
          content: [{ type: "text", text: `Passthrough failed: ${result.message || "Unknown error"}` }],
        };
      }
    },
  );

  // List all components in schematic
  server.tool(
    "list_schematic_components",
    "List all components in a schematic with their references, values, positions, and pins. Essential for inspecting what's on the schematic before making edits.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      filter: z
        .object({
          libId: z.string().optional().describe("Filter by library ID (e.g., 'Device:R')"),
          referencePrefix: z.string().optional().describe("Filter by reference prefix (e.g., 'R', 'C', 'U')"),
        })
        .optional()
        .describe("Optional filters"),
    },
    async (args: {
      schematicPath: string;
      filter?: { libId?: string; referencePrefix?: string };
    }) => {
      const result = await callKicadScript("list_schematic_components", args);
      if (result.success) {
        const comps = result.components || [];
        if (comps.length === 0) {
          return {
            content: [{ type: "text", text: "No components found in schematic." }],
          };
        }
        const lines = comps.map(
          (c: any) =>
            `  ${c.reference}: ${c.libId} = "${c.value}" at (${c.position.x}, ${c.position.y}) rot=${c.rotation}°${c.pins ? ` [${c.pins.length} pins]` : ""}`,
        );
        return {
          content: [
            {
              type: "text",
              text: `Components (${comps.length}):\n${lines.join("\n")}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to list components: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // List all nets in schematic
  server.tool(
    "list_schematic_nets",
    "List all nets in the schematic with their connections.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("list_schematic_nets", args);
      if (result.success) {
        const nets = result.nets || [];
        if (nets.length === 0) {
          return {
            content: [{ type: "text", text: "No nets found in schematic." }],
          };
        }
        const lines = nets.map((n: any) => {
          const conns = (n.connections || [])
            .map((c: any) => `${c.component}/${c.pin}`)
            .join(", ");
          return `  ${n.name}: ${conns || "(no connections)"}`;
        });
        return {
          content: [
            {
              type: "text",
              text: `Nets (${nets.length}):\n${lines.join("\n")}`,
            },
          ],
        };
      }
      return {
        content: [
          { type: "text", text: `Failed to list nets: ${result.message || "Unknown error"}` },
        ],
        isError: true,
      };
    },
  );

  // List all wires in schematic
  server.tool(
    "list_schematic_wires",
    "List all wires in the schematic with start/end coordinates.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("list_schematic_wires", args);
      if (result.success) {
        const wires = result.wires || [];
        if (wires.length === 0) {
          return {
            content: [{ type: "text", text: "No wires found in schematic." }],
          };
        }
        const lines = wires.map(
          (w: any) =>
            `  (${w.start.x}, ${w.start.y}) → (${w.end.x}, ${w.end.y})`,
        );
        return {
          content: [
            {
              type: "text",
              text: `Wires (${wires.length}):\n${lines.join("\n")}`,
            },
          ],
        };
      }
      return {
        content: [
          { type: "text", text: `Failed to list wires: ${result.message || "Unknown error"}` },
        ],
        isError: true,
      };
    },
  );

  // List all labels in schematic
  server.tool(
    "list_schematic_labels",
    "List all net labels, global labels, and power flags in the schematic.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("list_schematic_labels", args);
      if (result.success) {
        const labels = result.labels || [];
        if (labels.length === 0) {
          return {
            content: [{ type: "text", text: "No labels found in schematic." }],
          };
        }
        const lines = labels.map(
          (l: any) =>
            `  [${l.type}] ${l.name} at (${l.position.x}, ${l.position.y})`,
        );
        return {
          content: [
            {
              type: "text",
              text: `Labels (${labels.length}):\n${lines.join("\n")}`,
            },
          ],
        };
      }
      return {
        content: [
          { type: "text", text: `Failed to list labels: ${result.message || "Unknown error"}` },
        ],
        isError: true,
      };
    },
  );

  // Move schematic component
  server.tool(
    "move_schematic_component",
    "Move a placed symbol to a new position. WARNING: Does NOT move connected wires, labels, or power symbols. After moving, you must manually reconnect pins with stub wires. Use move_connected instead to preserve connectivity.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Reference designator (e.g., R1, U1)"),
      position: z
        .object({
          x: z.number(),
          y: z.number(),
        })
        .describe("New position"),
    },
    async (args: {
      schematicPath: string;
      reference: string;
      position: { x: number; y: number };
    }) => {
      const result = await callKicadScript("move_schematic_component", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Moved ${args.reference} from (${result.oldPosition.x}, ${result.oldPosition.y}) to (${result.newPosition.x}, ${result.newPosition.y})`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to move component: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Rotate schematic component
  server.tool(
    "rotate_schematic_component",
    "Rotate a placed symbol in the schematic.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Reference designator (e.g., R1, U1)"),
      angle: z.number().describe("Rotation angle in degrees (0, 90, 180, 270)"),
      mirror: z
        .enum(["x", "y"])
        .optional()
        .describe("Optional mirror axis"),
    },
    async (args: {
      schematicPath: string;
      reference: string;
      angle: number;
      mirror?: "x" | "y";
    }) => {
      const result = await callKicadScript("rotate_schematic_component", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Rotated ${args.reference} to ${args.angle}°${args.mirror ? ` (mirrored ${args.mirror})` : ""}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to rotate component: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Annotate schematic
  server.tool(
    "annotate_schematic",
    "Assign reference designators to unannotated components (R? → R1, R2, ...). Must be called before tools that require known references.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("annotate_schematic", args);
      if (result.success) {
        const annotated = result.annotated || [];
        if (annotated.length === 0) {
          return {
            content: [
              { type: "text", text: "All components are already annotated." },
            ],
          };
        }
        const lines = annotated.map(
          (a: any) => `  ${a.oldReference} → ${a.newReference}`,
        );
        return {
          content: [
            {
              type: "text",
              text: `Annotated ${annotated.length} component(s):\n${lines.join("\n")}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to annotate: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Delete wire from schematic
  server.tool(
    "delete_schematic_wire",
    "Remove a wire from the schematic by start and end coordinates.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      start: z
        .object({ x: z.number(), y: z.number() })
        .describe("Wire start position"),
      end: z
        .object({ x: z.number(), y: z.number() })
        .describe("Wire end position"),
    },
    async (args: {
      schematicPath: string;
      start: { x: number; y: number };
      end: { x: number; y: number };
    }) => {
      const result = await callKicadScript("delete_schematic_wire", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Deleted wire from (${args.start.x}, ${args.start.y}) to (${args.end.x}, ${args.end.y})`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to delete wire: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Batch delete wires
  server.tool(
    "batch_delete_schematic_wire",
    "Delete multiple wires in a single call. Each wire is identified by start and end coordinates.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      wires: z.array(z.object({
        start: z.object({ x: z.number(), y: z.number() }).describe("Wire start position"),
        end: z.object({ x: z.number(), y: z.number() }).describe("Wire end position"),
      })).describe("Array of wires to delete"),
    },
    async (args) => {
      const result = await callKicadScript("batch_delete_schematic_wire", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Delete net label from schematic
  server.tool(
    "delete_schematic_net_label",
    "Remove a net label from the schematic.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      netName: z.string().describe("Name of the net label to remove"),
      position: z
        .object({ x: z.number(), y: z.number() })
        .optional()
        .describe("Position to disambiguate if multiple labels with same name"),
    },
    async (args: {
      schematicPath: string;
      netName: string;
      position?: { x: number; y: number };
    }) => {
      const result = await callKicadScript("delete_schematic_net_label", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Deleted net label '${args.netName}'`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to delete label: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Delete no-connect flag from schematic
  server.tool(
    "delete_no_connect",
    "Remove a no-connect (X) flag from the schematic at a given position.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      position: z
        .object({ x: z.number(), y: z.number() })
        .describe("Position of the no-connect flag (mm)"),
    },
    async (args: {
      schematicPath: string;
      position: { x: number; y: number };
    }) => {
      const result = await callKicadScript("delete_no_connect", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Deleted no-connect at (${args.position.x}, ${args.position.y})`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to delete no-connect: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Batch delete no-connect flags
  server.tool(
    "batch_delete_no_connect",
    "Delete multiple no-connect (X) flags in a single call. Each is identified by position.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      positions: z.array(z.object({
        x: z.number(),
        y: z.number(),
      })).describe("Array of positions where no-connect flags should be removed"),
    },
    async (args) => {
      const result = await callKicadScript("batch_delete_no_connect", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Export schematic to SVG
  server.tool(
    "export_schematic_svg",
    "Export schematic to SVG format using kicad-cli.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      outputPath: z.string().describe("Output SVG file path"),
      blackAndWhite: z
        .boolean()
        .optional()
        .describe("Export in black and white"),
    },
    async (args: {
      schematicPath: string;
      outputPath: string;
      blackAndWhite?: boolean;
    }) => {
      const result = await callKicadScript("export_schematic_svg", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Exported schematic SVG to ${result.file?.path || args.outputPath}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to export SVG: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Export schematic to PDF
  server.tool(
    "export_schematic_pdf",
    "Export schematic to PDF format using kicad-cli.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      outputPath: z.string().describe("Output PDF file path"),
      blackAndWhite: z
        .boolean()
        .optional()
        .describe("Export in black and white"),
    },
    async (args: {
      schematicPath: string;
      outputPath: string;
      blackAndWhite?: boolean;
    }) => {
      const result = await callKicadScript("export_schematic_pdf", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Exported schematic PDF to ${result.file?.path || args.outputPath}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to export PDF: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Get schematic view (rasterized image)
  server.tool(
    "get_schematic_view",
    "Return a rasterized image of the schematic (PNG by default, or SVG). Uses kicad-cli to export SVG, then converts to PNG via cairosvg. Use this for visual feedback after placing or wiring components.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      format: z
        .enum(["png", "svg"])
        .optional()
        .describe("Output format (default: png)"),
      width: z.number().optional().describe("Image width in pixels (default: 1200)"),
      height: z.number().optional().describe("Image height in pixels (default: 900)"),
      region: z.object({
        x: z.number().describe("Left edge in schematic mm"),
        y: z.number().describe("Top edge in schematic mm"),
        width: z.number().describe("Region width in mm"),
        height: z.number().describe("Region height in mm"),
      }).optional().describe("Crop to a specific region of the schematic for high-zoom inspection"),
    },
    async (args: {
      schematicPath: string;
      format?: "png" | "svg";
      width?: number;
      height?: number;
      region?: { x: number; y: number; width: number; height: number };
    }) => {
      const result = await callKicadScript("get_schematic_view", args);
      if (result.success) {
        if (result.format === "svg") {
          const parts: { type: "text"; text: string }[] = [];
          if (result.message) {
            parts.push({ type: "text", text: result.message });
          }
          parts.push({
            type: "text",
            text: result.imageData || "",
          });
          return { content: parts };
        }
        // PNG — return as base64 image
        return {
          content: [
            {
              type: "image" as const,
              data: result.imageData,
              mimeType: "image/png",
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to get schematic view: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Run Electrical Rules Check (ERC)
  server.tool(
    "run_erc",
    "Runs the KiCAD Electrical Rules Check (ERC) on a schematic and returns all violations. Use after wiring to verify the schematic before generating a netlist. Note: coordinates in results are auto-scaled to schematic mm, but the heuristic may be wrong for small schematics — if positions look 100x too small, the raw kicad-cli output uses 1/100mm units.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch schematic file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("run_erc", args);
      if (result.success) {
        const violations: any[] = result.violations || [];
        const lines: string[] = [`ERC result: ${violations.length} violation(s)`];
        if (result.summary?.by_severity) {
          const s = result.summary.by_severity;
          lines.push(`  Errors: ${s.error ?? 0}  Warnings: ${s.warning ?? 0}  Info: ${s.info ?? 0}`);
        }
        if (violations.length > 0) {
          lines.push("");
          violations.slice(0, 30).forEach((v: any, i: number) => {
            const loc = v.location && (v.location.x !== undefined) ? ` @ (${v.location.x}, ${v.location.y})` : "";
            lines.push(`${i + 1}. [${v.severity}] ${v.message}${loc}`);
          });
          if (violations.length > 30) {
            lines.push(`... and ${violations.length - 30} more`);
          }
        }
        return { content: [{ type: "text", text: lines.join("\n") }] };
      } else {
        return {
          content: [{ type: "text", text: `ERC failed: ${result.message || "Unknown error"}${result.errorDetails ? "\n" + result.errorDetails : ""}` }],
        };
      }
    },
  );

  // Generate netlist
  server.tool(
    "generate_netlist",
    "Generate a netlist from the schematic",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("generate_netlist", args);
      if (result.success && result.netlist) {
        const netlist = result.netlist;
        const output = [
          `=== Netlist for ${args.schematicPath} ===`,
          `\nComponents (${netlist.components.length}):`,
          ...netlist.components.map(
            (comp: any) =>
              `  ${comp.reference}: ${comp.value} (${comp.footprint || "No footprint"})`,
          ),
          `\nNets (${netlist.nets.length}):`,
          ...netlist.nets.map((net: any) => {
            const connections = net.connections
              .map((conn: any) => `${conn.component}/${conn.pin}`)
              .join(", ");
            return `  ${net.name}: ${connections}`;
          }),
        ].join("\n");

        return {
          content: [
            {
              type: "text",
              text: output,
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Failed to generate netlist: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // Sync schematic to PCB board (equivalent to KiCAD F8 / "Update PCB from Schematic")
  server.tool(
    "sync_schematic_to_board",
    "Import the schematic netlist into the PCB board — equivalent to pressing F8 in KiCAD (Tools → Update PCB from Schematic). MUST be called after the schematic is complete and before placing or routing components on the PCB. Without this step, the board has no footprints and no net assignments — place_component and route_pad_to_pad will produce an empty, unroutable board.",
    {
      schematicPath: z.string().describe("Absolute path to the .kicad_sch schematic file"),
      boardPath: z.string().describe("Absolute path to the .kicad_pcb board file"),
    },
    async (args: { schematicPath: string; boardPath: string }) => {
      const result = await callKicadScript("sync_schematic_to_board", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // Place a power port symbol (GND, +3V3, +5V, VCC, etc.)
  server.tool(
    "add_power_symbol",
    "Place a power port symbol (GND, +3V3, +5V, VCC, etc.) from the KiCad power library",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      symbol: z.string().describe("Power symbol name (e.g., 'GND', '+3V3', '+5V', 'VCC', 'VDD')"),
      position: z.object({ x: z.number(), y: z.number() }).optional().describe("Position on schematic"),
      orientation: z.number().optional().describe("Rotation angle (0, 90, 180, 270)"),
    },
    async (args) => {
      const result = await callKicadScript("add_power_symbol", {
        schematicPath: args.schematicPath,
        symbol: args.symbol,
        position: args.position,
        orientation: args.orientation ?? 0,
      });
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Batch connect multiple pins to named nets
  server.tool(
    "batch_connect_to_net",
    "Connect multiple component pins to named nets in a single call. Much more efficient than calling connect_to_net repeatedly.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      connections: z.array(z.object({
        componentRef: z.string().describe("Component reference (e.g., 'R1', 'U1')"),
        pinName: z.string().describe("Pin name/number"),
        netName: z.string().describe("Net name to connect to"),
        labelType: z.enum(["label", "global_label"]).optional().describe("Label type (default: label)"),
        shape: z.string().optional().describe("For global_label: input, output, bidirectional, passive"),
      })).describe("Array of connections to make"),
    },
    async (args) => {
      const result = await callKicadScript("batch_connect_to_net", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Bulk move multiple schematic components
  server.tool(
    "bulk_move_schematic_components",
    "Move multiple schematic components to new positions in a single call. Moves fields (Reference, Value) along with each component.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      moves: z.record(z.string(), z.object({
        x: z.number(),
        y: z.number(),
      })).describe("Map of reference designator to new position, e.g., {'R1': {x: 100, y: 50}}"),
    },
    async (args) => {
      const result = await callKicadScript("bulk_move_schematic_components", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Batch get pin locations for multiple components
  server.tool(
    "batch_get_schematic_pin_locations",
    "Get pin endpoint coordinates for multiple components in one call. Much faster than calling get_schematic_pin_locations repeatedly — reads the schematic once.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      references: z.array(z.string()).describe("Array of component references (e.g., ['R1', 'U1', 'C1'])"),
    },
    async (args) => {
      const result = await callKicadScript("batch_get_schematic_pin_locations", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Move everything within a rectangular bounding box by an offset
  server.tool(
    "move_region",
    "Move everything (components, wires, labels) within a rectangular bounding box by an x,y offset. WARNING: Uses regex-based coordinate replacement which can match items outside the specified region in some cases. Verify results with get_schematic_view after use. Prefer move_connected for individual components.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      bbox: z.object({
        x1: z.number().describe("Left x coordinate"),
        y1: z.number().describe("Top y coordinate"),
        x2: z.number().describe("Right x coordinate"),
        y2: z.number().describe("Bottom y coordinate"),
      }).describe("Bounding box defining the region to move"),
      offset: z.object({
        dx: z.number().describe("X offset to move by"),
        dy: z.number().describe("Y offset to move by"),
      }).describe("How far to move the region"),
    },
    async (args) => {
      const result = await callKicadScript("move_region", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Add multiple wires in a single call
  server.tool(
    "batch_add_wire",
    "Add multiple wires in a single call. Each wire is defined by start and end points.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      wires: z.array(z.object({
        start: z.object({ x: z.number(), y: z.number() }),
        end: z.object({ x: z.number(), y: z.number() }),
      })).describe("Array of wires to add"),
    },
    async (args) => {
      const result = await callKicadScript("batch_add_wire", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Get all items connected to a component's pins
  server.tool(
    "get_connected_items",
    "Given a component reference, return all wires and labels connected to its pins. Essential for understanding what moves together.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      reference: z.string().describe("Component reference (e.g., 'U1', 'R1')"),
    },
    async (args) => {
      const result = await callKicadScript("get_connected_items", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Delete multiple wires and/or labels in a single call
  server.tool(
    "batch_delete",
    "Delete multiple wires and/or labels in a single call.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      wires: z.array(z.object({
        start: z.object({ x: z.number(), y: z.number() }),
        end: z.object({ x: z.number(), y: z.number() }),
      })).optional().describe("Array of wires to delete (matched by start/end coordinates)"),
      labels: z.array(z.object({
        netName: z.string(),
        position: z.object({ x: z.number(), y: z.number() }).optional(),
      })).optional().describe("Array of labels to delete (matched by name and optionally position)"),
    },
    async (args) => {
      const result = await callKicadScript("batch_delete", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Move a set of labels by an offset
  server.tool(
    "move_labels_by_offset",
    "Move a set of labels by an x,y offset. Useful after moving components to keep labels aligned.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      labels: z.array(z.object({
        netName: z.string().describe("Label text/net name"),
        position: z.object({ x: z.number(), y: z.number() }).describe("Current position of the label"),
      })).describe("Labels to move (identified by name + current position)"),
      offset: z.object({
        dx: z.number(),
        dy: z.number(),
      }).describe("How far to move each label"),
    },
    async (args) => {
      const result = await callKicadScript("move_labels_by_offset", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Find orphan/dangling items in schematic
  server.tool(
    "find_orphan_items",
    "Find dangling wires (endpoint not on pin/label/junction), orphan labels (not on wire/pin), and unconnected component pins. The #1 diagnostic tool.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
    },
    async (args) => {
      const result = await callKicadScript("find_orphan_items", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Check for overlapping components and text
  server.tool(
    "check_schematic_overlaps",
    "Detect visual overlaps in the schematic: component-on-component, label-on-component, wire-through-label, and label-on-label. Returns structured results with bounding boxes and severity.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      clearance: z.number().optional().describe("Minimum clearance in mm for component-component checks (default: 2.0)"),
      checkTypes: z.array(z.enum(["component_component", "label_component", "wire_label", "label_label"])).optional().describe("Which overlap types to check (default: all four)"),
      suppressPinLabels: z.boolean().optional().describe("Filter out label-component overlaps where the label's connection point is within 5.5mm of a pin endpoint of the overlapping component (default: true). These are standard pin-endpoint labels — their flags overlap the pin-stub area of the bounding box but that's normal KiCad practice."),
    },
    async (args) => {
      const result = await callKicadScript("check_schematic_overlaps", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Get structured layout data for a schematic region
  server.tool(
    "get_schematic_layout",
    "Return structured geometry for a region of the schematic. Returns components (with body rects, pin endpoints), labels (with bounding boxes, connection points, flag widths), wires (with lengths), junctions, no-connects, and pre-computed overlaps. Far more useful than get_schematic_view for programmatic analysis — gives exact coordinates instead of an image.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      region: z.object({
        x: z.number().describe("Left edge X coordinate (mm)"),
        y: z.number().describe("Top edge Y coordinate (mm)"),
        width: z.number().describe("Region width (mm)"),
        height: z.number().describe("Region height (mm)"),
      }).optional().describe("Region to query. Omit for full schematic."),
      suppressPinLabels: z.boolean().optional().describe("Suppress standard pin-stub overlaps in the overlaps array (default: true)"),
    },
    async (args) => {
      const result = await callKicadScript("get_schematic_layout", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Get per-pin connection status for a component
  server.tool(
    "get_pin_connections",
    "For a given component, show each pin and what it's connected to (net name, wire, or unconnected). Essential for verifying wiring.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      reference: z.string().describe("Component reference (e.g., 'U1', 'R1')"),
    },
    async (args) => {
      const result = await callKicadScript("get_pin_connections", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Batch edit multiple components with the same changes
  server.tool(
    "batch_edit_schematic_components",
    "Apply the same property edits to multiple components. Useful for bulk operations like hiding Reference on all power symbols.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      references: z.array(z.string()).describe("Array of component references to edit"),
      edits: z.object({
        footprint: z.string().optional(),
        value: z.string().optional(),
        hiddenFields: z.record(z.boolean()).optional().describe("Field visibility: {\"Reference\": true} hides Reference"),
      }).describe("Edits to apply to all listed components"),
    },
    async (args) => {
      const result = await callKicadScript("batch_edit_schematic_components", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Batch delete multiple components
  server.tool(
    "batch_delete_schematic_components",
    "Delete multiple schematic components in a single call.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      references: z.array(z.string()).describe("Array of component references to delete"),
    },
    async (args) => {
      const result = await callKicadScript("batch_delete_schematic_components", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Add no-connect flag (X) on unused pins
  server.tool(
    "add_no_connect",
    "Add a no-connect (X) flag at a position, typically on an unused pin endpoint to suppress ERC warnings.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      position: z.object({ x: z.number(), y: z.number() }).describe("Position for the no-connect flag (should be at a pin endpoint)"),
    },
    async (args) => {
      const result = await callKicadScript("add_no_connect", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Add text annotation to schematic
  server.tool(
    "add_schematic_text",
    "Add a text annotation to the schematic for section labels, notes, or documentation.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      text: z.string().describe("Text content"),
      position: z.object({ x: z.number(), y: z.number() }).describe("Position for the text"),
      size: z.number().optional().describe("Font size in mm (default: 2.54)"),
      angle: z.number().optional().describe("Rotation angle (default: 0)"),
    },
    async (args) => {
      const result = await callKicadScript("add_schematic_text", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Rotate a net label
  server.tool(
    "rotate_schematic_label",
    "Rotate a net label or global label to a new angle. Angle meanings: 0° = connection on right, flag extends left. 180° = connection on left, flag extends right. 90° = connection on bottom, flag extends up. 270° = connection on top, flag extends down.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      netName: z.string().describe("Label text/net name"),
      angle: z.number().describe("New rotation angle (0, 90, 180, 270)"),
      position: z.object({ x: z.number(), y: z.number() }).optional().describe("Label position to disambiguate if multiple labels share the same name"),
    },
    async (args) => {
      const result = await callKicadScript("rotate_schematic_label", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Add junction dot (T-connections)
  server.tool(
    "add_junction",
    "Add a junction dot at a wire T-intersection. Required when wires meet at T-junctions — without junctions, KiCad won't recognize the electrical connection (causes ERC 'pin not connected' errors).",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      position: z.object({ x: z.number(), y: z.number() }).describe("Position for the junction (must be at a wire intersection)"),
      diameter: z.number().optional().describe("Junction dot diameter in mm (default: 0 = auto)"),
    },
    async (args) => {
      const result = await callKicadScript("add_junction", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Batch add junctions
  server.tool(
    "batch_add_junction",
    "Add multiple junction dots in one call. Efficient for fixing many T-junction ERC errors at once.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      positions: z.array(z.object({ x: z.number(), y: z.number() })).describe("Array of positions for junction dots"),
    },
    async (args) => {
      const result = await callKicadScript("batch_add_junction", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Batch rotate labels
  server.tool(
    "batch_rotate_labels",
    "Rotate multiple net labels in one call. Each rotation specifies netName, angle, and optional position for disambiguation.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      rotations: z.array(z.object({
        netName: z.string().describe("Label text/net name"),
        angle: z.number().describe("New rotation angle (0, 90, 180, 270)"),
        position: z.object({ x: z.number(), y: z.number() }).optional().describe("Position to disambiguate if multiple labels share the same name"),
      })).describe("Array of label rotations"),
    },
    async (args) => {
      const result = await callKicadScript("batch_rotate_labels", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Get net connectivity — everything connected to a named net
  server.tool(
    "get_net_connectivity",
    "Get everything connected to a named net: component pins, labels, power symbols, and wire segments. Single call replaces cross-referencing list_schematic_wires + list_schematic_labels + get_schematic_pin_locations + run_erc.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      netName: z.string().describe("Net name to trace (e.g., '+5V', 'SDA', 'GND')"),
    },
    async (args) => {
      const result = await callKicadScript("get_net_connectivity", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Validate wire connections — targeted pin connectivity check
  server.tool(
    "validate_wire_connections",
    "Check if specific pins are electrically connected to expected nets. Targeted alternative to full ERC — checks only the pins you specify. Traces wires from each pin to find connected labels/power symbols.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      checks: z.array(z.object({
        reference: z.string().describe("Component reference (e.g., 'U1')"),
        pin: z.string().describe("Pin name (e.g., 'VDD', '1')"),
        expectedNet: z.string().optional().describe("Expected net name — if provided, result includes match: true/false"),
      })).describe("Array of pin connectivity checks"),
    },
    async (args) => {
      const result = await callKicadScript("validate_wire_connections", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // Trace all electrically connected elements from a coordinate
  server.tool(
    "trace_from_point",
    "Trace all electrically connected elements (wires, pins, labels, junctions, power symbols) reachable from a given coordinate. Use this to debug connectivity issues — shows exact path taken and any dead ends where connectivity breaks.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      x: z.number().describe("X coordinate to trace from (in mm)"),
      y: z.number().describe("Y coordinate to trace from (in mm)"),
      tolerance: z.number().optional().describe("Coordinate matching tolerance in mm (default: 0.05)"),
    },
    async (params) => {
      const result = await callKicadScript("trace_from_point", params);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
        isError: !result.success,
      };
    }
  );

  // Split a wire at a given point into two segments
  server.tool(
    "split_wire_at_point",
    "Split a wire segment at a given point, creating two wire segments that meet at that point. Converts implicit T-junctions into explicit shared endpoints for reliable connectivity. Optionally adds a junction dot at the split point.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      x: z.number().describe("X coordinate of split point (in mm)"),
      y: z.number().describe("Y coordinate of split point (in mm)"),
      addJunction: z.boolean().optional().describe("Whether to add a junction dot at split point (default: true)"),
      tolerance: z.number().optional().describe("Coordinate matching tolerance in mm (default: 0.05)"),
    },
    async (params) => {
      const result = await callKicadScript("split_wire_at_point", params);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
        isError: !result.success,
      };
    }
  );

  // Move a component and everything connected to its pins
  server.tool(
    "move_connected",
    "Move a component by an offset and drag all directly connected items (wire endpoints, labels, junctions) with it. Wire far-ends stay anchored, stretching the wires. Use this instead of move_schematic_component when you want to preserve connectivity.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      reference: z.string().describe("Component reference (e.g., 'U1', 'R1')"),
      offset: z.object({
        x: z.number().describe("Horizontal offset in mm"),
        y: z.number().describe("Vertical offset in mm"),
      }).describe("How far to move (dx, dy) in mm"),
    },
    async (args) => {
      const result = await callKicadScript("move_connected", args);
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    }
  );

  // ── Net analysis tools ──

  // Get all pin-to-net mappings for a component
  server.tool(
    "get_component_nets",
    "Return the net name for every pin of a component. The #1 tool for understanding what a component is connected to — replaces dozens of trace_from_point calls. Returns {pin_num: {net, name, x, y}} for all pins.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Component reference (e.g., 'U1', 'R1')"),
    },
    async (params) => {
      const result = await callKicadScript("get_component_nets", params);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
        isError: !result.success,
      };
    }
  );

  // Get all components/pins on a named net
  server.tool(
    "get_net_components",
    "Return all component pins connected to a named net. Inverse of get_component_nets — given a net name like 'VCC' or 'SDA', returns every component reference and pin number on that net.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      netName: z.string().describe("Net name to query (e.g., 'VCC', 'SDA', 'Net-(R1-Pad1)')"),
    },
    async (params) => {
      const result = await callKicadScript("get_net_components", params);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
        isError: !result.success,
      };
    }
  );

  // Get the net name for a single pin
  server.tool(
    "get_pin_net_name",
    "Return just the net name string for a single component pin. Simplest possible net query — e.g., get_pin_net_name(ref='U1', pin='14') returns '+3V3'.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Component reference (e.g., 'U1')"),
      pin: z.string().describe("Pin number (e.g., '1', '14')"),
    },
    async (params) => {
      const result = await callKicadScript("get_pin_net_name", params);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
        isError: !result.success,
      };
    }
  );

  // Export complete netlist as simple text
  server.tool(
    "export_netlist_summary",
    "Dump the complete netlist in a simple text format: every component with its pin-to-net assignments, every net with its connected pins, and all unconnected pins. Single call replaces 50+ individual trace calls for full schematic audit.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (params) => {
      const result = await callKicadScript("export_netlist_summary", params);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
        isError: !result.success,
      };
    }
  );

  // Validate component connections against expected pin-net mapping
  server.tool(
    "validate_component_connections",
    "Verify a component's actual pin-to-net connections against expected values. Pass a map of pin->expected_net. Prefix with '!' to assert NOT on that net (e.g., '!+5V'). Use null or 'unconnected' to assert no connection. Returns per-pin pass/fail with actual vs expected.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Component reference (e.g., 'U1')"),
      expected: z.record(z.string(), z.string().nullable()).describe(
        "Map of pin_number -> expected_net_name. Prefix '!' to negate (e.g., '!+5V' = must NOT be +5V). Use null or 'unconnected' for no connection."
      ),
    },
    async (params) => {
      const result = await callKicadScript("validate_component_connections", params);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
        isError: !result.success,
      };
    }
  );

  // Detect accidentally shorted nets
  server.tool(
    "find_shorted_nets",
    "Detect when two or more named nets are accidentally merged — e.g., +5V and an output signal sharing the same wire. Returns each group of shorted net names with the labels and power symbols involved.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
    },
    async (params) => {
      const result = await callKicadScript("find_shorted_nets", params);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
        isError: !result.success,
      };
    }
  );

  // Find nets with only one pin (likely broken connection)
  server.tool(
    "find_single_pin_nets",
    "Find nets with only one component pin connected — usually indicates a broken connection where one side of a wire was deleted or a component was moved off-grid.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      excludeNoConnect: z.boolean().optional().describe("Exclude nets where the pin has a no-connect flag (default: true)"),
    },
    async (params) => {
      const result = await callKicadScript("find_single_pin_nets", params);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
        isError: !result.success,
      };
    }
  );

  // Auto-fix connectivity issues using kicad-cli ERC as ground truth
  server.tool(
    "fix_connectivity",
    "Run kicad-cli ERC, parse the violations, and auto-fix what it can (mainly T-junctions that need junction dots). Returns what was fixed and what remains. Use dryRun=true to preview without changes. This is the ground truth — it uses kicad-cli's own connectivity engine, not MCP's.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      dryRun: z.boolean().optional().describe("If true, report what would be fixed without changing the file (default: false)"),
    },
    async (params) => {
      const result = await callKicadScript("fix_connectivity", params);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
        isError: !result.success,
      };
    }
  );
}
