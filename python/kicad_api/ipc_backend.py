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
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable

from kicad_api.base import (
    KiCADBackend,
    BoardAPI,
    ConnectionError,
    APINotAvailableError
)

logger = logging.getLogger(__name__)

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

    def __init__(self):
        self._kicad = None
        self._connected = False
        self._version = None
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
                # Common socket locations (platform-specific)
                socket_paths_to_try = []

                # Unix-specific socket paths (Linux/macOS)
                if hasattr(os, 'getuid'):
                    socket_paths_to_try.extend([
                        'ipc:///tmp/kicad/api.sock',  # Linux default
                        f'ipc:///run/user/{os.getuid()}/kicad/api.sock',  # XDG runtime
                    ])

                # Always try auto-detect last (works on all platforms including Windows)
                socket_paths_to_try.append(None)

            last_error = None
            for path in socket_paths_to_try:
                try:
                    if path:
                        logger.debug(f"Trying socket path: {path}")
                        self._kicad = KiCad(socket_path=path)
                    else:
                        logger.debug("Trying auto-detection")
                        self._kicad = KiCad()

                    # Verify connection with ping (ping returns None on success)
                    self._kicad.ping()
                    logger.info(f"Connected via socket: {path or 'auto-detected'}")
                    break
                except Exception as e:
                    last_error = e
                    logger.debug(f"Failed to connect via {path}: {e}")
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
                "IPC backend requires kicad-python. "
                "Install with: pip install kicad-python"
            ) from e
        except Exception as e:
            logger.error(f"Failed to connect via IPC: {e}")
            logger.info(
                "Ensure KiCAD is running with IPC enabled: "
                "Preferences > Plugins > Enable IPC API Server"
            )
            raise ConnectionError(f"IPC connection failed: {e}") from e

    def _get_kicad_version(self) -> str:
        """Get KiCAD version string."""
        try:
            if self._kicad.check_version():
                return self._kicad.get_api_version()
            return "9.0+ (version mismatch)"
        except Exception:
            return "unknown"

    def disconnect(self) -> None:
        """Disconnect from KiCAD."""
        if self._kicad:
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
            "suggestion": "Open KiCAD and create a new project, or use SWIG backend"
        }

    def open_project(self, path: Path) -> Dict[str, Any]:
        """Open existing project via IPC."""
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        try:
            # Check for open documents
            documents = self._kicad.get_open_documents()

            # Look for matching project
            path_str = str(path)
            for doc in documents:
                if path_str in str(doc):
                    return {
                        "success": True,
                        "message": f"Project already open: {path}",
                        "path": str(path)
                    }

            return {
                "success": False,
                "message": "Project not currently open in KiCAD",
                "suggestion": "Open the project in KiCAD first, then connect via IPC"
            }

        except Exception as e:
            logger.error(f"Failed to check project: {e}")
            return {
                "success": False,
                "message": "Failed to check project",
                "errorDetails": str(e)
            }

    def save_project(self, path: Optional[Path] = None) -> Dict[str, Any]:
        """Save current project via IPC."""
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        try:
            board = self._kicad.get_board()
            if path:
                board.save_as(str(path))
            else:
                board.save()

            self._notify_change("save", {"path": str(path) if path else "current"})

            return {
                "success": True,
                "message": "Project saved successfully"
            }
        except Exception as e:
            logger.error(f"Failed to save project: {e}")
            return {
                "success": False,
                "message": "Failed to save project",
                "errorDetails": str(e)
            }

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

    def __init__(self, kicad_instance, notify_callback: Callable):
        self._kicad = kicad_instance
        self._board = None
        self._notify = notify_callback
        self._current_commit = None

    def _get_board(self):
        """Get board instance, connecting if needed."""
        if self._board is None:
            try:
                self._board = self._kicad.get_board()
            except Exception as e:
                logger.error(f"Failed to get board: {e}")
                raise ConnectionError(f"No board open in KiCAD: {e}")
        return self._board

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
            from kipy.proto.board.board_types_pb2 import BoardLayer

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
            rect.start = Vector2.from_xy(0, 0)
            rect.end = Vector2.from_xy(w, h)
            rect.layer = BoardLayer.BL_Edge_Cuts
            rect.width = from_mm(0.1)  # Standard edge cut width

            # Begin transaction for undo support
            commit = board.begin_commit()
            board.create_items(rect)
            board.push_commit(commit, f"Set board size to {width}x{height} {unit}")

            self._notify("board_size", {"width": width, "height": height, "unit": unit})

            return True

        except Exception as e:
            logger.error(f"Failed to set board size: {e}")
            return False

    def get_size(self) -> Dict[str, float]:
        """Get current board size from bounding box."""
        try:
            board = self._get_board()

            # Get shapes on Edge.Cuts layer to determine board size
            shapes = board.get_shapes()

            if not shapes:
                return {"width": 0, "height": 0, "unit": "mm"}

            # Find bounding box of edge cuts
            from kipy.util.units import to_mm

            min_x = min_y = float('inf')
            max_x = max_y = float('-inf')

            for shape in shapes:
                # Check if on Edge.Cuts layer
                bbox = board.get_item_bounding_box(shape)
                if bbox:
                    min_x = min(min_x, bbox.min.x)
                    min_y = min(min_y, bbox.min.y)
                    max_x = max(max_x, bbox.max.x)
                    max_y = max(max_y, bbox.max.y)

            if min_x == float('inf'):
                return {"width": 0, "height": 0, "unit": "mm"}

            return {
                "width": to_mm(max_x - min_x),
                "height": to_mm(max_y - min_y),
                "unit": "mm"
            }

        except Exception as e:
            logger.error(f"Failed to get board size: {e}")
            return {"width": 0, "height": 0, "unit": "mm", "error": str(e)}

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
                    components.append({
                        "reference": fp.reference_field.text.value if fp.reference_field else "",
                        "value": fp.value_field.text.value if fp.value_field else "",
                        "footprint": str(fp.definition.library_link) if fp.definition else "",
                        "position": {
                            "x": to_mm(pos.x) if pos else 0,
                            "y": to_mm(pos.y) if pos else 0,
                            "unit": "mm"
                        },
                        "rotation": fp.orientation.degrees if fp.orientation else 0,
                        "layer": str(fp.layer) if hasattr(fp, 'layer') else "F.Cu",
                        "id": str(fp.id) if hasattr(fp, 'id') else ""
                    })
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
        value: str = ""
    ) -> bool:
        """
        Place a component on the board.

        The component appears immediately in the KiCAD UI.

        This method uses a hybrid approach:
        1. Load the footprint definition from the library using pcbnew (SWIG)
        2. Place it on the board via IPC for real-time UI updates

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
            # First, try to load the footprint from library using pcbnew SWIG
            loaded_fp = self._load_footprint_from_library(footprint)

            if loaded_fp:
                # We have the footprint from the library - place it via SWIG
                # then sync to IPC for UI update
                return self._place_loaded_footprint(
                    loaded_fp, reference, x, y, rotation, layer, value
                )
            else:
                # Fallback: Create a basic placeholder footprint via IPC
                logger.warning(f"Could not load footprint '{footprint}' from library, creating placeholder")
                return self._place_placeholder_footprint(
                    reference, footprint, x, y, rotation, layer, value
                )

        except Exception as e:
            logger.error(f"Failed to place component: {e}")
            return False

    def _load_footprint_from_library(self, footprint_path: str):
        """
        Load a footprint from the library using pcbnew SWIG API.

        Args:
            footprint_path: Either "Library:FootprintName" or just "FootprintName"

        Returns:
            pcbnew.FOOTPRINT object or None if not found
        """
        try:
            import pcbnew

            # Parse library and footprint name
            if ':' in footprint_path:
                lib_name, fp_name = footprint_path.split(':', 1)
            else:
                # Try to find the footprint in all libraries
                lib_name = None
                fp_name = footprint_path

            # Get the footprint library table
            fp_lib_table = pcbnew.GetGlobalFootprintLib()

            if lib_name:
                # Load from specific library
                try:
                    loaded_fp = pcbnew.FootprintLoad(fp_lib_table, lib_name, fp_name)
                    if loaded_fp:
                        logger.info(f"Loaded footprint '{fp_name}' from library '{lib_name}'")
                        return loaded_fp
                except Exception as e:
                    logger.warning(f"Could not load from {lib_name}: {e}")
            else:
                # Search all libraries for the footprint
                lib_names = fp_lib_table.GetLogicalLibs()
                for lib in lib_names:
                    try:
                        loaded_fp = pcbnew.FootprintLoad(fp_lib_table, lib, fp_name)
                        if loaded_fp:
                            logger.info(f"Found footprint '{fp_name}' in library '{lib}'")
                            return loaded_fp
                    except:
                        continue

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
        loaded_fp,
        reference: str,
        x: float,
        y: float,
        rotation: float,
        layer: str,
        value: str
    ) -> bool:
        """
        Place a loaded pcbnew footprint onto the board.

        Uses SWIG to add the footprint, then notifies for IPC sync.
        """
        try:
            import pcbnew

            # Get the board file path from IPC to load via pcbnew
            board = self._get_board()

            # Get the pcbnew board instance
            # We need to get the actual board file path
            project = board.get_project()
            board_path = None

            # Try to get the board path from kipy
            try:
                docs = self._kicad.get_open_documents()
                for doc in docs:
                    if hasattr(doc, 'path') and str(doc.path).endswith('.kicad_pcb'):
                        board_path = str(doc.path)
                        break
            except Exception as e:
                logger.debug(f"Could not get board path from IPC: {e}")

            if board_path and os.path.exists(board_path):
                # Load board via pcbnew
                pcb_board = pcbnew.LoadBoard(board_path)
            else:
                # Try to get from pcbnew directly
                pcb_board = pcbnew.GetBoard()

            if not pcb_board:
                logger.error("Could not get pcbnew board instance")
                return self._place_placeholder_footprint(
                    reference, "", x, y, rotation, layer, value
                )

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

            # Add to board
            pcb_board.Add(loaded_fp)

            # Save the board so IPC can see the changes
            pcbnew.SaveBoard(board_path, pcb_board)

            # Refresh IPC view
            try:
                board.revert()  # Reload from disk to sync IPC
            except Exception as e:
                logger.debug(f"Could not refresh IPC board: {e}")

            self._notify("component_placed", {
                "reference": reference,
                "footprint": loaded_fp.GetFPIDAsString(),
                "position": {"x": x, "y": y},
                "rotation": rotation,
                "layer": layer,
                "loaded_from_library": True
            })

            logger.info(f"Placed component {reference} ({loaded_fp.GetFPIDAsString()}) at ({x}, {y}) mm")
            return True

        except Exception as e:
            logger.error(f"Error placing loaded footprint: {e}")
            # Fall back to placeholder
            return self._place_placeholder_footprint(
                reference, "", x, y, rotation, layer, value
            )

    def _place_placeholder_footprint(
        self,
        reference: str,
        footprint: str,
        x: float,
        y: float,
        rotation: float,
        layer: str,
        value: str
    ) -> bool:
        """
        Place a placeholder footprint when library loading fails.

        Creates a basic footprint via IPC with just reference/value fields.
        """
        try:
            from kipy.board_types import Footprint
            from kipy.geometry import Vector2, Angle
            from kipy.util.units import from_mm
            from kipy.proto.board.board_types_pb2 import BoardLayer

            board = self._get_board()

            # Create footprint
            fp = Footprint()
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

            self._notify("component_placed", {
                "reference": reference,
                "footprint": footprint,
                "position": {"x": x, "y": y},
                "rotation": rotation,
                "layer": layer,
                "loaded_from_library": False,
                "is_placeholder": True
            })

            logger.info(f"Placed placeholder component {reference} at ({x}, {y}) mm")
            return True

        except Exception as e:
            logger.error(f"Failed to place placeholder component: {e}")
            return False

    def move_component(self, reference: str, x: float, y: float, rotation: Optional[float] = None) -> bool:
        """Move a component to a new position (updates UI immediately)."""
        try:
            from kipy.geometry import Vector2, Angle
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

            self._notify("component_moved", {
                "reference": reference,
                "position": {"x": x, "y": y},
                "rotation": rotation
            })

            return True

        except Exception as e:
            logger.error(f"Failed to move component: {e}")
            return False

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
        net_name: Optional[str] = None
    ) -> bool:
        """
        Add a track (trace) to the board.

        The track appears immediately in the KiCAD UI.
        """
        try:
            from kipy.board_types import Track
            from kipy.geometry import Vector2
            from kipy.util.units import from_mm
            from kipy.proto.board.board_types_pb2 import BoardLayer

            board = self._get_board()

            # Create track
            track = Track()
            track.start = Vector2.from_xy(from_mm(start_x), from_mm(start_y))
            track.end = Vector2.from_xy(from_mm(end_x), from_mm(end_y))
            track.width = from_mm(width)

            # Set layer
            layer_map = {
                "F.Cu": BoardLayer.BL_F_Cu,
                "B.Cu": BoardLayer.BL_B_Cu,
                "In1.Cu": BoardLayer.BL_In1_Cu,
                "In2.Cu": BoardLayer.BL_In2_Cu,
            }
            track.layer = layer_map.get(layer, BoardLayer.BL_F_Cu)

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

            self._notify("track_added", {
                "start": {"x": start_x, "y": start_y},
                "end": {"x": end_x, "y": end_y},
                "width": width,
                "layer": layer,
                "net": net_name
            })

            logger.info(f"Added track from ({start_x}, {start_y}) to ({end_x}, {end_y}) mm")
            return True

        except Exception as e:
            logger.error(f"Failed to add track: {e}")
            return False

    def add_via(
        self,
        x: float,
        y: float,
        diameter: float = 0.8,
        drill: float = 0.4,
        net_name: Optional[str] = None,
        via_type: str = "through"
    ) -> bool:
        """
        Add a via to the board.

        The via appears immediately in the KiCAD UI.
        """
        try:
            from kipy.board_types import Via
            from kipy.geometry import Vector2
            from kipy.util.units import from_mm
            from kipy.proto.board.board_types_pb2 import ViaType

            board = self._get_board()

            # Create via
            via = Via()
            via.position = Vector2.from_xy(from_mm(x), from_mm(y))
            via.diameter = from_mm(diameter)
            via.drill_diameter = from_mm(drill)

            # Set via type (enum values: VT_THROUGH=1, VT_BLIND_BURIED=2, VT_MICRO=3)
            type_map = {
                "through": ViaType.VT_THROUGH,
                "blind": ViaType.VT_BLIND_BURIED,
                "micro": ViaType.VT_MICRO,
            }
            via.type = type_map.get(via_type, ViaType.VT_THROUGH)

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

            self._notify("via_added", {
                "position": {"x": x, "y": y},
                "diameter": diameter,
                "drill": drill,
                "net": net_name,
                "type": via_type
            })

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
        rotation: float = 0
    ) -> bool:
        """Add text to the board."""
        try:
            from kipy.board_types import BoardText
            from kipy.geometry import Vector2, Angle
            from kipy.util.units import from_mm
            from kipy.proto.board.board_types_pb2 import BoardLayer

            board = self._get_board()

            # Create text
            board_text = BoardText()
            board_text.value = text
            board_text.position = Vector2.from_xy(from_mm(x), from_mm(y))
            board_text.angle = Angle.from_degrees(rotation)

            # Set layer
            layer_map = {
                "F.SilkS": BoardLayer.BL_F_SilkS,
                "B.SilkS": BoardLayer.BL_B_SilkS,
                "F.Cu": BoardLayer.BL_F_Cu,
                "B.Cu": BoardLayer.BL_B_Cu,
            }
            board_text.layer = layer_map.get(layer, BoardLayer.BL_F_SilkS)

            # Add text with transaction
            commit = board.begin_commit()
            board.create_items(board_text)
            board.push_commit(commit, f"Added text: {text}")

            self._notify("text_added", {
                "text": text,
                "position": {"x": x, "y": y},
                "layer": layer
            })

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
                    result.append({
                        "start": {
                            "x": to_mm(track.start.x),
                            "y": to_mm(track.start.y)
                        },
                        "end": {
                            "x": to_mm(track.end.x),
                            "y": to_mm(track.end.y)
                        },
                        "width": to_mm(track.width),
                        "layer": str(track.layer),
                        "net": track.net.name if track.net else "",
                        "id": str(track.id) if hasattr(track, 'id') else ""
                    })
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
                    result.append({
                        "position": {
                            "x": to_mm(via.position.x),
                            "y": to_mm(via.position.y)
                        },
                        "diameter": to_mm(via.diameter),
                        "drill": to_mm(via.drill_diameter),
                        "net": via.net.name if via.net else "",
                        "type": str(via.type),
                        "id": str(via.id) if hasattr(via, 'id') else ""
                    })
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
                    result.append({
                        "name": net.name,
                        "code": net.code if hasattr(net, 'code') else 0
                    })
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
        name: str = ""
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
            from kipy.proto.board.board_types_pb2 import BoardLayer

            board = self._get_board()

            if len(points) < 3:
                logger.error("Zone requires at least 3 points")
                return False

            # Create zone
            zone = Zone()
            zone.type = ZoneType.ZT_COPPER

            # Set layer
            layer_map = {
                "F.Cu": BoardLayer.BL_F_Cu,
                "B.Cu": BoardLayer.BL_B_Cu,
                "In1.Cu": BoardLayer.BL_In1_Cu,
                "In2.Cu": BoardLayer.BL_In2_Cu,
                "In3.Cu": BoardLayer.BL_In3_Cu,
                "In4.Cu": BoardLayer.BL_In4_Cu,
            }
            zone.layers = [layer_map.get(layer, BoardLayer.BL_F_Cu)]

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

            # Set fill mode
            if fill_mode == "hatched":
                zone.fill_mode = ZoneFillMode.ZFM_HATCHED
            else:
                zone.fill_mode = ZoneFillMode.ZFM_SOLID

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

            self._notify("zone_added", {
                "layer": layer,
                "net": net_name,
                "points": len(points),
                "priority": priority
            })

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
                    result.append({
                        "name": zone.name if hasattr(zone, 'name') else "",
                        "net": zone.net.name if zone.net else "",
                        "priority": zone.priority if hasattr(zone, 'priority') else 0,
                        "layers": [str(l) for l in zone.layers] if hasattr(zone, 'layers') else [],
                        "filled": zone.filled if hasattr(zone, 'filled') else False,
                        "id": str(zone.id) if hasattr(zone, 'id') else ""
                    })
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
                result.append({
                    "type": type(item).__name__,
                    "id": str(item.id) if hasattr(item, 'id') else ""
                })

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
__all__ = ['IPCBackend', 'IPCBoardAPI']
