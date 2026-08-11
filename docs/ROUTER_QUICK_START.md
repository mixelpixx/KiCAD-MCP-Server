# Tool Discovery Quick Start

KiCAD MCP exposes all 183 tools as first-class MCP tools. Most clients can
select and call them directly from `tools/list`. Three optional discovery
tools make the catalog easier to browse.

## Search by task

Call `search_tools` with a short keyword:

```json
{ "query": "gerber" }
```

The response contains matching first-class tool names and categories. Read the
selected definition from `tools/list`, then call that tool directly.

## Browse categories

Call `list_tool_categories` with no arguments to see the 18 KiCad capability
categories. Then inspect one category:

```json
{ "category": "export" }
```

Pass that object to `get_category_tools`. Every returned name remains directly
callable through MCP.

## Execute the selected operation

If discovery returns `export_gerber`, call `export_gerber` itself with the
arguments in its input schema. There is no `execute_tool` wrapper.

## What clients receive

- 180 KiCad capability tools
- 3 supplemental discovery tools
- Individual input and output schemas
- Safety annotations for read-only and destructive operations
- A deterministic, publicly cacheable `tools/list` result on MCP 2026-07-28

The server also supports legacy 2025 clients through the SDK v2 `serveStdio`
compatibility path.

For implementation details, see [Tool Discovery Architecture](ROUTER_ARCHITECTURE.md).
