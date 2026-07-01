"""Tests for ``_svg_to_png`` used by ``get_schematic_view``.

Regression guard for the bug where the converter chain (pymupdf → inkscape
→ ImageMagick) had no available backend on a stock install, so the function
returned ``None`` and the handler silently fell back to emitting the raw
full-sheet SVG — which ignores width/height and blows past MCP clients'
inline size cap. cairosvg is a declared dependency and must be used.

conftest.py pre-installs a MagicMock for ``pcbnew`` so the module imports
without a real KiCAD install.
"""

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.unit

from commands.schematic_handlers import _svg_to_png  # noqa: E402

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

SAMPLE_SVG = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="80mm" '
    'viewBox="0 0 100 80">'
    '<rect x="10" y="10" width="60" height="40" fill="none" stroke="black" '
    'stroke-width="1"/>'
    '<line x1="10" y1="30" x2="70" y2="30" stroke="black" stroke-width="0.5"/>'
    "</svg>"
)


def _png_dimensions(png: bytes) -> tuple[int, int]:
    """Read width/height from a PNG's IHDR chunk (bytes 16:24, big-endian)."""
    width, height = struct.unpack(">II", png[16:24])
    return width, height


@pytest.fixture()
def svg_file(tmp_path: Path) -> str:
    path = tmp_path / "sample.svg"
    path.write_text(SAMPLE_SVG, encoding="utf-8")
    return str(path)


def test_returns_png_bytes_not_none(svg_file: str) -> None:
    """A converter must be available on a stock install (cairosvg) — never None."""
    png = _svg_to_png(svg_file, 200, 150)
    assert png is not None, "no SVG->PNG converter available; would fall back to oversized SVG"
    assert png.startswith(PNG_MAGIC)


def test_honors_requested_dimensions(svg_file: str) -> None:
    """width/height must control the raster size (they were previously ignored)."""
    png = _svg_to_png(svg_file, 200, 150)
    assert png is not None
    assert _png_dimensions(png) == (200, 150)

    smaller = _svg_to_png(svg_file, 80, 60)
    assert smaller is not None
    assert _png_dimensions(smaller) == (80, 60)


def test_smaller_dimensions_shrink_payload(svg_file: str) -> None:
    """Shrinking dimensions must shrink the payload — the core promise to callers."""
    big = _svg_to_png(svg_file, 1200, 900)
    small = _svg_to_png(svg_file, 300, 225)
    assert big is not None and small is not None
    assert len(small) < len(big)
