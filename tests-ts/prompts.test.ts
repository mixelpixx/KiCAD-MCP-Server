import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { afterEach, describe, expect, it } from "vitest";
import { KiCADMcpServer } from "../src/server.js";
import { fillTemplate, NOT_PROVIDED } from "../src/prompts/template.js";

// Every prompt marks its arguments with {{name}}. These tests drive the real
// server through an in-memory MCP client and check that what the caller passes
// reaches the text, instead of the literal placeholder.
const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "..", "python", "kicad_interface.py");

const clients: Client[] = [];

afterEach(async () => {
  while (clients.length > 0) await clients.pop()!.close();
});

async function connect() {
  const kicad = new KiCADMcpServer(SCRIPT, "error");
  const mcp = (kicad as unknown as { server: McpServer }).server;
  const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
  await mcp.connect(serverSide);
  const client = new Client({ name: "prompt-test", version: "0.0.0" });
  await client.connect(clientSide);
  clients.push(client);
  return client;
}

function textOf(result: { messages: { content: { type: string; text?: string } }[] }) {
  return result.messages.map((m) => m.content.text ?? "").join("\n");
}

describe("prompts over MCP", () => {
  it("fill in every argument and leave no placeholder", async () => {
    const client = await connect();
    const { prompts } = await client.listPrompts();
    expect(prompts.length).toBeGreaterThan(0);

    for (const prompt of prompts) {
      const args = Object.fromEntries(
        (prompt.arguments ?? []).map((a) => [a.name, `VALUE_OF_${a.name}`]),
      );
      const text = textOf(await client.getPrompt({ name: prompt.name, arguments: args }));
      for (const value of Object.values(args)) expect(text, prompt.name).toContain(value);
      expect(text, prompt.name).not.toMatch(/\{\{\w+\}\}/);
    }
  });

  it("mark an optional argument the caller left out", async () => {
    const client = await connect();
    const text = textOf(
      await client.getPrompt({
        name: "create_footprint_guide",
        arguments: { component: "SOT-23 NPN transistor" },
      }),
    );
    expect(text).toContain("SOT-23 NPN transistor");
    expect(text).toContain(NOT_PROVIDED);
    expect(text).not.toContain("{{libraryPath}}");
  });
});

describe("fillTemplate", () => {
  const result = (text: string) => ({
    messages: [{ role: "user" as const, content: { type: "text" as const, text } }],
  });

  it("does not expand placeholders inside a value", () => {
    const filled = fillTemplate({ a: "{{b}}", b: "x" }, result("A={{a}} B={{b}}"));
    expect(textOf(filled)).toBe("A={{b}} B=x");
  });

  it("treats a blank value as not provided", () => {
    expect(textOf(fillTemplate({ a: "  " }, result("[{{a}}]")))).toBe(`[${NOT_PROVIDED}]`);
  });
});
