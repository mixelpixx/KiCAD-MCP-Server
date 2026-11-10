"""A rule area with several outlines reaches Freerouting whole.

KiCad's Specctra export writes only the first outline of a rule area; on a real board a
keepout built from many voltage halos exported as one polygon, and Freerouting put logic
vias 0.4 mm from 400 V pads that the dropped outlines covered.
"""

import os
import re

import pytest
from commands.freerouting import _append_to_structure, dsn_quote, dsn_unquote


def _require_pcbnew():
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
        pytest.skip("needs KICAD_USE_REAL_PCBNEW=1")
    return pytest.importorskip("pcbnew")


def _board_with_two_outline_keepout(pcbnew, tracks=True, vias=True, layer=None):
    b = pcbnew.BOARD()
    mm = pcbnew.FromMM
    # board outline so the export has a boundary
    for (x1, y1), (x2, y2) in (
        ((0, 0), (40, 0)),
        ((40, 0), (40, 30)),
        ((40, 30), (0, 30)),
        ((0, 30), (0, 0)),
    ):
        s = pcbnew.PCB_SHAPE(b)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pcbnew.VECTOR2I(mm(x1), mm(y1)))
        s.SetEnd(pcbnew.VECTOR2I(mm(x2), mm(y2)))
        s.SetLayer(pcbnew.Edge_Cuts)
        b.Add(s)
    z = pcbnew.ZONE(b)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowTracks(tracks)
    z.SetDoNotAllowVias(vias)
    z.SetLayer(pcbnew.F_Cu if layer is None else layer)
    o = z.Outline()
    for x0 in (5, 25):
        o.NewOutline()
        for x, y in ((x0, 5), (x0 + 8, 5), (x0 + 8, 12), (x0, 12)):
            o.Append(mm(x), mm(y))
    b.Add(z)
    return b


def _keepouts(text, layer="F.Cu"):
    pat = (
        r"\((keepout|wire_keepout|via_keepout) \"\" \(polygon " + re.escape(layer) + r" 0 ([^)]*)\)"
    )
    return re.findall(pat, text)


# --- the shared DSN name helper ---------------------------------------------------------


@pytest.mark.parametrize(
    "name, written",
    [
        ("F.Cu", "F.Cu"),
        ("In1.Cu", "In1.Cu"),
        ("Top", "Top"),
        ("Bottom side", '"Bottom side"'),  # a space
        ("GND-plane", '"GND-plane"'),  # a dash anywhere but first
        ("-plane", "-plane"),
        ("#weird", '"#weird"'),  # a leading #
        ("Net-(C5-Pad1)", '"Net-(C5-Pad1)"'),
        ("50%", '"50%"'),
        ("", '""'),
    ],
)
def test_dsn_quote_matches_kicads_export(name, written):
    # The quoted cases were checked against what KiCad 10.0.8 writes for renamed layers.
    assert dsn_quote(name) == written
    assert dsn_unquote(written) == name


def test_dsn_unquote_leaves_bare_names_alone():
    assert dsn_unquote("F.Cu") == "F.Cu"
    assert dsn_unquote('"') == '"'


# --- inserting at the end of (structure) ------------------------------------------------

DSN = (
    "(pcb x\n"
    "  (structure\n"
    "    (layer F.Cu\n      (type signal)\n    )\n"
    "    (boundary\n      (path pcb 0  0 0  40000 0  40000 -30000  0 -30000  0 0)\n    )\n"
    "  )\n"
    "  (placement\n"
    "  )\n"
    ")\n"
)


def test_lines_go_at_the_end_of_structure():
    out = _append_to_structure(DSN, ['    (keepout "" (polygon F.Cu 0 1 2 3 4))'])
    assert out == DSN.replace(
        "    )\n  )\n  (placement",
        '    )\n    (keepout "" (polygon F.Cu 0 1 2 3 4))\n  )\n  (placement',
    )


def test_structure_end_is_parsed_not_guessed():
    # Different indentation and a closing paren on a content line: still the right place.
    dsn = "(pcb x\n(structure\n (layer F.Cu (type signal))\n (boundary (path pcb 0 0 0 1 1)))\n(placement))\n"
    out = _append_to_structure(dsn, ['    (keepout "" (polygon F.Cu 0 1 2))'])
    assert out == (
        "(pcb x\n(structure\n (layer F.Cu (type signal))\n (boundary (path pcb 0 0 0 1 1))\n"
        '    (keepout "" (polygon F.Cu 0 1 2))\n)\n(placement))\n'
    )
    # A name containing a paren inside quotes does not end the block early.
    dsn = '(pcb x\n  (structure\n    (layer "Bottom (side)" (type signal))\n  )\n  (placement\n  )\n)\n'
    out = _append_to_structure(dsn, ["    (k)"])
    assert out.index("(k)") > out.index('"Bottom (side)"')
    assert out.index("(k)") < out.index("(placement")


def test_line_endings_are_kept():
    crlf = DSN.replace("\n", "\r\n")
    out = _append_to_structure(crlf, ["    (k 1)", "    (k 2)"])
    assert "\n" not in out.replace("\r\n", "")
    assert "    (k 1)\r\n    (k 2)\r\n  )\r\n  (placement" in out


def test_nothing_to_add_or_no_structure():
    assert _append_to_structure(DSN, []) == DSN
    assert _append_to_structure("(pcb x (placement))", ["    (k)"]) == "(pcb x (placement))"
    assert _append_to_structure("(pcb x (structure", ["    (k)"]) == "(pcb x (structure"


# --- against KiCad's own export ---------------------------------------------------------


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_every_outline_of_a_rule_area_is_exported(tmp_path):
    pcbnew = _require_pcbnew()
    from commands.freerouting import _append_missing_keepouts

    b = _board_with_two_outline_keepout(pcbnew)
    dsn = tmp_path / "b.dsn"
    assert pcbnew.ExportSpecctraDSN(b, str(dsn)) in (True, 0, None) or dsn.exists()
    raw = dsn.read_bytes()
    before = _keepouts(raw.decode())
    assert len(before) == 1  # KiCad's own export: the second outline is missing

    assert _append_missing_keepouts(b, str(dsn)) == 1
    patched = dsn.read_bytes()
    after = _keepouts(patched.decode())
    assert len(after) == 2
    xs = sorted(float(pts.split()[0]) for _, pts in after)
    # second rectangle starts at x = 25 mm (or 33 mm, depending on the first vertex)
    assert any(24999 <= x <= 33001 for x in xs[1:])
    # y is negated, as KiCad writes it
    assert all(float(pts.split()[1]) < 0 for _, pts in after)
    # the file keeps its line endings and everything outside the inserted line
    assert patched.count(b"\r\n") == raw.count(b"\r\n")
    assert patched.startswith(raw[: raw.index(b"(placement") - 4])
    assert patched.endswith(raw[raw.index(b"(placement") :])


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_renamed_layer_is_quoted_like_kicad_does(tmp_path):
    pcbnew = _require_pcbnew()
    from commands.freerouting import _append_missing_keepouts

    b = _board_with_two_outline_keepout(pcbnew, layer=pcbnew.B_Cu)
    b.SetLayerName(pcbnew.B_Cu, "Bottom side")
    dsn = tmp_path / "b.dsn"
    pcbnew.ExportSpecctraDSN(b, str(dsn))
    kicads = _keepouts(dsn.read_text(), layer='"Bottom side"')
    assert len(kicads) == 1  # KiCad quotes the name
    _append_missing_keepouts(b, str(dsn))
    assert len(_keepouts(dsn.read_text(), layer='"Bottom side"')) == 2
    assert "(polygon Bottom side" not in dsn.read_text()


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_keepout_kind_follows_the_rule_area_flags(tmp_path):
    pcbnew = _require_pcbnew()
    from commands.freerouting import _append_missing_keepouts

    b = _board_with_two_outline_keepout(pcbnew, tracks=False, vias=True)
    dsn = tmp_path / "b.dsn"
    pcbnew.ExportSpecctraDSN(b, str(dsn))
    _append_missing_keepouts(b, str(dsn))
    kinds = [k for k, _ in _keepouts(dsn.read_text())]
    assert kinds.count("via_keepout") == len(kinds) == 2


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_single_outline_areas_are_left_alone(tmp_path):
    pcbnew = _require_pcbnew()
    from commands.freerouting import _append_missing_keepouts

    b = pcbnew.BOARD()
    dsn = tmp_path / "b.dsn"
    dsn.write_text("(pcb x\n  (structure\n  )\n  (placement\n  )\n)\n")
    assert _append_missing_keepouts(b, str(dsn)) == 0


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_export_dsn_applies_the_same_fix(tmp_path):
    pcbnew = _require_pcbnew()
    from commands.freerouting import FreeroutingCommands

    b = _board_with_two_outline_keepout(pcbnew)
    out = tmp_path / "hand.dsn"
    r = FreeroutingCommands(b).export_dsn({"outputPath": str(out)})
    assert r["success"], r
    assert r["keepoutOutlinesAdded"] == 1
    assert len(_keepouts(out.read_text())) == 2
