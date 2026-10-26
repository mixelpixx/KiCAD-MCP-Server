import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ToolListChangedNotificationSchema } from "@modelcontextprotocol/sdk/types.js";
import { afterEach, describe, expect, it } from "vitest";
import { KiCADMcpServer } from "../src/server.js";
import { directToolNames, getDistinctToolNames, toolCategories } from "../src/tools/registry.js";
import { parseToolboxSetting, resolveToolbox, TOOLBOXES_ENV } from "../src/tools/toolboxes.js";

// Toolboxes (src/tools/toolboxes.ts) decide which registered tools a client
// sees. These tests drive the real KiCADMcpServer through an in-memory MCP
// client, so what they check is what a client receives: tools/list,
// tools/call and notifications/tools/list_changed.
//
// The constructor only checks that the interface script exists, and start()
// is never called, so no Python worker is spawned.
const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "..", "python", "kicad_interface.py");
const CONTROLS = ["list_toolboxes", "open_toolbox", "close_toolbox"];
const CATEGORY_BROWSERS = ["list_tool_categories", "get_category_tools"];

interface Session {
  names: () => Promise<string[]>;
  call: (name: string, args?: Record<string, unknown>) => Promise<{ isError: boolean; body: any }>;
  notifications: () => number;
}

const clients: Client[] = [];

afterEach(async () => {
  delete process.env[TOOLBOXES_ENV];
  while (clients.length > 0) await clients.pop()!.close();
});

async function connect(setting?: string): Promise<Session> {
  if (setting === undefined) delete process.env[TOOLBOXES_ENV];
  else process.env[TOOLBOXES_ENV] = setting;

  const kicad = new KiCADMcpServer(SCRIPT, "error");
  const mcp = (kicad as unknown as { server: McpServer }).server;
  const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
  await mcp.connect(serverSide);

  const client = new Client({ name: "toolbox-test", version: "0.0.0" });
  let notifications = 0;
  client.setNotificationHandler(ToolListChangedNotificationSchema, async () => {
    notifications++;
  });
  await client.connect(clientSide);
  clients.push(client);

  return {
    names: async () => (await client.listTools()).tools.map((tool) => tool.name).sort(),
    call: async (name, args = {}) => {
      try {
        const result = await client.callTool({ name, arguments: args });
        const text = (result.content as { text?: string }[])[0]?.text ?? "";
        let body: unknown = text;
        try {
          body = JSON.parse(text);
        } catch {
          // plain-text reply, e.g. an SDK error message
        }
        return { isError: result.isError === true, body };
      } catch (error) {
        return { isError: true, body: String(error) };
      }
    },
    notifications: () => notifications,
  };
}

/** Let notifications already sent reach the client. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 20));

const toolsOf = (toolbox: string) => toolCategories.find((c) => c.name === toolbox)!.tools;

describe("parseToolboxSetting", () => {
  it("shows every tool when unset, empty or 'all'", () => {
    expect(parseToolboxSetting(undefined)).toEqual({ mode: "all" });
    expect(parseToolboxSetting("")).toEqual({ mode: "all" });
    expect(parseToolboxSetting(" ALL ")).toEqual({ mode: "all" });
    expect(parseToolboxSetting("schematic,all")).toEqual({ mode: "all" });
  });

  it("'core' starts toolbox mode with nothing open", () => {
    expect(parseToolboxSetting("core")).toEqual({ mode: "toolboxes", preload: [], unknown: [] });
  });

  it("reads a list of toolboxes, case-insensitively and without duplicates", () => {
    expect(parseToolboxSetting(" Schematic , routing,schematic ")).toEqual({
      mode: "toolboxes",
      preload: ["schematic", "routing"],
      unknown: [],
    });
  });

  it("treats - and _ alike, since category names use both", () => {
    expect(resolveToolbox("parts_registry")).toBe("parts-registry");
    expect(resolveToolbox("GUI_DRIVER")).toBe("gui-driver");
    expect(resolveToolbox("symbol-library")).toBe("symbol_library");
  });

  it("reports unknown names instead of failing", () => {
    expect(parseToolboxSetting("bogus,core")).toEqual({
      mode: "toolboxes",
      preload: [],
      unknown: ["bogus"],
    });
  });
});

describe("toolboxes over MCP", () => {
  it("by default every tool is visible and the toolbox controls are not", async () => {
    const session = await connect();
    const names = await session.names();
    expect(names).toHaveLength(getDistinctToolNames().length - CONTROLS.length);
    for (const control of CONTROLS) expect(names).not.toContain(control);
    for (const browser of CATEGORY_BROWSERS) expect(names).toContain(browser);
    expect(names).toContain("route_arc_trace");
  });

  it("'core' shows only the core tools, search_tools and the toolbox controls", async () => {
    const session = await connect("core");
    expect(await session.names()).toEqual([...directToolNames, "search_tools", ...CONTROLS].sort());
  });

  it("a tool in a closed toolbox is rejected", async () => {
    const session = await connect("core");
    const reply = await session.call("route_arc_trace", {});
    expect(reply.isError).toBe(true);
    expect(String(reply.body)).toContain("disabled");
  });

  it("open_toolbox adds the toolbox's tools with one list_changed notification", async () => {
    const session = await connect("core");
    const reply = await session.call("open_toolbox", { toolboxes: ["Routing"] });
    await settle();

    expect(reply.isError).toBe(false);
    expect(reply.body.opened).toEqual(["routing"]);
    expect(reply.body.tools.routing.map((t: { name: string }) => t.name)).toEqual(
      toolsOf("routing"),
    );
    expect(reply.body.note).toContain("next message");
    expect(session.notifications()).toBe(1);

    const names = await session.names();
    for (const tool of toolsOf("routing")) expect(names).toContain(tool);
  });

  it("opening an open toolbox or an unknown name changes nothing", async () => {
    const session = await connect("routing");
    const reply = await session.call("open_toolbox", { toolboxes: ["routing", "nope"] });
    await settle();

    expect(reply.isError).toBe(false);
    expect(reply.body.already_open).toEqual(["routing"]);
    expect(reply.body.unknown).toEqual(["nope"]);
    expect(reply.body.available_toolboxes).toHaveLength(toolCategories.length);
    expect(session.notifications()).toBe(0);

    const onlyUnknown = await session.call("open_toolbox", { toolboxes: ["nope"] });
    expect(onlyUnknown.isError).toBe(true);
  });

  it("close_toolbox removes the toolbox's tools but keeps the core tools", async () => {
    const session = await connect("schematic");
    let names = await session.names();
    expect(names).toContain("add_schematic_wire");

    const reply = await session.call("close_toolbox", { toolboxes: ["schematic"] });
    await settle();
    expect(reply.body.closed).toEqual(["schematic"]);
    expect(session.notifications()).toBe(1);

    names = await session.names();
    expect(names).not.toContain("add_schematic_wire");
    // In the schematic toolbox and in the core list: stays.
    expect(names).toContain("add_schematic_component");
  });

  it("preloads the toolboxes named in the setting", async () => {
    const session = await connect("schematic,routing,bogus");
    const names = await session.names();
    expect(names).toContain("add_schematic_wire");
    expect(names).toContain("route_arc_trace");
    expect(names).not.toContain("export_gerber");
  });

  it("every registered tool is reachable through the core or a toolbox", async () => {
    const session = await connect(toolCategories.map((c) => c.name).join(","));
    const names = await session.names();
    // Everything except the two category browsers, which list_toolboxes replaces.
    expect(names).toHaveLength(getDistinctToolNames().length - CATEGORY_BROWSERS.length);
  });

  it("list_toolboxes reports every toolbox and whether it is open", async () => {
    const session = await connect("drc");
    const reply = await session.call("list_toolboxes");
    expect(reply.body.toolboxes).toHaveLength(toolCategories.length);
    expect(reply.body.open_toolboxes).toEqual(["drc"]);
    const drc = reply.body.toolboxes.find((t: { name: string }) => t.name === "drc");
    expect(drc.open).toBe(true);
    expect(drc.tools).toEqual(toolsOf("drc"));
    expect(reply.body.core_tools).toEqual(directToolNames);
  });

  it("search_tools says when a match's toolbox is closed", async () => {
    const session = await connect("core");
    let reply = await session.call("search_tools", { query: "route_arc" });
    let match = reply.body.matches.find((m: { tool: string }) => m.tool === "route_arc_trace");
    expect(match.toolbox_open).toBe(false);
    expect(reply.body.note).toContain("open_toolbox");

    await session.call("open_toolbox", { toolboxes: ["routing"] });
    reply = await session.call("search_tools", { query: "route_arc" });
    match = reply.body.matches.find((m: { tool: string }) => m.tool === "route_arc_trace");
    expect(match.toolbox_open).toBe(true);
    expect(reply.body.note).not.toContain("open_toolbox");
  });
});
