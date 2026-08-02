import { randomUUID } from "node:crypto";
import { INVALID_PARAMS, McpServer, ProtocolError } from "@modelcontextprotocol/server";
import { z } from "zod";
import { directToolNames, toolCategories } from "./tools/registry.js";

const CONTEXT_CATEGORIES = new Set([
  "board",
  "component",
  "export",
  "drc",
  "schematic",
  "schematic_hierarchy",
  "schematic_layout",
  "schematic_batch",
  "routing",
  "autoroute",
]);

const DIRECT_CONTEXT_EXCLUSIONS = new Set([
  "create_project",
  "open_project",
  "open_board",
  "get_backend_state",
  "check_kicad_ui",
]);

const EXTRA_CONTEXT_TOOLS = [
  "save_as",
  "align_components",
  "check_courtyard_overlaps",
  "copy_routing_pattern",
  "delete_trace",
  "duplicate_component",
  "get_component_list",
  "get_component_pads",
  "get_elements_in_region",
  "get_net_at_point",
  "get_nets_list",
  "get_pad_position",
  "modify_trace",
  "place_component_array",
  "query_traces",
  "query_zones",
  "refill_zones",
  "route_arc_trace",
  "route_differential_pair",
  "route_pad_to_pad",
  "snap_to_grid",
  "suggest_placement",
];

const OPEN_CONTEXT_COMMANDS = new Set(["create_project", "open_project", "open_board"]);
const PATH_REFRESH_COMMANDS = new Set([
  "reload_board",
  "discard_or_reload",
  "save_project",
  "save_board",
  "save_as",
  "get_project_info",
  "get_board_info",
]);

export const PROJECT_CONTEXT_TOOL_NAMES = new Set([
  ...directToolNames.filter((name) => !DIRECT_CONTEXT_EXCLUSIONS.has(name)),
  ...toolCategories
    .filter((category) => CONTEXT_CATEGORIES.has(category.name))
    .flatMap((category) => category.tools),
  ...EXTRA_CONTEXT_TOOLS,
]);

export interface ProjectContextSnapshot {
  projectHandle: string | null;
  projectPath: string | null;
}

/**
 * Owns the explicit identity of the single KiCad project held by the Python
 * backend. Handles are deliberately opaque and process-local: a server restart
 * invalidates them instead of silently applying a stale handle to another board.
 */
export class ProjectContextManager {
  private activeHandle: string | null = null;
  private activePath: string | null = null;

  snapshot(): ProjectContextSnapshot {
    return { projectHandle: this.activeHandle, projectPath: this.activePath };
  }

  isContextAware(command: string): boolean {
    return PROJECT_CONTEXT_TOOL_NAMES.has(command);
  }

  assertHandle(projectHandle: unknown, command: string): void {
    if (projectHandle === undefined) return; // Legacy compatibility.
    if (typeof projectHandle !== "string" || projectHandle.length === 0) {
      throw new ProtocolError(
        INVALID_PARAMS,
        `projectHandle for ${command} must be a non-empty string`,
      );
    }
    if (!this.activeHandle) {
      throw new ProtocolError(
        INVALID_PARAMS,
        `No project is associated with ${projectHandle}; open the project again to obtain a current handle`,
      );
    }
    if (projectHandle !== this.activeHandle) {
      throw new ProtocolError(
        INVALID_PARAMS,
        `Stale or incorrect projectHandle for ${command}; call get_project_info or open_project again`,
      );
    }
  }

  prepareParams(command: string, params: unknown): Record<string, unknown> {
    const source = params && typeof params === "object" ? (params as Record<string, unknown>) : {};
    this.assertHandle(source.projectHandle, command);
    const forwarded = { ...source };
    delete forwarded.projectHandle;
    return forwarded;
  }

  decorateResult(command: string, result: unknown): unknown {
    if (!result || typeof result !== "object" || Array.isArray(result)) return result;
    const value = result as Record<string, unknown>;
    const succeeded = value.success !== false;

    if (OPEN_CONTEXT_COMMANDS.has(command) && succeeded) {
      this.activeHandle = `kicad-project:${randomUUID()}`;
      this.activePath = this.resultPath(value);
    } else if (command === "close_project" && succeeded) {
      const closedHandle = this.activeHandle;
      const decorated = {
        ...value,
        projectHandle: closedHandle,
        projectHandleStatus: "closed",
      };
      this.activeHandle = null;
      this.activePath = null;
      return decorated;
    } else if (succeeded && PATH_REFRESH_COMMANDS.has(command)) {
      const path = this.resultPath(value);
      if (path) this.activePath = path;
    }

    if (this.activeHandle && (this.isContextAware(command) || OPEN_CONTEXT_COMMANDS.has(command))) {
      return {
        ...value,
        projectHandle: this.activeHandle,
        projectPath: this.activePath,
      };
    }
    return result;
  }

  private resultPath(result: Record<string, unknown>): string | null {
    const candidates = [result];
    if (result.project && typeof result.project === "object" && !Array.isArray(result.project)) {
      candidates.push(result.project as Record<string, unknown>);
    }

    for (const candidate of candidates) {
      for (const key of ["boardPath", "projectPath", "filename", "path"]) {
        if (typeof candidate[key] === "string" && candidate[key].length > 0) {
          return candidate[key];
        }
      }
    }
    return this.activePath;
  }
}

/**
 * Adds an optional projectHandle to tools whose behavior depends on the
 * currently loaded board and validates it before the original handler runs.
 * Omitting it preserves the server's 2025-era behavior during migration.
 */
export function installProjectContextSupport(
  server: McpServer,
  contexts: ProjectContextManager,
): void {
  const registerTool = server.registerTool.bind(server) as (...args: any[]) => any;

  (server as any).registerTool = (name: string, config: any, handler: any) => {
    if (!contexts.isContextAware(name)) return registerTool(name, config, handler);
    if (!(config?.inputSchema instanceof z.ZodObject)) {
      throw new Error(`Project-aware tool ${name} must use a Zod object input schema`);
    }

    const inputSchema = config.inputSchema.extend({
      projectHandle: z
        .string()
        .optional()
        .describe(
          "Opaque handle returned by open_project/create_project/open_board. Recommended for MCP 2026 clients; optional for legacy compatibility.",
        ),
    });

    return registerTool(
      name,
      { ...config, inputSchema },
      async (args: Record<string, unknown>, context: unknown) => {
        contexts.assertHandle(args.projectHandle, name);
        const legacyArgs = { ...args };
        delete legacyArgs.projectHandle;
        return handler(legacyArgs, context);
      },
    );
  };
}
