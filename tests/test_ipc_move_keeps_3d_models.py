"""Regression test: IPC move_component with a rotation must keep 3D models.

kipy's ``FootprintInstance.orientation`` setter (kicad-python 0.8.0) rebuilds
``definition.items`` from fields, pads, text, zones and shapes only, silently
dropping every ``Footprint3DModel``. ``move_component`` always assigned the
orientation when a rotation was passed, so each rotated move pushed a
model-less footprint back to KiCad and the part vanished from the 3D viewer.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

bt = pytest.importorskip("kipy.board_types", reason="kipy (kicad-python) not installed")
geometry = pytest.importorskip("kipy.geometry")

from kicad_api.ipc_backend import IPCBoardAPI, _set_orientation_keep_models  # noqa: E402

MODEL = "${KICAD9_3DMODEL_DIR}/Resistor_SMD.3dshapes/R_0603_1608Metric.step"


def _footprint_with_model(reference: str = "R1") -> "bt.FootprintInstance":
    fp = bt.FootprintInstance()
    fp.reference_field.text.value = reference
    model = bt.Footprint3DModel()
    model.filename = MODEL
    fp.definition.add_item(model)
    return fp


def _model_files(fp: "bt.FootprintInstance") -> list:
    return [m.filename for m in fp.definition.models]


def test_kipy_orientation_setter_drops_models() -> None:
    """Tripwire for the upstream bug. If this starts failing, kipy fixed the
    setter and _set_orientation_keep_models can be removed."""
    fp = _footprint_with_model()
    fp.orientation = geometry.Angle.from_degrees(90)
    assert _model_files(fp) == []


@pytest.mark.parametrize("degrees", [0, 90, 180, -90])
def test_helper_keeps_models(degrees: float) -> None:
    fp = _footprint_with_model()
    angle = geometry.Angle.from_degrees(degrees)
    _set_orientation_keep_models(fp, angle)
    assert _model_files(fp) == [MODEL]
    assert fp.orientation.degrees == pytest.approx(angle.normalize180().degrees)


def test_move_component_with_rotation_pushes_models() -> None:
    fp = _footprint_with_model("C12")
    board = MagicMock()
    board.get_footprints.return_value = [fp]

    api = IPCBoardAPI.__new__(IPCBoardAPI)
    get_board = patch.object(IPCBoardAPI, "_get_board", return_value=board)
    notify = patch.object(IPCBoardAPI, "_notify", create=True)
    with get_board, notify:
        assert api.move_component("C12", 119.8, 80.0, rotation=180) is True

    (pushed,), _ = board.update_items.call_args
    assert _model_files(pushed[0]) == [MODEL]
