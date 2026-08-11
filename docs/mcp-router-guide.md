# MCP Tool Discovery Guide

KiCAD MCP exposes every supported operation as a first-class MCP tool. The
current catalog contains 183 tools: 180 KiCad capabilities and three
supplemental discovery tools. Clients call the selected capability directly;
there is no generic `execute_tool` dispatcher and no hidden "routed" subset.

## Why the catalog stays first-class

Keeping each operation in `tools/list` preserves its individual input and
output schema, safety annotations, title, and client approval surface. MCP
2026-07-28 cache hints let clients reuse the deterministic catalog without
fetching it on every request.

The three discovery tools help a model navigate the catalog when needed:

- `list_tool_categories` returns the capability categories and counts.
- `get_category_tools` returns the first-class tools in one category.
- `search_tools` searches names, titles, descriptions, and categories.

The returned names are ordinary MCP tool names. Call them directly with the
arguments described by `tools/list`.

## Typical discovery flow

1. Inspect `tools/list`, or call `search_tools` with a task keyword.
2. Optionally call `get_category_tools` to browse a broader capability area.
3. Read the selected tool's schema and annotations from `tools/list`.
4. Call that tool directly.

For example, search for `gerber`, select `export_gerber`, and then call
`export_gerber` itself. Do not call `execute_tool`; it is not part of this
server.

## SDK v2 server pattern

The server uses the MCP TypeScript SDK v2 factory entry so one registration
surface can serve MCP 2026-07-28 and legacy 2025 clients:

```typescript
import { McpServer } from "@modelcontextprotocol/server";
import { serveStdio } from "@modelcontextprotocol/server/stdio";

function buildServer(): McpServer {
  const server = new McpServer(
    { name: "kicad-mcp-server", version: "2.7.0" },
    {
      cacheHints: {
        "server/discover": { ttlMs: 3_600_000, cacheScope: "public" },
        "tools/list": { ttlMs: 86_400_000, cacheScope: "public" },
      },
    },
  );

  // Register project, board, schematic, and other tool modules here.
  return server;
}

serveStdio(() => buildServer(), { legacy: "serve" });
```

Do not replace `serveStdio` with a hand-wired `StdioServerTransport`. The
factory entry owns modern `server/discover` negotiation and the legacy
`initialize` fallback.

## Adding a capability

Register new KiCad tools through `registerKiCadTool` in the appropriate
`src/tools/*.ts` module. That single call registers the MCP tool and records
its discovery metadata in the runtime registry. Do not maintain a second list
of direct or routed tool names.

Every new tool should provide:

- a stable name, category, title, and focused description;
- a Zod input schema and an appropriate output schema;
- correct read-only, destructive, idempotent, and open-world annotations;
- a Python command route when the tool calls the KiCad worker;
- tests for schema validation, backend-route parity, and result handling.

The relevant contract tests are in `tests-ts/protocol-contract.test.ts` and
`tests/test_ts_tool_registry.py`.

## Catalog invariants

- Registration order is deterministic.
- Tool names are unique.
- The runtime registry and `tools/list` contain the same capability names.
- Discovery tools are supplemental and excluded from KiCad capability counts.
- Backend failures are returned with MCP `isError: true`.
- Structured results are validated against advertised output schemas.

See [Tool Inventory](TOOL_INVENTORY.md) for current category counts and
[Architecture](ARCHITECTURE.md) for the complete TypeScript/Python design.
