"""Tests for the 7-Zip resolver (utils.seven_zip).

The 7-Zip Windows installer drops 7z.exe into C:\\Program Files\\7-Zip but does not add
it to PATH, so a bare shutil.which("7z") fails on a normal install. The resolver must
find 7-Zip via: $SEVEN_ZIP override -> PATH -> known install locations, with a clear,
actionable error (and absolute paths) when all fail. Mirrors the kicad-cli resolver.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import kicad_mcp.utils as utils.seven_zip as sz  # noqa: E402


def _make_fake_7z(directory: Path, name: str = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    exe = directory / (name or sz._exe_names()[0])
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    return exe


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    sz.reset_cache()
    for var in sz._ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield
    sz.reset_cache()


# --------------------------------------------------------------------------- #
# Resolution order
# --------------------------------------------------------------------------- #


class TestResolutionOrder:
    def test_env_override_valid_wins(self, tmp_path, monkeypatch):
        exe = _make_fake_7z(tmp_path / "custom")
        monkeypatch.setenv("SEVEN_ZIP", str(exe))
        assert sz.resolve_7z(force=True) == str(exe)

    def test_env_override_invalid_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SEVEN_ZIP", str(tmp_path / "missing.exe"))
        assert sz.resolve_7z(force=True) is None

    def test_invalid_override_does_not_fall_back(self, tmp_path, monkeypatch):
        """An explicit (but wrong) override must fail rather than silently picking
        another 7-Zip discoverable on PATH / in an install dir."""
        on_path = _make_fake_7z(tmp_path / "onpath")
        monkeypatch.setattr(sz.shutil, "which", lambda name: str(on_path))
        monkeypatch.setenv("SEVENZIP_PATH", str(tmp_path / "bogus.exe"))
        assert sz.resolve_7z(force=True) is None

    def test_path_lookup_returns_absolute(self, tmp_path, monkeypatch):
        on_path = _make_fake_7z(tmp_path / "bin")
        monkeypatch.setattr(sz.shutil, "which", lambda name: str(on_path))
        monkeypatch.setattr(sz, "_candidate_paths", lambda: [])
        assert sz.resolve_7z(force=True) == str(on_path)

    def test_known_install_dirs_when_not_on_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sz.shutil, "which", lambda name: None)
        installed = _make_fake_7z(tmp_path / "7-Zip")
        monkeypatch.setattr(sz, "_candidate_paths", lambda: [installed])
        resolved = sz.resolve_7z(force=True)
        assert resolved == str(installed)
        assert Path(resolved).is_absolute()

    def test_returns_none_when_nothing_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sz.shutil, "which", lambda name: None)
        monkeypatch.setattr(sz, "_candidate_paths", lambda: [tmp_path / "nope" / "7z.exe"])
        assert sz.resolve_7z(force=True) is None


# --------------------------------------------------------------------------- #
# Windows install-dir enumeration
# --------------------------------------------------------------------------- #


class TestWindowsInstallDirs:
    def test_windows_candidates_cover_program_files_7zip(self, monkeypatch):
        monkeypatch.setattr(sz.platform, "system", lambda: "Windows")
        monkeypatch.setenv("ProgramW6432", r"C:\Program Files")
        monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
        candidates = [str(c) for c in sz._candidate_paths()]
        assert any(c.endswith(r"7-Zip\7z.exe") for c in candidates)
        # Reduced CLIs are offered as fallbacks too.
        assert any(c.endswith(r"7-Zip\7za.exe") for c in candidates)


# --------------------------------------------------------------------------- #
# Caching
# --------------------------------------------------------------------------- #


class TestCaching:
    def test_autodetect_is_cached(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sz.shutil, "which", lambda name: None)
        installed = _make_fake_7z(tmp_path / "7-Zip")
        monkeypatch.setattr(sz, "_candidate_paths", lambda: [installed])
        first = sz.resolve_7z(force=True)
        monkeypatch.setattr(sz, "_candidate_paths", lambda: [])
        assert sz.resolve_7z() == first  # served from cache

    def test_env_override_rechecked_despite_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sz.shutil, "which", lambda name: None)
        installed = _make_fake_7z(tmp_path / "7-Zip")
        monkeypatch.setattr(sz, "_candidate_paths", lambda: [installed])
        assert sz.resolve_7z(force=True) == str(installed)
        monkeypatch.setenv("SEVEN_ZIP", str(tmp_path / "bogus.exe"))
        assert sz.resolve_7z() is None


# --------------------------------------------------------------------------- #
# Error message
# --------------------------------------------------------------------------- #


class TestNotFoundMessage:
    def test_message_lists_locations_and_hints(self):
        msg = sz.seven_zip_not_found_message()
        assert "Could not locate a 7-Zip CLI" in msg
        assert "SEVEN_ZIP" in msg
        assert "PATH" in msg
        assert "Install 7-Zip" in msg or "p7zip" in msg

    def test_message_flags_invalid_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SEVEN_ZIP", str(tmp_path / "wrong.exe"))
        msg = sz.seven_zip_not_found_message()
        assert str(tmp_path / "wrong.exe") in msg
        assert "not a file" in msg


# --------------------------------------------------------------------------- #
# Integration: the resolved binary actually runs
# --------------------------------------------------------------------------- #


def _real_7z() -> str:
    sz.reset_cache()
    return sz.resolve_7z(force=True)


@pytest.mark.integration
class TestResolvedBinaryRuns:
    def test_resolved_7z_emits_banner(self):
        exe = _real_7z()
        if not exe or not Path(exe).is_file():
            pytest.skip("no 7-Zip installed on this machine")
        out = subprocess.run([exe], capture_output=True, text=True)
        # 7-Zip prints its version banner mentioning "7-Zip" on stdout.
        assert "7-Zip" in (out.stdout + out.stderr)
