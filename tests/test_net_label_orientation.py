"""A net label snapped to a pin faces the way the pin does.

Regression guard: the label was written at angle 0 regardless of the pin, and
batch_connect went further and turned it around (a right-facing pin got 180).
KiCad pairs angle 0/90 with `justify left` and 180/270 with `justify right`, so
a label turned back on itself lays the net name across the symbol body. The
`justify` half is not separately settable through the API, so callers could not
repair it without hand-editing the file.
"""

import sys
import types
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.unit

import commands.pin_locator as pin_locator_mod  # noqa: E402
import commands.schematic_handlers as handlers_mod  # noqa: E402


def _iface() -> Any:
    from kicad_interface import KiCADInterface

    return KiCADInterface.__new__(KiCADInterface)


@pytest.fixture()
def schematic(tmp_path: Path) -> Path:
    p = tmp_path / "t.kicad_sch"
    p.write_text(
        '(kicad_sch (version 20250114) (generator "test")\n  (lib_symbols)\n'
        '  (sheet_instances (path "/" (page "1")))\n)\n',
        encoding="utf-8",
    )
    return p


def _fake_locator(pin_angle: float) -> Any:
    return types.SimpleNamespace(
        get_pin_location=lambda p, ref, pin: [100.0, 100.0],
        get_pin_angle=lambda p, ref, pin: pin_angle,
    )


def _added_labels(monkeypatch) -> list:
    """Capture (text, orientation) instead of writing to the file."""
    calls: list = []
    real_add_label = handlers_mod.WireManager.add_label

    def fake_add_label(path, text, position, label_type="label", orientation=0):
        calls.append((text, orientation))
        return True

    monkeypatch.setattr(handlers_mod.WireManager, "add_label", staticmethod(fake_add_label))
    assert real_add_label is not fake_add_label
    return calls


@pytest.mark.parametrize(
    "pin_angle,expected",
    [
        (0, 0),  # pin points right -> text grows right, clear of the body
        (180, 180),  # pin points left -> text grows left
        (90, 90),  # pin points up
        (270, 270),  # pin points down
        (359.6, 0),  # bearings are snapped to the four KiCad orientations
    ],
)
def test_orientation_follows_the_pin(monkeypatch, schematic, pin_angle, expected):
    monkeypatch.setattr(pin_locator_mod, "PinLocator", lambda: _fake_locator(pin_angle))
    calls = _added_labels(monkeypatch)

    result = _iface()._handle_add_schematic_net_label(
        {
            "schematicPath": str(schematic),
            "netName": "SDA",
            "componentRef": "U1",
            "pinNumber": "1",
        }
    )
    assert result["success"] is True
    assert result["orientation"] == expected
    assert calls == [("SDA", expected)]


def test_explicit_orientation_still_wins(monkeypatch, schematic):
    monkeypatch.setattr(pin_locator_mod, "PinLocator", lambda: _fake_locator(0))
    calls = _added_labels(monkeypatch)

    result = _iface()._handle_add_schematic_net_label(
        {
            "schematicPath": str(schematic),
            "netName": "SDA",
            "componentRef": "U1",
            "pinNumber": "1",
            "orientation": 90,
        }
    )
    assert result["success"] is True
    assert calls == [("SDA", 90)]


def test_free_position_label_still_defaults_to_zero(monkeypatch, schematic):
    calls = _added_labels(monkeypatch)

    result = _iface()._handle_add_schematic_net_label(
        {"schematicPath": str(schematic), "netName": "SDA", "position": [10.0, 20.0]}
    )
    assert result["success"] is True
    assert calls == [("SDA", 0)]
