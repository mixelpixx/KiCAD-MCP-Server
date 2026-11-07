import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KiCADMcpServer } from "../src/server.js";
import { flagFailure, reportsFailure } from "../src/tools/failure-as-error.js";

// A backend reply of {"success": false} must reach the client as an MCP error
// (isError: true). Most handlers return the backend JSON verbatim, and before
// failure-as-error.ts those failures went out as ordinary results.
//
// These tests drive the real KiCADMcpServer through an in-memory MCP client,
// with the Python bridge stubbed, so no worker is spawned.
const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "..", "python", "kicad_interface.py");
const clients: Client[] = [];

afterEach(async () => {
  vi.restoreAllMocks();
  while (clients.length > 0) await clients.pop()!.close();
});

async function connectWithBackend(reply: unknown) {
  vi.spyOn(
    KiCADMcpServer.prototype as unknown as { callKicadScript: () => Promise<unknown> },
    "callKicadScript",
  ).mockResolvedValue(reply);
  const kicad = new KiCADMcpServer(SCRIPT, "error");
  const mcp = (kicad as unknown as { server: McpServer }).server;
  const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
  await mcp.connect(serverSide);
  const client = new Client({ name: "failure-test", version: "0.0.0" });
  await client.connect(clientSide);
  clients.push(client);
  return client;
}

describe("backend failure reaches the client as isError", () => {
  // Tools from different modules, each returning the backend JSON verbatim.
  for (const [tool, args] of [
    ["create_project", { path: "/tmp/x", name: "x" }],
    ["get_board_info", {}],
    [
      "add_schematic_component",
      { schematicPath: "/tmp/x.kicad_sch", symbol: "Device:R", reference: "R1" },
    ],
  ] as const) {
    it(`${tool}: success=false → isError`, async () => {
      const client = await connectWithBackend({ success: false, message: "Board not loaded" });
      const result = await client.callTool({ name: tool, arguments: args });
      expect(result.isError).toBe(true);
      expect((result.content as { text: string }[])[0].text).toContain("Board not loaded");
    });
  }

  it("success=true stays a normal result", async () => {
    const client = await connectWithBackend({ success: true, project: {} });
    const result = await client.callTool({
      name: "create_project",
      arguments: { path: "/tmp/x", name: "x" },
    });
    expect(result.isError).toBeFalsy();
  });
});

describe("reportsFailure / flagFailure", () => {
  const text = (t: string) => ({ content: [{ type: "text", text: t }] });

  it("detects pretty-printed and compact success=false", () => {
    expect(reportsFailure(text('{\n  "success": false,\n  "message": "x"\n}'))).toBe(true);
    expect(reportsFailure(text('{"success":false}'))).toBe(true);
  });

  it("ignores success=true, missing success, arrays, non-JSON and non-text content", () => {
    expect(reportsFailure(text('{"success": true}'))).toBe(false);
    expect(reportsFailure(text('{"data": [1]}'))).toBe(false);
    expect(reportsFailure(text('[{"success": false}]'))).toBe(false);
    expect(reportsFailure(text('not json "success": false'))).toBe(false);
    expect(reportsFailure({ content: [{ type: "image", data: "..." }] })).toBe(false);
    expect(reportsFailure(null)).toBe(false);
  });

  it("only a nested success=false is not a top-level failure", () => {
    expect(reportsFailure(text('{"success": true, "steps": [{"success": false}]}'))).toBe(false);
  });

  it("leaves an existing isError and other fields alone", () => {
    const reply = { ...text('{"success": false}'), isError: true as const, extra: 1 };
    expect(flagFailure(reply)).toBe(reply);
    const flagged = flagFailure({ ...text('{"success": false}'), extra: 1 });
    expect(flagged).toMatchObject({ isError: true, extra: 1 });
  });
});
