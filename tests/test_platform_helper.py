"""
Tests for platform_helper utility

These are unit tests that work on all platforms.
"""
import pytest
import platform
from pathlib import Path
import sys
import os

# Add parent directory to path to import utils
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from utils.platform_helper import PlatformHelper, detect_platform


class TestPlatformDetection:
    """Test platform detection functions"""

    def test_exactly_one_platform_detected(self):
        """Ensure exactly one platform is detected"""
        platforms = [
            PlatformHelper.is_windows(),
            PlatformHelper.is_linux(),
            PlatformHelper.is_macos(),
        ]
        assert sum(platforms) == 1, "Exactly one platform should be detected"

    def test_platform_name_is_valid(self):
        """Test platform name is human-readable"""
        name = PlatformHelper.get_platform_name()
        assert name in ["Windows", "Linux", "macOS"], f"Unknown platform: {name}"

    def test_platform_name_matches_detection(self):
        """Ensure platform name matches detection functions"""
        name = PlatformHelper.get_platform_name()
        if name == "Windows":
            assert PlatformHelper.is_windows()
        elif name == "Linux":
            assert PlatformHelper.is_linux()
        elif name == "macOS":
            assert PlatformHelper.is_macos()


class TestPathGeneration:
    """Test path generation functions"""

    def test_config_dir_exists_after_ensure(self):
        """Test that config directory is created"""
        PlatformHelper.ensure_directories()
        config_dir = PlatformHelper.get_config_dir()
        assert config_dir.exists(), f"Config dir should exist: {config_dir}"
        assert config_dir.is_dir(), f"Config dir should be a directory: {config_dir}"

    def test_log_dir_exists_after_ensure(self):
        """Test that log directory is created"""
        PlatformHelper.ensure_directories()
        log_dir = PlatformHelper.get_log_dir()
        assert log_dir.exists(), f"Log dir should exist: {log_dir}"
        assert log_dir.is_dir(), f"Log dir should be a directory: {log_dir}"

    def test_cache_dir_exists_after_ensure(self):
        """Test that cache directory is created"""
        PlatformHelper.ensure_directories()
        cache_dir = PlatformHelper.get_cache_dir()
        assert cache_dir.exists(), f"Cache dir should exist: {cache_dir}"
        assert cache_dir.is_dir(), f"Cache dir should be a directory: {cache_dir}"

    def test_config_dir_is_platform_appropriate(self):
        """Test that config directory follows platform conventions"""
        config_dir = PlatformHelper.get_config_dir()

        if PlatformHelper.is_linux():
            # Should be ~/.config/kicad-mcp or $XDG_CONFIG_HOME/kicad-mcp
            if "XDG_CONFIG_HOME" in os.environ:
                expected = Path(os.environ["XDG_CONFIG_HOME"]) / "kicad-mcp"
            else:
                expected = Path.home() / ".config" / "kicad-mcp"
            assert config_dir == expected

        elif PlatformHelper.is_windows():
            # Should be %USERPROFILE%\.kicad-mcp
            expected = Path.home() / ".kicad-mcp"
            assert config_dir == expected

        elif PlatformHelper.is_macos():
            # Should be ~/Library/Application Support/kicad-mcp
            expected = Path.home() / "Library" / "Application Support" / "kicad-mcp"
            assert config_dir == expected

    def test_python_executable_is_valid(self):
        """Test that Python executable path is valid"""
        exe = PlatformHelper.get_python_executable()
        assert exe.exists(), f"Python executable should exist: {exe}"
        assert str(exe) == sys.executable

    def test_kicad_library_search_paths_returns_list(self):
        """Test that library search paths returns a list"""
        paths = PlatformHelper.get_kicad_library_search_paths()
        assert isinstance(paths, list)
        assert len(paths) > 0
        # All paths should be strings (glob patterns)
        assert all(isinstance(p, str) for p in paths)


class TestDetectPlatform:
    """Test the detect_platform convenience function"""

    def test_detect_platform_returns_dict(self):
        """Test that detect_platform returns a dictionary"""
        info = detect_platform()
        assert isinstance(info, dict)

    def test_detect_platform_has_required_keys(self):
        """Test that detect_platform includes all required keys"""
        info = detect_platform()
        required_keys = [
            "system",
            "platform",
            "is_windows",
            "is_linux",
            "is_macos",
            "python_version",
            "python_executable",
            "config_dir",
            "log_dir",
            "cache_dir",
            "kicad_python_paths",
        ]
        for key in required_keys:
            assert key in info, f"Missing key: {key}"

    def test_detect_platform_python_version_format(self):
        """Test that Python version is in correct format"""
        info = detect_platform()
        version = info["python_version"]
        # Should be like "3.12.3"
        parts = version.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)


@pytest.mark.integration
class TestKiCADPathDetection:
    """Tests that require KiCAD to be installed"""

    def test_kicad_python_paths_exist(self):
        """Test that at least one KiCAD Python path exists (if KiCAD is installed)"""
        paths = PlatformHelper.get_kicad_python_paths()
        # This test only makes sense if KiCAD is installed
        # In CI, KiCAD should be installed
        if paths:
            assert all(p.exists() for p in paths), "All returned paths should exist"

    def test_can_import_pcbnew_after_adding_paths(self):
        """Test that pcbnew can be imported after adding KiCAD paths"""
        PlatformHelper.add_kicad_to_python_path()
        try:
            import pcbnew
            # If we get here, pcbnew is available
            assert pcbnew is not None
            version = pcbnew.GetBuildVersion()
            assert version is not None
            print(f"Found KiCAD version: {version}")
        except ImportError:
            pytest.skip("KiCAD pcbnew module not available (KiCAD not installed)")


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
