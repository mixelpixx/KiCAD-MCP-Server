/**
 * UI/Process management tools for KiCAD MCP server
 */
import { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";
import { logger } from "../logger.js";

export function registerUITools(server: McpServer, callKicadScript: Function) {
  // Get MCP/KiCAD backend and loaded file state
  server.registerTool(
    "get_backend_state",
    {
      description:
        "Return the active backend, realtime status, loaded project/board paths, and dirty state.",
      inputSchema: z.object({}),
    },
    async () => {
      logger.info("Getting KiCAD backend state");
      const result = await callKicadScript("get_backend_state", {});
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  // Check if KiCAD UI is running
  server.registerTool(
    "check_kicad_ui",
    { description: "Check if KiCAD UI is currently running", inputSchema: z.object({}) },
    async () => {
      logger.info("Checking KiCAD UI status");
      const result = await callKicadScript("check_kicad_ui", {});
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  // Launch KiCAD UI
  server.registerTool(
    "launch_kicad_ui",
    {
      description: "Launch KiCAD UI, optionally with a project file",
      inputSchema: z.object({
        projectPath: z.string().optional().describe("Optional path to .kicad_pcb file to open"),
        autoLaunch: z
          .boolean()
          .optional()
          .describe("Whether to launch KiCAD if not running (default: true)"),
      }),
    },
    async (args: { projectPath?: string; autoLaunch?: boolean }) => {
      logger.info(
        `Launching KiCAD UI${args.projectPath ? " with project: " + args.projectPath : ""}`,
      );
      const result = await callKicadScript("launch_kicad_ui", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  logger.info("UI management tools registered");
}
