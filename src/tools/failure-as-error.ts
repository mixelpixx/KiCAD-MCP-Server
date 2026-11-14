/**
 * Mark a tool reply as an MCP error when the KiCad backend reports failure.
 *
 * Most tool handlers return the backend's JSON verbatim:
 * `{ content: [{ type: "text", text: JSON.stringify(result) }] }`. When the
 * backend says `{"success": false, ...}`, that reply still went out with
 * `isError` unset, so a client (and an agent driving it) saw a normal result
 * and carried on. Only the design-rule tools used `formatKicadResult`, which
 * sets the flag.
 *
 * Rather than edit ~150 handlers, this wraps every registration once. A reply
 * whose first text block is a JSON object with `success === false` gets
 * `isError: true`. Everything else, including replies that already set
 * `isError` and non-JSON or non-text content, passes through unchanged.
 *
 * A partial success is not an error. The batch tools (`batch_add_components`,
 * `batch_connect`, `connect_passthrough`, `backannotate_footprints`,
 * `batch_list_symbol_pins`, ...) answer `success: false` when some items
 * failed and the rest were written. Flagging that reply would tell an agent
 * the call did nothing, and retrying the whole batch would add the written
 * components and wires a second time. So a reply that reports applied work
 * (an added / connected / updated count above zero, or a non-empty list of
 * applied items) stays unflagged, and `isError` keeps meaning "nothing
 * happened, safe to retry".
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

type Reply = { content?: Array<{ type?: string; text?: unknown }>; isError?: boolean };

/**
 * Top-level fields that report work the backend applied before it answered
 * `success: false`. Counts of inputs (`boardFootprintCount`, `checked`) and
 * of failures (`errors`, `failed`, `error_count`) are deliberately not here.
 */
const APPLIED_WORK_FIELDS = [
  "added",
  "added_count",
  "connected",
  "connected_count",
  "updated",
  "updated_count",
  "placed",
  "applied",
  "applied_count",
  "updatedFiles",
  "symbols",
];

/** True when a parsed `success: false` reply says some of the work was applied. */
export function reportsAppliedWork(parsed: Record<string, unknown>): boolean {
  for (const field of APPLIED_WORK_FIELDS) {
    const value = parsed[field];
    if (typeof value === "number" && value > 0) return true;
    if (Array.isArray(value) && value.length > 0) return true;
    if (typeof value === "object" && value !== null && !Array.isArray(value)) {
      if (Object.keys(value).length > 0) return true;
    }
  }
  return false;
}

/**
 * True when `reply`'s first text block is a JSON object reporting
 * `success: false` and no applied work.
 */
export function reportsFailure(reply: unknown): boolean {
  if (typeof reply !== "object" || reply === null) return false;
  const first = (reply as Reply).content?.[0];
  if (first?.type !== "text" || typeof first.text !== "string") return false;
  // Cheap pre-check: most replies are successes, some are large (board views).
  if (!/"success"\s*:\s*false/.test(first.text)) return false;
  try {
    const parsed: unknown = JSON.parse(first.text);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return false;
    const record = parsed as Record<string, unknown>;
    return record.success === false && !reportsAppliedWork(record);
  } catch {
    return false;
  }
}

/** Set `isError` on a reply that reports backend failure; return it unchanged otherwise. */
export function flagFailure<T>(reply: T): T {
  if (reportsFailure(reply) && (reply as Reply).isError !== true) {
    return { ...(reply as object), isError: true } as T;
  }
  return reply;
}

/**
 * Wrap `server.tool` and `server.registerTool` so every handler registered
 * afterwards has its reply passed through `flagFailure`. Call before any tool
 * is registered. The handler is always the last argument for both methods.
 */
export function flagBackendFailuresAsErrors(server: McpServer): void {
  const target = server as unknown as Record<string, unknown>;
  for (const method of ["tool", "registerTool"]) {
    const original = target[method];
    if (typeof original !== "function") continue;
    target[method] = (...args: unknown[]) => {
      const last = args.length - 1;
      const handler = args[last];
      if (typeof handler === "function") {
        args[last] = async (...callArgs: unknown[]) =>
          flagFailure(await (handler as (...a: unknown[]) => unknown)(...callArgs));
      }
      return (original as (...a: unknown[]) => unknown).apply(server, args);
    };
  }
}
