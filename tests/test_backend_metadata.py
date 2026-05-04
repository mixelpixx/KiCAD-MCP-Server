"""Tests for backend metadata added by KiCADInterface.handle_command."""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


def _make_iface(command_routes, use_ipc=False):
    from kicad_interface import KiCADInterface

    iface = KiCADInterface.__new__(KiCADInterface)
    iface.use_ipc = use_ipc
    iface.ipc_backend = None
    iface.ipc_board_api = None
    iface.command_routes = command_routes
    return iface


class _FakeIPCBoardAPI:
    def get_size(self):
        return {"width": 10, "height": 20, "unit": "mm"}

    def list_components(self):
        return []

    def get_tracks(self):
        return [
            {
                "id": "track-1",
                "start": {"x": 0, "y": 0},
                "end": {"x": 3, "y": 4},
                "width": 0.25,
                "layer": "BL_F_Cu",
                "net": "N$1",
            }
        ]

    def get_vias(self):
        return []

    def get_nets(self):
        return [{"name": "N$1", "code": 1}]

    def get_enabled_layers(self):
        return ["F.Cu", "B.Cu"]


class _FakeIPCBackend:
    def __init__(self):
        self.connected = False

    def connect(self):
        self.connected = True
        return True

    def is_connected(self):
        return self.connected

    def get_board(self):
        return _FakeIPCBoardAPI()

    def get_version(self):
        return "9.0-test"


class _ConnectShouldNotBeCalledIPCBackend(_FakeIPCBackend):
    def connect(self):
        raise AssertionError("IPC reconnect should not be attempted")


class _FailingConnectIPCBackend(_FakeIPCBackend):
    def connect(self):
        raise RuntimeError("IPC unavailable")


class _NoBoardIPCBackend(_FakeIPCBackend):
    def get_board(self):
        raise RuntimeError("No board open")


class _FilteringIPCBoardAPI(_FakeIPCBoardAPI):
    def get_tracks(self):
        return [
            {
                "id": "track-1",
                "start": {"x": 0, "y": 0},
                "end": {"x": 3, "y": 4},
                "width": 0.25,
                "layer": "BL_F_Cu",
                "net": "N$1",
                "netCode": 1,
            },
            {
                "id": "track-2",
                "start": {"x": 10, "y": 10},
                "end": {"x": 11, "y": 11},
                "width": 0.2,
                "layer": "BL_B_Cu",
                "net": "N$2",
                "netCode": 2,
            },
        ]

    def get_vias(self):
        return [
            {
                "id": "via-1",
                "position": {"x": 0.5, "y": 0.5},
                "diameter": 0.8,
                "drill": 0.4,
                "net": "N$1",
                "netCode": 1,
            },
            {
                "id": "via-2",
                "position": {"x": 20, "y": 20},
                "diameter": 0.8,
                "drill": 0.4,
                "net": "N$2",
                "netCode": 2,
            },
        ]


class _Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class _BoxWithPosSize:
    def __init__(self, x, y, width, height):
        self.pos = _Point(x, y)
        self.size = _Point(width, height)


class _BoxWithMinMax:
    def __init__(self, min_x, min_y, max_x, max_y):
        self.min = _Point(min_x, min_y)
        self.max = _Point(max_x, max_y)


class _BoundingBoxBoard:
    def __init__(self, boxes):
        self._boxes = boxes

    def get_shapes(self):
        return list(range(len(self._boxes)))

    def get_item_bounding_box(self, shape):
        return self._boxes[shape]


def _stub_kipy_units(monkeypatch):
    units_module = types.ModuleType("kipy.util.units")
    units_module.to_mm = lambda nm: nm / 1_000_000
    monkeypatch.setitem(sys.modules, "kipy", types.ModuleType("kipy"))
    monkeypatch.setitem(sys.modules, "kipy.util", types.ModuleType("kipy.util"))
    monkeypatch.setitem(sys.modules, "kipy.util.units", units_module)


def test_generic_command_is_tagged_as_swig():
    iface = _make_iface(
        {
            "get_project_info": lambda params: {
                "success": True,
                "project": {"name": "demo"},
            }
        },
        use_ipc=True,
    )

    result = iface.handle_command("get_project_info", {})

    assert result["_backend"] == "swig"
    assert result["_realtime"] is False


def test_explicit_ipc_command_is_tagged_as_ipc_when_ipc_is_active():
    iface = _make_iface(
        {
            "ipc_add_track": lambda params: {
                "success": True,
                "message": "Track added",
                "realtime": True,
            }
        },
        use_ipc=True,
    )

    result = iface.handle_command("ipc_add_track", {})

    assert result["_backend"] == "ipc"
    assert result["_realtime"] is True


def test_backend_info_uses_reported_backend_for_metadata():
    iface = _make_iface(
        {
            "get_backend_info": lambda params: {
                "success": True,
                "backend": "ipc",
                "realtime_sync": True,
            }
        },
        use_ipc=True,
    )

    result = iface.handle_command("get_backend_info", {})

    assert result["_backend"] == "ipc"
    assert result["_realtime"] is True


def test_ipc_capable_command_reconnects_when_kicad_is_running(monkeypatch):
    import kicad_interface

    monkeypatch.setattr(kicad_interface, "KICAD_BACKEND", "auto")
    monkeypatch.setattr(kicad_interface.KiCADProcessManager, "is_running", lambda: True)
    monkeypatch.setitem(
        sys.modules,
        "kicad_api.ipc_backend",
        types.SimpleNamespace(IPCBackend=_FakeIPCBackend),
    )

    iface = _make_iface({}, use_ipc=False)

    result = iface.handle_command("get_board_info", {})

    assert result["success"] is True
    assert result["_backend"] == "ipc"
    assert result["_realtime"] is True


def test_ipc_capable_command_does_not_reconnect_in_strict_swig_mode(monkeypatch):
    import kicad_interface

    monkeypatch.setattr(kicad_interface, "KICAD_BACKEND", "swig")
    monkeypatch.setattr(kicad_interface.KiCADProcessManager, "is_running", lambda: True)
    monkeypatch.setitem(
        sys.modules,
        "kicad_api.ipc_backend",
        types.SimpleNamespace(IPCBackend=_ConnectShouldNotBeCalledIPCBackend),
    )

    iface = _make_iface(
        {
            "get_board_info": lambda params: {
                "success": True,
                "board": {"filename": "demo.kicad_pcb"},
            }
        },
        use_ipc=False,
    )

    result = iface.handle_command("get_board_info", {})

    assert result["success"] is True
    assert result["_backend"] == "swig"
    assert result["_realtime"] is False
    assert iface.ipc_board_api is None


def test_ipc_reconnect_failure_falls_back_to_swig(monkeypatch):
    import kicad_interface

    monkeypatch.setattr(kicad_interface, "KICAD_BACKEND", "auto")
    monkeypatch.setattr(kicad_interface.KiCADProcessManager, "is_running", lambda: True)
    monkeypatch.setitem(
        sys.modules,
        "kicad_api.ipc_backend",
        types.SimpleNamespace(IPCBackend=_FailingConnectIPCBackend),
    )

    iface = _make_iface(
        {
            "get_board_info": lambda params: {
                "success": True,
                "board": {"filename": "demo.kicad_pcb"},
            }
        },
        use_ipc=False,
    )

    result = iface.handle_command("get_board_info", {})

    assert result["success"] is True
    assert result["_backend"] == "swig"
    assert result["_realtime"] is False
    assert iface.use_ipc is False
    assert iface.ipc_board_api is None


def test_connected_ipc_without_board_api_reports_status_but_board_tools_fallback(monkeypatch):
    import kicad_interface

    monkeypatch.setattr(kicad_interface, "KICAD_BACKEND", "auto")
    monkeypatch.setattr(kicad_interface.KiCADProcessManager, "is_running", lambda: True)
    monkeypatch.setitem(
        sys.modules,
        "kicad_api.ipc_backend",
        types.SimpleNamespace(IPCBackend=_NoBoardIPCBackend),
    )

    iface = _make_iface(
        {
            "get_board_info": lambda params: {
                "success": True,
                "board": {"filename": "demo.kicad_pcb"},
            }
        },
        use_ipc=False,
    )
    iface.command_routes["get_backend_info"] = iface._handle_get_backend_info

    board_result = iface.handle_command("get_board_info", {})
    backend_result = iface.handle_command("get_backend_info", {})

    assert board_result["success"] is True
    assert board_result["_backend"] == "swig"
    assert board_result["_realtime"] is False
    assert iface.use_ipc is True
    assert iface.ipc_board_api is None

    assert backend_result["success"] is True
    assert backend_result["backend"] == "ipc"
    assert backend_result["realtime_sync"] is True
    assert backend_result["ipc_connected"] is True
    assert backend_result["_backend"] == "ipc"


def test_ui_status_tools_report_live_ipc_backend_status(monkeypatch):
    import kicad_interface

    monkeypatch.setattr(kicad_interface, "KICAD_BACKEND", "auto")
    monkeypatch.setattr(kicad_interface.KiCADProcessManager, "is_running", lambda self=None: True)
    monkeypatch.setattr(
        kicad_interface.KiCADProcessManager,
        "get_process_info",
        lambda self: [{"pid": "1234", "name": "pcbnew.exe", "command": "pcbnew.exe"}],
    )
    monkeypatch.setitem(
        sys.modules,
        "kicad_api.ipc_backend",
        types.SimpleNamespace(IPCBackend=_FakeIPCBackend),
    )

    iface = _make_iface({}, use_ipc=False)
    iface.ipc_backend = _FakeIPCBackend()
    iface.command_routes = {
        "check_kicad_ui": iface._handle_check_kicad_ui,
        "launch_kicad_ui": iface._handle_launch_kicad_ui,
        "get_backend_info": iface._handle_get_backend_info,
    }
    monkeypatch.setattr(
        kicad_interface,
        "check_and_launch_kicad",
        lambda path_obj, auto_launch: {
            "running": True,
            "launched": True,
            "processes": [{"pid": "1234", "name": "pcbnew.exe", "command": "pcbnew.exe"}],
            "message": "KiCAD launched successfully",
            "project": str(path_obj) if path_obj else None,
        },
    )

    for command in ("check_kicad_ui", "launch_kicad_ui", "get_backend_info"):
        result = iface.handle_command(command, {})

        assert result["success"] is True
        assert result["backend"] == "ipc"
        assert result["realtime_sync"] is True
        assert result["ipc_connected"] is True
        assert result["_backend"] == "ipc"
        assert result["_realtime"] is True


def test_query_traces_can_use_ipc_backend(monkeypatch):
    import kicad_interface

    monkeypatch.setattr(kicad_interface, "KICAD_BACKEND", "swig")

    iface = _make_iface({}, use_ipc=True)
    iface.ipc_board_api = _FakeIPCBoardAPI()

    result = iface.handle_command(
        "query_traces",
        {"layer": "F.Cu", "boundingBox": {"x1": -1, "y1": -1, "x2": 1, "y2": 1}},
    )

    assert result["success"] is True
    assert result["traceCount"] == 1
    assert result["traces"][0]["layer"] == "F.Cu"
    assert result["traces"][0]["length"] == 5
    assert result["_backend"] == "ipc"


def test_query_traces_ipc_filters_and_vias(monkeypatch):
    import kicad_interface

    monkeypatch.setattr(kicad_interface, "KICAD_BACKEND", "swig")

    iface = _make_iface({}, use_ipc=True)
    iface.ipc_board_api = _FilteringIPCBoardAPI()

    net_miss = iface.handle_command("query_traces", {"net": "NO_MATCH"})
    layer_match = iface.handle_command("query_traces", {"layer": "B.Cu"})
    reversed_bbox_with_vias = iface.handle_command(
        "query_traces",
        {
            "net": "N$1",
            "includeVias": True,
            "boundingBox": {"x1": 1, "y1": 1, "x2": -1, "y2": -1},
        },
    )

    assert net_miss["success"] is True
    assert net_miss["traceCount"] == 0
    assert net_miss["_backend"] == "ipc"

    assert layer_match["success"] is True
    assert layer_match["traceCount"] == 1
    assert layer_match["traces"][0]["uuid"] == "track-2"
    assert layer_match["traces"][0]["layer"] == "B.Cu"

    assert reversed_bbox_with_vias["success"] is True
    assert reversed_bbox_with_vias["traceCount"] == 1
    assert reversed_bbox_with_vias["traces"][0]["uuid"] == "track-1"
    assert reversed_bbox_with_vias["viaCount"] == 1
    assert reversed_bbox_with_vias["vias"][0]["uuid"] == "via-1"


def test_ipc_board_size_supports_kicad_10_box2_pos_size(monkeypatch):
    from kicad_api.ipc_backend import IPCBoardAPI

    _stub_kipy_units(monkeypatch)
    board_api = IPCBoardAPI(None, lambda *_args: None)
    board_api._board = _BoundingBoxBoard(
        [
            _BoxWithPosSize(1_000_000, 2_000_000, 3_000_000, 4_000_000),
            _BoxWithPosSize(0, 1_000_000, 2_000_000, 1_000_000),
        ]
    )

    result = board_api.get_size()

    assert result == {"width": 4.0, "height": 5.0, "unit": "mm"}


def test_ipc_board_size_keeps_min_max_box2_compatibility(monkeypatch):
    from kicad_api.ipc_backend import IPCBoardAPI

    _stub_kipy_units(monkeypatch)
    board_api = IPCBoardAPI(None, lambda *_args: None)
    board_api._board = _BoundingBoxBoard(
        [
            _BoxWithMinMax(1_000_000, 2_000_000, 3_000_000, 4_000_000),
            _BoxWithMinMax(0, 1_000_000, 2_000_000, 3_000_000),
        ]
    )

    result = board_api.get_size()

    assert result == {"width": 3.0, "height": 3.0, "unit": "mm"}
