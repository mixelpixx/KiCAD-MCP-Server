import { once } from "node:events";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { KiCADMcpServer } from "../src/server.js";

describe("Python worker recovery", () => {
  it("restarts an exited worker and resumes queued requests", async () => {
    const directory = mkdtempSync(join(tmpdir(), "kicad-mcp-worker-"));
    const scriptPath = join(directory, "worker.mjs");
    writeFileSync(
      scriptPath,
      `process.stdout.write(JSON.stringify({ type: "ready" }) + "\\n");
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
    process.stdout.write(JSON.stringify({ success: true, command: request.command, pid: process.pid, _requestId: request.requestId }) + "\\n");
  }
});
`,
    );

    const server = new KiCADMcpServer(scriptPath, "error");
    const bridge = server as any;

    try {
      bridge.pythonExecutable = process.execPath;
      bridge.pythonEnv = { ...process.env };
      bridge.spawnPythonProcess();
      await bridge.waitForReady(5_000);

      const before = await bridge.callKicadScript("before", {});
      const exited = once(bridge.pythonProcess, "exit");
      bridge.pythonProcess.kill();
      await exited;

      const after = await bridge.callKicadScript("after", {});
      expect(after.success).toBe(true);
      expect(after.pid).not.toBe(before.pid);
    } finally {
      await server.stop();
      rmSync(directory, { recursive: true, force: true });
    }
  });
});
