from skip import Schematic
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class ConnectionManager:
    """Manage connections between components in schematics"""

    @staticmethod
    def add_wire(schematic: Schematic, start_point: list, end_point: list, properties: dict = None):
        """
        Add a wire between two points

        Args:
            schematic: Schematic object
            start_point: [x, y] coordinates for wire start
            end_point: [x, y] coordinates for wire end
            properties: Optional wire properties (currently unused)

        Returns:
            Wire object or None on error
        """
        try:
            # Check if wire collection exists
            if not hasattr(schematic, 'wire'):
                logger.error("Schematic does not have wire collection")
                return None

            wire = schematic.wire.append(
                start={'x': start_point[0], 'y': start_point[1]},
                end={'x': end_point[0], 'y': end_point[1]}
            )
            logger.info(f"Added wire from {start_point} to {end_point}")
            return wire
        except Exception as e:
            logger.error(f"Error adding wire: {e}")
            return None

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
    def add_connection(schematic: Schematic, source_ref: str, source_pin: str, target_ref: str, target_pin: str):
        """
        Add a wire connection between two component pins

        Args:
            schematic: Schematic object
            source_ref: Reference designator of source component (e.g., "R1")
            source_pin: Pin name/number on source component
            target_ref: Reference designator of target component (e.g., "C1")
            target_pin: Pin name/number on target component

        Returns:
            True if connection was successful, False otherwise
        """
        try:
            # Find source and target symbols
            source_symbol = None
            target_symbol = None

            if not hasattr(schematic, 'symbol'):
                logger.error("Schematic has no symbols")
                return False

            for symbol in schematic.symbol:
                ref = symbol.property.Reference.value
                if ref == source_ref:
                    source_symbol = symbol
                if ref == target_ref:
                    target_symbol = symbol

            if not source_symbol:
                logger.error(f"Source component '{source_ref}' not found")
                return False

            if not target_symbol:
                logger.error(f"Target component '{target_ref}' not found")
                return False

            # Get pin locations
            source_loc = ConnectionManager.get_pin_location(source_symbol, source_pin)
            target_loc = ConnectionManager.get_pin_location(target_symbol, target_pin)

            if not source_loc or not target_loc:
                logger.error("Could not determine pin locations")
                return False

            # Add wire between pins
            wire = ConnectionManager.add_wire(schematic, source_loc, target_loc)

            if wire:
                logger.info(f"Connected {source_ref}/{source_pin} to {target_ref}/{target_pin}")
                return True
            else:
                return False

        except Exception as e:
            logger.error(f"Error adding connection: {e}")
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
    def _collect_from_schematic(schematic: Schematic, base_path: str, prefix: str = ""):
        """
        Recursively collect components and nets from a schematic and its hierarchical sheets.

        Args:
            schematic: Schematic object
            base_path: Base directory path for resolving relative sheet file paths
            prefix: Hierarchical path prefix for component references

        Returns:
            Tuple of (components list, net_names set, global_labels set)
        """
        components = []
        net_names = set()
        global_labels = set()

        # Collect components from this schematic
        if hasattr(schematic, 'symbol'):
            for symbol in schematic.symbol:
                try:
                    ref = symbol.property.Reference.value
                    # Skip power symbols (start with #)
                    if ref.startswith('#'):
                        continue

                    full_ref = f"{prefix}/{ref}" if prefix else ref
                    component_info = {
                        "reference": full_ref,
                        "value": symbol.property.Value.value if hasattr(symbol.property, 'Value') else "",
                        "footprint": symbol.property.Footprint.value if hasattr(symbol.property, 'Footprint') else "",
                        "sheet": prefix if prefix else "/"
                    }
                    components.append(component_info)
                except Exception as e:
                    logger.debug(f"Error processing symbol: {e}")
                    continue

        # Collect local labels
        if hasattr(schematic, 'label'):
            for label in schematic.label:
                if hasattr(label, 'value'):
                    net_names.add(label.value)

        # Collect global labels
        if hasattr(schematic, 'global_label'):
            for label in schematic.global_label:
                if hasattr(label, 'value'):
                    global_labels.add(label.value)
                    net_names.add(label.value)

        # Collect hierarchical labels (these connect to parent sheet)
        if hasattr(schematic, 'hierarchical_label'):
            for label in schematic.hierarchical_label:
                if hasattr(label, 'value'):
                    net_names.add(label.value)

        # Process hierarchical sheets recursively
        if hasattr(schematic, 'sheet'):
            for sheet in schematic.sheet:
                try:
                    # Get sheet properties
                    sheet_name = ""
                    sheet_file = ""

                    if hasattr(sheet, 'property'):
                        if hasattr(sheet.property, 'Sheetname'):
                            sheet_name = sheet.property.Sheetname.value
                        elif hasattr(sheet.property, 'Sheet_name'):
                            sheet_name = sheet.property.Sheet_name.value

                        if hasattr(sheet.property, 'Sheetfile'):
                            sheet_file = sheet.property.Sheetfile.value
                        elif hasattr(sheet.property, 'Sheet_file'):
                            sheet_file = sheet.property.Sheet_file.value

                    if not sheet_file:
                        logger.warning(f"Sheet has no file property: {sheet_name}")
                        continue

                    # Resolve sheet file path (relative to base_path)
                    sheet_path = Path(base_path) / sheet_file

                    if not sheet_path.exists():
                        logger.warning(f"Sheet file not found: {sheet_path}")
                        continue

                    # Load the sub-schematic
                    logger.info(f"Loading hierarchical sheet: {sheet_name} from {sheet_path}")
                    sub_schematic = Schematic(str(sheet_path))

                    # Build hierarchical prefix
                    new_prefix = f"{prefix}/{sheet_name}" if prefix else sheet_name

                    # Recursively collect from sub-schematic
                    sub_components, sub_nets, sub_globals = ConnectionManager._collect_from_schematic(
                        sub_schematic,
                        str(sheet_path.parent),
                        new_prefix
                    )

                    components.extend(sub_components)
                    net_names.update(sub_nets)
                    global_labels.update(sub_globals)

                except Exception as e:
                    logger.error(f"Error processing sheet: {e}")
                    continue

        return components, net_names, global_labels

    @staticmethod
    def generate_netlist(schematic: Schematic, schematic_path: str = None):
        """
        Generate a netlist from the schematic, including hierarchical sheets.

        Args:
            schematic: Schematic object
            schematic_path: Optional path to the schematic file (for resolving relative paths)

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
                    {"reference": "R1", "value": "10k", "footprint": "...", "sheet": "/"},
                    ...
                ]
            }
        """
        try:
            # Determine base path for resolving relative sheet paths
            if schematic_path:
                base_path = str(Path(schematic_path).parent)
            elif hasattr(schematic, '_filepath'):
                base_path = str(Path(schematic._filepath).parent)
            else:
                base_path = os.getcwd()

            # Collect components and nets recursively
            components, net_names, global_labels = ConnectionManager._collect_from_schematic(
                schematic, base_path, ""
            )

            netlist = {
                "nets": [],
                "components": components,
                "global_nets": list(global_labels)
            }

            # For each net, get connections (simplified - just list the net names)
            for net_name in net_names:
                connections = ConnectionManager.get_net_connections(schematic, net_name)
                netlist["nets"].append({
                    "name": net_name,
                    "connections": connections
                })

            logger.info(f"Generated hierarchical netlist with {len(netlist['components'])} components from {len(set(c.get('sheet', '/') for c in components))} sheets")
            return netlist

        except Exception as e:
            logger.error(f"Error generating netlist: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"nets": [], "components": [], "global_nets": []}

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
