"""creationflags for subprocess calls so no console window flashes on Windows.

On Windows, a console program started by a process that owns no console gets
a new, visible console window of its own. The server is started by an MCP
client with piped stdio, so neither the Node process nor the Python worker
owns one, and every ``kicad-cli`` call flashed a console window (issue #577).
Passing ``CREATE_NO_WINDOW`` keeps the child hidden. The flag is a no-op
anywhere else, so call sites pass it unconditionally; the source-scan test in
``tests/test_subprocess_flags.py`` guards every call site on every OS.
"""

import subprocess
import sys


def windows_no_console_flags(extra: int = 0) -> int:
    """Return ``creationflags`` that keep a child console hidden on Windows.

    On win32 this is ``subprocess.CREATE_NO_WINDOW`` ORed with ``extra``, so
    a caller that already passes flags (for example
    ``subprocess.CREATE_NEW_PROCESS_GROUP``) keeps them. Anywhere else it is
    just ``extra`` (0 by default), so the call is a no-op off Windows.
    """
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW | extra
    return extra
