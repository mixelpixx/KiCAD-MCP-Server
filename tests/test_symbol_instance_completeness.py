"""Tests that placed symbol instances are *structurally complete* — i.e. they match
KiCad-authored output closely enough that the editor does not crash when the symbol is
dragged.

Regression target: ``DynamicSymbolLoader.create_component_instance`` used to emit an
instance block with placeholder values:

    (instances (project "project" (path "/" ...)))   # literal "project", root "/"

and omitted ``body_style``/``exclude_from_sim``/``in_pos_files``, per-pin
``(pin "N" (uuid ...))`` entries and the v10 ``(show_name no)``/``(do_not_autoplace no)``
property attributes. KiCad rendered such a symbol but crashed on drag.

Both ``add_schematic_component`` and ``batch_add_components`` route through
``create_component_instance``, so these tests exercise the single shared writer.

Ground truth was captured from KiCad 10.0.4 (schematic format version 20260306,
generator "eeschema") by upgrading a bundled demo with ``kicad-cli sch upgrade``.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from kicad_mcp.commands.dynamic_symbol_loader import DynamicSymbolLoader  # noqa: E402

TEMPLATES_DIR = Path(__file__).parent.parent / "src" / "kicad_mcp" / "templates"
EMPTY_SCH = TEMPLATES_DIR / "empty.kicad_sch"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _project(tmp_path: Path, project_stem: str = "myproj") -> Path:
    """Create a flat project (one .kicad_sch + matching .kicad_pro) and return the sch."""
    sch = tmp_path / f"{project_stem}.kicad_sch"
    shutil.copy(EMPTY_SCH, sch)
    (tmp_path / f"{project_stem}.kicad_pro").write_text('{"meta":{"version":1}}', encoding="utf-8")
    return sch


def _root_uuid(sch: Path) -> str:
    m = re.search(r'\(uuid\s+"?([0-9a-fA-F-]+)"?\)', sch.read_text(encoding="utf-8"))
    assert m, "schematic has no top-level uuid"
    return m.group(1)


def _placed_block(sch: Path, lib_id: str = "Device:R") -> str:
    """Return the first placed (symbol ... (lib_id "<lib_id>") ... (instances ...)) block.

    Works for both the compact form the generator writes and the multi-line form KiCad
    rewrites to on save.
    """
    s = sch.read_text(encoding="utf-8")
    for m in re.finditer(r"\(symbol\b", s):
        start = m.start()
        depth = 0
        i = start
        while i < len(s):
            if s[i] == "(":
                depth += 1
            elif s[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        block = s[start : i + 1]
        if f'(lib_id "{lib_id}")' in block and "(instances" in block:
            return block
    raise AssertionError(f"placed symbol {lib_id} not found")


# A synthetic two-unit symbol: unit-0 sub-symbol holds shared power pins (8, 4);
# unit 1 holds pins 3/2/1; unit 2 holds pins 5/6/7. Used to pin down per-unit pin
# selection without depending on installed symbol libraries.
_DUAL_SCH = """(kicad_sch (version 20250114) (generator "x")
  (uuid "11110000-0000-0000-0000-000000000000")
  (paper "A4")
  (lib_symbols
    (symbol "Test:DUAL" (pin_numbers hide) (pin_names (offset 0)) (in_bom yes) (on_board yes)
      (property "Reference" "U" (at 0 0 0) (effects (font (size 1.27 1.27))))
      (property "Value" "DUAL" (at 0 0 0) (effects (font (size 1.27 1.27))))
      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))
      (property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))
      (symbol "DUAL_0_1"
        (pin power_in line (at 0 10 0) (length 2) (name "V+") (number "8"))
        (pin power_in line (at 0 -10 0) (length 2) (name "V-") (number "4")))
      (symbol "DUAL_1_1"
        (pin input line (at -5 5 0) (length 2) (name "+") (number "3"))
        (pin input line (at -5 -5 0) (length 2) (name "-") (number "2"))
        (pin output line (at 5 0 0) (length 2) (name "O") (number "1")))
      (symbol "DUAL_2_1"
        (pin input line (at -5 5 0) (length 2) (name "+") (number "5"))
        (pin input line (at -5 -5 0) (length 2) (name "-") (number "6"))
        (pin output line (at 5 0 0) (length 2) (name "O") (number "7")))
    )
  )
  (sheet_instances (path "/" (page "1")))
)
"""


# --------------------------------------------------------------------------- #
# Header / property field set (KiCad 10 format)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
class TestHeaderFieldSet:
    def test_header_has_v10_fields_in_order(self, tmp_path: Any) -> None:
        sch = _project(tmp_path)
        DynamicSymbolLoader().create_component_instance(
            sch, "Device", "R", reference="R1", value="10k", x=100, y=100
        )
        block = _placed_block(sch)
        order = [
            "(lib_id ",
            "(at ",
            "(unit ",
            "(body_style 1)",
            "(exclude_from_sim no)",
            "(in_bom yes)",
            "(on_board yes)",
            "(in_pos_files yes)",
            "(dnp no)",
            "(uuid ",
        ]
        positions = [block.find(tok) for tok in order]
        assert all(p != -1 for p in positions), dict(zip(order, positions))
        assert positions == sorted(positions), f"header fields out of order: {positions}"

    def test_properties_have_v10_attributes(self, tmp_path: Any) -> None:
        sch = _project(tmp_path)
        DynamicSymbolLoader().create_component_instance(
            sch, "Device", "R", reference="R1", value="10k", x=100, y=100
        )
        block = _placed_block(sch)
        for prop in ("Reference", "Value", "Footprint", "Datasheet"):
            assert f'(property "{prop}"' in block
        # Each visible/hidden property carries the v10 attributes.
        assert block.count("(show_name no)") >= 4
        assert block.count("(do_not_autoplace no)") >= 4
        # Hidden fields use a top-level (hide yes), not (hide yes) inside (effects ...).
        assert "(hide yes)" in block
        assert not re.search(r"\(effects[^)]*hide", block)


# --------------------------------------------------------------------------- #
# Real project name + real instance path (no placeholders)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
class TestProjectAndPath:
    def test_no_placeholder_project_or_root_path(self, tmp_path: Any) -> None:
        sch = _project(tmp_path, "myproj")
        DynamicSymbolLoader().create_component_instance(
            sch, "Device", "R", reference="R1", value="10k", x=100, y=100
        )
        block = _placed_block(sch)
        assert '(project "project"' not in block
        assert '(project "myproj"' in block
        # The symbol instance path must be the real root sheet UUID, not "/".
        assert '(path "/"' not in block

    def test_flat_path_is_root_uuid(self, tmp_path: Any) -> None:
        sch = _project(tmp_path, "myproj")
        DynamicSymbolLoader().create_component_instance(
            sch, "Device", "R", reference="R1", value="10k", x=100, y=100
        )
        block = _placed_block(sch)
        assert f'(path "/{_root_uuid(sch)}"' in block

    def test_project_name_falls_back_to_schematic_stem(self, tmp_path: Any) -> None:
        # No .kicad_pro present -> use the schematic's own stem.
        sch = tmp_path / "loneboard.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        assert DynamicSymbolLoader()._resolve_project_name(sch) == "loneboard"


# --------------------------------------------------------------------------- #
# Per-pin uuids + multi-unit pin selection
# --------------------------------------------------------------------------- #


@pytest.mark.unit
class TestPerPinUuids:
    def test_pins_emitted_with_uuids(self, tmp_path: Any) -> None:
        sch = _project(tmp_path)
        DynamicSymbolLoader().create_component_instance(
            sch, "Device", "R", reference="R1", value="10k", x=100, y=100
        )
        block = _placed_block(sch)
        # Device:R has two pins; both must be emitted with a uuid.
        assert re.search(r'\(pin "1" \(uuid "[0-9a-fA-F-]{36}"\)\)', block)
        assert re.search(r'\(pin "2" \(uuid "[0-9a-fA-F-]{36}"\)\)', block)

    def test_unit_pin_selection(self, tmp_path: Any) -> None:
        sch = tmp_path / "dual.kicad_sch"
        sch.write_text(_DUAL_SCH, encoding="utf-8")
        loader = DynamicSymbolLoader()
        # Unit 1 -> its own pins (1,2,3) + shared unit-0 pins (4,8); string-sorted.
        assert loader._extract_symbol_pins(sch, "Test", "DUAL", 1) == ["1", "2", "3", "4", "8"]
        # Unit 2 -> (5,6,7) + shared (4,8).
        assert loader._extract_symbol_pins(sch, "Test", "DUAL", 2) == ["4", "5", "6", "7", "8"]

    def test_pins_string_sorted(self, tmp_path: Any) -> None:
        sch = tmp_path / "dual.kicad_sch"
        sch.write_text(_DUAL_SCH, encoding="utf-8")
        pins = DynamicSymbolLoader()._extract_symbol_pins(sch, "Test", "DUAL", 1)
        assert pins == sorted(pins)


# --------------------------------------------------------------------------- #
# Hierarchical instance path reconstruction
# --------------------------------------------------------------------------- #


@pytest.mark.unit
class TestHierarchicalPath:
    def _build(self, tmp_path: Path) -> tuple:
        root = tmp_path / "design.kicad_sch"
        child = tmp_path / "child.kicad_sch"
        (tmp_path / "design.kicad_pro").write_text('{"meta":{"version":1}}', encoding="utf-8")
        root.write_text(
            '(kicad_sch (version 20250114) (generator "x")\n'
            '  (uuid "aaaa0000-0000-0000-0000-000000000001")\n  (paper "A4")\n'
            "  (lib_symbols)\n"
            "  (sheet (at 50 50) (size 30 20)\n"
            '    (uuid "bbbb0000-0000-0000-0000-000000000002")\n'
            '    (property "Sheet name" "Child" (at 50 48 0) (effects (font (size 1.27 1.27))))\n'
            '    (property "Sheet file" "child.kicad_sch" (at 50 72 0)'
            " (effects (font (size 1.27 1.27))))\n"
            "  )\n"
            '  (sheet_instances (path "/" (page "1")))\n)\n',
            encoding="utf-8",
        )
        child.write_text(
            '(kicad_sch (version 20250114) (generator "x")\n'
            '  (uuid "cccc0000-0000-0000-0000-000000000003")\n  (paper "A4")\n'
            "  (lib_symbols)\n)\n",
            encoding="utf-8",
        )
        return root, child

    def test_root_path_is_root_uuid(self, tmp_path: Any) -> None:
        root, _ = self._build(tmp_path)
        assert (
            DynamicSymbolLoader()._build_instance_path(root)
            == "/aaaa0000-0000-0000-0000-000000000001"
        )

    def test_child_path_is_root_then_sheet_block(self, tmp_path: Any) -> None:
        _, child = self._build(tmp_path)
        assert DynamicSymbolLoader()._build_instance_path(child) == (
            "/aaaa0000-0000-0000-0000-000000000001/bbbb0000-0000-0000-0000-000000000002"
        )


# --------------------------------------------------------------------------- #
# End-to-end structural round-trip via kicad-cli (skipped if unavailable)
# --------------------------------------------------------------------------- #


def _kicad_cli() -> str:
    cli = shutil.which("kicad-cli")
    if cli:
        return cli
    for cand in (
        r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe",
        r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
    ):
        if Path(cand).exists():
            return cand
    return ""


@pytest.mark.integration
class TestKicadCliRoundTrip:
    """A placed symbol must survive a KiCad save (``kicad-cli sch upgrade``) with its
    structural fields unchanged. If KiCad rewrites the instance, the generator did not
    match KiCad-authored output."""

    def setup_method(self) -> None:
        self.cli = _kicad_cli()
        if not self.cli:
            pytest.skip("kicad-cli not available")
        try:
            import sexpdata  # noqa: F401
        except ImportError:
            pytest.skip("sexpdata not available")

    def _canon(self, node: Any) -> Any:
        import sexpdata
        from sexpdata import Symbol

        if isinstance(node, list):
            if node and node[0] == Symbol("uuid"):
                return [Symbol("uuid"), "U"]
            return [self._canon(x) for x in node]
        return node

    def test_erc_parses_and_roundtrips(self, tmp_path: Any) -> None:
        import sexpdata

        sch = _project(tmp_path, "rt")
        DynamicSymbolLoader().create_component_instance(
            sch,
            "Device",
            "R",
            reference="R1",
            value="10k",
            footprint="Resistor_SMD:R_0402_1005Metric",
            x=100,
            y=100,
        )
        before = _placed_block(sch)

        # 1) ERC must load/parse the file (non-zero exit just means violations exist).
        erc = subprocess.run(
            [self.cli, "sch", "erc", str(sch)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert "Failed to load" not in (erc.stdout + erc.stderr)

        # 2) Round-trip: KiCad rewrites to canonical form; structural tree must be equal.
        up = subprocess.run(
            [self.cli, "sch", "upgrade", str(sch)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert up.returncode == 0, up.stdout + up.stderr
        after = _placed_block(sch)

        assert self._canon(sexpdata.loads(before)) == self._canon(sexpdata.loads(after))
