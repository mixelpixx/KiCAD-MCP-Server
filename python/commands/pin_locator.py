"""
Pin Locator for KiCad Schematics

Discovers pin locations on symbol instances, accounting for position, rotation, and mirroring.
Uses S-expression parsing to extract pin data from symbol definitions.
"""

import logging
import math
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sexpdata
from sexpdata import Symbol
from skip import Schematic

logger = logging.getLogger("kicad_interface")


class PinLocator:
    """Locate pins on symbol instances in KiCad schematics"""

    def __init__(self) -> None:
        """Initialize pin locator with empty cache"""
        self.pin_definition_cache = {}  # Cache: "lib_id:symbol_name" -> pin_data
        self._schematic_cache: Dict[str, object] = {}  # Cache: path -> loaded Schematic
        self._sexp_cache: Dict[str, Any] = {}  # Cache: path -> parsed sexpdata (mirror-aware)

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
        pins: Dict[str, Dict[str, Any]] = {}

        def extract_pins_recursive(sexp: Any) -> None:
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
                if isinstance(item, list) and len(item) > 0 and item[0] == Symbol("lib_symbols"):
                    lib_symbols = item
                    break

            if not lib_symbols:
                logger.error("No lib_symbols section found in schematic")
                return {}

            # Find the specific symbol definition.
            # KiCad lib_symbols may use a different name than the instance lib_id:
            #   instance lib_id:  "stat-tis-custom:BAT_18650"
            #   lib_symbols name: "BAT_18650_3"  (prefix stripped, unit suffix added)
            # Strategy: exact match first, then bare-name prefix match.
            bare_name = lib_id.split(":")[-1] if ":" in lib_id else lib_id

            best_match = None
            for item in lib_symbols[1:]:
                if not (isinstance(item, list) and len(item) > 1 and item[0] == Symbol("symbol")):
                    continue
                symbol_name = str(item[1]).strip('"')
                if symbol_name == lib_id:
                    best_match = item
                    break
                if best_match is None:
                    sn_bare = symbol_name.split(":")[-1] if ":" in symbol_name else symbol_name
                    if sn_bare == bare_name or (
                        sn_bare.startswith(bare_name)
                        and len(sn_bare) > len(bare_name)
                        and sn_bare[len(bare_name)] == "_"
                        and sn_bare[len(bare_name) + 1 :].isdigit()
                    ):
                        best_match = item

            if best_match is not None:
                matched_name = str(best_match[1]).strip('"')
                pins = self.parse_symbol_definition(best_match)
                self.pin_definition_cache[cache_key] = pins
                if matched_name != lib_id:
                    logger.info(
                        f"Matched {lib_id} → lib_symbols '{matched_name}' ({len(pins)} pins)"
                    )
                else:
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

        # Standard counter-clockwise rotation (math convention, Y-up).
        # Callers are responsible for any y-axis negation required to convert
        # library coordinates (y-up) to schematic coordinates (y-down) before
        # passing values here — see get_pin_location and _transform_local_point.
        rotated_x = x * cos_a - y * sin_a
        rotated_y = x * sin_a + y * cos_a

        return (rotated_x, rotated_y)

    def _get_lib_id(self, schematic_path: Path, symbol_reference: str) -> Optional[str]:
        """Helper: return the lib_id string for a placed symbol"""
        try:
            sch_key = str(schematic_path)
            if sch_key not in self._schematic_cache:
                self._schematic_cache[sch_key] = Schematic(sch_key)
            sch = self._schematic_cache[sch_key]
            for symbol in sch.symbol:
                if symbol.property.Reference.value.rstrip("_") == symbol_reference:
                    return symbol.lib_id.value if hasattr(symbol, "lib_id") else None
        except Exception:
            pass
        return None

    def _get_symbol_transform(
        self, schematic_path: Path, symbol_reference: str
    ) -> Optional[Tuple[float, float, float, bool, bool, str]]:
        """
        Read symbol position, rotation, mirror flags, and lib_id directly from the
        .kicad_sch file via sexpdata (authoritative — not kicad-skip cache, which
        does not reflect mirror/rotation changes made by rotate_schematic_component).

        Returns (x, y, rotation, mirror_x, mirror_y, lib_id) or None.
        """
        import sexpdata as _sexpdata
        from commands.wire_dragger import WireDragger

        sch_key = str(schematic_path)
        try:
            if sch_key not in self._sexp_cache:
                with open(schematic_path, "r", encoding="utf-8") as f:
                    self._sexp_cache[sch_key] = _sexpdata.loads(f.read())
        except Exception as e:
            logger.error(f"_get_symbol_transform: failed to parse {schematic_path}: {e}")
            return None

        found = WireDragger.find_symbol(self._sexp_cache[sch_key], symbol_reference)
        if found is None:
            return None

        _, sym_x, sym_y, rotation, lib_id, mirror_x, mirror_y = found
        return sym_x, sym_y, rotation, mirror_x, mirror_y, lib_id

    def get_pin_angle(
        self, schematic_path: Path, symbol_reference: str, pin_number: str
    ) -> Optional[float]:
        """
        Get the outward angle of a pin endpoint in degrees (0=right, 90=up, 180=left, 270=down).
        This is the direction a wire stub must extend to stay connected to the pin.

        Accounts for mirror flags read directly from the .kicad_sch file.

        Returns angle in degrees, or None if pin not found.
        """
        try:
            transform = self._get_symbol_transform(schematic_path, symbol_reference)
            if transform is None:
                return None

            _, _, symbol_rotation, mirror_x, mirror_y, lib_id = transform
            if not lib_id:
                return None

            pins = self.get_symbol_pins(schematic_path, lib_id)
            if pin_number not in pins:
                matched_num = next(
                    (num for num, data in pins.items() if data.get("name") == pin_number),
                    None,
                )
                if matched_num:
                    pin_number = matched_num
                else:
                    return None

            pin_def_angle = pins[pin_number].get("angle", 0)

            # Mirror flips the angle before applying symbol rotation.
            # mirror_x flips the X component of local vectors → reflects across Y axis → 180 - angle.
            # mirror_y flips the Y component of local vectors → reflects across X axis → negate angle.
            if mirror_x:
                pin_def_angle = (180 - pin_def_angle) % 360
            if mirror_y:
                pin_def_angle = (-pin_def_angle) % 360

            absolute_angle = (pin_def_angle + symbol_rotation) % 360
            return absolute_angle

        except Exception:
            return None

    def get_pin_location(
        self, schematic_path: Path, symbol_reference: str, pin_number: str
    ) -> Optional[List[float]]:
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
            # Load schematic with kicad-skip to get symbol instance
            # Use cache to avoid reloading the file for every pin lookup
            sch_key = str(schematic_path)
            if sch_key not in self._schematic_cache:
                self._schematic_cache[sch_key] = Schematic(sch_key)
            sch = self._schematic_cache[sch_key]

            # Find the symbol instance.
            # skip may write references with a trailing "_" (e.g. "R1_") — strip it when comparing.
            target_symbol = None
            for symbol in sch.symbol:
                ref = symbol.property.Reference.value.rstrip("_")
                if ref == symbol_reference:
                    target_symbol = symbol
                    break

            if not target_symbol:
                logger.error(f"Symbol {symbol_reference} not found in schematic")
                return None

            # Get symbol transform from sexpdata (authoritative: reflects mirror state
            # after rotate_schematic_component, which kicad-skip cache does not).
            transform = self._get_symbol_transform(schematic_path, symbol_reference)
            if transform is None:
                logger.error(f"Could not read transform for {symbol_reference}")
                return None
            symbol_x, symbol_y, symbol_rotation, mirror_x, mirror_y, lib_id = transform

            if not lib_id:
                logger.error(f"Symbol {symbol_reference} has no lib_id")
                return None

            logger.debug(
                f"Symbol {symbol_reference}: pos=({symbol_x}, {symbol_y}), rot={symbol_rotation}, "
                f"mirror_x={mirror_x}, mirror_y={mirror_y}, lib_id={lib_id}"
            )

            # Get pin definitions for this symbol
            pins = self.get_symbol_pins(schematic_path, lib_id)
            if not pins:
                logger.error(f"No pin definitions found for {lib_id}")
                return None

            # Find the requested pin — match by number first, then by name
            if pin_number not in pins:
                # Try matching by pin name (e.g. "VCC1", "SDA", "GND")
                matched_num = next(
                    (num for num, data in pins.items() if data.get("name") == pin_number),
                    None,
                )
                if matched_num:
                    logger.debug(
                        f"Resolved pin name '{pin_number}' to pin number '{matched_num}' on {symbol_reference}"
                    )
                    pin_number = matched_num
                else:
                    logger.error(
                        f"Pin {pin_number} not found on {symbol_reference}. Available pins: {list(pins.keys())} "
                        f"(names: {[d.get('name','') for d in pins.values()]})"
                    )
                    return None

            pin_data = pins[pin_number]
            from commands.wire_dragger import WireDragger

            abs_x, abs_y = WireDragger.pin_world_xy(
                pin_data["x"],
                pin_data["y"],
                symbol_x,
                symbol_y,
                symbol_rotation,
                mirror_x,
                mirror_y,
            )

            logger.info(f"Pin {symbol_reference}/{pin_number} located at ({abs_x}, {abs_y})")
            return [abs_x, abs_y]

        except Exception as e:
            logger.error(f"Error getting pin location: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return None

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
            # Load schematic (use cache)
            sch_key = str(schematic_path)
            if sch_key not in self._schematic_cache:
                self._schematic_cache[sch_key] = Schematic(sch_key)
            sch = self._schematic_cache[sch_key]

            # Find symbol
            target_symbol = None
            for symbol in sch.symbol:
                if symbol.property.Reference.value.rstrip("_") == symbol_reference:
                    target_symbol = symbol
                    break

            if not target_symbol:
                logger.error(f"Symbol {symbol_reference} not found")
                return {}

            # Get lib_id
            lib_id = target_symbol.lib_id.value if hasattr(target_symbol, "lib_id") else None
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
                location = self.get_pin_location(schematic_path, symbol_reference, pin_num)
                if location:
                    result[pin_num] = location

            logger.info(f"Located {len(result)} pins on {symbol_reference}")
            return result

        except Exception as e:
            logger.error(f"Error getting all symbol pins: {e}")
            return {}


if __name__ == "__main__":
    # Test pin location discovery
    import shutil
    import sys
    from pathlib import Path

    from commands.component_schematic import ComponentManager
    from commands.schematic import SchematicManager

    sys.path.insert(0, str(Path(__file__).parent.parent))

    print("=" * 80)
    print("PIN LOCATOR TEST")
    print("=" * 80)

    # Create test schematic with components (cross-platform temp directory)
    test_path = Path(tempfile.gettempdir()) / "test_pin_locator.kicad_sch"
    template_path = Path(__file__).parent.parent / "templates" / "template_with_symbols.kicad_sch"

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
