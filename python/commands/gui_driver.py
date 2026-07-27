"""GUI-driver MCP tools — the second channel to KiCad (chrome, not design).

Thin socket clients for the in-KiCad helper plugin (``gui_driver_plugin/`` in
this repo; installs to ``3rdparty/plugins/<id>/``). The helper listens on
``127.0.0.1:$KICAD_GUI_DRIVER_PORT`` (default 8770), JSON lines: one request
object per line in, one ``{"ok": bool, ...}`` response line back. All wx work
happens on KiCad's UI thread inside the helper; this side is pure sockets.

Surface (locked decisions, docs/GUI_DRIVER_FABLE_BRIEF.md):

* GENERIC scriptable surface — no curated allow-list. Agents look with
  ``kicad_gui_tree`` and act with ``kicad_gui_click`` by name.
* Destructive flagging is ADVISORY ONLY: tree entries matching the seed list
  get ``destructive: true`` and a ``"⚠ "`` name prefix; ``kicad_gui_click``
  executes without any confirm/gate.
* Playbooks (``kicad_pcb_snapshot``, ``kicad_reload_and_open_plugin``,
  ``kicad_run_drc``) stay thin conveniences over the generic tools.

Backend B (Linux AT-SPI, zero-in-KiCad) rides along as
``kicad_gui_tree_atspi`` / ``kicad_gui_click_atspi``; needs
``gsettings set org.gnome.desktop.interface toolkit-accessibility true`` and
KiCad launched with ``GTK_MODULES=gail:atk-bridge``.

Boundary: this module never imports kipy/pcbnew — kipy stays design-only.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("kicad_interface")

DEFAULT_PORT = 8770
DESTRUCTIVE_PREFIX = "⚠ "

# -- helper self-install -----------------------------------------------------
#
# The MCP bundles the in-KiCad helper (gui_driver_plugin/plugins/ in this repo)
# and self-deploys it into KiCad's 3rdparty plugin tree on connect failure —
# no separate installer. Bump HELPER_VERSION whenever the bundled helper
# changes; ensure_helper_installed() re-deploys on a marker mismatch, so
# helper updates ship with the MCP with zero user steps.

HELPER_VERSION = "0.0.2"  # 0.0.2: run_plugin triggers async (no UI-thread block/timeout)
HELPER_IDENTIFIER = "com_github_rossvonfange_kicad-gui-driver"
HELPER_VERSION_MARKER = "HELPER_VERSION"


def _bundled_helper_dir() -> Path:
    """The helper sources shipped with this repo/wheel (root-flatten source)."""
    return Path(__file__).resolve().parents[2] / "gui_driver_plugin" / "plugins"


def kicad_plugin_dirs(
    platform: Optional[str] = None,
    environ: Optional[Dict[str, str]] = None,
    home: Optional[Path] = None,
) -> List[Path]:
    """Per-OS ``<kicad-data>/<ver>/3rdparty/plugins`` dirs, one per KiCad version.

    Resolution (args are injectable for tests; defaults are the live OS):
    * Linux   ``~/.local/share/kicad/<ver>/3rdparty/plugins``
    * Windows ``%APPDATA%\\kicad\\<ver>\\3rdparty\\plugins``
    * macOS   ``~/Library/Preferences/kicad/<ver>/3rdparty/plugins``

    The ``<ver>`` dir is globbed (e.g. ``9.0``); only versions the user has
    actually run KiCad with exist, and those are the ones returned.
    """
    platform = platform if platform is not None else sys.platform
    environ = environ if environ is not None else dict(os.environ)
    home = home if home is not None else Path.home()
    if platform.startswith("win"):
        appdata = environ.get("APPDATA")
        base = Path(appdata) / "kicad" if appdata else None
    elif platform == "darwin":
        base = home / "Library" / "Preferences" / "kicad"
    else:
        base = home / ".local" / "share" / "kicad"
    if base is None or not base.is_dir():
        return []
    return sorted(
        ver / "3rdparty" / "plugins" for ver in base.glob("[0-9]*.[0-9]*") if ver.is_dir()
    )


def ensure_helper_installed(
    plugin_dirs: Optional[List[Path]] = None,
    bundled: Optional[Path] = None,
) -> Dict[str, Any]:
    """Self-deploy the bundled helper into every KiCad version's plugin tree.

    ROOT-FLATTEN layout (the packaging bug we fixed once): the bundled
    ``plugins/*`` files land directly at ``<plugins-dir>/<identifier>/`` —
    NOT nested another level down — matching how PCM installs the zip's
    ``plugins/`` contents. Idempotent: a dir is (re)written only when the
    ``HELPER_VERSION`` marker file is missing or differs from this MCP's
    :data:`HELPER_VERSION`.

    Returns ``{"installed": [dirs written], "current": [dirs already OK]}``.
    """
    bundled = bundled if bundled is not None else _bundled_helper_dir()
    if plugin_dirs is None:
        plugin_dirs = kicad_plugin_dirs()
    installed: List[str] = []
    current: List[str] = []
    if not bundled.is_dir():
        return {"installed": installed, "current": current}
    for plugins_dir in plugin_dirs:
        target = plugins_dir / HELPER_IDENTIFIER
        marker = target / HELPER_VERSION_MARKER
        try:
            if marker.is_file() and marker.read_text(encoding="utf-8").strip() == HELPER_VERSION:
                current.append(str(target))
                continue
            target.mkdir(parents=True, exist_ok=True)
            for src in bundled.iterdir():
                if src.name == "__pycache__":
                    continue
                if src.is_dir():
                    shutil.copytree(src, target / src.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, target / src.name)
            marker.write_text(HELPER_VERSION + "\n", encoding="utf-8")
            installed.append(str(target))
        except OSError as exc:  # never let self-install break the graceful path
            logger.warning("gui-driver helper install into %s failed: %s", target, exc)
    return {"installed": installed, "current": current}


# Seed list of destructive menu labels (docs/gui_destructive_seed.txt,
# regex-derived from the live pcbnew 215-item enumeration; embedded here so the
# installed wheel doesn't depend on docs/). Matching is on NORMALIZED labels —
# see _normalize_label — so "Update PCB from Schematic…" and
# "Update PCB from Schematic..." both hit.
DESTRUCTIVE_SEED_LABELS = [
    "Append Board...",
    "Cleanup Graphics...",
    "Cleanup Tracks & Vias...",
    "Clear Recent Files",
    "Delete",
    "Import Non-KiCad Board File…",
    "Interactive Delete Tool",
    "New...",
    "Remove Unused Pads...",
    "Rescue",
    "Reset Drill Origin",
    "Reset Grid Origin",
    "Revert",
    "Update PCB from Schematic…",
    "Update Schematic from PCB...",
]

# Preferred matching path: resolved KiCad TOOL_ACTION names (survive label
# renames). wx menu items expose no public action mapping today, so the helper
# reports action=None and this set is empty — it is consulted first whenever a
# tree entry does carry an "action" so the upgrade is a data change, not code.
DESTRUCTIVE_ACTIONS: frozenset = frozenset()


def _normalize_label(label: str) -> str:
    """Casefolded label; mnemonic '&', accel suffix and trailing ellipsis stripped."""
    text = label.split("\t", 1)[0].replace("&", "").strip()
    while text.endswith(("...", "…")):
        text = text[:-3] if text.endswith("...") else text[:-1]
        text = text.strip()
    return " ".join(text.split()).casefold()


_DESTRUCTIVE_NORMALIZED = {_normalize_label(label) for label in DESTRUCTIVE_SEED_LABELS}


def is_destructive(entry: Dict[str, Any]) -> bool:
    """Advisory destructive classification for one tree entry.

    Prefers a resolved KiCad action name when the entry has one; falls back to
    the normalized label against the seed list.
    """
    action = entry.get("action")
    if action and action in DESTRUCTIVE_ACTIONS:
        return True
    return _normalize_label(entry.get("name", "")) in _DESTRUCTIVE_NORMALIZED


def flag_destructive_tree(tree: Dict[str, Any]) -> Dict[str, Any]:
    """Mutate a helper `tree` result in place: prefix + flag destructive menu items."""

    def _walk(entries: List[Dict[str, Any]]) -> None:
        for entry in entries:
            if is_destructive(entry):
                entry["destructive"] = True
                if not entry["name"].startswith(DESTRUCTIVE_PREFIX):
                    entry["name"] = DESTRUCTIVE_PREFIX + entry["name"]
            _walk(entry.get("children", []))

    for menu in tree.get("menus", []):
        _walk(menu.get("children", []))
    return tree


def resolve_name(tree: Dict[str, Any], name: str) -> Optional[Tuple[int, str]]:
    """Resolve a human name to ``(id, kind)`` against a captured tree.

    Menus first (clean labels — the reliable path), then AUI toolbar tooltips.
    The ``⚠ `` advisory prefix is stripped before matching so names copied from
    ``kicad_gui_tree`` output resolve as-is.
    """
    wanted = _normalize_label(name.removeprefix(DESTRUCTIVE_PREFIX))

    def _walk(entries: List[Dict[str, Any]]) -> Optional[int]:
        for entry in entries:
            if _normalize_label(entry.get("name", "").removeprefix(DESTRUCTIVE_PREFIX)) == wanted:
                return entry["id"]
            hit = _walk(entry.get("children", []))
            if hit is not None:
                return hit
        return None

    for menu in tree.get("menus", []):
        hit = _walk(menu.get("children", []))
        if hit is not None:
            return (hit, "menu")
    for bar in tree.get("toolbars", []):
        for tool in bar.get("tools", []):
            if (
                _normalize_label(tool.get("tooltip") or "") == wanted
                or _normalize_label(tool.get("label") or "") == wanted
            ):
                return (tool["id"], "tool")
    return None


class GuiDriverCommands:
    """MCP command handlers for the GUI-driver channel (helper socket client)."""

    def __init__(self, interface: Any = None) -> None:
        self._interface = interface  # unused today; kept for parity with peers

    # -- socket plumbing -----------------------------------------------------

    @property
    def port(self) -> int:
        return int(os.environ.get("KICAD_GUI_DRIVER_PORT", DEFAULT_PORT))

    def _send(self, request: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
        """One request → one response over a fresh connection. Raises on I/O."""
        with socket.create_connection(("127.0.0.1", self.port), timeout=timeout) as conn:
            conn.sendall((json.dumps(request) + "\n").encode("utf-8"))
            reader = conn.makefile("r", encoding="utf-8")
            line = reader.readline()
        if not line:
            raise ConnectionError("helper closed the connection without a response")
        return json.loads(line)

    def _call(self, request: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
        """`_send` wrapped into the backend's {"success": ...} envelope."""
        try:
            response = self._send(request, timeout=timeout)
        except (OSError, ConnectionError) as exc:
            return {"success": False, "error": self._unreachable_error(exc)}
        except json.JSONDecodeError as exc:
            return {"success": False, "error": f"malformed helper response: {exc}"}
        if not response.get("ok"):
            return {"success": False, "error": response.get("error", "helper error")}
        return {"success": True, "result": response.get("result")}

    def _unreachable_error(self, exc: Exception) -> str:
        """Not-reachable message; tries the self-install friction-reducer first.

        Graceful degradation is the REQUIRED contract: this always returns a
        string for a ``success: False`` envelope — self-install and the AT-SPI
        refresh are best-effort layers that may improve the message, never a
        reliance, never a raise, never a hang.
        """
        base = f"GUI-driver helper not reachable on 127.0.0.1:{self.port} ({exc}). "
        try:
            deployed = ensure_helper_installed()
        except Exception as install_exc:  # noqa: BLE001 — never break graceful-fail
            logger.warning("gui-driver helper self-install failed: %s", install_exc)
            deployed = {"installed": [], "current": []}
        if deployed["installed"]:
            where = ", ".join(deployed["installed"])
            if self._try_refresh_plugins_atspi():
                return base + (
                    f"Helper self-installed to {where} and Refresh Plugins was "
                    "triggered via AT-SPI — retry the call."
                )
            return base + (
                f"Helper self-installed to {where} — in KiCad run Tools > "
                "External Plugins > Refresh Plugins (or restart KiCad), then retry."
            )
        return base + (
            "Is KiCad running with the kicad-gui-driver plugin installed? "
            "Install: copy gui_driver_plugin/plugins/ to "
            "<kicad-data>/3rdparty/plugins/com_github_rossvonfange_kicad-gui-driver/ "
            "and restart KiCad (or Tools > External Plugins > Refresh Plugins)."
        )

    def _try_refresh_plugins_atspi(self) -> bool:
        """Linux nicety: click Tools > External Plugins > Refresh Plugins via
        AT-SPI so a just-installed helper loads without a restart. Best-effort
        only — any failure (non-Linux, no a11y bus, no KiCad) is silent and
        the caller falls back to the refresh/restart prompt.
        """
        if not sys.platform.startswith("linux"):
            return False
        try:
            out = self.kicad_gui_click_atspi({"name": "Refresh Plugins"})
            return bool(out.get("success"))
        except Exception:  # noqa: BLE001 — nicety, never surfaces
            return False

    # -- generic tools -------------------------------------------------------

    def kicad_gui_tree(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Enumerate the live GUI: menus/submenus (name+id) + AUI toolbars (id+tooltip).

        Destructive items carry `destructive: true` and a leading `⚠ ` — an
        ADVISORY marker only; nothing is gated.
        """
        out = self._call({"cmd": "tree", "frame": params.get("frame")})
        if not out["success"]:
            return out
        tree = flag_destructive_tree(out["result"])
        return {"success": True, "tree": tree}

    def kicad_gui_click(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Activate a menu item or toolbar tool by name (or explicit id).

        Resolution: fetch the live tree, resolve name→(id, kind) client-side
        (menus by label, toolbar tools by tooltip), then inject the wx event.
        Falls back to helper-side resolution if the client miss was transient.
        """
        frame = params.get("frame")
        item_id = params.get("id")
        kind = params.get("kind", "menu")
        name = params.get("name")
        if item_id is None:
            if not name:
                return {"success": False, "error": "kicad_gui_click needs `name` or `id`"}
            tree_out = self._call({"cmd": "tree", "frame": frame})
            if tree_out["success"]:
                resolved = resolve_name(tree_out["result"], name)
                if resolved is not None:
                    item_id, kind = resolved
        request: Dict[str, Any] = {"cmd": "click", "kind": kind, "frame": frame}
        if item_id is not None:
            request["id"] = item_id
        else:
            request["name"] = name  # helper-side fallback resolution
        out = self._call(request)
        if not out["success"]:
            return out
        return {"success": True, **out["result"], "requested": name or item_id}

    def kicad_run_action_plugin(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Trigger an External-Plugins entry (an ActionPlugin) by name."""
        name = params.get("name")
        if not name:
            return {"success": False, "error": "kicad_run_action_plugin needs `name`"}
        out = self._call({"cmd": "run_plugin", "name": name, "frame": params.get("frame")})
        if not out["success"]:
            return out
        return {"success": True, **out["result"], "plugin": name}

    def kicad_gui_wait_for(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Wait until a top-level window whose title contains `title` is shown."""
        title = params.get("title")
        if not title:
            return {"success": False, "error": "kicad_gui_wait_for needs `title`"}
        timeout = float(params.get("timeout", 10.0))
        out = self._call(
            {"cmd": "wait_for", "title": title, "timeout": timeout},
            timeout=timeout + 10.0,
        )
        if not out["success"]:
            return out
        return {"success": True, **out["result"]}

    def kicad_gui_screenshot(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Capture the driven frame's screen rect to a PNG; returns its path."""
        out = self._call(
            {"cmd": "screenshot", "path": params.get("path"), "frame": params.get("frame")}
        )
        if not out["success"]:
            return out
        return {"success": True, **out["result"]}

    # -- playbooks (thin wrappers, deliberately not a framework) -------------

    def kicad_pcb_snapshot(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Playbook: Zoom to Fit, then screenshot — visual board verification."""
        zoom = self.kicad_gui_click({"name": "Zoom to Fit", "frame": params.get("frame")})
        if not zoom.get("success"):
            return {"success": False, "error": "Zoom to Fit failed", "detail": zoom}
        time.sleep(float(params.get("settle", 0.5)))  # let the canvas repaint
        shot = self.kicad_gui_screenshot(params)
        if not shot.get("success"):
            return shot
        return {
            "success": True,
            "zoomed": True,
            **{k: v for k, v in shot.items() if k != "success"},
        }

    def kicad_reload_and_open_plugin(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Playbook: Refresh Plugins, then trigger the named External-Plugins item.

        The plugin dev/test loop: re-scan the 3rdparty tree, launch the plugin.
        """
        name = params.get("name")
        if not name:
            return {"success": False, "error": "kicad_reload_and_open_plugin needs `name`"}
        refresh = self.kicad_gui_click({"name": "Refresh Plugins", "frame": params.get("frame")})
        if not refresh.get("success"):
            return {"success": False, "error": "Refresh Plugins failed", "detail": refresh}
        time.sleep(float(params.get("settle", 1.0)))  # let the re-scan rebuild the menu
        return self.kicad_run_action_plugin(params)

    def kicad_run_drc(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Playbook: open the DRC dialog, click Run, scrape the violations grid.

        Exercises the dialog-driving path (wait_for + child enumeration +
        button click). Grid scraping is best-effort: wx exposes ListCtrl rows
        directly; the DataViewCtrl KiCad uses for violations may only expose a
        row count — the raw widget scrape is returned either way.
        """
        frame = params.get("frame")
        opened = self.kicad_gui_click({"name": "Design Rules Checker", "frame": frame})
        if not opened.get("success"):
            return {"success": False, "error": "could not open the DRC dialog", "detail": opened}
        dialog_title = params.get("dialogTitle", "DRC")
        appeared = self.kicad_gui_wait_for(
            {"title": dialog_title, "timeout": float(params.get("timeout", 15.0))}
        )
        if not appeared.get("success") or not appeared.get("found"):
            return {
                "success": False,
                "error": f"DRC dialog (~{dialog_title!r}) did not appear",
                "detail": appeared,
            }
        title = appeared["title"]
        ran = self._call({"cmd": "click_button", "title": title, "label": "Run DRC"})
        if not ran["success"]:
            return {"success": False, "error": "could not click Run DRC", "detail": ran}
        # Poll the dialog until rows (or a row count) show up, then scrape.
        deadline = time.monotonic() + float(params.get("runTimeout", 60.0))
        scraped: Dict[str, Any] = {}
        while time.monotonic() < deadline:
            time.sleep(1.0)
            out = self._call({"cmd": "scrape", "title": title})
            if not out["success"]:
                continue
            scraped = out["result"]
            if self._collect_rows(scraped):
                break
        violations = self._collect_rows(scraped)
        return {
            "success": True,
            "dialog": title,
            "violations": violations,
            "violationCount": (
                sum(len(g["rows"]) for g in violations)
                if violations
                else self._collect_row_counts(scraped)
            ),
            "rawScrape": scraped,
        }

    @staticmethod
    def _collect_rows(widget: Dict[str, Any]) -> List[Dict[str, Any]]:
        """All list-like widgets in a scrape that yielded actual text rows."""
        found: List[Dict[str, Any]] = []

        def _walk(entry: Dict[str, Any]) -> None:
            rows = entry.get("rows")
            if rows:
                found.append({"widget": entry.get("class"), "rows": rows})
            for child in entry.get("children", []):
                _walk(child)

        if widget:
            _walk(widget)
        return found

    @staticmethod
    def _collect_row_counts(widget: Dict[str, Any]) -> Optional[int]:
        counts: List[int] = []

        def _walk(entry: Dict[str, Any]) -> None:
            if "row_count" in entry:
                counts.append(entry["row_count"])
            for child in entry.get("children", []):
                _walk(child)

        if widget:
            _walk(widget)
        return max(counts) if counts else None

    # -- Backend B: AT-SPI (Linux, zero-in-KiCad) ----------------------------

    @staticmethod
    def _atspi():
        """Import gi/Atspi or explain how to enable it (returns (module, error))."""
        try:
            import gi  # type: ignore[import-not-found]

            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi  # type: ignore[import-not-found]

            return Atspi, None
        except Exception as exc:  # noqa: BLE001
            return None, (
                f"AT-SPI unavailable ({exc}). Backend B needs the OS gi bindings "
                "(no pip), accessibility enabled once via `gsettings set "
                "org.gnome.desktop.interface toolkit-accessibility true`, and "
                "KiCad launched with GTK_MODULES=gail:atk-bridge."
            )

    @staticmethod
    def _atspi_find_apps(Atspi, app_match: str) -> List[Any]:
        desktop = Atspi.get_desktop(0)
        wanted = app_match.casefold()
        apps = []
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if app is not None and wanted in (app.get_name() or "").casefold():
                apps.append(app)
        return apps

    def kicad_gui_tree_atspi(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Linux fast-path: dump KiCad's accessible widget tree (role + name)."""
        Atspi, err = self._atspi()
        if Atspi is None:
            return {"success": False, "error": err}
        Atspi.init()
        app_match = params.get("app", "kicad")
        max_depth = int(params.get("maxDepth", 12))
        apps = self._atspi_find_apps(Atspi, app_match)
        if not apps:
            return {
                "success": False,
                "error": f"no accessible application matching {app_match!r} on the a11y bus",
            }

        def _node(obj, depth: int) -> Dict[str, Any]:
            entry: Dict[str, Any] = {
                "role": obj.get_role_name(),
                "name": obj.get_name() or "",
            }
            if depth < max_depth:
                children = []
                for i in range(obj.get_child_count()):
                    child = obj.get_child_at_index(i)
                    if child is not None:
                        children.append(_node(child, depth + 1))
                if children:
                    entry["children"] = children
            return entry

        return {"success": True, "apps": [_node(app, 0) for app in apps]}

    def kicad_gui_click_atspi(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Linux fast-path: activate the first accessible node matching name (+role)."""
        name = params.get("name")
        if not name:
            return {"success": False, "error": "kicad_gui_click_atspi needs `name`"}
        Atspi, err = self._atspi()
        if Atspi is None:
            return {"success": False, "error": err}
        Atspi.init()
        wanted = _normalize_label(name)
        role_filter = (params.get("role") or "").casefold() or None
        apps = self._atspi_find_apps(Atspi, params.get("app", "kicad"))
        if not apps:
            return {"success": False, "error": "no KiCad application on the a11y bus"}

        def _find(obj):
            node_name = _normalize_label(obj.get_name() or "")
            role = obj.get_role_name()
            if node_name == wanted and (role_filter is None or role_filter in role):
                return obj
            for i in range(obj.get_child_count()):
                child = obj.get_child_at_index(i)
                if child is not None:
                    hit = _find(child)
                    if hit is not None:
                        return hit
            return None

        for app in apps:
            node = _find(app)
            if node is not None:
                node.do_action(0)  # press / activate
                return {
                    "success": True,
                    "clicked": node.get_name(),
                    "role": node.get_role_name(),
                }
        return {"success": False, "error": f"no accessible node named {name!r}"}
