"""
Tests for schematic-writer output compatibility.

Three regressions, all of which made KiCad reject the whole schematic with a
bare "Failed to load schematic" that names neither a token nor a line:

1. ``(body_style ...)`` / ``(in_pos_files ...)`` were written into every placed
   symbol. Both are KiCad 10 additions, so any KiCad 8 (20231120) or KiCad 9
   (20250114) file became unloadable -- including this repo's own
   ``minimal``/``empty``/``template_with_symbols`` templates, which declare
   20250114.
2. Property values were interpolated into the s-expression unescaped. Several
   stock library descriptions embed double quotes (``power:GND`` is
   ``Power symbol creates a global label with name "GND" , ground``), so the
   first inner quote closed the token early and corrupted the block. Note the
   file's parentheses still balance afterwards and sexpdata still parses it,
   which is what made this silent.
3. ``add_schematic_component`` dropped the documented ``angle`` and ``mirrorY``
   arguments: the TS layer nests them inside ``component``, and the Python
   handler never read them back out.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

TEMPLATES_DIR = Path(__file__).parent.parent / "python" / "templates"

_KICAD_CLI = shutil.which("kicad-cli")

# Format version tokens, by the KiCad release that introduced them.
V8 = 20231120
V9 = 20250114
V10 = 20260101


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sch_with_version(tmp_path: Path, version: int, name: str = "s.kicad_sch") -> Path:
    """A minimal but structurally complete schematic declaring ``version``."""
    dest = tmp_path / name
    dest.write_text(
        f'(kicad_sch (version {version}) (generator "eeschema")'
        ' (generator_version "9.0")\n\n'
        "  (uuid 4f7d1c66-1f9e-4a2b-9d3c-0f1a2b3c4d5e)\n\n"
        '  (paper "A4")\n\n'
        "  (lib_symbols\n  )\n\n"
        '  (sheet_instances\n    (path "/" (page "1"))\n  )\n'
        ")\n",
        encoding="utf-8",
    )
    return dest


def _sch_without_version(tmp_path: Path) -> Path:
    """A schematic with no ``(version ...)`` token at all."""
    dest = tmp_path / "noversion.kicad_sch"
    dest.write_text(
        '(kicad_sch (generator "eeschema")\n'
        "  (uuid 4f7d1c66-1f9e-4a2b-9d3c-0f1a2b3c4d5e)\n"
        '  (paper "A4")\n'
        "  (lib_symbols\n  )\n"
        '  (sheet_instances\n    (path "/" (page "1"))\n  )\n'
        ")\n",
        encoding="utf-8",
    )
    return dest


def _place(sch: Path, library: str, symbol: str, reference: str, **kwargs: Any) -> bool:
    from commands.dynamic_symbol_loader import DynamicSymbolLoader

    loader = DynamicSymbolLoader()
    loader.inject_symbol_into_schematic(sch, library, symbol)
    return loader.create_component_instance(sch, library, symbol, reference=reference, **kwargs)


def _placed_symbol_header(content: str, lib_id: str) -> str:
    """The ``(symbol (lib_id ...) ...)`` opening line plus its attribute line."""
    m = re.search(
        r"\(symbol \(lib_id \"" + re.escape(lib_id) + r"\"\)[^\n]*\n[^\n]*",
        content,
    )
    assert m is not None, f"no placed symbol for {lib_id} in:\n{content[:2000]}"
    return m.group(0)


# ---------------------------------------------------------------------------
# 1. Version-gated KiCad 10 symbol attributes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKicad10TokensAreVersionGated:
    """body_style / in_pos_files must only reach files that accept them."""

    @pytest.mark.parametrize("version", [V8, V9])
    def test_legacy_versions_omit_kicad10_tokens(self, tmp_path: Path, version: int) -> None:
        sch = _sch_with_version(tmp_path, version)
        assert _place(sch, "Device", "R", "R1", value="10k", x=100, y=100)

        header = _placed_symbol_header(sch.read_text(), "Device:R")
        assert "body_style" not in header, f"v{version} file got a KiCad 10 token: {header}"
        assert "in_pos_files" not in header, f"v{version} file got a KiCad 10 token: {header}"

        # The attributes that ARE common to v8/v9/v10 must still be present.
        for token in ("(exclude_from_sim no)", "(in_bom yes)", "(on_board yes)", "(dnp no)"):
            assert token in header, f"{token} missing from {header}"

    def test_kicad10_version_keeps_kicad10_tokens(self, tmp_path: Path) -> None:
        sch = _sch_with_version(tmp_path, V10)
        assert _place(sch, "Device", "R", "R1", value="10k", x=100, y=100)

        header = _placed_symbol_header(sch.read_text(), "Device:R")
        assert "(body_style 1)" in header
        assert "(in_pos_files yes)" in header

    def test_missing_version_is_treated_as_kicad10(self, tmp_path: Path) -> None:
        """Absent version keeps the pre-fix behaviour rather than silently downgrading."""
        sch = _sch_without_version(tmp_path)
        assert _place(sch, "Device", "R", "R1", value="10k", x=100, y=100)

        header = _placed_symbol_header(sch.read_text(), "Device:R")
        assert "(body_style 1)" in header
        assert "(in_pos_files yes)" in header

    @pytest.mark.parametrize(
        "version,expected",
        [(V8, False), (V9, False), (V10, True), (V10 + 1, True)],
    )
    def test_support_predicate(self, version: int, expected: bool) -> None:
        from commands.dynamic_symbol_loader import DynamicSymbolLoader

        content = f'(kicad_sch (version {version}) (generator "eeschema"))'
        assert DynamicSymbolLoader._supports_kicad10_symbol_tokens(content) is expected

    def test_read_sch_version(self) -> None:
        from commands.dynamic_symbol_loader import DynamicSymbolLoader

        assert DynamicSymbolLoader._read_sch_version("(kicad_sch (version 20250114)") == V9
        assert DynamicSymbolLoader._read_sch_version("(kicad_sch (generator x)") is None


@pytest.mark.unit
class TestShippedTemplatesStayLoadable:
    """The repo's own templates declare a mix of v9 and v10 -- both must work."""

    @pytest.mark.parametrize("template", ["minimal", "empty", "template_with_symbols", "blank"])
    def test_template_gets_tokens_matching_its_own_version(
        self, tmp_path: Path, template: str
    ) -> None:
        src = TEMPLATES_DIR / f"{template}.kicad_sch"
        if not src.exists():
            pytest.skip(f"template {template} not present")
        sch = tmp_path / f"{template}.kicad_sch"
        sch.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

        declared = re.search(r"\(version\s+(\d+)\)", sch.read_text())
        assert declared is not None, f"{template} has no version token"
        version = int(declared.group(1))

        assert _place(sch, "Device", "R", "R1", value="10k", x=100, y=100)
        header = _placed_symbol_header(sch.read_text(), "Device:R")

        if version >= V10:
            assert "(body_style 1)" in header
        else:
            assert (
                "body_style" not in header
            ), f"{template} declares {version} but was given a KiCad 10 token"


# ---------------------------------------------------------------------------
# 2. Property-value escaping
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPropertyValuesAreEscaped:
    """A quote inside a property value must not terminate the token."""

    def test_library_description_with_quotes_is_escaped(self, tmp_path: Path) -> None:
        """power:GND's stock Description embeds "GND" -- the original trigger."""
        from utils.sexpr_format import QUOTED_VALUE, unescape_sexpr_string

        sch = _sch_with_version(tmp_path, V9)
        assert _place(sch, "power", "GND", "#PWR01", value="GND", x=50, y=50)

        content = sch.read_text()
        # Look at the *placed instance* property, not the lib_symbols one.
        instance = content[content.index('(symbol (lib_id "power:GND")') :]
        m = re.search(r'\(property "Description" ' + QUOTED_VALUE, instance)
        assert m is not None, "no Description property on the placed symbol"

        raw = m.group(1)
        assert '\\"GND\\"' in raw, f"quotes not escaped: {raw!r}"
        # And it must survive a round trip back to the original text.
        assert unescape_sexpr_string(raw) == (
            'Power symbol creates a global label with name "GND" , ground'
        )

    def test_user_supplied_value_with_quotes_is_escaped(self, tmp_path: Path) -> None:
        from utils.sexpr_format import QUOTED_VALUE, unescape_sexpr_string

        sch = _sch_with_version(tmp_path, V9)
        assert _place(sch, "Device", "R", "R1", value='1/4" 10k', x=100, y=100)

        instance = sch.read_text()
        instance = instance[instance.index('(symbol (lib_id "Device:R")') :]
        m = re.search(r'\(property "Value" ' + QUOTED_VALUE, instance)
        assert m is not None
        assert unescape_sexpr_string(m.group(1)) == '1/4" 10k'

    def test_backslash_in_value_survives(self, tmp_path: Path) -> None:
        """Backslash must be escaped before the quote, or the pair cancels out."""
        from utils.sexpr_format import QUOTED_VALUE, unescape_sexpr_string

        sch = _sch_with_version(tmp_path, V9)
        assert _place(sch, "Device", "R", "R1", value="a\\b", x=100, y=100)

        instance = sch.read_text()
        instance = instance[instance.index('(symbol (lib_id "Device:R")') :]
        m = re.search(r'\(property "Value" ' + QUOTED_VALUE, instance)
        assert m is not None
        assert unescape_sexpr_string(m.group(1)) == "a\\b"

    def test_every_property_value_token_ends_where_it_should(self, tmp_path: Path) -> None:
        """Each property's value token must be followed by its ``(at ...)`` child.

        This is the structural tell for a value that terminated early: the text
        after the closing quote is then the *remainder of the description* rather
        than the next s-expression. Counting parens does not catch it (they stay
        balanced) and neither does counting quotes (a description with two inner
        quotes keeps the total even), so assert on what actually breaks.
        """
        sch = _sch_with_version(tmp_path, V9)
        assert _place(sch, "power", "GND", "#PWR01", value="GND", x=50, y=50)

        content = sch.read_text()
        instance = content[content.index('(symbol (lib_id "power:GND")') :]

        properties = list(
            re.finditer(r'\(property "(?:[^"\\]|\\.)*" ((?:"(?:[^"\\]|\\.)*"))', instance)
        )
        assert len(properties) == 5, f"expected 5 properties, found {len(properties)}"
        for m in properties:
            tail = instance[m.end() : m.end() + 40].lstrip()
            assert tail.startswith(
                "(at "
            ), f"property value token ran on -- followed by {tail[:30]!r} instead of '(at '"


# ---------------------------------------------------------------------------
# 3. angle / mirrorY plumbed through the handler
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddComponentHonoursOrientation:
    """The handler must forward the nested angle/mirrorY to the loader."""

    def _handler(self) -> Any:
        from commands.schematic_handlers import SchematicHandlersMixin

        class _H(SchematicHandlersMixin):
            def _reload_kicad_schematic(self, *a: Any, **k: Any) -> None:
                return None

        return _H()

    def _add(self, sch: Path, **component: Any) -> Any:
        params = {
            "schematicPath": str(sch),
            "component": {
                "library": "Device",
                "type": "R",
                "reference": "R1",
                "value": "10k",
                "x": 100,
                "y": 100,
                "unit": 1,
                **component,
            },
        }
        return self._handler()._handle_add_schematic_component(params)

    def test_angle_is_written(self, tmp_path: Path) -> None:
        sch = _sch_with_version(tmp_path, V9)
        result = self._add(sch, angle=90)
        assert result["success"] is True, result

        header = _placed_symbol_header(sch.read_text(), "Device:R")
        assert re.search(r"\(at [\d.]+ [\d.]+ 90\)", header), header

    def test_angle_defaults_to_zero(self, tmp_path: Path) -> None:
        sch = _sch_with_version(tmp_path, V9)
        assert self._add(sch)["success"] is True

        header = _placed_symbol_header(sch.read_text(), "Device:R")
        assert re.search(r"\(at [\d.]+ [\d.]+ 0\)", header), header

    def test_mirror_y_is_written(self, tmp_path: Path) -> None:
        sch = _sch_with_version(tmp_path, V9)
        assert self._add(sch, mirrorY=True)["success"] is True

        header = _placed_symbol_header(sch.read_text(), "Device:R")
        assert "(mirror y)" in header, header

    def test_no_mirror_token_when_not_requested(self, tmp_path: Path) -> None:
        sch = _sch_with_version(tmp_path, V9)
        assert self._add(sch, mirrorY=False)["success"] is True

        header = _placed_symbol_header(sch.read_text(), "Device:R")
        assert "(mirror" not in header, header

    def test_angle_and_mirror_together(self, tmp_path: Path) -> None:
        sch = _sch_with_version(tmp_path, V9)
        assert self._add(sch, angle=270, mirrorY=True)["success"] is True

        header = _placed_symbol_header(sch.read_text(), "Device:R")
        assert re.search(r"\(at [\d.]+ [\d.]+ 270\)", header), header
        assert "(mirror y)" in header, header


# ---------------------------------------------------------------------------
# End-to-end: the file KiCad itself has to accept
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(_KICAD_CLI is None, reason="KiCad CLI not installed")
class TestRealKicadLoadsTheResult:
    """The unit tests above assert on tokens; this asserts on KiCad's verdict.

    Only exercises versions at or below the installed CLI's own format -- a
    newer-format file is legitimately refused and would prove nothing.
    """

    @staticmethod
    def _cli_major() -> int:
        out = subprocess.run(
            [str(_KICAD_CLI), "version"], capture_output=True, text=True, timeout=60
        )
        m = re.match(r"\s*(\d+)", out.stdout)
        return int(m.group(1)) if m else 0

    @pytest.mark.parametrize("version", [V8, V9])
    def test_placed_symbols_load(self, tmp_path: Path, version: int) -> None:
        if self._cli_major() < 9:
            pytest.skip("needs KiCad >= 9 to read a 20250114 file")

        sch = _sch_with_version(tmp_path, version)
        # power:GND exercises escaping, Device:R exercises the attribute line.
        assert _place(sch, "power", "GND", "#PWR01", value="GND", x=50, y=50)
        assert _place(sch, "Device", "R", "R1", value="10k", x=100, y=100, angle=90)

        out = subprocess.run(
            [str(_KICAD_CLI), "sch", "export", "svg", str(sch), "-o", str(tmp_path / "svg")],
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert out.returncode == 0, (
            f"KiCad refused a v{version} schematic it should accept.\n"
            f"stdout: {out.stdout}\nstderr: {out.stderr}"
        )
