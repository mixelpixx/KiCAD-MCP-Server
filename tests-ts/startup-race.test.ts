import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it } from "vitest";
import { KiCADMcpServer } from "../src/server.js";

const FAKE_WORKER = `
process.stdout.write(JSON.stringify({ type: "ready" }) + "\\n");
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
    process.stdout.write(JSON.stringify({ success: true, command: request.command, _requestId: request.requestId }) + "\\n");
  }
});
`;

// The server connects the MCP transport, then checks that pcbnew imports,
// and only then spawns the worker. A tool call in between used to be rejected
// with "Python process for KiCAD scripting is not running" (#453): supergateway
// sends its first tools/call right after initialize and hit it every time.

let server: KiCADMcpServer;
let directory: string;
const savedPython = process.env.KICAD_PYTHON;
afterEach(async () => {
  await server.stop();
  rmSync(directory, { recursive: true, force: true });
  if (savedPython === undefined) delete process.env.KICAD_PYTHON;
  else process.env.KICAD_PYTHON = savedPython;
});

it("a tool call during start-up validation is queued, not rejected (#453)", async () => {
  directory = mkdtempSync(join(tmpdir(), "kicad-mcp-race-"));
  const scriptPath = join(directory, "worker.cjs");
  writeFileSync(scriptPath, FAKE_WORKER);
  process.env.KICAD_PYTHON = process.execPath;

  server = new KiCADMcpServer(scriptPath, "error");
  const bridge = server as any;
  bridge.server.connect = async () => undefined; // no real stdio transport
  // Stand in for the `python -c "import pcbnew"` check (100-5000 ms in reality).
  bridge.validatePrerequisites = () => new Promise((r) => setTimeout(() => r(true), 200));

  const started = server.start();
  await new Promise((r) => setTimeout(r, 20)); // transport is "connected", worker not yet spawned
  const result = await bridge.callKicadScript("get_backend_state", {});
  expect(result.success).toBe(true);
  await started;
});
