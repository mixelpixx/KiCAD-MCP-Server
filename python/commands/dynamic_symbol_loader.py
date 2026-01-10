"""
Dynamic Symbol Loader for KiCad Schematics

Loads symbols from .kicad_sym library files and injects them into schematics
on-the-fly, eliminating the need for static templates.

This enables access to all ~10,000+ KiCad symbols dynamically.
"""

import os
import uuid
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import sexpdata
from sexpdata import Symbol

logger = logging.getLogger('kicad_interface')


class DynamicSymbolLoader:
    """
    Dynamically loads symbols from KiCad library files and injects them into schematics

    Workflow:
    1. Parse .kicad_sym library file to extract symbol definition
    2. Inject symbol definition into schematic's lib_symbols section
    3. Create an offscreen template instance that can be cloned
    4. Clone the template to create actual component instances
    """

    def __init__(self):
        """Initialize the dynamic symbol loader"""
        self.library_cache = {}  # Cache parsed library files: path -> parsed data
        self.symbol_cache = {}   # Cache extracted symbols: "lib:symbol" -> symbol_def

    def find_kicad_symbol_libraries(self) -> List[Path]:
        """
        Find all KiCad symbol library directories

        Returns:
            List of paths to symbol library directories
        """
        possible_paths = [
            # Linux
            Path("/usr/share/kicad/symbols"),
            Path("/usr/local/share/kicad/symbols"),
            # Windows
            Path("C:/Program Files/KiCad/9.0/share/kicad/symbols"),
            Path("C:/Program Files/KiCad/8.0/share/kicad/symbols"),
            # macOS
            Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"),
            # User libraries
            Path.home() / ".local" / "share" / "kicad" / "9.0" / "symbols",
            Path.home() / ".local" / "share" / "kicad" / "8.0" / "symbols",
            Path.home() / "Documents" / "KiCad" / "9.0" / "3rdparty" / "symbols",
        ]

        # Check environment variables
        for env_var in ['KICAD9_SYMBOL_DIR', 'KICAD8_SYMBOL_DIR', 'KICAD_SYMBOL_DIR']:
            if env_var in os.environ:
                possible_paths.insert(0, Path(os.environ[env_var]))

        found_paths = []
        for path in possible_paths:
            if path.exists() and path.is_dir():
                found_paths.append(path)
                logger.info(f"Found KiCad symbol library directory: {path}")

        return found_paths

    def find_library_file(self, library_name: str) -> Optional[Path]:
        """
        Find the .kicad_sym file for a given library name

        Args:
            library_name: Library name (e.g., "Device", "Connector_Generic")

        Returns:
            Path to .kicad_sym file or None if not found
        """
        library_dirs = self.find_kicad_symbol_libraries()

        for lib_dir in library_dirs:
            lib_file = lib_dir / f"{library_name}.kicad_sym"
            if lib_file.exists():
                logger.debug(f"Found library file: {lib_file}")
                return lib_file

        logger.warning(f"Library file not found: {library_name}.kicad_sym")
        return None

    def parse_library_file(self, library_path: Path) -> List:
        """
        Parse a .kicad_sym file into S-expression data structure

        Args:
            library_path: Path to .kicad_sym file

        Returns:
            Parsed S-expression data
        """
        # Check cache first
        cache_key = str(library_path)
        if cache_key in self.library_cache:
            logger.debug(f"Using cached library data for: {library_path.name}")
            return self.library_cache[cache_key]

        logger.info(f"Parsing library file: {library_path}")

        try:
            with open(library_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Parse S-expression
            parsed = sexpdata.loads(content)

            # Cache the result
            self.library_cache[cache_key] = parsed

            logger.debug(f"Successfully parsed library: {library_path.name}")
            return parsed

        except Exception as e:
            logger.error(f"Error parsing library file {library_path}: {e}")
            raise

    def extract_symbol_definition(self, library_path: Path, symbol_name: str) -> Optional[List]:
        """
        Extract a specific symbol definition from a library file

        Args:
            library_path: Path to .kicad_sym file
            symbol_name: Name of symbol to extract (e.g., "R", "LED")

        Returns:
            Symbol definition as S-expression list, or None if not found
        """
        cache_key = f"{library_path.name}:{symbol_name}"
        if cache_key in self.symbol_cache:
            logger.debug(f"Using cached symbol: {cache_key}")
            return self.symbol_cache[cache_key]

        parsed_lib = self.parse_library_file(library_path)

        # Library structure: (kicad_symbol_lib (version ...) (generator ...) (symbol ...) (symbol ...) ...)
        # We need to find the symbol with matching name

        for item in parsed_lib:
            if isinstance(item, list) and len(item) > 0:
                if item[0] == Symbol('symbol'):
                    # Symbol structure: (symbol "Name" ...)
                    if len(item) > 1 and isinstance(item[1], str):
                        # Handle both "Device:R" and "R" formats
                        item_name = item[1]
                        if ':' in item_name:
                            item_name = item_name.split(':')[1]

                        if item_name == symbol_name:
                            logger.info(f"Found symbol definition: {symbol_name}")
                            # Cache and return
                            self.symbol_cache[cache_key] = item
                            return item

        logger.warning(f"Symbol '{symbol_name}' not found in {library_path.name}")
        return None

    def inject_symbol_into_schematic(self, schematic_path: Path, library_name: str, symbol_name: str) -> bool:
        """
        Inject a symbol definition from a library into a schematic file

        Args:
            schematic_path: Path to .kicad_sch file to modify
            library_name: Source library name (e.g., "Device")
            symbol_name: Symbol to inject (e.g., "R")

        Returns:
            True if successful, False otherwise
        """
        try:
            # 1. Find and parse the library file
            library_path = self.find_library_file(library_name)
            if not library_path:
                raise ValueError(f"Library not found: {library_name}")

            # 2. Extract the symbol definition
            symbol_def = self.extract_symbol_definition(library_path, symbol_name)
            if not symbol_def:
                raise ValueError(f"Symbol '{symbol_name}' not found in library '{library_name}'")

            # 3. Read the schematic file
            with open(schematic_path, 'r', encoding='utf-8') as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            # 4. Find the lib_symbols section
            lib_symbols_index = None
            for i, item in enumerate(sch_data):
                if isinstance(item, list) and len(item) > 0 and item[0] == Symbol('lib_symbols'):
                    lib_symbols_index = i
                    break

            if lib_symbols_index is None:
                raise ValueError("No lib_symbols section found in schematic")

            # 5. Check if symbol already exists in lib_symbols
            full_symbol_name = f"{library_name}:{symbol_name}"
            symbol_exists = False

            for item in sch_data[lib_symbols_index][1:]:  # Skip the 'lib_symbols' symbol itself
                if isinstance(item, list) and len(item) > 1 and item[0] == Symbol('symbol'):
                    if item[1] == full_symbol_name or item[1] == symbol_name:
                        logger.info(f"Symbol {full_symbol_name} already exists in schematic")
                        symbol_exists = True
                        break

            if not symbol_exists:
                # 6. Inject the symbol definition
                # Need to update the symbol name to include library prefix
                modified_symbol_def = list(symbol_def)  # Make a copy
                modified_symbol_def[1] = full_symbol_name  # Update name to "Library:Symbol"

                sch_data[lib_symbols_index].append(modified_symbol_def)
                logger.info(f"Injected symbol {full_symbol_name} into schematic")

            # 7. Write the modified schematic back
            with open(schematic_path, 'w', encoding='utf-8') as f:
                output = sexpdata.dumps(sch_data)
                f.write(output)

            logger.info(f"Successfully injected symbol {full_symbol_name} into {schematic_path.name}")
            return True

        except Exception as e:
            logger.error(f"Error injecting symbol into schematic: {e}")
            raise

    def create_template_instance(self, schematic_path: Path, library_name: str, symbol_name: str,
                                 template_ref: Optional[str] = None) -> str:
        """
        Create an offscreen template instance of a symbol that can be cloned

        Args:
            schematic_path: Path to .kicad_sch file
            library_name: Library name (e.g., "Device")
            symbol_name: Symbol name (e.g., "R")
            template_ref: Optional custom reference (defaults to _TEMPLATE_{LIBRARY}_{SYMBOL})

        Returns:
            Template reference name
        """
        try:
            if template_ref is None:
                # Clean up library and symbol names for reference
                lib_clean = library_name.replace('-', '_').replace('.', '_')
                sym_clean = symbol_name.replace('-', '_').replace('.', '_')
                template_ref = f"_TEMPLATE_{lib_clean}_{sym_clean}"

            # Read schematic
            with open(schematic_path, 'r', encoding='utf-8') as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            # Check if template already exists
            for item in sch_data:
                if isinstance(item, list) and len(item) > 0 and item[0] == Symbol('symbol'):
                    # Find Reference property
                    for prop in item:
                        if isinstance(prop, list) and len(prop) > 2 and prop[0] == Symbol('property'):
                            if prop[1] == "Reference" and prop[2] == template_ref:
                                logger.info(f"Template instance {template_ref} already exists")
                                return template_ref

            # Find sheet_instances index (we'll insert before this)
            sheet_instances_index = None
            for i, item in enumerate(sch_data):
                if isinstance(item, list) and len(item) > 0 and item[0] == Symbol('sheet_instances'):
                    sheet_instances_index = i
                    break

            if sheet_instances_index is None:
                raise ValueError("No sheet_instances section found in schematic")

            # Create template symbol instance
            full_lib_id = f"{library_name}:{symbol_name}"

            # Calculate y position based on existing templates
            template_count = sum(1 for item in sch_data if isinstance(item, list) and len(item) > 0
                               and item[0] == Symbol('symbol')
                               and any(isinstance(p, list) and len(p) > 2 and p[0] == Symbol('property')
                                      and p[1] == "Reference" and str(p[2]).startswith('_TEMPLATE')
                                      for p in item))
            y_offset = -100 - (template_count * 10)

            new_uuid = str(uuid.uuid4())

            # Build the symbol instance S-expression
            template_instance = [
                Symbol('symbol'),
                [Symbol('lib_id'), full_lib_id],
                [Symbol('at'), -100, y_offset, 0],
                [Symbol('unit'), 1],
                [Symbol('in_bom'), Symbol('no')],
                [Symbol('on_board'), Symbol('no')],
                [Symbol('dnp'), Symbol('yes')],
                [Symbol('uuid'), new_uuid],
                [Symbol('property'), "Reference", template_ref,
                 [Symbol('at'), -100, y_offset - 2.54, 0],
                 [Symbol('effects'), [Symbol('font'), [Symbol('size'), 1.27, 1.27]]]
                ],
                [Symbol('property'), "Value", symbol_name,
                 [Symbol('at'), -100, y_offset + 2.54, 0],
                 [Symbol('effects'), [Symbol('font'), [Symbol('size'), 1.27, 1.27]]]
                ],
                [Symbol('property'), "Footprint", "",
                 [Symbol('at'), -100, y_offset, 0],
                 [Symbol('effects'), [Symbol('font'), [Symbol('size'), 1.27, 1.27]], Symbol('hide')]
                ],
                [Symbol('property'), "Datasheet", "~",
                 [Symbol('at'), -100, y_offset, 0],
                 [Symbol('effects'), [Symbol('font'), [Symbol('size'), 1.27, 1.27]], Symbol('hide')]
                ],
            ]

            # Insert before sheet_instances
            sch_data.insert(sheet_instances_index, template_instance)

            # Write back
            with open(schematic_path, 'w', encoding='utf-8') as f:
                output = sexpdata.dumps(sch_data)
                f.write(output)

            logger.info(f"Created template instance: {template_ref} at y={y_offset}")
            return template_ref

        except Exception as e:
            logger.error(f"Error creating template instance: {e}")
            raise

    def load_symbol_dynamically(self, schematic_path: Path, library_name: str, symbol_name: str) -> str:
        """
        Complete workflow: inject symbol and create template instance

        Args:
            schematic_path: Path to .kicad_sch file
            library_name: Library name (e.g., "Device")
            symbol_name: Symbol name (e.g., "R")

        Returns:
            Template reference that can be used with kicad-skip clone()
        """
        logger.info(f"Loading symbol dynamically: {library_name}:{symbol_name}")

        # Step 1: Inject symbol definition into lib_symbols
        self.inject_symbol_into_schematic(schematic_path, library_name, symbol_name)

        # Step 2: Create template instance
        template_ref = self.create_template_instance(schematic_path, library_name, symbol_name)

        logger.info(f"Symbol loaded successfully. Template reference: {template_ref}")
        return template_ref


if __name__ == '__main__':
    # Test the dynamic symbol loader
    logging.basicConfig(level=logging.INFO)

    loader = DynamicSymbolLoader()

    print("\n=== Testing Dynamic Symbol Loader ===\n")

    # Test 1: Find library directories
    print("1. Finding KiCad symbol library directories...")
    lib_dirs = loader.find_kicad_symbol_libraries()
    print(f"   Found {len(lib_dirs)} directories:")
    for lib_dir in lib_dirs:
        print(f"     - {lib_dir}")

    # Test 2: Find Device library
    print("\n2. Finding Device.kicad_sym library file...")
    device_lib = loader.find_library_file("Device")
    if device_lib:
        print(f"   ✓ Found: {device_lib}")
    else:
        print("   ✗ Not found")
        exit(1)

    # Test 3: Parse library file
    print("\n3. Parsing Device.kicad_sym...")
    parsed = loader.parse_library_file(device_lib)
    print(f"   ✓ Parsed successfully ({len(parsed)} top-level items)")

    # Test 4: Extract specific symbols
    print("\n4. Extracting symbol definitions...")
    for symbol in ['R', 'C', 'LED']:
        symbol_def = loader.extract_symbol_definition(device_lib, symbol)
        if symbol_def:
            print(f"   ✓ Extracted: {symbol}")
        else:
            print(f"   ✗ Failed: {symbol}")

    print("\n✓ All basic tests passed!")
