"""Tests for utils.sexpr_format — KiCad-canonical schematic serialization.

These guard the fix for the schematic write tools minifying .kicad_sch onto a
single line.  The formatter must reproduce, byte-for-byte, what eeschema's
"Save" produces so tool writes create minimal, reviewable diffs.
"""

import sys
from pathlib import Path

import sexpdata
from sexpdata import Symbol as S

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

from commands.wire_dragger import WireDragger  # noqa: E402
from utils.sexpr_format import dumps, prettify  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

# A genuine canonical schematic produced by `kicad-cli sch upgrade` (KiCad 10).
# Exercises: (xy ...) inline runs, an escaped quote in a string, nested effects,
# tab indentation, and the trailing newline.
CANONICAL_GOLDEN = (
    "(kicad_sch\n"
    "\t(version 20260306)\n"
    '\t(generator "eeschema")\n'
    '\t(generator_version "10.0")\n'
    '\t(uuid "11111111-1111-4111-8111-111111111111")\n'
    '\t(paper "A4")\n'
    "\t(lib_symbols)\n"
    "\t(polyline\n"
    "\t\t(pts\n"
    "\t\t\t(xy 0 0) (xy 1 0) (xy 2 0) (xy 3 0)\n"
    "\t\t)\n"
    "\t\t(stroke\n"
    "\t\t\t(width 0)\n"
    "\t\t\t(type default)\n"
    "\t\t)\n"
    "\t\t(fill\n"
    "\t\t\t(type none)\n"
    "\t\t)\n"
    '\t\t(uuid "c744d04a-07a6-46fb-a4c5-ff282ffe1664")\n'
    "\t)\n"
    '\t(text "quote \\"x\\" end"\n'
    "\t\t(exclude_from_sim no)\n"
    "\t\t(at 10 10 0)\n"
    "\t\t(effects\n"
    "\t\t\t(font\n"
    "\t\t\t\t(size 1.27 1.27)\n"
    "\t\t\t)\n"
    "\t\t)\n"
    '\t\t(uuid "08c0d948-c7dc-4db2-9955-79d9d2405d9d")\n'
    "\t)\n"
    '\t(label "NET1"\n'
    "\t\t(at 5 5 0)\n"
    "\t\t(effects\n"
    "\t\t\t(font\n"
    "\t\t\t\t(size 1.27 1.27)\n"
    "\t\t\t)\n"
    "\t\t\t(justify left)\n"
    "\t\t)\n"
    '\t\t(uuid "91ce1fc6-d449-41ea-a41b-1c11ec3499e7")\n'
    "\t)\n"
    ")\n"
)


class TestPrettify:
    def test_reproduces_canonical_kicad_output(self):
        """dumps(parsed) is byte-identical to eeschema's canonical format."""
        assert dumps(sexpdata.loads(CANONICAL_GOLDEN)) == CANONICAL_GOLDEN

    def test_prettify_is_idempotent(self):
        once = prettify(sexpdata.dumps(sexpdata.loads(CANONICAL_GOLDEN)))
        assert prettify(once) == once

    def test_not_minified(self):
        out = dumps(sexpdata.loads(CANONICAL_GOLDEN))
        assert out.count("\n") > 30  # multi-line, not a single minified line

    def test_uses_tab_indentation(self):
        out = dumps(sexpdata.loads(CANONICAL_GOLDEN))
        assert "\n\t(version" in out
        assert "    (version" not in out  # never space-indented

    def test_trailing_newline(self):
        assert dumps(sexpdata.loads(CANONICAL_GOLDEN)).endswith(")\n")

    def test_xy_runs_stay_inline(self):
        out = dumps(sexpdata.loads(CANONICAL_GOLDEN))
        assert "(xy 0 0) (xy 1 0) (xy 2 0) (xy 3 0)" in out

    def test_xy_wraps_long_runs(self):
        pts = " ".join(f"(xy {i}.5 {i}.25)" for i in range(20))
        out = prettify(f"(kicad_sch (polyline (pts {pts})))")
        xy_lines = [ln for ln in out.splitlines() if "(xy" in ln]
        # A long run wraps across multiple lines (not all 20 on one line) and no
        # data is lost (all 20 points survive the wrap).
        assert len(xy_lines) > 1
        assert out.count("(xy ") == 20
        # KiCad appends a new (xy only while column (tabs = 1) < 99, so lines
        # stay near that bound (at most one extra group of slack).
        for ln in xy_lines:
            assert len(ln) < 99 + len("(xy 19.5 19.25)")

    def test_escaped_quote_not_treated_as_list_boundary(self):
        # A "(" inside a quoted string must not open a new list.
        src = '(kicad_sch (text "a ( b ) c \\" d"))'
        out = prettify(src)
        assert sexpdata.loads(out) == sexpdata.loads(src)

    def test_backslash_before_quote_handled(self):
        # A literal backslash followed by an escaped quote: the quote still
        # toggles (odd backslash count before it means it is escaped).
        src = r'(kicad_sch (text "path C:\\dir\" x ) y"))'
        out = prettify(src)
        assert sexpdata.loads(out) == sexpdata.loads(src)

    def test_round_trip_data_stable(self):
        data = sexpdata.loads(CANONICAL_GOLDEN)
        assert sexpdata.loads(dumps(data)) == data

    def test_degrades_to_compact_is_never_needed_for_valid_data(self):
        # dumps() falls back to compact only if a formatting bug would corrupt
        # data; for well-formed input it must always return the pretty form.
        out = dumps(sexpdata.loads(CANONICAL_GOLDEN))
        assert "\n" in out  # not the single-line compact fallback


class TestCanonicalFixture:
    """Round-trip against a real, multi-symbol schematic emitted by kicad-cli.

    Covers the constructs the synthetic golden omits: a full lib_symbols
    definition, a placed symbol with a (instances (project ...)) block, an
    empty quoted string, and many wrapped (xy ...) runs.
    """

    def _golden(self):
        return (FIXTURES / "canonical_schematic.kicad_sch").read_text(encoding="utf-8")

    def test_byte_identical_round_trip(self):
        g = self._golden()
        assert dumps(sexpdata.loads(g)) == g

    def test_idempotent(self):
        g = self._golden()
        assert prettify(g) == g

    def test_data_preserved(self):
        g = self._golden()
        assert sexpdata.loads(dumps(sexpdata.loads(g))) == sexpdata.loads(g)


class TestWriteToolIntegration:
    """End-to-end: a real write tool must produce canonical output on disk, not a
    minified single line. WireManager.add_wire is self-contained (no pcbnew), so it
    exercises the full read -> mutate -> kicad_dumps write path a caller hits."""

    MINIMAL = (
        '(kicad_sch (version 20250114) (generator "test") (uuid "u") (paper "A4")'
        ' (lib_symbols) (sheet_instances (path "/" (page "1"))))'
    )

    def test_add_wire_writes_canonical_format(self, tmp_path):
        from commands.wire_manager import WireManager  # noqa: E402

        p = tmp_path / "t.kicad_sch"
        p.write_text(self.MINIMAL, encoding="utf-8")

        assert WireManager.add_wire(p, [10.0, 10.0], [20.0, 10.0]) is True

        out = p.read_text(encoding="utf-8")
        assert out.count("\n") > 5  # multi-line, not minified
        assert "\n\t(" in out  # tab-indented like eeschema
        assert out.endswith(")\n")  # trailing newline
        assert "(wire" in out  # the edit landed
        assert sexpdata.loads(out) is not None  # still parses
        # Writing again is stable (idempotent formatting).
        assert prettify(out) == out


class TestIntegerRotationAngle:
    """update_symbol_rotation_mirror must write integral angles as ints so the
    output matches KiCad (e.g. `(at x y 90)`, not `(at x y 90.0)`)."""

    def test_integral_angle_written_as_int(self):
        at = [S("at"), 36.83, 40.64, 0]
        sch = [
            S("kicad_sch"),
            [
                S("symbol"),
                [S("lib_id"), "Device:D"],
                at,
                [S("property"), "Reference", "D3"],
            ],
        ]
        WireDragger.update_symbol_rotation_mirror(sch, "D3", 90.0, None)
        assert at[3] == 90
        assert isinstance(at[3], int)
        assert "(at 36.83 40.64 90)" in dumps(sch)
