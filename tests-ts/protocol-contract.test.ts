import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { Client, InMemoryTransport, type Tool } from "@modelcontextprotocol/client";
import { serveStdio, type StdioServerHandle } from "@modelcontextprotocol/server/stdio";
import { KiCADMcpServer } from "../src/server.js";
import { getRoutedToolNames } from "../src/tools/registry.js";

const MODERN_PROTOCOL_VERSION = "2026-07-28";
const ROUTER_TOOL_NAMES = ["list_tool_categories", "get_category_tools", "search_tools"];

type ProtocolFixture = {
  client: Client;
  host: KiCADMcpServer;
  stdio: StdioServerHandle;
};

const fixtures: ProtocolFixture[] = [];

async function connectClient(mode: "auto" | "legacy"): Promise<ProtocolFixture> {
  const host = new KiCADMcpServer(resolve("python/kicad_interface.py"), "error");
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const stdio = serveStdio(() => host.createProtocolServer(), {
    legacy: "serve",
    transport: serverTransport,
  });
  const client = new Client(
    { name: `kicad-contract-${mode}`, version: "1.0.0" },
    { versionNegotiation: { mode } },
  );

  const fixture = { client, host, stdio };
  fixtures.push(fixture);
  await client.connect(clientTransport);
  return fixture;
}

function names(tools: Tool[]): string[] {
  return tools.map((tool) => tool.name);
}

afterEach(async () => {
  for (const { client, host, stdio } of fixtures.splice(0)) {
    await client.close().catch(() => undefined);
    await stdio.close().catch(() => undefined);
    await host.stop().catch(() => undefined);
  }
});

describe("KiCad MCP protocol contract", () => {
  it("auto-negotiates 2026-07-28 through the production stdio entry", async () => {
    const { client } = await connectClient("auto");

    expect(client.getProtocolEra()).toBe("modern");
    expect(client.getNegotiatedProtocolVersion()).toBe(MODERN_PROTOCOL_VERSION);
    expect(client.getServerVersion()).toMatchObject({
      name: "kicad-mcp-server",
      version: "2.7.0",
    });

    const discovery = client.getDiscoverResult();
    expect(discovery).toBeDefined();
    expect(discovery?.supportedVersions).toContain(MODERN_PROTOCOL_VERSION);
    expect(discovery).toMatchObject({
      ttlMs: 3_600_000,
      cacheScope: "public",
    });
  });

  it("keeps the 2025 initialize path available to legacy clients", async () => {
    const { client } = await connectClient("legacy");

    expect(client.getProtocolEra()).toBe("legacy");
    expect(client.getNegotiatedProtocolVersion()).toMatch(/^2025-/);
    expect(client.getDiscoverResult()).toBeUndefined();
    expect(client.getServerVersion()).toMatchObject({ name: "kicad-mcp-server" });

    const result = await client.listTools(undefined, { cacheMode: "refresh" });
    expect(result.tools.length).toBeGreaterThan(0);
    expect(result).not.toHaveProperty("ttlMs");
    expect(result).not.toHaveProperty("cacheScope");
  });

  it("publishes a deterministic, cacheable catalog matching the runtime registry", async () => {
    const { client } = await connectClient("auto");

    const first = await client.listTools(undefined, { cacheMode: "refresh" });
    const second = await client.listTools(undefined, { cacheMode: "refresh" });
    const firstNames = names(first.tools);
    const expectedNames = [...ROUTER_TOOL_NAMES, ...getRoutedToolNames()];

    expect(names(second.tools)).toEqual(firstNames);
    expect(new Set(firstNames).size).toBe(firstNames.length);
    expect(new Set(firstNames)).toEqual(new Set(expectedNames));
    expect(first).toMatchObject({
      ttlMs: 86_400_000,
      cacheScope: "public",
    });

    expect(first.tools.every((tool) => tool.annotations !== undefined)).toBe(true);
    expect(first.tools.every((tool) => tool.outputSchema !== undefined)).toBe(true);
  });

  it("returns schema-backed structured content from a backend-free router tool", async () => {
    const { client } = await connectClient("auto");
    const catalog = await client.listTools();
    const definition = catalog.tools.find((tool) => tool.name === "list_tool_categories");

    expect(definition?.outputSchema).toBeDefined();

    const result = await client.callTool({ name: "list_tool_categories", arguments: {} });
    expect(result.isError).not.toBe(true);
    expect(result.structuredContent).toMatchObject({
      total_categories: expect.any(Number),
      total_tools: expect.any(Number),
      categories: expect.any(Array),
    });

    const text = result.content.find((block) => block.type === "text");
    expect(text).toBeDefined();
    if (text?.type === "text") {
      expect(JSON.parse(text.text)).toEqual(result.structuredContent);
    }

    const missingCategory = await client.callTool({
      name: "get_category_tools",
      arguments: { category: "does_not_exist" },
    });
    expect(missingCategory.isError).toBe(true);
    expect(missingCategory.structuredContent).toMatchObject({
      error: expect.stringContaining("does_not_exist"),
      available_categories: expect.any(Array),
    });
  });
});
