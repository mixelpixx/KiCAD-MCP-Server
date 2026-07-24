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

  server.tool(
    "open_board",
    "Open a specific .kicad_pcb board file and refresh the MCP in-memory board state.",
    {
      boardPath: z.string().describe("Path to the .kicad_pcb file to open"),
    },
    async (args: { boardPath: string }) => {
      const result = await callKicadScript("open_board", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  server.tool(
    "reload_board",
    "Reload the current or specified .kicad_pcb from disk, discarding stale in-memory board state.",
    {
      boardPath: z
        .string()
        .optional()
        .describe("Optional .kicad_pcb path; defaults to current board"),
    },
    async (args: { boardPath?: string }) => {
      const result = await callKicadScript("reload_board", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
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

  server.tool(
    "save_board",
    "Save the current PCB board. Refuses to overwrite external disk edits unless force=true.",
    {
      boardPath: z.string().optional().describe("Optional destination .kicad_pcb path"),
      force: z
        .boolean()
        .optional()
        .describe("Overwrite even if the board changed externally on disk"),
    },
    async (args: { boardPath?: string; force?: boolean }) => {
      const result = await callKicadScript("save_board", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  server.tool(
    "save_as",
    "Save the current PCB board to a new .kicad_pcb path.",
    {
      boardPath: z.string().describe("Destination .kicad_pcb path"),
    },
    async (args: { boardPath: string }) => {
      const result = await callKicadScript("save_as", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  server.tool(
    "is_dirty",
    "Return whether the MCP knows the loaded board has unsaved memory changes or external disk changes.",
    {},
    async () => {
      const result = await callKicadScript("is_dirty", {});
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  server.tool(
    "discard_or_reload",
    "Discard the current in-memory PCB state and reload the board from disk.",
    {
      boardPath: z
        .string()
        .optional()
        .describe("Optional .kicad_pcb path; defaults to current board"),
    },
    async (args: { boardPath?: string }) => {
      const result = await callKicadScript("discard_or_reload", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
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
