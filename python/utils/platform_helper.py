"""
Platform detection and path utilities for cross-platform compatibility

This module provides helpers for detecting the current platform and
getting appropriate paths for KiCAD, configuration, logs, etc.
"""
import os
import platform
import sys
from pathlib import Path
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)


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
            # Windows: Check Program Files
            program_files = [
                Path("C:/Program Files/KiCad"),
                Path("C:/Program Files (x86)/KiCad"),
            ]
            for pf in program_files:
                # Check multiple KiCAD versions
                for version in ["9.0", "9.1", "10.0", "8.0"]:
                    path = pf / version / "lib" / "python3" / "dist-packages"
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
            candidates.extend([
                Path(f"/usr/lib/python{py_version}/dist-packages/kicad"),
                Path(f"/usr/local/lib/python{py_version}/dist-packages/kicad"),
            ])

            # Check system Python dist-packages (modern KiCAD 9+ on Ubuntu/Debian)
            # This is where pcbnew.py typically lives on modern systems
            candidates.extend([
                Path(f"/usr/lib/python3/dist-packages"),
                Path(f"/usr/lib/python{py_version}/dist-packages"),
                Path(f"/usr/local/lib/python3/dist-packages"),
                Path(f"/usr/local/lib/python{py_version}/dist-packages"),
            ])

            paths = [p for p in candidates if p.exists()]

        elif PlatformHelper.is_macos():
            # macOS: Check application bundle
            kicad_app = Path("/Applications/KiCad/KiCad.app")
            if kicad_app.exists():
                # Check Python framework path
                for version in ["3.9", "3.10", "3.11", "3.12"]:
                    path = kicad_app / "Contents" / "Frameworks" / "Python.framework" / "Versions" / version / "lib" / f"python{version}" / "site-packages"
                    if path.exists():
                        paths.append(path)

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
            patterns = [
                "C:/Program Files/KiCad/*/share/kicad/symbols/*.kicad_sym",
                "C:/Program Files (x86)/KiCad/*/share/kicad/symbols/*.kicad_sym",
            ]
        elif PlatformHelper.is_linux():
            patterns = [
                "/usr/share/kicad/symbols/*.kicad_sym",
                "/usr/local/share/kicad/symbols/*.kicad_sym",
                str(Path.home() / ".local/share/kicad/symbols/*.kicad_sym"),
            ]
        elif PlatformHelper.is_macos():
            patterns = [
                "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/*.kicad_sym",
            ]

        # Add user library paths for all platforms
        patterns.append(str(Path.home() / "Documents" / "KiCad" / "*" / "symbols" / "*.kicad_sym"))

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
                return Path(xdg_config) / "kicad-mcp"
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
                return Path(xdg_cache) / "kicad-mcp"
            return Path.home() / ".cache" / "kicad-mcp"
        elif PlatformHelper.is_macos():
            return Path.home() / "Library" / "Caches" / "kicad-mcp"
        else:
            return PlatformHelper.get_config_dir() / "cache"

    @staticmethod
    def ensure_directories() -> None:
        """Create all necessary directories if they don't exist"""
        dirs_to_create = [
            PlatformHelper.get_config_dir(),
            PlatformHelper.get_log_dir(),
            PlatformHelper.get_cache_dir(),
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
        "kicad_python_paths": [str(p) for p in PlatformHelper.get_kicad_python_paths()],
    }


if __name__ == "__main__":
    # Quick test/diagnostic
    import json
    info = detect_platform()
    print("Platform Information:")
    print(json.dumps(info, indent=2))
