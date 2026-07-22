import logging
import uuid
from pathlib import Path
from typing import Any, List, Optional

from skip import Schematic

logger = logging.getLogger(__name__)


class ComponentManager:
    """Manage components in an in-memory (kicad-skip) schematic.

    DEPRECATION NOTE (issue #221): ``add_component`` is the legacy,
    template-clone path. It only works on schematics that already contain
    placed ``_TEMPLATE_*`` donor symbols (e.g. fixtures copied from
    ``python/templates/template_with_symbols.kicad_sch``). The production
    path for adding components is the ``add_schematic_component`` tool,
    which synthesizes instances via ``DynamicSymbolLoader.add_component``
    and works on any schematic. New code should use that instead.

    The other methods here (remove/update/get/search) are
    template-independent and remain fully supported.
    """

    # Template symbol references mapping component type to template reference
    TEMPLATE_MAP = {
        # Passives
        "R": "_TEMPLATE_R",
        "C": "_TEMPLATE_C",
        "L": "_TEMPLATE_L",
        "Y": "_TEMPLATE_Y",
        "Crystal": "_TEMPLATE_Y",
        # Semiconductors
        "D": "_TEMPLATE_D",
        "LED": "_TEMPLATE_LED",
        "Q": "_TEMPLATE_Q_NPN",
        "Q_NPN": "_TEMPLATE_Q_NPN",
        "Q_NMOS": "_TEMPLATE_Q_NMOS",
        "MOSFET": "_TEMPLATE_Q_NMOS",
        # ICs
        "U": "_TEMPLATE_U_OPAMP",
        "OpAmp": "_TEMPLATE_U_OPAMP",
        "IC": "_TEMPLATE_U_OPAMP",
        "U_REG": "_TEMPLATE_U_REG",
        "Regulator": "_TEMPLATE_U_REG",
        # Connectors
        "J": "_TEMPLATE_J2",
        "J2": "_TEMPLATE_J2",
        "J4": "_TEMPLATE_J4",
        "Conn_2": "_TEMPLATE_J2",
        "Conn_4": "_TEMPLATE_J4",
        # Misc
        "SW": "_TEMPLATE_SW",
        "Button": "_TEMPLATE_SW",
        "Switch": "_TEMPLATE_SW",
    }

    @classmethod
    def find_template(
        cls,
        schematic: Schematic,
        comp_type: str,
        library: Optional[str] = None,
    ) -> Optional[str]:
        """Find a placed ``_TEMPLATE_*`` donor symbol for a component type.

        Looks up the static ``TEMPLATE_MAP`` alias plus the naming patterns
        used by previously (dynamically) injected templates. Purely a read of
        the in-memory schematic — never mutates the schematic or the file.

        The old ``get_or_create_template`` variant of this method could fall
        through to ``DynamicSymbolLoader.load_symbol_dynamically``, which wrote
        a ``_TEMPLATE_*`` instance into the *file* mid-call and cloned onto a
        locally reloaded object. Any caller following the normal
        add-then-save pattern then saved its stale in-memory schematic,
        silently discarding the new component while leaving the injected
        template clutter behind (issue #221). That branch is gone; template
        lookup is now read-only.

        Returns the template reference, or None if no donor symbol exists.
        """

        def template_exists(template_ref: str) -> bool:
            for symbol in schematic.symbol:
                if (
                    hasattr(symbol.property, "Reference")
                    and symbol.property.Reference.value == template_ref
                ):
                    return True
            return False

        candidates: List[str] = []
        if comp_type in cls.TEMPLATE_MAP:
            candidates.append(cls.TEMPLATE_MAP[comp_type])
        if library:
            candidates.append(f"_TEMPLATE_{library}_{comp_type}")
        candidates.append(f"_TEMPLATE_{comp_type}")

        for template_ref in candidates:
            if template_exists(template_ref):
                logger.debug(f"Using template: {template_ref}")
                return template_ref
        return None

    @staticmethod
    def add_component(
        schematic: Schematic, component_def: dict, schematic_path: Optional[Path] = None
    ) -> Any:
        """
        Add a component to the in-memory schematic by cloning a placed template.

        DEPRECATED for general use (issue #221): this only works when the
        schematic already contains a placed ``_TEMPLATE_*`` donor symbol for
        the component type (fixtures based on template_with_symbols.kicad_sch).
        For arbitrary schematics use the ``add_schematic_component`` tool /
        ``DynamicSymbolLoader.add_component``, which injects the library
        definition and synthesizes the instance directly in the file.

        Args:
            schematic: Schematic object to add component to
            component_def: Component definition dictionary
            schematic_path: Unused; retained for backward signature compatibility

        Returns:
            The newly added kicad-skip symbol object (part of ``schematic``).
        """
        try:
            logger.info(
                f"Adding component: type={component_def.get('type')}, ref={component_def.get('reference')}"
            )
            logger.debug(f"Full component_def: {component_def}")

            comp_type = component_def.get("type", "R")
            library = component_def.get("library", None)  # Optional library specification

            template_ref = ComponentManager.find_template(schematic, comp_type, library)

            template_symbol = None
            if template_ref is not None:
                # Find template symbol by reference (handles special characters like +)
                for symbol in schematic.symbol:
                    if (
                        hasattr(symbol.property, "Reference")
                        and symbol.property.Reference.value == template_ref
                    ):
                        template_symbol = symbol
                        break

            if not template_symbol:
                available = [str(s.property.Reference.value) for s in schematic.symbol]
                logger.error(
                    f"No placed template for type '{comp_type}' in schematic. "
                    f"Available symbols: {available}"
                )
                raise ValueError(
                    f"No placed _TEMPLATE_* donor symbol for component type "
                    f"'{comp_type}' in this schematic. ComponentManager.add_component "
                    f"is the legacy template-clone path and only works on schematics "
                    f"seeded with template_with_symbols.kicad_sch. To add components "
                    f"to an arbitrary schematic, use the add_schematic_component tool "
                    f"(DynamicSymbolLoader.add_component), which works on any file."
                )

            # Clone the template symbol
            new_symbol = template_symbol.clone()
            logger.debug(f"Cloned template symbol {template_ref}")

            # Set reference
            reference = component_def.get("reference", "R?")
            new_symbol.property.Reference.value = reference
            logger.debug(f"Set reference to {reference}")

            # Set value
            if "value" in component_def:
                new_symbol.property.Value.value = component_def["value"]
                logger.debug(f"Set value to {component_def['value']}")

            # Set footprint
            if "footprint" in component_def:
                new_symbol.property.Footprint.value = component_def["footprint"]
                logger.debug(f"Set footprint to {component_def['footprint']}")

            # Set datasheet
            if "datasheet" in component_def:
                new_symbol.property.Datasheet.value = component_def["datasheet"]

            # Set position
            x = component_def.get("x", 0)
            y = component_def.get("y", 0)
            rotation = component_def.get("rotation", 0)
            new_symbol.at.value = [x, y, rotation]
            logger.debug(f"Set position to ({x}, {y}, {rotation})")

            # Set BOM and board flags
            new_symbol.in_bom.value = component_def.get("in_bom", True)
            new_symbol.on_board.value = component_def.get("on_board", True)
            new_symbol.dnp.value = component_def.get("dnp", False)

            # Generate new UUID
            new_symbol.uuid.value = str(uuid.uuid4())

            # NOTE: clone() already inserts the raw element into the schematic tree.
            # Calling schematic.symbol.append() again causes NamedCollection to detect
            # the reference as "taken" and rename it to "R1_" (trailing underscore).
            logger.info(f"Successfully added component {reference} to schematic")

            return new_symbol
        except Exception as e:
            logger.error(f"Error adding component: {e}", exc_info=True)
            raise

    @staticmethod
    def remove_component(schematic: Schematic, component_ref: str) -> bool:
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
                schematic.symbol._elements.remove(symbol_to_remove)
                logger.info(f"Removed component {component_ref} from schematic.")
                return True
            else:
                logger.warning(f"Component with reference {component_ref} not found.")
                return False
        except Exception as e:
            logger.error(f"Error removing component {component_ref}: {e}")
            return False

    @staticmethod
    def update_component(schematic: Schematic, component_ref: str, new_properties: dict) -> bool:
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
                        symbol_to_update.property.append(key, value)
                logger.info(f"Updated properties for component {component_ref}.")
                return True
            else:
                logger.warning(f"Component with reference {component_ref} not found.")
                return False
        except Exception as e:
            logger.error(f"Error updating component {component_ref}: {e}")
            return False

    @staticmethod
    def get_component(schematic: Schematic, component_ref: str) -> Any:
        """Get a component by reference designator"""
        for symbol in schematic.symbol:
            if symbol.reference == component_ref:
                logger.debug(f"Found component with reference {component_ref}.")
                return symbol
        logger.warning(f"Component with reference {component_ref} not found.")
        return None

    @staticmethod
    def search_components(schematic: Schematic, query: str) -> List[Any]:
        """Search for components matching criteria (basic implementation)"""
        # This is a basic search, could be expanded to use regex or more complex logic
        matching_components = []
        query_lower = query.lower()
        for symbol in schematic.symbol:
            if (
                query_lower in symbol.reference.lower()
                or query_lower in symbol.name.lower()
                or (
                    hasattr(symbol.property, "Value")
                    and query_lower in symbol.property.Value.value.lower()
                )
            ):
                matching_components.append(symbol)
        logger.debug(f"Found {len(matching_components)} components matching query '{query}'.")
        return matching_components

    @staticmethod
    def get_all_components(schematic: Schematic) -> List[Any]:
        """Get all components in schematic"""
        logger.debug(f"Retrieving all {len(schematic.symbol)} components.")
        return list(schematic.symbol)
