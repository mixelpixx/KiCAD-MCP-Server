"""GUI-driver channel unit tests — everything testable without a live pcbnew.

Covered here:
* destructive flagging + name→(id, kind) resolution against a captured-shape tree
* the JSON-lines socket protocol end-to-end over loopback: the REAL helper
  listener (``gui_driver_plugin/plugins/listener.py``) run with a stub
  executor + a fake ``driver`` module, driven by the REAL MCP client
  (``commands.gui_driver.GuiDriverCommands``)
* MCP registration (command_routes + TOOL_SCHEMAS)

NOT covered (needs a live pcbnew, verified by the maintainer via the probe
technique): real wx menu/toolbar introspection, event injection actually
firing KiCad actions, dialog scraping, screenshots.
"""

from __future__ import annotations

import json
import socket
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

import commands.gui_driver as gui_driver  # noqa: E402
from commands.gui_driver import (  # noqa: E402
    DESTRUCTIVE_PREFIX,
    HELPER_IDENTIFIER,
    HELPER_VERSION,
    HELPER_VERSION_MARKER,
    GuiDriverCommands,
    ensure_helper_installed,
    flag_destructive_tree,
    is_destructive,
    kicad_plugin_dirs,
    resolve_name,
)

# ---------------------------------------------------------------------------
# fixture tree — shape as captured from the live pcbnew probe (2026-07-24)
# ---------------------------------------------------------------------------


def _captured_tree():
    return {
        "frame": {"name": "PcbFrame", "title": "PCB Editor"},
        "menus": [
            {
                "name": "File",
                "children": [
                    {"name": "New...", "id": 4097, "action": None, "enabled": True},
                    {"name": "Revert", "id": 4098, "action": None, "enabled": True},
                    {
                        "name": "Fabrication Outputs",
                        "id": 4099,
                        "action": None,
                        "enabled": True,
                        "children": [
                            {
                                "name": "Gerbers (.gbr)...",
                                "id": 4100,
                                "action": None,
                                "enabled": True,
                            }
                        ],
                    },
                ],
            },
            {
                "name": "View",
                "children": [
                    {"name": "Zoom to Fit", "id": 4200, "action": None, "enabled": True},
                ],
            },
            {
                "name": "Tools",
                "children": [
                    {
                        "name": "Update PCB from Schematic…",
                        "id": 4300,
                        "action": None,
                        "enabled": True,
                    },
                    {
                        "name": "External Plugins",
                        "id": 4301,
                        "action": None,
                        "enabled": True,
                        "children": [
                            {
                                "name": "Refresh Plugins",
                                "id": -2240,
                                "action": None,
                                "enabled": True,
                            },
                            {"name": "Git Plugin", "id": -2242, "action": None, "enabled": True},
                            {
                                "name": "Open kiHarness",
                                "id": -2245,
                                "action": None,
                                "enabled": True,
                            },
                        ],
                    },
                ],
            },
        ],
        "toolbars": [
            {
                "name": "",
                "class": "AuiToolBar",
                "tools": [
                    {"id": 5001, "tooltip": "Zoom to fit board", "label": ""},
                    {"id": 5002, "tooltip": "Show design rules checker window", "label": ""},
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# destructive flagging + resolution (pure logic)
# ---------------------------------------------------------------------------


class TestDestructiveFlagging:
    def test_seed_labels_flagged_with_prefix(self):
        tree = flag_destructive_tree(_captured_tree())
        file_children = tree["menus"][0]["children"]
        new = file_children[0]
        revert = file_children[1]
        assert new["destructive"] is True
        assert new["name"] == DESTRUCTIVE_PREFIX + "New..."
        assert revert["destructive"] is True

    def test_ellipsis_variants_match(self):
        # seed says "Update PCB from Schematic…" (unicode); a "..." rename still hits
        assert is_destructive({"name": "Update PCB from Schematic..."})
        assert is_destructive({"name": "Update PCB from Schematic…"})

    def test_non_destructive_untouched(self):
        tree = flag_destructive_tree(_captured_tree())
        zoom = tree["menus"][1]["children"][0]
        assert "destructive" not in zoom
        assert zoom["name"] == "Zoom to Fit"

    def test_nested_children_walked(self):
        # nothing in the nested Fabrication Outputs submenu is destructive,
        # but the walk must reach it without crashing
        tree = flag_destructive_tree(_captured_tree())
        gerbers = tree["menus"][0]["children"][2]["children"][0]
        assert gerbers["name"] == "Gerbers (.gbr)..."

    def test_flagging_is_advisory_not_gating(self):
        # click by the FLAGGED name (prefix included) must still resolve
        tree = flag_destructive_tree(_captured_tree())
        assert resolve_name(tree, DESTRUCTIVE_PREFIX + "Revert") == (4098, "menu")


class TestResolveName:
    def test_menu_by_label(self):
        assert resolve_name(_captured_tree(), "Zoom to Fit") == (4200, "menu")

    def test_nested_submenu_item(self):
        assert resolve_name(_captured_tree(), "Open kiHarness") == (-2245, "menu")

    def test_case_and_ellipsis_insensitive(self):
        assert resolve_name(_captured_tree(), "new") == (4097, "menu")
        assert resolve_name(_captured_tree(), "Gerbers (.gbr)") == (4100, "menu")

    def test_toolbar_by_tooltip_after_menus(self):
        assert resolve_name(_captured_tree(), "Zoom to fit board") == (5001, "tool")

    def test_miss_returns_none(self):
        assert resolve_name(_captured_tree(), "No Such Entry") is None


# ---------------------------------------------------------------------------
# loopback protocol: real listener + real client, stubbed wx layer
# ---------------------------------------------------------------------------


@pytest.fixture()
def helper(monkeypatch):
    """The real helper listener on an ephemeral port with a fake driver module."""
    plugin_root = REPO_ROOT / "gui_driver_plugin"
    monkeypatch.syspath_prepend(str(plugin_root))
    for mod in ("plugins", "plugins.listener", "plugins.driver"):
        sys.modules.pop(mod, None)

    # Fake `plugins.driver` BEFORE the package can import the real one (which
    # imports wx at module top). `from . import driver` picks this up.
    fake = types.ModuleType("plugins.driver")
    fake.calls = []
    fake.full_tree = lambda frame=None: _captured_tree()
    fake.window_titles = lambda: ["PCB Editor", "DRC Control"]

    def _click(item_id=None, name=None, kind="menu", frame_match=None):
        fake.calls.append({"id": item_id, "name": name, "kind": kind})
        return {"id": item_id, "kind": kind, "processed": True}

    fake.click = _click
    fake.run_plugin = lambda name, frame_match=None: {
        "id": -2245,
        "kind": "menu",
        "processed": True,
    }
    fake.screenshot = lambda path=None, frame_match=None: {
        "path": path or "/tmp/x.png",
        "width": 1,
        "height": 1,
    }
    fake.scrape = lambda title: {"class": "Dialog", "name": title, "id": 1, "children": []}
    fake.click_button = lambda title, label: {"id": 9, "label": label}
    fake.list_frames = lambda: [{"name": "PcbFrame"}]

    import plugins  # noqa: F401 — the package __init__ is NOT run here...

    # ...actually `import plugins` DOES run __init__, which calls listener.start()
    # on the default port with the wx executor. Stop that instance and run our own.
    sys.modules["plugins.driver"] = fake
    setattr(sys.modules["plugins"], "driver", fake)
    from plugins import listener

    listener.stop()

    def stub_executor(fn, timeout=None):  # listener thread runs the fn directly
        return fn()

    port = listener.start(port=0, executor=stub_executor)
    assert port
    monkeypatch.setenv("KICAD_GUI_DRIVER_PORT", str(port))
    yield types.SimpleNamespace(port=port, driver=fake, listener=listener)
    listener.stop()
    for mod in ("plugins", "plugins.listener", "plugins.driver"):
        sys.modules.pop(mod, None)


class TestSocketProtocol:
    def test_ping_raw(self, helper):
        with socket.create_connection(("127.0.0.1", helper.port)) as conn:
            conn.sendall(b'{"cmd": "ping"}\n')
            line = conn.makefile("r").readline()
        response = json.loads(line)
        assert response["ok"] is True
        assert response["result"]["pong"] is True

    def test_unknown_cmd_is_error_line(self, helper):
        with socket.create_connection(("127.0.0.1", helper.port)) as conn:
            conn.sendall(b'{"cmd": "explode"}\n')
            response = json.loads(conn.makefile("r").readline())
        assert response["ok"] is False
        assert "explode" in response["error"]

    def test_malformed_json_reported_not_fatal(self, helper):
        with socket.create_connection(("127.0.0.1", helper.port)) as conn:
            reader = conn.makefile("r")
            conn.sendall(b"not json\n")
            assert json.loads(reader.readline())["ok"] is False
            conn.sendall(b'{"cmd": "ping"}\n')  # same connection still works
            assert json.loads(reader.readline())["ok"] is True

    def test_gui_tree_flags_destructive(self, helper):
        out = GuiDriverCommands().kicad_gui_tree({})
        assert out["success"] is True
        names = [c["name"] for c in out["tree"]["menus"][0]["children"]]
        assert DESTRUCTIVE_PREFIX + "New..." in names
        assert DESTRUCTIVE_PREFIX + "Revert" in names

    def test_gui_click_resolves_name_to_id(self, helper):
        out = GuiDriverCommands().kicad_gui_click({"name": "Open kiHarness"})
        assert out["success"] is True
        # the client resolved the name and the helper received the id
        assert helper.driver.calls[-1]["id"] == -2245
        assert helper.driver.calls[-1]["kind"] == "menu"

    def test_gui_click_toolbar_tooltip(self, helper):
        out = GuiDriverCommands().kicad_gui_click({"name": "Zoom to fit board"})
        assert out["success"] is True
        assert helper.driver.calls[-1] == {"id": 5001, "name": None, "kind": "tool"}

    def test_run_action_plugin(self, helper):
        out = GuiDriverCommands().kicad_run_action_plugin({"name": "Open kiHarness"})
        assert out["success"] is True and out["plugin"] == "Open kiHarness"

    def test_wait_for_found(self, helper):
        out = GuiDriverCommands().kicad_gui_wait_for({"title": "DRC", "timeout": 2})
        assert out["success"] is True and out["found"] is True
        assert out["title"] == "DRC Control"

    def test_wait_for_timeout(self, helper):
        out = GuiDriverCommands().kicad_gui_wait_for({"title": "Nope", "timeout": 0.3})
        assert out["success"] is True and out["found"] is False

    def test_helper_unreachable_is_friendly(self, monkeypatch):
        monkeypatch.setenv("KICAD_GUI_DRIVER_PORT", "1")  # nothing listens there
        # keep the unit test off the real KiCad tree: no dirs → nothing to install
        monkeypatch.setattr(gui_driver, "kicad_plugin_dirs", lambda: [])
        out = GuiDriverCommands().kicad_gui_tree({})
        assert out["success"] is False
        assert "not reachable" in out["error"]
        assert "gui_driver_plugin" in out["error"]  # install hint present


# ---------------------------------------------------------------------------
# helper self-install: per-OS path resolution + idempotent deploy
# ---------------------------------------------------------------------------


class TestPluginDirResolution:
    """kicad_plugin_dirs with injected platform/environ/home — no monkeying with
    the live OS needed; the injectables ARE the per-OS switch under test."""

    def _fake_kicad_tree(self, tmp_path, base_rel):
        base = tmp_path / base_rel
        (base / "9.0" / "3rdparty" / "plugins").mkdir(parents=True)
        (base / "8.0" / "3rdparty" / "plugins").mkdir(parents=True)
        (base / "not-a-version").mkdir()  # must not match the <ver> glob
        return base

    def test_linux_path_and_version_glob(self, tmp_path):
        self._fake_kicad_tree(tmp_path, ".local/share/kicad")
        dirs = kicad_plugin_dirs(platform="linux", environ={}, home=tmp_path)
        assert [d.parts[-3] for d in dirs] == ["8.0", "9.0"]
        assert all(str(d).endswith("3rdparty/plugins") for d in dirs)
        assert str(dirs[0]).startswith(str(tmp_path / ".local/share/kicad"))

    def test_windows_uses_appdata(self, tmp_path):
        base = self._fake_kicad_tree(tmp_path, "AppData/Roaming/kicad")
        dirs = kicad_plugin_dirs(
            platform="win32",
            environ={"APPDATA": str(base.parent)},
            home=tmp_path,
        )
        assert len(dirs) == 2
        assert str(dirs[0]).startswith(str(base))

    def test_windows_without_appdata_is_empty(self, tmp_path):
        assert kicad_plugin_dirs(platform="win32", environ={}, home=tmp_path) == []

    def test_macos_preferences_path(self, tmp_path):
        self._fake_kicad_tree(tmp_path, "Library/Preferences/kicad")
        dirs = kicad_plugin_dirs(platform="darwin", environ={}, home=tmp_path)
        assert len(dirs) == 2
        assert "Library/Preferences/kicad" in str(dirs[0])

    def test_no_kicad_installed_is_empty(self, tmp_path):
        assert kicad_plugin_dirs(platform="linux", environ={}, home=tmp_path) == []


class TestEnsureHelperInstalled:
    def _plugins_dir(self, tmp_path):
        d = tmp_path / "9.0" / "3rdparty" / "plugins"
        d.mkdir(parents=True)
        return d

    def test_fresh_install_root_flatten(self, tmp_path):
        plugins = self._plugins_dir(tmp_path)
        out = ensure_helper_installed(plugin_dirs=[plugins])
        target = plugins / HELPER_IDENTIFIER
        assert out["installed"] == [str(target)]
        # ROOT-FLATTEN: files directly at <id>/, no <id>/plugins/ nesting
        assert (target / "__init__.py").is_file()
        assert (target / "listener.py").is_file()
        assert not (target / "plugins").exists()
        assert (target / HELPER_VERSION_MARKER).read_text().strip() == HELPER_VERSION
        assert not (target / "__pycache__").exists()

    def test_second_call_is_idempotent(self, tmp_path):
        plugins = self._plugins_dir(tmp_path)
        ensure_helper_installed(plugin_dirs=[plugins])
        out = ensure_helper_installed(plugin_dirs=[plugins])
        assert out["installed"] == []
        assert out["current"] == [str(plugins / HELPER_IDENTIFIER)]

    def test_stale_version_marker_redeploys(self, tmp_path):
        plugins = self._plugins_dir(tmp_path)
        ensure_helper_installed(plugin_dirs=[plugins])
        target = plugins / HELPER_IDENTIFIER
        (target / HELPER_VERSION_MARKER).write_text("0.0.0-old\n")
        (target / "listener.py").write_text("# stale helper\n")
        out = ensure_helper_installed(plugin_dirs=[plugins])
        assert out["installed"] == [str(target)]
        assert "# stale helper" not in (target / "listener.py").read_text()
        assert (target / HELPER_VERSION_MARKER).read_text().strip() == HELPER_VERSION

    def test_multiple_versions_all_deployed(self, tmp_path):
        dirs = []
        for ver in ("8.0", "9.0"):
            d = tmp_path / ver / "3rdparty" / "plugins"
            d.mkdir(parents=True)
            dirs.append(d)
        out = ensure_helper_installed(plugin_dirs=dirs)
        assert len(out["installed"]) == 2

    def test_missing_bundle_is_a_noop(self, tmp_path):
        plugins = self._plugins_dir(tmp_path)
        out = ensure_helper_installed(plugin_dirs=[plugins], bundled=tmp_path / "no-such-bundle")
        assert out == {"installed": [], "current": []}


class TestGracefulFailWithSelfInstall:
    """The REQUIRED contract: _call still returns success:False instantly on
    connect failure — self-install only improves the message, never raises."""

    def _unreachable(self, monkeypatch):
        monkeypatch.setenv("KICAD_GUI_DRIVER_PORT", "1")  # nothing listens there
        return GuiDriverCommands()

    def test_fresh_install_prompts_refresh(self, tmp_path, monkeypatch):
        plugins = tmp_path / "9.0" / "3rdparty" / "plugins"
        plugins.mkdir(parents=True)
        monkeypatch.setattr(gui_driver, "kicad_plugin_dirs", lambda: [plugins])
        monkeypatch.setattr(GuiDriverCommands, "_try_refresh_plugins_atspi", lambda self: False)
        out = self._unreachable(monkeypatch).kicad_gui_tree({})
        assert out["success"] is False
        assert "not reachable" in out["error"]
        assert "self-installed" in out["error"]
        assert "Refresh Plugins" in out["error"]
        assert (plugins / HELPER_IDENTIFIER / "__init__.py").is_file()

    def test_atspi_refresh_success_changes_prompt_to_retry(self, tmp_path, monkeypatch):
        plugins = tmp_path / "9.0" / "3rdparty" / "plugins"
        plugins.mkdir(parents=True)
        monkeypatch.setattr(gui_driver, "kicad_plugin_dirs", lambda: [plugins])
        monkeypatch.setattr(GuiDriverCommands, "_try_refresh_plugins_atspi", lambda self: True)
        out = self._unreachable(monkeypatch).kicad_gui_tree({})
        assert out["success"] is False
        assert "AT-SPI" in out["error"] and "retry" in out["error"]

    def test_already_current_keeps_not_running_hint(self, tmp_path, monkeypatch):
        plugins = tmp_path / "9.0" / "3rdparty" / "plugins"
        plugins.mkdir(parents=True)
        ensure_helper_installed(plugin_dirs=[plugins])  # pre-install, current
        monkeypatch.setattr(gui_driver, "kicad_plugin_dirs", lambda: [plugins])
        out = self._unreachable(monkeypatch).kicad_gui_tree({})
        assert out["success"] is False
        assert "Is KiCad running" in out["error"]

    def test_install_blowup_never_breaks_graceful_fail(self, monkeypatch):
        def _boom():
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(gui_driver, "ensure_helper_installed", _boom)
        out = self._unreachable(monkeypatch).kicad_gui_tree({})
        assert out["success"] is False
        assert "not reachable" in out["error"]

    def test_atspi_refresh_is_linux_gated(self, monkeypatch):
        monkeypatch.setattr(gui_driver.sys, "platform", "win32")
        assert GuiDriverCommands()._try_refresh_plugins_atspi() is False

    def test_atspi_refresh_swallows_exceptions(self, monkeypatch):
        monkeypatch.setattr(gui_driver.sys, "platform", "linux")

        def _boom(self, params):
            raise RuntimeError("no a11y bus")

        monkeypatch.setattr(GuiDriverCommands, "kicad_gui_click_atspi", _boom)
        assert GuiDriverCommands()._try_refresh_plugins_atspi() is False


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------

GUI_TOOL_NAMES = [
    "kicad_gui_tree",
    "kicad_gui_click",
    "kicad_run_action_plugin",
    "kicad_gui_wait_for",
    "kicad_gui_screenshot",
    "kicad_pcb_snapshot",
    "kicad_reload_and_open_plugin",
    "kicad_run_drc",
    "kicad_gui_tree_atspi",
    "kicad_gui_click_atspi",
]


class TestRegistration:
    def test_tool_schemas_present(self):
        from schemas.tool_schemas import TOOL_SCHEMAS

        for name in GUI_TOOL_NAMES:
            assert name in TOOL_SCHEMAS, name

    def test_command_routes_present(self):
        import kicad_interface

        interface = kicad_interface.KiCADInterface()
        for name in GUI_TOOL_NAMES:
            assert name in interface.command_routes, name


# ---------------------------------------------------------------------------
# real driver.py against a fake wx: prove plugin triggers fire ASYNCHRONOUSLY
# (via wx.CallAfter) so a plugin whose Run() blocks the UI thread neither
# freezes KiCad nor trips the listener's UI_CALL_TIMEOUT.
# ---------------------------------------------------------------------------


def _load_real_driver_with_fake_wx(monkeypatch):
    """Import the real gui_driver_plugin driver with a minimal fake wx."""
    plugin_root = REPO_ROOT / "gui_driver_plugin"
    monkeypatch.syspath_prepend(str(plugin_root))
    for mod in ("plugins", "plugins.driver", "wx"):
        sys.modules.pop(mod, None)

    calls = {"call_after": [], "process_event": []}

    class _Frame:
        def GetName(self):
            return "PcbFrame"

        def GetTitle(self):
            return "board — PCB Editor"

        def ProcessEvent(self, evt):
            calls["process_event"].append(evt)
            return True

    fake_wx = types.ModuleType("wx")
    fake_wx.wxEVT_COMMAND_MENU_SELECTED = 10001
    fake_wx.wxEVT_COMMAND_TOOL_CLICKED = 10002
    fake_wx.GetTopLevelWindows = lambda: [_Frame()]
    fake_wx.CommandEvent = lambda evt_type, item_id: {"type": evt_type, "id": item_id}
    fake_wx.CallAfter = lambda fn, *a, **k: calls["call_after"].append((fn, a, k))
    sys.modules["wx"] = fake_wx

    import plugins.driver as driver  # noqa: E402 — real module, fake wx underneath

    return driver, calls


class TestDriverAsyncTrigger:
    def test_async_click_uses_call_after_not_process_event(self, monkeypatch):
        driver, calls = _load_real_driver_with_fake_wx(monkeypatch)
        out = driver.click(item_id=-2245, async_trigger=True)
        # returns immediately, marked async — Run() is NOT awaited
        assert out["triggered"] is True and out["async"] is True and out["id"] == -2245
        assert len(calls["call_after"]) == 1
        assert calls["process_event"] == []  # nothing fired synchronously
        # the queued callback, when the UI tick runs it, performs the real trigger
        fn, a, k = calls["call_after"][0]
        fn(*a, **k)
        assert len(calls["process_event"]) == 1

    def test_sync_click_still_processes_immediately(self, monkeypatch):
        driver, calls = _load_real_driver_with_fake_wx(monkeypatch)
        out = driver.click(item_id=42, async_trigger=False)
        assert out["processed"] is True and out["id"] == 42
        assert len(calls["process_event"]) == 1
        assert calls["call_after"] == []
