import { afterEach, describe, expect, it, vi } from "vitest";
import { fileURLToPath } from "node:url";
import { KiCADMcpServer } from "../src/server.js";

const pythonBridge = fileURLToPath(new URL("../python/kicad_interface.py", import.meta.url));

afterEach(() => {
  vi.useRealTimers();
});

describe("Python bridge response correlation", () => {
  it("discards a late response and resolves only the matching request", () => {
    vi.useFakeTimers();
    const server = new KiCADMcpServer(pythonBridge, "error") as any;
    const resolve = vi.fn();
    const timeoutHandle = setTimeout(() => undefined, 30_000);

    server.processingRequest = true;
    server.currentRequestHandler = {
      requestId: 2,
      resolve,
      reject: vi.fn(),
      timeoutHandle,
    };
    server.responseBuffer =
      `${JSON.stringify({ success: true, value: "stale", _requestId: 1 })}\n` +
      `${JSON.stringify({ success: true, value: "current", _requestId: 2 })}\n`;

    server.tryParseResponse();

    expect(resolve).toHaveBeenCalledOnce();
    expect(resolve).toHaveBeenCalledWith({ success: true, value: "current" });
    expect(server.currentRequestHandler).toBeNull();
    expect(server.processingRequest).toBe(false);
    expect(server.responseBuffer).toBe("");
  });

  it("waits for a complete newline-delimited response", () => {
    vi.useFakeTimers();
    const server = new KiCADMcpServer(pythonBridge, "error") as any;
    const resolve = vi.fn();

    server.processingRequest = true;
    server.currentRequestHandler = {
      requestId: 7,
      resolve,
      reject: vi.fn(),
      timeoutHandle: setTimeout(() => undefined, 30_000),
    };

    server.handlePythonResponse(Buffer.from('{"success":true,"_request'));
    expect(resolve).not.toHaveBeenCalled();

    server.handlePythonResponse(Buffer.from('Id":7}\n'));
    expect(resolve).toHaveBeenCalledWith({ success: true });
  });
});
