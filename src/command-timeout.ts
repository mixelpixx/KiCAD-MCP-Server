/**
 * Per-command timeout policy for the Python worker bridge.
 *
 * Kept as a pure function so the policy is unit-testable without spawning a
 * worker — the same reason `tools/registry.ts` and `tools/tool-response.ts`
 * are separated out.
 */

/** Fallback for commands that should answer promptly. */
export const DEFAULT_COMMAND_TIMEOUT_MS = 30_000;

/** Blanket allowance for operations that are slow but not caller-tunable. */
export const LONG_COMMAND_TIMEOUT_MS = 600_000;

/**
 * Commands whose cost scales with the size of the thing being worked on rather
 * than with a parameter the caller can reason about up front.
 *
 * `digikey_check_library_availability` is here for a different reason to the
 * rest: it issues one or two rate-limited HTTP requests per symbol and
 * self-throttles between them, so even its reduced default of 25 symbols cannot
 * finish inside `DEFAULT_COMMAND_TIMEOUT_MS` once network latency is included.
 * Since #382 a late response is discarded by request id rather than mis-delivered
 * to the next call, so the cost of timing out is now confined to this command —
 * but it is still the whole sweep's results, every one of them already paid for
 * against the caller's rate limit.
 */
export const LONG_RUNNING_COMMANDS = [
  "run_drc",
  "export_gerber",
  "export_pdf",
  "export_3d",
  "sync_schematic_to_board",
  "list_schematic_nets",
  "list_schematic_labels",
  "get_schematic_view",
  "digikey_check_library_availability",
] as const;

/**
 * Extra wall-clock granted to `autoroute` on top of the routing budget the
 * caller asked for, covering DSN export, JVM start-up per attempt, SES import
 * and the board save.
 */
export const AUTOROUTE_OVERHEAD_MS = 120_000;

/**
 * How long the Node side waits for `command` before abandoning the request.
 *
 * `autoroute` is computed rather than fixed: its Python side takes a
 * per-attempt `timeout` (seconds, default 300) and repeats it `attempts` times
 * for best-of-N, so a flat ceiling would still cut off a caller who legitimately
 * raised either. Under-waiting here is what issue #251 reports — the Node
 * default fired at 30 s while Freerouting was still working, so the tool
 * reported failure even though a valid .ses had been written.
 */
export function computeCommandTimeout(command: string, params?: unknown): number {
  if (command === "autoroute") {
    const p = (params ?? {}) as Record<string, unknown>;

    const perAttemptSec = toPositiveNumber(p.timeout) ?? 300;
    const attempts = Math.max(1, Math.floor(toPositiveNumber(p.attempts) ?? 1));

    const budgetMs = perAttemptSec * 1000 * attempts + AUTOROUTE_OVERHEAD_MS;
    // Never drop below the blanket long-running allowance.
    return Math.max(budgetMs, LONG_COMMAND_TIMEOUT_MS);
  }

  if ((LONG_RUNNING_COMMANDS as readonly string[]).includes(command)) {
    return LONG_COMMAND_TIMEOUT_MS;
  }

  return DEFAULT_COMMAND_TIMEOUT_MS;
}

/** Finite, positive numbers only; anything else falls back to the default. */
function toPositiveNumber(value: unknown): number | undefined {
  const n = typeof value === "string" ? Number(value) : value;
  if (typeof n !== "number" || !Number.isFinite(n) || n <= 0) return undefined;
  return n;
}
