# Tool Discovery Quick Start

KiCAD MCP exposes every operation as a first-class MCP tool. Most clients can
select and call tools directly from `tools/list`. Three optional discovery
tools make the catalog easier to browse.

At the v2.7.0 migration baseline, the catalog contains 216 KiCad capabilities
across 20 categories plus three discovery tools.

## Search by task

Call `search_tools` with a short keyword:

```json
{ "query": "gerber" }
```

The response contains matching first-class tool names and categories. Read the
selected definition from `tools/list`, then call that tool directly.

## Browse categories

Call `list_tool_categories` with no arguments to see the capability categories.
Then inspect one category:

```json
{ "category": "export" }
```

Pass that object to `get_category_tools`. Every returned name remains directly
callable through MCP.

## Execute the selected operation

If discovery returns `export_gerber`, call `export_gerber` itself with the
arguments in its input schema. There is no `execute_tool` wrapper.

For example, a client may search for `gerber`, inspect the published
`export_gerber` schema, then call it with an output directory. The same flow
works for board geometry, DRC, schematic authoring, part sourcing, and every
other category.

## What clients receive

- Individual input and output schemas for every tool
- Safety annotations for read-only and destructive operations
- A deterministic, publicly cacheable `tools/list` result on MCP 2026-07-28
- Supplemental keyword search and category browsing
- Legacy 2025 client support through the SDK v2 `serveStdio` compatibility path

The discovery catalog is not a gate and does not reduce client context. The
historical `execute_tool` design was removed because clients could invent
schemas they had not seen.

For implementation details, see
[Tool Discovery Architecture](ROUTER_ARCHITECTURE.md).
