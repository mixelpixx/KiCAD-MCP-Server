"""Protect the MCP stdio wire from pcbnew's C-level stdout noise.

pcbnew (and wxWidgets underneath it) writes warnings and diagnostics straight
to fd 1 with C printf. With the SDK's stdio transport in the same process,
that would corrupt the JSON-RPC stream. The guard, installed BEFORE the
transport starts:

1. duplicates fd 1 (the real wire) to a private fd,
2. points fd 1 at stderr, so all C-level output lands in logs,
3. rebinds ``sys.stdout`` to the private wire fd, which is exactly where the
   SDK's stdio transport picks up its output stream (``sys.stdout.buffer``).

Python-level ``print()`` therefore also writes to the wire — the runtime tool
paths in this package log instead of printing, and must keep doing so.
"""

import io
import os
import sys


def install_stdio_guard() -> None:
    wire_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = io.TextIOWrapper(
        os.fdopen(wire_fd, "wb", buffering=0),
        encoding="utf-8",
        line_buffering=True,
    )
