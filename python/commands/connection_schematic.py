import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from skip import Schematic

logger = logging.getLogger(__name__)

# Import new wire and pin managers
try:
    from commands.pin_locator import PinLocator
    from commands.wire_manager import WireManager

    WIRE_MANAGER_AVAILABLE = True
except ImportError:
    logger.warning("WireManager/PinLocator not available")
    WIRE_MANAGER_AVAILABLE = False


class ConnectionManager:
    """Manage connections between components in schematics"""

    # Initialize pin locator (class variable, shared across instances)
    _pin_locator = None

    @classmethod
    def get_pin_locator(cls) -> Any:
        """Get or create pin locator instance"""
        if cls._pin_locator is None and WIRE_MANAGER_AVAILABLE:
            cls._pin_locator = PinLocator()
        return cls._pin_locator

    @staticmethod
    def add_net_label(schematic: Schematic, net_name: str, position: list) -> Any:
        """
        Add a net label to the schematic

        Args:
            schematic: Schematic object
            net_name: Name of the net (e.g., "VCC", "GND", "SIGNAL_1")
            position: [x, y] coordinates for the label

        Returns:
            Label object or None on error
        """
        try:
            if not hasattr(schematic, "label"):
                logger.error("Schematic does not have label collection")
                return None

            label = schematic.label.append(text=net_name, at={"x": position[0], "y": position[1]})
            logger.info(f"Added net label '{net_name}' at {position}")
            return label
        except Exception as e:
            logger.error(f"Error adding net label: {e}")
            return None

    @staticmethod
    def connect_to_net(
        schematic_path: Path, component_ref: str, pin_name: str, net_name: str
    ) -> Dict[str, Any]:
        """
        Connect a component pin to a named net using a wire stub and label.

        Args:
            schematic_path: Path to .kicad_sch file
            component_ref: Reference designator (e.g., "U1", "U1_")
            pin_name: Pin name/number
            net_name: Name of the net to connect to (e.g., "VCC", "GND", "SIGNAL_1")

        Returns:
            Dict with keys:
              success        – bool
              pin_location   – [x, y] exact pin endpoint used (present on success)
              label_location – [x, y] where the net label was placed (present on success)
              wire_stub      – [[x1,y1],[x2,y2]] the wire segment added (present on success)
              message        – human-readable status
        """
        try:
            if not WIRE_MANAGER_AVAILABLE:
                logger.error("WireManager/PinLocator not available")
                return {"success": False, "message": "WireManager/PinLocator not available"}

            locator = ConnectionManager.get_pin_locator()
            if not locator:
                logger.error("Pin locator unavailable")
                return {"success": False, "message": "Pin locator unavailable"}

            # Get pin location using PinLocator
            pin_loc = locator.get_pin_location(schematic_path, component_ref, pin_name)
            if not pin_loc:
                msg = f"Could not locate pin {component_ref}/{pin_name}"
                logger.error(msg)
                return {"success": False, "message": msg}

            # Add a small wire stub from the pin (2.54mm = 0.1 inch, standard grid spacing)
            # Stub direction follows the pin's outward angle from the PinLocator
            try:
                pin_angle_deg = locator.get_pin_angle(schematic_path, component_ref, pin_name) or 0
            except Exception as e:
                logger.warning(
                    f"Could not get pin angle for {component_ref}/{pin_name}, defaulting to 0: {e}"
                )
                pin_angle_deg = 0
            import math as _math

            angle_rad = _math.radians(pin_angle_deg)
            stub_end = [
                round(pin_loc[0] + 2.54 * _math.cos(angle_rad), 4),
                round(pin_loc[1] - 2.54 * _math.sin(angle_rad), 4),
            ]

            # Create wire stub using WireManager
            wire_success = WireManager.add_wire(schematic_path, pin_loc, stub_end)
            if not wire_success:
                msg = "Failed to create wire stub for net connection"
                logger.error(msg)
                return {"success": False, "message": msg}

            # Add label at the end of the stub using WireManager
            label_success = WireManager.add_label(
                schematic_path, net_name, stub_end, label_type="label"
            )
            if not label_success:
                msg = f"Failed to add net label '{net_name}'"
                logger.error(msg)
                return {"success": False, "message": msg}

            logger.info(f"Connected {component_ref}/{pin_name} to net '{net_name}'")
            return {
                "success": True,
                "message": f"Connected {component_ref}/{pin_name} to net '{net_name}'",
                "pin_location": pin_loc,
                "label_location": stub_end,
                "wire_stub": [pin_loc, stub_end],
            }

        except Exception as e:
            logger.error(f"Error connecting to net: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    @staticmethod
    def connect_passthrough(
        schematic_path: Path,
        source_ref: str,
        target_ref: str,
        net_prefix: str = "PIN",
        pin_offset: int = 0,
    ) -> Dict[str, List[str]]:
        """
        Connect all pins of source_ref to matching pins of target_ref via shared net labels.
        Useful for passthrough adapters: J1 pin N <-> J2 pin N on net {net_prefix}_{N}.

        Args:
            schematic_path: Path to .kicad_sch file
            source_ref: Reference of the first connector (e.g., "J1")
            target_ref: Reference of the second connector (e.g., "J2")
            net_prefix: Prefix for generated net names (default: "PIN" -> PIN_1, PIN_2, ...)
            pin_offset: Add this value to the pin number when building the net name (default 0)

        Returns:
            dict with 'connected' list and 'failed' list
        """
        if not WIRE_MANAGER_AVAILABLE:
            logger.error("WireManager/PinLocator not available")
            return {"connected": [], "failed": ["WireManager unavailable"]}

        locator = ConnectionManager.get_pin_locator()
        if not locator:
            return {"connected": [], "failed": ["PinLocator unavailable"]}

        # Get all pins of source and target
        src_pins = locator.get_all_symbol_pins(schematic_path, source_ref) or {}
        tgt_pins = locator.get_all_symbol_pins(schematic_path, target_ref) or {}

        if not src_pins:
            return {"connected": [], "failed": [f"No pins found on {source_ref}"]}
        if not tgt_pins:
            return {"connected": [], "failed": [f"No pins found on {target_ref}"]}

        connected = []
        failed = []

        for pin_num in sorted(src_pins.keys(), key=lambda x: int(x) if x.isdigit() else 0):
            try:
                net_name = (
                    f"{net_prefix}_{int(pin_num) + pin_offset}"
                    if pin_num.isdigit()
                    else f"{net_prefix}_{pin_num}"
                )

                res_src = ConnectionManager.connect_to_net(
                    schematic_path, source_ref, pin_num, net_name
                )
                if not res_src.get("success"):
                    failed.append(f"{source_ref}/{pin_num}")
                    continue

                if pin_num in tgt_pins:
                    res_tgt = ConnectionManager.connect_to_net(
                        schematic_path, target_ref, pin_num, net_name
                    )
                    if not res_tgt.get("success"):
                        failed.append(f"{target_ref}/{pin_num}")
                        continue
                else:
                    failed.append(f"{target_ref}/{pin_num} (pin not found)")
                    continue

                connected.append(f"{source_ref}/{pin_num} <-> {target_ref}/{pin_num} [{net_name}]")
            except Exception as e:
                failed.append(f"{source_ref}/{pin_num}: {e}")

        logger.info(f"connect_passthrough: {len(connected)} connected, {len(failed)} failed")
        return {"connected": connected, "failed": failed}

    @staticmethod
    def get_net_connections(
        schematic: Schematic, net_name: str, schematic_path: Optional[Path] = None
    ) -> List[Dict]:
        """
        Get all connections for a named net using wire graph analysis

        Args:
            schematic: Schematic object
            net_name: Name of the net to query
            schematic_path: Optional path to schematic file (enables accurate pin matching)

        Returns:
            List of connections: [{"component": ref, "pin": pin_name}, ...]
        """
        try:
            from commands.pin_locator import PinLocator

            connections = []
            tolerance = 0.5  # 0.5mm tolerance for point coincidence (grid spacing consideration)

            def points_coincide(p1: Any, p2: Any) -> bool:
                """Check if two points are the same (within tolerance)"""
                if not p1 or not p2:
                    return False
                dx = abs(p1[0] - p2[0])
                dy = abs(p1[1] - p2[1])
                return dx < tolerance and dy < tolerance

            # 1. Find all labels with this net name
            if not hasattr(schematic, "label"):
                logger.warning("Schematic has no labels")
                return connections

            net_label_positions = []
            for label in schematic.label:
                if hasattr(label, "value") and label.value == net_name:
                    if hasattr(label, "at") and hasattr(label.at, "value"):
                        pos = label.at.value
                        net_label_positions.append([float(pos[0]), float(pos[1])])

            if not net_label_positions:
                logger.info(f"No labels found for net '{net_name}'")
                return connections

            logger.debug(f"Found {len(net_label_positions)} labels for net '{net_name}'")

            # 2. Find all wires connected to these label positions.
            # A missing wire attribute is fine — all_match_points will still
            # include label positions, so label-at-pin connections are detected.
            connected_wire_points: set[tuple[float, float]] = set()
            if not hasattr(schematic, "wire"):
                logger.debug("Schematic has no wires — will match labels to pins directly")

            for wire in (schematic.wire if hasattr(schematic, "wire") else []):
                if hasattr(wire, "pts") and hasattr(wire.pts, "xy"):
                    # Get all points in this wire (polyline)
                    wire_points = []
                    for point in wire.pts.xy:
                        if hasattr(point, "value"):
                            wire_points.append([float(point.value[0]), float(point.value[1])])

                    # Check if any wire point touches a label
                    wire_connected = False
                    for wire_pt in wire_points:
                        for label_pt in net_label_positions:
                            if points_coincide(wire_pt, label_pt):
                                wire_connected = True
                                break
                        if wire_connected:
                            break

                    # If this wire is connected to the net, add all its points
                    if wire_connected:
                        for pt in wire_points:
                            connected_wire_points.add((pt[0], pt[1]))

            # Build match points: union of wire endpoints AND label positions.
            # This handles the valid KiCad style where a net label is placed
            # directly at a pin endpoint with no wire segment in between.
            all_match_points = connected_wire_points | {(p[0], p[1]) for p in net_label_positions}

            if not all_match_points:
                logger.debug(f"No connection points found for net '{net_name}'")
                return connections

            logger.debug(
                f"Found {len(connected_wire_points)} wire points, "
                f"{len(net_label_positions)} direct label positions, "
                f"{len(all_match_points)} total match points for net '{net_name}'"
            )

            # 3. Find component pins at wire endpoints
            if not hasattr(schematic, "symbol"):
                logger.warning("Schematic has no symbols")
                return connections

            # Create pin locator for accurate pin matching (if schematic_path available)
            locator = None
            if schematic_path and WIRE_MANAGER_AVAILABLE:
                locator = PinLocator()

            for symbol in schematic.symbol:
                # Skip template symbols
                if not hasattr(symbol.property, "Reference"):
                    continue

                ref = symbol.property.Reference.value
                if ref.startswith("_TEMPLATE"):
                    continue

                # Get lib_id for pin location lookup
                lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else None
                if not lib_id:
                    continue

                # If we have PinLocator and schematic_path, do accurate pin matching
                if locator and schematic_path:
                    try:
                        # Get all pins for this symbol
                        pins = locator.get_symbol_pins(schematic_path, lib_id)
                        if not pins:
                            continue

                        # Check each pin
                        for pin_num, pin_data in pins.items():
                            # Get pin location
                            pin_loc = locator.get_pin_location(schematic_path, ref, pin_num)
                            if not pin_loc:
                                continue

                            # Check if pin coincides with any match point
                            for wire_pt_tup in all_match_points:
                                if points_coincide(pin_loc, list(wire_pt_tup)):
                                    connections.append({"component": ref, "pin": pin_num})
                                    break  # Pin found, no need to check more wire points

                    except Exception as e:
                        logger.warning(f"Error matching pins for {ref}: {e}")
                        # Fall back to proximity matching
                        pass

                # Fallback: proximity-based matching if no PinLocator
                if not locator or not schematic_path:
                    symbol_pos = symbol.at.value if hasattr(symbol, "at") else None
                    if not symbol_pos:
                        continue

                    symbol_x = float(symbol_pos[0])
                    symbol_y = float(symbol_pos[1])

                    # Check if symbol is near any match point (within 10mm)
                    for wire_pt_tup in all_match_points:
                        dist = (
                            (symbol_x - wire_pt_tup[0]) ** 2 + (symbol_y - wire_pt_tup[1]) ** 2
                        ) ** 0.5
                        if dist < 10.0:  # 10mm proximity threshold
                            connections.append({"component": ref, "pin": "unknown"})
                            break  # Only add once per component

            logger.info(f"Found {len(connections)} connections for net '{net_name}'")
            return connections

        except Exception as e:
            logger.error(f"Error getting net connections: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return []

    @staticmethod
    def connect_component_to_nets(
        schematic_path: Path,
        component_ref: str,
        connections: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        Connect all pins of one component to their respective nets in a single call.

        Args:
            schematic_path: Path to .kicad_sch file
            component_ref: Reference designator (e.g. "U1", "R3")
            connections: Mapping of pin name/number → net name,
                         e.g. {"1": "GND", "8": "VCC", "3": "OUTPUT"}

        Returns:
            {success, connected, already_connected, failed, message}
        """
        if not WIRE_MANAGER_AVAILABLE:
            return {"success": False, "message": "WireManager/PinLocator not available"}
        if not connections:
            return {"success": False, "message": "connections map is empty"}

        connected: List[str] = []
        already_connected: List[str] = []
        failed: List[Dict] = []

        for pin_name, net_name in connections.items():
            existing = ConnectionManager.get_pin_net(schematic_path, component_ref, pin_name)
            key = f"{component_ref}/{pin_name}"

            if existing == net_name:
                already_connected.append(key)
                continue

            if existing is not None:
                failed.append(
                    {
                        "pin": key,
                        "reason": f"already on net '{existing}' (conflicts with '{net_name}')",
                    }
                )
                continue

            result = ConnectionManager.connect_to_net(
                schematic_path, component_ref, pin_name, net_name
            )
            if result.get("success"):
                connected.append(f"{key} → {net_name}")
            else:
                failed.append({"pin": key, "reason": result.get("message", "unknown")})

        parts: List[str] = []
        if connected:
            parts.append(f"{len(connected)} connected")
        if already_connected:
            parts.append(f"{len(already_connected)} already done")
        if failed:
            parts.append(f"{len(failed)} failed")

        return {
            "success": len(failed) == 0,
            "connected": connected,
            "already_connected": already_connected,
            "failed": failed,
            "message": (
                f"{component_ref} pin connections: "
                + (", ".join(parts) if parts else "nothing to do")
            ),
        }

    @staticmethod
    def get_pin_net(schematic_path: Path, component_ref: str, pin_name: str) -> Optional[str]:
        """
        Return the net label connected to this pin via the wire+label graph, or None.

        Walks the wire network from the pin endpoint via BFS and returns the first
        label found on any reachable node. Used by connect_pins to detect existing
        net assignments before placing new labels.
        """
        try:
            if not WIRE_MANAGER_AVAILABLE:
                return None
            locator = ConnectionManager.get_pin_locator()
            if not locator:
                return None

            pin_loc = locator.get_pin_location(schematic_path, component_ref, pin_name)
            if not pin_loc:
                return None

            sch = Schematic(str(schematic_path))
            TOLS = 0.5  # mm

            def close(a: tuple, b: tuple) -> bool:
                return abs(a[0] - b[0]) < TOLS and abs(a[1] - b[1]) < TOLS

            # Collect wire edges as pairs of (x, y) tuples
            wire_edges: List[tuple] = []
            all_wire_pts: List[tuple] = []
            for wire in getattr(sch, "wire", None) or []:
                xy_list = getattr(getattr(wire, "pts", None), "xy", [])
                pts_: List[tuple] = []
                for pt in xy_list:
                    v = getattr(pt, "value", None)
                    if v:
                        pts_.append((float(v[0]), float(v[1])))
                for i in range(len(pts_) - 1):
                    wire_edges.append((pts_[i], pts_[i + 1]))
                    all_wire_pts.extend([pts_[i], pts_[i + 1]])

            # Collect label positions → net name
            label_map: List[tuple] = []  # [(pos_tuple, net_name)]
            for lbl in getattr(sch, "label", None) or []:
                at = getattr(lbl, "at", None)
                v = getattr(at, "value", None) if at else None
                name = getattr(lbl, "value", None)
                if v and name:
                    label_map.append(((float(v[0]), float(v[1])), name))

            pin_pt = (pin_loc[0], pin_loc[1])

            # Seed BFS: pin endpoint itself plus any wire point coincident with pin
            seeds: List[tuple] = [pin_pt] + [p for p in all_wire_pts if close(p, pin_pt)]

            # Check seeds directly for a label
            for seed in seeds:
                for lpos, lname in label_map:
                    if close(seed, lpos):
                        return lname

            # BFS through wire adjacency
            visited: List[tuple] = list(seeds)
            queue: List[tuple] = list(seeds)
            while queue:
                current = queue.pop()
                for ea, eb in wire_edges:
                    if close(ea, current):
                        neighbor = eb
                    elif close(eb, current):
                        neighbor = ea
                    else:
                        continue
                    for lpos, lname in label_map:
                        if close(neighbor, lpos):
                            return lname
                    if not any(close(neighbor, v) for v in visited):
                        visited.append(neighbor)
                        queue.append(neighbor)

            return None
        except Exception as e:
            logger.warning(f"get_pin_net({component_ref}/{pin_name}): {e}")
            return None

    @staticmethod
    def connect_pins(
        schematic_path: Path,
        pins: List[Dict[str, str]],
        net_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Connect two or more component pins to the same named net.

        If net_name is omitted, existing labels on any of the listed pins are
        discovered first; a human-readable name takes priority over an
        auto-generated "Net-(...)" name.  If two pins already carry *different*
        human-readable nets the call fails with a conflict error.

        Handles the A→B→C orphan case: connect_pins([B, C]) detects B's existing
        label and reuses it for C, leaving A's connection intact.

        Returns dict with keys:
            success, net_used, connected, already_connected, failed, message
        """
        if not WIRE_MANAGER_AVAILABLE:
            return {"success": False, "message": "WireManager/PinLocator not available"}
        if not pins:
            return {"success": False, "message": "pins list is empty"}

        # Phase 1: discover current net on each pin (single file-read per pin)
        existing: Dict[str, Optional[str]] = {}
        for p in pins:
            ref, pin = p.get("ref", ""), p.get("pin", "")
            if ref and pin:
                existing[f"{ref}/{pin}"] = ConnectionManager.get_pin_net(schematic_path, ref, pin)

        # Phase 2: resolve target net
        resolved_net: Optional[str]
        if net_name:
            resolved_net = net_name
        else:
            found_nets = {v for v in existing.values() if v is not None}
            if not found_nets:
                return {
                    "success": False,
                    "message": (
                        "No existing net labels found on any of the specified pins "
                        "and no netName provided."
                    ),
                }
            human_nets = sorted(n for n in found_nets if not n.startswith("Net-("))
            if len(human_nets) > 1:
                return {
                    "success": False,
                    "message": (
                        f"Net conflict: pins carry different nets {human_nets}. "
                        "Specify netName to resolve."
                    ),
                    "conflicting_nets": human_nets,
                }
            resolved_net = human_nets[0] if human_nets else next(iter(found_nets))

        # Phase 3: apply label to each pin that needs it
        connected: List[str] = []
        already_connected: List[str] = []
        failed: List[Dict] = []

        for p in pins:
            ref, pin = p.get("ref", ""), p.get("pin", "")
            if not ref or not pin:
                failed.append({"pin": f"{ref}/{pin}", "reason": "missing ref or pin"})
                continue

            key = f"{ref}/{pin}"
            current = existing.get(key)

            if current == resolved_net:
                already_connected.append(key)
                continue

            if current is not None:
                failed.append(
                    {
                        "pin": key,
                        "reason": (
                            f"already on net '{current}' "
                            f"(conflicts with target '{resolved_net}')"
                        ),
                    }
                )
                continue

            result = ConnectionManager.connect_to_net(schematic_path, ref, pin, resolved_net)
            if result.get("success"):
                connected.append(key)
            else:
                failed.append({"pin": key, "reason": result.get("message", "unknown")})

        parts: List[str] = []
        if connected:
            parts.append(f"{len(connected)} connected")
        if already_connected:
            parts.append(f"{len(already_connected)} already on net")
        if failed:
            parts.append(f"{len(failed)} failed")

        return {
            "success": len(failed) == 0,
            "net_used": resolved_net,
            "connected": connected,
            "already_connected": already_connected,
            "failed": failed,
            "message": (
                f"connect_pins to '{resolved_net}': "
                + (", ".join(parts) if parts else "nothing to do")
            ),
        }

    @staticmethod
    def generate_netlist(
        schematic: Schematic, schematic_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Generate a netlist from the schematic

        Args:
            schematic: Schematic object
            schematic_path: Optional path to schematic file (enables accurate pin matching
                via PinLocator; without it, only one connection per component is found)

        Returns:
            Dictionary with net information:
            {
                "nets": [
                    {
                        "name": "VCC",
                        "connections": [
                            {"component": "R1", "pin": "1"},
                            {"component": "C1", "pin": "1"}
                        ]
                    },
                    ...
                ],
                "components": [
                    {"reference": "R1", "value": "10k", "footprint": "..."},
                    ...
                ]
            }
        """
        try:
            from commands.wire_connectivity import get_connections_for_net

            netlist: Dict[str, Any] = {"nets": [], "components": []}

            # Gather all components
            if hasattr(schematic, "symbol"):
                for symbol in schematic.symbol:
                    component_info = {
                        "reference": symbol.property.Reference.value,
                        "value": (
                            symbol.property.Value.value if hasattr(symbol.property, "Value") else ""
                        ),
                        "footprint": (
                            symbol.property.Footprint.value
                            if hasattr(symbol.property, "Footprint")
                            else ""
                        ),
                    }
                    netlist["components"].append(component_info)

            # Gather all nets from labels and global labels
            net_names: set = set()
            for attr_name in ("label", "global_label"):
                if hasattr(schematic, attr_name):
                    for label in getattr(schematic, attr_name):
                        if hasattr(label, "value"):
                            net_names.add(label.value)

            sch_path_str = str(schematic_path) if schematic_path else ""
            for net_name in net_names:
                connections = get_connections_for_net(schematic, sch_path_str, net_name)
                if connections:
                    netlist["nets"].append({"name": net_name, "connections": connections})

            logger.info(
                f"Generated netlist with {len(netlist['nets'])} nets and {len(netlist['components'])} components"
            )
            return netlist

        except Exception as e:
            logger.error(f"Error generating netlist: {e}")
            return {"nets": [], "components": []}
