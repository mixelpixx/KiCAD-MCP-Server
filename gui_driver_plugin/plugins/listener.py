"""Localhost JSON-lines control channel for the GUI-driver helper.

Protocol (the MCP's ``commands/gui_driver.py`` is the client):

* TCP on ``127.0.0.1``, port ``KICAD_GUI_DRIVER_PORT`` (default 8770).
* One request per line, UTF-8 JSON object: ``{"cmd": "tree", ...params}``.
* One response line per request: ``{"ok": true, "result": ...}`` or
  ``{"ok": false, "error": "..."}``. Connections may send many lines.

Threading model (the load-bearing part): wx is NOT thread-safe, so this
listener thread never calls wx. Each UI-bound command is queued to the UI
thread with ``wx.CallAfter``; the listener blocks on a ``threading.Event``
until the UI thread stores the result (or ``UI_CALL_TIMEOUT`` elapses —
e.g. a click that opened a *modal* dialog re-entering the event loop).

``wx`` / ``driver`` are imported lazily inside the executor so this module's
socket/dispatch layer is unit-testable in a plain venv with a stub executor.
"""

from __future__ import annotations

import json
import os
import socket
import socketserver
import threading
import time
from typing import Any, Callable, Dict, Optional

DEFAULT_PORT = 8770
PORT = int(os.environ.get("KICAD_GUI_DRIVER_PORT", DEFAULT_PORT))
UI_CALL_TIMEOUT = 15.0  # seconds a queued UI call may take before we report back

_server: Optional["_Server"] = None
_server_lock = threading.Lock()


# ---------------------------------------------------------------------------
# UI-thread executor
# ---------------------------------------------------------------------------

def wx_executor(fn: Callable[[], Any], timeout: float = UI_CALL_TIMEOUT) -> Any:
    """Run ``fn`` on the wx UI thread; block this (listener) thread for the result."""
    import wx  # deferred: only reachable inside a live KiCad

    done = threading.Event()
    box: Dict[str, Any] = {}

    def _on_ui() -> None:
        try:
            box["result"] = fn()
        except Exception as exc:  # noqa: BLE001 - marshalled back as the error
            box["error"] = exc
        finally:
            done.set()

    wx.CallAfter(_on_ui)
    if not done.wait(timeout):
        raise TimeoutError(
            f"UI thread did not answer within {timeout}s (modal dialog open, or "
            "KiCad busy). The command may still run."
        )
    if "error" in box:
        raise box["error"]
    return box.get("result")


# ---------------------------------------------------------------------------
# command dispatch
# ---------------------------------------------------------------------------

def _dispatch(request: Dict[str, Any], executor: Callable[..., Any]) -> Any:
    """Execute one request; returns the JSON-serializable result (or raises)."""
    cmd = request.get("cmd")
    frame = request.get("frame")  # optional frame name/title filter

    if cmd == "ping":
        return {"pong": True, "pid": os.getpid()}

    if cmd == "tree":
        from . import driver

        return executor(lambda: driver.full_tree(frame))

    if cmd == "click":
        from . import driver

        return executor(
            lambda: driver.click(
                item_id=request.get("id"),
                name=request.get("name"),
                kind=request.get("kind", "menu"),
                frame_match=frame,
            )
        )

    if cmd == "run_plugin":
        from . import driver

        name = request.get("name")
        if not name:
            raise ValueError("run_plugin needs `name`")
        return executor(lambda: driver.run_plugin(name, frame_match=frame))

    if cmd == "wait_for":
        # Polled from THIS thread (never block the UI thread); each poll is a
        # cheap UI-thread window-title snapshot.
        from . import driver

        title = request.get("title")
        if not title:
            raise ValueError("wait_for needs `title`")
        timeout = float(request.get("timeout", 10.0))
        wanted = title.casefold()
        deadline = time.monotonic() + timeout
        while True:
            titles = executor(driver.window_titles)
            hits = [t for t in titles if wanted in t.casefold()]
            if hits:
                return {"found": True, "title": hits[0], "titles": titles}
            if time.monotonic() >= deadline:
                return {"found": False, "titles": titles}
            time.sleep(0.25)

    if cmd == "windows":
        from . import driver

        return executor(driver.window_titles)

    if cmd == "frames":
        from . import driver

        return executor(driver.list_frames)

    if cmd == "scrape":
        from . import driver

        title = request.get("title")
        if not title:
            raise ValueError("scrape needs `title`")
        return executor(lambda: driver.scrape(title))

    if cmd == "click_button":
        from . import driver

        title, label = request.get("title"), request.get("label")
        if not title or not label:
            raise ValueError("click_button needs `title` and `label`")
        return executor(lambda: driver.click_button(title, label))

    if cmd == "screenshot":
        from . import driver

        return executor(lambda: driver.screenshot(request.get("path"), frame_match=frame))

    raise ValueError(f"unknown cmd {cmd!r}")


# ---------------------------------------------------------------------------
# socket server
# ---------------------------------------------------------------------------

class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:  # one connection, many JSON lines
        executor = self.server.executor  # type: ignore[attr-defined]
        for raw in self.rfile:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                result = _dispatch(request, executor)
                response = {"ok": True, "result": result}
            except Exception as exc:  # noqa: BLE001 - protocol boundary
                response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            try:
                self.wfile.write((json.dumps(response) + "\n").encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, executor: Callable[..., Any]):
        super().__init__(addr, _Handler)
        self.executor = executor


def start(port: int = PORT, executor: Callable[..., Any] = wx_executor) -> Optional[int]:
    """Start the listener thread (idempotent). Returns the bound port, or None
    if the port is taken (e.g. a second KiCad frame already serves it)."""
    global _server
    with _server_lock:
        if _server is not None:
            return _server.server_address[1]
        try:
            server = _Server(("127.0.0.1", port), executor)
        except OSError:
            return None
        thread = threading.Thread(
            target=server.serve_forever, name="kicad-gui-driver-listener", daemon=True
        )
        thread.start()
        _server = server
        return server.server_address[1]


def stop() -> None:
    global _server
    with _server_lock:
        if _server is not None:
            _server.shutdown()
            _server.server_close()
            _server = None
