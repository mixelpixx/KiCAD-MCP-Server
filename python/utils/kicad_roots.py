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

macOS has the same shape of problem for *bundles* rather than roots: the
DMG layout puts KiCad at ``/Applications/KiCad/KiCad.app``, but the app can
also be dragged straight into ``/Applications/KiCad.app`` (or the user's
``~/Applications``), and every module above hard-coded the DMG path (#543).
``macos_kicad_apps()`` is the macOS counterpart of ``kicad_install_roots()``:
the installed bundles, the one holding the running interpreter first, for
callers to append ``Contents/...`` suffixes to.
"""

import itertools
import logging
import os
import platform
import re
import sys
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Tuple

logger = logging.getLogger("kicad_interface")

# A version tuple used only for newest-first ordering; missing parts sort as 0.
_VersionKey = Tuple[int, int, int]
_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")

# Discovered roots are cached for the process: install locations do not change
# while the server runs, and discovery walks the registry + globs the filesystem,
# which is far too expensive to repeat on every library-path resolution.
_cached_roots: Optional[List[Path]] = None

# Same caching for the macOS bundle list (a handful of is_dir checks, but the
# callers run on every library-path resolution).
_cached_macos_apps: Optional[List[Path]] = None


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


def _discover_windows_roots() -> List[Path]:
    """Merge registry + glob roots, newest-version first and de-duplicated.

    When the same root is found by more than one source (the common case — a
    Program Files install is both in the registry and under the glob) it appears
    once, keyed case-insensitively on its normalised path.
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


def windows_kicad_roots() -> List[Path]:
    """KiCad install roots on Windows, newest-version first and de-duplicated.

    The result is cached for the process (see ``_cached_roots``); a fresh copy is
    returned each call so callers can freely mutate it. Use ``reset_cache()`` in
    tests that change the underlying registry/filesystem view.
    """
    global _cached_roots
    if _cached_roots is None:
        _cached_roots = _discover_windows_roots()
    return list(_cached_roots)


def kicad_install_roots() -> List[Path]:
    """KiCad install roots for the current platform, newest-version first.

    Windows returns registry + Program Files + custom-root discovery. Other
    platforms return ``[]`` — their install layout does not have the relocatable-
    root problem this solves, and callers retain their own per-OS paths there.
    """
    if platform.system() == "Windows":
        return windows_kicad_roots()
    return []


def _macos_bundle_candidates() -> List[Path]:
    """Candidate macOS KiCad.app locations in priority order (may not exist).

    The bundle holding the running interpreter comes first: KiCad's bundled
    Python runs from inside the bundle, so a server launched from it finds
    its own install before any ``/Applications`` copy. Then the DMG layout,
    the app dragged straight into ``/Applications``, and the ``~/Applications``
    variants, with the alternative ``KiCAD`` capitalization last (as
    ``platform_helper`` and ``server.ts`` already handled).
    """
    candidates: List[Path] = []
    exe = Path(sys.executable or "")
    for parent in exe.parents:
        if parent.suffix == ".app" and "kicad" in parent.name.lower():
            candidates.append(parent)
            break
    candidates.extend(
        [
            Path("/Applications/KiCad/KiCad.app"),
            Path("/Applications/KiCad.app"),
            Path.home() / "Applications" / "KiCad" / "KiCad.app",
            Path.home() / "Applications" / "KiCad.app",
            Path("/Applications/KiCAD/KiCad.app"),
            Path.home() / "Applications" / "KiCad" / "KiCAD.app",
        ]
    )
    return candidates


def macos_kicad_apps() -> List[Path]:
    """Installed macOS KiCad.app bundles, the interpreter's bundle first.

    Only bundles that exist are returned, de-duplicated (the ``KiCad`` /
    ``KiCAD`` spellings can name the same directory on a case-insensitive
    filesystem). The result is cached for the process (see ``_cached_roots``);
    a fresh copy is returned each call so callers can freely mutate it. Use
    ``reset_cache()`` in tests that change the underlying filesystem view.
    Non-macOS platforms return ``[]``.
    """
    global _cached_macos_apps
    if platform.system() != "Darwin":
        return []
    if _cached_macos_apps is None:
        seen: set = set()
        apps: List[Path] = []
        for candidate in _macos_bundle_candidates():
            if not candidate.is_dir():
                continue
            key = os.path.normcase(os.path.normpath(str(candidate.resolve())))
            if key in seen:
                continue
            seen.add(key)
            apps.append(candidate)
        _cached_macos_apps = apps
    return list(_cached_macos_apps)


def reroot_kicad_app_path(path: Path) -> List[Path]:
    """Re-root a path inside a missing KiCad.app bundle onto installed bundles (#543).

    Global lib tables can hold stock rows as absolute paths into the bundle
    KiCad was installed in (``/Applications/KiCad/KiCad.app/Contents/...``);
    once the app moves, those rows point at a bundle that no longer exists
    even though the same files ship in the installed bundle. Given such a
    path, return the same ``Contents/...`` suffix under each installed
    bundle, in priority order; ``[]`` when the path has no KiCad.app segment
    or the bundle it names still exists.
    """
    parts = Path(path).parts
    for i, part in enumerate(parts):
        if part.lower().endswith(".app") and "kicad" in part.lower():
            if i + 1 < len(parts) and parts[i + 1] == "Contents":
                if Path(*parts[: i + 1]).is_dir():
                    return []
                suffix = Path(*parts[i + 2 :])
                if not suffix.parts:
                    return []
                return [app / "Contents" / suffix for app in macos_kicad_apps()]
    return []


def reset_cache() -> None:
    """Clear the cached install-root discovery (primarily for tests)."""
    global _cached_roots, _cached_macos_apps
    _cached_roots = None
    _cached_macos_apps = None


def ensure_cairo_on_path(extra_dirs: Iterable[str] = ()) -> Optional[str]:
    """Put the first directory holding ``cairo-2.dll`` at the head of PATH.

    cairocffi loads the library with ``ffi.dlopen("cairo-2")``, which searches
    PATH. KiCad's own Python runs with KiCad's ``bin`` there already; a venv
    does not, and a venv is the layout the TypeScript launcher prefers. Every
    KiCad install ships the DLL in its ``bin`` directory, so after
    *extra_dirs* each install root is tried, newest first. The list used to
    stop at ``Program Files\\KiCad\\9.0`` and ``8.0``, which missed KiCad 10
    and every custom install root (#425).

    Returns the directory now on PATH, or None when no candidate has the DLL.
    Windows-only in practice: the caller gates on the platform, and the
    install-root discovery returns nothing elsewhere.
    """

    def install_bins() -> Iterator[str]:
        # A generator function, not a generator expression: the expression
        # would call kicad_install_roots() (a registry walk) on creation even
        # when a caller's directory already has the DLL.
        for root in kicad_install_roots():
            yield str(root / "bin")

    for directory in itertools.chain(extra_dirs, install_bins()):
        if not directory or not (Path(directory) / "cairo-2.dll").is_file():
            continue
        current = os.environ.get("PATH", "")
        on_path = {
            os.path.normcase(os.path.normpath(entry))
            for entry in current.split(os.pathsep)
            if entry
        }
        if os.path.normcase(os.path.normpath(directory)) not in on_path:
            os.environ["PATH"] = directory + os.pathsep + current
        return directory
    return None
