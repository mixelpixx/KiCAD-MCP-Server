import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { KiCADMcpServer } from "../src/server.js";

/**
 * A stand-in for python/kicad_interface.py: prints the READY marker, answers
 * every request with its pid, and misbehaves on demand.
 *
 *   command "hang"            never answered (timeout path)
 *   command "die"             process.exit(1) without answering (exit mid-request)
 *   FAKE_WORKER_MODE
 *     exit-before-ready       exits with code 3 before printing READY
 *     exit-after-ready-once   the first life exits 30 ms after READY; later lives serve
 *     exit-after-ready-always every life exits 30 ms after READY (crash loop)
 *
 * FAKE_WORKER_LIVES names a file the worker increments at start-up, so a test
 * can count how many times it was spawned.
 */
const FAKE_WORKER = `
const fs = require("node:fs");
const mode = process.env.FAKE_WORKER_MODE || "";
const livesFile = process.env.FAKE_WORKER_LIVES;
let lives = 1;
if (livesFile) {
  try { lives = Number(fs.readFileSync(livesFile, "utf8")) + 1; } catch {}
  fs.writeFileSync(livesFile, String(lives));
}
if (mode === "exit-before-ready") process.exit(3);
process.stdout.write(JSON.stringify({ type: "ready" }) + "\\n");
if (mode === "exit-after-ready-always" || (mode === "exit-after-ready-once" && lives === 1)) {
  setTimeout(() => process.exit(2), 30);
}
let buffer = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  buffer += chunk;
  while (buffer.includes("\\n")) {
    const index = buffer.indexOf("\\n");
    const line = buffer.slice(0, index);
    buffer = buffer.slice(index + 1);
    if (!line.trim()) continue;
    const request = JSON.parse(line);
    if (request.command === "hang") continue;
    if (request.command === "die") process.exit(1);
    process.stdout.write(JSON.stringify({ success: true, command: request.command, pid: process.pid, _requestId: request.requestId }) + "\\n");
  }
});
`;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitUntil(condition: () => boolean, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!condition()) {
    if (Date.now() > deadline) throw new Error("condition not met in time");
    await sleep(20);
  }
}

describe("Python worker recovery", () => {
  let directory: string;
  let server: KiCADMcpServer;
  let bridge: any;
  let livesFile: string;

  function setUp(mode = ""): void {
    directory = mkdtempSync(join(tmpdir(), "kicad-mcp-worker-"));
    const scriptPath = join(directory, "worker.cjs");
    writeFileSync(scriptPath, FAKE_WORKER);
    livesFile = join(directory, "lives");

    server = new KiCADMcpServer(scriptPath, "error");
    bridge = server as any;
    bridge.pythonExecutable = process.execPath;
    bridge.pythonEnv = { ...process.env, FAKE_WORKER_MODE: mode, FAKE_WORKER_LIVES: livesFile };
  }

  const lives = () => Number(readFileSync(livesFile, "utf8"));

  afterEach(async () => {
    await server.stop();
    rmSync(directory, { recursive: true, force: true });
  });

  it("restarts a timed-out worker and resumes queued requests", async () => {
    setUp();
    bridge.spawnPythonProcess();
    await bridge.waitForReady(5_000);

    const before = await bridge.callKicadScript("before", {});
    const timedOut = new Promise((resolve, reject) => {
      bridge.requestQueue.push({
        request: {
          command: "hang",
          params: {},
          timeout: 25,
          requestId: bridge.allocateInternalRequestId(),
        },
        resolve,
        reject,
      });
      bridge.processNextRequest();
    });
    await expect(timedOut).rejects.toThrow("Command timeout");

    const after = await bridge.callKicadScript("after", {});
    expect(after.success).toBe(true);
    expect(after.pid).not.toBe(before.pid);
  });

  it("rejects the in-flight request when the worker dies mid-request and serves the next one", async () => {
    setUp();
    bridge.spawnPythonProcess();
    await bridge.waitForReady(5_000);

    const before = await bridge.callKicadScript("before", {});
    await expect(bridge.callKicadScript("die", {})).rejects.toThrow(
      "Python process exited with code 1",
    );

    const after = await bridge.callKicadScript("after", {});
    expect(after.success).toBe(true);
    expect(after.pid).not.toBe(before.pid);
    expect(lives()).toBe(2);
  });

  it("restarts a worker that exits while idle, queuing calls until the replacement is ready", async () => {
    setUp("exit-after-ready-once");
    bridge.spawnPythonProcess();
    await bridge.waitForReady(5_000);
    const first = bridge.pythonProcess;

    await new Promise((resolve) => first.once("exit", resolve));
    // The call lands while the replacement is still starting up.
    const after = await bridge.callKicadScript("after", {});
    expect(after.success).toBe(true);
    expect(after.pid).not.toBe(first.pid);
    expect(lives()).toBe(2);
  });

  it("does not spawn a replacement when the worker dies before its first READY", async () => {
    setUp("exit-before-ready");
    bridge.spawnPythonProcess();
    await expect(bridge.waitForReady(5_000)).rejects.toThrow("Python process exited with code 3");

    await sleep(250);
    expect(bridge.pythonProcess).toBeNull();
    expect(bridge.restartPromise).toBeNull();
    expect(lives()).toBe(1);
  });

  it("gives up after three restarts in the window instead of crash-looping", async () => {
    setUp("exit-after-ready-always");
    bridge.spawnPythonProcess();
    await bridge.waitForReady(5_000);

    // One initial life plus MAX_RESTARTS_PER_WINDOW replacements.
    await waitUntil(
      () => lives() >= 4 && bridge.pythonProcess === null && bridge.restartPromise === null,
      10_000,
    );
    await sleep(250);
    expect(lives()).toBe(4);
    await expect(bridge.callKicadScript("after", {})).rejects.toThrow(
      "Python process for KiCAD scripting is not running",
    );
  }, 15_000);
});
