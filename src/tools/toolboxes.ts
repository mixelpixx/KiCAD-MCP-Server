/**
 * Toolboxes: start a client with a small core of tools and let it open the
 * rest in groups, instead of loading every tool definition up front.
 *
 * Why. The server registers about 250 tools. Every definition a client loads
 * costs context, and some clients cap the count: VS Code Copilot stops at 128
 * (discussion #446). The registry already groups the tools into categories; in
 * toolbox mode each category is a toolbox the agent can open and close.
 *
 * How. Every tool stays registered with the MCP server as a real tool with its
 * own schema. Toolbox mode only flips each tool's `enabled` flag, which the SDK
 * honours in tools/list and tools/call, and announces the change with one
 * notifications/tools/list_changed so the client re-reads the list. An opened
 * tool reaches the model exactly like any other. The first gated design routed
 * every call through a single execute_tool instead, and the model invented
 * arguments for tools whose schemas it had never seen (see router.ts).
 *
 * Clients (checked 2026-10-01). Claude Code and VS Code Copilot re-read the
 * list, but the model can call the new tools from the user's next message, not
 * in the turn that opened them. Claude Desktop ignores the notification until
 * it is restarted. Toolboxes named in KICAD_MCP_TOOLBOXES are open from the
 * start, which works in every client.
 *
 * KICAD_MCP_TOOLBOXES:
 *   unset or "all"   every tool visible: the default, and the behaviour before toolboxes
 *   "core"           the core tools and the toolbox controls; open the rest on demand
 *   "schematic,drc"  toolbox mode with those toolboxes open from the start
 */

import type { McpServer, RegisteredTool } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { directToolNames, getAllCategories, getCategory, getToolCategory } from "./registry.js";

export const TOOLBOXES_ENV = "KICAD_MCP_TOOLBOXES";

/** Visible only in toolbox mode: with every tool visible there is nothing to open. */
const TOOLBOX_CONTROLS = new Set(["list_toolboxes", "open_toolbox", "close_toolbox"]);
/** Visible only when every tool is: list_toolboxes covers them in toolbox mode. */
const CATEGORY_BROWSERS = new Set(["list_tool_categories", "get_category_tools"]);
/** Visible in toolbox mode whatever is open. */
const CORE = new Set<string>([...directToolNames, "search_tools"]);

export type ToolboxSetting =
  | { mode: "all" }
  | { mode: "toolboxes"; preload: string[]; unknown: string[] };

/** Toolbox names match case-insensitively, with "-" and "_" interchangeable. */
function normalise(name: string): string {
  return name.trim().toLowerCase().replace(/-/g, "_");
}

/** The toolbox a user-supplied name refers to, or undefined. */
export function resolveToolbox(name: string): string | undefined {
  const wanted = normalise(name);
  return getAllCategories().find((category) => normalise(category.name) === wanted)?.name;
}

/** Read a KICAD_MCP_TOOLBOXES value. An unknown name is reported, not fatal. */
export function parseToolboxSetting(raw: string | undefined): ToolboxSetting {
  const names = (raw ?? "")
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
  if (names.length === 0 || names.some((name) => name.toLowerCase() === "all")) {
    return { mode: "all" };
  }
  const preload: string[] = [];
  const unknown: string[] = [];
  for (const name of names) {
    if (name.toLowerCase() === "core") continue;
    const toolbox = resolveToolbox(name);
    if (toolbox === undefined) unknown.push(name);
    else if (!preload.includes(toolbox)) preload.push(toolbox);
  }
  return { mode: "toolboxes", preload, unknown };
}

/** The outcome of opening or closing toolboxes. */
export interface ToolboxChange {
  /** Toolboxes whose state changed. */
  changed: string[];
  /** Toolboxes that were already in the requested state. */
  unchanged: string[];
  /** Names that are not toolboxes. */
  unknown: string[];
}

export class ToolboxManager {
  private readonly handles = new Map<string, RegisteredTool>();
  private readonly open = new Set<string>();

  constructor(
    private readonly server: McpServer,
    readonly setting: ToolboxSetting,
  ) {
    if (setting.mode === "toolboxes") {
      for (const toolbox of setting.preload) this.open.add(toolbox);
    }
  }

  get toolboxMode(): boolean {
    return this.setting.mode === "toolboxes";
  }

  /**
   * Keep the handle of every tool registered from now on, so its visibility
   * can be switched later. Call before the register*Tools functions run.
   * Wrapping the two registration methods avoids reading the SDK's private
   * tool table, which the 2.x SDK may lay out differently.
   */
  captureRegistrations(): void {
    const target = this.server as unknown as Record<string, unknown>;
    for (const method of ["tool", "registerTool"]) {
      const original = target[method];
      if (typeof original !== "function") continue;
      target[method] = (...args: unknown[]): RegisteredTool => {
        const handle = (original as (...a: unknown[]) => RegisteredTool).apply(this.server, args);
        if (typeof args[0] === "string") this.handles.set(args[0], handle);
        return handle;
      };
    }
  }

  isOpen(toolbox: string): boolean {
    return this.setting.mode === "all" || this.open.has(toolbox);
  }

  openToolboxes(): string[] {
    return getAllCategories()
      .map((category) => category.name)
      .filter((name) => this.open.has(name));
  }

  /** Whether a tool is in the client's list under the current setting. */
  isVisible(tool: string): boolean {
    if (this.setting.mode === "all") return !TOOLBOX_CONTROLS.has(tool);
    if (CORE.has(tool) || TOOLBOX_CONTROLS.has(tool)) return true;
    if (CATEGORY_BROWSERS.has(tool)) return false;
    const toolbox = getToolCategory(tool);
    return toolbox !== undefined && this.open.has(toolbox);
  }

  /**
   * Bring every tool's enabled flag in line with isVisible, and announce the
   * change once. RegisteredTool.enable() would send one notification per tool,
   * a burst of dozens for a single toolbox. sendToolListChanged() does nothing
   * while no client is connected, so the call at startup is silent.
   */
  applyVisibility(): number {
    let changed = 0;
    for (const [name, handle] of this.handles) {
      const visible = this.isVisible(name);
      if (handle.enabled !== visible) {
        handle.enabled = visible;
        changed++;
      }
    }
    if (changed > 0) this.server.sendToolListChanged();
    return changed;
  }

  visibleToolNames(): string[] {
    return [...this.handles.keys()].filter((name) => this.isVisible(name));
  }

  /** The first sentence of a tool's description, for open_toolbox replies. */
  shortDescription(tool: string): string {
    const description = this.handles.get(tool)?.description ?? "";
    const first = description.split(/(?<=\.)\s/)[0] ?? "";
    return first.length > 160 ? `${first.slice(0, 157)}...` : first;
  }

  /** Open or close toolboxes, and update the client's tool list if anything changed. */
  setOpen(names: string[], open: boolean): ToolboxChange {
    const change: ToolboxChange = { changed: [], unchanged: [], unknown: [] };
    for (const name of names) {
      const toolbox = resolveToolbox(name);
      if (toolbox === undefined) {
        change.unknown.push(name);
      } else if (this.open.has(toolbox) === open) {
        if (!change.unchanged.includes(toolbox)) change.unchanged.push(toolbox);
      } else {
        if (open) this.open.add(toolbox);
        else this.open.delete(toolbox);
        change.changed.push(toolbox);
      }
    }
    if (change.changed.length > 0) this.applyVisibility();
    return change;
  }

  /** One line for the server log. */
  describe(): string {
    const visible = this.visibleToolNames().length;
    if (this.setting.mode === "all") {
      return `All ${visible} tools visible (set ${TOOLBOXES_ENV} to use toolboxes)`;
    }
    const open = this.openToolboxes();
    return (
      `Toolbox mode: ${visible} of ${this.handles.size} tools visible; ` +
      `open toolboxes: ${open.length > 0 ? open.join(", ") : "none"}`
    );
  }
}

function json(value: unknown, isError = false) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value, null, 2) }],
    ...(isError ? { isError: true } : {}),
  };
}

const AFTER_OPENING =
  "The client re-reads its tool list when it changes. In Claude Code and VS Code the new " +
  "tools can be called from the user's next message, not in this turn, so tell the user " +
  "which toolbox you opened. Claude Desktop only re-reads the list when it is restarted: " +
  `there, ask the user to add the toolbox to ${TOOLBOXES_ENV} in the server configuration.`;

/** Register list_toolboxes, open_toolbox and close_toolbox. Hidden unless toolbox mode is on. */
export function registerToolboxTools(server: McpServer, toolboxes: ToolboxManager): void {
  server.tool(
    "list_toolboxes",
    "List the toolboxes: groups of related KiCad tools, each with a description, its tools, and whether it is open. Your tool list holds the core tools plus the tools of open toolboxes; open a toolbox with open_toolbox to add its tools.",
    {},
    async () =>
      json({
        open_toolboxes: toolboxes.openToolboxes(),
        toolboxes: getAllCategories().map((category) => ({
          name: category.name,
          description: category.description,
          open: toolboxes.isOpen(category.name),
          tool_count: category.tools.length,
          tools: category.tools,
        })),
        core_tools: directToolNames,
        note: "Open the toolboxes a task needs with open_toolbox before calling their tools. A tool in a closed toolbox is rejected as disabled.",
      }),
  );

  server.tool(
    "open_toolbox",
    "Open one or more toolboxes (see list_toolboxes) to add their tools to your tool list. In most clients the new tools can be called from the user's next message, not in the current turn, so open what a task needs before starting it.",
    {
      toolboxes: z
        .array(z.string())
        .min(1)
        .describe('Toolbox names from list_toolboxes, for example ["routing"]'),
    },
    async ({ toolboxes: names }) => {
      const change = toolboxes.setOpen(names, true);
      const ready = [...change.changed, ...change.unchanged];
      return json(
        {
          opened: change.changed,
          already_open: change.unchanged,
          unknown: change.unknown,
          ...(change.unknown.length > 0
            ? { available_toolboxes: getAllCategories().map((category) => category.name) }
            : {}),
          tools: Object.fromEntries(
            ready.map((name) => [
              name,
              (getCategory(name)?.tools ?? []).map((tool) => ({
                name: tool,
                description: toolboxes.shortDescription(tool),
              })),
            ]),
          ),
          ...(change.changed.length > 0 ? { note: AFTER_OPENING } : {}),
        },
        ready.length === 0,
      );
    },
  );

  server.tool(
    "close_toolbox",
    "Close one or more toolboxes to remove their tools from your tool list and free context. The core tools stay.",
    {
      toolboxes: z.array(z.string()).min(1).describe("Toolbox names to close"),
    },
    async ({ toolboxes: names }) => {
      const change = toolboxes.setOpen(names, false);
      return json(
        {
          closed: change.changed,
          not_open: change.unchanged,
          unknown: change.unknown,
          open_toolboxes: toolboxes.openToolboxes(),
        },
        change.changed.length === 0 && change.unchanged.length === 0,
      );
    },
  );
}
