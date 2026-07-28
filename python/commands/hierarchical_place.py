"""Hierarchy-aware footprint placement command.

A thin MCP wrapper around the vendored HierPlace algorithm (see _hierplace.py).
It clusters a board's footprints by their schematic-sheet hierarchy, so that
after sync_schematic_to_board dumps every footprint at the origin, each
functional block lands together -- a sane starting point for manual placement.
"""

import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("kicad_interface")


class HierarchicalPlaceCommands:
    """Handler for hierarchy-aware footprint placement on a .kicad_pcb file."""

    def hierarchical_place(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Cluster a board's footprints by schematic hierarchy (HierPlace).

        File-based: reads boardPath, repacks the footprints, writes boardPath
        back to disk. Save any in-memory board edits first. Locked footprints
        are left untouched.
        """
        logger.info("Hierarchical place: clustering footprints by schematic hierarchy")
        try:
            board_path = params.get("boardPath")
            if not board_path:
                return {"success": False, "message": "boardPath is required"}
            path = Path(board_path)
            if not path.exists():
                return {"success": False, "message": f"board file not found: {board_path}"}

            try:
                import pcbnew
            except Exception as e:
                return {"success": False, "message": f"pcbnew not available: {e}"}
            try:
                from commands._hierplace import hier_place
            except Exception as e:
                return {"success": False, "message": f"failed to load HierPlace algorithm: {e}"}

            brd = pcbnew.LoadBoard(str(path))
            footprint_count = len(list(brd.GetFootprints()))
            if footprint_count == 0:
                return {
                    "success": True,
                    "placed_count": 0,
                    "footprint_count": 0,
                    "message": "no footprints on the board (run sync_schematic_to_board first)",
                }

            placed = hier_place(brd)
            pcbnew.SaveBoard(str(path), brd)

            return {
                "success": True,
                "placed_count": placed,
                "footprint_count": footprint_count,
                "message": (
                    f"Hierarchically placed {placed} footprint(s) in {path.name}; "
                    "clustered by schematic sheet"
                ),
            }

        except Exception as e:
            logger.error(f"Error in hierarchical_place: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}
