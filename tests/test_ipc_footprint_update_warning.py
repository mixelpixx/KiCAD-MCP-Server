"""#569: IPC tools that rewrite a footprint warn that KiCad drops data from it.

KiCad's IPC ``UpdateItems`` rebuilds a footprint from the message the client
sends, and loses what the message does not carry: the ``(units ...)`` map
(kicad#25859, fixed in 10.0.8), pad fabrication properties and the stroke type
``default`` (kicad#26112). The next save writes the loss to the file. The server
cannot restore it, so the replies of the four tools that push footprints back
say which footprints were rewritten and what can be lost.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from kicad_api.ipc_backend import IPCBackend, footprint_update_loss_warning  # noqa: E402

pytestmark = pytest.mark.unit


# --- the warning text ----------------------------------------------------------


def test_no_references_means_no_warning():
    assert footprint_update_loss_warning((10, 0, 6), []) is None


def test_before_10_0_8_the_units_map_is_named():
    warning = footprint_update_loss_warning((10, 0, 6), ["U1"])
    assert warning is not None
    assert "U1" in warning
    assert "(units ...)" in warning and "25859" in warning and "fixed in 10.0.8" in warning
    assert "heatsink" in warning and "26112" in warning
    assert "next save" in warning


@pytest.mark.parametrize("version", [(10, 0, 8), (10, 1, 0), (11, 0, 0), (9, 0, 7)])
def test_the_units_map_is_not_named_where_it_is_not_lost(version):
    # Fixed from 10.0.8; KiCad 9 footprints have no (units ...) block.
    warning = footprint_update_loss_warning(version, ["R1"])
    assert warning is not None
    assert "(units ...)" not in warning
    assert "26112" in warning


def test_an_unknown_version_names_the_units_map_with_its_range():
    warning = footprint_update_loss_warning(None, ["R1"])
    assert warning is not None
    assert "on KiCad 10 before 10.0.8" in warning


def test_a_long_list_of_references_is_shortened():
    refs = [f"R{i}" for i in range(1, 16)]
    warning = footprint_update_loss_warning((10, 0, 8), refs)
    assert warning is not None
    assert "R10" in warning and "R11" not in warning
    assert "and 5 more" in warning


# --- the running KiCad version ---------------------------------------------------


def test_running_version_asks_kicad_not_the_api_build():
    backend = IPCBackend()
    backend._kicad = MagicMock()
    backend._kicad.get_version.return_value = SimpleNamespace(major=10, minor=0, patch=6)
    backend._kicad.get_api_version.return_value = SimpleNamespace(major=10, minor=0, patch=1)

    assert backend.running_kicad_version() == (10, 0, 6)
    assert backend.running_kicad_version() == (10, 0, 6)
    backend._kicad.get_version.assert_called_once()  # cached for the connection


def test_running_version_is_none_when_kicad_cannot_say():
    backend = IPCBackend()
    backend._kicad = MagicMock()
    backend._kicad.get_version.side_effect = RuntimeError("no reply")
    assert backend.running_kicad_version() is None
    assert IPCBackend().running_kicad_version() is None


# --- the dispatcher ------------------------------------------------------------


def _make_iface(version: Any = (10, 0, 6)) -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", True):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)

    iface.use_ipc = True
    iface.board = None
    iface.ipc_backend = MagicMock()
    iface.ipc_backend.running_kicad_version.return_value = version
    iface.ipc_board_api = MagicMock()
    iface.ipc_board_api.move_component.return_value = True
    iface.ipc_board_api.list_components.return_value = [
        {"reference": "U1", "position": {"x": 10, "y": 20}}
    ]
    iface.command_routes = {}
    iface._board_disk_signature = None
    iface._current_project_path = None
    iface._last_auto_save_status = None
    return iface


def _dispatch(iface: Any, command: str, params: dict) -> dict:
    import kicad_interface

    with patch.object(kicad_interface, "KICAD_BACKEND", "swig"):
        return iface.handle_command(command, params)


def test_move_component_over_ipc_warns_about_the_moved_footprint():
    iface = _make_iface()
    result = _dispatch(iface, "move_component", {"reference": "U1", "x": 1, "y": 2})

    assert result["success"] is True and result["_backend"] == "ipc"
    [warning] = result["warnings"]
    assert "U1" in warning and "(units ...)" in warning


def test_rotate_component_over_ipc_warns():
    result = _dispatch(_make_iface(), "rotate_component", {"reference": "U1", "angle": 90})
    assert result["success"] is True
    assert "U1" in result["warnings"][0]


def test_add_3d_model_lists_only_the_footprints_it_rewrote():
    iface = _make_iface((10, 0, 8))
    iface.ipc_board_api.add_3d_model.return_value = {
        "success": True,
        "updated": 1,
        "details": [
            {"reference": "D1", "added": True, "replaced": 0},
            {"reference": "D2", "added": False, "note": "already present"},
        ],
    }
    result = _dispatch(iface, "add_component_3d_model", {"reference": ["D1", "D2"]})

    [warning] = result["warnings"]
    assert "D1" in warning and "D2" not in warning
    assert "(units ...)" not in warning  # 10.0.8 keeps the map


def test_add_3d_model_that_changed_nothing_does_not_warn():
    iface = _make_iface()
    iface.ipc_board_api.add_3d_model.return_value = {
        "success": True,
        "updated": 0,
        "details": [{"reference": "D1", "added": False, "note": "already present"}],
    }
    result = _dispatch(iface, "add_component_3d_model", {"reference": "D1"})
    assert "warnings" not in result


def test_a_failed_move_does_not_warn():
    iface = _make_iface()
    iface.ipc_board_api.move_component.return_value = False
    result = _dispatch(iface, "move_component", {"reference": "U1", "x": 1, "y": 2})
    assert result["success"] is False
    assert "warnings" not in result


def test_a_handler_that_fell_back_to_swig_does_not_warn():
    # set_footprint_type falls back to the SWIG copy when the proto update fails;
    # that path never went through UpdateItems.
    iface = _make_iface()
    iface._ipc_set_footprint_type = MagicMock(  # type: ignore[method-assign]
        return_value={"success": True, "_backend": "swig"}
    )
    result = _dispatch(iface, "set_footprint_type", {"reference": "U1", "type": "smd"})
    assert result["_backend"] == "swig"
    assert "warnings" not in result


def test_set_footprint_type_over_ipc_warns():
    iface = _make_iface()
    iface._ipc_set_footprint_type = MagicMock(  # type: ignore[method-assign]
        return_value={"success": True, "_backend": "ipc", "_realtime": True}
    )
    result = _dispatch(iface, "set_footprint_type", {"reference": "U1", "type": "smd"})
    assert "U1" in result["warnings"][0]


def test_tools_that_do_not_rewrite_footprints_do_not_warn():
    iface = _make_iface()
    iface.ipc_board_api.delete_component.return_value = True
    result = _dispatch(iface, "delete_component", {"reference": "U1"})
    assert result["success"] is True
    assert "warnings" not in result
