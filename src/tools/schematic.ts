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
    },
    async (args: { name: string; path?: string }) => {
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
    },
    async (args: {
      schematicPath: string;
      symbol: string;
      reference: string;
      value?: string;
      footprint?: string;
      position?: { x: number; y: number };
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
    },
    async (args: {
      schematicPath: string;
      reference: string;
      footprint?: string;
      value?: string;
      newReference?: string;
      fieldPositions?: Record<string, { x: number; y: number; angle?: number }>;
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
      const result = await callKicadScript("add_wire", args);
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
    "Add a net label to the schematic",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      netName: z
        .string()
        .describe("Name of the net (e.g., VCC, GND, SIGNAL_1)"),
      position: z
        .array(z.number())
        .length(2)
        .describe("Position [x, y] for the label"),
    },
    async (args: {
      schematicPath: string;
      netName: string;
      position: number[];
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
    "Connect a component pin to a named net",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      componentRef: z.string().describe("Component reference (e.g., U1, R1)"),
      pinName: z.string().describe("Pin name/number to connect"),
      netName: z.string().describe("Name of the net to connect to"),
    },
    async (args: {
      schematicPath: string;
      componentRef: string;
      pinName: string;
      netName: string;
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

  // Get wire connections
  server.tool(
    "get_wire_connections",
    "Find all component pins reachable from a schematic point via connected wires, net labels, and power symbols. The query point must be at a wire endpoint or junction — midpoints of wire segments are not matched. Use get_schematic_pin_locations or list_schematic_wires to obtain exact endpoint coordinates first.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      x: z.number().describe("X coordinate of a wire endpoint or junction"),
      y: z.number().describe("Y coordinate of a wire endpoint or junction"),
    },
    async (args: { schematicPath: string; x: number; y: number }) => {
      const result = await callKicadScript("get_wire_connections", args);
      if (result.success && result.pins) {
        const pinList = result.pins
          .map((p: any) => `  - ${p.component}/${p.pin}`)
          .join("\n");
        const wireList = (result.wires ?? [])
          .map((w: any) => `  - (${w.start.x},${w.start.y}) → (${w.end.x},${w.end.y})`)
          .join("\n");
        return {
          content: [
            {
              type: "text",
              text: `Pins connected at (${args.x},${args.y}):\n${pinList || "  (none found)"}\n\nWire segments:\n${wireList || "  (none)"}`,
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Failed to get wire connections: ${result.message || "Unknown error"}`,
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
    "Move a placed symbol to a new position in the schematic.",
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
    },
    async (args: {
      schematicPath: string;
      format?: "png" | "svg";
      width?: number;
      height?: number;
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
    "Runs the KiCAD Electrical Rules Check (ERC) on a schematic and returns all violations. Use after wiring to verify the schematic before generating a netlist.",
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

  // ============================================================
  // Schematic Analysis Tools (read-only)
  // ============================================================

  // Get a zoomed view of a schematic region
  server.tool(
    "get_schematic_view_region",
    "Export a cropped region of the schematic as an image (PNG or SVG). Specify bounding box coordinates in schematic mm. Useful for zooming into a specific area to inspect wiring or layout.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch schematic file"),
      x1: z.number().describe("Left X coordinate of the region in mm"),
      y1: z.number().describe("Top Y coordinate of the region in mm"),
      x2: z.number().describe("Right X coordinate of the region in mm"),
      y2: z.number().describe("Bottom Y coordinate of the region in mm"),
      format: z.enum(["png", "svg"]).optional().describe("Output image format (default: png)"),
      width: z.number().optional().describe("Output image width in pixels (default: 800)"),
      height: z.number().optional().describe("Output image height in pixels (default: 600)"),
    },
    async (args: {
      schematicPath: string;
      x1: number; y1: number; x2: number; y2: number;
      format?: string; width?: number; height?: number;
    }) => {
      const result = await callKicadScript("get_schematic_view_region", args);
      if (result.success && result.imageData) {
        if (result.format === "svg") {
          return { content: [{ type: "text", text: result.imageData }] };
        }
        return {
          content: [{
            type: "image",
            data: result.imageData,
            mimeType: "image/png",
          }],
        };
      }
      return {
        content: [{ type: "text", text: `Failed: ${result.message || "Unknown error"}` }],
      };
    },
  );


  // Find overlapping elements
  server.tool(
    "find_overlapping_elements",
    "Detect spatially overlapping symbols, wires, and labels in the schematic. Finds duplicate power symbols at the same position, collinear overlapping wires, and labels stacked on top of each other.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch schematic file"),
      tolerance: z.number().optional().describe("Distance threshold in mm for label proximity and wire collinearity checks. Symbol overlap uses bounding-box intersection. (default: 0.5)"),
    },
    async (args: { schematicPath: string; tolerance?: number }) => {
      const result = await callKicadScript("find_overlapping_elements", args);
      if (result.success) {
        const lines = [`Found ${result.totalOverlaps} overlap(s):`];
        const syms: any[] = result.overlappingSymbols || [];
        const lbls: any[] = result.overlappingLabels || [];
        const wires: any[] = result.overlappingWires || [];
        if (syms.length) {
          lines.push(`\nOverlapping symbols (${syms.length}):`);
          syms.slice(0, 20).forEach((o: any) => {
            lines.push(`  ${o.element1.reference} ↔ ${o.element2.reference} (${o.distance}mm) [${o.type}]`);
          });
        }
        if (lbls.length) {
          lines.push(`\nOverlapping labels (${lbls.length}):`);
          lbls.slice(0, 20).forEach((o: any) => {
            lines.push(`  "${o.element1.name}" ↔ "${o.element2.name}" (${o.distance}mm)`);
          });
        }
        if (wires.length) {
          lines.push(`\nOverlapping wires (${wires.length}):`);
          wires.slice(0, 20).forEach((o: any) => {
            lines.push(`  wire @ (${o.wire1.start.x},${o.wire1.start.y})→(${o.wire1.end.x},${o.wire1.end.y}) overlaps with another`);
          });
        }
        return { content: [{ type: "text", text: lines.join("\n") }] };
      }
      return {
        content: [{ type: "text", text: `Failed: ${result.message || "Unknown error"}` }],
      };
    },
  );

  // Get elements in a region
  server.tool(
    "get_elements_in_region",
    "List all symbols, wires, and labels within a rectangular region of the schematic. Useful for understanding what is in a specific area before modifying it.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch schematic file"),
      x1: z.number().describe("Left X coordinate of the region in mm"),
      y1: z.number().describe("Top Y coordinate of the region in mm"),
      x2: z.number().describe("Right X coordinate of the region in mm"),
      y2: z.number().describe("Bottom Y coordinate of the region in mm"),
    },
    async (args: {
      schematicPath: string;
      x1: number; y1: number; x2: number; y2: number;
    }) => {
      const result = await callKicadScript("get_elements_in_region", args);
      if (result.success) {
        const c = result.counts;
        const lines = [`Region (${args.x1},${args.y1})→(${args.x2},${args.y2}): ${c.symbols} symbols, ${c.wires} wires, ${c.labels} labels`];
        const syms: any[] = result.symbols || [];
        if (syms.length) {
          lines.push("\nSymbols:");
          syms.forEach((s: any) => {
            const pinCount = s.pins ? Object.keys(s.pins).length : 0;
            lines.push(`  ${s.reference} (${s.libId}) @ (${s.position.x}, ${s.position.y}) [${pinCount} pins]`);
          });
        }
        const wires: any[] = result.wires || [];
        if (wires.length) {
          lines.push(`\nWires (${wires.length}):`);
          wires.slice(0, 30).forEach((w: any) => {
            lines.push(`  (${w.start.x},${w.start.y}) → (${w.end.x},${w.end.y})`);
          });
          if (wires.length > 30) lines.push(`  ... and ${wires.length - 30} more`);
        }
        const labels: any[] = result.labels || [];
        if (labels.length) {
          lines.push(`\nLabels (${labels.length}):`);
          labels.forEach((l: any) => {
            lines.push(`  "${l.name}" [${l.type}] @ (${l.position.x}, ${l.position.y})`);
          });
        }
        return { content: [{ type: "text", text: lines.join("\n") }] };
      }
      return {
        content: [{ type: "text", text: `Failed: ${result.message || "Unknown error"}` }],
      };
    },
  );

  // Find wires crossing symbols
  server.tool(
    "find_wires_crossing_symbols",
    "Find all wires that cross over component symbol bodies. Wires passing over symbols are unacceptable in schematics — they indicate routing mistakes where a wire was drawn across a component instead of around it.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch schematic file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("find_wires_crossing_symbols", args);
      if (result.success) {
        const collisions: any[] = result.collisions || [];
        const lines = [`Found ${collisions.length} wire(s) crossing symbols:`];
        collisions.slice(0, 30).forEach((c: any, i: number) => {
          lines.push(
            `  ${i + 1}. Wire (${c.wire.start.x},${c.wire.start.y})→(${c.wire.end.x},${c.wire.end.y}) crosses ${c.component.reference} (${c.component.libId})`
          );
        });
        if (collisions.length > 30) lines.push(`  ... and ${collisions.length - 30} more`);
        return { content: [{ type: "text", text: lines.join("\n") }] };
      }
      return {
        content: [{ type: "text", text: `Failed: ${result.message || "Unknown error"}` }],
      };
    },
  );
}
