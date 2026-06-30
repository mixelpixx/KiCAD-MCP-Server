"""Robust resolution of the ``kicad-cli`` executable.

KiCad's Windows installer does **not** add ``KiCad\\<ver>\\bin`` to ``PATH``, so a
bare ``shutil.which("kicad-cli")`` fails on an otherwise-normal install even though
``kicad-cli.exe`` is sitting right there in the install's ``bin`` directory. Every MCP
tool that shells out to ``kicad-cli`` (netlist/gerber/drill/pos/pdf/svg/... exports,
ERC/DRC) then fails with a misleading "not found in PATH" error.

This module centralises resolution so every cli-backed tool uses the same logic:

    1. Explicit override: ``$KICAD_CLI`` / ``$KICAD_CLI_PATH`` (if set). An explicit
       override is authoritative — if it is set but does not point at a real file we
       refuse to silently fall back to a different binary.
    2. Adjacent to the running interpreter: ``Path(sys.executable).parent / kicad-cli``.
       The MCP backend runs under KiCad's bundled Python (``KiCad\\<ver>\\bin\\python``,
       which is how it imports ``pcbnew``); ``kicad-cli`` lives in that same ``bin``
       directory, making this the most reliable source for this server.
    3. ``PATH`` lookup.
    4. Known per-OS install locations (newest KiCad version first).

The resolved path is cached. The environment override is re-checked on every call so a
test (or a user) can change it without a stale cache masking the new value.
"""

import logging
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("kicad_interface")

_ENV_VARS = ("KICAD_CLI", "KICAD_CLI_PATH")
_cached_cli: Optional[str] = None


def _cli_name() -> str:
    """Executable basename for the current OS."""
    return "kicad-cli.exe" if platform.system() == "Windows" else "kicad-cli"


def _override_value() -> Optional[str]:
    """Return the first non-empty KICAD_CLI / KICAD_CLI_PATH value, or None."""
    for env in _ENV_VARS:
        val = os.environ.get(env)
        if val:
            return val
    return None


def _candidate_paths() -> List[Path]:
    """Well-known per-OS install locations for kicad-cli, newest version first."""
    name = _cli_name()
    system = platform.system()
    candidates: List[Path] = []

    if system == "Windows":
        for base in (r"C:\Program Files\KiCad", r"C:\Program Files (x86)\KiCad"):
            base_dir = Path(base)
            if base_dir.is_dir():
                versions = sorted(
                    (p for p in base_dir.iterdir() if p.is_dir()),
                    key=lambda p: p.name,
                    reverse=True,
                )
                candidates.extend(v / "bin" / name for v in versions)
            # Some installs drop straight into <base>\bin without a version dir.
            candidates.append(base_dir / "bin" / name)
    elif system == "Darwin":
        candidates.extend(
            [
                Path("/Applications/KiCad/KiCad.app/Contents/MacOS") / name,
                Path("/usr/local/bin") / name,
                Path("/opt/homebrew/bin") / name,
            ]
        )
    else:  # Linux / *nix
        candidates.extend(
            [
                Path("/usr/bin") / name,
                Path("/usr/local/bin") / name,
                Path("/app/bin") / name,  # Flatpak sandbox
                Path("/var/lib/flatpak/app/org.kicad.KiCad/current/active/files/bin") / name,
                Path.home() / ".local" / "bin" / name,
            ]
        )
    return candidates


def resolve_kicad_cli(force: bool = False) -> Optional[str]:
    """Return the absolute path to ``kicad-cli``, or ``None`` if it cannot be found.

    The environment override is honoured first and re-checked on every call. An override
    that is set but invalid returns ``None`` (we do not fall back to auto-detection — the
    user asked for a specific binary). Auto-detected results are cached; pass
    ``force=True`` to bypass the cache.
    """
    global _cached_cli

    # 1. Explicit override — authoritative, always checked first (never cached so a
    #    changed/cleared env var takes effect immediately).
    override = _override_value()
    if override is not None:
        path = Path(override)
        if path.is_file():
            return str(path)
        logger.warning(
            "KICAD_CLI override %r does not point at a file; refusing to fall back to "
            "another kicad-cli. Fix or unset the variable.",
            override,
        )
        return None

    if not force and _cached_cli is not None:
        return _cached_cli

    name = _cli_name()

    # 2. Adjacent to the running interpreter (KiCad's bundled python bin/).
    try:
        adjacent = Path(sys.executable).parent / name
        if adjacent.is_file():
            _cached_cli = str(adjacent)
            return _cached_cli
    except (OSError, ValueError):
        pass

    # 3. PATH.
    on_path = shutil.which(name) or shutil.which("kicad-cli")
    if on_path:
        _cached_cli = on_path
        return _cached_cli

    # 4. Known install locations.
    for candidate in _candidate_paths():
        if candidate.is_file():
            _cached_cli = str(candidate)
            return _cached_cli

    return None


def kicad_cli_not_found_message() -> str:
    """Build a clear, actionable error message listing every location tried.

    Replaces the old bare ``"kicad-cli not found in PATH"`` so users can see exactly
    where the resolver looked and how to point it at their install.
    """
    name = _cli_name()
    lines: List[str] = ["Could not locate kicad-cli. Tried, in order:"]

    override = _override_value()
    if override is not None:
        lines.append(f"  - ${{KICAD_CLI}} = {override}  (set, but not a file)")
    else:
        lines.append("  - $KICAD_CLI / $KICAD_CLI_PATH  (not set)")

    try:
        lines.append(f"  - next to the Python interpreter: {Path(sys.executable).parent / name}")
    except (OSError, ValueError):
        pass
    lines.append(f"  - PATH lookup of {name}")
    for candidate in _candidate_paths():
        lines.append(f"  - {candidate}")

    lines.append(
        "Set the KICAD_CLI environment variable to the full path of kicad-cli "
        "(e.g. on Windows: C:\\Program Files\\KiCad\\10.0\\bin\\kicad-cli.exe) and retry."
    )
    return "\n".join(lines)


def reset_cache() -> None:
    """Clear the cached resolution (primarily for tests)."""
    global _cached_cli
    _cached_cli = None
