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
    def add_wire(schematic_path: Path, start_point: list, end_point: list, properties: dict = None):
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

            stroke_width = properties.get('stroke_width', 0) if properties else 0
            stroke_type = properties.get('stroke_type', 'default') if properties else 'default'

            success = WireManager.add_wire(schematic_path, start_point, end_point,
                                          stroke_width=stroke_width, stroke_type=stroke_type)
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
            if not hasattr(symbol, 'pin'):
                logger.warning(f"Symbol {symbol.property.Reference.value} has no pins")
                return None

            # Find the pin by name
            target_pin = None
            for pin in symbol.pin:
                if pin.name == pin_name:
                    target_pin = pin
                    break

            if not target_pin:
                logger.warning(f"Pin '{pin_name}' not found on {symbol.property.Reference.value}")
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
    def add_connection(schematic_path: Path, source_ref: str, source_pin: str,
                      target_ref: str, target_pin: str, routing: str = 'direct'):
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
            source_loc = locator.get_pin_location(schematic_path, source_ref, source_pin)
            target_loc = locator.get_pin_location(schematic_path, target_ref, target_pin)

            if not source_loc or not target_loc:
                logger.error("Could not determine pin locations")
                return False

            # Create wire based on routing style
            if routing == 'direct':
                # Simple direct wire
                success = WireManager.add_wire(schematic_path, source_loc, target_loc)
            elif routing == 'orthogonal_h':
                # Orthogonal routing (horizontal first)
                path = WireManager.create_orthogonal_path(source_loc, target_loc, prefer_horizontal_first=True)
                success = WireManager.add_polyline_wire(schematic_path, path)
            elif routing == 'orthogonal_v':
                # Orthogonal routing (vertical first)
                path = WireManager.create_orthogonal_path(source_loc, target_loc, prefer_horizontal_first=False)
                success = WireManager.add_polyline_wire(schematic_path, path)
            else:
                logger.error(f"Unknown routing style: {routing}")
                return False

            if success:
                logger.info(f"Connected {source_ref}/{source_pin} to {target_ref}/{target_pin} (routing: {routing})")
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
            if not hasattr(schematic, 'label'):
                logger.error("Schematic does not have label collection")
                return None

            label = schematic.label.append(
                text=net_name,
                at={'x': position[0], 'y': position[1]}
            )
            logger.info(f"Added net label '{net_name}' at {position}")
            return label
        except Exception as e:
            logger.error(f"Error adding net label: {e}")
            return None

    @staticmethod
    def connect_to_net(schematic: Schematic, component_ref: str, pin_name: str, net_name: str):
        """
        Connect a component pin to a named net using a label

        Args:
            schematic: Schematic object
            component_ref: Reference designator (e.g., "U1")
            pin_name: Pin name/number
            net_name: Name of the net to connect to

        Returns:
            True if successful, False otherwise
        """
        try:
            # Find the component
            symbol = None
            if hasattr(schematic, 'symbol'):
                for s in schematic.symbol:
                    if s.property.Reference.value == component_ref:
                        symbol = s
                        break

            if not symbol:
                logger.error(f"Component '{component_ref}' not found")
                return False

            # Get pin location
            pin_loc = ConnectionManager.get_pin_location(symbol, pin_name)
            if not pin_loc:
                return False

            # Add a small wire stub from the pin (so label has something to attach to)
            stub_end = [pin_loc[0] + 2.54, pin_loc[1]]  # 2.54mm = 0.1 inch grid
            wire = ConnectionManager.add_wire(schematic, pin_loc, stub_end)

            if not wire:
                return False

            # Add label at the end of the stub
            label = ConnectionManager.add_net_label(schematic, net_name, stub_end)

            if label:
                logger.info(f"Connected {component_ref}/{pin_name} to net '{net_name}'")
                return True
            else:
                return False

        except Exception as e:
            logger.error(f"Error connecting to net: {e}")
            return False

    @staticmethod
    def get_net_connections(schematic: Schematic, net_name: str):
        """
        Get all connections for a named net

        Args:
            schematic: Schematic object
            net_name: Name of the net to query

        Returns:
            List of connections: [{"component": ref, "pin": pin_name}, ...]
        """
        try:
            connections = []

            if not hasattr(schematic, 'label'):
                logger.warning("Schematic has no labels")
                return connections

            # Find all labels with this net name
            net_labels = []
            for label in schematic.label:
                if hasattr(label, 'value') and label.value == net_name:
                    net_labels.append(label)

            if not net_labels:
                logger.info(f"No labels found for net '{net_name}'")
                return connections

            # For each label, find connected symbols
            for label in net_labels:
                # Find wires connected to this label position
                label_pos = label.at.value if hasattr(label, 'at') else None
                if not label_pos:
                    continue

                # Search for symbols near this label
                if hasattr(schematic, 'symbol'):
                    for symbol in schematic.symbol:
                        # Check if symbol has wires attached
                        if hasattr(symbol, 'attached_labels'):
                            for attached_label in symbol.attached_labels:
                                if attached_label.value == net_name:
                                    # Find which pin is connected
                                    if hasattr(symbol, 'pin'):
                                        for pin in symbol.pin:
                                            pin_loc = ConnectionManager.get_pin_location(symbol, pin.name)
                                            if pin_loc:
                                                # Check if pin is connected to any wire attached to this label
                                                connections.append({
                                                    "component": symbol.property.Reference.value,
                                                    "pin": pin.name
                                                })

            logger.info(f"Found {len(connections)} connections for net '{net_name}'")
            return connections

        except Exception as e:
            logger.error(f"Error getting net connections: {e}")
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
            netlist = {
                "nets": [],
                "components": []
            }

            # Gather all components
            if hasattr(schematic, 'symbol'):
                for symbol in schematic.symbol:
                    component_info = {
                        "reference": symbol.property.Reference.value,
                        "value": symbol.property.Value.value if hasattr(symbol.property, 'Value') else "",
                        "footprint": symbol.property.Footprint.value if hasattr(symbol.property, 'Footprint') else ""
                    }
                    netlist["components"].append(component_info)

            # Gather all nets from labels
            if hasattr(schematic, 'label'):
                net_names = set()
                for label in schematic.label:
                    if hasattr(label, 'value'):
                        net_names.add(label.value)

                # For each net, get connections
                for net_name in net_names:
                    connections = ConnectionManager.get_net_connections(schematic, net_name)
                    if connections:
                        netlist["nets"].append({
                            "name": net_name,
                            "connections": connections
                        })

            logger.info(f"Generated netlist with {len(netlist['nets'])} nets and {len(netlist['components'])} components")
            return netlist

        except Exception as e:
            logger.error(f"Error generating netlist: {e}")
            return {"nets": [], "components": []}

if __name__ == '__main__':
    # Example Usage (for testing)
    from schematic import SchematicManager # Assuming schematic.py is in the same directory

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
