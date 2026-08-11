import { describe, expect, it, vi } from "vitest";
import { PythonCommandBridge, type PythonCommandRequest } from "../src/python-bridge.js";

function createHarness() {
  const writes: PythonCommandRequest[] = [];
  const onDrainTimeout = vi.fn();
  const bridge = new PythonCommandBridge({
    writeRequest: (request) => writes.push(request),
    logger: {
      debug: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
    },
    onDrainTimeout,
  });
  return { bridge, writes, onDrainTimeout };
}

describe("PythonCommandBridge", () => {
  it("serializes commands and resolves only the matching response", async () => {
    const { bridge, writes } = createHarness();
    const first = bridge.execute("first", { value: 1 }, 1_000);
    const second = bridge.execute("second", { value: 2 }, 1_000);

    expect(writes).toHaveLength(1);
    bridge.handleChunk(
      `${JSON.stringify({ requestId: writes[0].requestId, success: true, value: 1 })}\n`,
    );
    await expect(first).resolves.toEqual({ success: true, value: 1 });

    expect(writes).toHaveLength(2);
    bridge.handleChunk(
      `${JSON.stringify({ requestId: writes[1].requestId, success: true, value: 2 })}\n`,
    );
    await expect(second).resolves.toEqual({ success: true, value: 2 });
  });

  it("discards a timed-out response instead of resolving the next request", async () => {
    vi.useFakeTimers();
    try {
      const { bridge, writes } = createHarness();
      const first = bridge.execute("slow", {}, 100);
      const second = bridge.execute("next", {}, 1_000);
      const firstRejection = expect(first).rejects.toThrow("timed out");

      await vi.advanceTimersByTimeAsync(101);
      await firstRejection;
      expect(writes).toHaveLength(1);

      bridge.handleChunk(
        `${JSON.stringify({ requestId: writes[0].requestId, success: true, wrong: true })}\n`,
      );
      expect(writes).toHaveLength(2);
      let secondSettled = false;
      void second.finally(() => {
        secondSettled = true;
      });
      await Promise.resolve();
      expect(secondSettled).toBe(false);

      bridge.handleChunk(
        `${JSON.stringify({ requestId: writes[1].requestId, success: true, right: true })}\n`,
      );
      await expect(second).resolves.toEqual({ success: true, right: true });
    } finally {
      vi.useRealTimers();
    }
  });

  it("removes a cancelled queued request", async () => {
    const { bridge, writes } = createHarness();
    const first = bridge.execute("first", {}, 1_000);
    const controller = new AbortController();
    const cancelled = bridge.execute("cancelled", {}, 1_000, controller.signal);
    controller.abort();

    await expect(cancelled).rejects.toMatchObject({ name: "AbortError" });
    bridge.handleChunk(`${JSON.stringify({ requestId: writes[0].requestId, success: true })}\n`);
    await expect(first).resolves.toEqual({ success: true });
    expect(writes).toHaveLength(1);
  });

  it("discards a late response after active cancellation", async () => {
    const { bridge, writes } = createHarness();
    const controller = new AbortController();
    const cancelled = bridge.execute("cancelled", {}, 1_000, controller.signal);
    const next = bridge.execute("next", {}, 1_000);

    controller.abort();
    await expect(cancelled).rejects.toMatchObject({ name: "AbortError" });
    expect(writes).toHaveLength(1);

    bridge.handleChunk(
      `${JSON.stringify({ requestId: writes[0].requestId, success: true, stale: true })}\n`,
    );
    expect(writes).toHaveLength(2);
    bridge.handleChunk(
      `${JSON.stringify({ requestId: writes[1].requestId, success: true, current: true })}\n`,
    );
    await expect(next).resolves.toEqual({ success: true, current: true });
  });

  it("buffers fragmented stdout until a complete response line arrives", async () => {
    const { bridge, writes } = createHarness();
    const result = bridge.execute("fragmented", {}, 1_000);
    const response = JSON.stringify({
      requestId: writes[0].requestId,
      success: true,
      value: "complete",
    });

    bridge.handleChunk(response.slice(0, 12));
    bridge.handleChunk(response.slice(12));
    let settled = false;
    void result.finally(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);

    bridge.handleChunk("\n");
    await expect(result).resolves.toEqual({ success: true, value: "complete" });
  });

  it("rejects active and queued work when the worker exits", async () => {
    const { bridge } = createHarness();
    const first = bridge.execute("first", {}, 1_000);
    const second = bridge.execute("second", {}, 1_000);

    bridge.failAll(new Error("worker exited"));

    await expect(first).rejects.toThrow("worker exited");
    await expect(second).rejects.toThrow("worker exited");
  });

  it("clears a timeout drain barrier when the worker exits", async () => {
    vi.useFakeTimers();
    try {
      const { bridge, writes } = createHarness();
      const expired = bridge.execute("expired", {}, 100);
      const queued = bridge.execute("queued", {}, 1_000);
      const expiredRejection = expect(expired).rejects.toThrow("timed out");

      await vi.advanceTimersByTimeAsync(101);
      await expiredRejection;
      expect(writes).toHaveLength(1);

      bridge.failAll(new Error("worker exited"));
      await expect(queued).rejects.toThrow("worker exited");

      const afterRestart = bridge.execute("after-restart", {}, 1_000);
      expect(writes).toHaveLength(2);
      bridge.handleChunk(`${JSON.stringify({ requestId: writes[1].requestId, success: true })}\n`);
      await expect(afterRestart).resolves.toEqual({ success: true });
    } finally {
      vi.useRealTimers();
    }
  });

  it("requests a worker restart when an expired command never drains", async () => {
    vi.useFakeTimers();
    try {
      const { bridge, writes, onDrainTimeout } = createHarness();
      const expired = bridge.execute("hung", {}, 100);
      const expiredRejection = expect(expired).rejects.toThrow("timed out");

      await vi.advanceTimersByTimeAsync(101);
      await expiredRejection;
      expect(onDrainTimeout).not.toHaveBeenCalled();

      await vi.advanceTimersByTimeAsync(5_000);
      expect(onDrainTimeout).toHaveBeenCalledOnce();
      expect(onDrainTimeout).toHaveBeenCalledWith(writes[0]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not dispatch queued work after drain escalation even if a late response arrives", async () => {
    vi.useFakeTimers();
    try {
      const { bridge, writes, onDrainTimeout } = createHarness();
      const expired = bridge.execute("hung", {}, 100);
      const queued = bridge.execute("must-not-run", {}, 1_000);
      const expiredRejection = expect(expired).rejects.toThrow("timed out");

      await vi.advanceTimersByTimeAsync(101);
      await expiredRejection;
      await vi.advanceTimersByTimeAsync(5_000);
      expect(onDrainTimeout).toHaveBeenCalledOnce();

      bridge.handleChunk(
        `${JSON.stringify({ requestId: writes[0].requestId, success: true, late: true })}\n`,
      );
      expect(writes).toHaveLength(1);

      bridge.failAll(new Error("worker terminated"));
      await expect(queued).rejects.toThrow("worker terminated");
    } finally {
      vi.useRealTimers();
    }
  });
});
