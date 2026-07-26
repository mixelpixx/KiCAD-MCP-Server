import { describe, it, expect } from "vitest";
import {
  computeCommandTimeout,
  DEFAULT_COMMAND_TIMEOUT_MS,
  LONG_COMMAND_TIMEOUT_MS,
  LONG_RUNNING_COMMANDS,
  AUTOROUTE_OVERHEAD_MS,
} from "../src/command-timeout.js";

describe("computeCommandTimeout", () => {
  it("gives ordinary commands the short default", () => {
    expect(computeCommandTimeout("get_board_info", {})).toBe(DEFAULT_COMMAND_TIMEOUT_MS);
    expect(computeCommandTimeout("place_component", { x: 1 })).toBe(DEFAULT_COMMAND_TIMEOUT_MS);
  });

  it("gives size-bound commands the blanket long allowance", () => {
    for (const command of LONG_RUNNING_COMMANDS) {
      expect(computeCommandTimeout(command, {})).toBe(LONG_COMMAND_TIMEOUT_MS);
    }
  });

  describe("autoroute (issue #251)", () => {
    it("is never left on the 30s default", () => {
      // The regression itself: autoroute was absent from the long-running list,
      // so Node abandoned the call while Freerouting was still routing and a
      // valid .ses had been written.
      const timeout = computeCommandTimeout("autoroute", {});
      expect(timeout).toBeGreaterThan(DEFAULT_COMMAND_TIMEOUT_MS);
      expect(timeout).toBeGreaterThanOrEqual(LONG_COMMAND_TIMEOUT_MS);
    });

    it("covers the caller's own per-attempt budget plus overhead", () => {
      // 900s per attempt is well past the blanket 600s ceiling.
      expect(computeCommandTimeout("autoroute", { timeout: 900 })).toBe(
        900 * 1000 + AUTOROUTE_OVERHEAD_MS,
      );
    });

    it("multiplies the budget by attempts for best-of-N", () => {
      // Python runs `attempts` sequential passes of `timeout` seconds each.
      expect(computeCommandTimeout("autoroute", { timeout: 300, attempts: 5 })).toBe(
        300 * 1000 * 5 + AUTOROUTE_OVERHEAD_MS,
      );
    });

    it("still waits at least the blanket allowance for small budgets", () => {
      expect(computeCommandTimeout("autoroute", { timeout: 10 })).toBe(LONG_COMMAND_TIMEOUT_MS);
    });

    it("falls back to the 300s default when timeout is absent or nonsense", () => {
      const expected = 300 * 1000 * 3 + AUTOROUTE_OVERHEAD_MS;
      for (const bad of [undefined, null, 0, -5, NaN, "abc", {}]) {
        expect(computeCommandTimeout("autoroute", { timeout: bad, attempts: 3 })).toBe(expected);
      }
    });

    it("accepts numeric strings, since MCP clients stringify params", () => {
      expect(computeCommandTimeout("autoroute", { timeout: "900" })).toBe(
        900 * 1000 + AUTOROUTE_OVERHEAD_MS,
      );
    });

    it("treats bad attempts values as a single attempt", () => {
      const single = computeCommandTimeout("autoroute", { timeout: 900, attempts: 1 });
      for (const bad of [undefined, 0, -3, NaN, "xyz"]) {
        expect(computeCommandTimeout("autoroute", { timeout: 900, attempts: bad })).toBe(single);
      }
    });

    it("floors fractional attempts rather than inflating the budget", () => {
      expect(computeCommandTimeout("autoroute", { timeout: 900, attempts: 2.9 })).toBe(
        computeCommandTimeout("autoroute", { timeout: 900, attempts: 2 }),
      );
    });

    it("tolerates a missing params object", () => {
      expect(computeCommandTimeout("autoroute")).toBe(LONG_COMMAND_TIMEOUT_MS);
    });
  });
});
