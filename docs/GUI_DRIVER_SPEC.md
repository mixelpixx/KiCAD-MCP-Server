# GUI-driver capability for the KiCad MCP harness — spec

_Backlog spec, opened 2026-07-24. Proven value this session: AT-SPI both (a) demonstrated
click-by-name on a live pcbnew and (b) DIAGNOSED the invisible-plugin-button bug by showing
which ActionPlugins actually registered ("Git Plugin" present, "Open Loom"/"Open kiHarness"
absent) — something `kipy` cannot see. Goal: end-to-end GUI verification (toolbars, menus,
dialogs, plugin buttons) to complement `kipy` (design-content only)._

**Multi-platform is a GOAL, not a hard requirement** (Ross): ship a Linux fast-path now, keep
the MCP tool interface OS-agnostic so a cross-platform backend can slot in.

## The kipy boundary (why this is needed)

`kipy` manipulates the _design_ (board/schematic objects). It does NOT touch GUI chrome —
you can't ask it "is the Open kiHarness button present?", click a menu item, or drive a dialog.
The PCB/schematic **canvas is one opaque widget** to any GUI-a11y layer, so the split is clean:
**kipy = design content, gui-driver = chrome.**

## Backend A — in-process native (CROSS-PLATFORM, preferred long-term)

KiCad's own Python has **wx 4.2.1 (Phoenix)** importable, and `pcbnew` exposes `ActionPlugin`,
`LoadPlugins`, `GetPluginForPath`, `IsActionRunning`. Because **wxWidgets is cross-platform**,
a helper running _inside_ KiCad works on Linux/Windows/macOS:

- Walk `wx.GetTopLevelWindows()` → frame → `GetToolBar()`/`GetMenuBar()`; find a tool/menu by
  label or id; trigger it by posting a `wx.CommandEvent(wx.wxEVT_COMMAND_TOOL_CLICKED, id)` to
  `frame.ProcessEvent(evt)` — a real activation, no pixel coordinates.
- For plugin actions specifically, invoke the registered `ActionPlugin.Run()` directly.
- **Needs:** a tiny helper loaded inside KiCad (a bundled ActionPlugin or a scripting-console
  bootstrap) + a control channel between the MCP and the helper (local socket / named pipe /
  watched file). The MCP sends "click X" / "dump tree"; the helper executes in KiCad's UI thread.
- **Ours to build, no upstream:** KiCad already exposes Python + wx to plugins, so the
  helper uses only public surface — no KiCad C++ changes. Same delivery pattern as
  kiHarness/Loom: a PCM plugin whose `__init__.py` starts a background listener on KiCad
  launch; commands marshal to the UI thread via `wx.CallAfter`. The ONLY upstream-y option
  is exposing KiCad's `TOOL_ACTION` 'run-by-name' registry to Python — optional; the
  wx-event path doesn't need it.
- **Trade-off:** must run code in-process (deploy a helper); introspecting wx toolbars is a bit
  fiddly (labels/ids), but it's the only path that is both native and cross-platform.

## Backend B — AT-SPI (Linux-only, external, zero-in-process) — VERIFIED

The Linux accessibility bus; screen-reader tech. GTK/Qt/wx apps publish their widget tree.

- Binding ships with the OS: `from gi.repository import Atspi` (GObject-introspection, **no pip**).
- Enable once: `gsettings set org.gnome.desktop.interface toolkit-accessibility true`; launch
  the app with the bridge (`GTK_MODULES=gail:atk-bridge`).
- `Atspi.init()` → `get_desktop(0)` → find app → recurse; each node has a **role**
  (`push button`, `menu item`, `dialog`, `text`) + **name**. Click = `node.do_action(0)`
  (press/activate). Also read/set text, query states (enabled/focused/checked).
- **Pro:** external, black-box, touches nothing in KiCad — ideal for CI-style "did the button
  appear + do the right thing" checks. **Con:** Linux-only (Windows=UIAutomation,
  macOS=AXUIElement would be separate adapters).

## The "read a UI file" question (Ross)

- There is **no live rendered-UI dump file** KiCad writes.
- BUT `plugin.json` **is** the declarative UI definition for API plugins (actions, buttons,
  scopes) — reading it on disk tells you what _should_ register (that's how the button bug was
  diagnosed). Static, not live.
- Live rendered state is only introspectable in-process (Backend A's wx/plugin registry) or via
  the a11y tree (Backend B). No file shortcut.
- **Patching KiCad's C++** to expose the tool-manager / a test hook is possible but impractical
  (build-from-source + maintenance) — rejected.

## Proposed MCP tool surface (backend-agnostic)

- `kicad_gui_tree()` → the clickable widget tree (roles + names), so an agent can _see_ the GUI.
- `kicad_gui_click(name|path)` → find + activate by name.
- `kicad_gui_set_text(name, value)` / `kicad_gui_wait_for(title, timeout)` → drive dialogs.
- `kicad_gui_screenshot()` → capture for visual verification.
- (Optional) `kicad_run_action_plugin(identifier)` → invoke a plugin's action directly (Backend A).

## Recommended build order

1. **Backend B (AT-SPI) first** — already proven, zero in-KiCad code, unblocks Linux GUI
   verification immediately (and would have caught the button regression in CI).
2. **Backend A (in-process wx)** — the cross-platform core; the helper + control channel is the
   real work. Design the tool interface now so B and A are swappable behind it.
3. Windows/macOS a11y adapters (UIAutomation / AXUIElement) only if/when needed.

Could live as a small standalone **`gui-driver` MCP** (useful for ANY GTK/wx/Qt app, not just
KiCad) or as tools inside the existing KiCad MCP.
