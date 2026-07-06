"""Tests for add_symbol_property — add custom properties to .kicad_sym library files."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
from commands.add_symbol_property import add_symbol_property, _has_property, _find_symbol_in_lib

LIB = """(kicad_symbol_lib (version 20231120) (generator "test")
  (symbol "R" (pin_names hide) (in_bom yes) (on_board yes)
    (property "Reference" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "Value" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (symbol "R_0_1" (pin "1" passive (at 0 2.54 0)))
    (symbol "R_1_1" (pin "2" passive (at 0 -2.54 0))))
  (symbol "C" (pin_names hide) (in_bom yes) (on_board yes)
    (property "Reference" "C" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "Value" "C" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "Manufacturer" "TDK" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))
    (symbol "C_0_1" (pin "1" passive (at 0 2.54 0)))
    (symbol "C_1_1" (pin "2" passive (at 0 -2.54 0))))
)
"""

@pytest.fixture
def tmp_lib(tmp_path):
    p = tmp_path / "test.kicad_sym"
    p.write_text(LIB, encoding="utf-8")
    return str(p)

def test_add_new_property(tmp_lib):
    r = add_symbol_property({"libraryPath": tmp_lib, "symbolName": "R", "propertyName": "Manufacturer", "propertyValue": "YAGEO", "hide": True})
    assert r["success"]
    assert "added" in r["message"].lower()
    assert "YAGEO" in Path(tmp_lib).read_text(encoding="utf-8")

def test_replace_existing(tmp_lib):
    r = add_symbol_property({"libraryPath": tmp_lib, "symbolName": "C", "propertyName": "Manufacturer", "propertyValue": "Murata"})
    assert r["success"]
    assert "updated" in r["message"].lower()
    c = Path(tmp_lib).read_text(encoding="utf-8")
    assert "Murata" in c
    assert "TDK" not in c

def test_symbol_not_found(tmp_lib):
    r = add_symbol_property({"libraryPath": tmp_lib, "symbolName": "L", "propertyName": "Manufacturer", "propertyValue": "test"})
    assert not r["success"]

def test_library_not_found():
    r = add_symbol_property({"libraryPath": "/no/such/file", "symbolName": "R", "propertyName": "M", "propertyValue": "x"})
    assert not r["success"]

def test_sub_symbol_not_matched(tmp_lib):
    c = Path(tmp_lib).read_text(encoding="utf-8")
    m = _find_symbol_in_lib(c, "C")
    assert m is not None
    b = c[m[0]:m[1]]
    assert "Reference" in b
    assert "symbol \"C_0_1\"" in b
    assert m[0] < c.find('symbol "C_0_1"')

def test_has_property_true(tmp_lib):
    c = Path(tmp_lib).read_text(encoding="utf-8")
    m = _find_symbol_in_lib(c, "C")
    assert _has_property(c[m[0]:m[1]], "Manufacturer")

def test_has_property_false(tmp_lib):
    c = Path(tmp_lib).read_text(encoding="utf-8")
    m = _find_symbol_in_lib(c, "R")
    assert not _has_property(c[m[0]:m[1]], "Manufacturer")

def test_has_property_partial(tmp_lib):
    c = Path(tmp_lib).read_text(encoding="utf-8")
    m = _find_symbol_in_lib(c, "C")
    assert not _has_property(c[m[0]:m[1]], "Man")

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
