# Tool Discovery Architecture

KiCAD MCP has one authoritative, first-class MCP tool surface. All 183 tools
are registered with the SDK and returned by `tools/list`; 180 are KiCad
capabilities and three provide supplemental catalog discovery.

## Runtime flow

```text
MCP client
  |
  | tools/list (all 183 definitions)
  v
TypeScript McpServer
  |-- registerKiCadTool(...) -> SDK registration
  |                         -> runtime catalog metadata
  |
  | optional discovery calls
  |-- list_tool_categories
  |-- get_category_tools
  `-- search_tools
  |
  | direct tools/call using the selected tool name
  v
Correlated Python command bridge -> KiCad backend
```

There is no `execute_tool`, hidden routed subset, or direct-versus-routed
distinction. This preserves every tool's schema, annotations, and approval
surface. The MCP 2026-07-28 `tools/list` cache hint allows clients to cache the
large deterministic catalog safely.

## Source ownership

### `src/tools/tool-registration.ts`

`registerKiCadTool` is the single registration wrapper. It:

- registers the tool with SDK v2;
- records its name, title, description, and category in the runtime catalog;
- attaches safety annotations;
- normalizes structured results and backend failures;
- provides confirmation through MCP `input_required` for destructive tools.

### `src/tools/registry.ts`

The registry is populated by real registrations. It derives categories,
statistics, lookup results, and keyword search from that live metadata. It
does not maintain a second manually curated tool inventory.

### `src/tools/router.ts`

This module implements three read-only supplemental tools:

1. `list_tool_categories`
2. `get_category_tools`
3. `search_tools`

They return names of tools that are already callable directly through MCP.

### `src/server.ts`

Each `serveStdio` connection receives a fresh server built by
`createProtocolServer()`. The same factory supports modern MCP 2026-07-28
`server/discover` negotiation and the legacy 2025 `initialize` path.

## Maintaining the catalog

To add a tool:

1. Add one `registerKiCadTool` call in the appropriate category module.
2. Add or reuse the corresponding Python command route.
3. Set accurate schemas and safety annotations.
4. Add focused behavior tests.
5. Run the live catalog and backend parity tests.

Do not add a name to a separate router list. Do not add a generic dispatcher
to bypass first-class schemas.

## Verification

`tests-ts/protocol-contract.test.ts` verifies modern and legacy negotiation,
deterministic tool listing, registry parity, cache hints, annotations, output
schemas, and structured results. `tests/test_ts_tool_registry.py` verifies
unique registrations and Python command-route coverage.

See [Tool Discovery Guide](mcp-router-guide.md) for client usage and
[Tool Inventory](TOOL_INVENTORY.md) for category counts.
