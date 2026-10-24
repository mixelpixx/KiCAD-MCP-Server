"""Footprints inside a board rectangle.

The schematic region query does not see the PCB. A shield-can review needs
every footprint whose anchor or a pad centre sits inside the can: reference,
value, position, side, and the net on each pad.
"""

import logging
from typing import Any, Dict, List, Optional

from commands.analysis_geom import (
    as_int,
    bbox_mm,
    iter_board_items,
    layer_fields,
    no_board,
    point_in,
    xy_mm,
)

logger = logging.getLogger("kicad_interface")


class RegionFootprintCommands:
    """Read-only footprint query. Holds the board the interface last loaded."""

    def __init__(self, board: Any) -> None:
        self.board = board

    def get_footprints_in_region(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return footprints whose anchor or any pad centre lies in ``boundingBox``.

        The box is inclusive. ``unit`` inside the box defaults to millimetres
        and may be ``mil`` or ``inch``. Every pad of a selected footprint is
        returned, including pads that sit outside the box.
        """
        if not self.board:
            return no_board()
        bounding_box = params.get("boundingBox")
        if bounding_box is None:
            return {
                "success": False,
                "message": "Missing boundingBox",
                "errorDetails": "boundingBox is required",
            }
        box, error = bbox_mm(bounding_box)
        if error:
            return {"success": False, "message": error, "errorDetails": error}
        try:
            footprints = self._collect(box)
        except Exception as exc:
            logger.error(f"get_footprints_in_region failed: {exc}")
            return {
                "success": False,
                "message": "Failed to list footprints in region",
                "errorDetails": str(exc),
            }
        footprints.sort(key=lambda row: row["reference"])
        return {"success": True, "count": len(footprints), "footprints": footprints}

    def _collect(self, box) -> List[Dict[str, Any]]:
        found: List[Dict[str, Any]] = []
        for footprint in iter_board_items(self.board, "GetFootprints"):
            anchor = xy_mm(self._call(footprint, "GetPosition"))
            pads = self._pads(footprint)
            anchor_inside = anchor is not None and point_in(anchor[0], anchor[1], box)
            pad_inside = any(
                pad["x"] is not None and point_in(pad["x"], pad["y"], box) for pad in pads
            )
            if not anchor_inside and not pad_inside:
                continue
            reference = self._text(footprint, "GetReference") or ""
            value = self._text(footprint, "GetValue") or ""
            layer_id = self._layer_id(footprint)
            row: Dict[str, Any] = {
                "reference": reference,
                "value": value,
                "pads": pads,
            }
            if anchor is not None:
                row["x"] = anchor[0]
                row["y"] = anchor[1]
            row.update(layer_fields(self.board, layer_id))
            if "name" in row:
                row["layer"] = row.pop("name")
            found.append(row)
        return found

    def _pads(self, footprint: Any) -> List[Dict[str, Any]]:
        getter = getattr(footprint, "Pads", None)
        if not callable(getter):
            return []
        try:
            raw_pads = list(getter())
        except TypeError:
            return []
        pads: List[Dict[str, Any]] = []
        for pad in raw_pads:
            position = xy_mm(self._call(pad, "GetPosition"))
            entry: Dict[str, Any] = {
                "number": self._pad_number(pad),
                "net": self._text(pad, "GetNetname") or "",
            }
            if position is not None:
                entry["x"] = position[0]
                entry["y"] = position[1]
            else:
                entry["x"] = None
                entry["y"] = None
            pads.append(entry)
        pads.sort(key=lambda row: row["number"])
        return pads

    def _pad_number(self, pad: Any) -> str:
        for method in ("GetNumber", "GetPadName", "GetName"):
            text = self._text(pad, method)
            if text:
                return text
        return ""

    def _layer_id(self, footprint: Any) -> Optional[int]:
        return as_int(self._call(footprint, "GetLayer"))

    def _text(self, item: Any, method: str) -> Optional[str]:
        value = self._call(item, method)
        if isinstance(value, str) and value:
            return value
        return None

    def _call(self, item: Any, method: str) -> Any:
        fn = getattr(item, method, None)
        if not callable(fn):
            return None
        try:
            return fn()
        except TypeError:
            return None
