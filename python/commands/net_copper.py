"""Copper summary for one net.

A switch node that exists only as vias must not be poured onto a second
layer. ``query_traces`` and ``query_zones`` can answer that only by
returning every object. This command returns the counts, the layers, and
a short shape: vias only, tracks only, zones only, empty, or mixed.
"""

import logging
from typing import Any, Dict, List, Optional, Set

from commands.analysis_geom import (
    as_int,
    canonical_layer_name,
    is_via,
    iter_board_items,
    nm_to_mm,
    no_board,
    user_layer_name,
    xy_mm,
)

logger = logging.getLogger("kicad_interface")


class _Extent:
    """Inclusive millimetre bounds of the copper that was actually found."""

    def __init__(self) -> None:
        self._xs: List[float] = []
        self._ys: List[float] = []

    def add(self, x: Optional[float], y: Optional[float]) -> None:
        if x is None or y is None:
            return
        self._xs.append(x)
        self._ys.append(y)

    def add_nm_box(self, box: Any) -> None:
        if box is None:
            return
        left = nm_to_mm(self._side(box, "GetLeft"))
        right = nm_to_mm(self._side(box, "GetRight"))
        top = nm_to_mm(self._side(box, "GetTop"))
        bottom = nm_to_mm(self._side(box, "GetBottom"))
        if left is None or right is None or top is None or bottom is None:
            return
        self.add(min(left, right), min(top, bottom))
        self.add(max(left, right), max(top, bottom))

    def as_dict(self) -> Optional[Dict[str, Any]]:
        if not self._xs:
            return None
        return {
            "x1": min(self._xs),
            "y1": min(self._ys),
            "x2": max(self._xs),
            "y2": max(self._ys),
            "unit": "mm",
        }

    @staticmethod
    def _side(box: Any, method: str) -> Any:
        fn = getattr(box, method, None)
        if not callable(fn):
            return None
        try:
            return fn()
        except TypeError:
            return None


def _shape(tracks: int, vias: int, zones: int) -> Dict[str, str]:
    """The short classification a layout check reads before the counts."""
    if tracks == 0 and vias == 0 and zones == 0:
        return {"shape": "empty", "summary": "No tracks, vias, or zones on this net."}
    if tracks == 0 and zones == 0:
        return {"shape": "vias_only", "summary": "Vias only, no tracks and no zones."}
    if vias == 0 and zones == 0:
        return {"shape": "tracks_only", "summary": "Tracks only, no vias and no zones."}
    if tracks == 0 and vias == 0:
        return {"shape": "zones_only", "summary": "Zones only, no tracks and no vias."}
    parts = []
    if tracks:
        parts.append(f"{tracks} track" if tracks == 1 else f"{tracks} tracks")
    if vias:
        parts.append(f"{vias} via" if vias == 1 else f"{vias} vias")
    if zones:
        parts.append(f"{zones} zone" if zones == 1 else f"{zones} zones")
    return {"shape": "mixed", "summary": ", ".join(parts) + "."}


class NetCopperCommands:
    """Read-only per-net copper summary. Holds the board the interface last loaded."""

    def __init__(self, board: Any) -> None:
        self.board = board

    def summarize_net_copper(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Count tracks, vias, and zones on ``net``.

        ``shape`` is ``vias_only`` when the net has vias and neither tracks
        nor zones. The bounding box covers the copper that was found.
        """
        if not self.board:
            return no_board()
        net = params.get("net")
        if not isinstance(net, str) or not net:
            return {
                "success": False,
                "message": "Missing net",
                "errorDetails": "net is required",
            }
        try:
            return self._summarize(net)
        except Exception as exc:
            logger.error(f"summarize_net_copper failed: {exc}")
            return {
                "success": False,
                "message": "Failed to summarize net copper",
                "errorDetails": str(exc),
            }

    def _summarize(self, net: str) -> Dict[str, Any]:
        tracks = 0
        vias = 0
        zones = 0
        layers: Set[str] = set()
        extent = _Extent()

        for item in iter_board_items(self.board, "Tracks"):
            if self._net_name(item) != net:
                continue
            if is_via(item):
                vias += 1
                position = xy_mm(self._call(item, "GetPosition"))
                if position is not None:
                    extent.add(position[0], position[1])
                self._remember_layer(layers, self._layer_id(item, "TopLayer"))
                self._remember_layer(layers, self._layer_id(item, "BottomLayer"))
            else:
                tracks += 1
                self._remember_layer(layers, self._layer_id(item, "GetLayer"))
                for method in ("GetStart", "GetEnd"):
                    position = xy_mm(self._call(item, method))
                    if position is not None:
                        extent.add(position[0], position[1])

        for zone in iter_board_items(self.board, "Zones"):
            if self._net_name(zone) != net:
                continue
            zones += 1
            for name in self._zone_layers(zone):
                layers.add(name)
            box_fn = getattr(zone, "GetBoundingBox", None)
            if callable(box_fn):
                try:
                    extent.add_nm_box(box_fn())
                except TypeError:
                    pass

        result: Dict[str, Any] = {
            "success": True,
            "net": net,
            "trackCount": tracks,
            "viaCount": vias,
            "zoneCount": zones,
            "layers": sorted(layers),
            "boundingBox": extent.as_dict(),
        }
        result.update(_shape(tracks, vias, zones))
        return result

    def _zone_layers(self, zone: Any) -> List[str]:
        names: List[str] = []
        try:
            layer_set = zone.GetLayerSet()
            seq = layer_set.CuStack() if hasattr(layer_set, "CuStack") else layer_set.Seq()
            for layer_id in seq:
                self._append_layer(names, as_int(layer_id))
            if names:
                return names
        except Exception:
            pass
        self._append_layer(names, self._layer_id(zone, "GetLayer"))
        return names

    def _remember_layer(self, layers: Set[str], layer_id: Optional[int]) -> None:
        name = user_layer_name(self.board, layer_id) or canonical_layer_name(self.board, layer_id)
        if name:
            layers.add(name)

    def _append_layer(self, names: List[str], layer_id: Optional[int]) -> None:
        name = user_layer_name(self.board, layer_id) or canonical_layer_name(self.board, layer_id)
        if name and name not in names:
            names.append(name)

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
