import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KiCADMcpServer } from "../src/server.js";
import { flagFailure, reportsAppliedWork, reportsFailure } from "../src/tools/failure-as-error.js";

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

  // A batch that wrote some of its items answers success=false. Flagging it
  // would tell the agent nothing happened; a retry would then add R1 again.
  it("a partial-success batch reply is not an error", async () => {
    const client = await connectWithBackend({
      success: false,
      added: [{ reference: "R1", symbol: "Device:R" }],
      errors: [{ reference: "U9", error: "Symbol not found: Nope:Nope" }],
      added_count: 1,
      error_count: 1,
    });
    const result = await client.callTool({
      name: "batch_add_components",
      arguments: {
        schematicPath: "/tmp/x.kicad_sch",
        components: [
          { symbol: "Device:R", reference: "R1" },
          { symbol: "Nope:Nope", reference: "U9" },
        ],
      },
    });
    expect(result.isError).toBeFalsy();
    const text = (result.content as { text: string }[])[0].text;
    expect(text).toContain("U9");
    expect(text).toContain("Symbol not found");
  });

  it("a batch that could not start is an error", async () => {
    const client = await connectWithBackend({
      success: false,
      message: "Schematic not found: /tmp/x.kicad_sch",
    });
    const result = await client.callTool({
      name: "batch_add_components",
      arguments: {
        schematicPath: "/tmp/x.kicad_sch",
        components: [{ symbol: "Device:R", reference: "R1" }],
      },
    });
    expect(result.isError).toBe(true);
    expect((result.content as { text: string }[])[0].text).toContain("Schematic not found");
  });

  // backannotate_footprints returns the backend JSON verbatim, so these two go
  // through the wrapper itself: written files mean applied work.
  it("verbatim JSON: a partial success stays unflagged, nothing written is an error", async () => {
    const partial = await connectWithBackend({
      success: false,
      updatedFiles: ["/tmp/x.kicad_sch"],
      changeCount: 3,
      failures: [{ reference: "U9", reason: "not in any sheet" }],
    });
    const applied = await partial.callTool({
      name: "backannotate_footprints",
      arguments: { boardPath: "/tmp/x.kicad_pcb" },
    });
    expect(applied.isError).toBeFalsy();
    expect((applied.content as { text: string }[])[0].text).toContain("not in any sheet");

    const nothing = await connectWithBackend({
      success: false,
      updatedFiles: [],
      changeCount: 0,
      boardFootprintCount: 12,
      failures: [{ reference: "U9", reason: "not in any sheet" }],
    });
    const none = await nothing.callTool({
      name: "backannotate_footprints",
      arguments: { boardPath: "/tmp/x.kicad_pcb" },
    });
    expect(none.isError).toBe(true);
  });
});

describe("reportsAppliedWork", () => {
  it("sees a count above zero or a non-empty list or map of applied items", () => {
    expect(reportsAppliedWork({ success: false, added_count: 1 })).toBe(true);
    expect(reportsAppliedWork({ success: false, connected: [{ ref: "U1", pin: "3" }] })).toBe(true);
    expect(reportsAppliedWork({ success: false, placed: [{ ref: "U1" }], failed: [{}] })).toBe(
      true,
    );
    expect(reportsAppliedWork({ success: false, updated: { R1: { Value: "10K" } } })).toBe(true);
    expect(reportsAppliedWork({ success: false, updatedFiles: ["/p/a.kicad_sch"] })).toBe(true);
    expect(reportsAppliedWork({ success: false, symbols: [{ pins: [] }], errors: ["x"] })).toBe(
      true,
    );
  });

  it("ignores empty results, failure counts and counts of inputs", () => {
    expect(reportsAppliedWork({ success: false, added: [], added_count: 0, error_count: 2 })).toBe(
      false,
    );
    expect(reportsAppliedWork({ success: false, updated: {}, errors: [{ ref: "R1" }] })).toBe(
      false,
    );
    expect(reportsAppliedWork({ success: false, failed: [{ ref: "R1" }] })).toBe(false);
    // backannotate_footprints: footprints counted on the board, none written
    expect(
      reportsAppliedWork({
        success: false,
        boardFootprintCount: 12,
        updatedFiles: [],
        changes: [],
      }),
    ).toBe(false);
    expect(reportsAppliedWork({ success: false, message: "Board not loaded" })).toBe(false);
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

  it("success=false with applied work is a partial success, not a failure", () => {
    expect(reportsFailure(text('{"success": false, "added_count": 2, "error_count": 1}'))).toBe(
      false,
    );
    expect(reportsFailure(text('{"success": false, "added_count": 0, "error_count": 3}'))).toBe(
      true,
    );
  });

  it("leaves an existing isError and other fields alone", () => {
    const reply = { ...text('{"success": false}'), isError: true as const, extra: 1 };
    expect(flagFailure(reply)).toBe(reply);
    const flagged = flagFailure({ ...text('{"success": false}'), extra: 1 });
    expect(flagged).toMatchObject({ isError: true, extra: 1 });
  });
});
