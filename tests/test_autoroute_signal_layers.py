"""signalLayers keeps tracks off plane layers through Freerouting's own layer switch.

KiCad exports every copper layer as (type signal), so Freerouting ran long tracks across
the inner planes of a 4-layer board and cut In2 into 7 islands. `signalLayers` writes a
rules file (-dr) whose autoroute_settings mark the other layers inactive.

A board-sized wire_keepout was tried first and is the wrong tool: Freerouting 2.5's fanout
stage runs but DrillPage excludes the keepout area from its via candidates, so no via at all
is placed (same DSN, 3 passes: 0 vias / 111 unrouted with the keepout; fanout escaped
244/304 pins without it). With the rules file In1 off: 80 vias, In2 used, no In1 tracks.

The rules file holds only what was asked for: (active off) for the restricted layers and
trace costs for the layers in layerTraceCosts. Freerouting reads each key on its own, and an
explicit value replaces the per-layer default it computes from the board (preferred
directions from the aspect ratio, the outer-layer surcharge), so nothing else is written.
"""

import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from commands import freerouting as fr_mod
from commands.freerouting import (
    FreeroutingCommands,
    _board_layer_names,
    _build_freerouting_cmd,
    _dsn_layer_names,
    _signal_layer_rules,
)

DSN = """(pcb "b.dsn"
  (resolution um 10)
  (unit um)
  (structure
    (layer F.Cu
      (type signal)
      (property
        (index 0)
      )
    )
    (layer In1.Cu
      (type signal)
      (property
        (index 1)
      )
    )
    (layer In2.Cu
      (type signal)
      (property
        (index 2)
      )
    )
    (layer B.Cu
      (type signal)
      (property
        (index 3)
      )
    )
    (boundary
      (path pcb 0  100 -100  200 -100  200 -200  100 -200  100 -100)
    )
  )
  (placement
  )
)
"""

# A renamed board: F.Cu is "Top", In1.Cu is "GND plane" (quoted by KiCad), B.Cu is "Bottom-side".
RENAMED = (
    DSN.replace("(layer F.Cu", "(layer Top")
    .replace("(layer In1.Cu", '(layer "GND plane"')
    .replace("(layer B.Cu", '(layer "Bottom-side"')
)


def test_rules_hold_only_the_restricted_layers():
    text, restricted = _signal_layer_rules(DSN, ["F.Cu", "In2.Cu", "B.Cu"])
    assert restricted == ["In1.Cu"]
    assert text == (
        '(rules PCB "kicad-mcp"\n'
        "  (autoroute_settings\n"
        "    (layer_rule In1.Cu (active off))\n"
        "  )\n"
        ")\n"
    )
    # nothing about the other layers, and no top-level cost settings
    for word in ("F.Cu", "In2.Cu", "B.Cu", "via_costs", "preferred_direction", "keepout"):
        assert word not in text


def test_nothing_to_restrict():
    assert _signal_layer_rules(DSN, ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]) == (None, [])
    assert _signal_layer_rules(DSN, []) == (None, [])


def test_an_unknown_layer_is_refused_not_ignored():
    # A typo must neither switch off every layer nor be dropped quietly.
    with pytest.raises(ValueError, match="Top"):
        _signal_layer_rules(DSN, ["Top"])
    with pytest.raises(ValueError, match="In3.Cu"):
        _signal_layer_rules(DSN, ["F.Cu", "In3.Cu"])
    with pytest.raises(ValueError, match="In9.Cu"):
        _signal_layer_rules(DSN, [], {"In9.Cu": 5})


def test_quoted_layer_names_are_read_and_written_quoted():
    assert _dsn_layer_names(RENAMED) == ["Top", "GND plane", "In2.Cu", "Bottom-side"]
    text, restricted = _signal_layer_rules(RENAMED, ["Top", "In2.Cu", "Bottom-side"])
    assert restricted == ["GND plane"]
    assert '(layer_rule "GND plane" (active off))' in text
    text, restricted = _signal_layer_rules(
        RENAMED, ["Top", "In2.Cu", "Bottom-side"], {"Bottom-side": 3}
    )
    assert restricted == ["GND plane"]
    assert '(layer_rule "Bottom-side" (preferred_direction_trace_costs 3)' in text


def test_dsn_layer_names_stop_at_the_end_of_structure():
    assert _dsn_layer_names(DSN) == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    assert _dsn_layer_names("(pcb x (placement))") == []


def test_rules_file_is_passed_to_freerouting(tmp_path, monkeypatch):
    monkeypatch.setattr(fr_mod, "_find_java", lambda *_: "java")
    cmd = _build_freerouting_cmd(
        "fr.jar", "/x/b.dsn", "/x/b.ses", 5, False, rules_path="/x/b.rules"
    )
    assert cmd[cmd.index("-dr") + 1] == "/x/b.rules"
    cmd = _build_freerouting_cmd("fr.jar", "/x/b.dsn", "/x/b.ses", 5, False)
    assert "-dr" not in cmd


def test_trace_costs_keep_a_layer_but_price_it():
    text, restricted = _signal_layer_rules(DSN, ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"], {"In1.Cu": 5})
    assert restricted == []
    assert text == (
        '(rules PCB "kicad-mcp"\n'
        "  (autoroute_settings\n"
        "    (layer_rule In1.Cu (preferred_direction_trace_costs 5)"
        " (against_preferred_direction_trace_costs 10))\n"
        "  )\n"
        ")\n"
    )


def test_costs_without_signal_layers_and_with_restriction():
    text, restricted = _signal_layer_rules(DSN, [], {"In2.Cu": 3})
    assert restricted == [] and "(preferred_direction_trace_costs 3)" in text
    text, restricted = _signal_layer_rules(DSN, ["F.Cu", "In2.Cu", "B.Cu"], {"In2.Cu": 3})
    assert restricted == ["In1.Cu"]
    assert "(layer_rule In1.Cu (active off))" in text
    assert "(layer_rule In2.Cu (preferred_direction_trace_costs 3)" in text
    assert "(layer_rule F.Cu" not in text and "(layer_rule B.Cu" not in text


# --- translating names through the board ----------------------------------------------------


def _renamed_board():
    """A mock of a 4-layer board whose F.Cu is called Top, as pcbnew answers."""
    ids = {"F.Cu": 0, "Top": 0, "B.Cu": 2, "Bottom-side": 2, "In1.Cu": 4, "GND plane": 4}
    ids["In2.Cu"] = 6
    ids["In3.Cu"] = 8  # KiCad resolves a canonical name even when the layer is not enabled
    ids["Edge.Cuts"] = 25
    names = {0: "Top", 2: "Bottom-side", 4: "GND plane", 6: "In2.Cu", 8: "In3.Cu", 25: "Edge.Cuts"}
    board = MagicMock(name="board")
    board.GetLayerID.side_effect = lambda n: ids.get(n, -1)
    board.GetLayerName.side_effect = lambda lid: names[lid]
    board.GetEnabledLayers.return_value.CuStack.return_value = [0, 4, 6, 2]
    return board


def test_canonical_names_become_the_boards_names():
    pcb = MagicMock(name="pcbnew")
    pcb.IsCopperLayer.side_effect = lambda lid: lid < 25
    with patch.dict(sys.modules, {"pcbnew": pcb}):
        board = _renamed_board()
        assert _board_layer_names(board, ["F.Cu", "In2.Cu", "B.Cu"]) == [
            "Top",
            "In2.Cu",
            "Bottom-side",
        ]
        assert _board_layer_names(board, ["Top", "In1.Cu", "GND plane"]) == [
            "Top",
            "GND plane",
            "GND plane",
        ]
        for bad in ("Nope", "In3.Cu", "Edge.Cuts"):
            with pytest.raises(ValueError, match="not a copper layer"):
                _board_layer_names(board, ["F.Cu", bad])


# --- through autoroute ----------------------------------------------------------------------


def _cmds(board, board_path):
    cc = FreeroutingCommands.__new__(FreeroutingCommands)
    board.GetFileName.return_value = str(board_path)
    board.Save.return_value = None
    tracks = MagicMock()
    tracks.__iter__ = lambda s: iter([])
    board.GetTracks.return_value = tracks
    cc.board = board
    cc._resolve_execution_mode = MagicMock(return_value={"mode": "direct", "use_docker": False})
    cc._apply_project_net_classes = MagicMock(return_value={"applied": []})
    return cc


def _run_autoroute(tmp_path, params, dsn_text=RENAMED):
    (tmp_path / "test.kicad_pcb").write_text("(kicad_pcb)\n")
    jar = tmp_path / "freerouting.jar"
    jar.write_text("not a real jar")
    cc = _cmds(_renamed_board(), tmp_path / "test.kicad_pcb")
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        if "-dr" in cmd:
            seen["rules"] = Path(cmd[cmd.index("-dr") + 1]).read_text()
        Path(cmd[cmd.index("-do") + 1]).write_text(
            '(net "N0"\n  (wire (path Top 200 0 0 1 1))\n)\n'
        )
        return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

    pcb = MagicMock(name="pcbnew")
    pcb.IsCopperLayer.side_effect = lambda lid: lid < 25

    def fake_export(_board, dsn_path, *_a, **_k):
        Path(dsn_path).write_text(dsn_text)
        return True

    pcb.ExportSpecctraDSN.side_effect = fake_export
    pcb.ImportSpecctraSES.return_value = True
    with patch.object(fr_mod, "subprocess") as sp, patch.dict(sys.modules, {"pcbnew": pcb}):
        sp.run.side_effect = fake_run
        sp.TimeoutExpired = TimeoutError
        with patch.object(fr_mod, "preserve_project_settings", create=True) as pps:
            pps.return_value.__enter__ = lambda *a: None
            pps.return_value.__exit__ = lambda *a: False
            out = cc.autoroute(
                {
                    "boardPath": str(tmp_path / "test.kicad_pcb"),
                    "freeroutingJar": str(jar),
                    "maxPasses": 3,
                    **params,
                }
            )
    return out, seen


@pytest.mark.unit
def test_autoroute_translates_names_and_reports_board_names(tmp_path):
    out, seen = _run_autoroute(tmp_path, {"signalLayers": ["F.Cu", "In2.Cu", "B.Cu"]})
    assert out["success"], out
    assert out["tracksKeptOffLayers"] == ["GND plane"]  # the board's name, not In1.Cu
    # named after the DSN file, which is what Freerouting checks the header against
    assert seen["rules"] == (
        "(rules PCB test\n  (autoroute_settings\n"
        '    (layer_rule "GND plane" (active off))\n  )\n)\n'
    )
    out, seen = _run_autoroute(tmp_path, {"layerTraceCosts": {"In1.Cu": 4}})
    assert out["success"], out
    assert out["layerTraceCosts"] == {"GND plane": 4.0}
    assert '(layer_rule "GND plane" (preferred_direction_trace_costs 4)' in seen["rules"]


@pytest.mark.unit
def test_autoroute_refuses_a_name_the_board_lacks(tmp_path):
    out, seen = _run_autoroute(tmp_path, {"signalLayers": ["F.Cu", "In3.Cu"]})
    assert out["success"] is False
    assert "In3.Cu" in out["errorDetails"]
    assert "cmd" not in seen  # Freerouting never ran
    out, seen = _run_autoroute(tmp_path, {"layerTraceCosts": {"Inner1": 2}})
    assert out["success"] is False and "Inner1" in out["errorDetails"]


@pytest.mark.unit
def test_autoroute_without_layer_params_writes_no_rules_file(tmp_path):
    out, seen = _run_autoroute(tmp_path, {})
    assert out["success"], out
    assert "-dr" not in seen["cmd"] and out["tracksKeptOffLayers"] == []


# --- against KiCad's own export -------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.real_pcbnew
def test_real_board_with_renamed_layers(tmp_path):
    if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
        pytest.skip("needs KICAD_USE_REAL_PCBNEW=1")
    pcbnew = pytest.importorskip("pcbnew")

    b = pcbnew.BOARD()
    b.SetCopperLayerCount(4)
    b.SetLayerName(pcbnew.F_Cu, "Top")
    b.SetLayerName(pcbnew.In1_Cu, "GND plane")
    mm = pcbnew.FromMM
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
    dsn = tmp_path / "b.dsn"
    pcbnew.ExportSpecctraDSN(b, str(dsn))
    text = dsn.read_text()
    assert _dsn_layer_names(text) == ["Top", "GND plane", "In2.Cu", "B.Cu"]
    assert _board_layer_names(b, ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]) == [
        "Top",
        "GND plane",
        "In2.Cu",
        "B.Cu",
    ]
    with pytest.raises(ValueError):
        _board_layer_names(b, ["In3.Cu"])  # a layer the board does not have enabled
    rules, restricted = _signal_layer_rules(
        text, _board_layer_names(b, ["F.Cu", "In2.Cu", "B.Cu"]), None
    )
    assert restricted == ["GND plane"]
    assert '(layer_rule "GND plane" (active off))' in rules
