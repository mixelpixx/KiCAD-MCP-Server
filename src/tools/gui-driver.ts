/**
 * GUI-driver tools for the KiCAD MCP server.
 *
 * A SECOND channel to KiCad, independent of kipy/design content: an in-process
 * wx helper (gui_driver_plugin/) reached over a localhost socket lets an agent
 * enumerate and activate GUI chrome — menus, AUI toolbars, plugin buttons,
 * dialogs — plus a Linux AT-SPI fast-path. Every tool degrades gracefully
 * (returns {success:false} instantly) when the helper isn't reachable; the
 * Python side self-installs the helper on first call. Destructive menu names
 * are advisory-flagged with a "⚠ " prefix by kicad_gui_tree — never gated.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { logger } from "../logger.js";

export function registerGuiDriverTools(server: McpServer, callKicadScript: Function) {
  const asText = (result: any) => ({
    content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
  });

  const frame = z
    .string()
    .optional()
    .describe(
      "Optional frame name/title filter (e.g. 'PcbFrame', 'Schematic'). Default: main frame.",
    );

  // --- Backend A: in-process wx (cross-platform core) ---
  server.tool(
    "kicad_gui_tree",
    "Enumerate the live KiCad GUI via the in-process helper: menus/submenus (name + wx id) and AUI toolbars (id + tooltip). Destructive names carry a '⚠ ' prefix.",
    { frame },
    async (args: { frame?: string }) => asText(await callKicadScript("kicad_gui_tree", args)),
  );

  server.tool(
    "kicad_gui_click",
    "Activate a menu item or AUI toolbar tool by name (as shown by kicad_gui_tree). Executes immediately — no gating.",
    {
      name: z.string().optional().describe("Menu label or toolbar tooltip to activate."),
      id: z.number().int().optional().describe("Explicit wx item id (skips name resolution)."),
      kind: z.string().optional().describe("Item kind when passing an explicit id (default menu)."),
      frame,
    },
    async (args: { name?: string; id?: number; kind?: string; frame?: string }) =>
      asText(await callKicadScript("kicad_gui_click", args)),
  );

  server.tool(
    "kicad_run_action_plugin",
    "Find the Tools > External Plugins submenu entry with the given name (e.g. 'Open kiHarness') and trigger it.",
    {
      name: z.string().describe("Plugin menu entry name."),
      frame,
    },
    async (args: { name: string; frame?: string }) =>
      asText(await callKicadScript("kicad_run_action_plugin", args)),
  );

  server.tool(
    "kicad_gui_wait_for",
    "Poll until a shown top-level window whose title contains `title` exists (or timeout).",
    {
      title: z.string().describe("Substring of the window title to wait for."),
      timeout: z.number().optional().describe("Seconds to wait (default 10)."),
    },
    async (args: { title: string; timeout?: number }) =>
      asText(await callKicadScript("kicad_gui_wait_for", args)),
  );

  server.tool(
    "kicad_gui_screenshot",
    "Capture the driven frame's screen rectangle to a PNG and return its path.",
    {
      path: z.string().optional().describe("Output PNG path (temp file if omitted)."),
      frame,
    },
    async (args: { path?: string; frame?: string }) =>
      asText(await callKicadScript("kicad_gui_screenshot", args)),
  );

  // --- GUI playbooks (thin wrappers over the generic surface) ---
  server.tool(
    "kicad_pcb_snapshot",
    "GUI playbook: trigger Zoom to Fit, wait for the repaint, screenshot the frame.",
    {
      path: z.string().optional().describe("Output PNG path (temp file if omitted)."),
      settle: z.number().optional().describe("Seconds to wait after zoom (default 0.5)."),
      frame,
    },
    async (args: { path?: string; settle?: number; frame?: string }) =>
      asText(await callKicadScript("kicad_pcb_snapshot", args)),
  );

  server.tool(
    "kicad_reload_and_open_plugin",
    "GUI playbook (plugin dev/test loop): trigger Refresh Plugins, then open the named External-Plugins entry.",
    {
      name: z.string().describe("Plugin menu entry to open after the refresh."),
      settle: z.number().optional().describe("Seconds to wait after refresh (default 1)."),
      frame,
    },
    async (args: { name: string; settle?: number; frame?: string }) =>
      asText(await callKicadScript("kicad_reload_and_open_plugin", args)),
  );

  server.tool(
    "kicad_run_drc",
    "GUI playbook: open the Design Rules Checker dialog, click 'Run DRC', then scrape the violations grid into structured results.",
    {
      dialogTitle: z.string().optional().describe("Dialog title substring (default 'DRC')."),
      timeout: z.number().optional().describe("Seconds to wait for the dialog (default 15)."),
      runTimeout: z.number().optional().describe("Seconds to wait for results (default 60)."),
      frame,
    },
    async (args: { dialogTitle?: string; timeout?: number; runTimeout?: number; frame?: string }) =>
      asText(await callKicadScript("kicad_run_drc", args)),
  );

  // --- Backend B: AT-SPI (Linux zero-in-KiCad fast-path) ---
  server.tool(
    "kicad_gui_tree_atspi",
    "Backend B: dump KiCad's accessible widget tree (role + name) from the Linux a11y bus — zero in-KiCad code.",
    {
      app: z.string().optional().describe("Accessible application name filter (default 'kicad')."),
      maxDepth: z.number().int().optional().describe("Recursion depth limit (default 12)."),
    },
    async (args: { app?: string; maxDepth?: number }) =>
      asText(await callKicadScript("kicad_gui_tree_atspi", args)),
  );

  server.tool(
    "kicad_gui_click_atspi",
    "Backend B: activate the first accessible node matching `name` (and optional role) via do_action.",
    {
      name: z.string().describe("Accessible name to activate."),
      role: z
        .string()
        .optional()
        .describe("Optional role substring filter (e.g. 'push button', 'menu item')."),
      app: z.string().optional().describe("Accessible application name filter (default 'kicad')."),
    },
    async (args: { name: string; role?: string; app?: string }) =>
      asText(await callKicadScript("kicad_gui_click_atspi", args)),
  );

  logger.info("GUI-driver tools registered");
}
