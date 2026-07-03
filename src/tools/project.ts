/**
 * Project management tools for KiCAD MCP server
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerProjectTools(server: McpServer, callKicadScript: Function) {
  // Create project tool
  server.tool(
    "create_project",
    "Create a new KiCAD project",
    {
      path: z.string().describe("Project directory path"),
      name: z.string().describe("Project name"),
    },
    async (args: { path: string; name: string }) => {
      const result = await callKicadScript("create_project", args);
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

  // Open project tool
  server.tool(
    "open_project",
    "Open an existing KiCAD project",
    {
      filename: z.string().describe("Path to .kicad_pro or .kicad_pcb file"),
    },
    async (args: { filename: string }) => {
      const result = await callKicadScript("open_project", args);
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

  // Close project tool
  server.tool(
    "close_project",
    "Close the currently loaded KiCAD project: optionally save, then drop the in-memory board and clear session state. Use this to hand control back so the user (or the agent) can edit project files directly without the MCP later clobbering those changes on save.",
    {
      save: z
        .boolean()
        .optional()
        .describe(
          "Save the board to disk before closing (default true). If false and there are unsaved changes, the close proceeds but the response warns they were discarded.",
        ),
    },
    async (args: { save?: boolean }) => {
      const result = await callKicadScript("close_project", args);
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

  // Save project tool
  server.tool(
    "save_project",
    "Save the current KiCAD project. Refuses to overwrite the board file if its " +
      "contents changed on disk since load (external edit) unless force is true.",
    {
      path: z.string().optional().describe("Optional new path to save to"),
      force: z
        .boolean()
        .optional()
        .describe(
          "Overwrite the loaded board file even if its on-disk contents changed externally",
        ),
    },
    async (args: { path?: string; force?: boolean }) => {
      const result = await callKicadScript("save_project", args);
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

  // Get project info tool
  server.tool(
    "get_project_info",
    "Get information about the current KiCAD project",
    {},
    async () => {
      const result = await callKicadScript("get_project_info", {});
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

  // Snapshot project tool — saves a named checkpoint as PDF/image
  server.tool(
    "snapshot_project",
    "Save a named checkpoint snapshot of the current project state (renders board to PDF and records step label). Call after completing each major step — e.g. after Step 1 (schematic_ok) and Step 2 (layout_ok). Required by the demo workflow before waiting for user confirmation.",
    {
      step: z.string().describe("Step number or identifier, e.g. '1' or '2'"),
      label: z
        .string()
        .describe("Short label for this checkpoint, e.g. 'schematic_ok' or 'layout_ok'"),
      prompt: z
        .string()
        .optional()
        .describe(
          "Full prompt text to save as PROMPT_step{step}_{timestamp}.md alongside the snapshot",
        ),
    },
    async (args: { step: string; label: string; prompt?: string }) => {
      const result = await callKicadScript("snapshot_project", args);
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
}
