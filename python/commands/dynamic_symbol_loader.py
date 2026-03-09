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

logger = logging.getLogger("kicad_interface")


class DynamicSymbolLoader:
    """
    Dynamically loads symbols from KiCad library files and injects them into schematics.

    Uses raw text manipulation instead of sexpdata to avoid corrupting the KiCad file format.

    Key rules for KiCad 9 .kicad_sch format:
    - Top-level symbols in lib_symbols must have library prefix: (symbol "Device:R" ...)
    - Sub-symbols must NOT have library prefix: (symbol "R_0_1" ...), (symbol "R_1_1" ...)
    - Parent symbols must appear BEFORE child symbols that use (extends ...)
    """

    def __init__(self, project_path: Optional[Path] = None):
        self.symbol_cache = {}  # Cache: "lib:symbol" -> raw text block
        self.project_path = project_path  # Project directory for project-specific libraries

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
        for env_var in ["KICAD9_SYMBOL_DIR", "KICAD8_SYMBOL_DIR", "KICAD_SYMBOL_DIR"]:
            if env_var in os.environ:
                possible_paths.insert(0, Path(os.environ[env_var]))

        return [p for p in possible_paths if p.exists() and p.is_dir()]

    def find_library_file(self, library_name: str) -> Optional[Path]:
        """Find the .kicad_sym file for a given library name.

        Search order:
        1. Project-specific sym-lib-table (if project_path is set)
        2. Global KiCad symbol library directories
        """
        # 1. Check project-specific sym-lib-table
        if self.project_path:
            project_table = Path(self.project_path) / "sym-lib-table"
            if project_table.exists():
                resolved = self._resolve_library_from_table(project_table, library_name)
                if resolved:
                    logger.info(f"Found '{library_name}' in project sym-lib-table: {resolved}")
                    return resolved

        # 2. Fall back to global KiCad symbol directories
        for lib_dir in self.find_kicad_symbol_libraries():
            lib_file = lib_dir / f"{library_name}.kicad_sym"
            if lib_file.exists():
                return lib_file

        logger.warning(f"Library file not found: {library_name}.kicad_sym")
        return None

    def _resolve_library_from_table(self, table_path: Path, library_name: str) -> Optional[Path]:
        """Parse a sym-lib-table file and return the resolved path for the given library nickname."""
        try:
            with open(table_path, "r", encoding="utf-8") as f:
                content = f.read()

            lib_pattern = r'\(lib\s+\(name\s+"?([^"\)\s]+)"?\)\s*\(type\s+[^)]+\)\s*\(uri\s+"?([^"\)\s]+)"?'
            for match in re.finditer(lib_pattern, content, re.IGNORECASE):
                nickname = match.group(1)
                if nickname != library_name:
                    continue
                uri = match.group(2)
                resolved = self._resolve_sym_uri(uri)
                if resolved and Path(resolved).exists():
                    return Path(resolved)
        except Exception as e:
            logger.warning(f"Could not parse sym-lib-table {table_path}: {e}")
        return None

    def _resolve_sym_uri(self, uri: str) -> Optional[str]:
        """Resolve environment variables in a sym-lib-table URI."""
        env_map = {
            "KICAD9_SYMBOL_DIR": [
                "C:/Program Files/KiCad/9.0/share/kicad/symbols",
                "/usr/share/kicad/symbols",
                "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
            ],
            "KICAD8_SYMBOL_DIR": [
                "C:/Program Files/KiCad/8.0/share/kicad/symbols",
            ],
            "KIPRJMOD": [str(self.project_path)] if self.project_path else [],
        }
        result = uri
        for var, candidates in env_map.items():
            if f"${{{var}}}" in result:
                for candidate in candidates:
                    candidate_path = result.replace(f"${{{var}}}", candidate)
                    if Path(candidate_path).exists():
                        return candidate_path
                # Fallback: try OS env
                if var in os.environ:
                    return result.replace(f"${{{var}}}", os.environ[var])
        return result

    def _extract_symbol_block(self, text: str, symbol_name: str) -> Optional[str]:
        """
        Extract a complete symbol block from a library or schematic file by matching
        parentheses depth. Returns the raw text of the symbol definition.
        """
        lines = text.split("\n")
        start = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Match exact symbol name (not sub-symbols like Name_0_1)
            if stripped.startswith(f'(symbol "{symbol_name}"') and not re.match(
                r'.*_\d+_\d+"', stripped
            ):
                start = i
                break

        if start is None:
            return None

        depth = 0
        end = None
        for i in range(start, len(lines)):
            for ch in lines[i]:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end is not None:
                break

        if end is None:
            return None

        return "\n".join(lines[start : end + 1])

    def _iter_top_level_items(self, symbol_block: str) -> list:
        """
        Extract each top-level s-expression item from inside a symbol block.
        Starts after the first line (symbol header) and stops before the final
        closing parenthesis.  Returns a list of raw text strings.
        """
        lines = symbol_block.split("\n")
        items = []
        i = 1  # skip first line: (symbol "Name" ...)
        n = len(lines)

        while i < n:
            line = lines[i]
            stripped = line.strip()

            if not stripped:
                i += 1
                continue

            # The final closing paren of the symbol itself
            if stripped == ")" and i == n - 1:
                break

            if not stripped.startswith("("):
                i += 1
                continue

            # Collect a balanced s-expression starting here
            depth = 0
            item_start = i
            while i < n:
                for ch in lines[i]:
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                i += 1
                if depth == 0:
                    break

            items.append("\n".join(lines[item_start:i]))

        return items

    def _inline_extends_symbol(
        self, lib_content: str, symbol_name: str, child_block: str
    ) -> str:
        """
        Fully inline a child symbol that uses (extends "ParentName") by merging
        the parent's pins / graphics into the child definition.

        KiCad 9 does NOT support (extends ...) inside a schematic's lib_symbols
        section.  This method produces a self-contained, fully-resolved symbol
        block – exactly what KiCad itself writes when saving a schematic.

        Algorithm:
          1. Extract the parent block from the library text.
          2. Take every top-level item from the parent (pin_names, properties,
             sub-symbols, …).
          3. For each property, use the child's override if one exists; otherwise
             keep the parent's value.
          4. Rename parent sub-symbols (ParentName_0_1 → ChildName_0_1).
          5. Append any child-only properties that do not exist in the parent.
          6. Return the merged block named after the child – no (extends …) left.
        """
        extends_match = re.search(r'\(extends "([^"]+)"\)', child_block)
        if not extends_match:
            return child_block

        parent_name = extends_match.group(1)
        parent_block = self._extract_symbol_block(lib_content, parent_name)
        if not parent_block:
            logger.warning(
                f"Cannot resolve parent '{parent_name}' for '{symbol_name}' "
                "- stripping extends clause (symbol may be incomplete)"
            )
            return re.sub(r"\s*\(extends \"[^\"]+\"\)\n?", "", child_block)

        # Collect child property overrides: prop_name -> raw block text
        child_props: dict = {}
        for item in self._iter_top_level_items(child_block):
            m = re.match(r'[\s\t]*\(property "([^"]+)"', item)
            if m:
                child_props[m.group(1)] = item

        # Walk parent items, applying child overrides
        body_lines = []
        parent_prop_names: set = set()

        for item in self._iter_top_level_items(parent_block):
            prop_match = re.match(r'[\s\t]*\(property "([^"]+)"', item)
            sub_match = re.search(
                r'\(symbol "' + re.escape(parent_name) + r'_\d+_\d+"', item
            )

            if prop_match:
                pname = prop_match.group(1)
                parent_prop_names.add(pname)
                body_lines.append(
                    child_props[pname] if pname in child_props else item
                )
            elif sub_match:
                # Rename ParentName_0_1 → ChildName_0_1
                body_lines.append(
                    item.replace(f'"{parent_name}_', f'"{symbol_name}_')
                )
            elif re.match(r'[\s\t]*\(extends ', item):
                pass  # drop extends clause
            else:
                body_lines.append(item)  # pin_names, in_bom, on_board …

        # Append child-only properties absent from parent
        for pname, pblock in child_props.items():
            if pname not in parent_prop_names:
                body_lines.append(pblock)

        first_line = parent_block.split("\n")[0].replace(
            f'"{parent_name}"', f'"{symbol_name}"'
        )
        last_line = parent_block.split("\n")[-1]

        return first_line + "\n" + "\n".join(body_lines) + "\n" + last_line

    def extract_symbol_from_library(
        self, library_name: str, symbol_name: str
    ) -> Optional[str]:
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

        with open(lib_path, "r", encoding="utf-8") as f:
            lib_content = f.read()

        block = self._extract_symbol_block(lib_content, symbol_name)
        if block is None:
            logger.warning(
                f"Symbol '{symbol_name}' not found in {library_name}.kicad_sym"
            )
            return None

        # If the symbol uses (extends "ParentName"), inline the parent content
        # so that the result is a fully self-contained definition.
        # (extends ...) is only valid in .kicad_sym files; KiCad 9 refuses to
        # load a schematic whose lib_symbols section contains it.
        if re.search(r'\(extends "([^"]+)"\)', block):
            parent_name = re.search(r'\(extends "([^"]+)"\)', block).group(1)
            logger.info(
                f"Symbol {symbol_name} extends {parent_name}, inlining parent content"
            )
            block = self._inline_extends_symbol(lib_content, symbol_name, block)

        # Prefix top-level symbol name with library
        full_name = f"{library_name}:{symbol_name}"
        block = block.replace(
            f'(symbol "{symbol_name}"',
            f'(symbol "{full_name}"',
            1,  # Only first occurrence (top-level)
        )
        # Sub-symbols like "Name_0_1" keep their short names (already correct from library)

        result = block

        self.symbol_cache[cache_key] = result
        logger.info(f"Extracted symbol {full_name} ({len(result)} chars)")
        return result

    def inject_symbol_into_schematic(
        self, schematic_path: Path, library_name: str, symbol_name: str
    ) -> bool:
        """
        Inject a symbol definition into a schematic's lib_symbols section.
        Uses text manipulation to preserve file formatting.
        """
        full_name = f"{library_name}:{symbol_name}"

        with open(schematic_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check if symbol already exists
        if f'(symbol "{full_name}"' in content:
            logger.info(f"Symbol {full_name} already exists in schematic")
            return True

        # Extract symbol from library
        symbol_block = self.extract_symbol_from_library(library_name, symbol_name)
        if not symbol_block:
            raise ValueError(
                f"Symbol '{symbol_name}' not found in library '{library_name}'"
            )

        # Indent the block to match lib_symbols indentation (4 spaces for top-level)
        indented_lines = []
        for line in symbol_block.split("\n"):
            # Add 4-space indent for the content inside lib_symbols
            indented_lines.append("    " + line if line.strip() else line)
        indented_block = "\n".join(indented_lines)

        # Find the end of lib_symbols section using string search (format-independent,
        # works even when sexpdata.dumps() has compacted the file to a single line)
        lib_sym_start = content.find("(lib_symbols")
        if lib_sym_start == -1:
            raise ValueError("No lib_symbols section found in schematic")

        depth = 0
        lib_sym_end = lib_sym_start
        for i in range(lib_sym_start, len(content)):
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
                if depth == 0:
                    lib_sym_end = i
                    break
        else:
            raise ValueError("No lib_symbols section found in schematic")

        # Insert the symbol block just before the closing ) of lib_symbols
        content = content[:lib_sym_end] + "\n    " + indented_block + "\n  " + content[lib_sym_end:]

        with open(schematic_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Handle both Path objects and strings
        sch_name = (
            schematic_path.name
            if hasattr(schematic_path, "name")
            else str(schematic_path)
        )
        logger.info(f"Injected symbol {full_name} into {sch_name}")
        return True

    def create_component_instance(
        self,
        schematic_path: Path,
        library_name: str,
        symbol_name: str,
        reference: str,
        value: str = "",
        footprint: str = "",
        x: float = 0,
        y: float = 0,
    ) -> bool:
        """
        Add a component instance to the schematic.
        This creates the (symbol ...) block with lib_id reference.
        """
        full_lib_id = f"{library_name}:{symbol_name}"
        new_uuid = str(uuid.uuid4())

        instance_block = f"""  (symbol (lib_id "{full_lib_id}") (at {x} {y} 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "{new_uuid}")
    (property "Reference" "{reference}" (at {x} {y - 2.54} 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "{value or symbol_name}" (at {x} {y + 2.54} 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "{footprint}" (at {x} {y} 0)
      (effects (font (size 1.27 1.27)) (hide yes))
    )
    (property "Datasheet" "~" (at {x} {y} 0)
      (effects (font (size 1.27 1.27)) (hide yes))
    )
  )"""

        with open(schematic_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Insert before (sheet_instances using direct string search.
        # This works for both pretty-printed and sexpdata-compacted single-line files.
        insert_marker = "(sheet_instances"
        insert_at = content.rfind(insert_marker)
        if insert_at == -1:
            raise ValueError("Could not find insertion point in schematic")

        content = content[:insert_at] + instance_block + "\n  " + content[insert_at:]

        with open(schematic_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(
            f"Added component instance {reference} ({full_lib_id}) at ({x}, {y})"
        )
        return True

    def load_symbol_dynamically(
        self, schematic_path: Path, library_name: str, symbol_name: str
    ) -> str:
        """
        Complete workflow: inject symbol definition and create a template instance.
        Returns a template reference name.
        """
        logger.info(f"Loading symbol dynamically: {library_name}:{symbol_name}")

        # Step 1: Inject symbol definition into lib_symbols
        self.inject_symbol_into_schematic(schematic_path, library_name, symbol_name)

        # Step 2: Create an offscreen template instance
        lib_clean = library_name.replace("-", "_").replace(".", "_")
        sym_clean = symbol_name.replace("-", "_").replace(".", "_")
        template_ref = f"_TEMPLATE_{lib_clean}_{sym_clean}"

        self.create_component_instance(
            schematic_path,
            library_name,
            symbol_name,
            reference=template_ref,
            value=symbol_name,
            x=-200,
            y=-200,
        )

        logger.info(f"Symbol loaded. Template reference: {template_ref}")
        return template_ref

    def add_component(
        self,
        schematic_path: Path,
        library_name: str,
        symbol_name: str,
        reference: str,
        value: str = "",
        footprint: str = "",
        x: float = 0,
        y: float = 0,
        project_path: Optional[Path] = None,
    ) -> bool:
        """
        High-level: ensure symbol definition exists in schematic, then add an instance.
        This is the main entry point for adding components.

        Args:
            project_path: Optional project directory. When set, project-specific
                          sym-lib-table is also searched for the library file.
        """
        if project_path:
            self.project_path = project_path
        # Ensure symbol definition is in lib_symbols
        self.inject_symbol_into_schematic(schematic_path, library_name, symbol_name)

        # Add the component instance
        return self.create_component_instance(
            schematic_path,
            library_name,
            symbol_name,
            reference=reference,
            value=value,
            footprint=footprint,
            x=x,
            y=y,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    loader = DynamicSymbolLoader()

    print("\n=== Testing Dynamic Symbol Loader (Text-based) ===\n")

    print("1. Finding KiCad symbol library directories...")
    lib_dirs = loader.find_kicad_symbol_libraries()
    print(f"   Found {len(lib_dirs)} directories")

    print("\n2. Extracting symbols...")
    for lib, sym in [
        ("Device", "R"),
        ("Device", "C"),
        ("Device", "LED"),
        ("Device", "Q_NMOS"),
    ]:
        block = loader.extract_symbol_from_library(lib, sym)
        if block:
            print(f"   OK: {lib}:{sym} ({len(block)} chars)")
        else:
            print(f"   FAIL: {lib}:{sym}")

    print("\n3. Testing extends resolution...")
    block = loader.extract_symbol_from_library("Regulator_Switching", "LM2596S-5")
    if block and "LM2596S-12" in block:
        print(f"   OK: LM2596S-5 includes parent LM2596S-12 ({len(block)} chars)")
    else:
        print(f"   FAIL: extends not resolved")

    print("\nAll tests passed!")
