from skip import Schematic
import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Import new wire and pin managers
try:
    from commands.wire_manager import WireManager
    from commands.pin_locator import PinLocator

    WIRE_MANAGER_AVAILABLE = True
except ImportError:
    logger.warning("WireManager/PinLocator not available")
    WIRE_MANAGER_AVAILABLE = False


class ConnectionManager:
    """Manage connections between components in schematics"""

    # Initialize pin locator (class variable, shared across instances)
    _pin_locator = None

    @classmethod
    def get_pin_locator(cls):
        """Get or create pin locator instance"""
        if cls._pin_locator is None and WIRE_MANAGER_AVAILABLE:
            cls._pin_locator = PinLocator()
        return cls._pin_locator

    @staticmethod
    def add_wire(
        schematic_path: Path,
        start_point: list,
        end_point: list,
        properties: dict = None,
    ):
        """
        Add a wire between two points using WireManager

        Args:
            schematic_path: Path to .kicad_sch file
            start_point: [x, y] coordinates for wire start
            end_point: [x, y] coordinates for wire end
            properties: Optional wire properties (stroke_width, stroke_type)

        Returns:
            True if successful, False otherwise
        """
        try:
            if not WIRE_MANAGER_AVAILABLE:
                logger.error("WireManager not available")
                return False

            stroke_width = properties.get("stroke_width", 0) if properties else 0
            stroke_type = (
                properties.get("stroke_type", "default") if properties else "default"
            )

            success = WireManager.add_wire(
                schematic_path,
                start_point,
                end_point,
                stroke_width=stroke_width,
                stroke_type=stroke_type,
            )
            return success
        except Exception as e:
            logger.error(f"Error adding wire: {e}")
            return False

    @staticmethod
    def get_pin_location(symbol_or_path, pin_name: str, symbol_ref: str = None):
        """
        Get the absolute location of a pin on a symbol.

        DEPRECATED: This method exists for backward compatibility. Prefer using
        PinLocator.get_pin_location() directly, which correctly handles Y-negation,
        mirror transforms, and rotation.

        Args:
            symbol_or_path: Either a kicad-skip Symbol object (legacy) or a Path
                to the .kicad_sch file (preferred).
            pin_name: Name or number of the pin (e.g., "1", "GND", "VCC")
            symbol_ref: Reference designator (required when symbol_or_path is a Path)

        Returns:
            [x, y] coordinates or None if pin not found
        """
        try:
            # If a file path was provided, use PinLocator directly
            if isinstance(symbol_or_path, (str, Path)):
                if not WIRE_MANAGER_AVAILABLE:
                    logger.error("PinLocator not available for accurate pin location")
                    return None
                if not symbol_ref:
                    logger.error("symbol_ref is required when passing a file path to get_pin_location")
                    return None
                locator = PinLocator()
                return locator.get_pin_location(symbol_or_path, symbol_ref, pin_name)

            # Legacy path: symbol object passed directly.
            # Delegate to PinLocator if possible, otherwise warn about inaccuracy.
            symbol = symbol_or_path
            ref = (
                symbol.property.Reference.value
                if hasattr(symbol.property, "Reference")
                else None
            )

            logger.warning(
                f"get_pin_location called with symbol object for '{ref}' -- "
                "this path cannot apply Y-negation, mirror, or rotation transforms. "
                "Use PinLocator.get_pin_location(schematic_path, ref, pin) instead."
            )

            if not hasattr(symbol, "pin"):
                logger.warning(f"Symbol {ref} has no pins")
                return None

            # Find the pin by name
            target_pin = None
            for pin in symbol.pin:
                if pin.name == pin_name:
                    target_pin = pin
                    break

            if not target_pin:
                logger.warning(f"Pin '{pin_name}' not found on {ref}")
                return None

            # Get pin location relative to symbol
            pin_loc = target_pin.location
            # Get symbol location
            symbol_at = symbol.at.value

            import math

            # Apply Y-negation (symbol-local Y-up -> schematic Y-down)
            pin_rel_x = pin_loc[0]
            pin_rel_y = -pin_loc[1]

            # Apply mirror transforms if available
            if hasattr(symbol, "mirror"):
                mirror_val = str(symbol.mirror.value) if hasattr(symbol.mirror, "value") else ""
                if "x" in mirror_val:
                    pin_rel_y = -pin_rel_y
                if "y" in mirror_val:
                    pin_rel_x = -pin_rel_x

            # Apply rotation
            rotation_deg = float(symbol_at[2]) if len(symbol_at) > 2 else 0.0
            rotation_rad = math.radians(rotation_deg)
            cos_r = math.cos(rotation_rad)
            sin_r = math.sin(rotation_rad)
            rotated_x = pin_rel_x * cos_r - pin_rel_y * sin_r
            rotated_y = -pin_rel_x * sin_r + pin_rel_y * cos_r

            abs_x = symbol_at[0] + rotated_x
            abs_y = symbol_at[1] + rotated_y

            return [abs_x, abs_y]
        except Exception as e:
            logger.error(f"Error getting pin location: {e}")
            return None

    @staticmethod
    def add_connection(
        schematic_path: Path,
        source_ref: str,
        source_pin: str,
        target_ref: str,
        target_pin: str,
        routing: str = "direct",
    ):
        """
        Add a wire connection between two component pins

        Args:
            schematic_path: Path to .kicad_sch file
            source_ref: Reference designator of source component (e.g., "R1", "R1_")
            source_pin: Pin name/number on source component
            target_ref: Reference designator of target component (e.g., "C1", "C1_")
            target_pin: Pin name/number on target component
            routing: Routing style ('direct', 'orthogonal_h', 'orthogonal_v')

        Returns:
            True if connection was successful, False otherwise
        """
        try:
            if not WIRE_MANAGER_AVAILABLE:
                logger.error("WireManager/PinLocator not available")
                return False

            locator = ConnectionManager.get_pin_locator()
            if not locator:
                logger.error("Pin locator unavailable")
                return False

            # Get pin locations
            source_loc = locator.get_pin_location(
                schematic_path, source_ref, source_pin
            )
            target_loc = locator.get_pin_location(
                schematic_path, target_ref, target_pin
            )

            if not source_loc or not target_loc:
                logger.error("Could not determine pin locations")
                return False

            # Create wire based on routing style
            if routing == "direct":
                # Simple direct wire
                success = WireManager.add_wire(schematic_path, source_loc, target_loc)
            elif routing == "orthogonal_h":
                # Orthogonal routing (horizontal first)
                path = WireManager.create_orthogonal_path(
                    source_loc, target_loc, prefer_horizontal_first=True
                )
                success = WireManager.add_polyline_wire(schematic_path, path)
            elif routing == "orthogonal_v":
                # Orthogonal routing (vertical first)
                path = WireManager.create_orthogonal_path(
                    source_loc, target_loc, prefer_horizontal_first=False
                )
                success = WireManager.add_polyline_wire(schematic_path, path)
            else:
                logger.error(f"Unknown routing style: {routing}")
                return False

            if success:
                logger.info(
                    f"Connected {source_ref}/{source_pin} to {target_ref}/{target_pin} (routing: {routing})"
                )
                return True
            else:
                return False

        except Exception as e:
            logger.error(f"Error adding connection: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_net_label(schematic: Schematic, net_name: str, position: list):
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

            label = schematic.label.append(
                text=net_name, at={"x": position[0], "y": position[1]}
            )
            logger.info(f"Added net label '{net_name}' at {position}")
            return label
        except Exception as e:
            logger.error(f"Error adding net label: {e}")
            return None

    # Power net patterns — these should use power symbols instead of labels
    POWER_NET_PATTERNS = {
        "GND", "GNDREF", "GNDA", "GNDD", "EARTH",
        "VCC", "VDD", "VSS", "VEE",
        "+5V", "+3V3", "+3.3V", "+12V", "+24V", "+9V", "+1V8", "+2V5",
        "-5V", "-12V", "-24V",
        "+5VA", "+3.3VA",
    }

    @staticmethod
    def _is_power_net(net_name: str) -> bool:
        """Check if a net name is a standard power net."""
        return net_name.upper() in {p.upper() for p in ConnectionManager.POWER_NET_PATTERNS}

    @staticmethod
    def connect_to_net(
        schematic_path: Path, component_ref: str, pin_name: str, net_name: str,
        label_type: str = None, shape: str = None,
    ):
        """
        Connect a component pin to a named net using a wire stub and label.

        For power nets (GND, +3V3, +5V, VCC, etc.), automatically places a power
        symbol from the power library instead of a plain net label.

        Args:
            schematic_path: Path to .kicad_sch file
            component_ref: Reference designator (e.g., "U1", "U1_")
            pin_name: Pin name/number
            net_name: Name of the net to connect to (e.g., "VCC", "GND", "SIGNAL_1")
            label_type: Override label type: None (auto), "label", "global_label"
            shape: For global_label: "input", "output", "bidirectional", "passive"

        Returns:
            True if successful, False otherwise
        """
        try:
            if not WIRE_MANAGER_AVAILABLE:
                logger.error("WireManager/PinLocator not available")
                return False

            # Create a fresh PinLocator each time to avoid stale cache
            locator = PinLocator()

            # Get pin location using PinLocator (now returns endpoint)
            pin_loc = locator.get_pin_location(schematic_path, component_ref, pin_name)
            if not pin_loc:
                logger.error(f"Could not locate pin {component_ref}/{pin_name}")
                return False

            # Add a small wire stub from the pin endpoint
            # (2.54mm = 0.1 inch, standard grid spacing)
            pin_angle_deg = 0
            try:
                pin_angle_deg = locator.get_pin_angle(schematic_path, component_ref, pin_name) or 0
            except Exception:
                pin_angle_deg = 0
            import math as _math

            def _snap_to_grid(v, grid=1.27):
                """Snap a coordinate to the nearest KiCad grid point."""
                return round(round(v / grid) * grid, 4)

            angle_rad = _math.radians(pin_angle_deg)
            raw_x = pin_loc[0] + 2.54 * _math.cos(angle_rad)
            raw_y = pin_loc[1] - 2.54 * _math.sin(angle_rad)

            # Only snap along the stub direction to avoid diagonal wires.
            # Vertical pins (90°/270°): snap y, keep x = pin x
            # Horizontal pins (0°/180°): snap x, keep y = pin y
            norm_angle = pin_angle_deg % 360
            if norm_angle in (90, 270):
                stub_end = [pin_loc[0], _snap_to_grid(raw_y)]
            elif norm_angle in (0, 180):
                stub_end = [_snap_to_grid(raw_x), pin_loc[1]]
            else:
                # Non-cardinal angle: snap both (rare)
                stub_end = [_snap_to_grid(raw_x), _snap_to_grid(raw_y)]

            # Create wire stub
            wire_success = WireManager.add_wire(schematic_path, pin_loc, stub_end)
            if not wire_success:
                logger.error("Failed to create wire stub for net connection")
                return False

            # Determine what to place at the stub end
            is_power = ConnectionManager._is_power_net(net_name)

            if is_power and label_type is None:
                # Place a power symbol instead of a label
                try:
                    import re as _re
                    from commands.dynamic_symbol_loader import DynamicSymbolLoader

                    # Auto-number #PWR reference
                    with open(schematic_path, "r", encoding="utf-8") as _f:
                        _content = _f.read()
                    existing_pwr = _re.findall(r'#PWR(\d+)', _content)
                    next_pwr = max((int(n) for n in existing_pwr), default=0) + 1
                    pwr_ref = f"#PWR{next_pwr:03d}"

                    loader = DynamicSymbolLoader(project_path=schematic_path.parent)
                    loader.add_component(
                        schematic_path,
                        "power",
                        net_name,
                        reference=pwr_ref,
                        value=net_name,
                        footprint="",
                        x=stub_end[0],
                        y=stub_end[1],
                        project_path=schematic_path.parent,
                    )
                    logger.info(f"Placed power symbol {net_name} for {component_ref}/{pin_name}")
                    return True
                except Exception as power_err:
                    logger.warning(f"Power symbol placement failed ({power_err}), falling back to label")

            # Place label (regular or global)
            effective_label_type = label_type or "label"
            label_success = WireManager.add_label(
                schematic_path, net_name, stub_end,
                label_type=effective_label_type,
                shape=shape,
            )
            if not label_success:
                logger.error(f"Failed to add net label '{net_name}'")
                return False

            logger.info(f"Connected {component_ref}/{pin_name} to net '{net_name}' ({effective_label_type})")
            return True

        except Exception as e:
            logger.error(f"Error connecting to net: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def connect_passthrough(
        schematic_path: Path,
        source_ref: str,
        target_ref: str,
        net_prefix: str = "PIN",
        pin_offset: int = 0,
    ):
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
                net_name = f"{net_prefix}_{int(pin_num) + pin_offset}" if pin_num.isdigit() else f"{net_prefix}_{pin_num}"

                ok_src = ConnectionManager.connect_to_net(
                    schematic_path, source_ref, pin_num, net_name
                )
                if not ok_src:
                    failed.append(f"{source_ref}/{pin_num}")
                    continue

                if pin_num in tgt_pins:
                    ok_tgt = ConnectionManager.connect_to_net(
                        schematic_path, target_ref, pin_num, net_name
                    )
                    if not ok_tgt:
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
    ):
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

            def points_coincide(p1, p2):
                """Check if two points are the same (within tolerance)"""
                if not p1 or not p2:
                    return False
                dx = abs(p1[0] - p2[0])
                dy = abs(p1[1] - p2[1])
                return dx < tolerance and dy < tolerance

            # 1. Find all labels with this net name (local, global, hierarchical, power)
            net_label_positions = []

            # Local labels
            if hasattr(schematic, "label"):
                for label in schematic.label:
                    if hasattr(label, "value") and label.value == net_name:
                        if hasattr(label, "at") and hasattr(label.at, "value"):
                            pos = label.at.value
                            net_label_positions.append([float(pos[0]), float(pos[1])])

            # Global labels
            if hasattr(schematic, "global_label"):
                for label in schematic.global_label:
                    if hasattr(label, "value") and label.value == net_name:
                        if hasattr(label, "at") and hasattr(label.at, "value"):
                            pos = label.at.value
                            net_label_positions.append([float(pos[0]), float(pos[1])])

            # Hierarchical labels
            if hasattr(schematic, "hierarchical_label"):
                for label in schematic.hierarchical_label:
                    if hasattr(label, "value") and label.value == net_name:
                        if hasattr(label, "at") and hasattr(label.at, "value"):
                            pos = label.at.value
                            net_label_positions.append([float(pos[0]), float(pos[1])])

            # Power symbols (#PWR with matching value)
            if hasattr(schematic, "symbol"):
                for symbol in schematic.symbol:
                    if not hasattr(symbol.property, "Reference"):
                        continue
                    ref = symbol.property.Reference.value
                    if not ref.startswith("#PWR"):
                        continue
                    val = symbol.property.Value.value if hasattr(symbol.property, "Value") else ""
                    if val == net_name:
                        pos = symbol.at.value if hasattr(symbol, "at") else [0, 0]
                        net_label_positions.append([float(pos[0]), float(pos[1])])

            if not net_label_positions:
                logger.info(f"No labels found for net '{net_name}'")
                return connections

            logger.debug(
                f"Found {len(net_label_positions)} labels for net '{net_name}'"
            )

            # 2. Find all wires connected to these label positions
            if not hasattr(schematic, "wire"):
                logger.warning("Schematic has no wires")
                return connections

            connected_wire_points = set()
            for wire in schematic.wire:
                if hasattr(wire, "pts") and hasattr(wire.pts, "xy"):
                    # Get all points in this wire (polyline)
                    wire_points = []
                    for point in wire.pts.xy:
                        if hasattr(point, "value"):
                            wire_points.append(
                                [float(point.value[0]), float(point.value[1])]
                            )

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

            if not connected_wire_points:
                logger.debug(f"No wires connected to net '{net_name}' labels")
                return connections

            logger.debug(
                f"Found {len(connected_wire_points)} wire connection points for net '{net_name}'"
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
                            pin_loc = locator.get_pin_location(
                                schematic_path, ref, pin_num
                            )
                            if not pin_loc:
                                continue

                            # Check if pin coincides with any wire point
                            for wire_pt in connected_wire_points:
                                if points_coincide(pin_loc, list(wire_pt)):
                                    connections.append(
                                        {"component": ref, "pin": pin_num}
                                    )
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

                    # Check if symbol is near any wire point (within 10mm)
                    for wire_pt in connected_wire_points:
                        dist = (
                            (symbol_x - wire_pt[0]) ** 2 + (symbol_y - wire_pt[1]) ** 2
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
    def generate_netlist(schematic: Schematic, schematic_path: Optional[Path] = None):
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
            netlist = {"nets": [], "components": []}

            # Gather all components
            if hasattr(schematic, "symbol"):
                for symbol in schematic.symbol:
                    component_info = {
                        "reference": symbol.property.Reference.value,
                        "value": (
                            symbol.property.Value.value
                            if hasattr(symbol.property, "Value")
                            else ""
                        ),
                        "footprint": (
                            symbol.property.Footprint.value
                            if hasattr(symbol.property, "Footprint")
                            else ""
                        ),
                    }
                    netlist["components"].append(component_info)

            # Gather all nets from labels (local, global, hierarchical) and power symbols
            net_names = set()

            # Local labels
            if hasattr(schematic, "label"):
                for label in schematic.label:
                    if hasattr(label, "value"):
                        net_names.add(label.value)

            # Global labels
            if hasattr(schematic, "global_label"):
                for label in schematic.global_label:
                    if hasattr(label, "value"):
                        net_names.add(label.value)

            # Hierarchical labels
            if hasattr(schematic, "hierarchical_label"):
                for label in schematic.hierarchical_label:
                    if hasattr(label, "value"):
                        net_names.add(label.value)

            # Power symbols (symbols with lib_id starting with "power:")
            if hasattr(schematic, "symbol"):
                for symbol in schematic.symbol:
                    lib_id = (
                        symbol.lib_id.value
                        if hasattr(symbol, "lib_id") and hasattr(symbol.lib_id, "value")
                        else ""
                    )
                    if lib_id.startswith("power:"):
                        val = (
                            symbol.property.Value.value
                            if hasattr(symbol.property, "Value")
                            else ""
                        )
                        if val:
                            net_names.add(val)

            # For each net, get connections
            for net_name in net_names:
                connections = ConnectionManager.get_net_connections(
                    schematic, net_name, schematic_path
                )
                if connections:
                    netlist["nets"].append(
                        {"name": net_name, "connections": connections}
                    )

            logger.info(
                f"Generated netlist with {len(netlist['nets'])} nets and {len(netlist['components'])} components"
            )
            return netlist

        except Exception as e:
            logger.error(f"Error generating netlist: {e}")
            return {"nets": [], "components": []}


if __name__ == "__main__":
    # Example Usage (for testing)
    from schematic import (
        SchematicManager,
    )  # Assuming schematic.py is in the same directory

    # Create a new schematic
    test_sch = SchematicManager.create_schematic("ConnectionTestSchematic")

    # Add some wires
    wire1 = ConnectionManager.add_wire(test_sch, [100, 100], [200, 100])
    wire2 = ConnectionManager.add_wire(test_sch, [200, 100], [200, 200])

    # Note: add_connection, remove_connection, get_net_connections are placeholders
    # and require more complex implementation based on kicad-skip's structure.

    # Example of how you might add a net label (requires finding a point on a wire)
    # from skip import Label
    # if wire1:
    #     net_label_pos = wire1.start # Or calculate a point on the wire
    #     net_label = test_sch.add_label(text="Net_01", at=net_label_pos)
    #     print(f"Added net label 'Net_01' at {net_label_pos}")

    # Save the schematic (optional)
    # SchematicManager.save_schematic(test_sch, "connection_test.kicad_sch")

    # Clean up (if saved)
    # if os.path.exists("connection_test.kicad_sch"):
    #     os.remove("connection_test.kicad_sch")
    #     print("Cleaned up connection_test.kicad_sch")
