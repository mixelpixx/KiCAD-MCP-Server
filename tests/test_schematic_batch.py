"""
Unit tests for batch schematic authoring commands (commands/schematic_batch.py).

Pure helpers are tested directly; handlers are tested for parameter validation and
orchestration with the heavy dependencies (DynamicSymbolLoader / PinLocator /
WireManager / interface handlers) stubbed, so no real KiCad install is needed.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from kicad_mcp.commands import schematic_batch as sb  # noqa: E402
from kicad_mcp.commands.schematic_batch import (  # noqa: E402
    SchematicBatchCommands,
    _bbox_from_pins,
    _field_positions_for_pins,
    _find_facing_label,
    _find_project_root,
    _snap,
)


class TestHelpers:
    def test_snap(self):
        # 1.27mm (50-mil) grid
        assert _snap(1.27) == 1.27
        assert _snap(2.54) == 2.54
        assert _snap(0.6) == 0.0  # rounds down to 0
        assert _snap(2.0) == 2.54  # nearest grid point

    def test_find_project_root(self, tmp_path):
        (tmp_path / "proj.kicad_pro").write_text("{}")
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        assert _find_project_root(sub) == tmp_path.resolve()

    def test_find_project_root_fallback(self, tmp_path):
        sub = tmp_path / "x"
        sub.mkdir()
        assert _find_project_root(sub) == sub  # no .kicad_pro anywhere -> start dir

    def test_find_facing_label(self, tmp_path):
        f = tmp_path / "s.kicad_sch"
        # A label "VBUS" at (10,20) angle 0; a pin at (24,20) facing it needs orientation 180.
        f.write_text('(kicad_sch (label "VBUS" (at 10 20 0)))')
        assert _find_facing_label(f, "VBUS", [12, 20], orientation=180) == [10.0, 20.0]
        # Wrong net -> None
        assert _find_facing_label(f, "GND", [12, 20], orientation=180) is None
        # Too far -> None
        assert _find_facing_label(f, "VBUS", [100, 200], orientation=180) is None

    def test_field_positions_two_pin_vertical(self):
        # pins stacked vertically -> labels go left/right
        pins = {"1": [0, 5], "2": [0, -5]}
        fp = _field_positions_for_pins(0, 0, pins)
        names = {n for n, *_ in fp}
        assert names == {"Reference", "Value"}
        ref = next(p for p in fp if p[0] == "Reference")
        assert ref[1] != 0  # x offset (left/right), y unchanged

    def test_field_positions_two_pin_horizontal(self):
        pins = {"1": [-5, 0], "2": [5, 0]}
        fp = _field_positions_for_pins(0, 0, pins)
        ref = next(p for p in fp if p[0] == "Reference")
        assert ref[1] == 0 and ref[2] != 0  # above/below

    def test_bbox_from_pins(self):
        bb = _bbox_from_pins({"1": [0, 0], "2": [10, 4]}, 5, 2)
        assert bb["x_min"] == -1.27 and bb["x_max"] == 11.27

    def test_bbox_from_pins_fallback(self):
        bb = _bbox_from_pins({}, 5, 5)
        assert bb == {"x_min": 2.46, "y_min": 2.46, "x_max": 7.54, "y_max": 7.54}


class TestParamValidation:
    def setup_method(self):
        self.c = SchematicBatchCommands(types.SimpleNamespace())

    def test_validation(self):
        assert self.c.batch_add_components({})["success"] is False
        assert (
            self.c.batch_add_components({"schematicPath": "/x"})["success"] is False
        )  # no components
        assert self.c.batch_edit_schematic_components({"schematicPath": "/x"})["success"] is False
        assert (
            self.c.replace_schematic_component({"schematicPath": "/x", "reference": "R1"})[
                "success"
            ]
            is False
        )
        assert self.c.batch_add_no_connects({"schematicPath": "/x"})["success"] is False
        assert self.c.batch_connect({"schematicPath": "/x"})["success"] is False
        assert self.c.batch_add_and_connect({"schematicPath": "/x"})["success"] is False


class TestBatchEdit:
    def test_aggregates_results(self):
        calls = []

        def fake_edit(params):
            calls.append(params)
            ref = params["reference"]
            if ref == "BAD":
                return {"success": False, "message": "nope"}
            return {"success": True, "updated": {"value": params.get("value")}}

        iface = types.SimpleNamespace(_handle_edit_schematic_component=fake_edit)
        c = SchematicBatchCommands(iface)
        r = c.batch_edit_schematic_components(
            {
                "schematicPath": "/x.kicad_sch",
                "components": {"R1": {"value": "10k"}, "BAD": {"value": "x"}},
            }
        )
        assert r["updated_count"] == 1
        assert r["error_count"] == 1
        assert r["success"] is False
        # sub-handler received merged params
        assert any(c_["reference"] == "R1" and c_["value"] == "10k" for c_ in calls)


class TestBatchAddNoConnects:
    def test_happy_and_fallback(self, monkeypatch):
        fake_loc = types.SimpleNamespace(
            get_pin_location=lambda p, ref, pin: [10.0, 20.0] if pin == "1" else None,
            get_all_symbol_pins=lambda p, ref: {"1": [10.0, 20.0]},  # single-pin fallback
        )
        added = []
        fake_wm = types.SimpleNamespace(add_no_connect=lambda p, loc: added.append(loc) or True)
        monkeypatch.setattr(sb, "PinLocator", lambda: fake_loc)
        monkeypatch.setattr(sb, "WireManager", fake_wm)

        c = SchematicBatchCommands(types.SimpleNamespace())
        r = c.batch_add_no_connects(
            {
                "schematicPath": "/x.kicad_sch",
                "pins": [
                    {"componentRef": "U1", "pinName": "1"},
                    {"componentRef": "TP1", "pinName": "9"},
                ],
            }
        )
        assert r["success"] is True  # both succeed (2nd via single-pin fallback)
        assert len(r["placed"]) == 2
        assert len(added) == 2


class TestBatchConnect:
    def test_places_label(self, monkeypatch, tmp_path):
        f = tmp_path / "x.kicad_sch"
        f.write_text("(kicad_sch)")
        fake_loc = types.SimpleNamespace(
            get_pin_location=lambda p, ref, pin: [10.0, 20.0],
            get_pin_angle=lambda p, ref, pin: 0,
            get_all_symbol_pins=lambda p, ref: {"1": [10.0, 20.0]},
        )
        labels = []
        fake_wm = types.SimpleNamespace(
            add_label=lambda p, net, pos, label_type="label", orientation=0: labels.append(
                (net, orientation)
            )
            or True,
            add_wire=lambda *a: True,
            delete_label=lambda *a, **k: True,
        )
        monkeypatch.setattr(sb, "PinLocator", lambda: fake_loc)
        monkeypatch.setattr(sb, "WireManager", fake_wm)
        monkeypatch.setattr(sb, "_find_facing_label", lambda *a, **k: None)

        c = SchematicBatchCommands(types.SimpleNamespace())
        r = c.batch_connect({"schematicPath": str(f), "connections": {"R1": {"1": "SDA"}}})
        assert r["success"] is True
        assert len(r["placed"]) == 1
        assert labels == [("SDA", 180)]  # pin angle 0 -> label orientation 180


class TestBatchAddAndConnect:
    def test_splits_nets_and_orchestrates(self):
        c = SchematicBatchCommands(types.SimpleNamespace())
        add_args = {}
        conn_args = {}

        def fake_add(params):
            add_args.update(params)
            return {
                "added_count": 1,
                "added": [{"reference": "R1"}],
                "errors": [],
                "placement_bbox": None,
            }

        def fake_connect(params):
            conn_args.update(params)
            return {"placed": [{"ref": "R1", "pin": "1", "net": "VCC"}], "failed": []}

        c.batch_add_components = fake_add
        c.batch_connect = fake_connect

        r = c.batch_add_and_connect(
            {
                "schematicPath": "/x.kicad_sch",
                "components": [{"symbol": "Device:R", "reference": "R1", "nets": {"1": "VCC"}}],
            }
        )
        assert r["success"] is True
        assert r["added_count"] == 1
        assert r["connected_count"] == 1
        # 'nets' stripped from the components passed to batch_add_components
        assert "nets" not in add_args["components"][0]
        # nets routed to batch_connect keyed by reference
        assert conn_args["connections"] == {"R1": {"1": "VCC"}}
