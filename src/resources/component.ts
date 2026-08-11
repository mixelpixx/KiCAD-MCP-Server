/** Read-only resources describing footprints placed on the current PCB. */

import { McpServer, ResourceTemplate } from "@modelcontextprotocol/server";
import { logger } from "../logger.js";
import {
  jsonContents,
  PRIVATE_LIVE_JSON,
  requireBackendSuccess,
  templateString,
  type CommandFunction,
} from "./shared.js";

export function registerComponentResources(
  server: McpServer,
  callKicadScript: CommandFunction,
): void {
  logger.info("Registering component resources");

  server.registerResource(
    "component_list",
    "kicad://components",
    {
      ...PRIVATE_LIVE_JSON,
      title: "Placed PCB components",
      description: "All footprints placed on the currently loaded PCB",
    },
    async (uri, ctx) => {
      const result = requireBackendSuccess(
        await callKicadScript("get_component_list", {}, ctx.mcpReq.signal),
        "Failed to retrieve component list",
        uri,
      );
      return jsonContents(uri, result);
    },
  );

  server.registerResource(
    "component_details",
    new ResourceTemplate("kicad://component/{reference}/details", { list: undefined }),
    {
      ...PRIVATE_LIVE_JSON,
      title: "PCB component details",
      description: "Properties of a placed PCB footprint selected by reference",
    },
    async (uri, variables, ctx) => {
      const reference = templateString(variables, "reference", uri, { required: true });
      const result = requireBackendSuccess(
        await callKicadScript("get_component_properties", { reference }, ctx.mcpReq.signal),
        `Failed to retrieve details for component ${reference}`,
        uri,
      );
      return jsonContents(uri, result);
    },
  );

  // get_component_pads is the implemented backend operation that returns pad
  // numbers, positions, and net connections for a placed component.
  server.registerResource(
    "component_connections",
    new ResourceTemplate("kicad://component/{reference}/connections", { list: undefined }),
    {
      ...PRIVATE_LIVE_JSON,
      title: "PCB component connections",
      description: "Pad and net connections for a placed PCB footprint",
    },
    async (uri, variables, ctx) => {
      const reference = templateString(variables, "reference", uri, { required: true });
      const result = requireBackendSuccess(
        await callKicadScript("get_component_pads", { reference }, ctx.mcpReq.signal),
        `Failed to retrieve connections for component ${reference}`,
        uri,
      );
      return jsonContents(uri, result);
    },
  );

  // The canonical component list already includes each footprint's position
  // and orientation. The former get_component_placement command did not exist.
  server.registerResource(
    "component_placement",
    "kicad://components/placement",
    {
      ...PRIVATE_LIVE_JSON,
      title: "PCB component placement",
      description: "Placement and orientation data for all footprints on the current PCB",
    },
    async (uri, ctx) => {
      const result = requireBackendSuccess(
        await callKicadScript("get_component_list", {}, ctx.mcpReq.signal),
        "Failed to retrieve component placement",
        uri,
      );
      return jsonContents(uri, result);
    },
  );

  // component_groups and component_visualization are intentionally absent:
  // neither has a read-only backend command with the advertised behavior.
  logger.info("Component resources registered");
}
