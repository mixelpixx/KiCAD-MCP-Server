"""Regression test for issue #287: cross-file sys.modules pollution.

``tests/test_rotate_schematic_mirror.py`` used to install a throwaway
``MagicMock`` at ``sys.modules["commands.pin_locator"]`` via
``sys.modules.setdefault(...)`` at module-collection time, with no teardown.
Any later-collected file relying on the real ``commands.pin_locator`` (e.g.
``WireDragger.get_pin_defs``, via ``commands.wire_dragger``) silently got
empty pin data instead of an error: iterating a bare ``MagicMock()`` is a
no-op by default (``MagicMock.__iter__`` returns ``iter([])``), so
``WireDragger.compute_pin_positions`` returned ``{}`` instead of raising.

The leak only manifests across a real pytest collection/run boundary (a
module-level side effect in one file affecting a later-collected file), so it
can't be reproduced by importing modules directly in-process — this runs
pytest as a subprocess against the exact repro from the issue, trimmed to the
fast (no live ``KiCADInterface``) subset so the regression test itself stays
quick.
"""

import subprocess
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent


@pytest.mark.slow
def test_rotate_mirror_then_compute_pin_positions_no_state_leak():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(TESTS_DIR / "test_rotate_schematic_mirror.py"),
            str(TESTS_DIR / "test_move_with_wire_preservation.py") + "::TestComputePinPositions",
            "-q",
            "--no-cov",
        ],
        capture_output=True,
        text=True,
        # Hang protection lives here rather than in pytest-timeout flags:
        # the plugin is not a declared dependency of this repo, and passing
        # --timeout to a pytest without it is a usage error (exit code 4).
        timeout=90,
    )
    assert result.returncode == 0, (
        "Collecting test_rotate_schematic_mirror.py before "
        "test_move_with_wire_preservation.py::TestComputePinPositions must not "
        "leak sys.modules state across files (#287).\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
