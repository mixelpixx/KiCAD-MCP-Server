import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";
import { registerRouterTools } from "../src/tools/router.js";

// The discovery tools (list_tool_categories, get_category_tools, search_tools)
// return prose telling the client how to run what it just found. That prose is
// read by a model, so a stale instruction there is not cosmetic: it sends the
// model after a tool that does not exist.
//
// This regressed for two releases. The gated router was disabled in 3d9497e
// because indirect execution made the model hallucinate tool schemas, and
// `execute_tool` was deleted in 963a39c -- but the response strings kept
// telling clients to call it. A single search_tools reply could contain both
// "call directly, no execute_tool needed" (registry.ts) and "Use execute_tool
// with the tool name to run it" (router.ts), contradicting itself.
//
// The assertion is on RUNTIME OUTPUT rather than source text on purpose. The
// file header in router.ts legitimately explains this history and names
// `execute_tool` in a comment; grepping the source would flag that comment and
// push a future author to delete the explanation. What must stay clean is what
// actually reaches a client.

const TOOLS_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "tools");

type Handler = (args: Record<string, unknown>) => Promise<{ content: { text: string }[] }>;

/**
 * Minimal stand-in for McpServer that records what registerRouterTools()
 * registers, so the handlers can be invoked without standing up a server.
 */
function recordRouterTools(): Map<string, Handler> {
  const handlers = new Map<string, Handler>();
  const fakeServer = {
    tool: (name: string, _description: string, _schema: unknown, handler: Handler) => {
      handlers.set(name, handler);
    },
  };
  // The command function is never called by the discovery tools: they only read
  // the in-process registry. Failing loudly is better than returning a stub,
  // because it proves discovery stayed read-only.
  const callKicad = async () => {
    throw new Error("discovery tools must not call into KiCAD");
  };
  registerRouterTools(fakeServer as never, callKicad as never);
  return handlers;
}

async function textOf(handler: Handler, args: Record<string, unknown> = {}): Promise<string> {
  const res = await handler(args);
  return res.content.map((c) => c.text).join("\n");
}

/** Every tool actually wired into the server via server.tool("name", ...). */
function registeredToolNames(): Set<string> {
  const names = new Set<string>();
  for (const file of readdirSync(TOOLS_DIR).filter((f) => f.endsWith(".ts"))) {
    const src = readFileSync(join(TOOLS_DIR, file), "utf-8");
    for (const m of src.matchAll(/server\.tool\(\s*["'`]([^"'`]+)["'`]/g)) {
      names.add(m[1]);
    }
  }
  return names;
}

describe("discovery responses do not reference deleted tools", () => {
  it("execute_tool is not registered anywhere", () => {
    expect(registeredToolNames().has("execute_tool")).toBe(false);
  });

  it("registers the three read-only discovery tools", () => {
    const handlers = recordRouterTools();
    expect([...handlers.keys()].sort()).toEqual([
      "get_category_tools",
      "list_tool_categories",
      "search_tools",
    ]);
  });

  it("no discovery response mentions execute_tool", async () => {
    const handlers = recordRouterTools();

    const responses = [
      await textOf(handlers.get("list_tool_categories")!),
      await textOf(handlers.get("get_category_tools")!, { category: "export" }),
      await textOf(handlers.get("search_tools")!, { query: "gerber" }),
      // A direct tool, which is the branch in registry.ts searchTools() that
      // used to say "no execute_tool needed".
      await textOf(handlers.get("search_tools")!, { query: "project" }),
      // The no-match branch has its own note; check it too.
      await textOf(handlers.get("search_tools")!, { query: "zzzz-no-such-tool" }),
    ];

    for (const body of responses) {
      expect(body).not.toContain("execute_tool");
    }
  });

  it("every tool named in a discovery response is actually registered", async () => {
    const handlers = recordRouterTools();
    const registered = registeredToolNames();

    const body = await textOf(handlers.get("get_category_tools")!, { category: "export" });
    const parsed = JSON.parse(body) as { tools: { name: string }[] };

    expect(parsed.tools.length).toBeGreaterThan(0);
    for (const tool of parsed.tools) {
      expect(registered, `${tool.name} is advertised but not registered`).toContain(tool.name);
    }
  });
});
