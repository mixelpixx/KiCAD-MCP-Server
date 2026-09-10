"""Regression tests for #405: a failed log rollover must not stop logging.

``RotatingFileHandler.doRollover`` renames the live log file. On Windows that
rename raises ``PermissionError`` (WinError 32) while any other process holds
the file open. The stock handler then reports "--- Logging error ---" on every
record and writes nothing more: the file in the report sat at exactly the
rotation threshold for two days.

``_TolerantRotatingFileHandler`` treats a failed rollover as best effort: it
keeps writing to the current file, warns once, backs off before retrying, and
rotates normally once the rename succeeds again.
"""

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from kicad_interface import _TolerantRotatingFileHandler  # noqa: E402

pytestmark = pytest.mark.unit

_LOCKED = PermissionError(
    32, "The process cannot access the file because it is being used by another process"
)


def _make_handler(tmp_path, max_bytes=200):
    handler = _TolerantRotatingFileHandler(
        str(tmp_path / "worker.log"),
        maxBytes=max_bytes,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    log = logging.Logger("rotation-tolerance-test")
    log.addHandler(handler)
    return handler, log


def _emit(log, count):
    for i in range(count):
        log.info("x" * 20 + f" record {i}")


def test_failed_rollover_keeps_writing_to_the_current_file(tmp_path, monkeypatch, capsys):
    handler, log = _make_handler(tmp_path)

    def locked(self, source, dest):
        raise _LOCKED

    monkeypatch.setattr(_TolerantRotatingFileHandler, "rotate", locked)
    logging_errors = []
    monkeypatch.setattr(handler, "handleError", logging_errors.append)

    _emit(log, 50)
    handler.close()

    text = (tmp_path / "worker.log").read_text(encoding="utf-8")
    assert "record 0" in text and "record 49" in text
    assert logging_errors == [], "a failed rollover must not be reported as a logging error"
    assert not (tmp_path / "worker.log.1").exists()
    assert capsys.readouterr().err.count("log rotation") == 1, "warn once, not per record"


def test_failed_rollover_backs_off_instead_of_retrying_every_record(tmp_path, monkeypatch):
    handler, log = _make_handler(tmp_path)
    attempts = []

    def locked(self, source, dest):
        attempts.append(source)
        raise _LOCKED

    monkeypatch.setattr(_TolerantRotatingFileHandler, "rotate", locked)
    monkeypatch.setattr(handler, "handleError", lambda record: None)

    _emit(log, 50)
    handler.close()

    assert len(attempts) == 1


def test_rotation_resumes_once_the_rename_succeeds(tmp_path, monkeypatch):
    handler, log = _make_handler(tmp_path)
    handler._RETRY_SECONDS = 0.0
    calls = []
    real_rotate = _TolerantRotatingFileHandler.rotate

    def flaky(self, source, dest):
        calls.append(source)
        if len(calls) == 1:
            raise _LOCKED
        return real_rotate(self, source, dest)

    monkeypatch.setattr(_TolerantRotatingFileHandler, "rotate", flaky)
    monkeypatch.setattr(handler, "handleError", lambda record: None)

    _emit(log, 50)
    handler.close()

    assert len(calls) >= 2
    assert (tmp_path / "worker.log.1").exists()
    assert "record 49" in (tmp_path / "worker.log").read_text(encoding="utf-8")


def test_successful_rollover_is_unchanged(tmp_path):
    handler, log = _make_handler(tmp_path)
    _emit(log, 50)
    handler.close()

    assert (tmp_path / "worker.log.1").exists()
    assert (tmp_path / "worker.log").stat().st_size <= 200
