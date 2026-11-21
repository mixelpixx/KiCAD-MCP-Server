import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { afterEach, expect, it, vi } from "vitest";
import { KiCADMcpServer } from "../src/server.js";

const project = { projectPath: "demo.kicad_pro" };
const component = { ...project, schematicPath: "demo.kicad_sch", reference: "R1", variant: "Lite" };
const cases = [
  ["list_variants", project, project],
  [
    "create_variant",
    { ...project, name: "Lite" },
    { ...project, name: "Lite", description: "Low cost" },
  ],
  ["get_component_variant", component, component],
  [
    "set_component_variant",
    component,
    { ...component, dnp: false, fields: { Value: "10k", MPN: null }, reset: false },
  ],
  [
    "export_variant_bom",
    { ...project, variant: "Lite", outputPath: "bom.csv" },
    { ...project, variant: "Lite", outputPath: "bom.csv", excludeDnp: false },
  ],
] as const;

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

it("publishes the variant schemas and forwards the unmodified arguments to Python", async () => {
  vi.stubEnv("KICAD_MCP_TOOLBOXES", "all");
  vi.stubEnv("KICAD_MCP_OPERATING_MODE", "write");
  const proto = KiCADMcpServer.prototype as unknown as {
    callKicadScript(name: string, args: Record<string, unknown>): Promise<unknown>;
  };
  const call = vi.spyOn(proto, "callKicadScript").mockResolvedValue({ success: true });
  const script = fileURLToPath(new URL("../python/kicad_interface.py", import.meta.url));
  const { server } = new KiCADMcpServer(script, "error") as unknown as { server: McpServer };
  const client = new Client({ name: "variants-test", version: "1" });
  const [left, right] = InMemoryTransport.createLinkedPair();
  await server.connect(right);
  try {
    await client.connect(left);
    const { tools } = await client.listTools();
    for (const [name, required, args] of cases) {
      const tool = tools.find((t) => t.name === name);
      expect(tool, name).toBeDefined();
      expect(tool!.inputSchema.required?.slice().sort()).toEqual(Object.keys(required).sort());
      expect(Object.keys(tool!.inputSchema.properties ?? {}).sort()).toEqual(
        Object.keys(args).sort(),
      );
      const response = await client.callTool({ name, arguments: args });
      expect(response.isError).not.toBe(true);
      expect(call).toHaveBeenLastCalledWith(name, args);
    }
    call.mockClear();
    const invalid = await client.callTool({
      name: "set_component_variant",
      arguments: { ...component, fields: { Value: 123 } },
    });
    expect(invalid.isError).toBe(true);
    expect(call).not.toHaveBeenCalled();
  } finally {
    await client.close();
  }
});
