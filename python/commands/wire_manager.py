"""
Wire Manager for KiCad Schematics

Delegates to sexp_writer for text-based file manipulation that preserves
KiCad's native formatting. This module provides the same API as before
but no longer uses sexpdata round-trips (which collapsed formatting).
"""

import logging
from pathlib import Path
from typing import List, Optional

from commands import sexp_writer

logger = logging.getLogger("kicad_interface")


class WireManager:
    """Manage wires in KiCad schematics using text-based manipulation"""

    @staticmethod
    def add_wire(
        schematic_path: Path,
        start_point: List[float],
        end_point: List[float],
        stroke_width: float = 0,
        stroke_type: str = "default",
    ) -> bool:
        """Add a wire to the schematic."""
        return sexp_writer.add_wire(
            schematic_path, start_point, end_point, stroke_width, stroke_type
        )

    @staticmethod
    def add_polyline_wire(
        schematic_path: Path,
        points: List[List[float]],
        stroke_width: float = 0,
        stroke_type: str = "default",
    ) -> bool:
        """Add a multi-segment wire (polyline) to the schematic."""
        return sexp_writer.add_polyline_wire(
            schematic_path, points, stroke_width, stroke_type
        )

    @staticmethod
    def add_label(
        schematic_path: Path,
        text: str,
        position: List[float],
        label_type: str = "label",
        orientation: int = 0,
        shape: Optional[str] = None,
    ) -> bool:
        """Add a net label to the schematic."""
        return sexp_writer.add_label(
            schematic_path, text, position, label_type, orientation, shape
        )

    @staticmethod
    def add_junction(
        schematic_path: Path, position: List[float], diameter: float = 0
    ) -> bool:
        """Add a junction (connection dot) to the schematic."""
        return sexp_writer.add_junction(schematic_path, position, diameter)

    @staticmethod
    def add_no_connect(schematic_path: Path, position: List[float]) -> bool:
        """Add a no-connect flag to the schematic."""
        return sexp_writer.add_no_connect(schematic_path, position)

    @staticmethod
    def delete_wire(
        schematic_path: Path,
        start_point: List[float],
        end_point: List[float],
        tolerance: float = 0.5,
    ) -> bool:
        """Delete a wire matching given start/end coordinates."""
        return sexp_writer.delete_wire(
            schematic_path, start_point, end_point, tolerance
        )

    @staticmethod
    def delete_label(
        schematic_path: Path,
        net_name: str,
        position: Optional[List[float]] = None,
        tolerance: float = 0.5,
    ) -> bool:
        """Delete a net label by name (and optionally position)."""
        return sexp_writer.delete_label(
            schematic_path, net_name, position, tolerance
        )

    @staticmethod
    def create_orthogonal_path(
        start: List[float], end: List[float], prefer_horizontal_first: bool = True
    ) -> List[List[float]]:
        """Create an orthogonal (right-angle) path between two points."""
        return sexp_writer.create_orthogonal_path(start, end, prefer_horizontal_first)
