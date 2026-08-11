import {
  isInputRequiredResult,
  type McpServer,
  type ServerContext,
} from "@modelcontextprotocol/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { resetToolRegistryForTests } from "../src/tools/registry.js";
import {
  registerKiCadTool,
  toolAnnotationsFor,
  toolConfirmationStateCodec,
  type CommandFunction,
  withToolSignal,
} from "../src/tools/tool-registration.js";

interface CapturedTool {
  name: string;
  config: Record<string, unknown>;
  callback: (args: unknown, ctx: ServerContext) => Promise<any>;
}

function captureServer(): { server: McpServer; tools: CapturedTool[] } {
  const tools: CapturedTool[] = [];
  const server = {
    registerTool: vi.fn((name, config, callback) => {
      tools.push({ name, config, callback });
      return {};
    }),
  } as unknown as McpServer;
  return { server, tools };
}

function context(
  signal: AbortSignal,
  inputResponses?: Record<string, unknown>,
  requestState?: unknown,
): ServerContext {
  return {
    mcpReq: {
      id: 1,
      method: "tools/call",
      signal,
      inputResponses,
      requestState: <T>() => requestState as T | undefined,
    },
  } as unknown as ServerContext;
}

describe("KiCad MCP v2 tool registration adapter", () => {
  beforeEach(() => resetToolRegistryForTests());

  it("marks network-backed database downloads as destructive and open-world", () => {
    expect(toolAnnotationsFor("download_jlcpcb_database")).toMatchObject({
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: true,
    });
  });

  it("adds a default output schema and parses any JSON root without replacing content blocks", async () => {
    const { server, tools } = captureServer();
    const image = { type: "image" as const, data: "AA==", mimeType: "image/png" };

    registerKiCadTool(server, "test", "array_result", { inputSchema: z.object({}) }, async () => ({
      content: [image, { type: "text" as const, text: "[1,2,3]" }],
    }));

    expect(tools[0].config.outputSchema).toBeDefined();
    const result = await tools[0].callback({}, context(new AbortController().signal));
    expect(result.structuredContent).toEqual([1, 2, 3]);
    expect(result.content).toEqual([image, { type: "text", text: "[1,2,3]" }]);
  });

  it("preserves explicit output data, forwards cancellation, and marks raw backend failures", async () => {
    const { server, tools } = captureServer();
    const explicitSchema = z.boolean();
    const backend = vi.fn<CommandFunction>(async () => ({ success: false, message: "denied" }));
    const callBackend = withToolSignal(backend);

    registerKiCadTool(
      server,
      "test",
      "backend_failure",
      { inputSchema: z.object({}), outputSchema: explicitSchema },
      async () => {
        const response = await callBackend("failing_command", {});
        return {
          content: [{ type: "text" as const, text: `Failed: ${response.message}` }],
          structuredContent: false,
        };
      },
    );

    const controller = new AbortController();
    const result = await tools[0].callback({}, context(controller.signal));
    expect(tools[0].config.outputSchema).toBe(explicitSchema);
    expect(backend).toHaveBeenCalledWith("failing_command", {}, controller.signal);
    expect(result.structuredContent).toBe(false);
    expect(result.content).toEqual([{ type: "text", text: "Failed: denied" }]);
    expect(result.isError).toBe(true);
  });

  it("requires validated MRTR confirmation only for destructive tools", async () => {
    const { server, tools } = captureServer();
    const destructiveHandler = vi.fn(async () => ({
      content: [{ type: "text" as const, text: '{"success":true}' }],
    }));
    const readHandler = vi.fn(async () => ({
      content: [{ type: "text" as const, text: '{"success":true}' }],
    }));

    registerKiCadTool(
      server,
      "component",
      "delete_component",
      { inputSchema: z.object({ reference: z.string() }) },
      destructiveHandler,
    );
    registerKiCadTool(
      server,
      "board",
      "get_board_info",
      { inputSchema: z.object({}) },
      readHandler,
    );

    const signal = new AbortController().signal;
    const firstRound = await tools[0].callback({ reference: "R1" }, context(signal));
    expect(isInputRequiredResult(firstRound)).toBe(true);
    expect(firstRound.inputRequests).toHaveProperty("confirmation");
    expect(firstRound.requestState).toEqual(expect.any(String));
    expect(destructiveHandler).not.toHaveBeenCalled();

    const verifiedState = await toolConfirmationStateCodec.verify(
      firstRound.requestState!,
      context(signal),
    );

    await tools[0].callback(
      { reference: "R1" },
      context(
        signal,
        {
          confirmation: { action: "accept", content: { confirmed: true } },
        },
        verifiedState,
      ),
    );
    expect(destructiveHandler).toHaveBeenCalledTimes(1);

    await expect(
      tools[0].callback(
        { reference: "R1" },
        context(
          signal,
          { confirmation: { action: "accept", content: { confirmed: true } } },
          verifiedState,
        ),
      ),
    ).rejects.toThrow("already been used");

    const declineRound = await tools[0].callback({ reference: "R2" }, context(signal));
    expect(isInputRequiredResult(declineRound)).toBe(true);
    const declineState = await toolConfirmationStateCodec.verify(
      declineRound.requestState!,
      context(signal),
    );
    const declined = await tools[0].callback(
      { reference: "R2" },
      context(signal, { confirmation: { action: "decline" } }, declineState),
    );
    expect(isInputRequiredResult(declined)).toBe(false);
    expect(declined.structuredContent).toMatchObject({
      success: false,
      cancelled: true,
      action: "decline",
    });
    expect(destructiveHandler).toHaveBeenCalledTimes(1);

    const spoofedFirstRound = await tools[0].callback(
      { reference: "R3" },
      context(signal, {
        confirmation: { action: "accept", content: { confirmed: true } },
      }),
    );
    expect(isInputRequiredResult(spoofedFirstRound)).toBe(true);
    expect(destructiveHandler).toHaveBeenCalledTimes(1);

    const mismatchedState = await toolConfirmationStateCodec.verify(
      spoofedFirstRound.requestState!,
      context(signal),
    );
    await expect(
      tools[0].callback(
        { reference: "R4" },
        context(
          signal,
          { confirmation: { action: "accept", content: { confirmed: true } } },
          mismatchedState,
        ),
      ),
    ).rejects.toThrow("does not match");

    await tools[1].callback({}, context(signal));
    expect(readHandler).toHaveBeenCalledTimes(1);
  });
});
