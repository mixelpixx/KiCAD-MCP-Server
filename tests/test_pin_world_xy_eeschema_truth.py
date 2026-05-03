"""
Ground-truth regression for WireDragger.pin_world_xy + label snap.

The oracle is eeschema itself, accessed via `kicad-cli sch export netlist`.
For each (rotation, mirror) corner case, we:
  1. Build a schematic with a polarized component (Device:D, K=pin1, A=pin2).
  2. Apply the transform via the MCP rotate handler.
  3. Snap a label "<ref>_K" to pin 1 and "<ref>_A" to pin 2 via PinLocator coords.
  4. Run kicad-cli to extract the netlist.
  5. Assert each label's net binds to the *named* pin in the netlist —
     i.e. label "_K" must end up on pin 1 (K), not pin 2 (A).

If our pin coords agree with eeschema's render, the labels land on the
intended pins. If they disagree, the netlist swaps them, exposing the bug.

Skips if kicad-cli or the system Device library aren't available.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).parent.parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

from commands.component_schematic import ComponentManager  # noqa: E402
from commands.pin_locator import PinLocator  # noqa: E402
from commands.schematic import SchematicManager  # noqa: E402
from commands.wire_dragger import WireDragger  # noqa: E402

_KICAD_CLI = shutil.which("kicad-cli")
_DEVICE_LIB = Path("/usr/share/kicad/symbols/Device.kicad_sym")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(_KICAD_CLI is None, reason="kicad-cli not on PATH"),
    pytest.mark.skipif(not _DEVICE_LIB.exists(), reason="Device lib not installed"),
]


def _add_labels_to_file(sch_path: Path, labels: list[tuple[str, float, float]]) -> None:
    """Inject (label ...) tokens before the closing ')' of a .kicad_sch file."""
    text = sch_path.read_text()
    block = "\n"
    for name, x, y in labels:
        block += (
            f'  (label "{name}"\n'
            f"    (at {x} {y} 0)\n"
            f"    (effects (font (size 1.27 1.27)) (justify left bottom))\n"
            f'    (uuid "00000000-0000-0000-0000-{abs(hash(name)) % 10**12:012d}")\n'
            f"  )\n"
        )
    last = text.rstrip().rfind(")")
    sch_path.write_text(text[:last] + block + text[last:])


def _extract_pin_to_net(netlist_xml: Path) -> dict:
    """Return {(ref, pin_num): net_name} from a kicad XML netlist."""
    tree = ET.parse(netlist_xml)
    root = tree.getroot()
    out = {}
    for net in root.findall(".//net"):
        net_name = net.attrib.get("name", "").lstrip("/")
        for node in net.findall("node"):
            ref = node.attrib.get("ref")
            pin = node.attrib.get("pin")
            if ref and pin:
                out[(ref, pin)] = net_name
    return out


def _build_diode_case(tmp: Path, rotation: int) -> tuple[Path, dict]:
    """Place a Device:D, rotate, snap labels, save. Returns (sch_path, expected_map)."""
    sch_path = tmp / f"diode_rot{rotation}.kicad_sch"
    template = PYTHON_DIR / "templates" / "template_with_symbols.kicad_sch"
    shutil.copy(template, sch_path)

    sch = SchematicManager.load_schematic(str(sch_path))
    ComponentManager.add_component(
        sch,
        {
            "type": "D",
            "reference": "D1",
            "value": "1N4148",
            "x": 100.0,
            "y": 100.0,
            "rotation": rotation,
        },
        sch_path,
    )
    SchematicManager.save_schematic(sch, str(sch_path))

    locator = PinLocator()
    p_k = locator.get_pin_location(sch_path, "D1", "1")
    p_a = locator.get_pin_location(sch_path, "D1", "2")
    assert p_k is not None and p_a is not None

    _add_labels_to_file(sch_path, [("D1_K", p_k[0], p_k[1]), ("D1_A", p_a[0], p_a[1])])

    return sch_path, {("D1", "1"): "D1_K", ("D1", "2"): "D1_A"}


def _apply_mirror_to_file(sch_path: Path, reference: str, axis: str) -> None:
    """Apply (mirror x|y) to a placed symbol via direct sexpr mutation.

    ComponentManager.add_component silently drops a 'mirror' kwarg, so this
    fixture goes around it via the same low-level helper rotate_schematic_component
    uses (WireDragger.update_symbol_rotation_mirror)."""
    import sexpdata

    sch_data = sexpdata.loads(sch_path.read_text())
    if not WireDragger.update_symbol_rotation_mirror(sch_data, reference, 0, axis):
        raise RuntimeError(f"Failed to apply mirror={axis} to {reference}")
    sch_path.write_text(sexpdata.dumps(sch_data))


def _build_mirror_case(tmp: Path, axis: str) -> tuple[Path, dict]:
    sch_path = tmp / f"resistor_mirror_{axis}.kicad_sch"
    template = PYTHON_DIR / "templates" / "template_with_symbols.kicad_sch"
    shutil.copy(template, sch_path)

    sch = SchematicManager.load_schematic(str(sch_path))
    ComponentManager.add_component(
        sch,
        {"type": "R", "reference": "R1", "value": "10k", "x": 100.0, "y": 100.0, "rotation": 0},
        sch_path,
    )
    SchematicManager.save_schematic(sch, str(sch_path))

    _apply_mirror_to_file(sch_path, "R1", axis)
    if f"(mirror {axis})" not in sch_path.read_text():
        raise RuntimeError(
            f"Fixture failed to write (mirror {axis}) — the kicad-cli oracle would "
            f"silently match our pin coords for an unmirrored symbol."
        )

    locator = PinLocator()
    p1 = locator.get_pin_location(sch_path, "R1", "1")
    p2 = locator.get_pin_location(sch_path, "R1", "2")
    if p1 is None or p2 is None:
        raise RuntimeError(f"PinLocator returned None for R1 mirror={axis}")

    _add_labels_to_file(sch_path, [("R1_PIN1", p1[0], p1[1]), ("R1_PIN2", p2[0], p2[1])])

    return sch_path, {("R1", "1"): "R1_PIN1", ("R1", "2"): "R1_PIN2"}


def _run_netlist(sch_path: Path) -> dict:
    out = sch_path.with_suffix(".net")
    env = {**os.environ, "KICAD_SYMBOL_DIR": "/usr/share/kicad/symbols"}
    subprocess.run(
        [
            _KICAD_CLI,
            "sch",
            "export",
            "netlist",
            "--format",
            "kicadxml",
            "-o",
            str(out),
            str(sch_path),
        ],
        check=True,
        capture_output=True,
        env=env,
    )
    return _extract_pin_to_net(out)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_diode_label_polarity_through_eeschema(rotation):
    """Snap-labelled K must show up on pin 1 in the kicad-cli netlist."""
    with tempfile.TemporaryDirectory() as td:
        sch_path, expected = _build_diode_case(Path(td), rotation)
        actual = _run_netlist(sch_path)
        for (ref, pin), net in expected.items():
            assert actual.get((ref, pin)) == net, (
                f"rotation={rotation}: D1.{pin} label landed on wrong pin. "
                f"Expected net={net}, got {actual.get((ref, pin))}. "
                f"Full mapping: {actual}"
            )


@pytest.mark.parametrize("axis", ["x", "y"])
def test_mirrored_resistor_label_through_eeschema(axis):
    """Snap-labelled pin 1 must show up on pin 1 after (mirror x) / (mirror y)."""
    with tempfile.TemporaryDirectory() as td:
        sch_path, expected = _build_mirror_case(Path(td), axis)
        actual = _run_netlist(sch_path)
        for (ref, pin), net in expected.items():
            assert actual.get((ref, pin)) == net, (
                f"mirror={axis}: R1.{pin} label landed on wrong pin. "
                f"Expected net={net}, got {actual.get((ref, pin))}. "
                f"Full mapping: {actual}"
            )


def test_pin_world_xy_rot90_matches_eeschema_transform():
    """Pure-math regression: pin_world_xy for Device:R rot=90 must match
    eeschema's TRANSFORM(0,1,-1,0) applied to internal Y-flipped pin."""
    # Device:R pin 1: lib (0, +3.81). parseXY(invertY=true) → internal (0, -3.81).
    # TRANSFORM(0,1,-1,0) applied: (0*0 + 1*-3.81, -1*0 + 0*-3.81) = (-3.81, 0).
    # Symbol at (100, 100) → world (96.19, 100).
    wx, wy = WireDragger.pin_world_xy(0.0, 3.81, 100.0, 100.0, 90, False, False)
    assert wx == pytest.approx(96.19), f"rot=90 X wrong: {wx} (expected 96.19)"
    assert wy == pytest.approx(100.0), f"rot=90 Y wrong: {wy} (expected 100.0)"


def test_pin_world_xy_mirror_x_matches_eeschema():
    """(mirror x) = SYM_MIRROR_X = TRANSFORM(1,0,0,-1) → negates internal Y.
    Device:R pin 1 lib (0, +3.81) → internal (0, -3.81) → mirror_x → (0, 3.81)
        → symbol (100, 100) → world (100, 103.81). Pin should NOT be at (100, 96.19)."""
    wx, wy = WireDragger.pin_world_xy(0.0, 3.81, 100.0, 100.0, 0, True, False)
    assert wx == pytest.approx(100.0)
    assert wy == pytest.approx(103.81), f"mirror_x Y wrong: {wy} (expected 103.81)"


def test_pin_world_xy_mirror_y_matches_eeschema():
    """(mirror y) = SYM_MIRROR_Y = TRANSFORM(-1,0,0,1) → negates internal X.
    Device:R pin 1 lib (0, +3.81) → internal (0, -3.81) → mirror_y → (0, -3.81)
        → world (100, 96.19). Y of pin 1 is unchanged by mirror across Y axis."""
    wx, wy = WireDragger.pin_world_xy(0.0, 3.81, 100.0, 100.0, 0, False, True)
    assert wx == pytest.approx(100.0)
    assert wy == pytest.approx(96.19), f"mirror_y Y wrong: {wy} (expected 96.19)"
