"""
IPC API Backend (KiCAD 9.0+)

Uses the official kicad-python library for inter-process communication
with a running KiCAD instance. This enables REAL-TIME UI synchronization.

Note: Requires KiCAD to be running with IPC server enabled:
    Preferences > Plugins > Enable IPC API Server

Key Benefits over SWIG:
- Changes appear instantly in KiCAD UI (no reload needed)
- Transaction support for undo/redo
- Stable API that won't break between versions
- Multi-language support
"""

import logging
import os
import platform
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from kicad_api.base import APINotAvailableError, BoardAPI, ConnectionError, KiCADBackend
from utils.project_settings_guard import preserve_project_settings

logger = logging.getLogger(__name__)

# Hard wall-clock cap for a single IPC connection attempt. kipy dials with
# pynng's block_on_dial=True, which has NO timeout (only send/recv are capped),
# so if KiCad's GUI thread is busy (e.g. reloading a library we just wrote to,
# or any modal/progress state) and not servicing its socket, a connect can hang
# until the client's ~240s watchdog fires. Bounding it here turns that into a
# fast fall-back to the SWIG/file backend instead of an apparent freeze.
IPC_CONNECT_TIMEOUT_S = float(os.getenv("KICAD_IPC_CONNECT_TIMEOUT", "5"))

# Unit conversion constant: KiCAD IPC uses nanometers internally
MM_TO_NM = 1_000_000
INCH_TO_NM = 25_400_000


class IPCBackend(KiCADBackend):
    """
    KiCAD IPC API backend for real-time UI synchronization.

    Communicates with KiCAD via Protocol Buffers over UNIX sockets.
    Requires KiCAD 9.0+ to be running with IPC enabled.

    Changes made through this backend appear immediately in the KiCAD UI
    without requiring manual reload.
    """

    def __init__(self) -> None:
        self._kicad = None
        self._connected = False
        self._version: Optional[str] = None
        self._on_change_callbacks: List[Callable] = []

    def connect(self, socket_path: Optional[str] = None) -> bool:
        """
        Connect to running KiCAD instance via IPC.

        Args:
            socket_path: Optional socket path. If not provided, will try common locations.
                        Use format: ipc:///tmp/kicad/api.sock

        Returns:
            True if connection successful

        Raises:
            ConnectionError: If connection fails
        """
        try:
            # Import here to allow module to load even without kicad-python
            from kipy import KiCad

            logger.info("Connecting to KiCAD via IPC...")

            # Try to connect with provided path or auto-detect
            socket_paths_to_try = []
            if socket_path:
                socket_paths_to_try.append(socket_path)
            else:
                # Common socket locations (Unix-like systems only)
                # Windows uses named pipes, handled by auto-detect
                if platform.system() != "Windows":
                    socket_paths_to_try.append("ipc:///tmp/kicad/api.sock")  # Linux default
                    # XDG runtime directory (requires getuid, Unix only)
                    if hasattr(os, "getuid"):
                        socket_paths_to_try.append(f"ipc:///run/user/{os.getuid()}/kicad/api.sock")

                # Auto-detect for all platforms (Windows uses named pipes, Unix uses sockets)
                socket_paths_to_try.append(None)

            last_error = None
            for path in socket_paths_to_try:
                try:
                    logger.debug(f"Trying socket path: {path or 'auto-detect'}")
                    kicad, elapsed = self._open_with_timeout(KiCad, path, IPC_CONNECT_TIMEOUT_S)
                    self._kicad = kicad
                    logger.info(f"Connected via socket: {path or 'auto-detected'} ({elapsed:.2f}s)")
                    break
                except Exception as e:
                    last_error = e
                    logger.debug(f"Failed to connect via {path or 'auto-detect'}: {e}")
                    continue
            else:
                # None of the paths worked
                raise ConnectionError(f"Could not connect to KiCAD IPC: {last_error}")

            # Get version info
            self._version = self._get_kicad_version()
            logger.info(f"Connected to KiCAD {self._version} via IPC")
            self._connected = True
            return True

        except ImportError as e:
            logger.error("kicad-python library not found")
            raise APINotAvailableError(
                "IPC backend requires kicad-python. " "Install with: pip install kicad-python"
            ) from e
        except Exception as e:
            logger.error(f"Failed to connect via IPC: {e}")
            logger.info(
                "Ensure KiCAD is running with IPC enabled: "
                "Preferences > Plugins > Enable IPC API Server"
            )
            raise ConnectionError(f"IPC connection failed: {e}") from e

    def _open_with_timeout(self, KiCad: Any, path: Optional[str], timeout_s: float):
        """Open one kipy connection and ping it, bounded by a wall-clock timeout.

        kipy's dial uses pynng block_on_dial=True (no timeout), so the open+ping
        can hang if KiCad is busy and not servicing its socket. Run it in a
        daemon thread and give up after ``timeout_s`` — a stuck thread is
        orphaned (harmless: daemon, dies with the process) rather than blocking
        the command loop until the client's ~240s watchdog fires.

        Returns (kicad, elapsed_seconds). Raises TimeoutError on overrun, or the
        underlying exception if the attempt failed fast.
        """
        result: Dict[str, Any] = {}
        start = time.monotonic()

        def worker() -> None:
            try:
                kicad = KiCad(socket_path=path) if path else KiCad()
                kicad.ping()  # returns None on success, raises on failure
                result["kicad"] = kicad
            except Exception as e:  # noqa: BLE001 — surfaced to caller below
                result["error"] = e

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(timeout_s)
        elapsed = time.monotonic() - start

        if t.is_alive():
            raise TimeoutError(
                f"IPC connect exceeded {timeout_s:.1f}s (KiCad busy or not servicing "
                f"its socket); falling back to SWIG"
            )
        if "error" in result:
            raise result["error"]
        return result["kicad"], elapsed

    def _get_kicad_version(self) -> str:
        """Get KiCAD version string."""
        try:
            if self._kicad.check_version():
                return self._kicad.get_api_version()
            return "9.0+ (version mismatch)"
        except Exception:
            return "unknown"

    def disconnect(self) -> None:
        """Disconnect from KiCAD.

        kipy does not expose a public close(), but it holds a persistent pynng
        socket at ``KiCad._client._conn``. Simply dropping the reference orphans
        that socket and leaks its OS file descriptors (they are not released
        promptly by GC), so long-lived sessions that reconnect accumulate fds.
        Close the underlying socket explicitly, tolerating any internal changes.
        """
        if self._kicad:
            try:
                conn = getattr(getattr(self._kicad, "_client", None), "_conn", None)
                if conn is not None and hasattr(conn, "close"):
                    conn.close()
                    logger.debug("Closed underlying KiCAD IPC socket")
            except Exception as e:
                logger.debug(f"Error closing IPC socket during disconnect: {e}")
            self._kicad = None
            self._connected = False
            logger.info("Disconnected from KiCAD IPC")

    def is_connected(self) -> bool:
        """Check if connected to KiCAD."""
        if not self._connected or not self._kicad:
            return False
        try:
            # ping() returns None on success, raises on failure
            self._kicad.ping()
            return True
        except Exception:
            self._connected = False
            return False

    def get_version(self) -> str:
        """Get KiCAD version."""
        return self._version or "unknown"

    def get_open_board_path(self) -> Optional[str]:
        """Path of the .kicad_pcb currently open in the live KiCad GUI, if any.

        Used to decide whether the GUI session and the MCP's loaded board refer
        to the same file before routing commands over IPC (issue #223).
        """
        if not self.is_connected():
            return None
        try:
            # kicad-python 0.7+ requires the document type argument and
            # returns a DocumentSpecifier whose PCB path is split between
            # ``project.path`` and ``board_filename``.  Older versions
            # exposed a single ``path`` field, so retain that fallback.
            from kipy.proto.common.types import DocumentType

            for doc in self._kicad.get_open_documents(DocumentType.DOCTYPE_PCB):
                legacy_path = getattr(doc, "path", None)
                if legacy_path and str(legacy_path).endswith(".kicad_pcb"):
                    return str(legacy_path)

                filename = getattr(doc, "board_filename", "")
                project = getattr(doc, "project", None)
                project_path = getattr(project, "path", "") if project else ""
                if filename:
                    candidate = Path(filename)
                    return str(candidate if candidate.is_absolute() else Path(project_path) / candidate)
        except Exception as e:
            logger.debug(f"Could not read open documents via IPC: {e}")
        return None

    def register_change_callback(self, callback: Callable) -> None:
        """Register a callback to be called when changes are made."""
        self._on_change_callbacks.append(callback)

    def _notify_change(self, change_type: str, details: Dict[str, Any]) -> None:
        """Notify registered callbacks of a change."""
        for callback in self._on_change_callbacks:
            try:
                callback(change_type, details)
            except Exception as e:
                logger.warning(f"Change callback error: {e}")

    # Project Operations
    def create_project(self, path: Path, name: str) -> Dict[str, Any]:
        """
        Create a new KiCAD project.

        Note: The IPC API doesn't directly create projects.
        Projects must be created through the UI or file system.
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        # IPC API doesn't have project creation - use file-based approach
        logger.warning("Project creation via IPC not fully supported - using hybrid approach")

        # For now, we'll return info about what needs to happen
        return {
            "success": False,
            "message": "Direct project creation not supported via IPC",
            "suggestion": "Open KiCAD and create a new project, or use SWIG backend",
        }

    def open_project(self, path: Path) -> Dict[str, Any]:
        """Open existing project via IPC."""
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        try:
            # Check for open documents
            from kipy.proto.common.types import DocumentType

            documents = self._kicad.get_open_documents(DocumentType.DOCTYPE_PCB)

            # Look for matching project
            path_str = str(path)
            for doc in documents:
                if path_str in str(doc):
                    return {
                        "success": True,
                        "message": f"Project already open: {path}",
                        "path": str(path),
                    }

            return {
                "success": False,
                "message": "Project not currently open in KiCAD",
                "suggestion": "Open the project in KiCAD first, then connect via IPC",
            }

        except Exception as e:
            logger.error(f"Failed to check project: {e}")
            return {"success": False, "message": "Failed to check project", "errorDetails": str(e)}

    def save_project(self, path: Optional[Path] = None, overwrite: bool = False) -> Dict[str, Any]:
        """Save current project via IPC."""
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        try:
            board = self._kicad.get_board()
            if path:
                saved = board.save_as(str(path), overwrite=overwrite)
            else:
                saved = board.save()

            if saved is False:
                return {
                    "success": False,
                    "message": "Failed to save project",
                    "errorDetails": "KiCad IPC save returned false",
                }

            self._notify_change("save", {"path": str(path) if path else "current"})

            return {"success": True, "message": "Project saved successfully"}
        except Exception as e:
            logger.error(f"Failed to save project: {e}")
            return {"success": False, "message": "Failed to save project", "errorDetails": str(e)}

    def close_project(self) -> None:
        """Close current project (not supported via IPC)."""
        logger.warning("Closing projects via IPC is not supported")

    # Board Operations
    def get_board(self) -> BoardAPI:
        """Get board API for real-time manipulation."""
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        return IPCBoardAPI(self._kicad, self._notify_change)


class IPCBoardAPI(BoardAPI):
    """
    Board API implementation for IPC backend.

    All changes made through this API appear immediately in the KiCAD UI.
    Uses transactions for proper undo/redo support.
    """

    def __init__(self, kicad_instance: Any, notify_callback: Callable) -> None:
        self._kicad = kicad_instance
        self._board = None
        self._notify = notify_callback
        self._current_commit = None

    def _get_board(self) -> Any:
        """Get board instance, connecting if needed."""
        if self._board is None:
            try:
                self._board = self._kicad.get_board()
            except Exception as e:
                logger.error(f"Failed to get board: {e}")
                raise ConnectionError(f"No board open in KiCAD: {e}")
        return self._board

    @staticmethod
    def _resolve_board_layer(layer: str, default: str = "F.Cu") -> int:
        """Resolve a KiCad layer name to its kipy enum value.

        Supports every layer exposed by KiCad 10 (including all inner copper,
        fabrication, courtyard, user, and drawing layers), plus the common
        EasyEDA-style ``Top Layer``/``Bottom Layer`` aliases.
        """
        from kipy.proto.board.board_types_pb2 import BoardLayer

        aliases = {
            "top layer": "F.Cu",
            "bottom layer": "B.Cu",
            "top silkscreen layer": "F.SilkS",
            "bottom silkscreen layer": "B.SilkS",
            "top solder mask layer": "F.Mask",
            "bottom solder mask layer": "B.Mask",
            "top paste mask layer": "F.Paste",
            "bottom paste mask layer": "B.Paste",
        }
        canonical = aliases.get(str(layer).strip().casefold(), str(layer).strip())
        enum_name = canonical if canonical.startswith("BL_") else f"BL_{canonical}"
        enum_name = enum_name.replace(".", "_").replace("-", "_").replace(" ", "_")

        names = {name.casefold(): name for name in BoardLayer.keys()}
        resolved = names.get(enum_name.casefold())
        if resolved:
            return BoardLayer.Value(resolved)

        fallback_name = f"BL_{default}".replace(".", "_")
        logger.warning("Unknown board layer '%s'; using %s", layer, default)
        return BoardLayer.Value(fallback_name)

    @staticmethod
    def _item_id_value(item: Any) -> str:
        """Return a plain UUID string from a kipy board item."""
        item_id = getattr(item, "id", None)
        return str(getattr(item_id, "value", "") or "")

    def begin_transaction(self, description: str = "MCP Operation") -> None:
        """Begin a transaction for grouping operations into a single undo step."""
        board = self._get_board()
        self._current_commit = board.begin_commit()
        logger.debug(f"Started transaction: {description}")

    def commit_transaction(self, description: str = "MCP Operation") -> None:
        """Commit the current transaction."""
        if self._current_commit:
            board = self._get_board()
            board.push_commit(self._current_commit, description)
            self._current_commit = None
            logger.debug(f"Committed transaction: {description}")

    def rollback_transaction(self) -> None:
        """Roll back the current transaction."""
        if self._current_commit:
            board = self._get_board()
            board.drop_commit(self._current_commit)
            self._current_commit = None
            logger.debug("Rolled back transaction")

    def save(self) -> bool:
        """Save the board immediately."""
        try:
            board = self._get_board()
            board.save()
            self._notify("save", {})
            return True
        except Exception as e:
            logger.error(f"Failed to save board: {e}")
            return False

    def set_size(self, width: float, height: float, unit: str = "mm") -> bool:
        """
        Set board size.

        Note: Board size in KiCAD is typically defined by the board outline,
        not a direct size property. This method may need to create/modify
        the board outline.
        """
        try:
            from kipy.board_types import BoardRectangle
            from kipy.geometry import Vector2
            from kipy.util.units import from_mm

            board = self._get_board()

            # Convert to nm
            if unit == "mm":
                w = from_mm(width)
                h = from_mm(height)
            else:
                w = int(width * INCH_TO_NM)
                h = int(height * INCH_TO_NM)

            # Create board outline rectangle on Edge.Cuts layer
            rect = BoardRectangle()
            rect.top_left = Vector2.from_xy(0, 0)
            rect.bottom_right = Vector2.from_xy(w, h)
            rect.layer = self._resolve_board_layer("Edge.Cuts")
            rect.attributes.stroke.width = from_mm(0.1)  # Standard edge cut width

            # Begin transaction for undo support
            commit = board.begin_commit()
            board.create_items(rect)
            board.push_commit(commit, f"Set board size to {width}x{height} {unit}")

            self._notify("board_size", {"width": width, "height": height, "unit": unit})

            return True

        except Exception as e:
            logger.error(f"Failed to set board size: {e}")
            return False

    def get_size(self) -> Dict[str, Any]:
        """Get current board size from bounding box."""
        try:
            board = self._get_board()

            # Get shapes on Edge.Cuts layer to determine board size
            shapes = board.get_shapes()

            if not shapes:
                return {"width": 0, "height": 0, "unit": "mm"}

            # Find bounding box of edge cuts
            from kipy.util.units import to_mm

            min_x = min_y = float("inf")
            max_x = max_y = float("-inf")

            for shape in shapes:
                # Check if on Edge.Cuts layer
                bbox = board.get_item_bounding_box(shape)
                if bbox:
                    left, top, right, bottom = self._get_box2_extents(bbox)
                    min_x = min(min_x, left)
                    min_y = min(min_y, top)
                    max_x = max(max_x, right)
                    max_y = max(max_y, bottom)

            if min_x == float("inf"):
                return {"width": 0, "height": 0, "unit": "mm"}

            return {"width": to_mm(max_x - min_x), "height": to_mm(max_y - min_y), "unit": "mm"}

        except Exception as e:
            logger.error(f"Failed to get board size: {e}")
            return {"width": 0, "height": 0, "unit": "mm", "error": str(e)}

    @staticmethod
    def _get_box2_extents(bbox: Any) -> tuple[float, float, float, float]:
        """Return left/top/right/bottom for kipy Box2 wrappers across versions."""
        if hasattr(bbox, "min") and hasattr(bbox, "max"):
            return bbox.min.x, bbox.min.y, bbox.max.x, bbox.max.y

        if hasattr(bbox, "pos") and hasattr(bbox, "size"):
            x1 = bbox.pos.x
            y1 = bbox.pos.y
            x2 = x1 + bbox.size.x
            y2 = y1 + bbox.size.y
            return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)

        raise AttributeError("Unsupported Box2 shape: expected min/max or pos/size")

    def add_layer(self, layer_name: str, layer_type: str) -> bool:
        """Add layer to the board (layers are typically predefined in KiCAD)."""
        logger.warning("Layer management via IPC is limited - layers are predefined")
        return False

    def get_enabled_layers(self) -> List[str]:
        """Get list of enabled layers."""
        try:
            board = self._get_board()
            layers = board.get_enabled_layers()
            return [str(layer) for layer in layers]
        except Exception as e:
            logger.error(f"Failed to get enabled layers: {e}")
            return []

    def list_components(self) -> List[Dict[str, Any]]:
        """List all components (footprints) on the board."""
        try:
            from kipy.util.units import to_mm

            board = self._get_board()
            footprints = board.get_footprints()

            components = []
            for fp in footprints:
                try:
                    pos = fp.position

                    # Try to get bounding box
                    bbox_data = None
                    try:
                        bbox = board.get_item_bounding_box(fp)
                        if bbox:
                            bbox_data = {
                                "min_x": to_mm(bbox.min.x),
                                "min_y": to_mm(bbox.min.y),
                                "max_x": to_mm(bbox.max.x),
                                "max_y": to_mm(bbox.max.y),
                                "width": to_mm(bbox.max.x - bbox.min.x),
                                "height": to_mm(bbox.max.y - bbox.min.y),
                                "unit": "mm",
                            }
                    except Exception:
                        pass  # Bounding box may not be available via IPC

                    # Fallback: compute bounding box from pad positions + sizes
                    if not bbox_data:
                        try:
                            pads = fp.pads if hasattr(fp, "pads") else []
                            pad_list = list(pads)
                            if pad_list:
                                min_x = float("inf")
                                min_y = float("inf")
                                max_x = float("-inf")
                                max_y = float("-inf")
                                for pad in pad_list:
                                    px = to_mm(pad.position.x) if pad.position else 0
                                    py = to_mm(pad.position.y) if pad.position else 0
                                    pw = (
                                        to_mm(pad.size.x) / 2
                                        if hasattr(pad, "size") and pad.size
                                        else 0.5
                                    )
                                    ph = (
                                        to_mm(pad.size.y) / 2
                                        if hasattr(pad, "size") and pad.size
                                        else 0.5
                                    )
                                    min_x = min(min_x, px - pw)
                                    min_y = min(min_y, py - ph)
                                    max_x = max(max_x, px + pw)
                                    max_y = max(max_y, py + ph)
                                margin = 0.25  # mm — small margin for component body beyond pads
                                bbox_data = {
                                    "min_x": min_x - margin,
                                    "min_y": min_y - margin,
                                    "max_x": max_x + margin,
                                    "max_y": max_y + margin,
                                    "width": (max_x - min_x) + 2 * margin,
                                    "height": (max_y - min_y) + 2 * margin,
                                    "unit": "mm",
                                }
                        except Exception as e:
                            logger.debug(f"Could not compute bbox from pads: {e}")

                    components.append(
                        {
                            "reference": (
                                fp.reference_field.text.value if fp.reference_field else ""
                            ),
                            "value": fp.value_field.text.value if fp.value_field else "",
                            "footprint": (
                                str(fp.definition.library_link)
                                if fp.definition and hasattr(fp.definition, "library_link")
                                else (
                                    str(fp.definition.id)
                                    if fp.definition and hasattr(fp.definition, "id")
                                    else ""
                                )
                            ),
                            "position": {
                                "x": to_mm(pos.x) if pos else 0,
                                "y": to_mm(pos.y) if pos else 0,
                                "unit": "mm",
                            },
                            "rotation": fp.orientation.degrees if fp.orientation else 0,
                            "layer": str(fp.layer) if hasattr(fp, "layer") else "F.Cu",
                            "id": self._item_id_value(fp),
                            "boundingBox": bbox_data,
                        }
                    )
                except Exception as e:
                    logger.warning(f"Error processing footprint: {e}")
                    continue

            return components

        except Exception as e:
            logger.error(f"Failed to list components: {e}")
            return []

    def place_component(
        self,
        reference: str,
        footprint: str,
        x: float,
        y: float,
        rotation: float = 0,
        layer: str = "F.Cu",
        value: str = "",
    ) -> bool:
        """
        Place a component on the board.

        The component appears immediately in the KiCAD UI.

        This method uses pcbnew only to load and serialize a library footprint.
        The actual board mutation is performed by KiCad's
        ParseAndCreateItemsFromString IPC command, so the item appears
        immediately in the open editor and participates in its undo history.

        Args:
            reference: Component reference designator (e.g., "R1", "U1")
            footprint: Footprint path in format "Library:FootprintName" or just "FootprintName"
            x: X position in mm
            y: Y position in mm
            rotation: Rotation angle in degrees
            layer: Layer name ("F.Cu" for top, "B.Cu" for bottom)
            value: Component value (optional)
        """
        try:
            loaded_fp = self._load_footprint_from_library(footprint)

            if loaded_fp:
                return self._place_loaded_footprint(
                    loaded_fp, reference, x, y, rotation, layer, value
                )

            # An empty placeholder is actively harmful in PCB work: it has no
            # pads and can look like a successfully placed component.  Report
            # the library resolution failure instead.
            logger.error(f"Could not load footprint '{footprint}' from any configured library")
            return False

        except Exception as e:
            logger.error(f"Failed to place component: {e}")
            return False

    def _get_project_directory(self) -> Optional[Path]:
        """Return the directory of the board currently attached to this IPC API."""
        try:
            document = self._get_board().document
            project = getattr(document, "project", None)
            project_path = getattr(project, "path", "") if project else ""
            if project_path:
                path = Path(project_path)
                return path if path.is_dir() else path.parent
        except Exception as e:
            logger.debug(f"Could not determine IPC project directory: {e}")
        return None

    @staticmethod
    def _expand_kicad_uri(uri: str, variables: Dict[str, str]) -> Path:
        """Expand ${VAR} and $(VAR) tokens used in KiCad library tables."""
        expanded = uri
        for name, value in variables.items():
            expanded = expanded.replace(f"${{{name}}}", value).replace(f"$({name})", value)
        return Path(os.path.expandvars(os.path.expanduser(expanded)))

    def _footprint_library_roots(self) -> List[Path]:
        """Return existing roots that may contain ``*.pretty`` libraries."""
        project_dir = self._get_project_directory()
        install_root = Path(sys.executable).resolve().parent.parent
        candidates: List[Path] = [
            install_root / "share" / "kicad" / "footprints",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            / "KiCad"
            / "10.0"
            / "share"
            / "kicad"
            / "footprints",
            Path.home() / "Documents" / "KiCad" / "10.0" / "footprints",
        ]
        configured_root = os.environ.get("KICAD10_FOOTPRINT_DIR")
        if configured_root:
            candidates.insert(0, Path(configured_root))
        if project_dir:
            candidates.insert(0, project_dir)

        roots: List[Path] = []
        for candidate in candidates:
            if str(candidate) and candidate.is_dir() and candidate not in roots:
                roots.append(candidate)
        return roots

    def _library_paths_from_tables(self, nickname: str) -> List[Path]:
        """Resolve a footprint-library nickname from project/global tables."""
        project_dir = self._get_project_directory()
        system_root = Path(sys.executable).resolve().parent.parent / "share" / "kicad"
        variables = dict(os.environ)
        variables.setdefault("KICAD10_FOOTPRINT_DIR", str(system_root / "footprints"))
        if project_dir:
            variables["KIPRJMOD"] = str(project_dir)

        tables: List[Path] = []
        if project_dir:
            tables.append(project_dir / "fp-lib-table")
        appdata = os.environ.get("APPDATA")
        if appdata:
            tables.append(Path(appdata) / "kicad" / "10.0" / "fp-lib-table")

        resolved: List[Path] = []
        entry_pattern = re.compile(
            r'\(lib\s+\(name\s+"([^"]+)"\).*?\(uri\s+"([^"]+)"\)',
            re.DOTALL,
        )
        for table in tables:
            try:
                contents = table.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for name, uri in entry_pattern.findall(contents):
                if name != nickname:
                    continue
                path = self._expand_kicad_uri(uri, variables)
                if path.is_dir() and path not in resolved:
                    resolved.append(path)
        return resolved

    def _load_footprint_from_library(self, footprint_path: str) -> Any:
        """
        Load a footprint from the library using pcbnew SWIG API.

        Args:
            footprint_path: Either "Library:FootprintName" or just "FootprintName"

        Returns:
            pcbnew.FOOTPRINT object or None if not found
        """
        try:
            import pcbnew

            if ":" in footprint_path:
                lib_name, fp_name = footprint_path.split(":", 1)
            else:
                lib_name = None
                fp_name = footprint_path

            # KiCad 10 removed GetGlobalFootprintLib().  The standalone
            # pcbnew Python module also has no initialized global library
            # table, but its file-format plugin can load directly from a
            # .pretty directory.
            io = pcbnew.PCB_IO_KICAD_SEXPR()
            candidate_libraries: List[Path] = []

            if lib_name:
                direct = Path(lib_name)
                if direct.is_dir():
                    candidate_libraries.append(direct)
                candidate_libraries.extend(self._library_paths_from_tables(lib_name))
                for root in self._footprint_library_roots():
                    candidate = root / f"{lib_name}.pretty"
                    if candidate.is_dir() and candidate not in candidate_libraries:
                        candidate_libraries.append(candidate)
            else:
                for root in self._footprint_library_roots():
                    candidate_libraries.extend(
                        path
                        for path in root.glob("*.pretty")
                        if (path / f"{fp_name}.kicad_mod").is_file()
                    )

            for library_path in candidate_libraries:
                try:
                    loaded_fp = io.FootprintLoad(str(library_path), fp_name)
                    if loaded_fp:
                        if lib_name:
                            try:
                                loaded_fp.SetFPIDAsString(f"{lib_name}:{fp_name}")
                            except Exception:
                                pass
                        logger.info(
                            f"Loaded footprint '{fp_name}' from '{library_path}'"
                        )
                        return loaded_fp
                except Exception as e:
                    logger.debug(f"Could not load from {library_path}: {e}")

            logger.warning(f"Footprint '{footprint_path}' not found in any library")
            return None

        except ImportError:
            logger.warning("pcbnew not available - cannot load footprints from library")
            return None
        except Exception as e:
            logger.error(f"Error loading footprint from library: {e}")
            return None

    def _place_loaded_footprint(
        self,
        loaded_fp: Any,
        reference: str,
        x: float,
        y: float,
        rotation: float,
        layer: str,
        value: str,
    ) -> bool:
        """
        Place a loaded pcbnew footprint onto the board.

        Serializes the SWIG-loaded footprint and creates it through IPC.
        """
        try:
            import pcbnew

            board = self._get_board()

            # Set footprint position and properties
            scale = MM_TO_NM
            loaded_fp.SetPosition(pcbnew.VECTOR2I(int(x * scale), int(y * scale)))
            loaded_fp.SetOrientationDegrees(rotation)

            # Set reference
            loaded_fp.SetReference(reference)

            # Set value if provided
            if value:
                loaded_fp.SetValue(value)

            # Set layer (flip if bottom)
            if layer == "B.Cu":
                if not loaded_fp.IsFlipped():
                    loaded_fp.Flip(loaded_fp.GetPosition(), False)

            # Serialize just this footprint and ask the live editor to parse
            # and create it.  This is the KiCad IPC equivalent of Paste.
            formatter = pcbnew.PCB_IO_KICAD_SEXPR()
            formatter.Format(loaded_fp)
            footprint_text = formatter.GetStringOutput(True)

            from kipy.proto.common.commands.editor_commands_pb2 import (
                CreateItemsResponse,
                ParseAndCreateItemsFromString,
            )

            command = ParseAndCreateItemsFromString()
            command.document.CopyFrom(board.document)
            command.contents = footprint_text

            commit = board.begin_commit()
            try:
                response = board.client.send(command, CreateItemsResponse)
                created = [
                    result
                    for result in response.created_items
                    if getattr(result.status, "code", 0) == 1
                ]
                if not created:
                    errors = [
                        getattr(result.status, "error_message", "")
                        for result in response.created_items
                    ]
                    board.drop_commit(commit)
                    # KiCad 10.0.x exposes this command in the protocol but its
                    # PCB handler is a stub that returns an empty response.
                    # Fall back to an on-disk insertion followed by a live
                    # editor reload.  Keep the native path first so this starts
                    # working transactionally as soon as KiCad implements it.
                    logger.info(
                        "ParseAndCreateItemsFromString created no items%s; "
                        "using save/reload compatibility path",
                        f": {'; '.join(filter(None, errors))}" if any(errors) else "",
                    )
                    return self._place_loaded_footprint_via_reload(
                        loaded_fp, reference, x, y, rotation, layer, value
                    )
                board.push_commit(commit, f"Placed component {reference}")
            except Exception:
                board.drop_commit(commit)
                raise

            self._notify(
                "component_placed",
                {
                    "reference": reference,
                    "footprint": loaded_fp.GetFPIDAsString(),
                    "position": {"x": x, "y": y},
                    "rotation": rotation,
                    "layer": layer,
                    "loaded_from_library": True,
                },
            )

            logger.info(
                f"Placed component {reference} ({loaded_fp.GetFPIDAsString()}) at ({x}, {y}) mm"
            )
            return True

        except Exception as e:
            logger.error(f"Error placing loaded footprint: {e}")
            return False

    def _place_loaded_footprint_via_reload(
        self,
        loaded_fp: Any,
        reference: str,
        x: float,
        y: float,
        rotation: float,
        layer: str,
        value: str,
    ) -> bool:
        """KiCad 10.0 compatibility path for creating a full footprint.

        KiCad 10.0 advertises ParseAndCreateItemsFromString but its PCB
        implementation returns an empty response.  Save the live board first,
        update that exact file with pcbnew, then ask the editor to revert to
        the just-written state.  This preserves any edits that were in memory
        before the operation and makes the new component visible immediately.
        """
        try:
            import pcbnew

            board = self._get_board()
            document = board.document
            filename = getattr(document, "board_filename", "")
            project = getattr(document, "project", None)
            project_path = getattr(project, "path", "") if project else ""
            board_path = Path(filename)
            if not board_path.is_absolute():
                board_path = Path(project_path) / board_path
            board_path = board_path.resolve()

            if not board_path.is_file():
                raise FileNotFoundError(f"Open IPC board was not found on disk: {board_path}")

            # Flush every live edit before the file-based insertion.
            board.save()

            pcb_board = pcbnew.LoadBoard(str(board_path))
            if pcb_board is None:
                raise RuntimeError(f"pcbnew could not load board: {board_path}")

            existing_refs = {fp.GetReference() for fp in pcb_board.GetFootprints()}
            if reference in existing_refs:
                raise ValueError(f"Component reference already exists: {reference}")

            pcb_board.Add(loaded_fp)
            with preserve_project_settings(str(board_path)):
                pcbnew.SaveBoard(str(board_path), pcb_board)

            # Reload the externally updated file in the already-open editor.
            board.revert()
            self._board = self._kicad.get_board()

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                matches = [
                    fp
                    for fp in self._board.get_footprints()
                    if fp.reference_field.text.value == reference
                ]
                if matches:
                    self._notify(
                        "component_placed",
                        {
                            "reference": reference,
                            "footprint": loaded_fp.GetFPIDAsString(),
                            "position": {"x": x, "y": y},
                            "rotation": rotation,
                            "layer": layer,
                            "loaded_from_library": True,
                            "compatibility_mode": "save_reload",
                        },
                    )
                    logger.info(
                        "Placed component %s through KiCad 10 save/reload compatibility path",
                        reference,
                    )
                    return True
                time.sleep(0.1)

            raise RuntimeError(
                f"KiCad reloaded the board but component {reference} was not visible through IPC"
            )
        except Exception as e:
            logger.error(f"KiCad 10 footprint compatibility path failed: {e}")
            return False

    def _place_placeholder_footprint(
        self,
        reference: str,
        footprint: str,
        x: float,
        y: float,
        rotation: float,
        layer: str,
        value: str,
    ) -> bool:
        """
        Place a placeholder footprint when library loading fails.

        Creates a basic footprint via IPC with just reference/value fields.
        """
        try:
            from kipy.board_types import FootprintInstance
            from kipy.geometry import Angle, Vector2
            from kipy.proto.board.board_types_pb2 import BoardLayer
            from kipy.util.units import from_mm

            board = self._get_board()

            # Create footprint
            fp = FootprintInstance()
            fp.position = Vector2.from_xy(from_mm(x), from_mm(y))
            fp.orientation = Angle.from_degrees(rotation)

            # Set layer
            if layer == "B.Cu":
                fp.layer = BoardLayer.BL_B_Cu
            else:
                fp.layer = BoardLayer.BL_F_Cu

            # Set reference and value
            if fp.reference_field:
                fp.reference_field.text.value = reference
            if fp.value_field:
                fp.value_field.text.value = value if value else footprint

            # Begin transaction
            commit = board.begin_commit()
            board.create_items(fp)
            board.push_commit(commit, f"Placed component {reference}")

            self._notify(
                "component_placed",
                {
                    "reference": reference,
                    "footprint": footprint,
                    "position": {"x": x, "y": y},
                    "rotation": rotation,
                    "layer": layer,
                    "loaded_from_library": False,
                    "is_placeholder": True,
                },
            )

            logger.info(f"Placed placeholder component {reference} at ({x}, {y}) mm")
            return True

        except Exception as e:
            logger.error(f"Failed to place placeholder component: {e}")
            return False

    def move_component(
        self, reference: str, x: float, y: float, rotation: Optional[float] = None
    ) -> bool:
        """Move a component to a new position (updates UI immediately)."""
        try:
            from kipy.geometry import Angle, Vector2
            from kipy.util.units import from_mm

            board = self._get_board()
            footprints = board.get_footprints()

            # Find the footprint by reference
            target_fp = None
            for fp in footprints:
                if fp.reference_field and fp.reference_field.text.value == reference:
                    target_fp = fp
                    break

            if not target_fp:
                logger.error(f"Component not found: {reference}")
                return False

            # Update position
            target_fp.position = Vector2.from_xy(from_mm(x), from_mm(y))

            if rotation is not None:
                target_fp.orientation = Angle.from_degrees(rotation)

            # Apply changes
            commit = board.begin_commit()
            board.update_items([target_fp])
            board.push_commit(commit, f"Moved component {reference}")

            self._notify(
                "component_moved",
                {"reference": reference, "position": {"x": x, "y": y}, "rotation": rotation},
            )

            return True

        except Exception as e:
            logger.error(f"Failed to move component: {e}")
            return False

    def add_3d_model(
        self,
        references: Any,
        model_path: str,
        offset: Optional[Dict[str, float]] = None,
        scale: Optional[Dict[str, float]] = None,
        rotate: Optional[Dict[str, float]] = None,
        replace: bool = True,
    ) -> Dict[str, Any]:
        """Attach a 3D model to one or more placed footprints (live UI update).

        ``references`` may be a single reference ("D1"), a list (["D1","D2"]),
        or "*"/"all" to apply to every footprint on the board.
        """
        try:
            import kipy.board_types as bt

            board = self._get_board()
            footprints = board.get_footprints()

            if isinstance(references, str):
                wanted = [references]
            else:
                wanted = list(references or [])
            apply_all = any(w in ("*", "all") for w in wanted)

            targets = []
            for fp in footprints:
                ref = fp.reference_field.text.value if fp.reference_field else ""
                if apply_all or ref in wanted:
                    targets.append((ref, fp))

            if not targets:
                return {"success": False, "error": f"No footprints matched: {references}"}

            off = offset or {}
            scl = scale or {}
            rot = rotate or {}

            changed = []
            details = []
            for ref, fp in targets:
                defn = fp.definition
                already = [m for m in defn.models if m.filename == model_path]
                if already and not replace:
                    details.append({"reference": ref, "added": False, "note": "already present"})
                    continue
                if already and replace:
                    keep = [
                        it
                        for it in defn.items
                        if not (isinstance(it, bt.Footprint3DModel) and it.filename == model_path)
                    ]
                    defn.items = keep

                from kipy.geometry import Vector3D

                model = bt.Footprint3DModel()
                model.filename = model_path
                model.visible = True
                model.opacity = 1.0
                # scale defaults to 0 on a fresh proto -> force 1 so the body renders
                model.scale = Vector3D.from_xyz(
                    float(scl.get("x", 1.0)), float(scl.get("y", 1.0)), float(scl.get("z", 1.0))
                )
                model.offset = Vector3D.from_xyz(
                    float(off.get("x", 0.0)), float(off.get("y", 0.0)), float(off.get("z", 0.0))
                )
                model.rotation = Vector3D.from_xyz(
                    float(rot.get("x", 0.0)), float(rot.get("y", 0.0)), float(rot.get("z", 0.0))
                )

                defn.add_item(model)
                changed.append(fp)
                details.append({"reference": ref, "added": True, "replaced": len(already)})

            if changed:
                commit = board.begin_commit()
                board.update_items(changed)
                board.push_commit(commit, f"Added 3D model to {len(changed)} footprint(s)")
                self._notify("model_added", {"count": len(changed), "model": model_path})

            return {
                "success": True,
                "model": model_path,
                "updated": len(changed),
                "details": details,
            }

        except Exception as e:
            logger.error(f"Failed to add 3D model: {e}")
            return {"success": False, "error": str(e)}

    def delete_component(self, reference: str) -> bool:
        """Delete a component from the board."""
        try:
            board = self._get_board()
            footprints = board.get_footprints()

            # Find the footprint by reference
            target_fp = None
            for fp in footprints:
                if fp.reference_field and fp.reference_field.text.value == reference:
                    target_fp = fp
                    break

            if not target_fp:
                logger.error(f"Component not found: {reference}")
                return False

            # Remove component
            commit = board.begin_commit()
            board.remove_items([target_fp])
            board.push_commit(commit, f"Deleted component {reference}")

            self._notify("component_deleted", {"reference": reference})

            return True

        except Exception as e:
            logger.error(f"Failed to delete component: {e}")
            return False

    def add_track(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        width: float = 0.25,
        layer: str = "F.Cu",
        net_name: Optional[str] = None,
    ) -> bool:
        """
        Add a track (trace) to the board.

        The track appears immediately in the KiCAD UI.
        """
        try:
            from kipy.board_types import Track
            from kipy.geometry import Vector2
            from kipy.util.units import from_mm

            board = self._get_board()

            # Create track
            track = Track()
            track.start = Vector2.from_xy(from_mm(start_x), from_mm(start_y))
            track.end = Vector2.from_xy(from_mm(end_x), from_mm(end_y))
            track.width = from_mm(width)

            # Set layer
            track.layer = self._resolve_board_layer(layer, "F.Cu")

            # Set net if specified
            if net_name:
                nets = board.get_nets()
                for net in nets:
                    if net.name == net_name:
                        track.net = net
                        break

            # Add track with transaction
            commit = board.begin_commit()
            board.create_items(track)
            board.push_commit(commit, "Added track")

            self._notify(
                "track_added",
                {
                    "start": {"x": start_x, "y": start_y},
                    "end": {"x": end_x, "y": end_y},
                    "width": width,
                    "layer": layer,
                    "net": net_name,
                },
            )

            logger.info(f"Added track from ({start_x}, {start_y}) to ({end_x}, {end_y}) mm")
            return True

        except Exception as e:
            logger.error(f"Failed to add track: {e}")
            return False

    def add_arc_track(
        self,
        start_x: float,
        start_y: float,
        mid_x: float,
        mid_y: float,
        end_x: float,
        end_y: float,
        width: float = 0.25,
        layer: str = "F.Cu",
        net_name: Optional[str] = None,
    ) -> bool:
        """Add a copper arc track to the board."""
        try:
            from kipy.board_types import ArcTrack
            from kipy.geometry import Vector2
            from kipy.util.units import from_mm

            board = self._get_board()

            arc = ArcTrack()
            arc.start = Vector2.from_xy(from_mm(start_x), from_mm(start_y))
            arc.mid = Vector2.from_xy(from_mm(mid_x), from_mm(mid_y))
            arc.end = Vector2.from_xy(from_mm(end_x), from_mm(end_y))
            arc.width = from_mm(width)

            arc.layer = self._resolve_board_layer(layer, "F.Cu")

            if net_name:
                nets = board.get_nets()
                for net in nets:
                    if net.name == net_name:
                        arc.net = net
                        break

            commit = board.begin_commit()
            board.create_items(arc)
            board.push_commit(commit, "Added arc track")

            self._notify(
                "arc_track_added",
                {
                    "start": {"x": start_x, "y": start_y},
                    "mid": {"x": mid_x, "y": mid_y},
                    "end": {"x": end_x, "y": end_y},
                    "width": width,
                    "layer": layer,
                    "net": net_name,
                },
            )
            logger.info(
                f"Added arc track start=({start_x}, {start_y}) mid=({mid_x}, {mid_y}) end=({end_x}, {end_y}) mm"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to add arc track: {e}")
            return False

    def add_via(
        self,
        x: float,
        y: float,
        diameter: float = 0.8,
        drill: float = 0.4,
        net_name: Optional[str] = None,
        via_type: str = "through",
        from_layer: str = "F.Cu",
        to_layer: str = "B.Cu",
    ) -> bool:
        """
        Add a via to the board.

        The via appears immediately in the KiCAD UI.
        """
        try:
            from kipy.board_types import Via
            from kipy.geometry import Vector2
            from kipy.proto.board.board_types_pb2 import ViaType
            from kipy.util.units import from_mm

            board = self._get_board()

            # Create via
            via = Via()
            via.position = Vector2.from_xy(from_mm(x), from_mm(y))
            via.diameter = from_mm(diameter)
            via.drill_diameter = from_mm(drill)

            # Set via type and its actual drill span.
            type_map = {
                "through": ViaType.VT_THROUGH,
                "blind": ViaType.VT_BLIND_BURIED,
                "buried": ViaType.VT_BLIND_BURIED,
                "blind_buried": ViaType.VT_BLIND_BURIED,
                "micro": ViaType.VT_MICRO,
            }
            via.type = type_map.get(str(via_type).casefold(), ViaType.VT_THROUGH)
            start_layer = self._resolve_board_layer(from_layer, "F.Cu")
            end_layer = self._resolve_board_layer(to_layer, "B.Cu")
            via.padstack.drill.start_layer = start_layer
            via.padstack.drill.end_layer = end_layer
            if via.padstack.copper_layers:
                via.padstack.copper_layers[0].layer = start_layer

            # Set net if specified
            if net_name:
                nets = board.get_nets()
                for net in nets:
                    if net.name == net_name:
                        via.net = net
                        break

            # Add via with transaction
            commit = board.begin_commit()
            board.create_items(via)
            board.push_commit(commit, "Added via")

            self._notify(
                "via_added",
                {
                    "position": {"x": x, "y": y},
                    "diameter": diameter,
                    "drill": drill,
                    "net": net_name,
                    "type": via_type,
                    "from_layer": from_layer,
                    "to_layer": to_layer,
                },
            )

            logger.info(f"Added via at ({x}, {y}) mm")
            return True

        except Exception as e:
            logger.error(f"Failed to add via: {e}")
            return False

    def add_text(
        self,
        text: str,
        x: float,
        y: float,
        layer: str = "F.SilkS",
        size: float = 1.0,
        rotation: float = 0,
        thickness: Optional[float] = None,
        style: str = "normal",
    ) -> bool:
        """Add text to the board."""
        try:
            from kipy.board_types import BoardText
            from kipy.geometry import Vector2
            from kipy.util.units import from_mm

            board = self._get_board()

            # Create text
            board_text = BoardText()
            board_text.value = text
            board_text.position = Vector2.from_xy(from_mm(x), from_mm(y))
            board_text.attributes.angle = rotation
            board_text.attributes.size = Vector2.from_xy(from_mm(size), from_mm(size))
            board_text.attributes.stroke_width = from_mm(
                thickness if thickness is not None else max(size * 0.15, 0.05)
            )
            board_text.attributes.bold = str(style).casefold() == "bold"
            board_text.attributes.italic = str(style).casefold() == "italic"

            board_text.layer = self._resolve_board_layer(layer, "F.SilkS")

            # Add text with transaction
            commit = board.begin_commit()
            board.create_items(board_text)
            board.push_commit(commit, f"Added text: {text}")

            self._notify("text_added", {"text": text, "position": {"x": x, "y": y}, "layer": layer})

            return True

        except Exception as e:
            logger.error(f"Failed to add text: {e}")
            return False

    def get_tracks(self) -> List[Dict[str, Any]]:
        """Get all tracks on the board."""
        try:
            from kipy.util.units import to_mm

            board = self._get_board()
            tracks = board.get_tracks()

            result = []
            for track in tracks:
                try:
                    result.append(
                        {
                            "start": {"x": to_mm(track.start.x), "y": to_mm(track.start.y)},
                            "end": {"x": to_mm(track.end.x), "y": to_mm(track.end.y)},
                            "width": to_mm(track.width),
                            "layer": str(track.layer),
                            "net": track.net.name if track.net else "",
                            "id": self._item_id_value(track),
                        }
                    )
                except Exception as e:
                    logger.warning(f"Error processing track: {e}")
                    continue

            return result

        except Exception as e:
            logger.error(f"Failed to get tracks: {e}")
            return []

    def get_vias(self) -> List[Dict[str, Any]]:
        """Get all vias on the board."""
        try:
            from kipy.util.units import to_mm

            board = self._get_board()
            vias = board.get_vias()

            result = []
            for via in vias:
                try:
                    result.append(
                        {
                            "position": {"x": to_mm(via.position.x), "y": to_mm(via.position.y)},
                            "diameter": to_mm(via.diameter),
                            "drill": to_mm(via.drill_diameter),
                            "net": via.net.name if via.net else "",
                            "type": str(via.type),
                            "id": self._item_id_value(via),
                        }
                    )
                except Exception as e:
                    logger.warning(f"Error processing via: {e}")
                    continue

            return result

        except Exception as e:
            logger.error(f"Failed to get vias: {e}")
            return []

    def get_nets(self) -> List[Dict[str, Any]]:
        """Get all nets on the board."""
        try:
            board = self._get_board()
            nets = board.get_nets()

            result = []
            for net in nets:
                try:
                    result.append(
                        {"name": net.name, "code": net.code if hasattr(net, "code") else 0}
                    )
                except Exception as e:
                    logger.warning(f"Error processing net: {e}")
                    continue

            return result

        except Exception as e:
            logger.error(f"Failed to get nets: {e}")
            return []

    def add_zone(
        self,
        points: List[Dict[str, float]],
        layer: str = "F.Cu",
        net_name: Optional[str] = None,
        clearance: float = 0.5,
        min_thickness: float = 0.25,
        priority: int = 0,
        fill_mode: str = "solid",
        name: str = "",
    ) -> bool:
        """
        Add a copper pour zone to the board.

        The zone appears immediately in the KiCAD UI.

        Args:
            points: List of points defining the zone outline, e.g. [{"x": 0, "y": 0}, ...]
            layer: Layer name (F.Cu, B.Cu, etc.)
            net_name: Net to connect the zone to (e.g., "GND")
            clearance: Clearance from other copper in mm
            min_thickness: Minimum copper thickness in mm
            priority: Zone priority (higher = fills first)
            fill_mode: "solid" or "hatched"
            name: Optional zone name
        """
        try:
            from kipy.board_types import Zone, ZoneFillMode, ZoneType
            from kipy.geometry import PolyLine, PolyLineNode, Vector2
            from kipy.util.units import from_mm

            board = self._get_board()

            if len(points) < 3:
                logger.error("Zone requires at least 3 points")
                return False

            # Create zone
            zone = Zone()
            zone.type = ZoneType.ZT_COPPER

            # Set layer
            zone.layers = [self._resolve_board_layer(layer, "F.Cu")]

            # Set net if specified
            if net_name:
                nets = board.get_nets()
                for net in nets:
                    if net.name == net_name:
                        zone.net = net
                        break

            # Set zone properties
            zone.clearance = from_mm(clearance)
            zone.min_thickness = from_mm(min_thickness)
            zone.priority = priority

            if name:
                zone.name = name

            # Set fill mode. kipy's Zone.fill_mode is a read-only property
            # (its getter reads _proto.copper_settings.fill_mode and there is
            # no setter), so assigning to it raises AttributeError at runtime.
            # Write through the proto, the same way the outline is set below.
            zone._proto.copper_settings.fill_mode = (
                ZoneFillMode.ZFM_HATCHED if fill_mode == "hatched" else ZoneFillMode.ZFM_SOLID
            )

            # Create outline polyline
            outline = PolyLine()
            outline.closed = True

            for point in points:
                x = point.get("x", 0)
                y = point.get("y", 0)
                node = PolyLineNode.from_xy(from_mm(x), from_mm(y))
                outline.append(node)

            # Set the outline on the zone
            # Note: Zone outline is set via the proto directly since kipy
            # doesn't expose a direct setter for creating new zones
            zone._proto.outline.polygons.add()
            zone._proto.outline.polygons[0].outline.CopyFrom(outline._proto)

            # Add zone with transaction
            commit = board.begin_commit()
            board.create_items(zone)
            board.push_commit(commit, f"Added copper zone on {layer}")

            self._notify(
                "zone_added",
                {"layer": layer, "net": net_name, "points": len(points), "priority": priority},
            )

            logger.info(f"Added zone on {layer} with {len(points)} points")
            return True

        except Exception as e:
            logger.error(f"Failed to add zone: {e}")
            return False

    def get_zones(self) -> List[Dict[str, Any]]:
        """Get all zones on the board."""
        try:
            from kipy.util.units import to_mm

            board = self._get_board()
            zones = board.get_zones()

            result = []
            for zone in zones:
                try:
                    result.append(
                        {
                            "name": zone.name if hasattr(zone, "name") else "",
                            "net": zone.net.name if zone.net else "",
                            "priority": zone.priority if hasattr(zone, "priority") else 0,
                            "layers": (
                                [str(l) for l in zone.layers] if hasattr(zone, "layers") else []
                            ),
                            "filled": zone.filled if hasattr(zone, "filled") else False,
                            "id": self._item_id_value(zone),
                        }
                    )
                except Exception as e:
                    logger.warning(f"Error processing zone: {e}")
                    continue

            return result

        except Exception as e:
            logger.error(f"Failed to get zones: {e}")
            return []

    def refill_zones(self) -> bool:
        """Refill all copper pour zones."""
        try:
            board = self._get_board()
            board.refill_zones()
            self._notify("zones_refilled", {})
            return True
        except Exception as e:
            logger.error(f"Failed to refill zones: {e}")
            return False

    def get_selection(self) -> List[Dict[str, Any]]:
        """Get currently selected items in the KiCAD UI."""
        try:
            board = self._get_board()
            selection = board.get_selection()

            result = []
            for item in selection:
                result.append(
                    {"type": type(item).__name__, "id": self._item_id_value(item)}
                )

            return result
        except Exception as e:
            logger.error(f"Failed to get selection: {e}")
            return []

    def clear_selection(self) -> bool:
        """Clear the current selection in KiCAD UI."""
        try:
            board = self._get_board()
            board.clear_selection()
            return True
        except Exception as e:
            logger.error(f"Failed to clear selection: {e}")
            return False


# Export for factory
__all__ = ["IPCBackend", "IPCBoardAPI"]
