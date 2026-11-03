import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { afterEach, describe, expect, it } from "vitest";
import { KiCADMcpServer } from "../src/server.js";
import {
  EXPORT_TOOLS,
  OPERATING_MODE_ENV,
  parseOperatingMode,
  READ_ONLY_TOOLS,
} from "../src/tools/operating-mode.js";
import { directToolNames, getDistinctToolNames } from "../src/tools/registry.js";
import { TOOLBOXES_ENV } from "../src/tools/toolboxes.js";

// Operating modes (src/tools/operating-mode.ts) hide every tool the mode does
// not allow, through the same enabled flag toolboxes use. These tests drive the
// real server through an in-memory MCP client, like tests-ts/toolboxes.test.ts.
const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "..", "python", "kicad_interface.py");
const CONTROLS = ["list_toolboxes", "open_toolbox", "close_toolbox"];

// Tools that change the design, the project or KiCad itself. If one of these
// ever appears in READ_ONLY_TOOLS, readonly mode would let an agent that was
// promised "no changes" make them.
const MUST_STAY_WRITE = [
  "save_project",
  "save_board",
  "save_as",
  "create_project",
  "place_component",
  "move_component",
  "delete_component",
  "route_trace",
  "add_net",
  "add_schematic_component",
  "add_schematic_wire",
  "annotate_schematic",
  "sync_schematic_to_board",
  "autoroute",
  "register_symbol_library",
  "register_footprint_library",
  "remove_library_table_entry",
  "launch_kicad_ui",
  "install_gui_driver",
  "kicad_gui_click",
  "refill_zones",
];

const clients: Client[] = [];

afterEach(async () => {
  delete process.env[OPERATING_MODE_ENV];
  delete process.env[TOOLBOXES_ENV];
  while (clients.length > 0) await clients.pop()!.close();
});

async function connect(mode?: string, toolboxes?: string) {
  if (mode === undefined) delete process.env[OPERATING_MODE_ENV];
  else process.env[OPERATING_MODE_ENV] = mode;
  if (toolboxes === undefined) delete process.env[TOOLBOXES_ENV];
  else process.env[TOOLBOXES_ENV] = toolboxes;

  const kicad = new KiCADMcpServer(SCRIPT, "error");
  const mcp = (kicad as unknown as { server: McpServer }).server;
  const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
  await mcp.connect(serverSide);
  const client = new Client({ name: "mode-test", version: "0.0.0" });
  await client.connect(clientSide);
  clients.push(client);
  return {
    list: async () => (await client.listTools()).tools,
    names: async () => (await client.listTools()).tools.map((t) => t.name).sort(),
    call: async (name: string, args: Record<string, unknown> = {}) => {
      try {
        const result = await client.callTool({ name, arguments: args });
        const text = (result.content as { text?: string }[])[0]?.text ?? "";
        return { isError: result.isError === true, text };
      } catch (error) {
        return { isError: true, text: String(error) };
      }
    },
  };
}

describe("parseOperatingMode", () => {
  it("defaults to write", () => {
    expect(parseOperatingMode(undefined)).toEqual({ mode: "write" });
    expect(parseOperatingMode("  ")).toEqual({ mode: "write" });
  });

  it("accepts the modes with any case, - or _", () => {
    expect(parseOperatingMode("ReadOnly").mode).toBe("readonly");
    expect(parseOperatingMode("read-only").mode).toBe("readonly");
    expect(parseOperatingMode("read_only").mode).toBe("readonly");
    expect(parseOperatingMode("MANUFACTURING").mode).toBe("manufacturing");
    expect(parseOperatingMode("write").mode).toBe("write");
  });

  it("fails closed: an unrecognised value means readonly", () => {
    expect(parseOperatingMode("experimental")).toEqual({
      mode: "readonly",
      unrecognised: "experimental",
    });
  });
});

describe("the mode lists", () => {
  const registered = new Set(getDistinctToolNames());

  it("name only registered tools", () => {
    expect([...READ_ONLY_TOOLS].filter((t) => !registered.has(t))).toEqual([]);
    expect([...EXPORT_TOOLS].filter((t) => !registered.has(t))).toEqual([]);
  });

  it("do not overlap", () => {
    expect([...EXPORT_TOOLS].filter((t) => READ_ONLY_TOOLS.has(t))).toEqual([]);
  });

  it("keep tools that change things out of readonly", () => {
    expect(MUST_STAY_WRITE.filter((t) => READ_ONLY_TOOLS.has(t))).toEqual([]);
  });

  it("include the discovery tools, so every mode can find its tools", () => {
    for (const tool of [
      "search_tools",
      "list_tool_categories",
      "get_category_tools",
      ...CONTROLS,
    ]) {
      expect(READ_ONLY_TOOLS.has(tool), tool).toBe(true);
    }
  });
});

describe("operating modes over MCP", () => {
  it("write mode (the default) changes nothing", async () => {
    const session = await connect();
    expect(await session.names()).toHaveLength(getDistinctToolNames().length - CONTROLS.length);
  });

  it("readonly shows exactly the read-only tools", async () => {
    const session = await connect("readonly");
    const expected = [...READ_ONLY_TOOLS].filter((t) => !CONTROLS.includes(t)).sort();
    expect(await session.names()).toEqual(expected);
  });

  it("readonly rejects a tool that would change the board", async () => {
    const session = await connect("readonly");
    const reply = await session.call("route_trace", {});
    expect(reply.isError).toBe(true);
    expect(reply.text).toContain("disabled");
  });

  it("manufacturing adds the export tools and nothing else", async () => {
    const session = await connect("manufacturing");
    const expected = [...READ_ONLY_TOOLS, ...EXPORT_TOOLS]
      .filter((t) => !CONTROLS.includes(t))
      .sort();
    expect(await session.names()).toEqual(expected);
  });

  it("an unrecognised mode runs as readonly", async () => {
    const session = await connect("experimental");
    const names = await session.names();
    for (const name of names) expect(READ_ONLY_TOOLS.has(name), name).toBe(true);
  });

  it("combines with toolboxes: a tool needs both", async () => {
    const session = await connect("readonly", "core");
    const names = await session.names();
    const expected = [...directToolNames, "search_tools", ...CONTROLS]
      .filter((t) => READ_ONLY_TOOLS.has(t))
      .sort();
    expect(names).toEqual(expected);

    // Opening a toolbox adds only its read-only tools.
    const reply = await session.call("open_toolbox", { toolboxes: ["routing"] });
    expect(reply.isError).toBe(false);
    const after = await session.names();
    for (const name of after) expect(READ_ONLY_TOOLS.has(name), name).toBe(true);
  });

  it("list_toolboxes reports the mode and only allowed tools", async () => {
    const session = await connect("readonly", "core");
    const body = JSON.parse((await session.call("list_toolboxes")).text);
    expect(body.operating_mode).toBe("readonly");
    for (const box of body.toolboxes) {
      expect(box.tool_count).toBe(box.tools.length);
      for (const tool of box.tools) expect(READ_ONLY_TOOLS.has(tool), tool).toBe(true);
    }
  });

  it("marks read-only tools with readOnlyHint in every mode", async () => {
    const session = await connect();
    for (const tool of await session.list()) {
      expect(tool.annotations?.readOnlyHint === true, tool.name).toBe(
        READ_ONLY_TOOLS.has(tool.name),
      );
    }
  });
});
