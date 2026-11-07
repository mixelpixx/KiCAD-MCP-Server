"""Via census for a PDN review.

``query_traces`` can return every via. A stitched ground net is thousands of
objects, which is too large to read back. This command returns the census a
review actually uses: how many vias, which drill, which layer span, and how
many go through every copper layer.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from commands.analysis_geom import (
    NM_PER_MM,
    as_int,
    back_copper_id,
    bbox_mm,
    front_copper_id,
    is_via,
    iter_board_items,
    layer_fields,
    layer_matches,
    no_board,
    point_in,
    xy_mm,
)

logger = logging.getLogger("kicad_interface")


class ViaSummaryCommands:
    """Read-only via census. Holds the board the interface last loaded."""

    def __init__(self, board: Any) -> None:
        self.board = board

    def summarize_vias(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Count vias. The response is a summary, not a list of via coordinates.

        Filters, all optional: ``net``, ``boundingBox``, ``drillMin``,
        ``drillMax`` (millimetres, inclusive), ``startLayer``, ``endLayer``.
        A layer filter matches the name stored on the board or the canonical
        name (``F.Cu``). A via is through-all-copper when it runs from F.Cu
        to B.Cu.
        """
        if not self.board:
            return no_board()
        net = params.get("net")
        bounding_box = params.get("boundingBox")
        drill_min = params.get("drillMin")
        drill_max = params.get("drillMax")
        start_layer = params.get("startLayer")
        end_layer = params.get("endLayer")

        box = None
        if bounding_box is not None:
            box, error = bbox_mm(bounding_box)
            if error:
                return {"success": False, "message": error, "errorDetails": error}
        try:
            drill_min_mm = None if drill_min is None else float(drill_min)
            drill_max_mm = None if drill_max is None else float(drill_max)
        except (TypeError, ValueError):
            return {
                "success": False,
                "message": "Drill limits must be numbers",
                "errorDetails": "drillMin and drillMax are millimetres",
            }

        try:
            return self._census(net, box, drill_min_mm, drill_max_mm, start_layer, end_layer)
        except Exception as exc:
            logger.error(f"summarize_vias failed: {exc}")
            return {
                "success": False,
                "message": "Failed to summarize vias",
                "errorDetails": str(exc),
            }

    def _census(
        self,
        net: Optional[str],
        box: Optional[Tuple[float, float, float, float]],
        drill_min_mm: Optional[float],
        drill_max_mm: Optional[float],
        start_layer: Optional[str],
        end_layer: Optional[str],
    ) -> Dict[str, Any]:
        drills: Dict[float, int] = {}
        spans: Dict[Tuple[Optional[int], Optional[int], bool], int] = {}
        via_count = 0
        through_count = 0
        front = front_copper_id()
        back = back_copper_id()

        for item in iter_board_items(self.board, "Tracks"):
            if not is_via(item):
                continue
            item_net = self._net_name(item)
            if net and item_net != net:
                continue
            position = xy_mm(self._call(item, "GetPosition"))
            if box is not None and (
                position is None or not point_in(position[0], position[1], box)
            ):
                continue
            top = self._layer_id(item, "TopLayer")
            bottom = self._layer_id(item, "BottomLayer")
            if not layer_matches(
                start_layer if isinstance(start_layer, str) else None, self.board, top
            ):
                continue
            if not layer_matches(
                end_layer if isinstance(end_layer, str) else None, self.board, bottom
            ):
                continue
            drill_mm = self._drill_mm(item)
            if drill_min_mm is not None and (drill_mm is None or drill_mm < drill_min_mm):
                continue
            if drill_max_mm is not None and (drill_mm is None or drill_mm > drill_max_mm):
                continue

            via_count += 1
            through = top == front and bottom == back
            if through:
                through_count += 1
            if drill_mm is not None:
                drills[drill_mm] = drills.get(drill_mm, 0) + 1
            key = (top, bottom, through)
            spans[key] = spans.get(key, 0) + 1

        layer_spans = [
            self._span(top, bottom, through, count)
            for (top, bottom, through), count in spans.items()
        ]
        layer_spans.sort(key=lambda row: (-row["count"], row["start"], row["end"]))
        return {
            "success": True,
            "viaCount": via_count,
            "throughAllCopperCount": through_count,
            "drillHistogram": [
                {"drillMm": drill, "count": drills[drill]} for drill in sorted(drills)
            ],
            "layerSpans": layer_spans,
        }

    def _span(
        self, top: Optional[int], bottom: Optional[int], through: bool, count: int
    ) -> Dict[str, Any]:
        start = layer_fields(self.board, top)
        end = layer_fields(self.board, bottom)
        row: Dict[str, Any] = {
            "start": start.get("name") or start.get("canonical") or "unknown",
            "end": end.get("name") or end.get("canonical") or "unknown",
            "count": count,
            "throughAllCopper": through,
        }
        if "canonical" in start:
            row["canonicalStart"] = start["canonical"]
        if "canonical" in end:
            row["canonicalEnd"] = end["canonical"]
        return row

    def _drill_mm(self, item: Any) -> Optional[float]:
        drill_nm = as_int(self._call(item, "GetDrillValue"))
        if drill_nm is None:
            return None
        return round(drill_nm / NM_PER_MM, 4)

    def _layer_id(self, item: Any, method: str) -> Optional[int]:
        return as_int(self._call(item, method))

    def _net_name(self, item: Any) -> Optional[str]:
        name = self._call(item, "GetNetname")
        return name if isinstance(name, str) else None

    def _call(self, item: Any, method: str) -> Any:
        fn = getattr(item, method, None)
        if not callable(fn):
            return None
        try:
            return fn()
        except TypeError:
            return None
