"""No-connect flags and junctions on a hierarchical child sheet.

A child sheet has no (sheet_instances) block. add_no_connect returned False
there ("No sheet_instances section found"), so batch_add_no_connects failed
for every pin of every part below the root, and sync_junctions skipped the
insert, so no junction a child sheet needed was ever written.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import sexpdata

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.wire_manager import WireManager  # noqa: E402

FONT = "(effects (font (size 1.27 1.27)))"
ROOT = "11111111-1111-1111-1111-111111111111"
SHEET = "22222222-2222-2222-2222-222222222222"
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
R1 = "33333333-3333-3333-3333-333333330000"


def _project(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "p.kicad_sch").write_text(
        f'(kicad_sch (version 20231120) (generator "eeschema") (generator_version "8.0")\n'
        f'  (uuid "{ROOT}")\n  (paper "A4")\n  (lib_symbols)\n'
        f'  (sheet (at 120 90) (size 20 20) (stroke (width 0.1524) (type solid)) (fill (color 0 0 0 0.0000)) (uuid "{SHEET}")\n'
        f'    (property "Sheetname" "Sub" (at 120 89 0) (effects (font (size 1.27 1.27)) (justify left bottom)))\n'
        f'    (property "Sheetfile" "sub.kicad_sch" (at 120 111 0) (effects (font (size 1.27 1.27)) (justify left top)))\n'
        f'    (instances (project "p" (path "/{ROOT}" (page "2"))))\n  )\n'
        f'  (sheet_instances (path "/" (page "1")))\n)\n'
    )
    (d / "sub.kicad_sch").write_text(
        f'(kicad_sch (version 20231120) (generator "eeschema") (generator_version "8.0")\n'
        f'  (uuid "44444444-4444-4444-4444-444444444444")\n  (paper "A4")\n'
        + LIB
        + f"""  (symbol (lib_id "T:R") (at 100 100 0) (unit 1) (in_bom yes) (on_board yes) (dnp no) (uuid "{R1}")
    (property "Reference" "R1" (at 100 97 0) {FONT})
    (property "Value" "10k" (at 100 103 0) {FONT})
    (property "Footprint" "R:R" (at 100 100 0) (effects (font (size 1.27 1.27)) hide))
    (property "Datasheet" "" (at 100 100 0) (effects (font (size 1.27 1.27)) hide))
    (pin "1" (uuid "{R1[:-4]}0001"))
    (pin "2" (uuid "{R1[:-4]}0002"))
    (instances (project "p" (path "/{ROOT}/{SHEET}" (reference "R1") (unit 1))))
  )
)
"""
    )
    (d / "p.kicad_pro").write_text("{}\n")
    return d / "sub.kicad_sch"


def _tags(path: Path, tag: str):
    data = sexpdata.loads(path.read_text())
    return [i for i in data if isinstance(i, list) and i and i[0] == sexpdata.Symbol(tag)]


def test_no_connect_on_a_child_sheet(tmp_path):
    sub = _project(tmp_path / "p")
    assert WireManager.add_no_connect(sub, [98.73, 100]) is True
    assert len(_tags(sub, "no_connect")) == 1


def test_junction_on_a_child_sheet(tmp_path):
    # Three wire ends meet at (110, 110): a T that needs a junction.
    sub = _project(tmp_path / "p")
    data = sexpdata.loads(sub.read_text())
    for x1, y1, x2, y2 in ((100, 110, 110, 110), (110, 110, 120, 110), (110, 110, 110, 120)):
        data.append(WireManager._make_wire_sexp([x1, y1], [x2, y2], 0, "default"))
    added, removed = WireManager.sync_junctions(data)
    assert (added, removed) == (1, 0)
    junctions = [
        i for i in data if isinstance(i, list) and i and i[0] == sexpdata.Symbol("junction")
    ]
    assert len(junctions) == 1


@pytest.mark.integration
def test_kicad_honours_the_child_sheet_no_connect(tmp_path):
    if not shutil.which("kicad-cli"):
        pytest.skip("needs kicad-cli")
    sub = _project(tmp_path / "p")
    root = sub.with_name("p.kicad_sch")

    def unconnected_pins():
        rep = tmp_path / "erc.json"
        subprocess.run(
            ["kicad-cli", "sch", "erc", "--format", "json", "-o", str(rep), str(root)],
            capture_output=True,
        )
        d = json.loads(rep.read_text())
        return sum(
            1
            for s in d.get("sheets", [])
            for v in s.get("violations", [])
            if v.get("type") == "pin_not_connected"
        )

    before = unconnected_pins()
    assert before == 2  # both R1 pins dangle
    assert WireManager.add_no_connect(sub, [98.73, 100])
    assert WireManager.add_no_connect(sub, [101.27, 100])
    assert unconnected_pins() == 0
