"""
Abstract base class for KiCAD API backends

Defines the interface that all KiCAD backends must implement.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)


class KiCADBackend(ABC):
    """Abstract base class for KiCAD API backends"""

    @abstractmethod
    def connect(self) -> bool:
        """
        Connect to KiCAD

        Returns:
            True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from KiCAD and clean up resources"""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """
        Check if currently connected to KiCAD

        Returns:
            True if connected, False otherwise
        """
        pass

    @abstractmethod
    def get_version(self) -> str:
        """
        Get KiCAD version

        Returns:
            Version string (e.g., "9.0.0")
        """
        pass

    # Project Operations
    @abstractmethod
    def create_project(self, path: Path, name: str) -> Dict[str, Any]:
        """
        Create a new KiCAD project

        Args:
            path: Directory path for the project
            name: Project name

        Returns:
            Dictionary with project info
        """
        pass

    @abstractmethod
    def open_project(self, path: Path) -> Dict[str, Any]:
        """
        Open an existing KiCAD project

        Args:
            path: Path to .kicad_pro file

        Returns:
            Dictionary with project info
        """
        pass

    @abstractmethod
    def save_project(self, path: Optional[Path] = None) -> Dict[str, Any]:
        """
        Save the current project

        Args:
            path: Optional new path to save to

        Returns:
            Dictionary with save status
        """
        pass

    @abstractmethod
    def close_project(self) -> None:
        """Close the current project"""
        pass

    # Board Operations
    @abstractmethod
    def get_board(self) -> 'BoardAPI':
        """
        Get board API for current project

        Returns:
            BoardAPI instance
        """
        pass


class BoardAPI(ABC):
    """Abstract interface for board operations"""

    @abstractmethod
    def set_size(self, width: float, height: float, unit: str = "mm") -> bool:
        """
        Set board size

        Args:
            width: Board width
            height: Board height
            unit: Unit of measurement ("mm" or "in")

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def get_size(self) -> Dict[str, float]:
        """
        Get current board size

        Returns:
            Dictionary with width, height, unit
        """
        pass

    @abstractmethod
    def add_layer(self, layer_name: str, layer_type: str) -> bool:
        """
        Add a layer to the board

        Args:
            layer_name: Name of the layer
            layer_type: Type ("copper", "technical", "user")

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def list_components(self) -> List[Dict[str, Any]]:
        """
        List all components on the board

        Returns:
            List of component dictionaries
        """
        pass

    @abstractmethod
    def place_component(
        self,
        reference: str,
        footprint: str,
        x: float,
        y: float,
        rotation: float = 0,
        layer: str = "F.Cu"
    ) -> bool:
        """
        Place a component on the board

        Args:
            reference: Component reference (e.g., "R1")
            footprint: Footprint library path
            x: X position (mm)
            y: Y position (mm)
            rotation: Rotation angle (degrees)
            layer: Layer name

        Returns:
            True if successful
        """
        pass

    # Routing Operations
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
        Add a track (trace) to the board

        Args:
            start_x: Start X position (mm)
            start_y: Start Y position (mm)
            end_x: End X position (mm)
            end_y: End Y position (mm)
            width: Track width (mm)
            layer: Layer name
            net_name: Optional net name

        Returns:
            True if successful
        """
        raise NotImplementedError()

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
        Add a via to the board

        Args:
            x: X position (mm)
            y: Y position (mm)
            diameter: Via diameter (mm)
            drill: Drill diameter (mm)
            net_name: Optional net name
            via_type: Via type ("through", "blind", "micro")

        Returns:
            True if successful
        """
        raise NotImplementedError()

    # Transaction support for undo/redo
    def begin_transaction(self, description: str = "MCP Operation") -> None:
        """Begin a transaction for grouping operations."""
        pass  # Optional - not all backends support this

    def commit_transaction(self, description: str = "MCP Operation") -> None:
        """Commit the current transaction."""
        pass  # Optional

    def rollback_transaction(self) -> None:
        """Roll back the current transaction."""
        pass  # Optional

    def save(self) -> bool:
        """Save the board."""
        raise NotImplementedError()

    # Query operations
    def get_tracks(self) -> List[Dict[str, Any]]:
        """Get all tracks on the board."""
        raise NotImplementedError()

    def get_vias(self) -> List[Dict[str, Any]]:
        """Get all vias on the board."""
        raise NotImplementedError()

    def get_nets(self) -> List[Dict[str, Any]]:
        """Get all nets on the board."""
        raise NotImplementedError()

    def get_selection(self) -> List[Dict[str, Any]]:
        """Get currently selected items."""
        raise NotImplementedError()


class BackendError(Exception):
    """Base exception for backend errors"""
    pass


class ConnectionError(BackendError):
    """Raised when connection to KiCAD fails"""
    pass


class APINotAvailableError(BackendError):
    """Raised when required API is not available"""
    pass
