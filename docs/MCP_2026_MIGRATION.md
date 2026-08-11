# MCP 2026-07-28 migration

This server uses `@modelcontextprotocol/server` 2.0 and Zod 4. Production stdio is created with `serveStdio(() => createProtocolServer())`; connecting `McpServer` directly to the legacy stdio transport would not enable modern protocol negotiation.

## Implemented

| 2026-07-28 capability     | KiCad server implementation                                                                                                                                                                                                |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Stateless protocol core   | Modern requests are served without `initialize` or an MCP session ID. The SDK's legacy 2025 path remains enabled for existing clients.                                                                                     |
| Optional discovery        | `server/discover` is available and covered by a protocol contract test.                                                                                                                                                    |
| Cacheable lists           | Tool, prompt, resource, and resource-template lists have deterministic order plus explicit `ttlMs` and `cacheScope` hints. Live project reads are private and non-cacheable; library reads have a short public cache hint. |
| Multi Round-Trip Requests | Destructive tools return `input_required` and accept a signed, tool-and-arguments-bound, schema-validated confirmation on retry.                                                                                           |
| Structured tools          | Every tool has an output schema, structured content, explicit annotations, protocol error signaling, and request cancellation propagation.                                                                                 |
| Application state         | The local Python worker owns one explicit KiCad project context. This is application state, not hidden MCP transport-session state, and is appropriate for the single-client local stdio deployment.                       |
| Compatibility             | Contract tests cover native 2026-07-28 negotiation and legacy 2025 initialization through the same entrypoint.                                                                                                             |

The Node-to-Python protocol is private newline-delimited JSON, not a second MCP implementation. Every request has a UUID `requestId`; timed-out, cancelled, late, or out-of-order responses cannot be delivered to another tool call.

## Deliberately not advertised

- HTTP `Mcp-Method`/`Mcp-Name` routing and the 2026 authorization changes do not apply to this local stdio transport. They belong in a separately secured remote HTTP deployment.
- `io.modelcontextprotocol/tasks` is not advertised. `@modelcontextprotocol/server` 2.0 exposes no supported Tasks extension runtime, and hand-registering its methods would bypass protocol-era validation. Long-running tools remain synchronous with explicit extended timeouts until the official SDK supplies an extension API.
- MCP Apps are not advertised because the server has no `ui://` resource or sandboxed app document.
- Enterprise Managed Authorization is not advertised because stdio has no HTTP bearer authorization context.
- Deprecated Roots, Sampling, Logging, HTTP+SSE, and Dynamic Client Registration were not added during the migration.

The strongest future Tasks candidates are `download_jlcpcb_database`, `autoroute`, and long-running 3D exports. A safe implementation must add durable task state, caller binding, expiry, cooperative subprocess cancellation, project serialization, and protocol contract tests before declaring the extension.

## Verification

```text
npm run build
npm run lint:ts
npm run test:ts
python -m pytest tests/
```

References: [2026-07-28 release article](https://blog.modelcontextprotocol.io/posts/2026-07-28/), [specification](https://modelcontextprotocol.io/specification/2026-07-28), and [Tasks extension](https://modelcontextprotocol.io/extensions/tasks/overview).
