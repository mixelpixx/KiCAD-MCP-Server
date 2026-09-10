"""
Tests for schematic-writer output compatibility.

Three regressions (#351), all of which made KiCad 8 or 9 reject the whole schematic with a
bare "Failed to load schematic" that names neither a token nor a line:

1. ``(body_style ...)`` / ``(in_pos_files ...)`` were written into every placed
   symbol. Both are KiCad 10 additions, so any KiCad 8 (20231120) or KiCad 9
   (20250114) file became unloadable -- including this repo's own
   ``minimal``/``empty``/``template_with_symbols`` templates, which declare
   20250114.
2. Property values were interpolated into the s-expression unescaped. Fixed in
   #354 and pinned by tests/test_sexpr_escaping.py; not repeated here.
3. ``add_schematic_component`` dropped the documented ``angle`` and ``mirrorY``
   arguments: the TS layer nests them inside ``component``, and the Python
   handler never read them back out.
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

TEMPLATES_DIR = Path(__file__).parent.parent / "python" / "templates"

from utils.kicad_cli import resolve_kicad_cli  # noqa: E402

_KICAD_CLI = resolve_kicad_cli()

# Format version tokens, by the KiCad release that introduced them.
V8 = 20231120
V9 = 20250114
V10 = 20260101


def _standin_library_text(lib_id: str, name: str) -> str:
    """A one-symbol ``.kicad_sym`` holding the KiCad-authored block that
    ``python/templates/empty.kicad_sch`` embeds for *lib_id*.

    That template declares 20250114 and its block carries no KiCad 10-only
    attribute, so the stand-in is what a KiCad 8 or 9 library would hold.
    """
    from utils.sexpr_format import match_paren

    text = (TEMPLATES_DIR / "empty.kicad_sch").read_text(encoding="utf-8")
    start = text.index(f'(symbol "{lib_id}"')
    block = text[start : match_paren(text, start) + 1].replace(f'"{lib_id}"', f'"{name}"', 1)
    return (
        '(kicad_symbol_lib (version 20231120) (generator "kicad_symbol_editor")\n' + block + "\n)\n"
    )


@pytest.fixture(autouse=True)
def _symbol_library(tmp_path_factory: Any, monkeypatch: Any) -> Any:
    """Use the installed KiCad libraries when there are any, else a stand-in.

    CI's unit jobs have no KiCad, so ``Device:R`` has to come from somewhere;
    a developer machine and the integration jobs have the real libraries, which
    is what the kicad-cli class below must exercise.
    """
    from commands.dynamic_symbol_loader import DynamicSymbolLoader

    DynamicSymbolLoader.clear_library_caches()
    if DynamicSymbolLoader().find_library_file("Device") is None:
        lib_dir = tmp_path_factory.mktemp("symbols")
        (lib_dir / "Device.kicad_sym").write_text(
            _standin_library_text("Device:R", "R"), encoding="utf-8"
        )
        monkeypatch.setenv("KICAD_SYMBOL_DIR", str(lib_dir))
        DynamicSymbolLoader.clear_library_caches()
    yield
    DynamicSymbolLoader.clear_library_caches()


@pytest.mark.unit
def test_standin_library_places_a_symbol(tmp_path: Path) -> None:
    """The stand-in must work end to end, or CI would only prove a skip."""
    from commands.dynamic_symbol_loader import DynamicSymbolLoader

    lib_dir = tmp_path / "symbols"
    lib_dir.mkdir()
    (lib_dir / "Standin.kicad_sym").write_text(
        _standin_library_text("Device:R", "R"), encoding="utf-8"
    )
    sch = _sch_with_version(tmp_path, V9)
    loader = DynamicSymbolLoader()
    loader.find_kicad_symbol_libraries = lambda: [lib_dir]  # type: ignore[method-assign]
    loader.inject_symbol_into_schematic(sch, "Standin", "R")
    assert loader.create_component_instance(sch, "Standin", "R", reference="R1", x=100, y=100)
    header = _placed_symbol_header(sch.read_text(), "Standin:R")
    assert "body_style" not in header


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
