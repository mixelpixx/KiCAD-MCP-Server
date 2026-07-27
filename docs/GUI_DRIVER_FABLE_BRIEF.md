# Fable brief — build the in-process wx GUI-driver into our MCP harness

Read `docs/GUI_DRIVER_SPEC.md` first (the why + both backends). This brief is the **verified,
concrete build** for Backend A (in-process wx, cross-platform) plus the AT-SPI fast-path
(Backend B). The core mechanism is already PROVEN on this machine (probe results below) — you
are wiring proven pieces into the MCP, not researching.

## PROVEN this session (don't re-derive)

A throwaway plugin `__init__.py` doing `import wx; wx.CallLater(3000, probe)` inside a live
pcbnew produced:

- `wx.GetTopLevelWindows()` → the `PcbFrame` (name `'PcbFrame'`, title `'PCB Editor'`).
- `frame.GetMenuBar()` → menus `[File, Edit, View, Place, Route, Inspect, Tools, Preferences, Help]`.
- **Recursing `menu.GetMenuItems()` (incl. `item.GetSubMenu()`) found plugin actions BY NAME
  with IDs:** under _Tools → External Plugins_: `Git Plugin` id=-2242, **`Open kiHarness`
  id=-2245**. → trigger with
  `frame.ProcessEvent(wx.CommandEvent(wx.wxEVT_COMMAND_MENU_SELECTED, item_id))`.
- `frame.GetToolBar()` returns **None** — KiCad uses **AUI toolbars**. Recurse `win.GetChildren()`,
  match `type(c).__name__` containing `AuiToolBar`; it exposed 27 tools via
  `GetToolCount()` + `FindToolByIndex(i)` → each a `.GetId()` (icon-only; names come from
  `.GetShortHelp()`/tooltip, not `.GetLabel()`). Trigger with `wxEVT_COMMAND_TOOL_CLICKED`.

## Architecture (fits our FastMCP harness)

Two processes, one thin channel:

1. **In-KiCad helper** — a tiny plugin (ship it the way kiHarness/Loom do: files at `plugins/`
   ROOT so they install to `<id>/`, per the packaging bug we just fixed). Its `__init__.py`
   starts a **background listener thread** on `127.0.0.1:<port>` (localhost TCP, JSON lines).
   Because wx is not thread-safe, the listener does NOT touch wx directly — it hands each
   command to the UI thread via `wx.CallAfter`, waits on a `threading.Event` for the result,
   and returns JSON. Commands: `tree`, `click {name|id, kind:menu|tool}`, `run_plugin {name}`,
   `wait_for {title,timeout}`, `screenshot`.
2. **MCP tools** (new `commands/gui_driver.py` + register in `kicad_mcp/server.py`) — thin
   clients that open the socket, send a command, return the response:
   - `kicad_gui_tree()` → menus/submenus (name+id) and AUI toolbars (id+tooltip).
   - `kicad_gui_click(name)` → resolve name→id in the helper, inject the wx event.
   - `kicad_run_action_plugin(name)` → find the External-Plugins submenu item by name, trigger it.
   - `kicad_gui_wait_for(title, timeout)` / `kicad_gui_screenshot()`.

This is a SECOND channel to KiCad, independent of kipy (kipy stays design-only). No upstream
KiCad changes — helper uses only public wx/pcbnew surface.

## Build steps

1. `helper/` (bundled, or its own PCM plugin): `__init__.py` → start listener; a `driver.py`
   with the verified wx introspection (menu recursion + AuiToolBar walk) and event injection,
   all executed under `wx.CallAfter`. Name→id resolution: menus by `GetItemLabelText()`,
   tools by `GetShortHelp()`.
2. `commands/gui_driver.py` — socket client + the tool functions.
3. Register the tools in `kicad_mcp/server.py` (match the existing `@mcp.tool` pattern).
4. Optional Backend B shim: `kicad_gui_tree_atspi()` / `kicad_gui_click_atspi()` using
   `gi.repository.Atspi` (no pip; enable `toolkit-accessibility`, launch with
   `GTK_MODULES=gail:atk-bridge`) — the Linux zero-in-KiCad path, for CI-style checks.
5. Test target: enumerate → find `Open kiHarness` → click it → assert the manager responds on
   `127.0.0.1:8761` (end-to-end proof the harness can drive a plugin button).

## Gotchas (learned)

- **UI-thread only** for wx calls (`wx.CallAfter`); the listener thread just queues.
- KiCad toolbars are AUI (`GetToolBar()` is None) — walk children for `AuiToolBar`.
- Toolbar buttons are icon-only → identify by `GetShortHelp()` (tooltip), not label.
- Menu/plugin actions DO have clean names → the reliable targeting path; prefer menu-item
  triggering over toolbar for plugin actions.
- Timing: query after the UI is built (`CallLater`/retry), not at plugin-scan time.

## Stretch (only if it lands cleanly): upstream

If this proves out in our fork, it could ride along with the PR #314 contribution before the
maintainer merges — but scope-check first (that PR is design-authoring tools; a GUI-driver is
a different capability and may belong in its own PR).

## DECISIONS (Ross, 2026-07-24) — action space + flagging + playbooks

**Action space (measured):** pcbnew = 302 actionable (215 menu items + 87 AUI toolbar tools);
eeschema adds ~similar. Every item is a clean `name → id`. So the surface is GENERIC +
scriptable — NO curated allow-list, the agent targets by name via `gui_tree`/`gui_click`.

**Destructive flagging = ADVISORY, NO GATING.** Classification of the 215 menu items:
15 destructive, 46 dialog-opening (`…` suffix), 154 plain. `gui_tree` output prepends a
`⚠ ` prefix to destructive names AND sets `destructive: true`; `gui_click` executes without
any confirm/allow-flag. Rationale: users back up projects; the prefix warning is the safeguard.
Seed destructive-label list: `docs/gui_destructive_seed.txt` (regex-derived — refine in build:
match by resolved KiCad ACTION where possible, not just label text, so it survives renames).

**Playbooks (a couple, thin wrappers over the generic surface — GUI-only, common):**

1. `kicad_pcb_snapshot()` — Zoom-to-Fit → `gui_screenshot()`. Visual board verification.
2. `kicad_reload_and_open_plugin(name)` — _Refresh Plugins_ → trigger the named External-Plugins
   item. The plugin dev/test loop (re-scan + launch).
3. `kicad_run_drc()` — open the DRC dialog → click _Run_ → scrape the violations grid → return
   structured results. Exercises the dialog-driving path (`wait_for` + child enumeration + click).

Keep playbooks as thin, named conveniences on top of the generic tools — not a framework. Add
more only if a GUI-only macro actually recurs.

## Self-install, no separate installer (Ross, 2026-07-24)

Do NOT ship the helper as a thing the user installs. The MCP **bundles** the helper
(`gui_driver_plugin/plugins/`) and **self-deploys** it:

- On any `gui_driver` tool call, if the listener socket doesn't answer, `ensure_helper_installed()`
  copies the bundled `plugins/*` into `~/.local/share/kicad/<ver>/3rdparty/plugins/<identifier>/`
  (glob the `<ver>` dir; use the **root-flatten** layout — files at `<id>/`, not `<id>/<name>/`;
  idempotent: write only if missing or a version marker is stale).
- The listener **auto-runs** as the `__init__.py` import side effect once KiCad scans the plugin —
  nothing to "start".
- KiCad must scan the freshly-dropped plugin ONCE: (1) return an actionable message
  ("helper installed → Tools → External Plugins → Refresh Plugins, or restart KiCad, then retry"),
  and (2) on Linux, optionally auto-trigger it via the **AT-SPI backend** (click Refresh Plugins) so
  it loads with no restart. Cross-platform falls back to the prompt.
- Bump a small `HELPER_VERSION` string; `ensure_helper_installed` re-deploys when it changes, so
  helper updates ship with the MCP with zero user action.

## Graceful degradation = REQUIRED (Ross, 2026-07-24) — verified

A dependency is acceptable; failing gracefully when the helper isn't loaded is NOT optional.
VERIFIED already-built: every tool routes through `_call()`, which catches `(OSError,
ConnectionError)` and returns `{"success": False, "error": "GUI-driver helper not reachable
on 127.0.0.1:<port> ... Is KiCad running with the plugin installed?"}` — instant (Connection
refused is not a timeout), no exception, no hang; playbooks wrap the same cause in their own
`success:False`. This is the baseline contract for every gui_driver tool. The self-install
above is now a NICE-TO-HAVE (reduce friction), NOT the reliance — the graceful error + install
hint is the required behavior.

## Non-Linux / cross-platform (Ross, 2026-07-24)

**Backend A (in-process wx) IS the cross-platform core** — Windows/macOS/Linux by construction
(all wx inside KiCad: menu/AUI enumeration, `ProcessEvent` injection, localhost socket,
`wx.CallAfter`). Target BY NAME (resolve name→id at call time) so per-OS ID/layout differences
don't matter. Backend B (AT-SPI) is a LINUX-ONLY accelerator; off Linux you simply use A — it
covers the same enumerate+click surface, in-process. Graceful failure is socket-only → portable.
Build-order note: A is the portable REQUIREMENT (build/verify it everywhere); B is the Linux
fast-path, optional.

**Per-OS work (verified only on Linux so far; needs a Win/Mac pass):**

- **Plugin dir per OS** for `ensure_helper_installed` + docs: Win `%APPDATA%\kicad\<ver>\3rdparty\plugins`,
  macOS `~/Library/Preferences/kicad/<ver>/3rdparty/plugins`, Linux `~/.local/share/kicad/<ver>/3rdparty/plugins`.
- **macOS global menu bar** — Preferences/Quit/About relocate to the app menu; wx still exposes
  them but the tree shape shifts; verify enumeration finds them.
- **Screenshot** — `wx.ScreenDC` is reliable on Win/Mac; the black-blit fallback is a
  Linux-Wayland issue only.
- **AT-SPI auto-refresh** nicety → prompt fallback off Linux.
