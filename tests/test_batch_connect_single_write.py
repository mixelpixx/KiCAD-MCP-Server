"""batch_connect resolves every pin first and writes the schematic once.

Writing per pin re-parsed and re-serialised the whole sheet two or three times
per label. On a real 11,000-line sheet that was about 2.4 s per label, so a
12-pin part ran past the bridge's 30 s timeout; the bridge restarted the worker
mid-batch and only some of the labels were written, while the caller was told
the call had failed.
"""

import sys
from pathlib import Path

import pytest
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


def _netlist_members(tmp_path, sch):
    """{net name: set of (ref, pin)} from kicad-cli's netlist, or None without kicad-cli."""
    import shutil
    import subprocess

    if not shutil.which("kicad-cli"):
        return None
    out = tmp_path / "renet.net"
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
            str(sch),
        ],
        capture_output=True,
        check=True,
    )
    data = sexpdata.loads(out.read_text())
    block = next(x for x in data[1:] if isinstance(x, list) and x[0] == sexpdata.Symbol("nets"))
    members = {}
    for net in block[1:]:
        fields = {str(f[0]): f for f in net if isinstance(f, list)}
        name = str(fields["name"][1]) if "name" in fields else "?"
        nodes = set()
        for node in net:
            if isinstance(node, list) and node and node[0] == sexpdata.Symbol("node"):
                d = {str(f[0]): str(f[1]) for f in node[1:] if isinstance(f, list)}
                nodes.add((d.get("ref"), d.get("pin")))
        members[name] = nodes
    return members


def test_replace_does_not_wire_a_pin_to_a_label_the_batch_renames(tmp_path):
    """#495 review: run 1 puts X on R1.2; run 2 with replace asks R1.2 -> Y and R2.1 -> X.
    R2.1 faces R1.2, whose old X label this same batch replaces with Y. Wiring R2.1 to that
    label (the file is read before the write) shorted R2.1 onto Y. It gets its own X label."""
    f = _sheet(tmp_path)
    c = SchematicBatchCommands(None)
    assert c.batch_connect({"schematicPath": str(f), "connections": {"R1": {"2": "X"}}})["success"]
    r = c.batch_connect(
        {
            "schematicPath": str(f),
            "connections": {"R1": {"2": "Y"}, "R2": {"1": "X"}},
            "replace": True,
        }
    )
    assert r["success"], r
    assert not any("wired to existing label" in p.get("note", "") for p in r["placed"]), r
    assert sorted(str(lbl[1]) for lbl in _items(f, "label")) == ["X", "Y"]
    members = _netlist_members(tmp_path, f)
    if members is not None:
        on_x = next(v for k, v in members.items() if k.endswith("X"))
        on_y = next(v for k, v in members.items() if k.endswith("Y"))
        assert ("R2", "1") in on_x and ("R2", "1") not in on_y, members
        assert ("R1", "2") in on_y and ("R1", "2") not in on_x, members


def test_replace_still_wires_to_a_facing_label_the_batch_keeps(tmp_path):
    """The guard only skips labels at positions this batch clears: R3's label is untouched,
    so R1.2 -> MID with replace still wires to a facing MID label elsewhere when one exists."""
    f = _sheet(tmp_path)
    c = SchematicBatchCommands(None)
    assert c.batch_connect({"schematicPath": str(f), "connections": {"R2": {"1": "MID"}}})[
        "success"
    ]
    r = c.batch_connect(
        {"schematicPath": str(f), "connections": {"R1": {"2": "MID"}}, "replace": True}
    )
    assert r["success"], r
    assert any("wired to existing label" in p.get("note", "") for p in r["placed"]), r


def _label_at(path: Path):
    """{(x, y): [text, ...]} of the local labels in *path*."""
    out: dict = {}
    for lbl in _items(path, "label"):
        at = next(x for x in lbl if isinstance(x, list) and x[0] == sexpdata.Symbol("at"))
        out.setdefault((round(float(at[1]), 2), round(float(at[2]), 2)), []).append(str(lbl[1]))
    return out


def _net_of(members, ref, pin):
    return sorted(k.lstrip("/") for k, v in members.items() if (ref, pin) in v)


@pytest.mark.parametrize("second_stub", [None, 5.08])
def test_replace_removes_an_earlier_runs_stub_wire_and_label(tmp_path, second_stub):
    """#495 review 2026-11-12, item 1: run 1 with stubLength 2.54 puts R1.2 and R3.1 on X
    through stub wires. Run 2 with replace and no stub (or 5.08) moves R1.2 to Y. The old
    stub wire and its X label at (103.81, 100) stayed, so R1.2 was on X and Y at once."""
    f = _sheet(tmp_path)
    c = SchematicBatchCommands(None)
    r = c.batch_connect(
        {
            "schematicPath": str(f),
            "connections": {"R1": {"2": "X"}, "R3": {"1": "X"}},
            "stubLength": 2.54,
        }
    )
    assert r["success"], r
    second = {"schematicPath": str(f), "connections": {"R1": {"2": "Y"}}, "replace": True}
    if second_stub:
        second["stubLength"] = second_stub
    r = c.batch_connect(second)
    assert r["success"], r
    labels = _label_at(f)
    assert (103.81, 100.0) not in labels, labels
    assert labels[(96.19, 130.0)] == ["X"], labels  # R3.1's stub is not in the batch
    y_at = (106.35, 100.0) if second_stub else (101.27, 100.0)
    assert labels[y_at] == ["Y"], labels
    assert len(_items(f, "wire")) == (2 if second_stub else 1)
    members = _netlist_members(tmp_path, f)
    if members is not None:
        assert _net_of(members, "R1", "2") == ["Y"], members
        assert _net_of(members, "R3", "1") == ["X"], members


def test_replace_keeps_a_stub_label_another_wire_still_uses(tmp_path):
    """The far-end label goes only when the stub is its only wire. Here R2.1 was wired to
    R1.2's stub label; replacing R1.2 removes R1.2's stub wire, and X stays on R2.1."""
    f = _sheet(tmp_path)
    c = SchematicBatchCommands(None)
    assert c.batch_connect(
        {"schematicPath": str(f), "connections": {"R1": {"2": "X"}}, "stubLength": 2.54}
    )["success"]
    r = c.batch_connect({"schematicPath": str(f), "connections": {"R2": {"1": "X"}}})
    assert any("wired to existing label" in p.get("note", "") for p in r["placed"]), r
    r = c.batch_connect(
        {"schematicPath": str(f), "connections": {"R1": {"2": "Y"}}, "replace": True}
    )
    assert r["success"], r
    assert _label_at(f) == {(103.81, 100.0): ["X"], (101.27, 100.0): ["Y"]}
    assert len(_items(f, "wire")) == 1
    members = _netlist_members(tmp_path, f)
    if members is not None:
        assert _net_of(members, "R1", "2") == ["Y"], members
        assert _net_of(members, "R2", "1") == ["X"], members


def test_replace_warns_when_it_keeps_a_wire_to_another_pins_label(tmp_path):
    """A wire that ends on another pin is kept (that pin's label stays), but the pin is
    then on both nets; the reply says so instead of staying silent."""
    f = _sheet(tmp_path)
    c = SchematicBatchCommands(None)
    assert c.batch_connect(
        {"schematicPath": str(f), "connections": {"R1": {"2": "X"}, "R2": {"1": "X"}}}
    )["success"]
    r = c.batch_connect(
        {"schematicPath": str(f), "connections": {"R2": {"1": "Y"}}, "replace": True}
    )
    assert r["success"], r
    assert _label_at(f)[(101.27, 100.0)] == ["X"]
    assert len(_items(f, "wire")) == 1
    assert any(w.startswith("R2.1: replace kept the wire") for w in r.get("warnings", [])), r


def test_replace_skips_a_facing_label_the_clear_removes_within_tolerance(tmp_path):
    """#495 review 2026-11-12, item 2: a hand-placed X label 0.23 mm in front of R1.2 is
    removed by the replace clear (0.5 mm), but the "cleared by this batch" check compared
    positions to 0.01 mm, so R2.1 was wired to it and ended on a dangling wire."""
    label = (
        '  (label "X" (at 101.5 100 0) (effects (font (size 1.27 1.27)) (justify left bottom))'
        ' (uuid "77777777-7777-7777-7777-777777770000"))\n'
    )
    f = _sheet(tmp_path, extra=label)
    r = SchematicBatchCommands(None).batch_connect(
        {
            "schematicPath": str(f),
            "connections": {"R1": {"2": "Y"}, "R2": {"1": "X"}},
            "replace": True,
        }
    )
    assert r["success"], r
    assert not any("wired to existing label" in p.get("note", "") for p in r["placed"]), r
    assert _label_at(f) == {(101.27, 100.0): ["Y"], (108.73, 100.0): ["X"]}
    assert _items(f, "wire") == []
    members = _netlist_members(tmp_path, f)
    if members is not None:
        assert _net_of(members, "R2", "1") == ["X"], members
        assert _net_of(members, "R1", "2") == ["Y"], members


def test_replace_clears_the_old_label_of_a_pin_wired_to_another_label(tmp_path):
    """#495 review 2026-11-12, optional item: R2.1 takes the "wired to existing label" branch
    to R1.2's new Y label. Its old Z label was not cleared, so Y and Z became one net and
    R3.1 (on Z) landed on Y."""
    f = _sheet(tmp_path)
    c = SchematicBatchCommands(None)
    assert c.batch_connect(
        {
            "schematicPath": str(f),
            "connections": {"R1": {"2": "X"}, "R2": {"1": "Z"}, "R3": {"1": "Z"}},
        }
    )["success"]
    r = c.batch_connect(
        {
            "schematicPath": str(f),
            "connections": {"R1": {"2": "Y"}, "R2": {"1": "Y"}},
            "replace": True,
        }
    )
    assert r["success"], r
    assert any("wired to existing label" in p.get("note", "") for p in r["placed"]), r
    assert _label_at(f) == {(101.27, 100.0): ["Y"], (98.73, 130.0): ["Z"]}
    members = _netlist_members(tmp_path, f)
    if members is not None:
        assert _net_of(members, "R2", "1") == ["Y"], members
        assert _net_of(members, "R3", "1") == ["Z"], members
