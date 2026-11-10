import { describe, it, expect } from "vitest";
import {
  computeCommandTimeout,
  DEFAULT_COMMAND_TIMEOUT_MS,
  LONG_COMMAND_TIMEOUT_MS,
  LONG_RUNNING_COMMANDS,
  AUTOROUTE_OVERHEAD_MS,
  JLCPCB_DOWNLOAD_TIMEOUT_MS,
} from "../src/command-timeout.js";

describe("computeCommandTimeout", () => {
  it("gives the JLCPCB catalog download an hour (#454)", () => {
    // Under the 30 s default the worker was restarted mid-download.
    expect(computeCommandTimeout("download_jlcpcb_database", {})).toBe(JLCPCB_DOWNLOAD_TIMEOUT_MS);
    expect(JLCPCB_DOWNLOAD_TIMEOUT_MS).toBeGreaterThan(LONG_COMMAND_TIMEOUT_MS);
  });

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

describe("schematic batch and board-creation commands", () => {
  it("get the long allowance", () => {
    // One STM32 symbol took longer than the 30 s default to place, and a
    // batch abandoned mid-write left a .kicad_sch that no longer loaded.
    for (const cmd of [
      "batch_add_components",
      "batch_connect",
      "batch_add_and_connect",
      "batch_add_no_connects",
      "batch_edit_schematic_components",
      "create_board_from_schematic",
      "run_erc",
    ]) {
      expect(computeCommandTimeout(cmd, {}, {})).toBe(LONG_COMMAND_TIMEOUT_MS);
    }
  });
});

describe("KICAD_MCP_COMMAND_TIMEOUT_MS", () => {
  it("raises the floor for every command", () => {
    const env = { KICAD_MCP_COMMAND_TIMEOUT_MS: "120000" };
    expect(computeCommandTimeout("get_board_info", {}, env)).toBe(120_000);
  });

  it("never shortens a longer policy timeout", () => {
    const env = { KICAD_MCP_COMMAND_TIMEOUT_MS: "1000" };
    expect(computeCommandTimeout("get_board_info", {}, env)).toBe(DEFAULT_COMMAND_TIMEOUT_MS);
    expect(computeCommandTimeout("run_drc", {}, env)).toBe(LONG_COMMAND_TIMEOUT_MS);
  });

  it("ignores values that are not positive numbers", () => {
    for (const bad of ["", "abc", "-5", "0"]) {
      const env = { KICAD_MCP_COMMAND_TIMEOUT_MS: bad };
      expect(computeCommandTimeout("get_board_info", {}, env)).toBe(DEFAULT_COMMAND_TIMEOUT_MS);
    }
  });
});
