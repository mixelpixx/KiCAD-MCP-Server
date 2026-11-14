"""list_schematic_rectangles and set_schematic_rectangle (#525).

A titled box drawn around a group of parts is a ``(rectangle ...)`` at the top
level of the sheet. ``lib_symbols`` holds rectangles too (symbol bodies), and
those must never be listed or touched.

KICAD_RECTANGLES is copied verbatim from KiCad's own test data
(``qa/data/eeschema/groups_load_save.kicad_sch``, written by eeschema 9.99):
KiCad writes a shape's uuid without quotes, while this repo's writers quote
theirs, so the parser has to read both. KICAD10_RECTANGLE follows KiCad 10's
writer (``formatRect`` in ``sch_io_kicad_sexpr_common.cpp``): an optional
``(radius r)`` after ``end`` and colors as ``(color r g b a)``.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import sexpdata

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.schematic_rectangles import (  # noqa: E402
    list_schematic_rectangles,
    set_schematic_rectangle,
)

pytestmark = pytest.mark.unit

KICAD_RECTANGLES = """\t(rectangle
\t\t(start 110.744 72.136)
\t\t(end 124.714 86.106)
\t\t(stroke
\t\t\t(width 0)
\t\t\t(type default)
\t\t)
\t\t(fill
\t\t\t(type none)
\t\t)
\t\t(uuid 7e1da7e2-473f-48bf-b7bf-2eb79e1b1372)
\t)
\t(rectangle
\t\t(start 129.794 68.326)
\t\t(end 137.414 94.996)
\t\t(stroke
\t\t\t(width 0)
\t\t\t(type default)
\t\t)
\t\t(fill
\t\t\t(type none)
\t\t)
\t\t(uuid d26fc350-11e5-4917-ba78-4e25070d7aa8)
\t)
"""
FIRST = "7e1da7e2-473f-48bf-b7bf-2eb79e1b1372"
SECOND = "d26fc350-11e5-4917-ba78-4e25070d7aa8"

KICAD10_RECTANGLE = """\t(rectangle
\t\t(start 50 40)
\t\t(end 90 70)
\t\t(radius 2.54)
\t\t(stroke
\t\t\t(width 0.254)
\t\t\t(type dash)
\t\t\t(color 255 0 0 1)
\t\t)
\t\t(fill
\t\t\t(type color)
\t\t\t(color 0 128 255 0.25)
\t\t)
\t\t(uuid "aaaaaaaa-0000-0000-0000-000000000010")
\t\t(locked yes)
\t)
"""
ROUNDED = "aaaaaaaa-0000-0000-0000-000000000010"

# A symbol body is a rectangle inside lib_symbols; it must stay invisible here.
LIB_SYMBOLS = """\t(lib_symbols
\t\t(symbol "T:Box"
\t\t\t(symbol "Box_0_1"
\t\t\t\t(rectangle
\t\t\t\t\t(start -2.54 2.54)
\t\t\t\t\t(end 2.54 -2.54)
\t\t\t\t\t(stroke
\t\t\t\t\t\t(width 0.254)
\t\t\t\t\t\t(type default)
\t\t\t\t\t)
\t\t\t\t\t(fill
\t\t\t\t\t\t(type background)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t)
\t\t)
\t)
"""


def _sch(body: str = "") -> str:
    return (
        "(kicad_sch\n"
        "\t(version 20250114)\n"
        '\t(generator "eeschema")\n'
        '\t(generator_version "9.0")\n'
        '\t(uuid "11111111-1111-1111-1111-111111111111")\n'
        '\t(paper "A4")\n' + LIB_SYMBOLS + body + "\t(sheet_instances\n"
        '\t\t(path "/"\n'
        '\t\t\t(page "1")\n'
        "\t\t)\n"
        "\t)\n"
        "\t(embedded_fonts no)\n"
        ")\n"
    )


def _write(tmp_path: Path, body: str = "", newline: str = "\n") -> Path:
    path = tmp_path / "box.kicad_sch"
    with open(path, "w", encoding="utf-8", newline=newline) as fh:
        fh.write(_sch(body))
    return path


def _list(path: Path):
    reply = list_schematic_rectangles({"schematicPath": str(path)})
    assert reply["success"], reply
    return reply["rectangles"]


def _set(path: Path, **params):
    return set_schematic_rectangle({"schematicPath": str(path), **params})


def _by_uuid(path: Path):
    return {r["uuid"]: r for r in _list(path)}


# --- list ---------------------------------------------------------------


def test_lists_rectangles_as_kicad_writes_them(tmp_path):
    path = _write(tmp_path, KICAD_RECTANGLES)
    reply = list_schematic_rectangles({"schematicPath": str(path)})
    assert reply["count"] == 2
    first = reply["rectangles"][0]
    assert first == {
        "uuid": FIRST,
        "start": {"x": 110.744, "y": 72.136},
        "end": {"x": 124.714, "y": 86.106},
        "stroke": {"width": 0.0, "type": "default"},
        "fill": {"type": "none"},
    }


def test_symbol_body_rectangles_are_not_listed(tmp_path):
    assert _list(_write(tmp_path)) == []


def test_lists_radius_colors_and_locked(tmp_path):
    rect = _list(_write(tmp_path, KICAD10_RECTANGLE))[0]
    assert rect["uuid"] == ROUNDED
    assert rect["radius"] == 2.54
    assert rect["stroke"] == {"width": 0.254, "type": "dash", "color": [255, 0, 0, 1.0]}
    assert rect["fill"] == {"type": "color", "color": [0, 128, 255, 0.25]}
    assert rect["locked"] is True


def test_list_needs_an_existing_schematic(tmp_path):
    reply = list_schematic_rectangles({"schematicPath": str(tmp_path / "missing.kicad_sch")})
    assert reply["success"] is False
    assert "not found" in reply["message"].lower()


# --- create -------------------------------------------------------------


def test_create_returns_the_new_uuid_and_lists_it(tmp_path):
    path = _write(tmp_path, KICAD_RECTANGLES)
    reply = _set(path, start=[20, 30], end={"x": 80.5, "y": 60})
    assert reply["success"], reply
    new = _by_uuid(path)[reply["uuid"]]
    assert new["start"] == {"x": 20.0, "y": 30.0}
    assert new["end"] == {"x": 80.5, "y": 60.0}
    assert new["stroke"] == {"width": 0.0, "type": "default"}
    assert new["fill"] == {"type": "none"}
    assert reply["rectangle"] == new
    assert len(_list(path)) == 3


def test_create_writes_kicads_layout_before_sheet_instances(tmp_path):
    path = _write(tmp_path)
    reply = _set(path, start=[20, 30], end=[80, 60])
    text = path.read_text(encoding="utf-8")
    block = (
        "\t(rectangle\n"
        "\t\t(start 20 30)\n"
        "\t\t(end 80 60)\n"
        "\t\t(stroke\n"
        "\t\t\t(width 0)\n"
        "\t\t\t(type default)\n"
        "\t\t)\n"
        "\t\t(fill\n"
        "\t\t\t(type none)\n"
        "\t\t)\n"
        f'\t\t(uuid "{reply["uuid"]}")\n'
        "\t)\n"
    )
    assert block in text
    assert text.index(block) < text.index("(sheet_instances")
    assert text.index(block) > text.index("(lib_symbols")
    sexpdata.loads(text)


def test_create_with_stroke_and_fill(tmp_path):
    path = _write(tmp_path)
    reply = _set(
        path,
        start=[0, 0],
        end=[10, 10],
        stroke={"width": 0.254, "type": "dash_dot", "color": [10, 20, 30, 0.5]},
        fill={"type": "color", "color": [255, 255, 0, 0.2]},
    )
    assert reply["success"], reply
    rect = _by_uuid(path)[reply["uuid"]]
    assert rect["stroke"] == {"width": 0.254, "type": "dash_dot", "color": [10, 20, 30, 0.5]}
    assert rect["fill"] == {"type": "color", "color": [255, 255, 0, 0.2]}


@pytest.mark.parametrize(
    "params, word",
    [
        ({"end": [1, 1]}, "start"),
        ({"start": [0, 0]}, "end"),
        ({"start": [0, 0], "end": "1,1"}, "end"),
        ({"start": [0, 0], "end": [1, 1], "stroke": {"type": "wavy"}}, "type"),
        ({"start": [0, 0], "end": [1, 1], "stroke": {"width": -1}}, "width"),
        ({"start": [0, 0], "end": [1, 1], "fill": {"type": "hatch"}}, "type"),
        ({"start": [0, 0], "end": [1, 1], "fill": {"type": "color"}}, "color"),
        (
            {"start": [0, 0], "end": [1, 1], "fill": {"type": "color", "color": [300, 0, 0, 1]}},
            "color",
        ),
        ({"start": [0, 0], "end": [1, 1], "stroke": {"color": [0, 0, 0]}}, "color"),
        ({"start": [0, 0], "end": [1, 1], "radius": 1}, "radius"),
        ({"delete": True}, "uuid"),
    ],
)
def test_bad_requests_are_refused_and_write_nothing(tmp_path, params, word):
    path = _write(tmp_path, KICAD_RECTANGLES)
    before = path.read_bytes()
    reply = _set(path, **params)
    assert reply["success"] is False
    assert word in reply["message"]
    assert path.read_bytes() == before


# --- edit ---------------------------------------------------------------


def test_edit_changes_only_the_given_fields(tmp_path):
    path = _write(tmp_path, KICAD_RECTANGLES)
    reply = _set(path, uuid=FIRST, end=[130, 90])
    assert reply["success"], reply
    rects = _by_uuid(path)
    assert rects[FIRST]["end"] == {"x": 130.0, "y": 90.0}
    assert rects[FIRST]["start"] == {"x": 110.744, "y": 72.136}
    assert rects[FIRST]["stroke"] == {"width": 0.0, "type": "default"}
    assert rects[SECOND]["end"] == {"x": 137.414, "y": 94.996}
    assert reply["rectangle"] == rects[FIRST]


def test_edit_leaves_untouched_lines_byte_for_byte(tmp_path):
    path = _write(tmp_path, KICAD_RECTANGLES)
    _set(path, uuid=FIRST, end=[130, 90])
    expected = _sch(KICAD_RECTANGLES.replace("(end 124.714 86.106)", "(end 130 90)", 1))
    assert path.read_text(encoding="utf-8") == expected


def test_edit_merges_a_partial_stroke(tmp_path):
    path = _write(tmp_path, KICAD10_RECTANGLE)
    assert _set(path, uuid=ROUNDED, stroke={"width": 0.5})["success"]
    rect = _by_uuid(path)[ROUNDED]
    assert rect["stroke"] == {"width": 0.5, "type": "dash", "color": [255, 0, 0, 1.0]}


def test_edit_keeps_radius_locked_and_uuid_as_written(tmp_path):
    path = _write(tmp_path, KICAD10_RECTANGLE)
    assert _set(path, uuid=ROUNDED, start=[45, 35], fill={"type": "none"})["success"]
    text = path.read_text(encoding="utf-8")
    assert "\t\t(radius 2.54)\n" in text
    assert "\t\t(locked yes)\n" in text
    assert f'\t\t(uuid "{ROUNDED}")\n' in text
    rect = _by_uuid(path)[ROUNDED]
    assert rect["radius"] == 2.54 and rect["fill"] == {"type": "none"}


def test_edit_keeps_kicads_unquoted_uuid(tmp_path):
    path = _write(tmp_path, KICAD_RECTANGLES)
    _set(path, uuid=SECOND, fill={"type": "background"})
    assert f"\t\t(uuid {SECOND})\n" in path.read_text(encoding="utf-8")
    assert _by_uuid(path)[SECOND]["fill"] == {"type": "background"}


def test_edit_to_color_fill_needs_a_color(tmp_path):
    path = _write(tmp_path, KICAD_RECTANGLES)
    reply = _set(path, uuid=FIRST, fill={"type": "color"})
    assert reply["success"] is False and "color" in reply["message"]


def test_edit_keeps_crlf_line_endings(tmp_path):
    path = _write(tmp_path, KICAD_RECTANGLES, newline="\r\n")
    assert _set(path, uuid=FIRST, end=[130, 90])["success"]
    raw = path.read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")


def test_edit_with_nothing_to_change_is_refused(tmp_path):
    path = _write(tmp_path, KICAD_RECTANGLES)
    reply = _set(path, uuid=FIRST)
    assert reply["success"] is False and "nothing to change" in reply["message"]


def test_unknown_uuid_is_an_error_that_names_the_rectangles_there(tmp_path):
    path = _write(tmp_path, KICAD_RECTANGLES)
    before = path.read_bytes()
    for params in ({"end": [1, 1]}, {"delete": True}):
        reply = _set(path, uuid="no-such-uuid", **params)
        assert reply["success"] is False
        assert FIRST in reply["message"] and SECOND in reply["message"]
    assert path.read_bytes() == before


def test_symbol_body_rectangles_cannot_be_edited(tmp_path):
    # The lib_symbols rectangle has no uuid; even a uuid-less match must not happen.
    path = _write(tmp_path)
    reply = _set(path, uuid="", end=[1, 1])
    assert reply["success"] is False


# --- delete -------------------------------------------------------------


def test_delete_removes_only_that_rectangle(tmp_path):
    path = _write(tmp_path, KICAD_RECTANGLES)
    reply = _set(path, uuid=FIRST, delete=True)
    assert reply["success"] and reply["deleted"] is True
    second_block = KICAD_RECTANGLES[KICAD_RECTANGLES.index("\t(rectangle", 1) :]
    assert path.read_text(encoding="utf-8") == _sch(second_block)


def test_delete_refuses_other_fields(tmp_path):
    path = _write(tmp_path, KICAD_RECTANGLES)
    reply = _set(path, uuid=FIRST, delete=True, end=[1, 1])
    assert reply["success"] is False and "delete" in reply["message"]


# --- KiCad --------------------------------------------------------------


@pytest.mark.integration
def test_kicad_cli_loads_the_result(tmp_path):
    if not shutil.which("kicad-cli"):
        pytest.skip("needs kicad-cli")
    path = _write(tmp_path, KICAD_RECTANGLES)
    made = _set(
        path,
        start=[20, 30],
        end=[80, 60],
        stroke={"width": 0.254, "type": "dash", "color": [0, 0, 255, 1]},
        fill={"type": "color", "color": [255, 255, 0, 0.2]},
    )
    assert made["success"]
    assert _set(path, uuid=made["uuid"], end=[90, 70])["success"]
    assert _set(path, uuid=FIRST, delete=True)["success"]
    out = tmp_path / "box.net"
    result = subprocess.run(
        ["kicad-cli", "sch", "export", "netlist", "-o", str(out), str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert out.exists()


def test_edit_adds_a_missing_stroke_or_fill(tmp_path):
    bare = (
        "\t(rectangle\n"
        "\t\t(start 1 2)\n"
        "\t\t(end 3 4)\n"
        '\t\t(uuid "bbbbbbbb-0000-0000-0000-000000000001")\n'
        "\t)\n"
    )
    path = _write(tmp_path, bare)
    uid = "bbbbbbbb-0000-0000-0000-000000000001"
    assert _set(path, uuid=uid, stroke={"type": "dot"}, fill={"type": "outline"})["success"]
    rect = _by_uuid(path)[uid]
    assert rect["stroke"] == {"width": 0.0, "type": "dot"}
    assert rect["fill"] == {"type": "outline"}
    text = path.read_text(encoding="utf-8")
    assert "\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type dot)\n\t\t)\n" in text
    assert text.index("(stroke") < text.index("(fill") < text.index('(uuid "bbbbbbbb')
