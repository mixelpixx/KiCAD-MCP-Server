import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { afterEach, describe, expect, it } from "vitest";
import { KiCADMcpServer } from "../src/server.js";
import { TOOLBOXES_ENV } from "../src/tools/toolboxes.js";

// A zod tuple reaches tools/list as an `items` array, which Codex CLI cannot
// read, so it drops the whole tool. Use z.array(...).length(n) instead.
const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "..", "python", "kicad_interface.py");

const clients: Client[] = [];

afterEach(async () => {
  while (clients.length > 0) await clients.pop()!.close();
});

async function listTools() {
  delete process.env[TOOLBOXES_ENV];
  const kicad = new KiCADMcpServer(SCRIPT, "error");
  const mcp = (kicad as unknown as { server: McpServer }).server;
  const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
  await mcp.connect(serverSide);
  const client = new Client({ name: "schema-test", version: "0.0.0" });
  await client.connect(clientSide);
  clients.push(client);
  return (await client.listTools()).tools;
}

/** JSON paths of every `items` keyword whose value is an array. */
function tupleItems(node: unknown, path: string): string[] {
  if (Array.isArray(node)) return node.flatMap((child, i) => tupleItems(child, `${path}[${i}]`));
  if (node === null || typeof node !== "object") return [];
  const found: string[] = [];
  for (const [key, child] of Object.entries(node)) {
    if (key === "items" && Array.isArray(child)) found.push(`${path}.items`);
    found.push(...tupleItems(child, `${path}.${key}`));
  }
  return found;
}

describe("tool input schemas", () => {
  it("lists the tool that used tuples", async () => {
    // Guards the check below against passing on an empty or partial list.
    const names = (await listTools()).map((tool) => tool.name);
    expect(names).toContain("set_voltage_clearance_rules");
  });

  it("declare no tuple-form items", async () => {
    const offenders = (await listTools()).flatMap((tool) =>
      tupleItems(tool.inputSchema, tool.name),
    );
    expect(offenders, "use z.array(...).length(n), not z.tuple(...)").toEqual([]);
  });
});
