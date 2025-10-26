"""
IPC API Backend (KiCAD 9.0+)

Uses the official kicad-python library for inter-process communication
with a running KiCAD instance.

Note: Requires KiCAD to be running with IPC server enabled:
    Preferences > Plugins > Enable IPC API Server
"""
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from kicad_api.base import (
    KiCADBackend,
    BoardAPI,
    ConnectionError,
    APINotAvailableError
)

logger = logging.getLogger(__name__)


class IPCBackend(KiCADBackend):
    """
    KiCAD IPC API backend

    Communicates with KiCAD via Protocol Buffers over UNIX sockets.
    Requires KiCAD 9.0+ to be running with IPC enabled.
    """

    def __init__(self):
        self.kicad = None
        self._connected = False

    def connect(self) -> bool:
        """
        Connect to running KiCAD instance via IPC

        Returns:
            True if connection successful

        Raises:
            ConnectionError: If connection fails
        """
        try:
            # Import here to allow module to load even without kicad-python
            from kicad import KiCad

            logger.info("Connecting to KiCAD via IPC...")
            self.kicad = KiCad()

            # Verify connection with version check
            version = self.get_version()
            logger.info(f"✓ Connected to KiCAD {version} via IPC")
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

    def disconnect(self) -> None:
        """Disconnect from KiCAD"""
        if self.kicad:
            # kicad-python handles cleanup automatically
            self.kicad = None
            self._connected = False
            logger.info("Disconnected from KiCAD IPC")

    def is_connected(self) -> bool:
        """Check if connected"""
        return self._connected and self.kicad is not None

    def get_version(self) -> str:
        """Get KiCAD version"""
        if not self.kicad:
            raise ConnectionError("Not connected to KiCAD")

        try:
            # Use kicad-python's version checking
            version_info = self.kicad.check_version()
            return str(version_info)
        except Exception as e:
            logger.warning(f"Could not get version: {e}")
            return "unknown"

    # Project Operations
    def create_project(self, path: Path, name: str) -> Dict[str, Any]:
        """
        Create a new KiCAD project

        TODO: Implement with IPC API
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        logger.warning("create_project not yet implemented for IPC backend")
        raise NotImplementedError(
            "Project creation via IPC API is not yet implemented. "
            "This will be added in Week 2-3 migration."
        )

    def open_project(self, path: Path) -> Dict[str, Any]:
        """Open existing project"""
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        logger.warning("open_project not yet implemented for IPC backend")
        raise NotImplementedError("Coming in Week 2-3 migration")

    def save_project(self, path: Optional[Path] = None) -> Dict[str, Any]:
        """Save current project"""
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        logger.warning("save_project not yet implemented for IPC backend")
        raise NotImplementedError("Coming in Week 2-3 migration")

    def close_project(self) -> None:
        """Close current project"""
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        logger.warning("close_project not yet implemented for IPC backend")
        raise NotImplementedError("Coming in Week 2-3 migration")

    # Board Operations
    def get_board(self) -> BoardAPI:
        """Get board API"""
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        return IPCBoardAPI(self.kicad)


class IPCBoardAPI(BoardAPI):
    """Board API implementation for IPC backend"""

    def __init__(self, kicad_instance):
        self.kicad = kicad_instance
        self._board = None

    def _get_board(self):
        """Lazy-load board instance"""
        if self._board is None:
            self._board = self.kicad.get_board()
        return self._board

    def set_size(self, width: float, height: float, unit: str = "mm") -> bool:
        """Set board size"""
        logger.warning("set_size not yet implemented for IPC backend")
        raise NotImplementedError("Coming in Week 2-3 migration")

    def get_size(self) -> Dict[str, float]:
        """Get board size"""
        logger.warning("get_size not yet implemented for IPC backend")
        raise NotImplementedError("Coming in Week 2-3 migration")

    def add_layer(self, layer_name: str, layer_type: str) -> bool:
        """Add layer"""
        logger.warning("add_layer not yet implemented for IPC backend")
        raise NotImplementedError("Coming in Week 2-3 migration")

    def list_components(self) -> List[Dict[str, Any]]:
        """List components"""
        logger.warning("list_components not yet implemented for IPC backend")
        raise NotImplementedError("Coming in Week 2-3 migration")

    def place_component(
        self,
        reference: str,
        footprint: str,
        x: float,
        y: float,
        rotation: float = 0,
        layer: str = "F.Cu"
    ) -> bool:
        """Place component"""
        logger.warning("place_component not yet implemented for IPC backend")
        raise NotImplementedError("Coming in Week 2-3 migration")


# Note: Full implementation will be completed during Week 2-3 migration
# This is a skeleton to establish the pattern
