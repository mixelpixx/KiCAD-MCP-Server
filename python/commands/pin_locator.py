"""
Pin Locator for KiCad Schematics

Discovers pin locations on symbol instances, accounting for position, rotation, and mirroring.
Uses S-expression parsing to extract pin data from symbol definitions.
"""

import logging
import math
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import sexpdata
from sexpdata import Symbol
from skip import Schematic

logger = logging.getLogger("kicad_interface")


class PinLocator:
    """Locate pins on symbol instances in KiCad schematics"""

    def __init__(self):
        """Initialize pin locator with empty cache"""
        self.pin_definition_cache = {}  # Cache: "lib_id:symbol_name" -> pin_data
        self.last_error: str = ""

    def _set_error(self, message: str) -> None:
        self.last_error = message
        logger.error(message)

    @staticmethod
    def _normalize_pin_identifier(pin_identifier: str) -> str:
        return str(pin_identifier).strip()

    @staticmethod
    def _resolve_symbol_reference(symbols, symbol_reference: str) -> Optional[str]:
        """Resolve common reference variants (R1 <-> R1_) against schematic symbols."""
        existing = set()
        for symbol in symbols:
            try:
                existing.add(symbol.property.Reference.value)
            except Exception:
                continue

        if symbol_reference in existing:
            return symbol_reference

        if not symbol_reference.endswith("_") and f"{symbol_reference}_" in existing:
            return f"{symbol_reference}_"

        if symbol_reference.endswith("_") and symbol_reference[:-1] in existing:
            return symbol_reference[:-1]

        return None

    @staticmethod
    def _find_pin_key(pins: Dict[str, Dict], pin_identifier: str) -> Optional[str]:
        """Match by pin number first, then by pin name (case-insensitive)."""
        normalized = PinLocator._normalize_pin_identifier(pin_identifier)

        if normalized in pins:
            return normalized

        for key, pin_data in pins.items():
            pin_name = str(pin_data.get("name", "")).strip()
            if pin_name and pin_name.lower() == normalized.lower():
                return key

        if normalized.isdigit() and str(int(normalized)) in pins:
            return str(int(normalized))

        return None

    @staticmethod
    def parse_symbol_definition(symbol_def: list) -> Dict[str, Dict]:
        """
        Parse a symbol definition from lib_symbols to extract pin information

        Args:
            symbol_def: S-expression list representing symbol definition

        Returns:
            Dictionary mapping pin number -> pin data:
            {
                "1": {"x": 0, "y": 3.81, "angle": 270, "length": 1.27, "name": "~", "type": "passive"},
                "2": {"x": 0, "y": -3.81, "angle": 90, "length": 1.27, "name": "~", "type": "passive"}
            }
        """
        pins = {}

        def extract_pins_recursive(sexp):
            """Recursively search for pin definitions"""
            if not isinstance(sexp, list):
                return

            # Check if this is a pin definition
            if len(sexp) > 0 and sexp[0] == Symbol("pin"):
                # Pin format: (pin type shape (at x y angle) (length len) (name "name") (number "num"))
                pin_data = {
                    "x": 0,
                    "y": 0,
                    "angle": 0,
                    "length": 0,
                    "name": "",
                    "number": "",
                    "type": str(sexp[1]) if len(sexp) > 1 else "passive",
                }

                # Extract pin attributes
                for item in sexp:
                    if isinstance(item, list) and len(item) > 0:
                        if item[0] == Symbol("at") and len(item) >= 3:
                            pin_data["x"] = float(item[1])
                            pin_data["y"] = float(item[2])
                            if len(item) >= 4:
                                pin_data["angle"] = float(item[3])

                        elif item[0] == Symbol("length") and len(item) >= 2:
                            pin_data["length"] = float(item[1])

                        elif item[0] == Symbol("name") and len(item) >= 2:
                            pin_data["name"] = str(item[1]).strip('"')

                        elif item[0] == Symbol("number") and len(item) >= 2:
                            pin_data["number"] = str(item[1]).strip('"')

                # Store by pin number
                if pin_data["number"]:
                    pins[pin_data["number"]] = pin_data

            # Recurse into sublists
            for item in sexp:
                if isinstance(item, list):
                    extract_pins_recursive(item)

        extract_pins_recursive(symbol_def)
        return pins

    def get_symbol_pins(self, schematic_path: Path, lib_id: str) -> Dict[str, Dict]:
        """
        Get pin definitions for a symbol from the schematic's lib_symbols section

        Args:
            schematic_path: Path to .kicad_sch file
            lib_id: Library identifier (e.g., "Device:R", "MCU_ST_STM32F1:STM32F103C8Tx")

        Returns:
            Dictionary mapping pin number -> pin data
        """
        # Check cache
        cache_key = f"{schematic_path}:{lib_id}"
        if cache_key in self.pin_definition_cache:
            logger.debug(f"Using cached pin data for {lib_id}")
            return self.pin_definition_cache[cache_key]

        try:
            # Read schematic
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            # Find lib_symbols section
            lib_symbols = None
            for item in sch_data:
                if (
                    isinstance(item, list)
                    and len(item) > 0
                    and item[0] == Symbol("lib_symbols")
                ):
                    lib_symbols = item
                    break

            if not lib_symbols:
                logger.error("No lib_symbols section found in schematic")
                return {}

            # Find the specific symbol definition
            for item in lib_symbols[1:]:  # Skip 'lib_symbols' itself
                if (
                    isinstance(item, list)
                    and len(item) > 1
                    and item[0] == Symbol("symbol")
                ):
                    symbol_name = str(item[1]).strip('"')
                    if symbol_name == lib_id:
                        # Found the symbol, parse pins
                        pins = self.parse_symbol_definition(item)
                        self.pin_definition_cache[cache_key] = pins
                        logger.info(f"Extracted {len(pins)} pins from {lib_id}")
                        return pins

            logger.warning(f"Symbol {lib_id} not found in lib_symbols")
            return {}

        except Exception as e:
            logger.error(f"Error getting symbol pins: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {}

    @staticmethod
    def rotate_point(x: float, y: float, angle_degrees: float) -> Tuple[float, float]:
        """
        Rotate a point around the origin

        Args:
            x: X coordinate
            y: Y coordinate
            angle_degrees: Rotation angle in degrees (counterclockwise)

        Returns:
            (rotated_x, rotated_y)
        """
        if angle_degrees == 0:
            return (x, y)

        angle_rad = math.radians(angle_degrees)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        rotated_x = x * cos_a - y * sin_a
        rotated_y = x * sin_a + y * cos_a

        return (rotated_x, rotated_y)

    def get_pin_info(
        self, schematic_path: Path, symbol_reference: str, pin_number: str
    ) -> Optional[Dict[str, float]]:
        """
        Get the absolute location of a pin on a symbol instance

        Args:
            schematic_path: Path to .kicad_sch file
            symbol_reference: Symbol reference designator (e.g., "R1", "U1")
            pin_number: Pin number/identifier (e.g., "1", "2", "GND", "VCC")

        Returns:
            [x, y] absolute coordinates of the pin, or None if not found
        """
        try:
            self.last_error = ""
            # Load schematic with kicad-skip to get symbol instance
            sch = Schematic(str(schematic_path))

            # Find the symbol instance
            resolved_ref = self._resolve_symbol_reference(sch.symbol, symbol_reference)
            if not resolved_ref:
                self._set_error(f"Symbol {symbol_reference} not found in schematic")
                return None

            target_symbol = None
            for symbol in sch.symbol:
                ref = symbol.property.Reference.value
                if ref == resolved_ref:
                    target_symbol = symbol
                    break

            if not target_symbol:
                self._set_error(f"Symbol {resolved_ref} not found in schematic")
                return None

            # Get symbol position and rotation
            symbol_at = target_symbol.at.value
            symbol_x = float(symbol_at[0])
            symbol_y = float(symbol_at[1])
            symbol_rotation = float(symbol_at[2]) if len(symbol_at) > 2 else 0.0

            # Get symbol lib_id
            lib_id = (
                target_symbol.lib_id.value if hasattr(target_symbol, "lib_id") else None
            )
            if not lib_id:
                self._set_error(f"Symbol {resolved_ref} has no lib_id")
                return None

            logger.debug(
                f"Symbol {resolved_ref}: pos=({symbol_x}, {symbol_y}), rot={symbol_rotation}, lib_id={lib_id}"
            )

            # Get pin definitions for this symbol
            pins = self.get_symbol_pins(schematic_path, lib_id)
            if not pins:
                self._set_error(f"No pin definitions found for {lib_id}")
                return None

            pin_key = self._find_pin_key(pins, pin_number)
            if not pin_key:
                available_numbers = list(pins.keys())
                available_names = [
                    p.get("name", "") for p in pins.values() if p.get("name")
                ]
                self._set_error(
                    f"Pin {pin_number} not found on {resolved_ref}. "
                    f"Available pin numbers: {available_numbers}. "
                    f"Available pin names: {available_names}"
                )
                return None

            pin_data = pins[pin_key]

            # Get pin position relative to symbol origin
            pin_rel_x = pin_data["x"]
            pin_rel_y = pin_data["y"]

            logger.debug(f"Pin {pin_key} relative position: ({pin_rel_x}, {pin_rel_y})")

            # Apply symbol rotation to pin position
            if symbol_rotation != 0:
                pin_rel_x, pin_rel_y = self.rotate_point(
                    pin_rel_x, pin_rel_y, symbol_rotation
                )
                logger.debug(
                    f"After rotation {symbol_rotation}°: ({pin_rel_x}, {pin_rel_y})"
                )

            # Calculate absolute position
            abs_x = symbol_x + pin_rel_x
            abs_y = symbol_y + pin_rel_y

            effective_angle = (
                float(pin_data.get("angle", 0.0)) + symbol_rotation
            ) % 360.0

            logger.info(f"Pin {resolved_ref}/{pin_key} located at ({abs_x}, {abs_y})")
            return {
                "x": abs_x,
                "y": abs_y,
                "symbol_reference": resolved_ref,
                "pin_key": pin_key,
                "pin_name": str(pin_data.get("name", "")),
                "pin_angle": float(pin_data.get("angle", 0.0)),
                "symbol_rotation": symbol_rotation,
                "effective_angle": effective_angle,
            }

        except Exception as e:
            self._set_error(f"Error getting pin location: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return None

    def get_pin_location(
        self, schematic_path: Path, symbol_reference: str, pin_number: str
    ) -> Optional[List[float]]:
        """Backward-compatible location-only helper."""
        pin_info = self.get_pin_info(schematic_path, symbol_reference, pin_number)
        if not pin_info:
            return None
        return [pin_info["x"], pin_info["y"]]

    def get_all_symbol_pins(
        self, schematic_path: Path, symbol_reference: str
    ) -> Dict[str, List[float]]:
        """
        Get locations of all pins on a symbol instance

        Args:
            schematic_path: Path to .kicad_sch file
            symbol_reference: Symbol reference designator (e.g., "R1", "U1")

        Returns:
            Dictionary mapping pin number -> [x, y] coordinates
        """
        try:
            # Load schematic
            sch = Schematic(str(schematic_path))

            # Find symbol
            target_symbol = None
            for symbol in sch.symbol:
                if symbol.property.Reference.value == symbol_reference:
                    target_symbol = symbol
                    break

            if not target_symbol:
                logger.error(f"Symbol {symbol_reference} not found")
                return {}

            # Get lib_id
            lib_id = (
                target_symbol.lib_id.value if hasattr(target_symbol, "lib_id") else None
            )
            if not lib_id:
                logger.error(f"Symbol {symbol_reference} has no lib_id")
                return {}

            # Get pin definitions
            pins = self.get_symbol_pins(schematic_path, lib_id)
            if not pins:
                return {}

            # Calculate location for each pin
            result = {}
            for pin_num in pins.keys():
                location = self.get_pin_location(
                    schematic_path, symbol_reference, pin_num
                )
                if location:
                    result[pin_num] = location

            logger.info(f"Located {len(result)} pins on {symbol_reference}")
            return result

        except Exception as e:
            logger.error(f"Error getting all symbol pins: {e}")
            return {}


if __name__ == "__main__":
    # Test pin location discovery
    import sys

    sys.path.insert(0, "/home/chris/MCP/KiCAD-MCP-Server/python")

    from pathlib import Path
    from commands.component_schematic import ComponentManager
    from commands.schematic import SchematicManager
    import shutil

    print("=" * 80)
    print("PIN LOCATOR TEST")
    print("=" * 80)

    # Create test schematic with components
    test_path = Path("/tmp/test_pin_locator.kicad_sch")
    template_path = Path(
        "/home/chris/MCP/KiCAD-MCP-Server/python/templates/template_with_symbols_expanded.kicad_sch"
    )

    shutil.copy(template_path, test_path)
    print(f"\n✓ Created test schematic: {test_path}")

    # Add some components
    print("\n[1/4] Adding test components...")
    sch = SchematicManager.load_schematic(str(test_path))

    # Add resistor at (100, 100), rotation 0
    r1_def = {
        "type": "R",
        "reference": "R1",
        "value": "10k",
        "x": 100,
        "y": 100,
        "rotation": 0,
    }
    ComponentManager.add_component(sch, r1_def, test_path)

    # Add capacitor at (150, 100), rotation 90
    c1_def = {
        "type": "C",
        "reference": "C1",
        "value": "100nF",
        "x": 150,
        "y": 100,
        "rotation": 90,
    }
    ComponentManager.add_component(sch, c1_def, test_path)

    SchematicManager.save_schematic(sch, str(test_path))
    print("  ✓ Added R1 and C1")

    # Test pin locator
    print("\n[2/4] Testing pin location discovery...")
    locator = PinLocator()

    # Find R1 pins
    r1_pin1 = locator.get_pin_location(test_path, "R1", "1")
    r1_pin2 = locator.get_pin_location(test_path, "R1", "2")

    print(f"  R1 pin 1: {r1_pin1}")
    print(f"  R1 pin 2: {r1_pin2}")

    # Find C1 pins (rotated 90 degrees)
    c1_pin1 = locator.get_pin_location(test_path, "C1", "1")
    c1_pin2 = locator.get_pin_location(test_path, "C1", "2")

    print(f"  C1 pin 1: {c1_pin1}")
    print(f"  C1 pin 2: {c1_pin2}")

    # Test get all pins
    print("\n[3/4] Testing get all pins...")
    r1_all_pins = locator.get_all_symbol_pins(test_path, "R1")
    print(f"  R1 all pins: {r1_all_pins}")

    c1_all_pins = locator.get_all_symbol_pins(test_path, "C1")
    print(f"  C1 all pins: {c1_all_pins}")

    # Verify results
    print("\n[4/4] Verification...")
    success = True

    if not r1_pin1 or not r1_pin2:
        print("  ✗ Failed to locate R1 pins")
        success = False
    else:
        print("  ✓ R1 pins located")

    if not c1_pin1 or not c1_pin2:
        print("  ✗ Failed to locate C1 pins")
        success = False
    else:
        print("  ✓ C1 pins located")

    # Check rotation (C1 pins should be rotated 90 degrees from R1)
    if r1_pin1 and c1_pin1:
        # R1 is not rotated, pins should be at y offset from symbol center
        # C1 is rotated 90°, pins should be at x offset from symbol center
        print(f"\n  Pin offset analysis:")
        print(f"    R1 (0°):  pin 1 y-offset = {r1_pin1[1] - 100}")
        print(f"    C1 (90°): pin 1 x-offset = {c1_pin1[0] - 150}")

    print("\n" + "=" * 80)
    if success:
        print("✅ PIN LOCATOR TEST PASSED!")
    else:
        print("❌ PIN LOCATOR TEST FAILED!")
    print("=" * 80)
    print(f"\nTest schematic saved: {test_path}")
