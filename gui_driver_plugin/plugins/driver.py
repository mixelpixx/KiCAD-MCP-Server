"""wx introspection + event injection for the GUI-driver helper.

EVERY function in this module MUST run on the wx UI thread (via the listener's
``wx.CallAfter`` executor) — wx is not thread-safe. The listener thread never
calls in here directly.

All of the mechanisms below were proven by live probes inside pcbnew
(2026-07-24, see docs/GUI_DRIVER_FABLE_BRIEF.md in the MCP repo):

* ``wx.GetTopLevelWindows()`` finds the ``PcbFrame``.
* ``frame.GetMenuBar()`` + recursing ``menu.GetMenuItems()`` /
  ``item.GetSubMenu()`` enumerates every menu item with a clean name + id
  (215 on pcbnew), including the *Tools → External Plugins* submenu where
  ActionPlugin entries live (e.g. ``Open kiHarness`` id=-2245).
* ``frame.GetToolBar()`` is None — KiCad uses AUI toolbars. Recurse
  ``win.GetChildren()`` matching ``type(c).__name__`` containing
  ``AuiToolBar``; tools expose ``GetToolCount()`` / ``FindToolByIndex(i)``
  and are icon-only, so the human name is ``GetShortHelp()`` (tooltip).
* Trigger = ``frame.ProcessEvent(wx.CommandEvent(<type>, item_id))`` with
  ``wxEVT_COMMAND_MENU_SELECTED`` for menu items and
  ``wxEVT_COMMAND_TOOL_CLICKED`` for toolbar tools. Real activations, no
  pixel coordinates.
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import Any, Dict, List, Optional

import wx

# ---------------------------------------------------------------------------
# label normalization (shared convention with the MCP client's resolver)
# ---------------------------------------------------------------------------


def normalize_label(label: str) -> str:
    """Casefolded label with mnemonic '&', trailing ellipsis and accel stripped."""
    text = label.split("\t", 1)[0]
    text = text.replace("&", "")
    text = text.strip()
    while text.endswith(("...", "…")):
        text = text[:-3] if text.endswith("...") else text[:-1]
        text = text.strip()
    return " ".join(text.split()).casefold()


# ---------------------------------------------------------------------------
# frames
# ---------------------------------------------------------------------------


def list_frames() -> List[Dict[str, Any]]:
    frames = []
    for win in wx.GetTopLevelWindows():
        frames.append(
            {
                "name": win.GetName(),
                "title": win.GetTitle() if hasattr(win, "GetTitle") else "",
                "class": type(win).__name__,
                "shown": bool(win.IsShown()),
            }
        )
    return frames


def find_frame(match: Optional[str] = None):
    """Best frame to drive: name/title contains ``match``, else PcbFrame, else
    the first shown top-level window with a menubar."""
    wins = list(wx.GetTopLevelWindows())
    if match:
        wanted = match.casefold()
        for win in wins:
            title = win.GetTitle() if hasattr(win, "GetTitle") else ""
            if wanted in win.GetName().casefold() or wanted in title.casefold():
                return win
        return None
    for win in wins:
        if win.GetName() == "PcbFrame":
            return win
    for win in wins:
        if win.IsShown() and getattr(win, "GetMenuBar", None) and win.GetMenuBar():
            return win
    return wins[0] if wins else None


# ---------------------------------------------------------------------------
# menu tree
# ---------------------------------------------------------------------------


def _menu_items(menu) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for item in menu.GetMenuItems():
        if item.IsSeparator():
            continue
        entry: Dict[str, Any] = {
            "name": item.GetItemLabelText(),
            "id": item.GetId(),
            # wx has no public mapping from a menu item to KiCad's TOOL_ACTION;
            # reported as None so the client's destructive matcher can prefer
            # action names once/if a mapping ever becomes available.
            "action": None,
            "enabled": bool(item.IsEnabled()),
        }
        help_text = item.GetHelp()
        if help_text:
            entry["help"] = help_text
        sub = item.GetSubMenu()
        if sub is not None:
            entry["children"] = _menu_items(sub)
        items.append(entry)
    return items


def menu_tree(frame) -> List[Dict[str, Any]]:
    bar = frame.GetMenuBar()
    if bar is None:
        return []
    menus = []
    for i in range(bar.GetMenuCount()):
        menus.append(
            {
                "name": bar.GetMenuLabelText(i),
                "children": _menu_items(bar.GetMenu(i)),
            }
        )
    return menus


# ---------------------------------------------------------------------------
# AUI toolbars (frame.GetToolBar() is None in KiCad)
# ---------------------------------------------------------------------------


def _find_aui_toolbars(win, found: List[Any]) -> None:
    for child in win.GetChildren():
        if "AuiToolBar" in type(child).__name__:
            found.append(child)
        _find_aui_toolbars(child, found)


def toolbar_tree(frame) -> List[Dict[str, Any]]:
    bars: List[Any] = []
    _find_aui_toolbars(frame, bars)
    out = []
    for bar in bars:
        tools = []
        for i in range(bar.GetToolCount()):
            tool = bar.FindToolByIndex(i)
            if tool is None:
                continue
            tools.append(
                {
                    "id": tool.GetId(),
                    # icon-only buttons: tooltip is the only human name
                    "tooltip": tool.GetShortHelp(),
                    "label": tool.GetLabel(),
                }
            )
        out.append({"name": bar.GetName(), "class": type(bar).__name__, "tools": tools})
    return out


def full_tree(frame_match: Optional[str] = None) -> Dict[str, Any]:
    frame = find_frame(frame_match)
    if frame is None:
        raise RuntimeError(f"no top-level frame matching {frame_match!r}")
    return {
        "frame": {"name": frame.GetName(), "title": frame.GetTitle()},
        "menus": menu_tree(frame),
        "toolbars": toolbar_tree(frame),
    }


# ---------------------------------------------------------------------------
# resolution + event injection
# ---------------------------------------------------------------------------


def _walk_menu_entries(entries, path=()):
    for entry in entries:
        here = path + (entry["name"],)
        yield entry, here
        for sub, sub_path in _walk_menu_entries(entry.get("children", []), here):
            yield sub, sub_path


def resolve_menu_id(frame, name: str) -> Optional[int]:
    wanted = normalize_label(name)
    for menu in menu_tree(frame):
        for entry, _path in _walk_menu_entries(menu["children"], (menu["name"],)):
            if normalize_label(entry["name"]) == wanted:
                return entry["id"]
    return None


def resolve_tool_id(frame, name: str) -> Optional[int]:
    wanted = normalize_label(name)
    for bar in toolbar_tree(frame):
        for tool in bar["tools"]:
            if (
                normalize_label(tool.get("tooltip") or "") == wanted
                or normalize_label(tool.get("label") or "") == wanted
            ):
                return tool["id"]
    return None


def click(
    item_id: Optional[int] = None,
    name: Optional[str] = None,
    kind: str = "menu",
    frame_match: Optional[str] = None,
    async_trigger: bool = False,
) -> Dict[str, Any]:
    """Inject a menu/tool activation into the frame's event handler.

    ``async_trigger`` posts the event via ``wx.CallAfter`` and returns without
    waiting for the handler to finish. Use it for plugin actions whose ``Run()``
    may occupy the UI thread (open a dialog, launch a browser, start a server):
    the activation fires on the next UI tick, so the caller's control channel is
    never held hostage to the plugin's duration — and a plugin that blocks the
    UI thread no longer trips the listener's UI_CALL_TIMEOUT.
    """
    frame = find_frame(frame_match)
    if frame is None:
        raise RuntimeError(f"no top-level frame matching {frame_match!r}")
    resolved_kind = kind
    if item_id is None:
        if not name:
            raise ValueError("click needs `id` or `name`")
        if kind == "tool":
            item_id = resolve_tool_id(frame, name)
        else:
            item_id = resolve_menu_id(frame, name)
            if item_id is None:  # fall through to toolbar tooltips
                item_id = resolve_tool_id(frame, name)
                resolved_kind = "tool" if item_id is not None else kind
        if item_id is None:
            raise LookupError(f"no {kind} item named {name!r}")
    evt_type = (
        wx.wxEVT_COMMAND_TOOL_CLICKED if resolved_kind == "tool" else wx.wxEVT_COMMAND_MENU_SELECTED
    )
    if async_trigger:
        # Fire on the next UI tick and return now — do NOT wait on Run().
        wx.CallAfter(lambda: frame.ProcessEvent(wx.CommandEvent(evt_type, item_id)))
        return {"id": item_id, "kind": resolved_kind, "triggered": True, "async": True}
    evt = wx.CommandEvent(evt_type, item_id)
    processed = frame.ProcessEvent(evt)
    return {"id": item_id, "kind": resolved_kind, "processed": bool(processed)}


def run_plugin(name: str, frame_match: Optional[str] = None) -> Dict[str, Any]:
    """Trigger an External-Plugins submenu entry by (normalized) name.

    Prefers the *External Plugins* submenu (that's where ActionPlugin entries
    land); falls back to a whole-menubar label match.
    """
    frame = find_frame(frame_match)
    if frame is None:
        raise RuntimeError(f"no top-level frame matching {frame_match!r}")
    wanted = normalize_label(name)
    fallback_id: Optional[int] = None
    for menu in menu_tree(frame):
        for entry, path in _walk_menu_entries(menu["children"], (menu["name"],)):
            if normalize_label(entry["name"]) != wanted:
                continue
            in_external = any("external plugins" in normalize_label(p) for p in path[:-1])
            if in_external:
                return click(item_id=entry["id"], frame_match=frame_match, async_trigger=True)
            if fallback_id is None:
                fallback_id = entry["id"]
    if fallback_id is not None:
        return click(item_id=fallback_id, frame_match=frame_match, async_trigger=True)
    raise LookupError(f"no plugin menu entry named {name!r}")


# ---------------------------------------------------------------------------
# windows / dialog scraping / button clicks (for playbooks like run_drc)
# ---------------------------------------------------------------------------


def window_titles() -> List[str]:
    titles = []
    for win in wx.GetTopLevelWindows():
        title = win.GetTitle() if hasattr(win, "GetTitle") else ""
        if title and win.IsShown():
            titles.append(title)
    return titles


def _find_window(title: str):
    wanted = title.casefold()
    for win in wx.GetTopLevelWindows():
        wtitle = (win.GetTitle() if hasattr(win, "GetTitle") else "") or ""
        if wanted in wtitle.casefold() and win.IsShown():
            return win
    return None


def _widget_entry(widget) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "class": type(widget).__name__,
        "name": widget.GetName(),
        "id": widget.GetId(),
    }
    label = getattr(widget, "GetLabel", None)
    if label:
        try:
            text = widget.GetLabel()
            if text:
                entry["label"] = text
        except Exception:
            pass
    value = getattr(widget, "GetValue", None)
    if value:
        try:
            entry["value"] = str(widget.GetValue())
        except Exception:
            pass
    # Row extraction for list-like controls (DRC violations grid etc.).
    try:
        if hasattr(widget, "GetItemCount") and hasattr(widget, "GetItemText"):
            count = widget.GetItemCount()
            cols = widget.GetColumnCount() if hasattr(widget, "GetColumnCount") else 1
            rows = []
            for r in range(min(count, 500)):
                rows.append([widget.GetItemText(r, c) for c in range(max(cols, 1))])
            entry["rows"] = rows
        elif "DataViewCtrl" in type(widget).__name__ and hasattr(widget, "GetModel"):
            model = widget.GetModel()
            if model is not None and hasattr(model, "GetCount"):
                entry["row_count"] = int(model.GetCount())
    except Exception:
        pass
    children = [_widget_entry(c) for c in widget.GetChildren()]
    if children:
        entry["children"] = children
    return entry


def scrape(title: str) -> Dict[str, Any]:
    win = _find_window(title)
    if win is None:
        raise LookupError(f"no shown top-level window titled ~{title!r}")
    return _widget_entry(win)


def _find_button(widget, wanted: str):
    if isinstance(widget, wx.Button):
        try:
            if normalize_label(widget.GetLabel()) == wanted:
                return widget
        except Exception:
            pass
    for child in widget.GetChildren():
        hit = _find_button(child, wanted)
        if hit is not None:
            return hit
    return None


def click_button(title: str, label: str) -> Dict[str, Any]:
    win = _find_window(title)
    if win is None:
        raise LookupError(f"no shown top-level window titled ~{title!r}")
    btn = _find_button(win, normalize_label(label))
    if btn is None:
        raise LookupError(f"no button labelled {label!r} in window ~{title!r}")
    evt = wx.CommandEvent(wx.wxEVT_COMMAND_BUTTON_CLICKED, btn.GetId())
    evt.SetEventObject(btn)
    wx.PostEvent(btn.GetEventHandler(), evt)
    return {"id": btn.GetId(), "label": btn.GetLabel()}


# ---------------------------------------------------------------------------
# screenshot
# ---------------------------------------------------------------------------


def screenshot(path: Optional[str] = None, frame_match: Optional[str] = None) -> Dict[str, Any]:
    """Capture the driven frame's screen rect (whole screen if no frame)."""
    if not path:
        fd, path = tempfile.mkstemp(prefix="kicad_gui_%d_" % int(time.time()), suffix=".png")
        os.close(fd)
    frame = find_frame(frame_match)
    screen = wx.ScreenDC()
    if frame is not None:
        rect = frame.GetScreenRect()
    else:
        size = screen.GetSize()
        rect = wx.Rect(0, 0, size.width, size.height)
    bmp = wx.Bitmap(rect.width, rect.height)
    mem = wx.MemoryDC(bmp)
    mem.Blit(0, 0, rect.width, rect.height, screen, rect.x, rect.y)
    mem.SelectObject(wx.NullBitmap)
    bmp.SaveFile(path, wx.BITMAP_TYPE_PNG)
    return {"path": path, "width": rect.width, "height": rect.height}
