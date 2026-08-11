/**
 * Project management tools for KiCAD MCP server
 */
import { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";
import { registerKiCadTool, type CommandFunction, withToolSignal } from "./tool-registration.js";

export function registerProjectTools(server: McpServer, callKicadScript: CommandFunction) {
  callKicadScript = withToolSignal(callKicadScript);
  // Create project tool
  registerKiCadTool(
    server,
    "project",
    "create_project",
    {
      description: "Create a new KiCAD project",
      inputSchema: z.object({
        path: z.string().describe("Project directory path"),
        name: z.string().describe("Project name"),
      }),
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
  registerKiCadTool(
    server,
    "project",
    "open_project",
    {
      description: "Open an existing KiCAD project",
      inputSchema: z.object({
        filename: z.string().describe("Path to .kicad_pro or .kicad_pcb file"),
      }),
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

  registerKiCadTool(
    server,
    "project",
    "open_board",
    {
      description:
        "Open a specific .kicad_pcb board file and refresh the MCP in-memory board state.",
      inputSchema: z.object({
        boardPath: z.string().describe("Path to the .kicad_pcb file to open"),
      }),
    },
    async (args: { boardPath: string }) => {
      const result = await callKicadScript("open_board", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  registerKiCadTool(
    server,
    "project",
    "reload_board",
    {
      description:
        "Reload the current or specified .kicad_pcb from disk, discarding stale in-memory board state.",
      inputSchema: z.object({
        boardPath: z
          .string()
          .optional()
          .describe("Optional .kicad_pcb path; defaults to current board"),
      }),
    },
    async (args: { boardPath?: string }) => {
      const result = await callKicadScript("reload_board", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // Close project tool
  registerKiCadTool(
    server,
    "project",
    "close_project",
    {
      description:
        "Close the currently loaded KiCAD project: optionally save, then drop the in-memory board and clear session state. Use this to hand control back so the user (or the agent) can edit project files directly without the MCP later clobbering those changes on save.",
      inputSchema: z.object({
        save: z
          .boolean()
          .optional()
          .describe(
            "Save the board to disk before closing (default true). If false and there are unsaved changes, the close proceeds but the response warns they were discarded.",
          ),
        forceExternalChanges: z
          .boolean()
          .optional()
          .describe("Save despite external changes to the loaded SWIG board file"),
        force: z
          .boolean()
          .optional()
          .describe("Backward-compatible alias for forceExternalChanges"),
      }),
    },
    async (args: { save?: boolean; force?: boolean; forceExternalChanges?: boolean }) => {
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
  registerKiCadTool(
    server,
    "project",
    "save_project",
    {
      description:
        "Save the current KiCAD project. Refuses to overwrite the board file if its " +
        "contents changed on disk since load (external edit) unless force is true.",
      inputSchema: z.object({
        path: z.string().optional().describe("Optional new path to save to"),
        force: z
          .boolean()
          .optional()
          .describe(
            "Overwrite the loaded board file even if its on-disk contents changed externally",
          ),
        forceExternalChanges: z
          .boolean()
          .optional()
          .describe("Explicit alias for force; takes precedence when both are provided"),
        overwrite: z
          .boolean()
          .optional()
          .describe("Replace an existing destination when path points to a different file"),
      }),
    },
    async (args: {
      path?: string;
      force?: boolean;
      forceExternalChanges?: boolean;
      overwrite?: boolean;
    }) => {
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

  registerKiCadTool(
    server,
    "project",
    "save_board",
    {
      description:
        "Save the current PCB board. Refuses to overwrite external disk edits unless force=true.",
      inputSchema: z.object({
        boardPath: z.string().optional().describe("Optional destination .kicad_pcb path"),
        force: z
          .boolean()
          .optional()
          .describe("Overwrite even if the board changed externally on disk"),
        forceExternalChanges: z.boolean().optional().describe("Explicit alias for force"),
        overwrite: z
          .boolean()
          .optional()
          .describe("Replace boardPath if it already exists and differs from the current board"),
      }),
    },
    async (args: {
      boardPath?: string;
      force?: boolean;
      forceExternalChanges?: boolean;
      overwrite?: boolean;
    }) => {
      const result = await callKicadScript("save_board", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  registerKiCadTool(
    server,
    "project",
    "save_as",
    {
      description: "Save the current PCB board to a new .kicad_pcb path.",
      inputSchema: z.object({
        boardPath: z.string().describe("Destination .kicad_pcb path"),
        overwrite: z.boolean().optional().describe("Replace the destination if it already exists"),
        force: z
          .boolean()
          .optional()
          .describe("Allow saving over external changes to the loaded file"),
        forceExternalChanges: z
          .boolean()
          .optional()
          .describe("Explicit alias for force; takes precedence when both are provided"),
      }),
    },
    async (args: {
      boardPath: string;
      overwrite?: boolean;
      force?: boolean;
      forceExternalChanges?: boolean;
    }) => {
      const result = await callKicadScript("save_as", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  registerKiCadTool(
    server,
    "project",
    "is_dirty",
    {
      description:
        "Return whether the MCP knows the loaded board has unsaved memory changes or external disk changes.",
      inputSchema: z.object({}),
    },
    async () => {
      const result = await callKicadScript("is_dirty", {});
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  registerKiCadTool(
    server,
    "project",
    "discard_or_reload",
    {
      description: "Discard the current in-memory PCB state and reload the board from disk.",
      inputSchema: z.object({
        boardPath: z
          .string()
          .optional()
          .describe("Optional .kicad_pcb path; defaults to current board"),
      }),
    },
    async (args: { boardPath?: string }) => {
      const result = await callKicadScript("discard_or_reload", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // Get project info tool
  registerKiCadTool(
    server,
    "project",
    "get_project_info",
    { description: "Get information about the current KiCAD project", inputSchema: z.object({}) },
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
  registerKiCadTool(
    server,
    "project",
    "snapshot_project",
    {
      description:
        "Save a named checkpoint snapshot of the current project state (renders board to PDF and records step label). Call after completing each major step — e.g. after Step 1 (schematic_ok) and Step 2 (layout_ok). Required by the demo workflow before waiting for user confirmation.",
      inputSchema: z.object({
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
      }),
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
