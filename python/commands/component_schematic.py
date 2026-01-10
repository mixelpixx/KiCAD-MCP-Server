from skip import Schematic
import os
import uuid
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Import dynamic symbol loader
try:
    from commands.dynamic_symbol_loader import DynamicSymbolLoader
    DYNAMIC_LOADING_AVAILABLE = True
except ImportError:
    logger.warning("Dynamic symbol loader not available - falling back to template-only mode")
    DYNAMIC_LOADING_AVAILABLE = False

class ComponentManager:
    """Manage components in a schematic"""

    # Initialize dynamic loader (class variable, shared across instances)
    _dynamic_loader = None

    @classmethod
    def get_dynamic_loader(cls):
        """Get or create dynamic symbol loader instance"""
        if cls._dynamic_loader is None and DYNAMIC_LOADING_AVAILABLE:
            cls._dynamic_loader = DynamicSymbolLoader()
        return cls._dynamic_loader

    # Template symbol references mapping component type to template reference
    TEMPLATE_MAP = {
        # Passives
        'R': '_TEMPLATE_R',
        'C': '_TEMPLATE_C',
        'L': '_TEMPLATE_L',
        'Y': '_TEMPLATE_Y',
        'Crystal': '_TEMPLATE_Y',

        # Semiconductors
        'D': '_TEMPLATE_D',
        'LED': '_TEMPLATE_LED',
        'Q': '_TEMPLATE_Q_NPN',
        'Q_NPN': '_TEMPLATE_Q_NPN',
        'Q_NMOS': '_TEMPLATE_Q_NMOS',
        'MOSFET': '_TEMPLATE_Q_NMOS',

        # ICs
        'U': '_TEMPLATE_U_OPAMP',
        'OpAmp': '_TEMPLATE_U_OPAMP',
        'IC': '_TEMPLATE_U_OPAMP',
        'U_REG': '_TEMPLATE_U_REG',
        'Regulator': '_TEMPLATE_U_REG',

        # Connectors
        'J': '_TEMPLATE_J2',
        'J2': '_TEMPLATE_J2',
        'J4': '_TEMPLATE_J4',
        'Conn_2': '_TEMPLATE_J2',
        'Conn_4': '_TEMPLATE_J4',

        # Misc
        'SW': '_TEMPLATE_SW',
        'Button': '_TEMPLATE_SW',
        'Switch': '_TEMPLATE_SW',
    }

    @classmethod
    def get_or_create_template(cls, schematic: Schematic, comp_type: str, library: Optional[str] = None,
                              schematic_path: Optional[Path] = None) -> tuple:
        """
        Get template reference for a component type, creating it dynamically if needed

        Args:
            schematic: Schematic object
            comp_type: Component type (e.g., 'R', 'LED', 'STM32F103C8Tx')
            library: Optional library name (defaults to 'Device' for common types)
            schematic_path: Optional path to schematic file (required for dynamic loading)

        Returns:
            Tuple of (template_ref, needs_reload) where needs_reload indicates if schematic must be reloaded
        """
        # Helper function to check if template exists in schematic
        def template_exists(schematic, template_ref):
            """Check if template exists by iterating symbols (handles special characters)"""
            for symbol in schematic.symbol:
                if hasattr(symbol.property, 'Reference') and symbol.property.Reference.value == template_ref:
                    return True
            return False

        # 1. Check static template map first
        if comp_type in cls.TEMPLATE_MAP:
            template_ref = cls.TEMPLATE_MAP[comp_type]
            # Verify template exists in schematic
            if template_exists(schematic, template_ref):
                logger.debug(f"Using static template: {template_ref}")
                return (template_ref, False)

        # 2. Check if dynamically loaded template already exists
        # Build potential template reference names
        potential_refs = []
        if library:
            potential_refs.append(f"_TEMPLATE_{library}_{comp_type}")
        potential_refs.append(f"_TEMPLATE_{comp_type}")
        if comp_type in cls.TEMPLATE_MAP:
            potential_refs.append(cls.TEMPLATE_MAP[comp_type])

        # Check each potential reference
        for template_ref in potential_refs:
            if template_exists(schematic, template_ref):
                logger.debug(f"Found existing template: {template_ref}")
                return (template_ref, False)

        # 3. Try dynamic loading
        if not DYNAMIC_LOADING_AVAILABLE:
            logger.warning(f"Component type '{comp_type}' not in static templates and dynamic loading unavailable")
            # Fall back to basic resistor template
            return ('_TEMPLATE_R', False)

        loader = cls.get_dynamic_loader()
        if not loader:
            logger.warning("Dynamic loader unavailable, using fallback template")
            return ('_TEMPLATE_R', False)

        # Check if schematic path is available
        if schematic_path is None:
            logger.warning("Dynamic loading requires schematic file path but none was provided")
            fallback = cls.TEMPLATE_MAP.get(comp_type, '_TEMPLATE_R')
            return (fallback, False)

        # Determine library name
        if library is None:
            # Default library for common component types
            library = 'Device'  # Most passives and basic components are in Device library

        try:
            logger.info(f"Attempting dynamic load: {library}:{comp_type} from {schematic_path}")

            # Use dynamic symbol loader to inject symbol and create template
            template_ref = loader.load_symbol_dynamically(schematic_path, library, comp_type)

            logger.info(f"Successfully loaded symbol dynamically. Template ref: {template_ref}")
            # Signal that schematic needs reload to see new template
            return (template_ref, True)

        except Exception as e:
            logger.error(f"Dynamic loading failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Fall back to static template if available
            fallback = cls.TEMPLATE_MAP.get(comp_type, '_TEMPLATE_R')
            return (fallback, False)

    @staticmethod
    def add_component(schematic: Schematic, component_def: dict, schematic_path: Optional[Path] = None):
        """
        Add a component to the schematic by cloning from template

        Args:
            schematic: Schematic object to add component to
            component_def: Component definition dictionary
            schematic_path: Optional path to schematic file (enables dynamic symbol loading)

        Returns:
            Tuple of (new_symbol, needs_reload) where needs_reload indicates if caller should reload schematic
        """
        try:
            from commands.schematic import SchematicManager

            logger.info(f"Adding component: type={component_def.get('type')}, ref={component_def.get('reference')}")
            logger.debug(f"Full component_def: {component_def}")

            # Get component type and determine template
            comp_type = component_def.get('type', 'R')
            library = component_def.get('library', None)  # Optional library specification

            # Get template reference (static or dynamic)
            template_ref, needs_reload = ComponentManager.get_or_create_template(schematic, comp_type, library, schematic_path)

            # If dynamic loading occurred, reload schematic to see new template
            if needs_reload and schematic_path:
                logger.info(f"Reloading schematic after dynamic loading: {schematic_path}")
                schematic = SchematicManager.load_schematic(str(schematic_path))

            # Find template symbol by reference (handles special characters like +)
            template_symbol = None
            for symbol in schematic.symbol:
                if hasattr(symbol.property, 'Reference') and symbol.property.Reference.value == template_ref:
                    template_symbol = symbol
                    break

            if not template_symbol:
                logger.error(f"Template symbol {template_ref} not found in schematic. Available symbols: {[str(s.property.Reference.value) for s in schematic.symbol]}")
                raise ValueError(f"Template symbol {template_ref} not found. The schematic must be created from template_with_symbols.kicad_sch")

            # Clone the template symbol
            new_symbol = template_symbol.clone()
            logger.debug(f"Cloned template symbol {template_ref}")

            # Set reference
            reference = component_def.get('reference', 'R?')
            new_symbol.property.Reference.value = reference
            logger.debug(f"Set reference to {reference}")

            # Set value
            if 'value' in component_def:
                new_symbol.property.Value.value = component_def['value']
                logger.debug(f"Set value to {component_def['value']}")

            # Set footprint
            if 'footprint' in component_def:
                new_symbol.property.Footprint.value = component_def['footprint']
                logger.debug(f"Set footprint to {component_def['footprint']}")

            # Set datasheet
            if 'datasheet' in component_def:
                new_symbol.property.Datasheet.value = component_def['datasheet']

            # Set position
            x = component_def.get('x', 0)
            y = component_def.get('y', 0)
            rotation = component_def.get('rotation', 0)
            new_symbol.at.value = [x, y, rotation]
            logger.debug(f"Set position to ({x}, {y}, {rotation})")

            # Set BOM and board flags
            new_symbol.in_bom.value = component_def.get('in_bom', True)
            new_symbol.on_board.value = component_def.get('on_board', True)
            new_symbol.dnp.value = component_def.get('dnp', False)

            # Generate new UUID
            new_symbol.uuid.value = str(uuid.uuid4())

            # Append to schematic
            schematic.symbol.append(new_symbol)
            logger.info(f"Successfully added component {reference} to schematic")

            return new_symbol
        except Exception as e:
            logger.error(f"Error adding component: {e}", exc_info=True)
            raise

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
