"""
Platform detection and path utilities for cross-platform compatibility

This module provides helpers for detecting the current platform and
getting appropriate paths for KiCAD, configuration, logs, etc.
"""

import json
import logging
import os
import platform
import sys
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

#: KiCad releases whose per-version configuration directories are searched,
#: newest first (see ``PlatformHelper.kicad_config_dirs``).
KICAD_CONFIG_VERSIONS = ("10.0", "9.0", "8.0")


class PlatformHelper:
    """Platform detection and path resolution utilities"""

    @staticmethod
    def is_windows() -> bool:
        """Check if running on Windows"""
        return platform.system() == "Windows"

    @staticmethod
    def is_linux() -> bool:
        """Check if running on Linux"""
        return platform.system() == "Linux"

    @staticmethod
    def is_macos() -> bool:
        """Check if running on macOS"""
        return platform.system() == "Darwin"

    @staticmethod
    def get_platform_name() -> str:
        """Get human-readable platform name"""
        system = platform.system()
        if system == "Darwin":
            return "macOS"
        return system

    @staticmethod
    def get_kicad_python_paths() -> List[Path]:
        """
        Get potential KiCAD Python dist-packages paths for current platform

        Returns:
            List of potential paths to check (in priority order)
        """
        paths = []

        if PlatformHelper.is_windows():
            # Discover install roots (registry + Program Files + custom C:\KiCad
            # roots, newest first) via the shared helper so a relocated install is
            # found here the same as by cli/footprint lookups (#286).
            from utils.kicad_roots import kicad_install_roots

            for root in kicad_install_roots():
                # KiCad 10.0+ Windows: bin/Lib/site-packages
                path = root / "bin" / "Lib" / "site-packages"
                if path.exists():
                    paths.append(path)
                # KiCad 9.x Windows: lib/python3/dist-packages
                path = root / "lib" / "python3" / "dist-packages"
                if path.exists():
                    paths.append(path)

        elif PlatformHelper.is_linux():
            # Linux: Check common installation paths
            candidates = [
                Path("/usr/lib/kicad/lib/python3/dist-packages"),
                Path("/usr/share/kicad/scripting/plugins"),
                Path("/usr/local/lib/kicad/lib/python3/dist-packages"),
                Path.home() / ".local/lib/kicad/lib/python3/dist-packages",
            ]

            # Also check based on Python version
            py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
            candidates.extend(
                [
                    Path(f"/usr/lib/python{py_version}/dist-packages/kicad"),
                    Path(f"/usr/local/lib/python{py_version}/dist-packages/kicad"),
                ]
            )

            # Check system Python dist-packages (modern KiCAD 9+ on Ubuntu/Debian)
            # This is where pcbnew.py typically lives on modern systems
            candidates.extend(
                [
                    Path(f"/usr/lib/python3/dist-packages"),
                    Path(f"/usr/lib/python{py_version}/dist-packages"),
                    Path(f"/usr/local/lib/python3/dist-packages"),
                    Path(f"/usr/local/lib/python{py_version}/dist-packages"),
                ]
            )

            paths = [p for p in candidates if p.exists()]

        elif PlatformHelper.is_macos():
            # macOS: Check multiple KiCAD application bundle locations
            kicad_app_paths = [
                Path("/Applications/KiCad/KiCad.app"),
                Path("/Applications/KiCAD/KiCad.app"),  # Alternative capitalization
                Path.home() / "Applications" / "KiCad" / "KiCad.app",  # User Applications
            ]

            # Check Python framework paths in each KiCAD installation
            for kicad_app in kicad_app_paths:
                if kicad_app.exists():
                    for version in ["3.9", "3.10", "3.11", "3.12", "3.13"]:
                        path = (
                            kicad_app
                            / "Contents"
                            / "Frameworks"
                            / "Python.framework"
                            / "Versions"
                            / version
                            / "lib"
                            / f"python{version}"
                            / "site-packages"
                        )
                        if path.exists():
                            paths.append(path)

            # Also check Homebrew Python site-packages (if pcbnew installed via pip)
            homebrew_paths = [
                Path("/opt/homebrew/lib/python3.12/site-packages"),  # Apple Silicon
                Path("/opt/homebrew/lib/python3.11/site-packages"),
                Path("/usr/local/lib/python3.12/site-packages"),  # Intel Mac
                Path("/usr/local/lib/python3.11/site-packages"),
            ]
            for hp in homebrew_paths:
                pcbnew_path = hp / "pcbnew.py"
                if pcbnew_path.exists():
                    paths.append(hp)

        if not paths:
            logger.warning(f"No KiCAD Python paths found for {PlatformHelper.get_platform_name()}")
        else:
            logger.info(f"Found {len(paths)} potential KiCAD Python paths")

        return paths

    @staticmethod
    def get_kicad_python_path() -> Optional[Path]:
        """
        Get the first valid KiCAD Python path

        Returns:
            Path to KiCAD Python dist-packages, or None if not found
        """
        paths = PlatformHelper.get_kicad_python_paths()
        return paths[0] if paths else None

    @staticmethod
    def get_kicad_library_search_paths() -> List[str]:
        """
        Get platform-appropriate KiCAD symbol library search paths

        Returns:
            List of glob patterns for finding .kicad_sym files
        """
        patterns = []

        if PlatformHelper.is_windows():
            # Build symbol-library globs from the shared install-root discovery
            # (registry + Program Files + custom C:\KiCad roots) so libraries in a
            # relocated install are found, not just Program Files ones (#286).
            from utils.kicad_roots import kicad_install_roots

            for root in kicad_install_roots():
                symbols = root / "share" / "kicad" / "symbols"
                # KiCAD 8/9 single-file libraries
                patterns.append(str(symbols / "*.kicad_sym"))
                # KiCAD 10 per-symbol directory libraries
                patterns.append(str(symbols / "*.kicad_symdir" / "*.kicad_sym"))
        elif PlatformHelper.is_linux():
            patterns = [
                "/usr/share/kicad/symbols/*.kicad_sym",
                "/usr/local/share/kicad/symbols/*.kicad_sym",
                str(Path.home() / ".local/share/kicad/symbols/*.kicad_sym"),
                # KiCAD 10 per-symbol directory libraries
                "/usr/share/kicad/symbols/*.kicad_symdir/*.kicad_sym",
                "/usr/local/share/kicad/symbols/*.kicad_symdir/*.kicad_sym",
            ]
        elif PlatformHelper.is_macos():
            patterns = [
                "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/*.kicad_sym",
                "/Applications/KiCAD/KiCad.app/Contents/SharedSupport/symbols/*.kicad_sym",
                str(
                    Path.home()
                    / "Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/*.kicad_sym"
                ),
                # KiCAD 10 per-symbol directory libraries
                "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/*.kicad_symdir/*.kicad_sym",
            ]

        # Add user library paths for all platforms
        patterns.append(str(Path.home() / "Documents" / "KiCad" / "*" / "symbols" / "*.kicad_sym"))
        patterns.append(
            str(
                Path.home()
                / "Documents"
                / "KiCad"
                / "*"
                / "symbols"
                / "*.kicad_symdir"
                / "*.kicad_sym"
            )
        )

        return patterns

    @staticmethod
    def get_config_dir() -> Path:
        r"""
        Get appropriate configuration directory for current platform

        Follows platform conventions:
        - Windows: %USERPROFILE%\.kicad-mcp
        - Linux: $XDG_CONFIG_HOME/kicad-mcp or ~/.config/kicad-mcp
        - macOS: ~/Library/Application Support/kicad-mcp

        Returns:
            Path to configuration directory
        """
        if PlatformHelper.is_windows():
            return Path.home() / ".kicad-mcp"
        elif PlatformHelper.is_linux():
            # Use XDG Base Directory specification
            xdg_config = os.environ.get("XDG_CONFIG_HOME")
            if xdg_config:
                xdg_config_path = Path(xdg_config).expanduser()
                if xdg_config_path.is_absolute():
                    return xdg_config_path / "kicad-mcp"
                logger.warning("Ignoring relative XDG_CONFIG_HOME: %s", xdg_config)
            return Path.home() / ".config" / "kicad-mcp"
        elif PlatformHelper.is_macos():
            return Path.home() / "Library" / "Application Support" / "kicad-mcp"
        else:
            # Fallback for unknown platforms
            return Path.home() / ".kicad-mcp"

    @staticmethod
    def get_log_dir() -> Path:
        """
        Get appropriate log directory for current platform

        Returns:
            Path to log directory
        """
        config_dir = PlatformHelper.get_config_dir()
        return config_dir / "logs"

    @staticmethod
    def get_cache_dir() -> Path:
        r"""
        Get appropriate cache directory for current platform

        Follows platform conventions:
        - Windows: %USERPROFILE%\.kicad-mcp\cache
        - Linux: $XDG_CACHE_HOME/kicad-mcp or ~/.cache/kicad-mcp
        - macOS: ~/Library/Caches/kicad-mcp

        Returns:
            Path to cache directory
        """
        if PlatformHelper.is_windows():
            return PlatformHelper.get_config_dir() / "cache"
        elif PlatformHelper.is_linux():
            xdg_cache = os.environ.get("XDG_CACHE_HOME")
            if xdg_cache:
                xdg_cache_path = Path(xdg_cache).expanduser()
                if xdg_cache_path.is_absolute():
                    return xdg_cache_path / "kicad-mcp"
                logger.warning("Ignoring relative XDG_CACHE_HOME: %s", xdg_cache)
            return Path.home() / ".cache" / "kicad-mcp"
        elif PlatformHelper.is_macos():
            return Path.home() / "Library" / "Caches" / "kicad-mcp"
        else:
            return PlatformHelper.get_config_dir() / "cache"

    @staticmethod
    def get_data_dir() -> Path:
        r"""
        Get appropriate data directory for current platform

        Used for application state that should persist across runs and is not
        a transient cache (e.g. the JLCPCB parts database).

        Follows platform conventions:
        - Windows: %USERPROFILE%\.kicad-mcp\data
        - Linux: $XDG_DATA_HOME/kicad-mcp or ~/.local/share/kicad-mcp
        - macOS: ~/Library/Application Support/kicad-mcp

        Returns:
            Path to data directory
        """
        if PlatformHelper.is_windows():
            return PlatformHelper.get_config_dir() / "data"
        elif PlatformHelper.is_linux():
            xdg_data = os.environ.get("XDG_DATA_HOME")
            if xdg_data:
                xdg_data_path = Path(xdg_data).expanduser()
                if xdg_data_path.is_absolute():
                    return xdg_data_path / "kicad-mcp"
                logger.warning("Ignoring relative XDG_DATA_HOME: %s", xdg_data)
            return Path.home() / ".local" / "share" / "kicad-mcp"
        elif PlatformHelper.is_macos():
            return Path.home() / "Library" / "Application Support" / "kicad-mcp"
        else:
            return PlatformHelper.get_config_dir() / "data"

    @staticmethod
    def ensure_directories() -> None:
        """Create all necessary directories if they don't exist"""
        dirs_to_create = [
            PlatformHelper.get_config_dir(),
            PlatformHelper.get_log_dir(),
            PlatformHelper.get_cache_dir(),
            PlatformHelper.get_data_dir(),
        ]

        for directory in dirs_to_create:
            directory.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Ensured directory exists: {directory}")

    @staticmethod
    def get_python_executable() -> Path:
        """Get path to current Python executable"""
        return Path(sys.executable)

    @staticmethod
    def add_kicad_to_python_path() -> bool:
        """
        Add KiCAD Python paths to sys.path

        Returns:
            True if at least one path was added, False otherwise
        """
        paths_added = False

        for path in PlatformHelper.get_kicad_python_paths():
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
                logger.info(f"Added to Python path: {path}")
                paths_added = True

        return paths_added

    @staticmethod
    def kicad_config_dirs() -> List[Path]:
        r"""KiCad's per-version user configuration directories, newest version first.

        KiCad keeps its settings, including the global ``fp-lib-table`` and
        ``sym-lib-table`` and ``kicad_common.json``, in ``<root>\<major.minor>``:
        ``%APPDATA%\kicad`` on Windows, ``~/.config/kicad`` (or
        ``$XDG_CONFIG_HOME/kicad``) on Linux, ``~/Library/Preferences/kicad`` on
        macOS, or ``$KICAD_CONFIG_HOME`` when that is set. Each KiCad release
        reads only its own version's directory, and an upgraded machine keeps the
        older ones, so a lookup walks this list and takes the first hit. A
        hard-coded ``9.0`` finds nothing on a machine that has only KiCad 10
        (#425).
        """
        home = Path.home()
        roots = [
            Path(os.environ["KICAD_CONFIG_HOME"]) if os.environ.get("KICAD_CONFIG_HOME") else None,
            Path(os.environ["APPDATA"]) / "kicad" if os.environ.get("APPDATA") else None,
            home / "AppData" / "Roaming" / "kicad",
            (
                Path(os.environ["XDG_CONFIG_HOME"]) / "kicad"
                if os.environ.get("XDG_CONFIG_HOME")
                else None
            ),
            home / ".config" / "kicad",
            home / "Library" / "Preferences" / "kicad",
        ]
        dirs: List[Path] = []
        for version in KICAD_CONFIG_VERSIONS:
            for root in roots:
                if root is not None and root / version not in dirs:
                    dirs.append(root / version)
        return dirs

    @staticmethod
    def find_kicad_3rd_party_dir() -> Optional[str]:
        """The directory ``${KICAD10_3RD_PARTY}`` and its siblings stand for.

        That is where KiCad's Plugin and Content Manager installs libraries, and
        library tables refer to them through the variable. Resolution order:

        1. The shell environment: KICAD10_3RD_PARTY, KICAD9_3RD_PARTY,
           KICAD8_3RD_PARTY, then KICAD_3RD_PARTY.
        2. The newest KiCad configuration's own versioned variable, e.g.
           KICAD10_3RD_PARTY in ``10.0/kicad_common.json`` (Preferences >
           Configure Paths).
        3. That version's default location, ``Documents/KiCad/<ver>/3rdparty``
           on Windows and macOS or ``~/.local/share/kicad/<ver>/3rdparty`` on
           Linux, then the other versions' defaults, newest first.

        Steps 2 and 3 used to read only the 9.0 configuration and default to
        9.0, so on a machine with only KiCad 10 the variable never resolved
        unless it was set in the shell (#425).
        """
        for var in ("KICAD10_3RD_PARTY", "KICAD9_3RD_PARTY", "KICAD8_3RD_PARTY", "KICAD_3RD_PARTY"):
            path = os.environ.get(var)
            if path and os.path.isdir(path):
                return path

        version = None
        for config_dir in PlatformHelper.kicad_config_dirs():
            config_path = config_dir / "kicad_common.json"
            if not config_path.is_file():
                continue
            version = config_dir.name
            var = f"KICAD{version.split('.')[0]}_3RD_PARTY"
            path = PlatformHelper._read_kicad_common_vars(config_path).get(var)
            if path and os.path.isdir(path):
                return path
            break

        versions = list(KICAD_CONFIG_VERSIONS)
        if version in versions:
            versions.remove(version)
            versions.insert(0, version)
        home = Path.home()
        for ver in versions:
            for candidate in (
                home / "Documents" / "KiCad" / ver / "3rdparty",  # Windows, macOS
                home / ".local" / "share" / "kicad" / ver / "3rdparty",  # Linux
            ):
                if candidate.is_dir():
                    return str(candidate)

        # Not a warning: most installs never use the PCM, and this runs once
        # per library-table row.
        logger.debug("Could not find KiCad 3rd party directory")
        return None

    @staticmethod
    def find_kicad_template_dir() -> Optional[str]:
        """The directory ``${KICAD10_TEMPLATE_DIR}`` and its siblings stand for.

        KiCad 10's global library tables hold a single ``(type "Table")`` row,
        ``(uri "${KICAD10_TEMPLATE_DIR}/sym-lib-table")``, that stands for every
        stock library; the table it names lives in KiCad's ``template``
        directory. Like the symbol and footprint directories, KiCad defines the
        variable internally, so it is in neither ``kicad_common.json`` nor the
        process environment unless the user set it.

        Resolution order: the shell environment (KICAD10_TEMPLATE_DIR,
        KICAD9_TEMPLATE_DIR, KICAD8_TEMPLATE_DIR, then KICAD_TEMPLATE_DIR), then
        ``share/kicad/template`` under each discovered install root, then the
        Linux and macOS system locations.
        """
        for var in (
            "KICAD10_TEMPLATE_DIR",
            "KICAD9_TEMPLATE_DIR",
            "KICAD8_TEMPLATE_DIR",
            "KICAD_TEMPLATE_DIR",
        ):
            path = os.environ.get(var)
            if path and os.path.isdir(path):
                return path

        candidates: List[Path] = []
        try:
            from utils.kicad_roots import kicad_install_roots

            candidates += [root / "share" / "kicad" / "template" for root in kicad_install_roots()]
        except Exception:
            pass
        candidates += [
            Path("/usr/share/kicad/template"),
            Path("/usr/local/share/kicad/template"),
            Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/template"),
        ]
        for candidate in candidates:
            if candidate.is_dir():
                return str(candidate)

        logger.debug("Could not find KiCad template directory")
        return None

    @staticmethod
    def _read_kicad_common_vars(config_path: Path) -> Dict[str, str]:
        """``environment.vars`` of one kicad_common.json; {} if absent or unreadable.

        KiCad writes ``"vars": null`` until the user adds a path variable.
        """
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            vars_ = (config.get("environment") or {}).get("vars") or {}
        except (OSError, ValueError, AttributeError):
            return {}
        if not isinstance(vars_, dict):
            return {}
        return {k: str(v) for k, v in vars_.items()}

    @staticmethod
    def load_kicad_env_vars() -> Dict[str, str]:
        """
        Load user-defined environment variables from kicad_common.json.

        KiCad stores custom path variables (Preferences > Configure Paths) in
        kicad_common.json under environment.vars. These are referenced in
        sym-lib-table / fp-lib-table URIs, e.g. ``${SEEK}/mylib.kicad_sym``.
        The newest KiCad version's file is the one read.

        Returns:
            Dict of variable name -> value (empty if not found or unreadable)
        """
        for config_dir in PlatformHelper.kicad_config_dirs():
            config_path = config_dir / "kicad_common.json"
            if config_path.is_file():
                return PlatformHelper._read_kicad_common_vars(config_path)
        return {}


# Convenience function for quick platform detection
def detect_platform() -> dict:
    """
    Detect platform and return useful information

    Returns:
        Dictionary with platform information
    """
    return {
        "system": platform.system(),
        "platform": PlatformHelper.get_platform_name(),
        "is_windows": PlatformHelper.is_windows(),
        "is_linux": PlatformHelper.is_linux(),
        "is_macos": PlatformHelper.is_macos(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_executable": str(PlatformHelper.get_python_executable()),
        "config_dir": str(PlatformHelper.get_config_dir()),
        "log_dir": str(PlatformHelper.get_log_dir()),
        "cache_dir": str(PlatformHelper.get_cache_dir()),
        "data_dir": str(PlatformHelper.get_data_dir()),
        "kicad_python_paths": [str(p) for p in PlatformHelper.get_kicad_python_paths()],
    }


if __name__ == "__main__":
    # Quick test/diagnostic
    import json

    info = detect_platform()
    print("Platform Information:")
    print(json.dumps(info, indent=2))
