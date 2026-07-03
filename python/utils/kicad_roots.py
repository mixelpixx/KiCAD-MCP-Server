"""Unified discovery of KiCad install roots.

Three modules used to independently assume KiCad lives under ``Program Files`` on
Windows (``kicad_cli.py``'s last-resort scan, ``platform_helper.py``'s
symbol/python paths, ``library.py``'s footprint dirs). The KiCad Windows
installer lets the user pick any root, and short no-space roots like
``C:\\KiCad\\<ver>`` are common — every such install got degraded discovery,
each module failing in its own way (issue #286).

This centralises the discovery of KiCad *install roots* (the directory that
contains ``bin\\`` and ``share\\kicad\\``) so the three modules can append their
own suffix to a single, authoritative list and can no longer drift apart — the
same unification #267 did for the three ``kicad-cli`` resolvers.

Roots are returned newest-version first and de-duplicated. On Windows they come
from, in order of authority:

    1. The registry uninstall keys (``...\\Uninstall\\KiCad*`` → ``InstallLocation``),
       which point at wherever the user actually installed KiCad.
    2. ``C:\\Program Files\\KiCad\\*`` / ``Program Files (x86)`` version globs.
    3. Common custom roots (``C:\\KiCad\\*``).

Only Windows has the "installer can relocate the root" problem this solves;
other platforms return an empty list, and callers keep their existing per-OS
logic there.
"""

import logging
import os
import platform
import re
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger("kicad_interface")

# A version tuple used only for newest-first ordering; missing parts sort as 0.
_VersionKey = Tuple[int, int, int]
_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def _version_key(text: str) -> _VersionKey:
    """Parse a leading ``major[.minor[.patch]]`` out of ``text`` for sorting.

    ``"10.0.4"`` -> ``(10, 0, 4)``, ``"KiCad 9.0"`` -> ``(9, 0, 0)``, and anything
    without digits -> ``(0, 0, 0)`` so it sorts last.
    """
    m = _VERSION_RE.search(text or "")
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0))


def _registry_roots() -> List[Tuple[_VersionKey, Path]]:
    """KiCad install roots from the Windows uninstall registry keys.

    Walks HKLM/HKCU (including the 32-bit ``WOW6432Node`` view) for uninstall
    entries whose ``DisplayName`` mentions KiCad and reads their
    ``InstallLocation``. This is the authoritative source: it reflects wherever
    the user chose to install, custom roots included. Any read error on an
    individual key is skipped rather than aborting discovery.
    """
    if platform.system() != "Windows":
        return []

    import winreg

    hives = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    results: List[Tuple[_VersionKey, Path]] = []
    for hive, subpath in hives:
        try:
            key = winreg.OpenKey(hive, subpath)
        except OSError:
            continue
        try:
            count = winreg.QueryInfoKey(key)[0]
        except OSError:
            continue
        for i in range(count):
            try:
                sub = winreg.EnumKey(key, i)
                subkey = winreg.OpenKey(key, sub)
                display_name = winreg.QueryValueEx(subkey, "DisplayName")[0]
            except OSError:
                continue
            if "kicad" not in str(display_name).lower():
                continue
            try:
                location = winreg.QueryValueEx(subkey, "InstallLocation")[0]
            except OSError:
                location = None
            if not location:
                continue
            try:
                version = winreg.QueryValueEx(subkey, "DisplayVersion")[0]
            except OSError:
                version = sub  # fall back to the key name, e.g. "KiCad 10.0"
            root = Path(str(location))
            if root.is_dir():
                results.append((_version_key(str(version)), root))
    return results


def _glob_roots() -> List[Tuple[_VersionKey, Path]]:
    """KiCad install roots from Program Files and common custom base dirs."""
    if platform.system() != "Windows":
        return []

    results: List[Tuple[_VersionKey, Path]] = []
    for base in (r"C:\Program Files\KiCad", r"C:\Program Files (x86)\KiCad", r"C:\KiCad"):
        base_dir = Path(base)
        if not base_dir.is_dir():
            continue
        for child in base_dir.iterdir():
            if child.is_dir():
                results.append((_version_key(child.name), child))
        # Some installs drop straight into <base>\bin with no version subdir.
        if (base_dir / "bin").is_dir():
            results.append((_version_key(base_dir.name), base_dir))
    return results


def windows_kicad_roots() -> List[Path]:
    """KiCad install roots on Windows, newest-version first and de-duplicated.

    Registry entries and filesystem globs are merged; when the same root is found
    by more than one source (the common case — a Program Files install is both in
    the registry and under the glob) it appears once, keyed case-insensitively on
    its normalised path.
    """
    combined = _registry_roots() + _glob_roots()
    # Stable sort by version descending so the newest KiCad wins ties on dedup.
    combined.sort(key=lambda item: item[0], reverse=True)

    seen: set = set()
    roots: List[Path] = []
    for _, root in combined:
        norm = os.path.normcase(os.path.normpath(str(root)))
        if norm in seen:
            continue
        seen.add(norm)
        roots.append(root)
    return roots


def kicad_install_roots() -> List[Path]:
    """KiCad install roots for the current platform, newest-version first.

    Windows returns registry + Program Files + custom-root discovery. Other
    platforms return ``[]`` — their install layout does not have the relocatable-
    root problem this solves, and callers retain their own per-OS paths there.
    """
    if platform.system() == "Windows":
        return windows_kicad_roots()
    return []
