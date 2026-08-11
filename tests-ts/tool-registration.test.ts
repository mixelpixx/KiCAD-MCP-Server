import {
  isInputRequiredResult,
  type CallToolResult,
  type InputRequiredResult,
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
  toolRequiresConfirmation,
  type CommandFunction,
  withToolSignal,
} from "../src/tools/tool-registration.js";

interface CapturedTool {
  name: string;
  config: Record<string, unknown>;
  callback: (args: unknown, ctx: ServerContext) => Promise<CallToolResult | InputRequiredResult>;
}

function callToolResult(result: CallToolResult | InputRequiredResult): CallToolResult {
  expect(isInputRequiredResult(result)).toBe(false);
  if (isInputRequiredResult(result)) throw new Error("Expected a completed tool result");
  return result;
}

function inputRequiredResult(result: CallToolResult | InputRequiredResult): InputRequiredResult {
  expect(isInputRequiredResult(result)).toBe(true);
  if (!isInputRequiredResult(result)) throw new Error("Expected an input-required result");
  return result;
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

  it.each([
    "check_clearance",
    "check_placement_clearance",
    "estimate_airwire_lengths",
    "generate_netlist",
    "get_board_origin",
    "get_component_geometry",
    "get_design_rules",
    "get_net_pads",
    "get_pads",
    "get_ratsnest",
    "get_schematic_view",
    "get_sheet_properties",
    "is_dirty",
    "list_graphics",
    "run_erc",
  ])("marks the audited inspection tool %s as read-only", (name) => {
    expect(toolAnnotationsFor(name)).toMatchObject({
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    });
  });

  it.each(["get_registry_part", "search_parts_registry", "get_jlcpcb_part"])(
    "marks the remote catalog lookup %s as read-only and open-world",
    (name) => {
      expect(toolAnnotationsFor(name)).toMatchObject({
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
      });
    },
  );

  it("does not claim optional writers or local URL construction are read-only/open-world", () => {
    for (const name of ["suggest_placement", "suggest_schematic_declutter", "get_board_2d_view"]) {
      expect(toolAnnotationsFor(name)).toMatchObject({
        readOnlyHint: false,
        destructiveHint: true,
      });
    }

    expect(toolAnnotationsFor("get_datasheet_url").openWorldHint).toBe(false);
    expect(toolAnnotationsFor("enrich_datasheets").openWorldHint).toBe(false);
  });

  it.each([
    "clear_board_outline",
    "delete_graphic",
    "discard_or_reload",
    "import_pcb",
    "reload_board",
    "remove_hierarchical_sheet",
    "remove_schematic_component_property",
    "replace_board_outline",
    "set_layer_constraints",
    "set_sheet_property",
  ])("requires confirmation for the audited high-impact tool %s", (name) => {
    expect(toolAnnotationsFor(name)).toMatchObject({
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: false,
    });
    expect(toolRequiresConfirmation(name, {})).toBe(true);
  });

  it("requires confirmation only for the write/overwrite forms of dual-mode tools", () => {
    expect(toolRequiresConfirmation("repair_flat_symbols", {})).toBe(false);
    expect(toolRequiresConfirmation("repair_flat_symbols", { dryRun: true })).toBe(false);
    expect(toolRequiresConfirmation("repair_flat_symbols", { dryRun: false })).toBe(true);
    expect(toolAnnotationsFor("repair_flat_symbols").destructiveHint).toBe(true);

    expect(toolRequiresConfirmation("suggest_placement", { apply: false })).toBe(false);
    expect(toolRequiresConfirmation("suggest_placement", { apply: true })).toBe(true);
    expect(toolRequiresConfirmation("suggest_schematic_declutter", { apply: false })).toBe(false);
    expect(toolRequiresConfirmation("suggest_schematic_declutter", { apply: true })).toBe(true);

    for (const name of ["save_as", "save_board", "save_project"]) {
      expect(toolRequiresConfirmation(name, {})).toBe(false);
      expect(toolRequiresConfirmation(name, { force: true })).toBe(true);
      expect(toolRequiresConfirmation(name, { forceExternalChanges: true })).toBe(true);
      expect(toolRequiresConfirmation(name, { overwrite: true })).toBe(true);
    }

    expect(toolRequiresConfirmation("create_symbol", { overwrite: true })).toBe(true);
    expect(toolRequiresConfirmation("import_symbol", { overwrite: true })).toBe(true);
  });

  it.each(["add_schematic_component", "move_component", "set_schematic_component_property"])(
    "does not add MRTR friction to the ordinary edit %s",
    (name) => {
      expect(toolRequiresConfirmation(name, {})).toBe(false);
    },
  );

  it("adds a default output schema and parses any JSON root without replacing content blocks", async () => {
    const { server, tools } = captureServer();
    const image = { type: "image" as const, data: "AA==", mimeType: "image/png" };

    registerKiCadTool(server, "test", "array_result", { inputSchema: z.object({}) }, async () => ({
      content: [image, { type: "text" as const, text: "[1,2,3]" }],
    }));

    expect(tools[0].config.outputSchema).toBeDefined();
    const result = callToolResult(
      await tools[0].callback({}, context(new AbortController().signal)),
    );
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
    const result = callToolResult(await tools[0].callback({}, context(controller.signal)));
    expect(tools[0].config.outputSchema).toBe(explicitSchema);
    expect(backend).toHaveBeenCalledWith("failing_command", {}, controller.signal);
    expect(result.structuredContent).toBe(false);
    expect(result.content).toEqual([{ type: "text", text: "Failed: denied" }]);
    expect(result.isError).toBe(true);
  });

  it("requires validated MRTR confirmation only for policy-selected tools", async () => {
    const { server, tools } = captureServer();
    const destructiveHandler = vi.fn(async () => ({
      content: [{ type: "text" as const, text: '{"success":true}' }],
    }));
    const readHandler = vi.fn(async () => ({
      content: [{ type: "text" as const, text: '{"success":true}' }],
    }));
    const safeEditHandler = vi.fn(async () => ({
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
    registerKiCadTool(
      server,
      "component",
      "move_component",
      { inputSchema: z.object({ reference: z.string() }) },
      safeEditHandler,
    );

    const signal = new AbortController().signal;
    const firstRound = inputRequiredResult(
      await tools[0].callback({ reference: "R1" }, context(signal)),
    );
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

    const declineRound = inputRequiredResult(
      await tools[0].callback({ reference: "R2" }, context(signal)),
    );
    const declineState = await toolConfirmationStateCodec.verify(
      declineRound.requestState!,
      context(signal),
    );
    const declined = callToolResult(
      await tools[0].callback(
        { reference: "R2" },
        context(signal, { confirmation: { action: "decline" } }, declineState),
      ),
    );
    expect(declined.structuredContent).toMatchObject({
      success: false,
      cancelled: true,
      action: "decline",
    });
    expect(destructiveHandler).toHaveBeenCalledTimes(1);

    const spoofedFirstRound = inputRequiredResult(
      await tools[0].callback(
        { reference: "R3" },
        context(signal, {
          confirmation: { action: "accept", content: { confirmed: true } },
        }),
      ),
    );
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

    const safeEdit = await tools[2].callback({ reference: "R5" }, context(signal));
    expect(isInputRequiredResult(safeEdit)).toBe(false);
    expect(safeEditHandler).toHaveBeenCalledTimes(1);
  });
});
