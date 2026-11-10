"""sync_schematic_to_board takes nets and symbol links from KiCad's own netlist.

The built-in geometric walker disagreed with KiCad wherever a net changes name
across a sheet boundary, and on a real 77-part, 9-sheet board it left 304 of
333 pads on a net KiCad disagrees with, while reporting success.
``utils.kicad_netlist`` reads ``kicad-cli sch export netlist --format
kicadsexpr``, the netlist KiCad's own "Update PCB from Schematic" works from.

Unit tests cover the parser. The real-KiCad tests (``KICAD_USE_REAL_PCBNEW=1``,
kicad-cli on PATH) sync a two-sheet project and use KiCad's own schematic
parity check (``kicad-cli pcb drc --schematic-parity``) as the oracle.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from utils.kicad_netlist import parse_netlist, parse_sexpr  # noqa: E402

# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

SAMPLE = r"""(export (version "E")
  (design (source "p.kicad_sch")
    (sheet (number "1") (name "/") (tstamps "/"))
    (sheet (number "2") (name "/Sub/") (tstamps "/2222/")))
  (components
    (comp (ref "U2") (value "MCU")
      (footprint "Package_QFP:TQFP-32")
      (fields (field (name "MB P/N") "9042001") (field (name "Footprint") "Package_QFP:TQFP-32")
              (field (name "Datasheet")))
      (property (name "Sheetname") (value "Sub"))
      (property (name "Sheetfile") (value "sub.kicad_sch"))
      (property (name "exclude_from_bom"))
      (sheetpath (names "/Sub/") (tstamps "/2222/"))
      (tstamps "4444"))
    (comp (ref "R1") (value "10\"k")
      (footprint "R:R_0603")
      (sheetpath (names "/") (tstamps "/"))
      (tstamps "3333")))
  (nets
    (net (code "1") (name "Net-(U2-ADC7{slash}PB6)") (class "Default")
      (node (ref "U2") (pin "7") (pintype "input"))
      (node (ref "R1") (pin "1") (pintype "passive")))
    (net (code "2") (name "unconnected-(R1-Pad2)") (class "Default")
      (node (ref "R1") (pin "2") (pintype "passive")))))
"""


@pytest.mark.unit
def test_parse_keeps_kicads_escaped_net_names():
    n = parse_netlist(SAMPLE)
    # The XML netlist writes "Net-(U2-ADC7/PB6)"; pcbnew and parity use the escaped name.
    assert n.pad_nets[("U2", "7")] == "Net-(U2-ADC7{slash}PB6)"
    assert n.pad_nets[("R1", "2")] == "unconnected-(R1-Pad2)"
    assert n.net_names == ["Net-(U2-ADC7{slash}PB6)", "unconnected-(R1-Pad2)"]
    assert n.sheets == ["/", "/Sub/"]


@pytest.mark.unit
def test_parse_builds_symbol_paths_fields_and_flags():
    by_ref = {c["reference"]: c for c in parse_netlist(SAMPLE).components}
    assert by_ref["U2"]["path"] == "/2222/4444"
    assert by_ref["R1"]["path"] == "/3333"
    assert by_ref["U2"]["fields"] == {
        "MB P/N": "9042001",
        "Footprint": "Package_QFP:TQFP-32",
        "Datasheet": "",
    }
    assert by_ref["U2"]["exclude_from_bom"] is True and by_ref["U2"]["dnp"] is False
    assert (by_ref["U2"]["sheetname"], by_ref["U2"]["sheetfile"]) == ("Sub", "sub.kicad_sch")
    assert by_ref["R1"]["value"] == '10"k'  # backslash escape undone


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["(export (a)", "(export) (x)", '(export "x', "(a))", "(foo)"])
def test_parse_rejects_malformed_input(bad):
    with pytest.raises(ValueError):
        parse_netlist(bad)


@pytest.mark.unit
def test_parse_sexpr_keeps_parens_inside_strings():
    assert parse_sexpr('(name "PA13(JTMS")') == ["name", "PA13(JTMS"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "written, value",
    [
        (r'"line1\nline2"', "line1\nline2"),
        (r'"a\rb"', "a\rb"),
        (r'"a\tb"', "a\tb"),
        (r'"10\"k"', '10"k'),
        (r'"C:\\new"', "C:\\new"),  # an escaped backslash is not the start of \n
        (r'"\\n"', "\\n"),  # ... so a literal backslash-n stays two characters
        (r'"\q"', "\\q"),  # anything else keeps its backslash, as KiCad's lexer does
    ],
)
def test_parse_sexpr_maps_kicads_escapes_back(written, value):
    """kicad-cli writes "line1\\nline2" for a two-line field; the parser used to
    drop the backslash and return "line1nline2", which the sync then wrote onto
    the footprint, so the field showed as changed on every later sync."""
    assert parse_sexpr(f"(value {written})") == ["value", value]


@pytest.mark.unit
def test_parse_netlist_keeps_multiline_field_values():
    text = SAMPLE.replace('(field (name "Datasheet"))', r'(field (name "Note") "line1\nline2")')
    by_ref = {c["reference"]: c for c in parse_netlist(text).components}
    assert by_ref["U2"]["fields"]["Note"] == "line1\nline2"


# --------------------------------------------------------------------------- #
# Footprint library IDs (unit, fake footprints)
# --------------------------------------------------------------------------- #


class _FPID:
    def __init__(self, lib, name):
        self.lib, self.name = lib, name

    def GetLibNickname(self):
        return self.lib

    def GetLibItemName(self):
        return self.name


class _Footprint:
    """Just enough of pcbnew.FOOTPRINT for _update_footprints_from_symbols."""

    def __init__(self, ref, lib, name):
        self.ref, self.fpid = ref, _FPID(lib, name)
        self.set_fpid_calls = []

    def GetReference(self):
        return self.ref

    def GetValue(self):
        return "10k"

    def GetFPID(self):
        return self.fpid

    def SetFPID(self, fpid):
        self.set_fpid_calls.append(fpid)

    def HasField(self, name):
        return False

    def GetFields(self):
        return []

    def IsFlipped(self):
        return False


def _update(fps, want):
    from commands.schematic_handlers import SchematicHandlersMixin

    board = type("B", (), {"GetFootprints": lambda self: fps})()
    comps = [{"reference": fp.ref, "value": "10k", "footprint": want} for fp in fps]
    return SchematicHandlersMixin._update_footprints_from_symbols(board, comps)


@pytest.mark.unit
def test_footprint_with_no_library_gets_the_symbols_library():
    """What older versions of this tool left behind: ``R_0603`` with no nickname."""
    fp = _Footprint("R1", "", "R_0603_1608Metric")
    updated, pending = _update([fp], "Resistor_SMD:R_0603_1608Metric")
    assert len(fp.set_fpid_calls) == 1
    assert updated == ["R1: library '(none)' -> 'Resistor_SMD'"]
    assert pending == []


@pytest.mark.unit
def test_different_library_same_name_is_a_pending_change_not_a_rewrite():
    """KiCad treats a different library as a footprint change: it reports it and
    swaps the footprint only when "replace footprints" is ticked. Rewriting the
    nickname alone would keep the old library's geometry under the new name."""
    fp = _Footprint("R1", "project_lib", "R_0603_1608Metric")
    updated, pending = _update([fp], "Resistor_SMD:R_0603_1608Metric")
    assert fp.set_fpid_calls == []
    assert updated == []
    assert pending == [
        {
            "reference": "R1",
            "board": "project_lib:R_0603_1608Metric",
            "schematic": "Resistor_SMD:R_0603_1608Metric",
        }
    ]


@pytest.mark.unit
def test_same_library_id_changes_nothing():
    fp = _Footprint("R1", "Resistor_SMD", "R_0603_1608Metric")
    updated, pending = _update([fp], "Resistor_SMD:R_0603_1608Metric")
    assert fp.set_fpid_calls == [] and updated == [] and pending == []


# --------------------------------------------------------------------------- #
# Real KiCad
# --------------------------------------------------------------------------- #

FONT = "(effects (font (size 1.27 1.27)))"
LIB = f"""  (lib_symbols
    (symbol "T:R" (pin_names (offset 0)) (in_bom yes) (on_board yes)
      (property "Reference" "R" (at 0 2.54 0) {FONT})
      (property "Value" "R" (at 0 -2.54 0) {FONT})
      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))
      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))
      (symbol "R_1_1"
        (pin passive line (at -1.27 0 0) (length 0) (name "~" {FONT}) (number "1" {FONT}))
        (pin passive line (at 1.27 0 180) (length 0) (name "~" {FONT}) (number "2" {FONT}))
      )
    )
  )
"""
ROOT = "11111111-1111-1111-1111-111111111111"
SHEET = "22222222-2222-2222-2222-222222222222"
R1 = "33333333-3333-3333-3333-333333330000"
R2 = "44444444-4444-4444-4444-444444440000"
FP = "Resistor_SMD:R_0603_1608Metric"


def _symbol(ref, uuid, path, value="10k"):
    return f"""  (symbol (lib_id "T:R") (at 100 100 0) (unit 1) (in_bom yes) (on_board yes) (dnp no) (uuid "{uuid}")
    (property "Reference" "{ref}" (at 100 97 0) {FONT})
    (property "Value" "{value}" (at 100 103 0) {FONT})
    (property "Footprint" "{FP}" (at 100 100 0) (effects (font (size 1.27 1.27)) hide))
    (property "Datasheet" "" (at 100 100 0) (effects (font (size 1.27 1.27)) hide))
    (property "MPN" "RC0603FR-0710KL" (at 100 100 0) (effects (font (size 1.27 1.27)) hide))
    (pin "1" (uuid "{uuid[:-4]}0001"))
    (pin "2" (uuid "{uuid[:-4]}0002"))
    (instances (project "p" (path "{path}" (reference "{ref}") (unit 1))))
  )
"""


def _project(d: Path) -> Path:
    """Two sheets; one net changes name at the boundary.

    Root: R1 pin 2, wire with local label "CANH" placed mid-wire, sheet pin
    "CAN_H". Sub: hierarchical label "CAN_H" on R2 pin 1. KiCad joins R1.2 and
    R2.1 into one net, "/CANH".
    """
    import pcbnew

    root = f"""(kicad_sch (version 20231120) (generator "eeschema") (generator_version "8.0")
  (uuid "{ROOT}")
  (paper "A4")
{LIB}  (wire (pts (xy 101.27 100) (xy 120 100)) (stroke (width 0) (type default)) (uuid "55555555-5555-5555-5555-555555555501"))
  (label "CANH" (at 105 100 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "55555555-5555-5555-5555-555555555502"))
{_symbol("R1", R1, "/" + ROOT)}  (sheet (at 120 90) (size 20 20) (stroke (width 0.1524) (type solid)) (fill (color 0 0 0 0.0000)) (uuid "{SHEET}")
    (property "Sheetname" "Sub" (at 120 89 0) (effects (font (size 1.27 1.27)) (justify left bottom)))
    (property "Sheetfile" "sub.kicad_sch" (at 120 111 0) (effects (font (size 1.27 1.27)) (justify left top)))
    (pin "CAN_H" input (at 120 100 180) (effects (font (size 1.27 1.27)) (justify left)) (uuid "55555555-5555-5555-5555-555555555503"))
    (instances (project "p" (path "/{ROOT}" (page "2"))))
  )
  (sheet_instances (path "/" (page "1")))
)
"""
    sub = f"""(kicad_sch (version 20231120) (generator "eeschema") (generator_version "8.0")
  (uuid "66666666-6666-6666-6666-666666666666")
  (paper "A4")
{LIB}  (hierarchical_label "CAN_H" (shape input) (at 98.73 100 180) (effects (font (size 1.27 1.27)) (justify right)) (uuid "55555555-5555-5555-5555-555555555504"))
{_symbol("R2", R2, "/" + ROOT + "/" + SHEET, value="22k")})
"""
    d.mkdir(parents=True, exist_ok=True)
    (d / "p.kicad_sch").write_text(root)
    (d / "sub.kicad_sch").write_text(sub)
    (d / "p.kicad_pro").write_text("{}\n")

    # A board laid out before: R1 and R2 placed, no nets, no symbol links,
    # R2 still at an old value and both missing the library nickname.
    fp_dir = next(
        (
            Path(os.environ[v])
            for v in ("KICAD10_FOOTPRINT_DIR", "KICAD9_FOOTPRINT_DIR")
            if v in os.environ
        ),
        Path("/usr/share/kicad/footprints"),
    )
    if not (fp_dir / "Resistor_SMD.pretty").is_dir():
        pytest.skip(f"no KiCad footprint library at {fp_dir} (set KICAD10_FOOTPRINT_DIR)")
    board = pcbnew.BOARD()
    for ref, x in (("R1", 10), ("R2", 20)):
        fp = pcbnew.FootprintLoad(str(fp_dir / "Resistor_SMD.pretty"), "R_0603_1608Metric")
        fp.SetReference(ref)
        fp.SetValue("10k" if ref == "R1" else "18k")
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(10)))
        board.Add(fp)
    for x1, y1, x2, y2 in ((0, 0, 30, 0), (30, 0, 30, 20), (30, 20, 0, 20), (0, 20, 0, 0)):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
        s.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x2), pcbnew.FromMM(y2)))
        board.Add(s)
    board_path = d / "p.kicad_pcb"
    pcbnew.SaveBoard(str(board_path), board)
    return board_path


def _require_kicad():
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1" or not shutil.which("kicad-cli"):
        pytest.skip("needs KICAD_USE_REAL_PCBNEW=1 and kicad-cli")


def _sync(board_path: Path, **extra):
    from kicad_interface import KiCADInterface

    iface = KiCADInterface()
    handlers = getattr(iface, "schematic_handlers", iface)
    return handlers._handle_sync_schematic_to_board(
        {
            "schematicPath": str(board_path.with_suffix(".kicad_sch")),
            "boardPath": str(board_path),
            **extra,
        }
    )


def _parity(board_path: Path):
    rep = board_path.with_suffix(".parity.json")
    subprocess.run(
        [
            "kicad-cli",
            "pcb",
            "drc",
            "--schematic-parity",
            "--format",
            "json",
            "-o",
            str(rep),
            str(board_path),
        ],
        capture_output=True,
        check=True,
    )
    return json.loads(rep.read_text()).get("schematic_parity", [])


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_sync_matches_kicads_netlist_and_parity_is_clean(tmp_path, monkeypatch):
    _require_kicad()
    monkeypatch.setenv("KICAD_SKIP_SYMBOL_WARMUP", "1")
    import pcbnew

    board_path = _project(tmp_path / "p")
    r = _sync(board_path)
    assert r["success"], r
    assert r["netSource"] == "kicad-cli"

    board = pcbnew.LoadBoard(str(board_path))
    pads = {
        (fp.GetReference(), str(p.GetNumber())): p.GetNetname()
        for fp in board.GetFootprints()
        for p in fp.Pads()
    }
    # One net across the sheet boundary, named as KiCad names it.
    assert pads[("R1", "2")] == pads[("R2", "1")] == "/CANH"
    assert pads[("R1", "1")] == "unconnected-(R1-Pad1)"
    paths = {fp.GetReference(): fp.GetPath().AsString() for fp in board.GetFootprints()}
    assert paths == {"R1": f"/{R1}", "R2": f"/{SHEET}/{R2}"}
    assert sorted(r["footprints_linked"]) == ["R1", "R2"]
    values = {fp.GetReference(): fp.GetValue() for fp in board.GetFootprints()}
    assert values["R2"] == "22k"
    assert any("MPN" in u for u in r["footprints_updated"])
    # A field the sync creates is hidden on Fab, not printed on the silkscreen.
    for fp in board.GetFootprints():
        for f in fp.GetFields():
            if not (f.IsReference() or f.IsValue()) and f.GetName() in ("MPN", "MB P/N"):
                assert not f.IsVisible(), (fp.GetReference(), f.GetName())
                assert f.GetLayer() in (pcbnew.F_Fab, pcbnew.B_Fab), (
                    fp.GetReference(),
                    f.GetName(),
                )

    assert _parity(board_path) == []  # KiCad agrees with every pad, field and link


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_dry_run_reports_the_changes_and_saves_nothing(tmp_path, monkeypatch):
    _require_kicad()
    monkeypatch.setenv("KICAD_SKIP_SYMBOL_WARMUP", "1")

    board_path = _project(tmp_path / "p")
    before = board_path.read_bytes()
    preview = _sync(board_path, dryRun=True)
    assert preview["success"], preview
    assert preview["dryRun"] is True
    assert preview["message"].startswith("Preview only, nothing saved")
    assert board_path.read_bytes() == before  # not one byte written

    applied = _sync(board_path)
    assert applied["dryRun"] is False
    # The preview lists exactly what the real sync then does.
    for key in ("pads_changed", "footprints_updated", "footprints_linked", "nets_added"):
        assert preview[key] == applied[key], key
    assert "R1/2: '' -> '/CANH'" in applied["pads_changed"]

    again = _sync(board_path, dryRun=True)  # an up-to-date board has nothing to change
    assert again["pads_changed"] == [] and again["footprints_updated"] == []
    assert again["pads_assigned"] == applied["pads_assigned"] > 0


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_dry_run_through_handle_command_leaves_the_file_and_the_loaded_board(tmp_path, monkeypatch):
    """The MCP layer auto-saves after sync_schematic_to_board. open_project, move
    a footprint without saving, then preview: the file must not be rewritten
    with the move, no backup may appear, and the loaded board keeps the move."""
    _require_kicad()
    monkeypatch.setenv("KICAD_SKIP_SYMBOL_WARMUP", "1")
    import pcbnew
    from kicad_interface import KiCADInterface

    board_path = _project(tmp_path / "p")
    iface = KiCADInterface()
    opened = iface.handle_command(
        "open_project", {"filename": str(board_path.with_suffix(".kicad_pro"))}
    )
    assert opened["success"], opened
    moved_to = pcbnew.VECTOR2I(pcbnew.FromMM(15), pcbnew.FromMM(15))
    iface.board.FindFootprintByReference("R1").SetPosition(moved_to)  # unsaved edit
    before = board_path.read_bytes()

    preview = iface.handle_command(
        "sync_schematic_to_board",
        {"schematicPath": str(board_path.with_suffix(".kicad_sch")), "dryRun": True},
    )
    assert preview["success"], preview
    assert preview["dryRun"] is True
    assert "R1/2: '' -> '/CANH'" in preview["pads_changed"]
    assert board_path.read_bytes() == before, "the preview saved the board"
    assert not (board_path.parent / ".mcp-backups").exists(), "the preview made a backup"
    assert "autoSave" not in preview
    assert iface.board.FindFootprintByReference("R1").GetPosition() == moved_to
    # Nothing in memory was synced either: the loaded board still has no nets.
    assert iface.board.FindFootprintByReference("R1").FindPadByNumber("2").GetNetname() == ""

    applied = iface.handle_command(
        "sync_schematic_to_board",
        {"schematicPath": str(board_path.with_suffix(".kicad_sch"))},
    )
    assert applied["success"] and applied["dryRun"] is False, applied
    assert board_path.read_bytes() != before
    assert preview["pads_changed"] == applied["pads_changed"]


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_fallback_without_kicad_cli_says_so(tmp_path, monkeypatch):
    _require_kicad()
    monkeypatch.setenv("KICAD_SKIP_SYMBOL_WARMUP", "1")
    from kicad_interface import KiCADInterface as cls

    board_path = _project(tmp_path / "p")
    monkeypatch.setattr(cls, "_find_kicad_cli_static", staticmethod(lambda: None))
    monkeypatch.setattr(
        cls, "_build_hierarchical_pad_net_map", lambda self, path, sheets_out=None: ({}, [])
    )
    r = _sync(board_path)
    assert r["success"], r
    assert r["netSource"] == "built-in"
    assert any("built-in walker" in w for w in r["warnings"])
