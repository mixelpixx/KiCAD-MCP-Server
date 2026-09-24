"""PinLocator must not answer from a stale cache after the schematic changes.

``ConnectionManager.get_pin_locator()`` hands out one PinLocator for the life of
the worker, and PinLocator cached the parsed schematic, the parsed S-expression
and the pin definitions by path alone, with no invalidation. After a component
was moved or rotated, ``connect_to_net`` / ``connect_passthrough`` therefore kept
using the pin positions from before the edit and placed the label and wire stub
where the pin used to be: a floating label, reported as success.

Each test rewrites the file and moves its mtime forward explicitly, so the check
does not depend on the file system's timestamp resolution.
"""

import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.pin_locator import PinLocator  # noqa: E402

pytestmark = pytest.mark.unit

TEMPLATE = Path(__file__).resolve().parent.parent / "python" / "templates" / "empty.kicad_sch"


def _resistor(x: float, y: float, rotation: int = 0) -> str:
    return f"""
  (symbol (lib_id "Device:R") (at {x} {y} {rotation}) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "{uuid.uuid4()}")
    (property "Reference" "R1" (at {x} {y} 0) (effects (font (size 1.27 1.27))))
    (property "Value" "10k" (at {x} {y} 0) (effects (font (size 1.27 1.27))))
    (pin "1" (uuid "{uuid.uuid4()}"))
    (pin "2" (uuid "{uuid.uuid4()}"))
    (instances (project "t" (path "/" (reference "R1") (unit 1))))
  )
"""


class _Sheet:
    """A schematic holding one Device:R (pins at library (0, +/-3.81))."""

    def __init__(self, tmp_path: Path) -> None:
        self.path = tmp_path / "sheet.kicad_sch"
        shutil.copy(TEMPLATE, self.path)
        self._base = self.path.read_text(encoding="utf-8")
        self._stamp = 1_700_000_000

    def place(self, x: float, y: float, rotation: int = 0, lib_text=None) -> None:
        base = self._base if lib_text is None else lib_text(self._base)
        cut = base.rfind(")")
        self.path.write_text(base[:cut] + _resistor(x, y, rotation) + ")", encoding="utf-8")
        self._stamp += 10  # a distinct mtime for every write
        os.utime(self.path, (self._stamp, self._stamp))


def test_pin_location_follows_a_moved_component(tmp_path):
    sheet = _Sheet(tmp_path)
    sheet.place(100.0, 100.0)
    locator = PinLocator()  # one long-lived locator, like ConnectionManager's
    assert locator.get_pin_location(sheet.path, "R1", "1") == pytest.approx([100.0, 96.19])

    sheet.place(150.0, 100.0)  # same file size: only the mtime changes
    assert locator.get_pin_location(sheet.path, "R1", "1") == pytest.approx([150.0, 96.19])
    assert locator.get_all_symbol_pins(sheet.path, "R1")["2"] == pytest.approx([150.0, 103.81])


def test_pin_location_follows_a_rotation(tmp_path):
    sheet = _Sheet(tmp_path)
    sheet.place(100.0, 100.0, 0)
    locator = PinLocator()
    assert locator.get_pin_location(sheet.path, "R1", "1") == pytest.approx([100.0, 96.19])

    sheet.place(100.0, 100.0, 90)
    # rot 90: (x - py, y - px) with pin 1 at library (0, 3.81)
    assert locator.get_pin_location(sheet.path, "R1", "1") == pytest.approx([96.19, 100.0])


def test_pin_definitions_follow_a_changed_library_symbol(tmp_path):
    sheet = _Sheet(tmp_path)
    sheet.place(100.0, 100.0)
    locator = PinLocator()
    assert locator.get_symbol_pins(sheet.path, "Device:R")["1"]["y"] == pytest.approx(3.81)

    # e.g. update_symbol_from_library rewrote the embedded lib_symbols entry
    sheet.place(
        100.0,
        100.0,
        lib_text=lambda text: text.replace("(at 0 3.81 270)", "(at 0 5.08 270)", 1),
    )
    assert locator.get_symbol_pins(sheet.path, "Device:R")["1"]["y"] == pytest.approx(5.08)


def test_unchanged_file_is_served_from_cache(tmp_path, monkeypatch):
    import commands.pin_locator as pin_locator_module

    sheet = _Sheet(tmp_path)
    sheet.place(100.0, 100.0)
    locator = PinLocator()
    loads = []
    real_load = pin_locator_module.SchematicManager.load_schematic

    def counting_load(path):
        loads.append(path)
        return real_load(path)

    monkeypatch.setattr(pin_locator_module.SchematicManager, "load_schematic", counting_load)
    for pin in ("1", "2", "1"):
        locator.get_pin_location(sheet.path, "R1", pin)
    assert len(loads) == 1
