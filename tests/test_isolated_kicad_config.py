"""In stub mode every test sees KiCad's config variables pointed at its own empty temp directory.

Deleting them (the old behaviour) let a test that runs kicad-cli fall back to the user's real config
(%APPDATA%\\kicad, ~/.config/kicad) and write kicad_common.json there.
"""

import os
from pathlib import Path

import pytest

_VARS = ("KICAD_CONFIG_HOME", "APPDATA", "XDG_CONFIG_HOME")
_REAL = os.environ.get("KICAD_USE_REAL_PCBNEW") == "1"  # as conftest.py

pytestmark = pytest.mark.skipif(
    _REAL, reason="real-KiCad mode keeps the caller's config on purpose"
)


def test_config_vars_point_at_an_empty_temp_dir():
    home = Path.home().resolve()
    for var in _VARS:
        value = os.environ.get(var)
        assert value, f"{var} is not set"
        d = Path(value).resolve()
        assert d.is_dir(), f"{var}={value} is not a directory"
        assert not any(d.iterdir()), f"{var}={value} is not empty"
        assert (
            d != home / ".config" and d != home / ".config" / "kicad"
        ), f"{var} is the real config"


_seen = []


@pytest.mark.parametrize("i", [0, 1])
def test_each_test_gets_its_own_dir(i):
    _seen.append(os.environ["KICAD_CONFIG_HOME"])
    if i == 1:
        assert _seen[0] != _seen[1]
