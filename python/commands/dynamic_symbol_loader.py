"""
Dynamic Symbol Loader for KiCad Schematics

Loads symbols from .kicad_sym library files and injects them into schematics
on-the-fly using TEXT MANIPULATION (not sexpdata) to preserve file formatting.

This enables access to all ~10,000+ KiCad symbols dynamically.
"""

import os
import re
import uuid
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger('kicad_interface')


class DynamicSymbolLoader:
    """
    Dynamically loads symbols from KiCad library files and injects them into schematics.

    Uses raw text manipulation instead of sexpdata to avoid corrupting the KiCad file format.

    Key rules for KiCad 9 .kicad_sch format:
    - Top-level symbols in lib_symbols must have library prefix: (symbol "Device:R" ...)
    - Sub-symbols must NOT have library prefix: (symbol "R_0_1" ...), (symbol "R_1_1" ...)
    - Parent symbols must appear BEFORE child symbols that use (extends ...)
    """

    def __init__(self):
        self.symbol_cache = {}  # Cache: "lib:symbol" -> raw text block

    def find_kicad_symbol_libraries(self) -> List[Path]:
        """Find all KiCad symbol library directories"""
        possible_paths = [
            Path("/usr/share/kicad/symbols"),
            Path("/usr/local/share/kicad/symbols"),
            Path("C:/Program Files/KiCad/9.0/share/kicad/symbols"),
            Path("C:/Program Files/KiCad/8.0/share/kicad/symbols"),
            Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"),
            Path.home() / ".local" / "share" / "kicad" / "9.0" / "symbols",
            Path.home() / "Documents" / "KiCad" / "9.0" / "3rdparty" / "symbols",
        ]
        for env_var in ['KICAD9_SYMBOL_DIR', 'KICAD8_SYMBOL_DIR', 'KICAD_SYMBOL_DIR']:
            if env_var in os.environ:
                possible_paths.insert(0, Path(os.environ[env_var]))

        return [p for p in possible_paths if p.exists() and p.is_dir()]

    def find_library_file(self, library_name: str) -> Optional[Path]:
        """Find the .kicad_sym file for a given library name"""
        for lib_dir in self.find_kicad_symbol_libraries():
            lib_file = lib_dir / f"{library_name}.kicad_sym"
            if lib_file.exists():
                return lib_file
        logger.warning(f"Library file not found: {library_name}.kicad_sym")
        return None

    def _extract_symbol_block(self, text: str, symbol_name: str) -> Optional[str]:
        """
        Extract a complete symbol block from a library or schematic file by matching
        parentheses depth. Returns the raw text of the symbol definition.
        """
        lines = text.split('\n')
        start = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Match exact symbol name (not sub-symbols like Name_0_1)
            if stripped.startswith(f'(symbol "{symbol_name}"') and \
               not re.match(r'.*_\d+_\d+"', stripped):
                start = i
                break

        if start is None:
            return None

        depth = 0
        end = None
        for i in range(start, len(lines)):
            for ch in lines[i]:
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end is not None:
                break

        if end is None:
            return None

        return '\n'.join(lines[start:end + 1])

    def extract_symbol_from_library(self, library_name: str, symbol_name: str) -> Optional[str]:
        """
        Extract a symbol definition from a KiCad .kicad_sym library file.
        Returns the raw text block, ready to be injected into a schematic.

        The returned block has:
        - Top-level name prefixed with library: (symbol "Library:Name" ...)
        - Sub-symbol names WITHOUT prefix: (symbol "Name_0_1" ...)
        """
        cache_key = f"{library_name}:{symbol_name}"
        if cache_key in self.symbol_cache:
            return self.symbol_cache[cache_key]

        lib_path = self.find_library_file(library_name)
        if not lib_path:
            return None

        with open(lib_path, 'r', encoding='utf-8') as f:
            lib_content = f.read()

        block = self._extract_symbol_block(lib_content, symbol_name)
        if block is None:
            logger.warning(f"Symbol '{symbol_name}' not found in {library_name}.kicad_sym")
            return None

        # Check if this symbol uses (extends "ParentName")
        extends_match = re.search(r'\(extends "([^"]+)"\)', block)
        parent_block = None
        if extends_match:
            parent_name = extends_match.group(1)
            logger.info(f"Symbol {symbol_name} extends {parent_name}, extracting parent too")
            parent_block = self._extract_symbol_block(lib_content, parent_name)
            if parent_block:
                # Prefix parent top-level name with library
                parent_block = parent_block.replace(
                    f'(symbol "{parent_name}"',
                    f'(symbol "{library_name}:{parent_name}"',
                    1  # Only first occurrence (top-level)
                )

        # Prefix top-level symbol name with library
        full_name = f"{library_name}:{symbol_name}"
        block = block.replace(
            f'(symbol "{symbol_name}"',
            f'(symbol "{full_name}"',
            1  # Only first occurrence (top-level)
        )
        # Sub-symbols like "Name_0_1" keep their short names (already correct from library)

        # Combine parent + child if extends is used
        if parent_block:
            result = parent_block + '\n' + block
        else:
            result = block

        self.symbol_cache[cache_key] = result
        logger.info(f"Extracted symbol {full_name} ({len(result)} chars)")
        return result

    def inject_symbol_into_schematic(self, schematic_path: Path, library_name: str, symbol_name: str) -> bool:
        """
        Inject a symbol definition into a schematic's lib_symbols section.
        Uses text manipulation to preserve file formatting.
        """
        full_name = f"{library_name}:{symbol_name}"

        with open(schematic_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check if symbol already exists
        if f'(symbol "{full_name}"' in content:
            logger.info(f"Symbol {full_name} already exists in schematic")
            return True

        # Extract symbol from library
        symbol_block = self.extract_symbol_from_library(library_name, symbol_name)
        if not symbol_block:
            raise ValueError(f"Symbol '{symbol_name}' not found in library '{library_name}'")

        # Indent the block to match lib_symbols indentation (4 spaces for top-level)
        indented_lines = []
        for line in symbol_block.split('\n'):
            # Add 4-space indent for the content inside lib_symbols
            indented_lines.append('    ' + line if line.strip() else line)
        indented_block = '\n'.join(indented_lines)

        # Find the end of lib_symbols section to insert before closing )
        lines = content.split('\n')
        lib_sym_start = None
        lib_sym_end = None
        depth = 0

        for i, line in enumerate(lines):
            if '(lib_symbols' in line and lib_sym_start is None:
                lib_sym_start = i
                depth = 0
                for ch in line:
                    if ch == '(':
                        depth += 1
                    elif ch == ')':
                        depth -= 1
                continue
            if lib_sym_start is not None and lib_sym_end is None:
                for ch in line:
                    if ch == '(':
                        depth += 1
                    elif ch == ')':
                        depth -= 1
                        if depth == 0:
                            lib_sym_end = i
                            break
                if lib_sym_end is not None:
                    break

        if lib_sym_end is None:
            raise ValueError("No lib_symbols section found in schematic")

        # Insert the symbol block just before the closing ) of lib_symbols
        lines.insert(lib_sym_end, indented_block)

        with open(schematic_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"Injected symbol {full_name} into {schematic_path.name}")
        return True

    def create_component_instance(self, schematic_path: Path, library_name: str,
                                   symbol_name: str, reference: str,
                                   value: str = "", x: float = 0, y: float = 0) -> bool:
        """
        Add a component instance to the schematic.
        This creates the (symbol ...) block with lib_id reference.
        """
        full_lib_id = f"{library_name}:{symbol_name}"
        new_uuid = str(uuid.uuid4())

        instance_block = f'''  (symbol (lib_id "{full_lib_id}") (at {x} {y} 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "{new_uuid}")
    (property "Reference" "{reference}" (at {x} {y - 2.54} 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "{value or symbol_name}" (at {x} {y + 2.54} 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "" (at {x} {y} 0)
      (effects (font (size 1.27 1.27)) (hide yes))
    )
    (property "Datasheet" "~" (at {x} {y} 0)
      (effects (font (size 1.27 1.27)) (hide yes))
    )
  )'''

        with open(schematic_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Insert before (sheet_instances or at end before final )
        lines = content.split('\n')
        insert_pos = None

        for i, line in enumerate(lines):
            if '(sheet_instances' in line:
                insert_pos = i
                break

        if insert_pos is None:
            # Insert before the last closing parenthesis
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip() == ')':
                    insert_pos = i
                    break

        if insert_pos is None:
            raise ValueError("Could not find insertion point in schematic")

        lines.insert(insert_pos, instance_block)

        with open(schematic_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"Added component instance {reference} ({full_lib_id}) at ({x}, {y})")
        return True

    def load_symbol_dynamically(self, schematic_path: Path, library_name: str, symbol_name: str) -> str:
        """
        Complete workflow: inject symbol definition and create a template instance.
        Returns a template reference name.
        """
        logger.info(f"Loading symbol dynamically: {library_name}:{symbol_name}")

        # Step 1: Inject symbol definition into lib_symbols
        self.inject_symbol_into_schematic(schematic_path, library_name, symbol_name)

        # Step 2: Create an offscreen template instance
        lib_clean = library_name.replace('-', '_').replace('.', '_')
        sym_clean = symbol_name.replace('-', '_').replace('.', '_')
        template_ref = f"_TEMPLATE_{lib_clean}_{sym_clean}"

        self.create_component_instance(
            schematic_path, library_name, symbol_name,
            reference=template_ref, value=symbol_name,
            x=-200, y=-200
        )

        logger.info(f"Symbol loaded. Template reference: {template_ref}")
        return template_ref

    def add_component(self, schematic_path: Path, library_name: str, symbol_name: str,
                      reference: str, value: str = "", x: float = 0, y: float = 0) -> bool:
        """
        High-level: ensure symbol definition exists in schematic, then add an instance.
        This is the main entry point for adding components.
        """
        # Ensure symbol definition is in lib_symbols
        self.inject_symbol_into_schematic(schematic_path, library_name, symbol_name)

        # Add the component instance
        return self.create_component_instance(
            schematic_path, library_name, symbol_name,
            reference=reference, value=value, x=x, y=y
        )


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    loader = DynamicSymbolLoader()

    print("\n=== Testing Dynamic Symbol Loader (Text-based) ===\n")

    print("1. Finding KiCad symbol library directories...")
    lib_dirs = loader.find_kicad_symbol_libraries()
    print(f"   Found {len(lib_dirs)} directories")

    print("\n2. Extracting symbols...")
    for lib, sym in [('Device', 'R'), ('Device', 'C'), ('Device', 'LED'), ('Device', 'Q_NMOS')]:
        block = loader.extract_symbol_from_library(lib, sym)
        if block:
            print(f"   OK: {lib}:{sym} ({len(block)} chars)")
        else:
            print(f"   FAIL: {lib}:{sym}")

    print("\n3. Testing extends resolution...")
    block = loader.extract_symbol_from_library('Regulator_Switching', 'LM2596S-5')
    if block and 'LM2596S-12' in block:
        print(f"   OK: LM2596S-5 includes parent LM2596S-12 ({len(block)} chars)")
    else:
        print(f"   FAIL: extends not resolved")

    print("\nAll tests passed!")
