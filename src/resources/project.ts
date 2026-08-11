/** Read-only resources describing the currently loaded KiCad project. */

import { McpServer } from "@modelcontextprotocol/server";
import { logger } from "../logger.js";
import {
  jsonContents,
  PRIVATE_LIVE_JSON,
  requireBackendSuccess,
  type CommandFunction,
} from "./shared.js";

export function registerProjectResources(
  server: McpServer,
  callKicadScript: CommandFunction,
): void {
  logger.info("Registering project resources");

  server.registerResource(
    "project_info",
    "kicad://project/info",
    {
      ...PRIVATE_LIVE_JSON,
      title: "Current KiCad project",
      description: "Metadata for the currently loaded KiCad project",
    },
    async (uri, ctx) => {
      const result = requireBackendSuccess(
        await callKicadScript("get_project_info", {}, ctx.mcpReq.signal),
        "Failed to retrieve project information",
        uri,
      );
      return jsonContents(uri, result);
    },
  );

  // get_project_info is the backend's canonical source for title-block and
  // project properties. The former get_project_properties command never
  // existed in the Python command router.
  server.registerResource(
    "project_properties",
    "kicad://project/properties",
    {
      ...PRIVATE_LIVE_JSON,
      title: "KiCad project properties",
      description: "Title-block and metadata properties for the current project",
    },
    async (uri, ctx) => {
      const result = requireBackendSuccess(
        await callKicadScript("get_project_info", {}, ctx.mcpReq.signal),
        "Failed to retrieve project properties",
        uri,
      );
      return jsonContents(uri, result.project ?? result);
    },
  );

  // get_backend_state is the implemented status operation and includes the
  // loaded project/board paths, dirty state, and active backend.
  server.registerResource(
    "project_status",
    "kicad://project/status",
    {
      ...PRIVATE_LIVE_JSON,
      title: "KiCad backend and project status",
      description: "Current backend, loaded-file, synchronization, and dirty-state status",
    },
    async (uri, ctx) => {
      const result = requireBackendSuccess(
        await callKicadScript("get_backend_state", {}, ctx.mcpReq.signal),
        "Failed to retrieve project status",
        uri,
      );
      return jsonContents(uri, result);
    },
  );

  server.registerResource(
    "project_summary",
    "kicad://project/summary",
    {
      ...PRIVATE_LIVE_JSON,
      title: "KiCad project summary",
      description: "Combined project, board, and component summary",
    },
    async (uri, ctx) => {
      const infoResult = requireBackendSuccess(
        await callKicadScript("get_project_info", {}, ctx.mcpReq.signal),
        "Failed to retrieve project information",
        uri,
      );
      const boardResult = requireBackendSuccess(
        await callKicadScript("get_board_info", {}, ctx.mcpReq.signal),
        "Failed to retrieve board information",
        uri,
      );
      const componentsResult = requireBackendSuccess(
        await callKicadScript("get_component_list", {}, ctx.mcpReq.signal),
        "Failed to retrieve component list",
        uri,
      );

      const components = Array.isArray(componentsResult.components)
        ? componentsResult.components
        : [];
      const board = asRecord(boardResult.board);
      const layers = Array.isArray(board.layers) ? board.layers : [];
      return jsonContents(uri, {
        project: infoResult.project,
        board: {
          size: board.size,
          layers: layers.length,
          title: board.title,
        },
        components: {
          count: components.length,
          types: countComponentTypes(components),
        },
      });
    },
  );

  // project_files is intentionally not registered: no read-only backend
  // command currently supplies the authoritative project file set.
  logger.info("Project resources registered");
}

function countComponentTypes(components: unknown[]): Record<string, number> {
  const typeCounts: Record<string, number> = {};
  for (const component of components) {
    const value =
      typeof component === "object" && component !== null && "value" in component
        ? (component as { value?: unknown }).value
        : undefined;
    const type = typeof value === "string" ? value.split(" ")[0] || "Unknown" : "Unknown";
    typeCounts[type] = (typeCounts[type] ?? 0) + 1;
  }
  return typeCounts;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
