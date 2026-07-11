"""Robust resolution of a 7-Zip CLI executable.

Mirrors the kicad-cli resolver pattern (PR #267): the 7-Zip Windows installer drops
``7z.exe`` into ``C:\\Program Files\\7-Zip`` but does **not** add it to ``PATH``, so a
bare ``shutil.which("7z")`` fails even when 7-Zip is installed. The yaqwsx JLCPCB
download path needs a 7-Zip CLI to extract its split archive and then fails with a
misleading "not found".

Resolution order:

    1. Explicit override: ``$SEVEN_ZIP`` / ``$SEVENZIP_PATH`` (if set). An explicit
       override is authoritative — if it is set but does not point at a real file we
       refuse to silently fall back to a different binary.
    2. ``PATH`` lookup of the known basenames.
    3. Known per-OS install locations (newest/most-specific first).

The resolved absolute path is cached (subprocess accepts an absolute path). The
environment override is re-checked on every call so a changed value is never masked.
"""

import logging
import os
import platform
import shutil
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("kicad_interface")

_ENV_VARS = ("SEVEN_ZIP", "SEVENZIP_PATH")
# Order matters: prefer the full-featured CLIs over the reduced 7zr/7za.
_BASENAMES = ("7z", "7zz", "7za", "7zr")
_cached_7z: Optional[str] = None


def _exe_names() -> List[str]:
    """Candidate basenames for the current OS (``.exe`` suffixed on Windows)."""
    if platform.system() == "Windows":
        return [f"{name}.exe" for name in _BASENAMES]
    return list(_BASENAMES)


def _override_value() -> Optional[str]:
    """Return the first non-empty SEVEN_ZIP / SEVENZIP_PATH value, or None."""
    for env in _ENV_VARS:
        val = os.environ.get(env)
        if val:
            return val
    return None


def _windows_install_dirs() -> List[Path]:
    """7-Zip install directories on Windows, from env then literal Program Files."""
    dirs: List[Path] = []
    seen: set = set()
    for env in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            candidate = Path(base) / "7-Zip"
            key = os.path.normcase(str(candidate))
            if key not in seen:
                seen.add(key)
                dirs.append(candidate)
    for literal in (r"C:\Program Files\7-Zip", r"C:\Program Files (x86)\7-Zip"):
        key = os.path.normcase(literal)
        if key not in seen:
            seen.add(key)
            dirs.append(Path(literal))
    return dirs


def _candidate_paths() -> List[Path]:
    """Well-known per-OS install locations for a 7-Zip CLI."""
    system = platform.system()
    candidates: List[Path] = []

    if system == "Windows":
        # 7z.exe is the full CLI; 7zr/7za are reduced fallbacks.
        for directory in _windows_install_dirs():
            for name in ("7z.exe", "7zr.exe", "7za.exe"):
                candidates.append(directory / name)
    elif system == "Darwin":
        for base in ("/opt/homebrew/bin", "/usr/local/bin"):
            for name in ("7z", "7zz", "7za"):
                candidates.append(Path(base) / name)
    else:  # Linux / *nix
        for base in ("/usr/bin", "/usr/local/bin"):
            for name in ("7z", "7zz", "7za", "7zr"):
                candidates.append(Path(base) / name)
        # Common snap/flatpak shims.
        candidates.append(Path("/snap/bin/7z"))
        candidates.append(Path("/var/lib/flatpak/exports/bin/7z"))
    return candidates


def _is_usable(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def resolve_7z(force: bool = False) -> Optional[str]:
    """Return the absolute path to a 7-Zip CLI, or ``None`` if none can be found.

    The environment override is honoured first and re-checked on every call. An override
    that is set but invalid returns ``None`` (we do not fall back — the user asked for a
    specific binary). Auto-detected results are cached; pass ``force=True`` to bypass.
    """
    global _cached_7z

    # 1. Explicit override — authoritative, always checked first (never cached).
    override = _override_value()
    if override is not None:
        path = Path(override)
        if path.is_file():
            return str(path)
        logger.warning(
            "SEVEN_ZIP override %r does not point at a file; refusing to fall back to "
            "another 7-Zip. Fix or unset the variable.",
            override,
        )
        return None

    if not force and _cached_7z is not None:
        return _cached_7z

    # 2. PATH.
    for name in _exe_names():
        on_path = shutil.which(name)
        if on_path:
            _cached_7z = on_path
            return _cached_7z

    # 3. Known install locations.
    for candidate in _candidate_paths():
        if _is_usable(candidate):
            _cached_7z = str(candidate)
            return _cached_7z

    return None


def seven_zip_not_found_message() -> str:
    """Build a clear, actionable error listing every location tried."""
    lines: List[str] = ["Could not locate a 7-Zip CLI (7z/7zz/7za/7zr). Tried, in order:"]

    override = _override_value()
    if override is not None:
        lines.append(f"  - $SEVEN_ZIP = {override}  (set, but not a file)")
    else:
        lines.append("  - $SEVEN_ZIP / $SEVENZIP_PATH  (not set)")

    lines.append("  - PATH lookup of " + ", ".join(_exe_names()))
    for candidate in _candidate_paths():
        lines.append(f"  - {candidate}")

    lines.append(
        "Install 7-Zip (Windows: https://www.7-zip.org/) or p7zip (macOS: "
        "`brew install sevenzip`; Linux: `apt install p7zip-full`), add it to PATH, or "
        "set the SEVEN_ZIP environment variable to the full path of the 7z executable."
    )
    return "\n".join(lines)


def reset_cache() -> None:
    """Clear the cached resolution (primarily for tests)."""
    global _cached_7z
    _cached_7z = None
