from skip import Schematic
# Symbol class might not be directly importable in the current version
import os

class ComponentManager:
    """Manage components in a schematic"""

    @staticmethod
    def add_component(schematic: Schematic, component_def: dict):
        """Add a component to the schematic"""
        try:
            # Create a new symbol
            symbol = schematic.add_symbol(
                lib=component_def.get('library', 'Device'),
                name=component_def.get('type', 'R'), # Default to Resistor symbol 'R'
                reference=component_def.get('reference', 'R?'),
                at=[component_def.get('x', 0), component_def.get('y', 0)],
                unit=component_def.get('unit', 1),
                rotation=component_def.get('rotation', 0)
            )

            # Set properties
            if 'value' in component_def:
                symbol.property.Value.value = component_def['value']
            if 'footprint' in component_def:
                symbol.property.Footprint.value = component_def['footprint']
            if 'datasheet' in component_def:
                 symbol.property.Datasheet.value = component_def['datasheet']

            # Add additional properties
            for key, value in component_def.get('properties', {}).items():
                # Avoid overwriting standard properties unless explicitly intended
                if key not in ['Reference', 'Value', 'Footprint', 'Datasheet']:
                    symbol.property.append(key, value)

            print(f"Added component {symbol.reference} ({symbol.name}) to schematic.")
            return symbol
        except Exception as e:
            print(f"Error adding component: {e}")
            return None

    @staticmethod
    def remove_component(schematic: Schematic, component_ref: str):
        """Remove a component from the schematic by reference designator"""
        try:
            # kicad-skip doesn't have a direct remove_symbol method by reference.
            # We need to find the symbol and then remove it from the symbols list.
            symbol_to_remove = None
            for symbol in schematic.symbol:
                if symbol.reference == component_ref:
                    symbol_to_remove = symbol
                    break

            if symbol_to_remove:
                schematic.symbol.remove(symbol_to_remove)
                print(f"Removed component {component_ref} from schematic.")
                return True
            else:
                print(f"Component with reference {component_ref} not found.")
                return False
        except Exception as e:
            print(f"Error removing component {component_ref}: {e}")
            return False


    @staticmethod
    def update_component(schematic: Schematic, component_ref: str, new_properties: dict):
        """Update component properties by reference designator"""
        try:
            symbol_to_update = None
            for symbol in schematic.symbol:
                if symbol.reference == component_ref:
                    symbol_to_update = symbol
                    break

            if symbol_to_update:
                for key, value in new_properties.items():
                    if key in symbol_to_update.property:
                        symbol_to_update.property[key].value = value
                    else:
                         # Add as a new property if it doesn't exist
                         symbol_to_update.property.append(key, value)
                print(f"Updated properties for component {component_ref}.")
                return True
            else:
                print(f"Component with reference {component_ref} not found.")
                return False
        except Exception as e:
            print(f"Error updating component {component_ref}: {e}")
            return False

    @staticmethod
    def get_component(schematic: Schematic, component_ref: str):
        """Get a component by reference designator"""
        for symbol in schematic.symbol:
            if symbol.reference == component_ref:
                print(f"Found component with reference {component_ref}.")
                return symbol
        print(f"Component with reference {component_ref} not found.")
        return None

    @staticmethod
    def search_components(schematic: Schematic, query: str):
        """Search for components matching criteria (basic implementation)"""
        # This is a basic search, could be expanded to use regex or more complex logic
        matching_components = []
        query_lower = query.lower()
        for symbol in schematic.symbol:
            if query_lower in symbol.reference.lower() or \
               query_lower in symbol.name.lower() or \
               (hasattr(symbol.property, 'Value') and query_lower in symbol.property.Value.value.lower()):
                matching_components.append(symbol)
        print(f"Found {len(matching_components)} components matching query '{query}'.")
        return matching_components

    @staticmethod
    def get_all_components(schematic: Schematic):
        """Get all components in schematic"""
        print(f"Retrieving all {len(schematic.symbol)} components.")
        return list(schematic.symbol)

if __name__ == '__main__':
    # Example Usage (for testing)
    from schematic import SchematicManager # Assuming schematic.py is in the same directory

    # Create a new schematic
    test_sch = SchematicManager.create_schematic("ComponentTestSchematic")

    # Add components
    comp1_def = {"type": "R", "reference": "R1", "value": "10k", "x": 100, "y": 100}
    comp2_def = {"type": "C", "reference": "C1", "value": "0.1uF", "x": 200, "y": 100, "library": "Device"}
    comp3_def = {"type": "LED", "reference": "D1", "x": 300, "y": 100, "library": "Device", "properties": {"Color": "Red"}}

    comp1 = ComponentManager.add_component(test_sch, comp1_def)
    comp2 = ComponentManager.add_component(test_sch, comp2_def)
    comp3 = ComponentManager.add_component(test_sch, comp3_def)

    # Get a component
    retrieved_comp = ComponentManager.get_component(test_sch, "C1")
    if retrieved_comp:
        print(f"Retrieved component: {retrieved_comp.reference} ({retrieved_comp.value})")

    # Update a component
    ComponentManager.update_component(test_sch, "R1", {"value": "20k", "Tolerance": "5%"})

    # Search components
    matching_comps = ComponentManager.search_components(test_sch, "100") # Search by position
    print(f"Search results for '100': {[c.reference for c in matching_comps]}")

    # Get all components
    all_comps = ComponentManager.get_all_components(test_sch)
    print(f"All components: {[c.reference for c in all_comps]}")

    # Remove a component
    ComponentManager.remove_component(test_sch, "D1")
    all_comps_after_remove = ComponentManager.get_all_components(test_sch)
    print(f"Components after removing D1: {[c.reference for c in all_comps_after_remove]}")

    # Save the schematic (optional)
    # SchematicManager.save_schematic(test_sch, "component_test.kicad_sch")

    # Clean up (if saved)
    # if os.path.exists("component_test.kicad_sch"):
    #     os.remove("component_test.kicad_sch")
    #     print("Cleaned up component_test.kicad_sch")
