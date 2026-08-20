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
import secrets
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

DEFAULT_PORT = 8770
PORT = int(os.environ.get("KICAD_GUI_DRIVER_PORT", DEFAULT_PORT))
UI_CALL_TIMEOUT = 15.0  # seconds a queued UI call may take before we report back

_server: Optional["_Server"] = None
_server_lock = threading.Lock()


# ---------------------------------------------------------------------------
# session token — the channel only accepts the caller we handed the secret to
# ---------------------------------------------------------------------------
#
# The listener binds 127.0.0.1, but localhost is NOT a trust boundary: any local
# process (a browser tab over WebSocket, another user on a shared box, an npm
# postinstall) could otherwise drive the GUI. So we mint a per-session secret and
# write it to a mode-0600 file the MCP client reads out of band; every request
# must echo it. A 0600 file is unreadable by other users and by the browser
# sandbox, which is exactly the exposure this closes. NOTE: this MUST stay in
# lock-step with the identical ``_token_path`` in ``python/commands/gui_driver.py``.


def _token_path() -> Path:
    """Path of the mode-0600 session-token file (shared with the MCP client)."""
    override = os.environ.get("KICAD_GUI_DRIVER_TOKEN_FILE")
    if override:
        return Path(override)
    port = int(os.environ.get("KICAD_GUI_DRIVER_PORT", DEFAULT_PORT))
    plat = sys.platform
    home = Path.home()
    if plat.startswith("win"):
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) / "kicad" if appdata else home / ".kicad"
    elif plat == "darwin":
        base = home / "Library" / "Preferences" / "kicad"
    else:
        base = home / ".local" / "share" / "kicad"
    return base / f"gui_driver_{port}.token"


def _write_token_file(token: str, path: Optional[Path] = None) -> Optional[Path]:
    """Write ``token`` to a 0600 file; best-effort (never breaks listener start)."""
    path = path if path is not None else _token_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # create with 0600 from the start (don't briefly expose it 0644)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, token.encode("utf-8"))
        finally:
            os.close(fd)
        try:
            os.chmod(path, 0o600)  # tighten if it pre-existed with looser perms
        except OSError:
            pass
        return path
    except OSError:
        return None


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


def _token_ok(got: Optional[str], expected: Optional[str]) -> bool:
    """Constant-time token comparison. An empty/None expected token disables the
    check (used only by tests that construct a server without a secret)."""
    if not expected:
        return True
    if not isinstance(got, str):
        return False
    return secrets.compare_digest(got, expected)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:  # one connection, many JSON lines
        executor = self.server.executor  # type: ignore[attr-defined]
        expected = getattr(self.server, "token", None)
        for raw in self.rfile:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                if not _token_ok(request.get("token"), expected):
                    response = {"ok": False, "error": "unauthorized: missing or invalid session token"}
                else:
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

    def __init__(self, addr, executor: Callable[..., Any], token: Optional[str] = None,
                 token_file: Optional[Path] = None):
        super().__init__(addr, _Handler)
        self.executor = executor
        self.token = token
        self.token_file = token_file


def start(port: int = PORT, executor: Callable[..., Any] = wx_executor,
          token: Optional[str] = None, token_file: Optional[Path] = None) -> Optional[int]:
    """Start the listener thread (idempotent). Mints a session token, writes it to a
    mode-0600 file the MCP client reads, and requires it on every request. Returns the
    bound port, or None if the port is taken (a second KiCad frame already serves it).

    ``token``/``token_file`` are injectable for tests; in real use both are minted/derived.
    """
    global _server
    with _server_lock:
        if _server is not None:
            return _server.server_address[1]
        # token=None  -> mint a fresh secret (real use)
        # token=""    -> explicitly disabled (tests that exercise other behaviour)
        tok = token if token is not None else secrets.token_hex(32)
        tf = token_file if token_file is not None else _token_path()
        try:
            server = _Server(("127.0.0.1", port), executor, tok, tf)
        except OSError:
            return None
        thread = threading.Thread(
            target=server.serve_forever, name="kicad-gui-driver-listener", daemon=True
        )
        thread.start()
        _server = server
        if tok:
            _write_token_file(tok, tf)
        return server.server_address[1]


def stop() -> None:
    global _server
    with _server_lock:
        if _server is not None:
            tf = getattr(_server, "token_file", None)
            _server.shutdown()
            _server.server_close()
            if tf is not None:
                try:
                    Path(tf).unlink()
                except OSError:
                    pass
            _server = None
