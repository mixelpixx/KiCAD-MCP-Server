"""
Routing-related command implementations for KiCAD interface
"""

import os
import pcbnew
import logging
import math
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger('kicad_interface')

class RoutingCommands:
    """Handles routing-related KiCAD operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

    def add_net(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new net to the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            name = params.get("name")
            net_class = params.get("class")

            if not name:
                return {
                    "success": False,
                    "message": "Missing net name",
                    "errorDetails": "name parameter is required"
                }

            # Create new net
            netinfo = self.board.GetNetInfo()
            nets_map = netinfo.NetsByName()
            if nets_map.has_key(name):
                net = nets_map[name]
            else:
                net = pcbnew.NETINFO_ITEM(self.board, name)
                self.board.Add(net)

            # Set net class if provided
            if net_class:
                net_classes = self.board.GetNetClasses()
                if net_classes.Find(net_class):
                    net.SetClass(net_classes.Find(net_class))

            return {
                "success": True,
                "message": f"Added net: {name}",
                "net": {
                    "name": name,
                    "class": net_class if net_class else "Default",
                    "netcode": net.GetNetCode()
                }
            }

        except Exception as e:
            logger.error(f"Error adding net: {str(e)}")
            return {
                "success": False,
                "message": "Failed to add net",
                "errorDetails": str(e)
            }

    def route_trace(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route a trace between two points or pads"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            start = params.get("start")
            end = params.get("end")
            layer = params.get("layer", "F.Cu")
            width = params.get("width")
            net = params.get("net")
            via = params.get("via", False)

            if not start or not end:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "start and end points are required"
                }

            # Get layer ID
            layer_id = self.board.GetLayerID(layer)
            if layer_id < 0:
                return {
                    "success": False,
                    "message": "Invalid layer",
                    "errorDetails": f"Layer '{layer}' does not exist"
                }

            # Get start point
            start_point = self._get_point(start)
            end_point = self._get_point(end)

            # Create track segment
            track = pcbnew.PCB_TRACK(self.board)
            track.SetStart(start_point)
            track.SetEnd(end_point)
            track.SetLayer(layer_id)

            # Set width (default to board's current track width)
            if width:
                track.SetWidth(int(width * 1000000))  # Convert mm to nm
            else:
                track.SetWidth(self.board.GetDesignSettings().GetCurrentTrackWidth())

            # Set net if provided
            if net:
                netinfo = self.board.GetNetInfo()
                nets_map = netinfo.NetsByName()
                if nets_map.has_key(net):
                    net_obj = nets_map[net]
                    track.SetNet(net_obj)

            # Add track to board
            self.board.Add(track)

            # Add via if requested and net is specified
            if via and net:
                via_point = end_point
                self.add_via({
                    "position": {
                        "x": via_point.x / 1000000,
                        "y": via_point.y / 1000000,
                        "unit": "mm"
                    },
                    "net": net
                })

            return {
                "success": True,
                "message": "Added trace",
                "trace": {
                    "start": {
                        "x": start_point.x / 1000000,
                        "y": start_point.y / 1000000,
                        "unit": "mm"
                    },
                    "end": {
                        "x": end_point.x / 1000000,
                        "y": end_point.y / 1000000,
                        "unit": "mm"
                    },
                    "layer": layer,
                    "width": track.GetWidth() / 1000000,
                    "net": net
                }
            }

        except Exception as e:
            logger.error(f"Error routing trace: {str(e)}")
            return {
                "success": False,
                "message": "Failed to route trace",
                "errorDetails": str(e)
            }

    def add_via(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a via at the specified location"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            position = params.get("position")
            size = params.get("size")
            drill = params.get("drill")
            net = params.get("net")
            from_layer = params.get("from_layer", "F.Cu")
            to_layer = params.get("to_layer", "B.Cu")

            if not position:
                return {
                    "success": False,
                    "message": "Missing position",
                    "errorDetails": "position parameter is required"
                }

            # Create via
            via = pcbnew.PCB_VIA(self.board)
            
            # Set position
            scale = 1000000 if position["unit"] == "mm" else 25400000  # mm or inch to nm
            x_nm = int(position["x"] * scale)
            y_nm = int(position["y"] * scale)
            via.SetPosition(pcbnew.VECTOR2I(x_nm, y_nm))

            # Set size and drill (default to board's current via settings)
            design_settings = self.board.GetDesignSettings()
            via.SetWidth(int(size * 1000000) if size else design_settings.GetCurrentViaSize())
            via.SetDrill(int(drill * 1000000) if drill else design_settings.GetCurrentViaDrill())

            # Set layers
            from_id = self.board.GetLayerID(from_layer)
            to_id = self.board.GetLayerID(to_layer)
            if from_id < 0 or to_id < 0:
                return {
                    "success": False,
                    "message": "Invalid layer",
                    "errorDetails": "Specified layers do not exist"
                }
            via.SetLayerPair(from_id, to_id)

            # Set net if provided
            if net:
                netinfo = self.board.GetNetInfo()
                nets_map = netinfo.NetsByName()
                if nets_map.has_key(net):
                    net_obj = nets_map[net]
                    via.SetNet(net_obj)

            # Add via to board
            self.board.Add(via)

            return {
                "success": True,
                "message": "Added via",
                "via": {
                    "position": {
                        "x": position["x"],
                        "y": position["y"],
                        "unit": position["unit"]
                    },
                    "size": via.GetWidth() / 1000000,
                    "drill": via.GetDrill() / 1000000,
                    "from_layer": from_layer,
                    "to_layer": to_layer,
                    "net": net
                }
            }

        except Exception as e:
            logger.error(f"Error adding via: {str(e)}")
            return {
                "success": False,
                "message": "Failed to add via",
                "errorDetails": str(e)
            }

    def delete_trace(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a trace from the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            trace_uuid = params.get("traceUuid")
            position = params.get("position")
            net_name = params.get("net")
            layer = params.get("layer")
            include_vias = params.get("includeVias", False)

            if not trace_uuid and not position and not net_name:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "One of traceUuid, position, or net must be provided"
                }

            # Delete by net name (bulk delete)
            if net_name:
                tracks_to_remove = []
                for track in self.board.Tracks():
                    if track.GetNetname() != net_name:
                        continue

                    # Skip vias if not requested
                    is_via = track.Type() == pcbnew.PCB_VIA_T
                    if is_via and not include_vias:
                        continue

                    # Filter by layer if specified (only for non-vias)
                    if layer and not is_via:
                        layer_id = self.board.GetLayerID(layer)
                        if track.GetLayer() != layer_id:
                            continue

                    tracks_to_remove.append(track)

                for track in tracks_to_remove:
                    self.board.Remove(track)

                return {
                    "success": True,
                    "message": f"Deleted {len(tracks_to_remove)} traces on net '{net_name}'",
                    "deletedCount": len(tracks_to_remove)
                }

            # Find track by UUID
            if trace_uuid:
                track = None
                for item in self.board.Tracks():
                    if str(item.m_Uuid) == trace_uuid:
                        track = item
                        break

                if not track:
                    return {
                        "success": False,
                        "message": "Track not found",
                        "errorDetails": f"Could not find track with UUID: {trace_uuid}"
                    }

                self.board.Remove(track)
                return {
                    "success": True,
                    "message": f"Deleted track: {trace_uuid}"
                }

            # Find track by position
            if position:
                scale = 1000000 if position["unit"] == "mm" else 25400000  # mm or inch to nm
                x_nm = int(position["x"] * scale)
                y_nm = int(position["y"] * scale)
                point = pcbnew.VECTOR2I(x_nm, y_nm)

                # Find closest track
                closest_track = None
                min_distance = float('inf')
                for track in self.board.Tracks():
                    dist = self._point_to_track_distance(point, track)
                    if dist < min_distance:
                        min_distance = dist
                        closest_track = track

                if closest_track and min_distance < 1000000:  # Within 1mm
                    self.board.Remove(closest_track)
                    return {
                        "success": True,
                        "message": "Deleted track at specified position"
                    }
                else:
                    return {
                        "success": False,
                        "message": "No track found",
                        "errorDetails": "No track found near specified position"
                    }

        except Exception as e:
            logger.error(f"Error deleting trace: {str(e)}")
            return {
                "success": False,
                "message": "Failed to delete trace",
                "errorDetails": str(e)
            }

    def delete_all_traces(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Delete ALL traces and optionally all vias from the PCB.

        This is a bulk operation for clearing all routing, useful when
        routing needs to be completely redone.

        Parameters:
            includeVias: Whether to also delete all vias (default True)
            net: Optional net name to restrict deletion to
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            include_vias = params.get("includeVias", True)
            net_filter = params.get("net")

            tracks_to_remove = []
            vias_to_remove = []

            for track in self.board.Tracks():
                is_via = track.Type() == pcbnew.PCB_VIA_T

                # Apply net filter if specified
                if net_filter and track.GetNetname() != net_filter:
                    continue

                if is_via:
                    if include_vias:
                        vias_to_remove.append(track)
                else:
                    tracks_to_remove.append(track)

            # Remove all collected items
            for item in tracks_to_remove + vias_to_remove:
                self.board.Remove(item)

            msg = f"Deleted {len(tracks_to_remove)} traces"
            if include_vias:
                msg += f" and {len(vias_to_remove)} vias"
            if net_filter:
                msg += f" on net '{net_filter}'"

            return {
                "success": True,
                "message": msg,
                "tracesDeleted": len(tracks_to_remove),
                "viasDeleted": len(vias_to_remove)
            }

        except Exception as e:
            logger.error(f"Error deleting all traces: {str(e)}")
            return {
                "success": False,
                "message": "Failed to delete all traces",
                "errorDetails": str(e)
            }

    def get_nets_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a list of all nets in the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            nets = []
            netinfo = self.board.GetNetInfo()
            for net_code in range(netinfo.GetNetCount()):
                net = netinfo.GetNetItem(net_code)
                if net:
                    nets.append({
                        "name": net.GetNetname(),
                        "code": net.GetNetCode(),
                        "class": net.GetClassName()
                    })

            return {
                "success": True,
                "nets": nets
            }

        except Exception as e:
            logger.error(f"Error getting nets list: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get nets list",
                "errorDetails": str(e)
            }

    def query_traces(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Query traces by net, layer, or bounding box"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            # Get filter parameters
            net_name = params.get("net")
            layer = params.get("layer")
            bbox = params.get("boundingBox")  # {x1, y1, x2, y2, unit}
            include_vias = params.get("includeVias", False)

            scale = 1000000  # nm to mm conversion factor
            traces = []
            vias = []

            # Process tracks
            for track in self.board.Tracks():
                # Check if it's a via
                is_via = track.Type() == pcbnew.PCB_VIA_T

                if is_via and not include_vias:
                    continue

                # Filter by net
                if net_name and track.GetNetname() != net_name:
                    continue

                # Filter by layer (only for tracks, not vias)
                if layer and not is_via:
                    layer_id = self.board.GetLayerID(layer)
                    if track.GetLayer() != layer_id:
                        continue

                # Filter by bounding box
                if bbox:
                    bbox_unit = bbox.get("unit", "mm")
                    bbox_scale = scale if bbox_unit == "mm" else 25400000
                    x1 = int(bbox.get("x1", 0) * bbox_scale)
                    y1 = int(bbox.get("y1", 0) * bbox_scale)
                    x2 = int(bbox.get("x2", 0) * bbox_scale)
                    y2 = int(bbox.get("y2", 0) * bbox_scale)

                    if is_via:
                        pos = track.GetPosition()
                        if not (x1 <= pos.x <= x2 and y1 <= pos.y <= y2):
                            continue
                    else:
                        start = track.GetStart()
                        end = track.GetEnd()
                        # Check if either endpoint is within bbox
                        start_in = x1 <= start.x <= x2 and y1 <= start.y <= y2
                        end_in = x1 <= end.x <= x2 and y1 <= end.y <= y2
                        if not (start_in or end_in):
                            continue

                if is_via:
                    pos = track.GetPosition()
                    vias.append({
                        "uuid": str(track.m_Uuid),
                        "position": {
                            "x": pos.x / scale,
                            "y": pos.y / scale,
                            "unit": "mm"
                        },
                        "net": track.GetNetname(),
                        "netCode": track.GetNetCode(),
                        "diameter": track.GetWidth() / scale,
                        "drill": track.GetDrillValue() / scale
                    })
                else:
                    start = track.GetStart()
                    end = track.GetEnd()
                    traces.append({
                        "uuid": str(track.m_Uuid),
                        "net": track.GetNetname(),
                        "netCode": track.GetNetCode(),
                        "layer": self.board.GetLayerName(track.GetLayer()),
                        "width": track.GetWidth() / scale,
                        "start": {
                            "x": start.x / scale,
                            "y": start.y / scale,
                            "unit": "mm"
                        },
                        "end": {
                            "x": end.x / scale,
                            "y": end.y / scale,
                            "unit": "mm"
                        },
                        "length": track.GetLength() / scale
                    })

            result = {
                "success": True,
                "traceCount": len(traces),
                "traces": traces
            }

            if include_vias:
                result["viaCount"] = len(vias)
                result["vias"] = vias

            return result

        except Exception as e:
            logger.error(f"Error querying traces: {str(e)}")
            return {
                "success": False,
                "message": "Failed to query traces",
                "errorDetails": str(e)
            }

    def modify_trace(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Modify properties of an existing trace

        Allows changing trace width, layer, and net assignment.
        Find trace by UUID or position.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            # Identification parameters
            trace_uuid = params.get("uuid")
            position = params.get("position")  # {x, y, unit}

            # Modification parameters
            new_width = params.get("width")  # in mm
            new_layer = params.get("layer")
            new_net = params.get("net")

            if not trace_uuid and not position:
                return {
                    "success": False,
                    "message": "Missing trace identifier",
                    "errorDetails": "Provide either 'uuid' or 'position' to identify the trace"
                }

            scale = 1000000  # nm to mm conversion

            # Find the track
            track = None

            if trace_uuid:
                for item in self.board.Tracks():
                    if str(item.m_Uuid) == trace_uuid:
                        track = item
                        break
            elif position:
                pos_unit = position.get("unit", "mm")
                pos_scale = scale if pos_unit == "mm" else 25400000
                x_nm = int(position["x"] * pos_scale)
                y_nm = int(position["y"] * pos_scale)
                point = pcbnew.VECTOR2I(x_nm, y_nm)

                # Find closest track
                min_distance = float('inf')
                for item in self.board.Tracks():
                    dist = self._point_to_track_distance(point, item)
                    if dist < min_distance:
                        min_distance = dist
                        track = item

                # Only accept if within 1mm
                if min_distance >= 1000000:
                    track = None

            if not track:
                return {
                    "success": False,
                    "message": "Track not found",
                    "errorDetails": "Could not find track with specified identifier"
                }

            # Check if it's a via (some modifications don't apply)
            is_via = track.Type() == pcbnew.PCB_VIA_T
            modifications = []

            # Apply modifications
            if new_width is not None:
                width_nm = int(new_width * scale)
                track.SetWidth(width_nm)
                modifications.append(f"width={new_width}mm")

            if new_layer and not is_via:
                layer_id = self.board.GetLayerID(new_layer)
                if layer_id < 0:
                    return {
                        "success": False,
                        "message": "Invalid layer",
                        "errorDetails": f"Layer '{new_layer}' not found"
                    }
                track.SetLayer(layer_id)
                modifications.append(f"layer={new_layer}")

            if new_net:
                netinfo = self.board.GetNetInfo()
                net = netinfo.GetNetItem(new_net)
                if not net:
                    return {
                        "success": False,
                        "message": "Invalid net",
                        "errorDetails": f"Net '{new_net}' not found"
                    }
                track.SetNet(net)
                modifications.append(f"net={new_net}")

            if not modifications:
                return {
                    "success": False,
                    "message": "No modifications specified",
                    "errorDetails": "Provide at least one of: width, layer, net"
                }

            return {
                "success": True,
                "message": f"Modified trace: {', '.join(modifications)}",
                "uuid": str(track.m_Uuid),
                "modifications": modifications
            }

        except Exception as e:
            logger.error(f"Error modifying trace: {str(e)}")
            return {
                "success": False,
                "message": "Failed to modify trace",
                "errorDetails": str(e)
            }

    def copy_routing_pattern(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Copy routing pattern from source components to target components

        This enables routing replication between identical component groups.
        The pattern is copied with a translation offset calculated from
        the position difference between source and target components.
        """
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            source_refs = params.get("sourceRefs", [])  # e.g., ["U1", "U2", "U3"]
            target_refs = params.get("targetRefs", [])  # e.g., ["U4", "U5", "U6"]
            include_vias = params.get("includeVias", True)
            trace_width = params.get("traceWidth")  # Optional override

            if not source_refs or not target_refs:
                return {
                    "success": False,
                    "message": "Missing component references",
                    "errorDetails": "Provide both 'sourceRefs' and 'targetRefs' arrays"
                }

            if len(source_refs) != len(target_refs):
                return {
                    "success": False,
                    "message": "Mismatched component counts",
                    "errorDetails": f"sourceRefs has {len(source_refs)} items, targetRefs has {len(target_refs)}"
                }

            scale = 1000000  # nm to mm conversion

            # Get footprints
            footprints = {fp.GetReference(): fp for fp in self.board.GetFootprints()}

            # Validate all references exist
            for ref in source_refs + target_refs:
                if ref not in footprints:
                    return {
                        "success": False,
                        "message": "Component not found",
                        "errorDetails": f"Component '{ref}' not found on board"
                    }

            # Calculate offset from first source to first target component
            source_fp = footprints[source_refs[0]]
            target_fp = footprints[target_refs[0]]
            source_pos = source_fp.GetPosition()
            target_pos = target_fp.GetPosition()

            offset_x = target_pos.x - source_pos.x
            offset_y = target_pos.y - source_pos.y

            # Build mapping from source refs to target refs
            ref_mapping = dict(zip(source_refs, target_refs))

            # Collect all nets connected to source components
            source_nets = set()
            for ref in source_refs:
                fp = footprints[ref]
                for pad in fp.Pads():
                    net_name = pad.GetNetname()
                    if net_name and net_name != "":
                        source_nets.add(net_name)

            # Collect traces and vias connected to source nets
            traces_to_copy = []
            vias_to_copy = []

            for track in self.board.Tracks():
                if track.GetNetname() not in source_nets:
                    continue

                is_via = track.Type() == pcbnew.PCB_VIA_T

                if is_via:
                    if include_vias:
                        vias_to_copy.append(track)
                else:
                    traces_to_copy.append(track)

            # Create new traces with offset
            created_traces = 0
            created_vias = 0

            for track in traces_to_copy:
                start = track.GetStart()
                end = track.GetEnd()

                # Create new track
                new_track = pcbnew.PCB_TRACK(self.board)
                new_track.SetStart(pcbnew.VECTOR2I(start.x + offset_x, start.y + offset_y))
                new_track.SetEnd(pcbnew.VECTOR2I(end.x + offset_x, end.y + offset_y))
                new_track.SetLayer(track.GetLayer())

                # Set width (use override or original)
                if trace_width:
                    new_track.SetWidth(int(trace_width * scale))
                else:
                    new_track.SetWidth(track.GetWidth())

                # Try to find corresponding target net
                # This is a simplification - more sophisticated mapping would be needed
                # for complex designs
                self.board.Add(new_track)
                created_traces += 1

            for via in vias_to_copy:
                pos = via.GetPosition()

                # Create new via
                new_via = pcbnew.PCB_VIA(self.board)
                new_via.SetPosition(pcbnew.VECTOR2I(pos.x + offset_x, pos.y + offset_y))
                new_via.SetWidth(via.GetWidth())
                new_via.SetDrill(via.GetDrillValue())
                new_via.SetViaType(via.GetViaType())

                self.board.Add(new_via)
                created_vias += 1

            result = {
                "success": True,
                "message": f"Copied routing pattern: {created_traces} traces, {created_vias} vias",
                "offset": {
                    "x": offset_x / scale,
                    "y": offset_y / scale,
                    "unit": "mm"
                },
                "createdTraces": created_traces,
                "createdVias": created_vias,
                "sourceComponents": source_refs,
                "targetComponents": target_refs
            }

            return result

        except Exception as e:
            logger.error(f"Error copying routing pattern: {str(e)}")
            return {
                "success": False,
                "message": "Failed to copy routing pattern",
                "errorDetails": str(e)
            }

    def create_netclass(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new net class with specified properties"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            name = params.get("name")
            clearance = params.get("clearance")
            track_width = params.get("trackWidth")
            via_diameter = params.get("viaDiameter")
            via_drill = params.get("viaDrill")
            uvia_diameter = params.get("uviaDiameter")
            uvia_drill = params.get("uviaDrill")
            diff_pair_width = params.get("diffPairWidth")
            diff_pair_gap = params.get("diffPairGap")
            nets = params.get("nets", [])

            if not name:
                return {
                    "success": False,
                    "message": "Missing netclass name",
                    "errorDetails": "name parameter is required"
                }

            # Get net classes
            net_classes = self.board.GetNetClasses()
            
            # Create new net class if it doesn't exist
            if not net_classes.Find(name):
                netclass = pcbnew.NETCLASS(name)
                net_classes.Add(netclass)
            else:
                netclass = net_classes.Find(name)

            # Set properties
            scale = 1000000  # mm to nm
            if clearance is not None:
                netclass.SetClearance(int(clearance * scale))
            if track_width is not None:
                netclass.SetTrackWidth(int(track_width * scale))
            if via_diameter is not None:
                netclass.SetViaDiameter(int(via_diameter * scale))
            if via_drill is not None:
                netclass.SetViaDrill(int(via_drill * scale))
            if uvia_diameter is not None:
                netclass.SetMicroViaDiameter(int(uvia_diameter * scale))
            if uvia_drill is not None:
                netclass.SetMicroViaDrill(int(uvia_drill * scale))
            if diff_pair_width is not None:
                netclass.SetDiffPairWidth(int(diff_pair_width * scale))
            if diff_pair_gap is not None:
                netclass.SetDiffPairGap(int(diff_pair_gap * scale))

            # Add nets to net class
            netinfo = self.board.GetNetInfo()
            nets_map = netinfo.NetsByName()
            for net_name in nets:
                if nets_map.has_key(net_name):
                    net = nets_map[net_name]
                    net.SetClass(netclass)

            return {
                "success": True,
                "message": f"Created net class: {name}",
                "netClass": {
                    "name": name,
                    "clearance": netclass.GetClearance() / scale,
                    "trackWidth": netclass.GetTrackWidth() / scale,
                    "viaDiameter": netclass.GetViaDiameter() / scale,
                    "viaDrill": netclass.GetViaDrill() / scale,
                    "uviaDiameter": netclass.GetMicroViaDiameter() / scale,
                    "uviaDrill": netclass.GetMicroViaDrill() / scale,
                    "diffPairWidth": netclass.GetDiffPairWidth() / scale,
                    "diffPairGap": netclass.GetDiffPairGap() / scale,
                    "nets": nets
                }
            }

        except Exception as e:
            logger.error(f"Error creating net class: {str(e)}")
            return {
                "success": False,
                "message": "Failed to create net class",
                "errorDetails": str(e)
            }
            
    def add_copper_pour(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a copper pour (zone) to the PCB"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            layer = params.get("layer", "F.Cu")
            net = params.get("net")
            clearance = params.get("clearance")
            min_width = params.get("minWidth", 0.2)
            points = params.get("points", [])
            priority = params.get("priority", 0)
            fill_type = params.get("fillType", "solid")  # solid or hatched
            
            if not points or len(points) < 3:
                return {
                    "success": False,
                    "message": "Missing points",
                    "errorDetails": "At least 3 points are required for copper pour outline"
                }

            # Get layer ID
            layer_id = self.board.GetLayerID(layer)
            if layer_id < 0:
                return {
                    "success": False,
                    "message": "Invalid layer",
                    "errorDetails": f"Layer '{layer}' does not exist"
                }

            # Create zone
            zone = pcbnew.ZONE(self.board)
            zone.SetLayer(layer_id)
            
            # Set net if provided
            if net:
                netinfo = self.board.GetNetInfo()
                nets_map = netinfo.NetsByName()
                if nets_map.has_key(net):
                    net_obj = nets_map[net]
                    zone.SetNet(net_obj)
            
            # Set zone properties
            scale = 1000000  # mm to nm
            zone.SetAssignedPriority(priority)
            
            if clearance is not None:
                zone.SetLocalClearance(int(clearance * scale))
            
            zone.SetMinThickness(int(min_width * scale))
            
            # Set fill type
            if fill_type == "hatched":
                zone.SetFillMode(pcbnew.ZONE_FILL_MODE_HATCH_PATTERN)
            else:
                zone.SetFillMode(pcbnew.ZONE_FILL_MODE_POLYGONS)
            
            # Create outline
            outline = zone.Outline()
            outline.NewOutline()  # Create a new outline contour first

            # Add points to outline
            for point in points:
                scale = 1000000 if point.get("unit", "mm") == "mm" else 25400000
                x_nm = int(point["x"] * scale)
                y_nm = int(point["y"] * scale)
                outline.Append(pcbnew.VECTOR2I(x_nm, y_nm))  # Add point to outline
            
            # Add zone to board
            self.board.Add(zone)

            # Fill zone
            # Note: Zone filling can cause issues with SWIG API
            # Comment out for now - zones will be filled when board is saved/opened in KiCAD
            # filler = pcbnew.ZONE_FILLER(self.board)
            # filler.Fill(self.board.Zones())

            return {
                "success": True,
                "message": "Added copper pour",
                "pour": {
                    "layer": layer,
                    "net": net,
                    "clearance": clearance,
                    "minWidth": min_width,
                    "priority": priority,
                    "fillType": fill_type,
                    "pointCount": len(points)
                }
            }

        except Exception as e:
            logger.error(f"Error adding copper pour: {str(e)}")
            return {
                "success": False,
                "message": "Failed to add copper pour",
                "errorDetails": str(e)
            }
            
    def route_differential_pair(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route a differential pair between two sets of points or pads"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first"
                }

            start_pos = params.get("startPos")
            end_pos = params.get("endPos")
            net_pos = params.get("netPos")
            net_neg = params.get("netNeg")
            layer = params.get("layer", "F.Cu")
            width = params.get("width")
            gap = params.get("gap")

            if not start_pos or not end_pos or not net_pos or not net_neg:
                return {
                    "success": False,
                    "message": "Missing parameters",
                    "errorDetails": "startPos, endPos, netPos, and netNeg are required"
                }

            # Get layer ID
            layer_id = self.board.GetLayerID(layer)
            if layer_id < 0:
                return {
                    "success": False,
                    "message": "Invalid layer",
                    "errorDetails": f"Layer '{layer}' does not exist"
                }

            # Get nets
            netinfo = self.board.GetNetInfo()
            nets_map = netinfo.NetsByName()

            net_pos_obj = nets_map[net_pos] if nets_map.has_key(net_pos) else None
            net_neg_obj = nets_map[net_neg] if nets_map.has_key(net_neg) else None

            if not net_pos_obj or not net_neg_obj:
                return {
                    "success": False,
                    "message": "Nets not found",
                    "errorDetails": "One or both nets specified for the differential pair do not exist"
                }

            # Get start and end points
            start_point = self._get_point(start_pos)
            end_point = self._get_point(end_pos)
            
            # Calculate offset vectors for the two traces
            # First, get the direction vector from start to end
            dx = end_point.x - start_point.x
            dy = end_point.y - start_point.y
            length = math.sqrt(dx * dx + dy * dy)
            
            if length <= 0:
                return {
                    "success": False,
                    "message": "Invalid points",
                    "errorDetails": "Start and end points must be different"
                }
                
            # Normalize direction vector
            dx /= length
            dy /= length
            
            # Get perpendicular vector
            px = -dy
            py = dx
            
            # Set default gap if not provided
            if gap is None:
                gap = 0.2  # mm
                
            # Convert to nm
            gap_nm = int(gap * 1000000)
            
            # Calculate offsets
            offset_x = int(px * gap_nm / 2)
            offset_y = int(py * gap_nm / 2)
            
            # Create positive and negative trace points
            pos_start = pcbnew.VECTOR2I(int(start_point.x + offset_x), int(start_point.y + offset_y))
            pos_end = pcbnew.VECTOR2I(int(end_point.x + offset_x), int(end_point.y + offset_y))
            neg_start = pcbnew.VECTOR2I(int(start_point.x - offset_x), int(start_point.y - offset_y))
            neg_end = pcbnew.VECTOR2I(int(end_point.x - offset_x), int(end_point.y - offset_y))
            
            # Create positive trace
            pos_track = pcbnew.PCB_TRACK(self.board)
            pos_track.SetStart(pos_start)
            pos_track.SetEnd(pos_end)
            pos_track.SetLayer(layer_id)
            pos_track.SetNet(net_pos_obj)
            
            # Create negative trace
            neg_track = pcbnew.PCB_TRACK(self.board)
            neg_track.SetStart(neg_start)
            neg_track.SetEnd(neg_end)
            neg_track.SetLayer(layer_id)
            neg_track.SetNet(net_neg_obj)
            
            # Set width
            if width:
                trace_width_nm = int(width * 1000000)
                pos_track.SetWidth(trace_width_nm)
                neg_track.SetWidth(trace_width_nm)
            else:
                # Get default width from design rules or net class
                trace_width = self.board.GetDesignSettings().GetCurrentTrackWidth()
                pos_track.SetWidth(trace_width)
                neg_track.SetWidth(trace_width)
            
            # Add tracks to board
            self.board.Add(pos_track)
            self.board.Add(neg_track)

            return {
                "success": True,
                "message": "Added differential pair traces",
                "diffPair": {
                    "posNet": net_pos,
                    "negNet": net_neg,
                    "layer": layer,
                    "width": pos_track.GetWidth() / 1000000,
                    "gap": gap,
                    "length": length / 1000000
                }
            }

        except Exception as e:
            logger.error(f"Error routing differential pair: {str(e)}")
            return {
                "success": False,
                "message": "Failed to route differential pair",
                "errorDetails": str(e)
            }

    def _get_point(self, point_spec: Dict[str, Any]) -> pcbnew.VECTOR2I:
        """Convert point specification to KiCAD point"""
        if "x" in point_spec and "y" in point_spec:
            scale = 1000000 if point_spec.get("unit", "mm") == "mm" else 25400000
            x_nm = int(point_spec["x"] * scale)
            y_nm = int(point_spec["y"] * scale)
            return pcbnew.VECTOR2I(x_nm, y_nm)
        elif "pad" in point_spec and "componentRef" in point_spec:
            module = self.board.FindFootprintByReference(point_spec["componentRef"])
            if module:
                pad = module.FindPadByName(point_spec["pad"])
                if pad:
                    return pad.GetPosition()
        raise ValueError("Invalid point specification")

    def _point_to_track_distance(self, point: pcbnew.VECTOR2I, track: pcbnew.PCB_TRACK) -> float:
        """Calculate distance from point to track segment"""
        start = track.GetStart()
        end = track.GetEnd()
        
        # Vector from start to end
        v = pcbnew.VECTOR2I(end.x - start.x, end.y - start.y)
        # Vector from start to point
        w = pcbnew.VECTOR2I(point.x - start.x, point.y - start.y)
        
        # Length of track squared
        c1 = v.x * v.x + v.y * v.y
        if c1 == 0:
            return self._point_distance(point, start)
            
        # Projection coefficient
        c2 = float(w.x * v.x + w.y * v.y) / c1
        
        if c2 < 0:
            return self._point_distance(point, start)
        elif c2 > 1:
            return self._point_distance(point, end)
            
        # Point on line
        proj = pcbnew.VECTOR2I(
            int(start.x + c2 * v.x),
            int(start.y + c2 * v.y)
        )
        return self._point_distance(point, proj)

    def _point_distance(self, p1: pcbnew.VECTOR2I, p2: pcbnew.VECTOR2I) -> float:
        """Calculate distance between two points"""
        dx = p1.x - p2.x
        dy = p1.y - p2.y
        return (dx * dx + dy * dy) ** 0.5
