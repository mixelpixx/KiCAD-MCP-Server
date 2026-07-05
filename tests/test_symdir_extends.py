"""Regression tests for issue #282:

    symdir libraries: (extends) parent in a sibling shard is not resolved

In KiCad 10's sharded ``.kicad_symdir`` format each symbol is its own
``<Symbol>.kicad_sym`` file. A derived symbol that uses ``(extends "Parent")``
therefore has its parent in a *sibling* shard, not in its own file.
``extract_symbol_from_library`` used to hand the child's shard alone to the
inliner, so the parent was never found and the ``(extends)`` clause was stripped,
yielding an incomplete symbol (no parent pins/graphics).

These tests build a fake ``.kicad_symdir`` directory of shards and assert the
parent is now resolved across shards — including a multi-level chain — and that a
genuinely missing parent still degrades gracefully.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.dynamic_symbol_loader import DynamicSymbolLoader


def _parent_shard(name: str) -> str:
    """A complete base symbol with two pins in its unit sub-symbol."""
    return (
        f"(kicad_symbol_lib (version 20241209) (generator test)\n"
        f'  (symbol "{name}" (pin_numbers (hide yes)) (pin_names (offset 0.254))'
        f" (exclude_from_sim no) (in_bom yes) (on_board yes)\n"
        f'    (property "Reference" "C" (at 0 0 0))\n'
        f'    (property "Value" "{name}" (at 0 0 0))\n'
        f'    (property "Datasheet" "~" (at 0 0 0))\n'
        f'    (symbol "{name}_0_1"\n'
        f"      (polyline (pts (xy -2 0) (xy 2 0)) (stroke (width 0)) (fill (type none)))\n"
        f"    )\n"
        f'    (symbol "{name}_1_1"\n'
        f"      (pin passive line (at 0 3.81 270) (length 2.54)"
        f' (name "~" (effects (font (size 1.27 1.27))))'
        f' (number "1" (effects (font (size 1.27 1.27)))))\n'
        f"      (pin passive line (at 0 -3.81 90) (length 2.54)"
        f' (name "~" (effects (font (size 1.27 1.27))))'
        f' (number "2" (effects (font (size 1.27 1.27)))))\n'
        f"    )\n"
        f"  )\n"
        f")\n"
    )


def _derived_shard(name: str, parent: str, extra_property: str = "") -> str:
    """A derived symbol that extends ``parent`` and overrides its Value."""
    return (
        f"(kicad_symbol_lib (version 20241209) (generator test)\n"
        f'  (symbol "{name}" (extends "{parent}")\n'
        f'    (property "Value" "{name}" (at 0 0 0))\n'
        f"{extra_property}"
        f"  )\n"
        f")\n"
    )


def _make_symdir(tmp_path: Path, lib: str, shards: dict) -> DynamicSymbolLoader:
    """Create ``<lib>.kicad_symdir`` with the given ``{symbol: content}`` shards and
    return a loader whose bundled-library search points at the containing dir."""
    symdir = tmp_path / f"{lib}.kicad_symdir"
    symdir.mkdir()
    for sym, content in shards.items():
        (symdir / f"{sym}.kicad_sym").write_text(content, encoding="utf-8")

    loader = DynamicSymbolLoader()
    loader.find_kicad_symbol_libraries = lambda: [tmp_path]  # type: ignore[method-assign]
    return loader


def test_derived_symbol_inlines_parent_from_sibling_shard(tmp_path):
    loader = _make_symdir(
        tmp_path,
        "TestLib",
        {
            "C_Feedthrough": _parent_shard("C_Feedthrough"),
            "Filter_EMI_C": _derived_shard("Filter_EMI_C", "C_Feedthrough"),
        },
    )

    block = loader.extract_symbol_from_library("TestLib", "Filter_EMI_C")

    assert block is not None
    # Parent content is inlined: both pins are present...
    assert '(number "1"' in block
    assert '(number "2"' in block
    # ...the parent's unit sub-symbol was renamed to the child...
    assert '(symbol "Filter_EMI_C_1_1"' in block
    assert "C_Feedthrough_1_1" not in block
    # ...no (extends) survives (KiCad refuses it inside a schematic)...
    assert "(extends" not in block
    # ...the top-level symbol is library-qualified, and the child's Value wins.
    assert '(symbol "TestLib:Filter_EMI_C"' in block
    assert '(property "Value" "Filter_EMI_C"' in block


def test_multi_level_extends_chain_resolves(tmp_path):
    loader = _make_symdir(
        tmp_path,
        "TestLib",
        {
            "Base": _parent_shard("Base"),
            "Mid": _derived_shard("Mid", "Base"),
            "Top": _derived_shard("Top", "Mid"),
        },
    )

    block = loader.extract_symbol_from_library("TestLib", "Top")

    assert block is not None
    # Grandparent pins reach the grandchild, renamed all the way down.
    assert '(number "1"' in block
    assert '(number "2"' in block
    assert '(symbol "Top_1_1"' in block
    assert "(extends" not in block
    assert '(symbol "TestLib:Top"' in block


def test_missing_parent_shard_degrades_gracefully(tmp_path):
    loader = _make_symdir(
        tmp_path,
        "TestLib",
        {"Orphan": _derived_shard("Orphan", "Ghost")},  # no Ghost.kicad_sym
    )

    block = loader.extract_symbol_from_library("TestLib", "Orphan")

    # No crash; the unresolved (extends) is stripped so the file stays loadable.
    assert block is not None
    assert "(extends" not in block
    assert '(symbol "TestLib:Orphan"' in block
