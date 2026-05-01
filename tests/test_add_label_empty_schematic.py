"""
Regression tests for WireManager.add_label on schematics with zero existing labels.

Bug: PR #88 rewrote add_label to clone an existing label via kicad-skip; on a
fresh schematic with no labels this returns False. The fix restores a hand-built
sexpdata path (without the spurious fields_autoplaced token) as the primary path.
"""

import importlib.util
import os
import sys
from unittest.mock import MagicMock

import sexpdata
from sexpdata import Symbol

# Stub heavy / optional deps before loading wire_manager
for modname in ("pcbnew", "skip"):
    sys.modules.setdefault(modname, MagicMock())

_wm_spec = importlib.util.spec_from_file_location(
    "wire_manager",
    os.path.join(os.path.dirname(__file__), "..", "python", "commands", "wire_manager.py"),
)
_wm_mod = importlib.util.module_from_spec(_wm_spec)
_wm_spec.loader.exec_module(_wm_mod)
WireManager = _wm_mod.WireManager


_EMPTY_SCH = """\
(kicad_sch (version 20250114) (generator "test")
  (lib_symbols)
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""


def _find_label(sch_data, text):
    for item in sch_data:
        if (
            isinstance(item, list)
            and len(item) >= 2
            and isinstance(item[0], Symbol)
            and str(item[0]) == "label"
            and item[1] == text
        ):
            return item
    return None


def _has_token(label_sexp, name):
    for part in label_sexp[2:]:
        if isinstance(part, list) and part and isinstance(part[0], Symbol) and str(part[0]) == name:
            return True
    return False


def _find_subtoken(label_sexp, name):
    for part in label_sexp[2:]:
        if isinstance(part, list) and part and isinstance(part[0], Symbol) and str(part[0]) == name:
            return part
    return None


def test_add_label_to_empty_schematic_succeeds(tmp_path):
    sch_path = tmp_path / "empty.kicad_sch"
    sch_path.write_text(_EMPTY_SCH)

    ok = WireManager.add_label(sch_path, "TEST", [50.0, 50.0], "label", 0)
    assert ok is True

    sch_data = sexpdata.loads(sch_path.read_text())
    label = _find_label(sch_data, "TEST")
    assert label is not None, 'Expected a (label "TEST" ...) token in the file'

    # The fields_autoplaced token must NOT be present (regression guard for PR #88's bug).
    assert not _has_token(
        label, "fields_autoplaced"
    ), "fields_autoplaced should not be emitted by add_label"


def test_add_label_orientation_180_uses_right_bottom_justify(tmp_path):
    sch_path = tmp_path / "empty180.kicad_sch"
    sch_path.write_text(_EMPTY_SCH)

    ok = WireManager.add_label(sch_path, "NETR", [60.0, 60.0], "label", 180)
    assert ok is True

    sch_data = sexpdata.loads(sch_path.read_text())
    label = _find_label(sch_data, "NETR")
    assert label is not None

    effects = _find_subtoken(label, "effects")
    assert effects is not None, "label must carry an (effects ...) token"

    justify = _find_subtoken(effects, "justify")
    assert justify is not None, "effects must carry a (justify ...) token"

    justify_vals = [str(t) for t in justify[1:] if isinstance(t, Symbol)]
    assert justify_vals == [
        "right",
        "bottom",
    ], f"orientation=180 should produce 'right bottom' justify, got {justify_vals}"
