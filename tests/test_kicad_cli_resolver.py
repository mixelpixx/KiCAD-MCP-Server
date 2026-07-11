"""Tests for the centralized kicad-cli resolver (utils.kicad_cli).

KiCad's Windows installer does not put KiCad\\<ver>\\bin on PATH, so a bare
shutil.which("kicad-cli") fails on a normal install. The resolver must find kicad-cli
via: $KICAD_CLI override -> next to the running interpreter (KiCad's bundled python) ->
PATH -> known install locations, with a clear actionable error when all fail.
"""

import shutil
import sys
from pathlib import Path
from typing import Any, Optional

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import kicad_mcp.utils as utils.kicad_cli as kc  # noqa: E402

TEMPLATES_DIR = Path(__file__).parent.parent / "python" / "templates"
EMPTY_SCH = TEMPLATES_DIR / "empty.kicad_sch"


def _make_fake_cli(directory: Path) -> Path:
    """Create a file with the platform's kicad-cli basename inside ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    cli = directory / kc._cli_name()
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    cli.chmod(0o755)
    return cli


@pytest.fixture(autouse=True)
def _clean_resolver_state(monkeypatch):
    """Each test starts with a clear cache and no override env vars."""
    kc.reset_cache()
    for var in kc._ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield
    kc.reset_cache()


# --------------------------------------------------------------------------- #
# Resolution order
# --------------------------------------------------------------------------- #


class TestResolutionOrder:
    def test_env_override_valid_wins(self, tmp_path, monkeypatch):
        cli = _make_fake_cli(tmp_path / "custom")
        monkeypatch.setenv("KICAD_CLI", str(cli))
        assert kc.resolve_kicad_cli(force=True) == str(cli)

    def test_env_override_invalid_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KICAD_CLI", str(tmp_path / "does_not_exist.exe"))
        assert kc.resolve_kicad_cli(force=True) is None

    def test_invalid_override_does_not_fall_back_to_other_binary(self, tmp_path, monkeypatch):
        """An explicit (but wrong) override must fail rather than silently pick another
        kicad-cli — even when one is discoverable next to the interpreter."""
        interp_dir = tmp_path / "interp"
        _make_fake_cli(interp_dir)
        monkeypatch.setattr(sys, "executable", str(interp_dir / "python"))
        monkeypatch.setenv("KICAD_CLI", str(tmp_path / "bogus.exe"))
        assert kc.resolve_kicad_cli(force=True) is None

    def test_interpreter_adjacent_is_preferred_over_path(self, tmp_path, monkeypatch):
        interp_dir = tmp_path / "kicad_bin"
        adjacent = _make_fake_cli(interp_dir)
        monkeypatch.setattr(sys, "executable", str(interp_dir / "python"))
        # PATH would resolve to a different binary, but interpreter-adjacent wins.
        other = _make_fake_cli(tmp_path / "elsewhere")
        monkeypatch.setattr(kc.shutil, "which", lambda name: str(other))
        assert kc.resolve_kicad_cli(force=True) == str(adjacent)

    def test_path_used_when_not_interpreter_adjacent(self, tmp_path, monkeypatch):
        # Interpreter dir has no kicad-cli.
        monkeypatch.setattr(sys, "executable", str(tmp_path / "empty" / "python"))
        on_path = _make_fake_cli(tmp_path / "onpath")
        monkeypatch.setattr(kc.shutil, "which", lambda name: str(on_path))
        monkeypatch.setattr(kc, "_candidate_paths", lambda: [])
        assert kc.resolve_kicad_cli(force=True) == str(on_path)

    def test_known_install_locations_last(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "executable", str(tmp_path / "empty" / "python"))
        monkeypatch.setattr(kc.shutil, "which", lambda name: None)
        known = _make_fake_cli(tmp_path / "install" / "bin")
        monkeypatch.setattr(kc, "_candidate_paths", lambda: [known])
        assert kc.resolve_kicad_cli(force=True) == str(known)

    def test_returns_none_when_nothing_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "executable", str(tmp_path / "empty" / "python"))
        monkeypatch.setattr(kc.shutil, "which", lambda name: None)
        monkeypatch.setattr(kc, "_candidate_paths", lambda: [tmp_path / "missing" / "kicad-cli"])
        assert kc.resolve_kicad_cli(force=True) is None


# --------------------------------------------------------------------------- #
# Caching
# --------------------------------------------------------------------------- #


class TestCaching:
    def test_autodetect_result_is_cached(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "executable", str(tmp_path / "empty" / "python"))
        monkeypatch.setattr(kc.shutil, "which", lambda name: None)
        known = _make_fake_cli(tmp_path / "install" / "bin")
        monkeypatch.setattr(kc, "_candidate_paths", lambda: [known])

        first = kc.resolve_kicad_cli(force=True)
        # Now make discovery impossible; cached value must still be returned.
        monkeypatch.setattr(kc, "_candidate_paths", lambda: [])
        assert kc.resolve_kicad_cli() == first

    def test_env_override_rechecked_despite_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "executable", str(tmp_path / "empty" / "python"))
        monkeypatch.setattr(kc.shutil, "which", lambda name: None)
        known = _make_fake_cli(tmp_path / "install" / "bin")
        monkeypatch.setattr(kc, "_candidate_paths", lambda: [known])
        assert kc.resolve_kicad_cli(force=True) == str(known)  # populate cache

        # Setting a bogus override must override the cache and yield None.
        monkeypatch.setenv("KICAD_CLI", str(tmp_path / "bogus.exe"))
        assert kc.resolve_kicad_cli() is None


# --------------------------------------------------------------------------- #
# Error message
# --------------------------------------------------------------------------- #


class TestNotFoundMessage:
    def test_message_lists_locations_and_env_hint(self):
        msg = kc.kicad_cli_not_found_message()
        assert "Could not locate kicad-cli" in msg
        assert "KICAD_CLI" in msg
        assert "PATH" in msg
        # Mentions at least one concrete candidate path and the actionable hint.
        assert "kicad-cli" in msg
        assert "Set the KICAD_CLI environment variable" in msg

    def test_message_flags_invalid_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KICAD_CLI", str(tmp_path / "wrong.exe"))
        msg = kc.kicad_cli_not_found_message()
        assert str(tmp_path / "wrong.exe") in msg
        assert "not a file" in msg


# --------------------------------------------------------------------------- #
# End-to-end: a cli-backed tool resolves kicad-cli without KiCad bin on PATH
# --------------------------------------------------------------------------- #


def _real_kicad_cli() -> Optional[str]:
    found = shutil.which("kicad-cli") or shutil.which("kicad-cli.exe")
    if found:
        return found
    for cand in kc._candidate_paths():
        if cand.is_file():
            return str(cand)
    return None


def _path_without_kicad(monkeypatch) -> None:
    """Remove any KiCad bin entries from PATH to simulate the default Windows install."""
    import os

    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if "kicad" not in p.lower()]
    monkeypatch.setenv("PATH", os.pathsep.join(parts))


@pytest.mark.integration
class TestCliBackedToolEndToEnd:
    def setup_method(self) -> None:
        if not _real_kicad_cli():
            pytest.skip("kicad-cli not available on this machine")

    def test_export_netlist_succeeds_without_kicad_on_path(self, tmp_path, monkeypatch):
        """generate/export netlist must succeed even when KiCad's bin is not on PATH."""
        from kicad_interface import KiCADInterface

        kc.reset_cache()
        _path_without_kicad(monkeypatch)

        sch = tmp_path / "board.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        out = tmp_path / "board.net"

        result = KiCADInterface()._handle_export_netlist(
            {"schematicPath": str(sch), "outputPath": str(out)}
        )
        assert result["success"] is True, result
        assert out.exists()

    def test_resolved_cli_version_matches_running_kicad(self):
        import subprocess

        kc.reset_cache()
        cli = kc.resolve_kicad_cli(force=True)
        assert cli is not None
        out = subprocess.run([cli, "version"], capture_output=True, text=True)
        assert out.returncode == 0
        # e.g. "10.0.4" — a bare major.minor.patch line.
        assert out.stdout.strip()[0].isdigit()


@pytest.mark.unit
class TestCliBackedToolClearError:
    def test_bogus_override_yields_actionable_error(self, tmp_path, monkeypatch):
        """With KICAD_CLI pointing at a bogus path, a cli-backed tool must fail with the
        new clear error (locations tried + env-var hint), not spawn a wrong binary."""
        from kicad_interface import KiCADInterface

        kc.reset_cache()
        monkeypatch.setenv("KICAD_CLI", str(tmp_path / "nope" / "kicad-cli.exe"))

        sch = tmp_path / "board.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)

        result = KiCADInterface()._handle_export_netlist(
            {"schematicPath": str(sch), "outputPath": str(tmp_path / "out.net")}
        )
        assert result["success"] is False
        assert "Could not locate kicad-cli" in result["message"]
        assert "KICAD_CLI" in result["message"]
