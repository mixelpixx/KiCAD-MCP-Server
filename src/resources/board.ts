/** Read-only resources for the currently loaded KiCad PCB. */

import {
  INTERNAL_ERROR,
  McpServer,
  ProtocolError,
  ResourceTemplate,
  type Variables,
} from "@modelcontextprotocol/server";
import { logger } from "../logger.js";
import {
  jsonContents,
  oneOfTemplateStrings,
  optionalPositiveInteger,
  PRIVATE_LIVE_IMAGE,
  PRIVATE_LIVE_JSON,
  requiredResultString,
  requireBackendSuccess,
  templateString,
  type CommandFunction,
} from "./shared.js";

export function registerBoardResources(server: McpServer, callKicadScript: CommandFunction): void {
  logger.info("Registering board resources");

  server.registerResource(
    "board_info",
    "kicad://board/info",
    {
      ...PRIVATE_LIVE_JSON,
      title: "Current KiCad board",
      description: "Properties of the currently loaded PCB",
    },
    async (uri, ctx) => {
      const result = requireBackendSuccess(
        await callKicadScript("get_board_info", {}, ctx.mcpReq.signal),
        "Failed to retrieve board information",
        uri,
      );
      return jsonContents(uri, result);
    },
  );

  server.registerResource(
    "layer_list",
    "kicad://board/layers",
    {
      ...PRIVATE_LIVE_JSON,
      title: "Current KiCad board layers",
      description: "Enabled layer stack for the currently loaded PCB",
    },
    async (uri, ctx) => {
      const result = requireBackendSuccess(
        await callKicadScript("get_layer_list", {}, ctx.mcpReq.signal),
        "Failed to retrieve the board layer list",
        uri,
      );
      return jsonContents(uri, result);
    },
  );

  server.registerResource(
    "board_extents",
    new ResourceTemplate("kicad://board/extents{?unit}", {
      list: async () => ({
        resources: [
          { uri: "kicad://board/extents?unit=mm", name: "Board extents in millimeters" },
          { uri: "kicad://board/extents?unit=inch", name: "Board extents in inches" },
        ],
      }),
      complete: { unit: () => ["mm", "inch"] },
    }),
    {
      ...PRIVATE_LIVE_JSON,
      title: "Current board extents",
      description: "Bounding box of the loaded PCB in millimeters or inches",
    },
    async (uri, variables, ctx) => {
      const unit = oneOfTemplateStrings(variables, "unit", uri, ["mm", "inch"], "mm");
      const result = requireBackendSuccess(
        await callKicadScript("get_board_extents", { unit }, ctx.mcpReq.signal),
        "Failed to retrieve board extents",
        uri,
      );
      return jsonContents(uri, result);
    },
  );

  server.registerResource(
    "board_2d_view",
    new ResourceTemplate("kicad://board/2d-view{?format,width,height,layers}", {
      list: async () => ({
        resources: [
          { uri: "kicad://board/2d-view?format=png", name: "Board preview (PNG)" },
          { uri: "kicad://board/2d-view?format=jpg", name: "Board preview (JPEG)" },
          { uri: "kicad://board/2d-view?format=svg", name: "Board preview (SVG)" },
        ],
      }),
      complete: { format: () => ["png", "jpg", "svg"] },
    }),
    {
      ...PRIVATE_LIVE_IMAGE,
      title: "Current board 2D preview",
      description: "Rendered image of the loaded PCB with optional dimensions and layer filter",
    },
    async (uri, variables, ctx) => {
      const format = oneOfTemplateStrings(variables, "format", uri, ["png", "jpg", "svg"], "png");
      const width = optionalPositiveInteger(variables, "width", uri);
      const height = optionalPositiveInteger(variables, "height", uri);
      const layers = parseLayers(variables, uri);

      const result = requireBackendSuccess(
        await callKicadScript(
          "get_board_2d_view",
          {
            layers,
            width,
            height,
            format,
            responseMode: "inline",
          },
          ctx.mcpReq.signal,
        ),
        "Failed to retrieve the 2D board view",
        uri,
      );
      const imageData = requiredResultString(result, "imageData", uri);
      const actualFormat = oneOfResultFormats(result.format, uri);

      if (actualFormat === "svg") {
        return {
          contents: [
            {
              uri: uri.href,
              text: Buffer.from(imageData, "base64").toString("utf8"),
              mimeType: "image/svg+xml",
            },
          ],
        };
      }

      return {
        contents: [
          {
            uri: uri.href,
            blob: imageData,
            mimeType: actualFormat === "jpg" ? "image/jpeg" : "image/png",
          },
        ],
      };
    },
  );

  server.registerResource(
    "board_statistics",
    "kicad://board/statistics",
    {
      ...PRIVATE_LIVE_JSON,
      title: "Current board statistics",
      description: "Combined board dimensions, component counts, and net counts",
    },
    async (uri, ctx) => {
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
      const netsResult = requireBackendSuccess(
        await callKicadScript("get_nets_list", {}, ctx.mcpReq.signal),
        "Failed to retrieve net list",
        uri,
      );

      const components = Array.isArray(componentsResult.components)
        ? componentsResult.components
        : [];
      const board = asRecord(boardResult.board);
      const layers = Array.isArray(board.layers) ? board.layers : [];
      const nets = Array.isArray(netsResult.nets) ? netsResult.nets : [];
      return jsonContents(uri, {
        board: {
          size: board.size,
          layers: layers.length,
          title: board.title,
        },
        components: {
          count: components.length,
          types: countComponentTypes(components),
        },
        nets: { count: nets.length },
      });
    },
  );

  // board_3d_view is intentionally not registered: the backend can export a
  // board model, but it has no command that renders the promised PNG view.
  logger.info("Board resources registered");
}

function parseLayers(variables: Variables, uri: URL): string[] | undefined {
  const value = templateString(variables, "layers", uri);
  const layers = value
    ?.split(",")
    ?.map((layer) => layer.trim())
    .filter(Boolean);
  return layers && layers.length > 0 ? layers : undefined;
}

function oneOfResultFormats(value: unknown, uri: URL): "png" | "jpg" | "svg" {
  // Older backends omitted format when returning the requested PNG. Preserve
  // that compatible default while respecting explicit SVG fallback results.
  if (value === undefined) return "png";
  if (value === "png" || value === "jpg" || value === "svg") return value;
  throw new ProtocolError(INTERNAL_ERROR, "KiCad backend returned an unsupported image format", {
    uri: uri.href,
    format: value,
  });
}

function countComponentTypes(components: unknown[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const component of components) {
    const value =
      typeof component === "object" && component !== null && "value" in component
        ? (component as { value?: unknown }).value
        : undefined;
    const type = typeof value === "string" ? value.split(" ")[0] || "Unknown" : "Unknown";
    counts[type] = (counts[type] ?? 0) + 1;
  }
  return counts;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
