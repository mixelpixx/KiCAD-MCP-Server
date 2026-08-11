import { AsyncLocalStorage } from "node:async_hooks";
import { createHash, randomBytes, randomUUID } from "node:crypto";
import {
  acceptedContent,
  createRequestStateCodec,
  inputResponse,
  inputRequired,
  INVALID_PARAMS,
  isInputRequiredResult,
  ProtocolError,
} from "@modelcontextprotocol/server";
import type {
  CallToolResult,
  Icon,
  InputRequiredResult,
  McpServer,
  RegisteredTool,
  ServerContext,
  StandardSchemaWithJSON,
  ToolAnnotations,
  ToolCallback,
} from "@modelcontextprotocol/server";
import { z } from "zod";
import { registerToolDefinition } from "./registry.js";

type ToolConfig<InputSchema extends StandardSchemaWithJSON> = {
  title?: string;
  description?: string;
  inputSchema: InputSchema;
  outputSchema?: StandardSchemaWithJSON;
  annotations?: ToolAnnotations;
  icons?: Icon[];
  _meta?: Record<string, unknown>;
};

const READ_ONLY_TOOLS = new Set([
  "batch_list_symbol_pins",
  "check_clearance",
  "check_courtyard_overlaps",
  "check_freerouting",
  "check_kicad_ui",
  "check_placement_clearance",
  "estimate_airwire_lengths",
  "find_component",
  "find_orphaned_wires",
  "find_overlapping_elements",
  "find_wires_crossing_symbols",
  "generate_netlist",
  "get_backend_state",
  "get_board_extents",
  "get_board_info",
  "get_board_origin",
  "get_category_tools",
  "get_component_geometry",
  "get_component_list",
  "get_component_pads",
  "get_component_properties",
  "get_datasheet_url",
  "get_design_rules",
  "get_drc_violations",
  "get_elements_in_region",
  "get_footprint_info",
  "get_jlcpcb_database_stats",
  "get_jlcpcb_part",
  "get_layer_list",
  "get_net_at_point",
  "get_net_connections",
  "get_net_pads",
  "get_nets_list",
  "get_pad_position",
  "get_pads",
  "get_project_info",
  "get_ratsnest",
  "get_registry_part",
  "get_schematic_component",
  "get_schematic_pin_locations",
  "get_schematic_view",
  "get_schematic_view_region",
  "get_sheet_properties",
  "get_symbol_info",
  "get_wire_connections",
  "is_dirty",
  "list_floating_labels",
  "list_footprint_libraries",
  "list_graphics",
  "list_libraries",
  "list_library_footprints",
  "list_library_symbols",
  "list_schematic_components",
  "list_schematic_labels",
  "list_schematic_nets",
  "list_schematic_texts",
  "list_schematic_wires",
  "list_symbol_libraries",
  "list_symbol_pins",
  "list_symbols_in_library",
  "list_tool_categories",
  "query_traces",
  "query_zones",
  "run_erc",
  "search_footprints",
  "search_jlcpcb_parts",
  "search_parts_registry",
  "search_symbols",
  "search_tools",
  "suggest_jlcpcb_alternatives",
]);

/**
 * Operations whose normal execution is broad, destructive, or discards state.
 * Ordinary additive edits intentionally do not require an MRTR round trip even
 * though their conservative SDK annotation remains destructiveHint=true.
 */
const ALWAYS_CONFIRM_TOOLS = new Set([
  "annotate_schematic",
  "autoroute",
  "batch_edit_schematic_components",
  "clear_board_outline",
  "close_project",
  "create_board_from_schematic",
  "delete_component",
  "delete_graphic",
  "delete_schematic_component",
  "delete_schematic_net_label",
  "delete_schematic_wire",
  "delete_symbol",
  "delete_trace",
  "discard_or_reload",
  "download_jlcpcb_database",
  "import_eagle_project",
  "import_pcb",
  "import_ses",
  "hierarchical_place",
  "reload_board",
  "remove_hierarchical_sheet",
  "remove_schematic_component_property",
  "replace_board_outline",
  "replace_instance_lib_ids",
  "replace_schematic_component",
  "set_board_size",
  "set_design_rules",
  "set_layer_constraints",
  "set_sheet_property",
  "sync_schematic_to_board",
  "update_symbol_from_library",
]);

const OPEN_WORLD_TOOLS = new Set([
  "download_jlcpcb_database",
  "download_registry_part",
  "get_jlcpcb_part",
  "get_registry_part",
  "launch_kicad_ui",
  "search_parts_registry",
]);

function booleanArg(args: unknown, key: string): boolean {
  return (
    typeof args === "object" &&
    args !== null &&
    !Array.isArray(args) &&
    (args as Record<string, unknown>)[key] === true
  );
}

function falseBooleanArg(args: unknown, key: string): boolean {
  return (
    typeof args === "object" &&
    args !== null &&
    !Array.isArray(args) &&
    (args as Record<string, unknown>)[key] === false
  );
}

/**
 * Decide whether this exact invocation needs an SDK-v2 MRTR confirmation.
 * Argument-aware rules keep dry runs and guarded saves frictionless while
 * requiring confirmation when a caller explicitly opts into an overwrite or
 * a broad automatic rewrite.
 */
export function toolRequiresConfirmation(name: string, args: unknown): boolean {
  if (ALWAYS_CONFIRM_TOOLS.has(name)) return true;

  switch (name) {
    case "create_symbol":
    case "import_symbol":
      return booleanArg(args, "overwrite");
    case "repair_flat_symbols":
      return falseBooleanArg(args, "dryRun");
    case "save_as":
    case "save_board":
    case "save_project":
      return (
        booleanArg(args, "overwrite") ||
        booleanArg(args, "force") ||
        booleanArg(args, "forceExternalChanges")
      );
    case "suggest_placement":
    case "suggest_schematic_declutter":
      return booleanArg(args, "apply");
    default:
      return false;
  }
}

const CONFIRMATION_KEY = "confirmation";
const CONFIRMATION_SCHEMA = z.object({
  confirmed: z
    .boolean()
    .describe("Set true to confirm this destructive or high-impact KiCad operation"),
});
const CONFIRMATION_STATE_TTL_SECONDS = 600;
const MAX_CONSUMED_CONFIRMATIONS = 4_096;

interface ToolConfirmationState {
  kind: "kicad-tool-confirmation";
  tool: string;
  argsHash: string;
  nonce: string;
}

/**
 * Signed MRTR state shared by every protocol server instance in this process.
 * The payload binds a confirmation to one tool and one exact argument set;
 * the request method is also bound by the SDK codec.
 */
export const toolConfirmationStateCodec = createRequestStateCodec<ToolConfirmationState>({
  key: randomBytes(32),
  ttlSeconds: CONFIRMATION_STATE_TTL_SECONDS,
  bind: (ctx) => ctx.mcpReq.method,
});

const consumedConfirmationNonces = new Map<string, number>();

function canonicalJson(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) {
    return `[${value.map((item) => (item === undefined ? "null" : canonicalJson(item))).join(",")}]`;
  }

  switch (typeof value) {
    case "string":
    case "boolean":
      return JSON.stringify(value);
    case "number":
      return Number.isFinite(value) ? JSON.stringify(value) : "null";
    case "object": {
      const entries = Object.entries(value as Record<string, unknown>)
        .filter(([, item]) => item !== undefined)
        .sort(([left], [right]) => left.localeCompare(right));
      return `{${entries
        .map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`)
        .join(",")}}`;
    }
    default:
      return "null";
  }
}

function hashToolArgs(args: unknown): string {
  return createHash("sha256").update(canonicalJson(args)).digest("base64url");
}

function confirmationTarget(args: unknown): string {
  const rendered = canonicalJson(args);
  if (rendered.length <= 600) return rendered;
  return `${rendered.slice(0, 600)}… [sha256:${hashToolArgs(args)}]`;
}

function consumeConfirmationNonce(nonce: string): boolean {
  const now = Date.now();
  for (const [candidate, expiresAt] of consumedConfirmationNonces) {
    if (expiresAt <= now) consumedConfirmationNonces.delete(candidate);
  }

  if (consumedConfirmationNonces.has(nonce)) return false;
  consumedConfirmationNonces.set(nonce, now + CONFIRMATION_STATE_TTL_SECONDS * 1_000);

  while (consumedConfirmationNonces.size > MAX_CONSUMED_CONFIRMATIONS) {
    const oldest = consumedConfirmationNonces.keys().next().value as string | undefined;
    if (!oldest) break;
    consumedConfirmationNonces.delete(oldest);
  }
  return true;
}

function confirmationStoppedResult(
  name: string,
  action: "decline" | "cancel" | "not-confirmed",
): CallToolResult {
  const payload = {
    success: false,
    cancelled: true,
    action,
    message: `KiCad operation '${name}' was not executed`,
  };
  return {
    content: [{ type: "text", text: payload.message }],
    structuredContent: payload,
  };
}

interface ToolExecutionContext {
  signal: AbortSignal;
  backendFailed: boolean;
}

/** Shared backend-caller contract used by every tool registration module. */
export type CommandFunction = (
  command: string,
  params: Record<string, unknown>,
  signal?: AbortSignal,
) => Promise<any>;

const toolExecutionContext = new AsyncLocalStorage<ToolExecutionContext>();
const callerWrappers = new WeakMap<CommandFunction, CommandFunction>();

/**
 * Bind a backend caller to the active MCP request without changing every tool
 * callback. AsyncLocalStorage keeps concurrent requests and cancellation
 * signals isolated from one another.
 */
export function withToolSignal(callBackend: CommandFunction): CommandFunction {
  const existing = callerWrappers.get(callBackend);
  if (existing) return existing;

  const wrapped: CommandFunction = async (command, params, signal) => {
    const execution = toolExecutionContext.getStore();
    const result = await callBackend(command, params, signal ?? execution?.signal);

    if (
      execution &&
      typeof result === "object" &&
      result !== null &&
      !Array.isArray(result) &&
      (result as Record<string, unknown>).success === false
    ) {
      execution.backendFailed = true;
    }

    return result;
  };

  callerWrappers.set(callBackend, wrapped);
  callerWrappers.set(wrapped, wrapped);
  return wrapped;
}

function titleFromName(name: string): string {
  return name
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function toolAnnotationsFor(name: string): ToolAnnotations {
  if (READ_ONLY_TOOLS.has(name)) {
    return {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: OPEN_WORLD_TOOLS.has(name),
    };
  }
  if (ALWAYS_CONFIRM_TOOLS.has(name)) {
    return {
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: OPEN_WORLD_TOOLS.has(name),
    };
  }
  if (OPEN_WORLD_TOOLS.has(name)) {
    return {
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: true,
    };
  }
  // Match the protocol's conservative defaults explicitly so every catalog
  // entry is self-describing. Unknown mutating operations must never be
  // presented to a client as harmless or idempotent by omission.
  return {
    readOnlyHint: false,
    destructiveHint: true,
    idempotentHint: false,
    openWorldHint: false,
  };
}

function deriveStructuredContent(content: CallToolResult["content"]): unknown {
  let firstText: string | undefined;

  for (const block of content ?? []) {
    if (block.type !== "text") continue;
    firstText ??= block.text;

    try {
      return JSON.parse(block.text) as unknown;
    } catch {
      // A human-readable text result is still a valid natural JSON string root.
    }
  }

  // outputSchema requires structuredContent. Preserve plain-text results as a
  // string and give image-only/empty results the natural JSON null value.
  return firstText ?? null;
}

function isBackendFailure(value: unknown): boolean {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    (value as Record<string, unknown>).success === false
  );
}

function normalizeToolResult(result: CallToolResult, backendFailed: boolean): CallToolResult {
  const normalized = { ...result };

  if (normalized.structuredContent === undefined) {
    normalized.structuredContent = deriveStructuredContent(normalized.content);
  }

  if (backendFailed || isBackendFailure(normalized.structuredContent)) {
    normalized.isError = true;
  }

  return normalized;
}

/** Register a tool and its discovery metadata from one authoritative call site. */
export function registerKiCadTool<InputSchema extends StandardSchemaWithJSON>(
  server: McpServer,
  category: string,
  name: string,
  config: ToolConfig<InputSchema>,
  callback: ToolCallback<InputSchema>,
): RegisteredTool {
  const title = config.title ?? titleFromName(name);
  const inferredAnnotations = toolAnnotationsFor(name);
  const annotations = { ...inferredAnnotations, ...config.annotations };

  registerToolDefinition({
    name,
    title,
    description: config.description ?? title,
    category,
  });

  const outputSchema = config.outputSchema ?? z.unknown();
  const wrappedCallback = async (
    args: unknown,
    ctx: ServerContext,
  ): Promise<CallToolResult | InputRequiredResult> => {
    if (toolRequiresConfirmation(name, args)) {
      const argsHash = hashToolArgs(args);
      const state = ctx.mcpReq.requestState<ToolConfirmationState>();

      if (!state) {
        const requestState = await toolConfirmationStateCodec.mint(
          {
            kind: "kicad-tool-confirmation",
            tool: name,
            argsHash,
            nonce: randomUUID(),
          },
          ctx,
        );
        return inputRequired({
          requestState,
          inputRequests: {
            [CONFIRMATION_KEY]: inputRequired.elicit({
              message: `Confirm destructive or high-impact KiCad operation: ${title} (${name})\nTarget arguments: ${confirmationTarget(args)}`,
              requestedSchema: CONFIRMATION_SCHEMA,
            }),
          },
        });
      }

      if (
        state.kind !== "kicad-tool-confirmation" ||
        state.tool !== name ||
        state.argsHash !== argsHash ||
        typeof state.nonce !== "string" ||
        state.nonce.length === 0
      ) {
        throw new ProtocolError(INVALID_PARAMS, "Confirmation state does not match this tool call");
      }

      const response = inputResponse(ctx.mcpReq.inputResponses, CONFIRMATION_KEY);
      if (response.kind !== "elicit") {
        throw new ProtocolError(INVALID_PARAMS, "A confirmation response is required");
      }

      if (response.action === "decline" || response.action === "cancel") {
        if (!consumeConfirmationNonce(state.nonce)) {
          throw new ProtocolError(INVALID_PARAMS, "Confirmation state has already been used");
        }
        return confirmationStoppedResult(name, response.action);
      }

      const confirmation = acceptedContent(
        ctx.mcpReq.inputResponses,
        CONFIRMATION_KEY,
        CONFIRMATION_SCHEMA,
      );
      if (!confirmation) {
        throw new ProtocolError(INVALID_PARAMS, "The confirmation response is invalid");
      }
      if (confirmation.confirmed !== true) {
        if (!consumeConfirmationNonce(state.nonce)) {
          throw new ProtocolError(INVALID_PARAMS, "Confirmation state has already been used");
        }
        return confirmationStoppedResult(name, "not-confirmed");
      }
      if (!consumeConfirmationNonce(state.nonce)) {
        throw new ProtocolError(INVALID_PARAMS, "Confirmation state has already been used");
      }
    }

    const execution: ToolExecutionContext = {
      signal: ctx.mcpReq.signal,
      backendFailed: false,
    };
    const result = await toolExecutionContext.run(execution, () => callback(args as any, ctx));

    if (isInputRequiredResult(result)) return result;
    return normalizeToolResult(result, execution.backendFailed);
  };

  return server.registerTool(
    name,
    { ...config, outputSchema, title, annotations } as any,
    wrappedCallback as any,
  );
}
