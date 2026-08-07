# MCP 2026-07-28 Migration

This server supports both MCP eras over the existing STDIO entrypoint:

- Modern clients can negotiate `2026-07-28` with `server/discover`.
- Existing clients can continue using the legacy `initialize` / `initialized`
  exchange and negotiate `2025-11-25`.

No client configuration path or command needs to change. The protocol era is
selected per connection by the TypeScript SDK v2 STDIO server factory.

## What changed

- `@modelcontextprotocol/sdk` v1 was replaced by the split
  `@modelcontextprotocol/server` v2 package.
- Tool, prompt, and resource registration uses the SDK v2 APIs and Zod 4.
- Modern list and resource results include `ttlMs` and `cacheScope` hints.
- A fresh `McpServer` is created after the connection's protocol era is known.
- Project-bound tools advertise an optional `projectHandle` argument.
- The Node/Python bridge correlates every request and response so a late result
  from a timed-out operation cannot be delivered to the next MCP call.
- The historical `dist/kicad-server.js` executable delegates to the canonical
  entry point instead of publishing a second, divergent server implementation.

This server does not use sampling, roots, elicitation, or the deprecated
HTTP+SSE transport, so no Multi Round-Trip Request conversion was required.
The current transport remains local STDIO; HTTP routing and authorization
changes therefore do not affect this installation.

## Project state

MCP 2026 removes protocol-level sessions, but it explicitly permits an
application to carry state through tool-visible handles. KiCad's Python APIs
still hold one loaded board in memory, so open/create operations now mint an
opaque, process-local handle:

```json
{
  "success": true,
  "projectPath": "C:/boards/demo/demo.kicad_pcb",
  "projectHandle": "kicad-project:..."
}
```

Modern clients should return that handle on later project-bound calls:

```json
{
  "projectHandle": "kicad-project:...",
  "force": false
}
```

The server serializes project-bound operations, validates and removes the
handle, then keeps the project lock until the Python operation finishes. A
stale or incorrect handle therefore fails before touching KiCad even when a
project switch was queued concurrently. `close_project` invalidates the
current handle. Omitting the handle keeps the old implicit-current-project
behavior for existing clients.

Handles are deliberately local to the running process. They prevent a stale
client from silently operating on a different loaded board; they are not a
persistent project identifier and do not survive a server restart.

## Cache policy

| Response                                      |        TTL | Scope   |
| --------------------------------------------- | ---------: | ------- |
| Discovery, tools, prompts, resource templates |  5 minutes | Private |
| Resource list                                 |  5 seconds | Private |
| Resource read                                 | Not cached | Private |

The catalogues are stable during a process lifetime. Project resources can
change after every KiCad operation, so their caching is intentionally short or
disabled.

## Verification

Run the regular test suites, then exercise both wire protocols:

```powershell
npm test
npm run test:protocol
```

`test:protocol` starts the built server twice through the official v2 client:
once in default legacy mode and once pinned to `2026-07-28`. It verifies the
negotiated era, full tool catalogue, `projectHandle` schema, and modern cache
hints. It expects the repository-local `.venv` created with KiCad's Python.
CI runs the same test with a hermetic Python fixture; local runs use the real
KiCad backend by default and additionally exercise project-handle lifecycle.
