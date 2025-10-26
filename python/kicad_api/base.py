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

    # Add more abstract methods for routing, DRC, export, etc.
    # These will be filled in during migration


class BackendError(Exception):
    """Base exception for backend errors"""
    pass


class ConnectionError(BackendError):
    """Raised when connection to KiCAD fails"""
    pass


class APINotAvailableError(BackendError):
    """Raised when required API is not available"""
    pass
