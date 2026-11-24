"""Process creation flags that keep console children from opening a window (#577).

The server runs without a console of its own: an MCP client starts it with piped stdio.
When such a process launches a console program such as kicad-cli.exe on Windows, Windows
gives the child a new, visible console window that flashes open and closes again.
``CREATE_NO_WINDOW`` prevents that. It only affects console programs, so GUI programs
such as the KiCad editor still open their windows.

Every ``subprocess`` launch in ``python/`` passes ``creationflags=no_window_flags(...)``;
``tests/test_subprocess_flags.py`` enforces it on every OS.
"""

import subprocess
import sys

# The constants exist in the subprocess module on Windows only; the values are fixed by Win32.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_CONSOLE_FLAGS = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010) | getattr(
    subprocess, "DETACHED_PROCESS", 0x00000008
)


def no_window_flags(flags: int = 0) -> int:
    """Return ``creationflags`` for a subprocess launch, with CREATE_NO_WINDOW added on Windows.

    ``flags`` are the creation flags the caller needs anyway, such as
    ``subprocess.CREATE_NEW_PROCESS_GROUP``; they are returned unchanged on other platforms,
    where ``creationflags`` must stay 0. A caller that asks for a console of its own
    (CREATE_NEW_CONSOLE or DETACHED_PROCESS) keeps its flags as given, because Windows
    rejects those in combination with CREATE_NO_WINDOW.
    """
    if sys.platform != "win32" or flags & _CONSOLE_FLAGS:
        return flags
    return flags | CREATE_NO_WINDOW
