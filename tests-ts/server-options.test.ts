import { resolve } from "node:path";
import type { ChildProcess } from "node:child_process";
import { describe, expect, it, vi } from "vitest";
import { commandTimeoutMs, KiCADMcpServer } from "../src/server.js";

describe("KiCad command timeout policy", () => {
  it("gives the live autoroute command the long-running budget", () => {
    expect(commandTimeoutMs("autoroute")).toBe(1_800_000);
    expect(commandTimeoutMs("export_3d_cli")).toBe(600_000);
    expect(commandTimeoutMs("download_jlcpcb_database")).toBe(3_600_000);
    expect(commandTimeoutMs("run_freerouting")).toBe(30_000);
  });

  it("keeps ordinary commands on the bounded default timeout", () => {
    expect(commandTimeoutMs("get_board_info")).toBe(30_000);
  });
});

describe("KiCad backend warm-up", () => {
  function warmupHarness(result: Promise<unknown>) {
    const server = new KiCADMcpServer(resolve("python/kicad_interface.py"), "error");
    const execute = vi.fn(() => result);
    const internals = server as unknown as {
      pythonProcess: ChildProcess;
      bridge: { execute: typeof execute };
      runWarmup(timeoutMs: number): Promise<boolean>;
    };
    internals.pythonProcess = { stdin: {} } as ChildProcess;
    internals.bridge = { execute };
    return { execute, run: () => internals.runWarmup(1234) };
  }

  it("treats a response-level failure as a completed transport exchange", async () => {
    const harness = warmupHarness(Promise.resolve({ success: false, message: "IPC only" }));

    await expect(harness.run()).resolves.toBe(true);
    expect(harness.execute).toHaveBeenCalledWith("_warmup", {}, 1234);
  });

  it("does not report a rejected warm-up command as ready", async () => {
    const harness = warmupHarness(Promise.reject(new Error("timed out")));

    await expect(harness.run()).resolves.toBe(false);
  });
});
