"""File I/O helpers for KiCad text files."""

from __future__ import annotations

import os
from pathlib import Path


def read_text_preserve_newline(path: Path) -> tuple[str, str]:
    """Read UTF-8 text as LF internally and return the original newline style."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        raw = fh.read()
    return raw.replace("\r\n", "\n"), ("\r\n" if "\r\n" in raw else "\n")


def write_text_atomic(path: Path, text: str, newline: str) -> None:
    """Atomically write UTF-8 text while preserving the caller's newline style."""
    tmp = path.with_name(path.name + ".mcp-tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline=newline) as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
