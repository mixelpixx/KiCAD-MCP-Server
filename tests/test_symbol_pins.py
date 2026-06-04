"""
Unit tests for the symbol/pin discovery commands (commands/symbol_pins.py).

These avoid any dependency on a system-wide KiCad library install by feeding the
parser a hand-written symbol block and by stubbing DynamicSymbolLoader, so they run
identically in CI and on a developer machine.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands import symbol_pins  # noqa: E402
from commands.symbol_pins import SymbolPinCommands, _body_bbox, _parse_symbol_pins  # noqa: E402

# A minimal symbol definition block with two pins, in KiCad lib S-expression form.
_R_BLOCK = """
(symbol "R"
  (symbol "R_1_1"
    (pin passive line (at 0 3.81 270) (length 1.27)
      (name "~" (effects (font (size 1.27 1.27))))
      (number "1" (effects (font (size 1.27 1.27)))))
    (pin passive line (at 0 -3.81 90) (length 1.27)
      (name "~" (effects (font (size 1.27 1.27))))
      (number "2" (effects (font (size 1.27 1.27)))))
  )
)
"""

# Three-pin block with named pins to verify name/type/ordering.
_U_BLOCK = """
(symbol "LDO"
  (symbol "LDO_1_1"
    (pin power_in line (at -5.08 0 0) (name "VIN" (effects (font (size 1 1)))) (number "1"))
    (pin power_out line (at 5.08 0 180) (name "VOUT" (effects (font (size 1 1)))) (number "3"))
    (pin power_in line (at 0 -5.08 90) (name "GND" (effects (font (size 1 1)))) (number "2"))
  )
)
"""


def _fake_loader(block):
    loader = MagicMock()
    loader.extract_symbol_from_library.return_value = block
    return loader


class TestParseSymbolPins:
    def test_basic_two_pin(self):
        pins = _parse_symbol_pins(_fake_loader(_R_BLOCK), "Device", "R")
        assert [p["number"] for p in pins] == ["1", "2"]
        assert pins[0] == {
            "number": "1",
            "name": "~",
            "type": "passive",
            "x": 0.0,
            "y": 3.81,
            "angle": 270.0,
        }

    def test_named_pins_and_sort(self):
        pins = _parse_symbol_pins(_fake_loader(_U_BLOCK), "Reg", "LDO")
        # Sorted by (len(number), number): "1","2","3"
        assert [p["number"] for p in pins] == ["1", "2", "3"]
        by_num = {p["number"]: p for p in pins}
        assert by_num["1"]["name"] == "VIN" and by_num["1"]["type"] == "power_in"
        assert by_num["3"]["name"] == "VOUT" and by_num["3"]["type"] == "power_out"

    def test_not_found_raises(self):
        with pytest.raises(ValueError):
            _parse_symbol_pins(_fake_loader(None), "Device", "Nope")


class TestBodyBbox:
    def test_bbox_math(self):
        pins = [{"x": 0.0, "y": 3.81}, {"x": 0.0, "y": -3.81}]
        bb = _body_bbox(pins)
        assert bb["width"] == pytest.approx(2.54)
        assert bb["height"] == pytest.approx(10.16)
        assert bb["y_max"] == pytest.approx(5.08)

    def test_bbox_empty(self):
        assert _body_bbox([]) is None


class TestListSymbolPins:
    def test_bad_spec(self):
        c = SymbolPinCommands()
        r = c.list_symbol_pins({"symbol": "NoColon"})
        assert r["success"] is False

    def test_happy_path(self, monkeypatch):
        monkeypatch.setattr(symbol_pins, "DynamicSymbolLoader", lambda **kw: _fake_loader(_R_BLOCK))
        c = SymbolPinCommands()
        r = c.list_symbol_pins({"symbol": "Device:R"})
        assert r["success"] is True
        assert r["pin_count"] == 2
        assert r["symbol"] == "Device:R"

    def test_not_found_returns_suggestions(self, monkeypatch):
        monkeypatch.setattr(symbol_pins, "DynamicSymbolLoader", lambda **kw: _fake_loader(None))
        c = SymbolPinCommands()
        r = c.list_symbol_pins({"symbol": "Device:Nope"})
        assert r["success"] is False
        assert "suggestions" in r


class TestBatchListSymbolPins:
    def test_requires_symbols(self):
        c = SymbolPinCommands()
        assert c.batch_list_symbol_pins({"symbols": []})["success"] is False

    def test_compact_symmetric_passive(self, monkeypatch):
        monkeypatch.setattr(symbol_pins, "DynamicSymbolLoader", lambda **kw: _fake_loader(_R_BLOCK))
        c = SymbolPinCommands()
        r = c.batch_list_symbol_pins({"symbols": ["Device:R"], "compact": True})
        assert r["success"] is True
        entry = r["symbols"]["Device:R"]
        assert entry["compact"] is True and entry["is_symmetric"] is True
        assert "pins" not in entry  # detail omitted in compact mode
        assert entry["body_bbox"]["width"] == pytest.approx(2.54)

    def test_full_detail_when_not_compact(self, monkeypatch):
        monkeypatch.setattr(symbol_pins, "DynamicSymbolLoader", lambda **kw: _fake_loader(_R_BLOCK))
        c = SymbolPinCommands()
        r = c.batch_list_symbol_pins({"symbols": ["Device:R"], "compact": False})
        assert r["symbols"]["Device:R"]["pins"]

    def test_bad_spec_collected_as_error(self):
        c = SymbolPinCommands()
        r = c.batch_list_symbol_pins({"symbols": ["NoColon"]})
        assert r["success"] is False
        assert "NoColon" in r["errors"]
