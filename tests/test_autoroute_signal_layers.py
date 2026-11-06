"""signalLayers keeps tracks off plane layers.

KiCad exports every copper layer as (type signal), so Freerouting ran long tracks across
the inner planes of a 4-layer board and cut In2 into 7 islands. The autoroute
`signalLayers` option adds a board-sized wire_keepout on every other copper layer.
"""

from commands.freerouting import _restrict_signal_layers

DSN = """(pcb "b.dsn"
  (parser
    (host_cad "KiCad's Pcbnew")
  )
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
      (path pcb 0  100 -100  200 -100
            200 -200  100 -200  100 -100)
    )
    (via "Via[0-3]_600:300_um")
    (rule
      (width 200)
      (clearance 200)
    )
  )
  (placement
  )
)
"""


def test_inner_layers_get_a_wire_keepout_over_the_boundary():
    out, restricted = _restrict_signal_layers(DSN, ["F.Cu", "B.Cu"])
    assert restricted == ["In1.Cu", "In2.Cu"]
    assert (
        '(wire_keepout "" (polygon In1.Cu 0 100 -100 200 -100 200 -200 100 -200 100 -100))' in out
    )
    assert '(wire_keepout "" (polygon In2.Cu 0 ' in out
    assert "polygon F.Cu" not in out and "polygon B.Cu" not in out
    # inside (structure ...), before (placement
    assert out.index("wire_keepout") < out.index("(placement")
    assert out.index("wire_keepout") > out.index("(rule")
    # parens still balance
    assert out.count("(") == out.count(")")


def test_no_restriction_when_all_or_none_are_named():
    assert _restrict_signal_layers(DSN, ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]) == (DSN, [])
    assert _restrict_signal_layers(DSN, []) == (DSN, [])
    # a typo must not keep tracks off every layer
    assert _restrict_signal_layers(DSN, ["Top"]) == (DSN, [])


def test_no_boundary_leaves_the_text_alone():
    text = DSN.replace("(boundary", "(nothing")
    assert _restrict_signal_layers(text, ["F.Cu"]) == (text, [])
