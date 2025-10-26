"""
SWIG Backend (Legacy - DEPRECATED)

Uses the legacy SWIG-based pcbnew Python bindings.
This backend wraps the existing implementation for backward compatibility.

WARNING: SWIG bindings are deprecated as of KiCAD 9.0
         and will be removed in KiCAD 10.0.
         Please migrate to IPC backend.
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


class SWIGBackend(KiCADBackend):
    """
    Legacy SWIG-based backend

    Wraps existing commands/project.py, commands/component.py, etc.
    for compatibility during migration period.
    """

    def __init__(self):
        self._connected = False
        self._pcbnew = None
        logger.warning(
            "⚠️ Using DEPRECATED SWIG backend. "
            "This will be removed in KiCAD 10.0. "
            "Please migrate to IPC API."
        )

    def connect(self) -> bool:
        """
        'Connect' to SWIG API (just validates pcbnew import)

        Returns:
            True if pcbnew module available
        """
        try:
            import pcbnew
            self._pcbnew = pcbnew
            version = pcbnew.GetBuildVersion()
            logger.info(f"✓ Connected to pcbnew (SWIG): {version}")
            self._connected = True
            return True
        except ImportError as e:
            logger.error("pcbnew module not found")
            raise APINotAvailableError(
                "SWIG backend requires pcbnew module. "
                "Ensure KiCAD Python module is in PYTHONPATH."
            ) from e

    def disconnect(self) -> None:
        """Disconnect from SWIG API (no-op)"""
        self._connected = False
        self._pcbnew = None
        logger.info("Disconnected from SWIG backend")

    def is_connected(self) -> bool:
        """Check if connected"""
        return self._connected

    def get_version(self) -> str:
        """Get KiCAD version"""
        if not self.is_connected():
            raise ConnectionError("Not connected")

        return self._pcbnew.GetBuildVersion()

    # Project Operations
    def create_project(self, path: Path, name: str) -> Dict[str, Any]:
        """Create project using existing SWIG implementation"""
        if not self.is_connected():
            raise ConnectionError("Not connected")

        # Import existing implementation
        from commands.project import ProjectCommands

        try:
            result = ProjectCommands.create_project(str(path), name)
            return result
        except Exception as e:
            logger.error(f"Failed to create project: {e}")
            raise

    def open_project(self, path: Path) -> Dict[str, Any]:
        """Open project using existing SWIG implementation"""
        if not self.is_connected():
            raise ConnectionError("Not connected")

        from commands.project import ProjectCommands

        try:
            result = ProjectCommands.open_project(str(path))
            return result
        except Exception as e:
            logger.error(f"Failed to open project: {e}")
            raise

    def save_project(self, path: Optional[Path] = None) -> Dict[str, Any]:
        """Save project using existing SWIG implementation"""
        if not self.is_connected():
            raise ConnectionError("Not connected")

        from commands.project import ProjectCommands

        try:
            path_str = str(path) if path else None
            result = ProjectCommands.save_project(path_str)
            return result
        except Exception as e:
            logger.error(f"Failed to save project: {e}")
            raise

    def close_project(self) -> None:
        """Close project (SWIG doesn't have explicit close)"""
        logger.info("Closing project (SWIG backend)")
        # SWIG backend doesn't maintain project state,
        # so this is essentially a no-op

    # Board Operations
    def get_board(self) -> BoardAPI:
        """Get board API"""
        if not self.is_connected():
            raise ConnectionError("Not connected")

        return SWIGBoardAPI(self._pcbnew)


class SWIGBoardAPI(BoardAPI):
    """Board API implementation wrapping SWIG/pcbnew"""

    def __init__(self, pcbnew_module):
        self.pcbnew = pcbnew_module
        self._board = None

    def set_size(self, width: float, height: float, unit: str = "mm") -> bool:
        """Set board size using existing implementation"""
        from commands.board import BoardCommands

        try:
            result = BoardCommands.set_board_size(width, height, unit)
            return result.get("success", False)
        except Exception as e:
            logger.error(f"Failed to set board size: {e}")
            return False

    def get_size(self) -> Dict[str, float]:
        """Get board size"""
        # TODO: Implement using existing SWIG code
        raise NotImplementedError("get_size not yet wrapped")

    def add_layer(self, layer_name: str, layer_type: str) -> bool:
        """Add layer using existing implementation"""
        from commands.board import BoardCommands

        try:
            result = BoardCommands.add_layer(layer_name, layer_type)
            return result.get("success", False)
        except Exception as e:
            logger.error(f"Failed to add layer: {e}")
            return False

    def list_components(self) -> List[Dict[str, Any]]:
        """List components using existing implementation"""
        from commands.component import ComponentCommands

        try:
            result = ComponentCommands.get_component_list()
            if result.get("success"):
                return result.get("components", [])
            return []
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
        layer: str = "F.Cu"
    ) -> bool:
        """Place component using existing implementation"""
        from commands.component import ComponentCommands

        try:
            result = ComponentCommands.place_component(
                component_id=footprint,
                position={"x": x, "y": y, "unit": "mm"},
                reference=reference,
                rotation=rotation,
                layer=layer
            )
            return result.get("success", False)
        except Exception as e:
            logger.error(f"Failed to place component: {e}")
            return False


# This backend serves as a wrapper during the migration period.
# Once IPC backend is fully implemented, this can be deprecated.
