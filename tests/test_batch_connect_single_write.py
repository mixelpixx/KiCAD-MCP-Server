"""batch_connect resolves every pin first and writes the schematic once.

Writing per pin re-parsed and re-serialised the whole sheet two or three times
per label. On a real 11,000-line sheet that was about 2.4 s per label, so a
12-pin part ran past the bridge's 30 s timeout; the bridge restarted the worker
mid-batch and only some of the labels were written, while the caller was told
the call had failed.
"""

import sys
from pathlib import Path

import sexpdata

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from commands.schematic_batch import SchematicBatchCommands  # noqa: E402
from commands.wire_manager import WireManager  # noqa: E402

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


def _sym(ref, uuid, x, y):
    return f"""  (symbol (lib_id "T:R") (at {x} {y} 0) (unit 1) (in_bom yes) (on_board yes) (dnp no) (uuid "{uuid}")
    (property "Reference" "{ref}" (at {x} {y - 3} 0) {FONT})
    (property "Value" "10k" (at {x} {y + 3} 0) {FONT})
    (property "Footprint" "" (at {x} {y} 0) (effects (font (size 1.27 1.27)) hide))
    (property "Datasheet" "" (at {x} {y} 0) (effects (font (size 1.27 1.27)) hide))
    (pin "1" (uuid "{uuid[:-4]}0001"))
    (pin "2" (uuid "{uuid[:-4]}0002"))
    (instances (project "p" (path "/11111111-1111-1111-1111-111111111111" (reference "{ref}") (unit 1))))
  )
"""


def _sheet(tmp_path: Path, extra: str = "") -> Path:
    f = tmp_path / "p.kicad_sch"
    f.write_text(
        '(kicad_sch (version 20231120) (generator "eeschema") (generator_version "8.0")\n'
        '  (uuid "11111111-1111-1111-1111-111111111111")\n  (paper "A4")\n'
        + LIB
        + _sym("R1", "33333333-3333-3333-3333-333333330000", 100, 100)
        + _sym("R2", "44444444-4444-4444-4444-444444440000", 110, 100)
        + _sym("R3", "55555555-5555-5555-5555-555555550000", 100, 130)
        + extra
        + '  (sheet_instances (path "/" (page "1")))\n)\n'
    )
    return f


def _items(path: Path, tag: str):
    data = sexpdata.loads(path.read_text())
    return [i for i in data if isinstance(i, list) and i and i[0] == sexpdata.Symbol(tag)]


def test_one_write_for_the_whole_batch(tmp_path, monkeypatch):
    f = _sheet(tmp_path)
    calls = {"bulk": 0, "single": 0}
    real_bulk = WireManager.add_labels_and_wires

    def bulk(*a, **k):
        calls["bulk"] += 1
        return real_bulk(*a, **k)

    monkeypatch.setattr(WireManager, "add_labels_and_wires", staticmethod(bulk))
    monkeypatch.setattr(
        WireManager,
        "add_label",
        staticmethod(lambda *a, **k: calls.__setitem__("single", calls["single"] + 1) or True),
    )
    r = SchematicBatchCommands(None).batch_connect(
        {
            "schematicPath": str(f),
            "connections": {"R1": {"1": "A"}, "R3": {"1": "B", "2": "C"}},
        }
    )
    assert r["success"], r
    assert calls == {"bulk": 1, "single": 0}
    names = sorted(str(lbl[1]) for lbl in _items(f, "label"))
    assert names == ["A", "B", "C"]


def test_facing_pins_in_one_batch_are_joined_by_a_wire(tmp_path):
    # R1 pin 2 (101.27, 100) faces R2 pin 1 (108.73, 100). The second gets a
    # wire to the first's label, as it did when each label was written at once.
    f = _sheet(tmp_path)
    r = SchematicBatchCommands(None).batch_connect(
        {"schematicPath": str(f), "connections": {"R1": {"2": "MID"}, "R2": {"1": "MID"}}}
    )
    assert r["success"], r
    assert len(_items(f, "label")) == 1
    wires = _items(f, "wire")
    assert len(wires) == 1
    assert any("wired to existing label" in p.get("note", "") for p in r["placed"])


def test_replace_clears_the_old_label(tmp_path):
    f = _sheet(tmp_path)
    c = SchematicBatchCommands(None)
    assert c.batch_connect({"schematicPath": str(f), "connections": {"R3": {"1": "OLD"}}})[
        "success"
    ]
    r = c.batch_connect(
        {"schematicPath": str(f), "connections": {"R3": {"1": "NEW"}}, "replace": True}
    )
    assert r["success"], r
    assert [str(lbl[1]) for lbl in _items(f, "label")] == ["NEW"]


def test_replace_removes_and_inserts_in_the_same_write(tmp_path, monkeypatch):
    # The old labels used to be deleted one write at a time before the bulk
    # write. If that write then failed, the old labels were gone and nothing
    # new was written: a half-applied batch. Now removal rides in the one
    # write, so a failed write leaves the sheet exactly as it was.
    f = _sheet(tmp_path)
    c = SchematicBatchCommands(None)
    assert c.batch_connect({"schematicPath": str(f), "connections": {"R3": {"1": "OLD"}}})[
        "success"
    ]
    before = f.read_text()

    def no_single_delete(*a, **k):
        raise AssertionError("labels must not be deleted outside the bulk write")

    monkeypatch.setattr(WireManager, "delete_label", staticmethod(no_single_delete))
    seen = {}
    real_bulk = WireManager.add_labels_and_wires

    def failing_bulk(path, labels, wires, clear=None, **k):
        seen["clear"] = list(clear or [])
        return False

    monkeypatch.setattr(WireManager, "add_labels_and_wires", staticmethod(failing_bulk))
    r = c.batch_connect(
        {"schematicPath": str(f), "connections": {"R3": {"1": "NEW"}}, "replace": True}
    )
    assert not r["success"] and r["placed"] == [] and len(r["failed"]) == 1
    assert seen["clear"] and seen["clear"][0][0] == "NEW"
    assert f.read_text() == before, "a failed write must leave the old label in place"

    # The same call with the real write: OLD removed and NEW added, one write.
    monkeypatch.setattr(WireManager, "add_labels_and_wires", staticmethod(real_bulk))
    r = c.batch_connect(
        {"schematicPath": str(f), "connections": {"R3": {"1": "NEW"}}, "replace": True}
    )
    assert r["success"], r
    assert [str(lbl[1]) for lbl in _items(f, "label")] == ["NEW"]


def test_replace_rerun_with_a_stub_adds_no_second_wire_or_label(tmp_path):
    # An earlier stub run left the label at the stub end, not on the pin.
    # replace=True clears that too, and the stub wire is not stacked twice.
    f = _sheet(tmp_path)
    c = SchematicBatchCommands(None)
    call = {"schematicPath": str(f), "connections": {"R1": {"1": "LEFT"}}, "stubLength": 2.54}
    assert c.batch_connect(call)["success"]
    r = c.batch_connect(dict(call, replace=True))
    assert r["success"], r
    labels = _items(f, "label")
    assert [str(lbl[1]) for lbl in labels] == ["LEFT"]
    at = next(x for x in labels[0] if isinstance(x, list) and x[0] == sexpdata.Symbol("at"))
    assert (round(float(at[1]), 2), round(float(at[2]), 2)) == (96.19, 100.0)
    assert len(_items(f, "wire")) == 1


def test_facing_planned_label_off_the_pin_axis_gets_its_own_label(tmp_path):
    # R1 pin 2 (101.27, 100) points right; R4 pin 1 (108.73, 108) points left,
    # 10.9 mm away but 8 mm below the axis. Before #500's gate the second pin
    # was wired diagonally to the first's label. Same gate for labels planned
    # earlier in the batch: two labels, no wire.
    f = _sheet(tmp_path, extra=_sym("R4", "66666666-6666-6666-6666-666666660000", 110, 108))
    r = SchematicBatchCommands(None).batch_connect(
        {"schematicPath": str(f), "connections": {"R1": {"2": "MID"}, "R4": {"1": "MID"}}}
    )
    assert r["success"], r
    assert len(_items(f, "label")) == 2
    assert _items(f, "wire") == []
    assert not any("wired to" in p.get("note", "") for p in r["placed"])


def test_bulk_write_matches_single_writes(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = _sheet(tmp_path / "a")
    b = tmp_path / "b" / "p.kicad_sch"
    b.write_text(a.read_text())
    labels = [("X", [90.0, 100.0], "label", 0), ("Y", [90.0, 110.0], "global_label", 180)]
    wires = [([90.0, 100.0], [95.0, 100.0])]
    assert WireManager.add_labels_and_wires(a, labels, wires)
    for text, pos, kind, angle in labels:
        assert WireManager.add_label(b, text, pos, label_type=kind, orientation=angle)
    for start, end in wires:
        assert WireManager.add_wire(b, start, end)

    def shape(p):
        out = []
        for tag in ("label", "global_label", "wire"):
            for item in _items(p, tag):
                out.append(
                    sexpdata.dumps(
                        [
                            x
                            for x in item
                            if not (isinstance(x, list) and x and x[0] == sexpdata.Symbol("uuid"))
                        ]
                    )
                )
        return sorted(out)

    assert shape(a) == shape(b)


def test_failed_write_reports_every_pin_failed(tmp_path, monkeypatch):
    f = _sheet(tmp_path)
    monkeypatch.setattr(WireManager, "add_labels_and_wires", staticmethod(lambda *a, **k: False))
    r = SchematicBatchCommands(None).batch_connect(
        {"schematicPath": str(f), "connections": {"R3": {"1": "B", "2": "C"}}}
    )
    assert not r["success"]
    assert r["placed"] == [] and len(r["failed"]) == 2


def test_stub_puts_the_label_off_the_pin_and_keeps_it_connected(tmp_path):
    import shutil
    import subprocess

    f = _sheet(tmp_path)
    r = SchematicBatchCommands(None).batch_connect(
        {"schematicPath": str(f), "connections": {"R1": {"1": "LEFT"}}, "stubLength": 2.54}
    )
    assert r["success"], r
    # R1 pin 1 is at (98.73, 100) and faces left, so the label moves 2.54 mm further left.
    lbl = _items(f, "label")[0]
    at = next(x for x in lbl if isinstance(x, list) and x[0] == sexpdata.Symbol("at"))
    assert (round(float(at[1]), 2), round(float(at[2]), 2)) == (96.19, 100.0)
    assert len(_items(f, "wire")) == 1
    if shutil.which("kicad-cli"):
        out = tmp_path / "n.net"
        subprocess.run(
            [
                "kicad-cli",
                "sch",
                "export",
                "netlist",
                "--format",
                "kicadsexpr",
                "-o",
                str(out),
                str(f),
            ],
            capture_output=True,
            check=True,
        )
        nets = sexpdata.loads(out.read_text())
        net_block = next(
            x for x in nets[1:] if isinstance(x, list) and x[0] == sexpdata.Symbol("nets")
        )
        on_left = [
            n
            for n in net_block[1:]
            if any(
                isinstance(f, list)
                and f[0] == sexpdata.Symbol("name")
                and str(f[1]).endswith("LEFT")
                for f in n
            )
        ]
        assert on_left, "no LEFT net"
        nodes = [
            {str(f[0]): str(f[1]) for f in node[1:] if isinstance(f, list)}
            for node in on_left[0]
            if isinstance(node, list) and node[0] == sexpdata.Symbol("node")
        ]
        assert {"ref": "R1", "pin": "1"}.items() <= nodes[0].items() if nodes else False
