/**
 * Schematic tools for KiCAD MCP server
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerSchematicTools(server: McpServer, callKicadScript: Function) {
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
        .describe("Symbol library:name reference (e.g., Device:R, EDA-MCP:ESP32-C3)"),
      reference: z.string().describe("Component reference (e.g., R1, U1)"),
      value: z.string().optional().describe("Component value"),
      footprint: z
        .string()
        .optional()
        .describe("KiCAD footprint (e.g. Resistor_SMD:R_0603_1608Metric)"),
      position: z
        .object({
          x: z.number(),
          y: z.number(),
        })
        .optional()
        .describe("Position on schematic"),
      unit: z
        .number()
        .int()
        .min(1)
        .optional()
        .describe("Unit number for multi-unit symbols (1=A, 2=B, 3=C, …). Defaults to 1."),
    },
    async (args: {
      schematicPath: string;
      symbol: string;
      reference: string;
      value?: string;
      footprint?: string;
      position?: { x: number; y: number };
      unit?: number;
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
          unit: args.unit ?? 1,
        },
      };

      const result = await callKicadScript("add_schematic_component", transformed);
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

  // Edit component properties in schematic (footprint, value, reference, custom fields)
  server.tool(
    "edit_schematic_component",
    `Update properties of a placed symbol in a KiCAD schematic (.kicad_sch) in-place.

Use this tool to:
  • assign or update the footprint, value, or reference designator,
  • reposition field labels (Reference / Value text),
  • add, update, or remove ARBITRARY CUSTOM PROPERTIES used by BOM and sourcing
    workflows: MPN, Manufacturer, Manufacturer_PN, Distributor, DigiKey, DigiKey_PN,
    Mouser_PN, LCSC, JLCPCB_PN, Voltage, Tolerance, Power, Dielectric, etc.

Custom properties are first-class — they survive ERC, are exported by export_bom,
and are picked up by the JLCPCB / Digi-Key BOM tooling. Newly-added properties
default to hidden so they do not clutter the schematic canvas.

Multiple updates can be batched in a single call: pass any combination of
\`footprint\`, \`value\`, \`newReference\`, \`fieldPositions\`, \`properties\`,
and \`removeProperties\` together.

This is more efficient than delete + re-add because it preserves the component's
position and UUID. Operates on .kicad_sch files only — to modify a PCB footprint
use edit_component instead.`,
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Current reference designator of the component (e.g. R1, U3)"),
      footprint: z
        .string()
        .optional()
        .describe("New KiCAD footprint string (e.g. Resistor_SMD:R_0603_1608Metric)"),
      value: z.string().optional().describe("New value string (e.g. 10k, 100nF)"),
      newReference: z
        .string()
        .optional()
        .describe("Rename the reference designator (e.g. R1 → R10)"),
      fieldPositions: z
        .record(
          z.object({
            x: z.number(),
            y: z.number(),
            angle: z.number().optional().default(0),
          }),
        )
        .optional()
        .describe(
          'Reposition field labels: map of field name to {x, y, angle} (e.g. {"Reference": {"x": 12.5, "y": 17.0}})',
        ),
      properties: z
        .record(
          z.union([
            z.string(),
            z.object({
              value: z.string().describe("Property value to write"),
              x: z.number().optional().describe("Label X position in mm (default: component X)"),
              y: z.number().optional().describe("Label Y position in mm (default: component Y)"),
              angle: z.number().optional().describe("Label rotation in degrees (default: 0)"),
              hide: z
                .boolean()
                .optional()
                .describe(
                  "Whether to hide the property text on the schematic. Defaults to true for newly-created custom properties (BOM/sourcing data is normally hidden).",
                ),
              fontSize: z
                .number()
                .optional()
                .describe("Font size in mm for the label (default: 1.27)"),
            }),
          ]),
        )
        .optional()
        .describe(
          "Add or update component properties. Map of property name to either a string value (sensible defaults) " +
            "or a full spec object {value, x?, y?, angle?, hide?, fontSize?}. Use this to attach BOM and sourcing " +
            "metadata such as MPN, Manufacturer, Distributor, DigiKey, LCSC, JLCPCB_PN, Voltage, Tolerance, " +
            "Dielectric, Power, etc. Built-in fields (Reference, Value, Footprint, Datasheet) can also be set " +
            "this way but the dedicated parameters above are clearer. Example: " +
            '{"MPN": "RC0603FR-0710KL", "Manufacturer": "Yageo", "Tolerance": "1%"}',
        ),
      removeProperties: z
        .array(z.string())
        .optional()
        .describe(
          "List of custom property names to delete from this component. The built-in fields " +
            "Reference, Value, Footprint, and Datasheet cannot be removed (clear them by setting " +
            'value to "" instead). Example: ["OldMPN", "Distributor_PN"]',
        ),
    },
    async (args: {
      schematicPath: string;
      reference: string;
      footprint?: string;
      value?: string;
      newReference?: string;
      fieldPositions?: Record<string, { x: number; y: number; angle?: number }>;
      properties?: Record<
        string,
        | string
        | {
            value: string;
            x?: number;
            y?: number;
            angle?: number;
            hide?: boolean;
            fontSize?: number;
          }
      >;
      removeProperties?: string[];
    }) => {
      const result = await callKicadScript("edit_schematic_component", args);
      if (result.success) {
        const updated = result.updated ?? {};
        const summaryParts: string[] = [];
        const simpleKeys = ["footprint", "value", "reference"] as const;
        for (const k of simpleKeys) {
          if (updated[k] !== undefined) summaryParts.push(`${k}=${updated[k]}`);
        }
        if (updated.fieldPositions)
          summaryParts.push(`fieldPositions=${Object.keys(updated.fieldPositions).join(",")}`);
        if (updated.propertiesAdded)
          summaryParts.push(`added=${Object.keys(updated.propertiesAdded).join(",")}`);
        if (updated.propertiesUpdated)
          summaryParts.push(`updated=${Object.keys(updated.propertiesUpdated).join(",")}`);
        if (updated.propertiesRemoved)
          summaryParts.push(`removed=${updated.propertiesRemoved.join(",")}`);
        return {
          content: [
            {
              type: "text" as const,
              text: `Successfully updated ${args.reference}: ${summaryParts.join("; ") || "(no-op)"}`,
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

  // ------------------------------------------------------------------
  // Single-property convenience tools (delegate to edit_schematic_component)
  // ------------------------------------------------------------------

  // Set a single custom property on a placed symbol
  server.tool(
    "set_schematic_component_property",
    `Add or update a single custom property on a placed schematic symbol.

This is a focused convenience wrapper around edit_schematic_component for the very
common case of attaching one BOM / sourcing field at a time. The property is
created if it does not already exist on the component.

Typical custom properties:
  • MPN, Manufacturer, Manufacturer_PN — manufacturer part number metadata
  • DigiKey, DigiKey_PN, Mouser_PN, LCSC, JLCPCB_PN — distributor part numbers
  • Voltage, Tolerance, Power, Dielectric, Temperature_Coefficient — passive parameters
  • Description, Notes — free-form documentation
  • Any custom field your BOM exporter expects.

These properties are written into the .kicad_sch file as standard KiCad property
records, are exported by export_bom, and are picked up by the JLCPCB and Digi-Key
sourcing tools. Newly-created properties default to hidden — set hide=false to
display the value on the schematic canvas.

For batch updates of multiple properties at once, use edit_schematic_component
with the \`properties\` parameter instead.`,
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Reference designator of the component (e.g. R1, U3)"),
      name: z
        .string()
        .describe(
          "Property name (e.g. 'MPN', 'Manufacturer', 'DigiKey_PN', 'Voltage', 'Dielectric')",
        ),
      value: z.string().describe("Property value to write (use empty string to clear)"),
      x: z.number().optional().describe("Label X position in mm (default: component X)"),
      y: z.number().optional().describe("Label Y position in mm (default: component Y)"),
      angle: z.number().optional().describe("Label rotation in degrees (default: 0)"),
      hide: z
        .boolean()
        .optional()
        .describe(
          "Hide the property text on the schematic canvas. Defaults to true for newly-created custom properties.",
        ),
      fontSize: z.number().optional().describe("Font size in mm for the label (default: 1.27)"),
    },
    async (args: {
      schematicPath: string;
      reference: string;
      name: string;
      value: string;
      x?: number;
      y?: number;
      angle?: number;
      hide?: boolean;
      fontSize?: number;
    }) => {
      const result = await callKicadScript("set_schematic_component_property", args);
      if (result.success) {
        const updated = result.updated ?? {};
        const action = updated.propertiesAdded?.[args.name] !== undefined ? "added" : "updated";
        return {
          content: [
            {
              type: "text" as const,
              text: `Successfully ${action} property ${args.name}="${args.value}" on ${args.reference}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text" as const,
            text: `Failed to set property '${args.name}' on ${args.reference}: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // Remove a single custom property from a placed symbol
  server.tool(
    "remove_schematic_component_property",
    `Remove a single custom property from a placed schematic symbol.

Built-in fields (Reference, Value, Footprint, Datasheet) cannot be removed —
KiCad requires them on every symbol. To clear a built-in field, use
edit_schematic_component and set its value to an empty string.`,
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Reference designator of the component (e.g. R1, U3)"),
      name: z
        .string()
        .describe("Custom property name to remove (e.g. 'MPN', 'Distributor_PN', 'OldField')"),
    },
    async (args: { schematicPath: string; reference: string; name: string }) => {
      const result = await callKicadScript("remove_schematic_component_property", args);
      if (result.success) {
        const removed = result.updated?.propertiesRemoved ?? [];
        if (removed.includes(args.name)) {
          return {
            content: [
              {
                type: "text" as const,
                text: `Successfully removed property '${args.name}' from ${args.reference}`,
              },
            ],
          };
        }
        return {
          content: [
            {
              type: "text" as const,
              text: `Property '${args.name}' was not present on ${args.reference} (no change made)`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text" as const,
            text: `Failed to remove property '${args.name}' from ${args.reference}: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // Get component properties and field positions from schematic
  server.tool(
    "get_schematic_component",
    "Get full component info from a schematic: position, every field's value, and each field's " +
      "label position (at x/y/angle). Returns ALL properties — both built-in fields " +
      "(Reference, Value, Footprint, Datasheet) and any custom BOM/sourcing properties present " +
      "on the symbol (MPN, Manufacturer, DigiKey_PN, LCSC, Voltage, Tolerance, Dielectric, etc.). " +
      "Use this before edit_schematic_component / set_schematic_component_property to inspect " +
      "what is currently set, or to plan a label repositioning.",
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
            `  ${name}: "${f.value}" @ (${f.x}, ${f.y}, angle=${f.angle}°)`,
        );
        return {
          content: [
            {
              type: "text",
              text: `Component ${result.reference} at ${pos}\nFields:\n${fieldLines.join("\n")}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to get component: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // Draw wire between coordinate waypoints with optional pin snapping
  server.tool(
    "add_schematic_wire",
    "Draws a wire on the schematic between two or more coordinate points. Always call get_schematic_pin_locations first to get the approximate pin coordinates, then pass them as the first and last waypoints. snapToPins (on by default) will correct any float imprecision by snapping endpoints to the exact nearest pin coordinate. To route around components, add intermediate waypoints between the start and end: e.g. [[x1,y1], [xMid,y1], [xMid,y2], [x2,y2]] routes horizontally then vertically. Intermediate waypoints are never snapped.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      waypoints: z
        .array(z.array(z.number()).length(2))
        .min(2)
        .describe("Ordered list of [x, y] coordinates. Minimum 2 points."),
      snapToPins: z
        .boolean()
        .optional()
        .describe("Snap the first and last waypoints to the nearest pin (default: true)"),
      snapTolerance: z.number().optional().describe("Maximum snap distance in mm (default: 1.0)"),
    },
    async (args: {
      schematicPath: string;
      waypoints: number[][];
      snapToPins?: boolean;
      snapTolerance?: number;
    }) => {
      const result = await callKicadScript("add_schematic_wire", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text" as const,
              text: result.message || "Wire added successfully",
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text" as const,
              text: `Failed to add wire: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // Add net label
  server.tool(
    "add_schematic_net_label",
    "Add a net label to the schematic. " +
      "PREFERRED: supply componentRef + pinNumber to snap the label to the exact pin endpoint — " +
      "this guarantees an electrical connection. " +
      "Alternatively supply position [x, y], but the coordinates must match the pin endpoint exactly " +
      "(even a 0.01 mm offset breaks the connection). " +
      "The response includes actual_position (coordinates actually used) and snapped_to_pin " +
      "(present when a pin reference was resolved).",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      netName: z.string().describe("Name of the net (e.g., VCC, GND, SIGNAL_1)"),
      position: z
        .array(z.number())
        .length(2)
        .optional()
        .describe(
          "Position [x, y] for the label. Required when componentRef/pinNumber are not given.",
        ),
      componentRef: z
        .string()
        .optional()
        .describe("Component reference to snap label to (e.g. U1, R1). Use with pinNumber."),
      pinNumber: z
        .union([z.string(), z.number()])
        .optional()
        .describe(
          "Pin number or name on componentRef to snap label to (e.g. '1', 'GND'). Use with componentRef.",
        ),
      labelType: z
        .enum(["label", "global_label", "hierarchical_label"])
        .optional()
        .describe("Label type (default: label)"),
      orientation: z.number().optional().describe("Rotation angle 0/90/180/270 (default: 0)"),
    },
    async (args: {
      schematicPath: string;
      netName: string;
      position?: number[];
      componentRef?: string;
      pinNumber?: string | number;
      labelType?: string;
      orientation?: number;
    }) => {
      const result = await callKicadScript("add_schematic_net_label", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(result, null, 2),
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
    "Connect a component pin to a named net by adding a wire stub and net label at the exact pin endpoint. " +
      "The response includes pin_location (exact pin coords), label_location (where the label was placed), " +
      "and wire_stub (the wire segment added) so you can confirm the placement.",
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
              text: JSON.stringify(result, null, 2),
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
    "Returns the net name and all wires and component pins connected at a given point. " +
      "Accepts either a component reference + pin number (e.g. reference='U1', pin='3') " +
      "or a schematic coordinate (x, y in mm). " +
      "Returns net=null for unnamed (unlabelled) nets. " +
      "The query point must be at a wire endpoint or junction — midpoints are not matched. " +
      "Use get_schematic_pin_locations or list_schematic_wires to obtain exact endpoint coordinates.",
    {
      schematicPath: z.string().describe("Path to the schematic file"),
      reference: z
        .string()
        .optional()
        .describe("Component reference (e.g. U1, R1). Pair with pin."),
      pin: z
        .string()
        .optional()
        .describe("Pin number or name (e.g. '3', 'SDA'). Pair with reference."),
      x: z.number().optional().describe("X coordinate of a wire endpoint in mm. Pair with y."),
      y: z.number().optional().describe("Y coordinate of a wire endpoint in mm. Pair with x."),
    },
    async (args: {
      schematicPath: string;
      reference?: string;
      pin?: string;
      x?: number;
      y?: number;
    }) => {
      const result = await callKicadScript("get_wire_connections", args);
      if (result.success) {
        const netLabel = result.net ?? "(unnamed)";
        const pinList = (result.pins ?? [])
          .map((p: any) => `  - ${p.component}/${p.pin}`)
          .join("\n");
        const wireList = (result.wires ?? [])
          .map((w: any) => `  - (${w.start.x},${w.start.y}) → (${w.end.x},${w.end.y})`)
          .join("\n");
        const qp = result.query_point;
        return {
          content: [
            {
              type: "text",
              text:
                `Net: ${netLabel}\n` +
                `Query point: (${qp?.x ?? args.x}, ${qp?.y ?? args.y})\n` +
                `Connected pins:\n${pinList || "  (none found)"}\n\nWire segments:\n${wireList || "  (none)"}`,
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
            `  Pin ${pinNum} (${data.name || pinNum}): x=${data.x}, y=${data.y}, angle=${data.angle ?? 0}°`,
        );
        return {
          content: [
            {
              type: "text",
              text: `Pin locations for ${args.reference}:\n${lines.join("\n")}`,
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Failed to get pin locations: ${result.message || "Unknown error"}`,
            },
          ],
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
      netPrefix: z
        .string()
        .optional()
        .describe("Net name prefix, e.g. 'CSI' → CSI_1, CSI_2 (default: PIN)"),
      pinOffset: z
        .number()
        .optional()
        .describe("Add to pin number when building net name (default: 0)"),
    },
    async (args: {
      schematicPath: string;
      sourceRef: string;
      targetRef: string;
      netPrefix?: string;
      pinOffset?: number;
    }) => {
      const result = await callKicadScript("connect_passthrough", args);
      if (result.success !== false || (result.connected && result.connected.length > 0)) {
        const lines: string[] = [];
        if (result.connected?.length)
          lines.push(
            `Connected (${result.connected.length}): ${result.connected.slice(0, 5).join(", ")}${result.connected.length > 5 ? " ..." : ""}`,
          );
        if (result.failed?.length)
          lines.push(`Failed (${result.failed.length}): ${result.failed.join(", ")}`);
        return {
          content: [{ type: "text", text: result.message + "\n" + lines.join("\n") }],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Passthrough failed: ${result.message || "Unknown error"}`,
            },
          ],
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
          referencePrefix: z
            .string()
            .optional()
            .describe("Filter by reference prefix (e.g., 'R', 'C', 'U')"),
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
          const conns = (n.connections || []).map((c: any) => `${c.component}/${c.pin}`).join(", ");
          const pinCount =
            n.connected_pin_count !== undefined ? ` [${n.connected_pin_count} pin(s)]` : "";
          return `  ${n.name}${pinCount}: ${conns || "(no connections)"}`;
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
          (w: any) => `  (${w.start.x}, ${w.start.y}) → (${w.end.x}, ${w.end.y})`,
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
    "List all net labels, global labels, and power flags in the schematic. " +
      "Optionally filter by label name (netName) and/or label type (labelType).",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      netName: z
        .string()
        .optional()
        .describe(
          "Filter to labels whose name exactly matches this string (case-sensitive). Omit to return all labels.",
        ),
      labelType: z
        .enum(["net", "global", "power"])
        .optional()
        .describe(
          "Filter by label type. 'net' = local label, 'global' = global label, 'power' = power symbol. Omit to return all types.",
        ),
    },
    async (args: { schematicPath: string; netName?: string; labelType?: string }) => {
      const result = await callKicadScript("list_schematic_labels", args);
      if (result.success) {
        const labels = result.labels || [];
        if (labels.length === 0) {
          return {
            content: [{ type: "text", text: "No labels found in schematic." }],
          };
        }
        const lines = labels.map(
          (l: any) => `  [${l.type}] ${l.name} at (${l.position.x}, ${l.position.y})`,
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

  // Move a placed symbol, dragging connected wires
  server.tool(
    "move_schematic_component",
    "Move a placed symbol to a new position in the schematic. By default (preserveWires=true) wire endpoints touching the component's pins are stretched to follow the new position.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      reference: z.string().describe("Reference designator (e.g., R1, U1)"),
      position: z
        .object({ x: z.number(), y: z.number() })
        .describe("New position in schematic mm coordinates"),
      preserveWires: z
        .boolean()
        .optional()
        .describe("Stretch connected wire endpoints to follow the move (default true)"),
    },
    async (args: {
      schematicPath: string;
      reference: string;
      position: { x: number; y: number };
      preserveWires?: boolean;
    }) => {
      const result = await callKicadScript("move_schematic_component", args);
      if (result.success) {
        const moved = result.wiresMoved ?? 0;
        const removed = result.wiresRemoved ?? 0;
        return {
          content: [
            {
              type: "text",
              text:
                `Moved ${args.reference} from (${result.oldPosition.x}, ${result.oldPosition.y}) ` +
                `to (${result.newPosition.x}, ${result.newPosition.y})` +
                (moved > 0 ? `, ${moved} wire endpoint(s) updated` : "") +
                (removed > 0 ? `, ${removed} zero-length wire(s) removed` : ""),
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
      mirror: z.enum(["x", "y"]).optional().describe("Optional mirror axis"),
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
            content: [{ type: "text", text: "All components are already annotated." }],
          };
        }
        const lines = annotated.map((a: any) => `  ${a.oldReference} → ${a.newReference}`);
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
      start: z.object({ x: z.number(), y: z.number() }).describe("Wire start position"),
      end: z.object({ x: z.number(), y: z.number() }).describe("Wire end position"),
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

  // Move net label to a new position in the schematic
  server.tool(
    "move_schematic_net_label",
    "Move a net label (local, global, or hierarchical) to a new position in the schematic. Use currentPosition to disambiguate when multiple labels share the same name.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      netName: z.string().describe("Name of the net label to move"),
      newPosition: z.object({ x: z.number(), y: z.number() }).describe("Target position in mm"),
      currentPosition: z
        .object({ x: z.number(), y: z.number() })
        .optional()
        .describe("Current position to disambiguate when multiple labels share the same name"),
      labelType: z
        .enum(["label", "global_label", "hierarchical_label"])
        .optional()
        .describe("Restrict search to a specific label type"),
    },
    async (args: {
      schematicPath: string;
      netName: string;
      newPosition: { x: number; y: number };
      currentPosition?: { x: number; y: number };
      labelType?: "label" | "global_label" | "hierarchical_label";
    }) => {
      const result = await callKicadScript("move_schematic_net_label", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text",
              text: `Moved net label '${args.netName}' from (${result.oldPosition?.x}, ${result.oldPosition?.y}) to (${result.newPosition?.x}, ${result.newPosition?.y})`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `Failed to move label: ${result.message || "Unknown error"}`,
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
      blackAndWhite: z.boolean().optional().describe("Export in black and white"),
    },
    async (args: { schematicPath: string; outputPath: string; blackAndWhite?: boolean }) => {
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
      blackAndWhite: z.boolean().optional().describe("Export in black and white"),
    },
    async (args: { schematicPath: string; outputPath: string; blackAndWhite?: boolean }) => {
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
      format: z.enum(["png", "svg"]).optional().describe("Output format (default: png)"),
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
          lines.push(
            `  Errors: ${s.error ?? 0}  Warnings: ${s.warning ?? 0}  Info: ${s.info ?? 0}`,
          );
        }
        if (violations.length > 0) {
          lines.push("");
          violations.slice(0, 30).forEach((v: any, i: number) => {
            const loc =
              v.location && v.location.x !== undefined
                ? ` @ (${v.location.x}, ${v.location.y})`
                : "";
            lines.push(`${i + 1}. [${v.severity}] ${v.message}${loc}`);
          });
          if (violations.length > 30) {
            lines.push(`... and ${violations.length - 30} more`);
          }
        }
        return { content: [{ type: "text", text: lines.join("\n") }] };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `ERC failed: ${result.message || "Unknown error"}${result.errorDetails ? "\n" + result.errorDetails : ""}`,
            },
          ],
        };
      }
    },
  );

  // Generate netlist
  server.tool(
    "generate_netlist",
    "Return a structured JSON netlist from the schematic — component list (reference, value, footprint) and net list (net name with all connected component/pin pairs). Use this to inspect or verify connectivity within the conversation. Does not write any file. To export a netlist file in Spice, KiCad XML, Cadstar, or OrcadPCB2 format, use export_netlist instead.",
    {
      schematicPath: z.string().describe("Absolute path to the .kicad_sch schematic file"),
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
      x1: number;
      y1: number;
      x2: number;
      y2: number;
      format?: string;
      width?: number;
      height?: number;
    }) => {
      const result = await callKicadScript("get_schematic_view_region", args);
      if (result.success && result.imageData) {
        if (result.format === "svg") {
          return { content: [{ type: "text", text: result.imageData }] };
        }
        return {
          content: [
            {
              type: "image",
              data: result.imageData,
              mimeType: "image/png",
            },
          ],
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
      tolerance: z
        .number()
        .optional()
        .describe(
          "Distance threshold in mm for label proximity and wire collinearity checks. Symbol overlap uses bounding-box intersection. (default: 0.5)",
        ),
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
            lines.push(
              `  ${o.element1.reference} ↔ ${o.element2.reference} (${o.distance}mm) [${o.type}]`,
            );
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
            lines.push(
              `  wire @ (${o.wire1.start.x},${o.wire1.start.y})→(${o.wire1.end.x},${o.wire1.end.y}) overlaps with another`,
            );
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
    async (args: { schematicPath: string; x1: number; y1: number; x2: number; y2: number }) => {
      const result = await callKicadScript("get_elements_in_region", args);
      if (result.success) {
        const c = result.counts;
        const lines = [
          `Region (${args.x1},${args.y1})→(${args.x2},${args.y2}): ${c.symbols} symbols, ${c.wires} wires, ${c.labels} labels`,
        ];
        const syms: any[] = result.symbols || [];
        if (syms.length) {
          lines.push("\nSymbols:");
          syms.forEach((s: any) => {
            const pinCount = s.pins ? Object.keys(s.pins).length : 0;
            lines.push(
              `  ${s.reference} (${s.libId}) @ (${s.position.x}, ${s.position.y}) [${pinCount} pins]`,
            );
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
            `  ${i + 1}. Wire (${c.wire.start.x},${c.wire.start.y})→(${c.wire.end.x},${c.wire.end.y}) crosses ${c.component.reference} (${c.component.libId})`,
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

  // List floating net labels
  server.tool(
    "list_floating_labels",
    "Returns all net labels in the schematic that are not connected to any component pin. " +
      "A label is 'floating' when no component pin falls on the wire-network reachable from the " +
      "label's position. Floating labels indicate misplaced or off-grid labels that cause ERC errors. " +
      "Does not require the KiCAD UI to be running.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch schematic file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("list_floating_labels", args);
      if (result.success) {
        const labels: any[] = result.floating_labels || [];
        if (labels.length === 0) {
          return { content: [{ type: "text", text: "No floating labels found." }] };
        }
        const lines: string[] = [`Found ${labels.length} floating label(s):\n`];
        labels.slice(0, 50).forEach((lbl: any) => {
          lines.push(`  "${lbl.name}" (${lbl.type}) at (${lbl.x}, ${lbl.y})`);
        });
        if (labels.length > 50) {
          lines.push(`  ... and ${labels.length - 50} more`);
        }
        return { content: [{ type: "text", text: lines.join("\n") }] };
      }
      return {
        content: [{ type: "text", text: `Failed: ${result.message || "Unknown error"}` }],
      };
    },
  );

  // Find orphaned wires
  server.tool(
    "find_orphaned_wires",
    "Find wire segments with at least one dangling endpoint — not connected to a component pin, " +
      "net label, or another wire. Orphaned wires cause ERC 'wire end unconnected' errors. " +
      "Does not require the KiCad UI to be running.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch schematic file"),
    },
    async (args: { schematicPath: string }) => {
      const result = await callKicadScript("find_orphaned_wires", args);
      if (result.success) {
        const wires: any[] = result.orphaned_wires || [];
        if (wires.length === 0) {
          return { content: [{ type: "text", text: "No orphaned wires found." }] };
        }
        const lines: string[] = [`Found ${wires.length} orphaned wire(s):\n`];
        wires.slice(0, 50).forEach((w: any) => {
          const dangling = w.dangling_ends.map((e: any) => `(${e.x}, ${e.y})`).join(", ");
          lines.push(
            `  wire (${w.start.x}, ${w.start.y})→(${w.end.x}, ${w.end.y})  dangling end(s): ${dangling}`,
          );
        });
        if (wires.length > 50) lines.push(`  ... and ${wires.length - 50} more`);
        return { content: [{ type: "text", text: lines.join("\n") }] };
      }
      return {
        content: [{ type: "text", text: `Failed: ${result.message || "Unknown error"}` }],
      };
    },
  );

  // Snap schematic elements to grid
  server.tool(
    "snap_to_grid",
    "Snap schematic element coordinates to the nearest grid point. " +
      "KiCAD uses exact integer matching for connectivity, so off-grid coordinates cause wires " +
      "that look connected to fail ERC checks. " +
      "Modifies the .kicad_sch file in place. Does not require the KiCAD UI to be running.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch schematic file"),
      gridSize: z
        .number()
        .optional()
        .describe("Grid spacing in mm (default: 2.54 — standard KiCAD schematic grid)"),
      elements: z
        .array(z.enum(["wires", "junctions", "labels", "components"]))
        .optional()
        .describe(
          'Element types to snap (default: ["wires", "junctions", "labels"]). ' +
            '"components" is opt-in — moving a component without re-routing wires creates new mismatches.',
        ),
    },
    async (args: { schematicPath: string; gridSize?: number; elements?: string[] }) => {
      const result = await callKicadScript("snap_to_grid", args);
      if (result.success) {
        return { content: [{ type: "text", text: result.message }] };
      }
      return {
        content: [{ type: "text", text: `Failed: ${result.message || "Unknown error"}` }],
      };
    },
  );

  server.tool(
    "get_net_at_point",
    "Returns the net name at a given (x, y) coordinate in a schematic, or null if no net label " +
      "or wire endpoint is present at that position. Faster than get_pin_net when you only need " +
      "the net name at a known coordinate and don't need pin traversal.",
    {
      schematicPath: z.string().describe("Path to the schematic file (.kicad_sch)"),
      x: z.number().describe("X coordinate in mm"),
      y: z.number().describe("Y coordinate in mm"),
    },
    async (args: { schematicPath: string; x: number; y: number }) => {
      const result = await callKicadScript("get_net_at_point", args);
      if (result.success) {
        const netName = result.net_name ?? null;
        const source = result.source ?? null;
        const pos = result.position;
        return {
          content: [
            {
              type: "text",
              text:
                `Net at (${pos?.x ?? args.x}, ${pos?.y ?? args.y}): ` +
                (netName !== null ? netName : "(none)") +
                (source ? ` [source: ${source}]` : ""),
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text",
              text: `Failed to get net at point: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // Add hierarchical label to a sub-sheet
  server.tool(
    "add_schematic_hierarchical_label",
    "Add a hierarchical label (sheet interface port) to a sub-sheet schematic. " +
      "Hierarchical labels are the connection points that link a sub-sheet to its " +
      "parent via sheet pins. The label text must exactly match the corresponding " +
      "sheet pin name.",
    {
      schematicPath: z.string().describe("Path to the sub-sheet .kicad_sch file"),
      text: z.string().describe("Label text (e.g. 'SD_CLK') — must match the sheet pin name"),
      position: z.array(z.number()).length(2).describe("Position [x, y] in mm"),
      shape: z
        .enum(["input", "output", "bidirectional"])
        .describe("Signal direction from the sub-sheet's perspective"),
      orientation: z
        .number()
        .optional()
        .describe("Rotation in degrees: 0=label points right, 180=label points left (default: 0)"),
    },
    async (args: {
      schematicPath: string;
      text: string;
      position: number[];
      shape: "input" | "output" | "bidirectional";
      orientation?: number;
    }) => {
      const result = await callKicadScript("add_schematic_hierarchical_label", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text" as const,
              text: result.message || `Added hierarchical label '${args.text}'`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text" as const,
            text: `Failed to add hierarchical label: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );

  // List free-form text annotations in schematic
  server.tool(
    "list_schematic_texts",
    "List all free-form text annotations (notes, headings, documentation strings) in the schematic. " +
      "Returns position, angle, font size, bold/italic flags, and justification for each text element. " +
      "Optionally filter by a substring match on the text content.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      text: z
        .string()
        .optional()
        .describe("Case-insensitive substring filter — only return texts containing this string"),
    },
    async (args: { schematicPath: string; text?: string }) => {
      const result = await callKicadScript("list_schematic_texts", args);
      if (result.success) {
        const texts = result.texts || [];
        if (texts.length === 0) {
          return {
            content: [{ type: "text" as const, text: "No text annotations found in schematic." }],
          };
        }
        const lines = texts.map(
          (t: any) =>
            `  "${t.text}" at (${t.position.x}, ${t.position.y})` +
            (t.angle ? ` angle=${t.angle}` : "") +
            ` size=${t.font_size}` +
            (t.bold ? " bold" : "") +
            (t.italic ? " italic" : "") +
            ` justify=${t.justify}`,
        );
        return {
          content: [
            {
              type: "text" as const,
              text: `Text annotations (${texts.length}):\n${lines.join("\n")}`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text" as const,
            text: `Failed to list text annotations: ${result.message || "Unknown error"}`,
          },
        ],
        isError: true,
      };
    },
  );

  // Add free-form text annotation to schematic
  server.tool(
    "add_schematic_text",
    "Add a free-form text annotation to the schematic. " +
      "Use this to add notes, labels, section headings, or documentation strings " +
      "directly on the schematic canvas. Unlike net labels, text annotations have " +
      "no electrical significance.",
    {
      schematicPath: z.string().describe("Path to the .kicad_sch file"),
      text: z.string().describe("Text content to display"),
      position: z
        .array(z.number())
        .length(2)
        .describe("Position [x, y] in schematic mm coordinates"),
      angle: z.number().optional().describe("Rotation angle in degrees (default: 0)"),
      fontSize: z.number().optional().describe("Font size in mm (default: 1.27)"),
      bold: z.boolean().optional().describe("Bold text (default: false)"),
      italic: z.boolean().optional().describe("Italic text (default: false)"),
      justify: z
        .enum(["left", "center", "right"])
        .optional()
        .describe("Horizontal text justification (default: left)"),
    },
    async (args: {
      schematicPath: string;
      text: string;
      position: number[];
      angle?: number;
      fontSize?: number;
      bold?: boolean;
      italic?: boolean;
      justify?: "left" | "center" | "right";
    }) => {
      const result = await callKicadScript("add_schematic_text", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text" as const,
              text: result.message || "Text annotation added successfully",
            },
          ],
        };
      } else {
        return {
          content: [
            {
              type: "text" as const,
              text: `Failed to add text annotation: ${result.message || "Unknown error"}`,
            },
          ],
        };
      }
    },
  );

  // Add sheet pin to a sheet block on the parent schematic
  server.tool(
    "add_sheet_pin",
    "Add a pin to a sheet symbol block on the parent schematic. Sheet pins are the " +
      "parent-side connection points that correspond to hierarchical labels in the " +
      "sub-sheet. The pinName must exactly match a hierarchical_label in the sub-sheet.",
    {
      schematicPath: z.string().describe("Path to the PARENT .kicad_sch file"),
      sheetName: z
        .string()
        .describe("Sheet name as it appears in the Sheetname property (e.g. 'Storage')"),
      pinName: z.string().describe("Pin name — must match a hierarchical_label in the sub-sheet"),
      pinType: z
        .enum(["input", "output", "bidirectional"])
        .describe("Signal direction (should match the sub-sheet hierarchical label shape)"),
      position: z
        .array(z.number())
        .length(2)
        .describe("Pin position [x, y] in mm — must be on the sheet block boundary"),
      orientation: z
        .number()
        .optional()
        .describe("Pin orientation: 0=right edge of sheet box, 180=left edge (default: 0)"),
    },
    async (args: {
      schematicPath: string;
      sheetName: string;
      pinName: string;
      pinType: "input" | "output" | "bidirectional";
      position: number[];
      orientation?: number;
    }) => {
      const result = await callKicadScript("add_sheet_pin", args);
      if (result.success) {
        return {
          content: [
            {
              type: "text" as const,
              text:
                result.message || `Added sheet pin '${args.pinName}' to sheet '${args.sheetName}'`,
            },
          ],
        };
      }
      return {
        content: [
          {
            type: "text" as const,
            text: `Failed to add sheet pin: ${result.message || "Unknown error"}`,
          },
        ],
      };
    },
  );
}
