/** Read-only resources for installed KiCad footprint and symbol libraries. */

import { McpServer, ResourceTemplate } from "@modelcontextprotocol/server";
import { logger } from "../logger.js";
import {
  jsonContents,
  optionalPositiveInteger,
  PUBLIC_LIBRARY_JSON,
  requireBackendSuccess,
  templateString,
  type CommandFunction,
} from "./shared.js";

export function registerLibraryResources(
  server: McpServer,
  callKicadScript: CommandFunction,
): void {
  logger.info("Registering library resources");

  // Optional values belong in an RFC 6570 query expansion. Patterns such as
  // {filter?} are not RFC 6570 and were treated as a variable literally named
  // "filter?" by compliant URI-template implementations.
  server.registerResource(
    "component_library",
    new ResourceTemplate("kicad://library/footprints{?filter,library,limit}", {
      list: async () => ({
        resources: [{ uri: "kicad://library/footprints", name: "All footprint libraries" }],
      }),
    }),
    {
      ...PUBLIC_LIBRARY_JSON,
      title: "KiCad footprint library search",
      description: "Search installed footprint libraries by name and optional library filter",
    },
    async (uri, variables, ctx) => {
      const filter = templateString(variables, "filter", uri) ?? "*";
      const library = templateString(variables, "library", uri);
      const limit = optionalPositiveInteger(variables, "limit", uri);
      const result = requireBackendSuccess(
        await callKicadScript(
          "search_footprints",
          {
            pattern: filter,
            library,
            limit,
          },
          ctx.mcpReq.signal,
        ),
        "Failed to search the footprint library",
        uri,
      );
      return jsonContents(uri, result);
    },
  );

  server.registerResource(
    "library_list",
    "kicad://libraries",
    {
      ...PUBLIC_LIBRARY_JSON,
      title: "Installed KiCad footprint libraries",
      description: "Names of all installed footprint libraries",
    },
    async (uri, ctx) => {
      const result = requireBackendSuccess(
        await callKicadScript("list_libraries", {}, ctx.mcpReq.signal),
        "Failed to retrieve the footprint library list",
        uri,
      );
      return jsonContents(uri, result);
    },
  );

  // get_footprint_info is the implemented backend equivalent for library
  // component details. Supplying library makes the lookup unambiguous.
  server.registerResource(
    "library_component_details",
    new ResourceTemplate("kicad://library/component/{componentId}{?library}", {
      list: undefined,
    }),
    {
      ...PUBLIC_LIBRARY_JSON,
      title: "KiCad library footprint details",
      description: "Parsed metadata and pad information for a library footprint",
    },
    async (uri, variables, ctx) => {
      const componentId = templateString(variables, "componentId", uri, { required: true });
      const library = templateString(variables, "library", uri);
      const footprintName = library ? `${library}:${componentId}` : componentId;
      const result = requireBackendSuccess(
        await callKicadScript(
          "get_footprint_info",
          {
            footprint_name: footprintName,
            library_name: library,
          },
          ctx.mcpReq.signal,
        ),
        `Failed to retrieve footprint details for ${footprintName}`,
        uri,
      );
      return jsonContents(uri, result);
    },
  );

  server.registerResource(
    "component_footprint",
    new ResourceTemplate("kicad://footprint/{componentId}{?footprint}", { list: undefined }),
    {
      ...PUBLIC_LIBRARY_JSON,
      title: "KiCad component footprint",
      description: "Footprint metadata for an explicit footprint name or component identifier",
    },
    async (uri, variables, ctx) => {
      const componentId = templateString(variables, "componentId", uri, { required: true });
      const footprint = templateString(variables, "footprint", uri);
      const footprintName = footprint ?? componentId;
      const result = requireBackendSuccess(
        await callKicadScript(
          "get_footprint_info",
          { footprint_name: footprintName },
          ctx.mcpReq.signal,
        ),
        `Failed to retrieve footprint ${footprintName}`,
        uri,
      );
      return jsonContents(uri, result);
    },
  );

  server.registerResource(
    "component_symbol",
    new ResourceTemplate("kicad://symbol/{componentId}", { list: undefined }),
    {
      ...PUBLIC_LIBRARY_JSON,
      title: "KiCad library symbol",
      description: "Metadata for a symbol in Library:Symbol form",
    },
    async (uri, variables, ctx) => {
      const componentId = templateString(variables, "componentId", uri, { required: true });
      const result = requireBackendSuccess(
        await callKicadScript("get_symbol_info", { symbol: componentId }, ctx.mcpReq.signal),
        `Failed to retrieve symbol ${componentId}`,
        uri,
      );
      return jsonContents(uri, result);
    },
  );

  // component_3d_model is intentionally not registered: no backend command
  // can read or render an individual component's 3D model.
  logger.info("Library resources registered");
}
