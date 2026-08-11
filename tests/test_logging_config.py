"""
Regression tests for env-driven, single-writer logging (issue #181).

Before this fix kicad_interface.py hardcoded the log level to DEBUG and used a
plain (unbounded) FileHandler, and the noisy kicad-skip loggers were never
muted — so ~/.kicad-mcp/logs grew to gigabytes and LOG_LEVEL was ignored.

These tests exercise level parsing, skip-logger muting, and the rule that the
Python worker logs only to stderr while the TypeScript parent owns bounded
file logging. No real KiCAD required.
"""

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from kicad_interface import (  # noqa: E402
    _env_flag_enabled,
    _parse_log_level,
)


@pytest.mark.unit
class TestParseLogLevel:
    def test_defaults_to_info_when_unset(self, monkeypatch):
        monkeypatch.delenv("KICAD_MCP_LOG_LEVEL", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        assert _parse_log_level() == logging.INFO

    def test_reads_log_level_env(self, monkeypatch):
        monkeypatch.delenv("KICAD_MCP_LOG_LEVEL", raising=False)
        monkeypatch.setenv("LOG_LEVEL", "warning")
        assert _parse_log_level() == logging.WARNING

    def test_kicad_mcp_log_level_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "debug")
        monkeypatch.setenv("KICAD_MCP_LOG_LEVEL", "error")
        assert _parse_log_level() == logging.ERROR

    def test_case_insensitive_and_aliases(self, monkeypatch):
        monkeypatch.delenv("KICAD_MCP_LOG_LEVEL", raising=False)
        for raw, expected in [
            ("debug", logging.DEBUG),
            ("INFO", logging.INFO),
            ("Warn", logging.WARNING),
            ("FATAL", logging.CRITICAL),
        ]:
            monkeypatch.setenv("LOG_LEVEL", raw)
            assert _parse_log_level() == expected

    def test_off_disables_logging(self, monkeypatch):
        monkeypatch.delenv("KICAD_MCP_LOG_LEVEL", raising=False)
        for raw in ("OFF", "none", "0", "false"):
            monkeypatch.setenv("LOG_LEVEL", raw)
            assert _parse_log_level() > logging.CRITICAL

    def test_garbage_falls_back_to_info(self, monkeypatch):
        monkeypatch.delenv("KICAD_MCP_LOG_LEVEL", raising=False)
        monkeypatch.setenv("LOG_LEVEL", "verbose-ish")
        assert _parse_log_level() == logging.INFO


@pytest.mark.unit
class TestEnvHelpers:
    def test_flag_truthy_values(self, monkeypatch):
        for raw in ("1", "true", "YES", "On"):
            monkeypatch.setenv("X_FLAG", raw)
            assert _env_flag_enabled("X_FLAG") is True

    def test_flag_falsey_values(self, monkeypatch):
        for raw in ("0", "false", "no", ""):
            monkeypatch.setenv("X_FLAG", raw)
            assert _env_flag_enabled("X_FLAG") is False
        monkeypatch.delenv("X_FLAG", raising=False)
        assert _env_flag_enabled("X_FLAG") is False


@pytest.mark.unit
class TestLoggingSideEffects:
    def test_skip_loggers_muted_by_default(self):
        # Importing kicad_interface (no KICAD_MCP_DEBUG_SKIP in the test env)
        # must have set the noisy kicad-skip loggers to WARNING.
        for name in ("skip", "skip.sexp", "skip.sexp.parser", "skip.sexp.sourcefile"):
            assert logging.getLogger(name).level == logging.WARNING

    def test_python_worker_does_not_install_a_file_handler(self):
        assert all(
            "kicad_interface" not in str(getattr(handler, "baseFilename", ""))
            for handler in logging.getLogger().handlers
        )
