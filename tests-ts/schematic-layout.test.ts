import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KiCADMcpServer } from "../src/server.js";

const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "..", "python", "kicad_interface.py");
const clients: Client[] = [];

afterEach(async () => {
  vi.restoreAllMocks();
  while (clients.length > 0) await clients.pop()!.close();
});

async function connectWithSpy(reply: unknown) {
  const spy = vi
    .spyOn(
      KiCADMcpServer.prototype as unknown as {
        callKicadScript: (command: string, params: unknown) => Promise<unknown>;
      },
      "callKicadScript",
    )
    .mockResolvedValue(reply);
  const kicad = new KiCADMcpServer(SCRIPT, "error");
  const mcp = (kicad as unknown as { server: McpServer }).server;
  const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
  await mcp.connect(serverSide);
  const client = new Client({ name: "schematic-layout-test", version: "0.0.0" });
  await client.connect(clientSide);
  clients.push(client);
  return { client, spy };
}

describe("schematic property position MCP schemas (#520)", () => {
  it("set_schematic_property_position omits angle when not supplied instead of defaulting to 0", async () => {
    const reply = {
      success: true,
      message: "Moved R2.Reference",
      stored_angle: 90,
      drawn_angle: 0,
      effective_justify: { horizontal: "right", vertical: "top" },
    };
    const { client, spy } = await connectWithSpy(reply);

    const result = await client.callTool({
      name: "set_schematic_property_position",
      arguments: {
        schematicPath: "/tmp/test.kicad_sch",
        reference: "R2",
        property: "Reference",
        x: 100,
        y: 55,
      },
    });

    expect(spy).toHaveBeenCalledTimes(1);
    const [command, params] = spy.mock.calls[0] as [string, Record<string, unknown>];
    expect(command).toBe("set_schematic_property_position");
    expect(params.angle).toBeUndefined();
    expect(result.isError).toBeFalsy();
    const parsed = JSON.parse((result.content as { text: string }[])[0].text);
    expect(parsed.stored_angle).toBe(90);
    expect(parsed.drawn_angle).toBe(0);
    expect(parsed.effective_justify).toEqual({ horizontal: "right", vertical: "top" });
  });

  it("batch_set_schematic_property_positions omits angle per item when not supplied", async () => {
    const reply = {
      success: true,
      applied: [
        {
          reference: "R2",
          property: "Reference",
          x: 100,
          y: 55,
          angle: 0,
          stored_angle: 90,
          drawn_angle: 0,
          effective_justify: { horizontal: "center", vertical: "center" },
          visible: true,
        },
        {
          reference: "R2",
          property: "Value",
          x: 100,
          y: 65,
          angle: 90,
          stored_angle: 0,
          drawn_angle: 90,
          effective_justify: { horizontal: "center", vertical: "center" },
          visible: true,
        },
      ],
      failed: [],
      applied_count: 2,
      failed_count: 0,
    };
    const { client, spy } = await connectWithSpy(reply);

    const result = await client.callTool({
      name: "batch_set_schematic_property_positions",
      arguments: {
        schematicPath: "/tmp/test.kicad_sch",
        updates: [
          { reference: "R2", property: "Reference", x: 100, y: 55 },
          { reference: "R2", property: "Value", x: 100, y: 65, angle: 90 },
        ],
      },
    });

    expect(spy).toHaveBeenCalledTimes(1);
    const [, params] = spy.mock.calls[0] as [string, { updates: Array<Record<string, unknown>> }];
    expect(params.updates[0].angle).toBeUndefined();
    expect(params.updates[1].angle).toBe(90);
    expect(result.isError).toBeFalsy();
    const parsed = JSON.parse((result.content as { text: string }[])[0].text);
    expect(parsed.applied[0].stored_angle).toBe(90);
    expect(parsed.applied[1].drawn_angle).toBe(90);
  });

  it("flags total failure as isError and keeps partial batch unflagged", async () => {
    const { client: failClient } = await connectWithSpy({
      success: false,
      message: "Component 'R99' not found in schematic",
    });
    const failRes = await failClient.callTool({
      name: "set_schematic_property_position",
      arguments: {
        schematicPath: "/tmp/test.kicad_sch",
        reference: "R99",
        property: "Reference",
        x: 10,
        y: 10,
      },
    });
    expect(failRes.isError).toBe(true);

    const { client: partialClient } = await connectWithSpy({
      success: false,
      applied: [
        { reference: "R1", property: "Reference", x: 10, y: 10, stored_angle: 0, drawn_angle: 0 },
      ],
      failed: [{ reference: "R99", property: "Reference", reason: "not found" }],
      applied_count: 1,
      failed_count: 1,
    });
    const partialRes = await partialClient.callTool({
      name: "batch_set_schematic_property_positions",
      arguments: {
        schematicPath: "/tmp/test.kicad_sch",
        updates: [
          { reference: "R1", property: "Reference", x: 10, y: 10 },
          { reference: "R99", property: "Reference", x: 10, y: 10 },
        ],
      },
    });
    expect(partialRes.isError).toBeFalsy();
  });
});
