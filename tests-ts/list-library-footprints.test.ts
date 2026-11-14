import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KiCADMcpServer } from "../src/server.js";

// list_library_footprints (#407): the zod schema states the same limit rule as
// the Python handler, the description says a call returns at most 100 names,
// and a capped reply tells the agent how to get the rest.
const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "..", "python", "kicad_interface.py");
const clients: Client[] = [];

afterEach(async () => {
  vi.restoreAllMocks();
  while (clients.length > 0) await clients.pop()!.close();
});

async function connectWithBackend(reply: unknown) {
  const backend = vi
    .spyOn(
      KiCADMcpServer.prototype as unknown as {
        callKicadScript: (command: string, args: unknown) => Promise<unknown>;
      },
      "callKicadScript",
    )
    .mockResolvedValue(reply);
  const kicad = new KiCADMcpServer(SCRIPT, "error");
  const mcp = (kicad as unknown as { server: McpServer }).server;
  const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
  await mcp.connect(serverSide);
  const client = new Client({ name: "list-footprints-test", version: "0.0.0" });
  await client.connect(clientSide);
  clients.push(client);
  return { client, backend };
}

function text(result: unknown): string {
  return ((result as { content: { text: string }[] }).content[0] ?? { text: "" }).text;
}

describe("list_library_footprints", () => {
  it("advertises limit as an integer of at least 1 with a default of 100", async () => {
    const { client } = await connectWithBackend({ success: true, footprints: [] });
    const { tools } = await client.listTools();
    const tool = tools.find((t) => t.name === "list_library_footprints")!;
    const limit = (tool.inputSchema.properties as Record<string, Record<string, unknown>>).limit;
    expect(limit.type).toBe("integer");
    expect(limit.minimum).toBe(1);
    expect(limit.default).toBe(100);
    expect(limit.description).toContain("default 100");
    expect(tool.description).toContain("sorted by name");
    expect(tool.description).toContain("first 100");
  });

  it.each([0, 2.5])("refuses limit %s before calling the backend", async (limit) => {
    const { client, backend } = await connectWithBackend({ success: true, footprints: [] });
    const result = await client.callTool({
      name: "list_library_footprints",
      arguments: { library_name: "Package_SO", limit },
    });
    expect(result.isError).toBe(true);
    expect(backend).not.toHaveBeenCalled();
  });

  it("sends limit 100 when none is given", async () => {
    const { client, backend } = await connectWithBackend({ success: true, footprints: [] });
    await client.callTool({ name: "list_library_footprints", arguments: { library_name: "X" } });
    expect(backend).toHaveBeenCalledWith("list_library_footprints", {
      library_name: "X",
      limit: 100,
    });
  });

  it("says how to get the rest when the list was capped", async () => {
    const { client } = await connectWithBackend({
      success: true,
      footprints: ["A", "B"],
      count: 2,
      total: 5,
    });
    const result = await client.callTool({
      name: "list_library_footprints",
      arguments: { library_name: "X", limit: 2 },
    });
    expect(text(result)).toContain("showing 2 of 5 matching footprints");
    expect(text(result)).toContain("pass `filter` to narrow, or a larger `limit` for more");
  });

  it("adds no hint when every match was returned", async () => {
    const { client } = await connectWithBackend({
      success: true,
      footprints: ["A", "B"],
      count: 2,
      total: 2,
    });
    const result = await client.callTool({
      name: "list_library_footprints",
      arguments: { library_name: "X" },
    });
    expect(text(result)).toContain("contains 2 matching footprints");
    expect(text(result)).not.toContain("larger `limit`");
  });
});
