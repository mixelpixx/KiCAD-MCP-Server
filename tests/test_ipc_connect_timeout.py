"""IPCBackend._open_with_timeout bounds a stuck kipy dial.

kipy dials with pynng block_on_dial=True (no timeout), so a busy KiCad that
isn't servicing its socket could make connect() hang until the client's ~240s
watchdog fires. _open_with_timeout caps a single attempt so the caller falls
back to SWIG in seconds instead.
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.unit

from kicad_mcp.backends.ipc_backend import IPCBackend  # noqa: E402


def test_bounds_a_stuck_dial():
    class StuckKiCad:
        def __init__(self, socket_path=None):
            time.sleep(30)  # emulate a GUI-busy hang

        def ping(self):
            pass

    b = IPCBackend()
    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        b._open_with_timeout(StuckKiCad, "ipc:///tmp/x.sock", 0.5)
    assert time.monotonic() - t0 < 5.0  # bounded, not the 30s sleep


def test_returns_fast_connection():
    class FastKiCad:
        def __init__(self, socket_path=None):
            pass

        def ping(self):
            pass

    kicad, elapsed = IPCBackend()._open_with_timeout(FastKiCad, None, 5.0)
    assert isinstance(kicad, FastKiCad)
    assert elapsed >= 0.0


def test_propagates_fast_failure():
    class FailKiCad:
        def __init__(self, socket_path=None):
            raise ConnectionError("connection refused")

        def ping(self):
            pass

    with pytest.raises(ConnectionError):
        IPCBackend()._open_with_timeout(FailKiCad, None, 5.0)
