"""signalLayers keeps tracks off plane layers through Freerouting's own layer switch.

KiCad exports every copper layer as (type signal), so Freerouting ran long tracks across
the inner planes of a 4-layer board and cut In2 into 7 islands. `signalLayers` writes a
rules file (-dr) whose autoroute_settings mark the other layers inactive.

A board-sized wire_keepout was tried first and is the wrong tool: Freerouting 2.5 then
skips its fanout stage and places no vias at all (same DSN, 3 passes: 0 vias / 111
unrouted with the keepout; fanout escaped 244/304 pins without it). With the rules file
In1 off: 80 vias, In2 used, no In1 tracks.
"""

from commands.freerouting import _build_freerouting_cmd, _signal_layer_rules

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


def test_rules_switch_off_the_other_layers_only():
    text, restricted = _signal_layer_rules(DSN, ["F.Cu", "In2.Cu", "B.Cu"])
    assert restricted == ["In1.Cu"]
    assert "(layer_rule In1.Cu (active off)" in text
    for name in ("F.Cu", "In2.Cu", "B.Cu"):
        assert f"(layer_rule {name} (active on)" in text
    assert "(vias on)" in text
    assert text.startswith("(rules PCB") and text.count("(") == text.count(")")
    assert "keepout" not in text


def test_nothing_to_restrict():
    assert _signal_layer_rules(DSN, ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]) == (None, [])
    assert _signal_layer_rules(DSN, []) == (None, [])
    # a typo must not switch off every layer
    assert _signal_layer_rules(DSN, ["Top"]) == (None, [])


def test_rules_file_is_passed_to_freerouting(tmp_path, monkeypatch):
    import commands.freerouting as fr

    monkeypatch.setattr(fr, "_find_java", lambda *_: "java")
    cmd = _build_freerouting_cmd(
        "fr.jar", "/x/b.dsn", "/x/b.ses", 5, False, rules_path="/x/b.rules"
    )
    assert cmd[cmd.index("-dr") + 1] == "/x/b.rules"
    cmd = _build_freerouting_cmd("fr.jar", "/x/b.dsn", "/x/b.ses", 5, False)
    assert "-dr" not in cmd
