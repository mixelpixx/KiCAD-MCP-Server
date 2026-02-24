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
    _last_error = ""

    @classmethod
    def get_pin_locator(cls):
        """Get or create pin locator instance"""
        if cls._pin_locator is None and WIRE_MANAGER_AVAILABLE:
            cls._pin_locator = PinLocator()
        return cls._pin_locator

    @classmethod
    def _set_error(cls, message: str):
        cls._last_error = message
        logger.error(message)

    @classmethod
    def get_last_error(cls) -> str:
        return cls._last_error

    @staticmethod
    def add_wire(
        schematic_path: Path,
        start_point: list,
        end_point: list,
        properties: Optional[dict] = None,
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

            props = properties or {}
            stroke_width = props.get("stroke_width", 0)
            stroke_type = props.get("stroke_type", "default")

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
    def get_pin_location(symbol, pin_name: str):
        """
        Get the absolute location of a pin on a symbol

        Args:
            symbol: Symbol object
            pin_name: Name or number of the pin (e.g., "1", "GND", "VCC")

        Returns:
            [x, y] coordinates or None if pin not found
        """
        try:
            if not hasattr(symbol, "pin"):
                logger.warning(f"Symbol {symbol.property.Reference.value} has no pins")
                return None

            # Find the pin by name
            target_pin = None
            for pin in symbol.pin:
                if pin.name == pin_name:
                    target_pin = pin
                    break

            if not target_pin:
                logger.warning(
                    f"Pin '{pin_name}' not found on {symbol.property.Reference.value}"
                )
                return None

            # Get pin location relative to symbol
            pin_loc = target_pin.location
            # Get symbol location
            symbol_at = symbol.at.value

            # Calculate absolute position
            # pin_loc is relative to symbol origin, need to add symbol position
            abs_x = symbol_at[0] + pin_loc[0]
            abs_y = symbol_at[1] + pin_loc[1]

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
            ConnectionManager._last_error = ""
            if not WIRE_MANAGER_AVAILABLE:
                ConnectionManager._set_error("WireManager/PinLocator not available")
                return False

            locator = ConnectionManager.get_pin_locator()
            if not locator:
                ConnectionManager._set_error("Pin locator unavailable")
                return False

            # Get pin locations
            source_loc = locator.get_pin_location(
                schematic_path, source_ref, source_pin
            )
            source_lookup_error = getattr(locator, "last_error", "")
            target_loc = locator.get_pin_location(
                schematic_path, target_ref, target_pin
            )
            target_lookup_error = getattr(locator, "last_error", "")

            if not source_loc or not target_loc:
                ConnectionManager._set_error(
                    "Could not determine pin locations. "
                    f"source={source_ref}/{source_pin}: {source_lookup_error or 'not found'}, "
                    f"target={target_ref}/{target_pin}: {target_lookup_error or 'not found'}"
                )
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
                ConnectionManager._set_error(f"Unknown routing style: {routing}")
                return False

            if success:
                logger.info(
                    f"Connected {source_ref}/{source_pin} to {target_ref}/{target_pin} (routing: {routing})"
                )
                return True
            else:
                ConnectionManager._set_error(
                    f"Failed to create wire geometry from {source_ref}/{source_pin} to {target_ref}/{target_pin}"
                )
                return False

        except Exception as e:
            ConnectionManager._set_error(f"Error adding connection: {e}")
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

    @staticmethod
    def connect_to_net(
        schematic_path: Path, component_ref: str, pin_name: str, net_name: str
    ):
        """
        Connect a component pin to a named net using a wire stub and label

        Args:
            schematic_path: Path to .kicad_sch file
            component_ref: Reference designator (e.g., "U1", "U1_")
            pin_name: Pin name/number
            net_name: Name of the net to connect to (e.g., "VCC", "GND", "SIGNAL_1")

        Returns:
            True if successful, False otherwise
        """
        try:
            ConnectionManager._last_error = ""
            if not WIRE_MANAGER_AVAILABLE:
                ConnectionManager._set_error("WireManager/PinLocator not available")
                return False

            locator = ConnectionManager.get_pin_locator()
            if not locator:
                ConnectionManager._set_error("Pin locator unavailable")
                return False

            # Get pin info using PinLocator
            pin_info = locator.get_pin_info(schematic_path, component_ref, pin_name)
            if not pin_info:
                ConnectionManager._set_error(
                    f"Could not locate pin {component_ref}/{pin_name}. "
                    f"Details: {getattr(locator, 'last_error', '')}"
                )
                return False

            pin_loc = [pin_info["x"], pin_info["y"]]

            # Create wire stub in direction of pin orientation
            angle = pin_info.get("effective_angle", 0.0) % 360.0
            nearest = int(round(angle / 90.0) * 90) % 360
            stub_length = 2.54
            direction_map = {
                0: (stub_length, 0.0),
                90: (0.0, stub_length),
                180: (-stub_length, 0.0),
                270: (0.0, -stub_length),
            }
            dx, dy = direction_map.get(nearest, (stub_length, 0.0))

            # Add a small wire stub from the pin (2.54mm = 0.1 inch, standard grid spacing)
            stub_end = [pin_loc[0] + dx, pin_loc[1] + dy]

            # Create wire stub using WireManager
            wire_success = WireManager.add_wire(schematic_path, pin_loc, stub_end)
            if not wire_success:
                ConnectionManager._set_error(
                    "Failed to create wire stub for net connection"
                )
                return False

            # Add label at the end of the stub using WireManager
            label_success = WireManager.add_label(
                schematic_path, net_name, stub_end, label_type="label"
            )
            if not label_success:
                ConnectionManager._set_error(f"Failed to add net label '{net_name}'")
                return False

            logger.info(f"Connected {component_ref}/{pin_name} to net '{net_name}'")
            return True

        except Exception as e:
            ConnectionManager._set_error(f"Error connecting to net: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False

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
    def generate_netlist(schematic: Schematic):
        """
        Generate a netlist from the schematic

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
                        "value": symbol.property.Value.value
                        if hasattr(symbol.property, "Value")
                        else "",
                        "footprint": symbol.property.Footprint.value
                        if hasattr(symbol.property, "Footprint")
                        else "",
                    }
                    netlist["components"].append(component_info)

            # Gather all nets from labels
            if hasattr(schematic, "label"):
                net_names = set()
                for label in schematic.label:
                    if hasattr(label, "value"):
                        net_names.add(label.value)

                # For each net, get connections
                for net_name in net_names:
                    connections = ConnectionManager.get_net_connections(
                        schematic, net_name
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
