"""
Library management for KiCAD symbols

Handles parsing sym-lib-table files, discovering symbols,
and providing search functionality for component selection.
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger('kicad_interface')


@dataclass
class SymbolInfo:
    """Information about a symbol in a library"""
    name: str               # Symbol name (without library prefix)
    library: str            # Library nickname
    full_ref: str           # "Library:SymbolName"
    value: str = ""         # Value property
    description: str = ""   # Description property
    footprint: str = ""     # Footprint reference if present
    lcsc_id: str = ""       # LCSC property if present
    manufacturer: str = ""  # Manufacturer property
    mpn: str = ""           # Part/MPN property
    category: str = ""      # Category property
    datasheet: str = ""     # Datasheet URL
    stock: str = ""         # Stock (from JLCPCB libs)
    price: str = ""         # Price (from JLCPCB libs)
    lib_class: str = ""     # Basic/Preferred/Extended


class SymbolLibraryManager:
    """
    Manages KiCAD symbol libraries

    Parses sym-lib-table files (both global and project-specific),
    indexes available symbols, and provides search functionality.
    """

    def __init__(self, project_path: Optional[Path] = None):
        """
        Initialize symbol library manager

        Args:
            project_path: Optional path to project directory for project-specific libraries
        """
        self.project_path = project_path
        self.libraries: Dict[str, str] = {}  # nickname -> path mapping
        self.symbol_cache: Dict[str, List[SymbolInfo]] = {}  # library -> [SymbolInfo]
        self._load_libraries()

    def _load_libraries(self):
        """Load libraries from sym-lib-table files"""
        # Load global libraries
        global_table = self._get_global_sym_lib_table()
        if global_table and global_table.exists():
            logger.info(f"Loading global sym-lib-table from: {global_table}")
            self._parse_sym_lib_table(global_table)
        else:
            logger.warning(f"Global sym-lib-table not found at: {global_table}")

        # Load project-specific libraries if project path provided
        if self.project_path:
            project_table = self.project_path / "sym-lib-table"
            if project_table.exists():
                logger.info(f"Loading project sym-lib-table from: {project_table}")
                self._parse_sym_lib_table(project_table)

        logger.info(f"Loaded {len(self.libraries)} symbol libraries")

    def _get_global_sym_lib_table(self) -> Optional[Path]:
        """Get path to global sym-lib-table file"""
        # Try different possible locations (same as fp-lib-table but for symbols)
        kicad_config_paths = [
            Path.home() / ".config" / "kicad" / "9.0" / "sym-lib-table",
            Path.home() / ".config" / "kicad" / "8.0" / "sym-lib-table",
            Path.home() / ".config" / "kicad" / "sym-lib-table",
            # Windows paths
            Path.home() / "AppData" / "Roaming" / "kicad" / "9.0" / "sym-lib-table",
            Path.home() / "AppData" / "Roaming" / "kicad" / "8.0" / "sym-lib-table",
            # macOS paths
            Path.home() / "Library" / "Preferences" / "kicad" / "9.0" / "sym-lib-table",
            Path.home() / "Library" / "Preferences" / "kicad" / "8.0" / "sym-lib-table",
        ]

        for path in kicad_config_paths:
            if path.exists():
                return path

        return None

    def _parse_sym_lib_table(self, table_path: Path):
        """
        Parse sym-lib-table file

        Format is S-expression (Lisp-like):
        (sym_lib_table
          (lib (name "Library_Name")(type KiCad)(uri "${KICAD9_SYMBOL_DIR}/Library.kicad_sym")(options "")(descr "Description"))
        )
        """
        try:
            with open(table_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Simple regex-based parser for lib entries
            # Pattern: (lib (name "NAME")(type TYPE)(uri "URI")...)
            lib_pattern = r'\(lib\s+\(name\s+"?([^")\s]+)"?\)\s*\(type\s+[^)]+\)\s*\(uri\s+"?([^")\s]+)"?'

            for match in re.finditer(lib_pattern, content, re.IGNORECASE):
                nickname = match.group(1)
                uri = match.group(2)

                # Resolve environment variables in URI
                resolved_uri = self._resolve_uri(uri)

                if resolved_uri:
                    self.libraries[nickname] = resolved_uri
                    logger.debug(f"  Found library: {nickname} -> {resolved_uri}")
                else:
                    logger.debug(f"  Could not resolve URI for library {nickname}: {uri}")

        except Exception as e:
            logger.error(f"Error parsing sym-lib-table at {table_path}: {e}")

    def _resolve_uri(self, uri: str) -> Optional[str]:
        """
        Resolve environment variables and paths in library URI

        Handles:
        - ${KICAD9_SYMBOL_DIR} -> /Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols
        - ${KICAD9_3RD_PARTY} -> ~/Documents/KiCad/9.0/3rdparty
        - ${KIPRJMOD} -> project directory
        - Relative paths
        - Absolute paths
        """
        resolved = uri

        # Common KiCAD environment variables
        env_vars = {
            'KICAD9_SYMBOL_DIR': self._find_kicad_symbol_dir(),
            'KICAD8_SYMBOL_DIR': self._find_kicad_symbol_dir(),
            'KICAD_SYMBOL_DIR': self._find_kicad_symbol_dir(),
            'KICAD9_3RD_PARTY': self._find_3rd_party_dir(),
            'KICAD8_3RD_PARTY': self._find_3rd_party_dir(),
            'KISYSSYM': self._find_kicad_symbol_dir(),
        }

        # Project directory
        if self.project_path:
            env_vars['KIPRJMOD'] = str(self.project_path)

        # Replace environment variables
        for var, value in env_vars.items():
            if value:
                resolved = resolved.replace(f'${{{var}}}', value)
                resolved = resolved.replace(f'${var}', value)

        # Expand ~ to home directory
        resolved = os.path.expanduser(resolved)

        # Convert to absolute path
        path = Path(resolved)

        # Check if path exists
        if path.exists():
            return str(path)
        else:
            logger.debug(f"    Path does not exist: {path}")
            return None

    def _find_kicad_symbol_dir(self) -> Optional[str]:
        """Find KiCAD symbol directory"""
        possible_paths = [
            "/usr/share/kicad/symbols",
            "/usr/local/share/kicad/symbols",
            "C:/Program Files/KiCad/9.0/share/kicad/symbols",
            "C:/Program Files/KiCad/8.0/share/kicad/symbols",
            "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
        ]

        # Check environment variable
        if 'KICAD9_SYMBOL_DIR' in os.environ:
            possible_paths.insert(0, os.environ['KICAD9_SYMBOL_DIR'])
        if 'KICAD8_SYMBOL_DIR' in os.environ:
            possible_paths.insert(0, os.environ['KICAD8_SYMBOL_DIR'])

        for path in possible_paths:
            if os.path.isdir(path):
                return path

        return None

    def _find_3rd_party_dir(self) -> Optional[str]:
        """Find KiCAD 3rd party library directory (PCM installed libs)"""
        possible_paths = [
            str(Path.home() / "Documents" / "KiCad" / "9.0" / "3rdparty"),
            str(Path.home() / "Documents" / "KiCad" / "8.0" / "3rdparty"),
        ]

        # Check environment variable
        if 'KICAD9_3RD_PARTY' in os.environ:
            possible_paths.insert(0, os.environ['KICAD9_3RD_PARTY'])
        if 'KICAD8_3RD_PARTY' in os.environ:
            possible_paths.insert(0, os.environ['KICAD8_3RD_PARTY'])

        for path in possible_paths:
            if os.path.isdir(path):
                return path

        return None

    def _parse_kicad_sym_file(self, library_path: str, library_name: str) -> List[SymbolInfo]:
        """
        Parse a .kicad_sym file to extract symbol metadata

        Args:
            library_path: Path to the .kicad_sym file
            library_name: Nickname of the library

        Returns:
            List of SymbolInfo objects
        """
        symbols = []

        try:
            with open(library_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Find all top-level symbol definitions
            # Pattern: (symbol "SYMBOL_NAME" ... ) at the top level
            # We need to find symbols that are direct children of kicad_symbol_lib
            # and not sub-symbols (which have names like "PARENT_0_1")

            # Simple approach: find all (symbol "NAME" and filter out sub-symbols
            symbol_pattern = r'\(symbol\s+"([^"]+)"'

            for match in re.finditer(symbol_pattern, content):
                symbol_name = match.group(1)

                # Skip sub-symbols (they contain _0_, _1_, etc. suffixes)
                if re.search(r'_\d+_\d+$', symbol_name):
                    continue

                # Find the start position of this symbol
                start_pos = match.start()

                # Extract properties from this symbol block
                # We need to find the matching closing paren - use a simple heuristic
                # Look for the next 2000 characters for properties
                block_end = min(start_pos + 5000, len(content))
                symbol_block = content[start_pos:block_end]

                # Extract properties
                properties = self._extract_properties(symbol_block)

                symbol_info = SymbolInfo(
                    name=symbol_name,
                    library=library_name,
                    full_ref=f"{library_name}:{symbol_name}",
                    value=properties.get('Value', ''),
                    description=properties.get('Description', ''),
                    footprint=properties.get('Footprint', ''),
                    lcsc_id=properties.get('LCSC', ''),
                    manufacturer=properties.get('Manufacturer', ''),
                    mpn=properties.get('Part', properties.get('MPN', '')),
                    category=properties.get('Category', ''),
                    datasheet=properties.get('Datasheet', ''),
                    stock=properties.get('Stock', ''),
                    price=properties.get('Price', ''),
                    lib_class=properties.get('Class', ''),
                )

                symbols.append(symbol_info)

            logger.debug(f"Parsed {len(symbols)} symbols from {library_name}")

        except Exception as e:
            logger.error(f"Error parsing symbol library {library_path}: {e}")

        return symbols

    def _extract_properties(self, symbol_block: str) -> Dict[str, str]:
        """Extract properties from a symbol block"""
        properties = {}

        # Pattern for properties: (property "KEY" "VALUE" ...)
        prop_pattern = r'\(property\s+"([^"]+)"\s+"([^"]*)"'

        for match in re.finditer(prop_pattern, symbol_block):
            key = match.group(1)
            value = match.group(2)
            properties[key] = value

        return properties

    def list_libraries(self) -> List[str]:
        """Get list of available library nicknames"""
        return list(self.libraries.keys())

    def get_library_path(self, nickname: str) -> Optional[str]:
        """Get filesystem path for a library nickname"""
        return self.libraries.get(nickname)

    def list_symbols(self, library_nickname: str) -> List[SymbolInfo]:
        """
        List all symbols in a library

        Args:
            library_nickname: Library name (e.g., "Device")

        Returns:
            List of SymbolInfo objects
        """
        # Check cache first
        if library_nickname in self.symbol_cache:
            return self.symbol_cache[library_nickname]

        library_path = self.libraries.get(library_nickname)
        if not library_path:
            logger.warning(f"Library not found: {library_nickname}")
            return []

        # Parse the library file
        symbols = self._parse_kicad_sym_file(library_path, library_nickname)

        # Cache the results
        self.symbol_cache[library_nickname] = symbols

        return symbols

    def search_symbols(self, query: str, limit: int = 20, library_filter: Optional[str] = None) -> List[SymbolInfo]:
        """
        Search for symbols matching a query

        Args:
            query: Search query (matches name, LCSC ID, description, category, manufacturer)
            limit: Maximum number of results to return
            library_filter: Optional library name pattern to filter by

        Returns:
            List of SymbolInfo objects sorted by relevance
        """
        results = []
        query_lower = query.lower()

        # Determine which libraries to search
        libraries_to_search = self.libraries.keys()
        if library_filter:
            filter_lower = library_filter.lower()
            libraries_to_search = [lib for lib in libraries_to_search if filter_lower in lib.lower()]

        for library_nickname in libraries_to_search:
            symbols = self.list_symbols(library_nickname)

            for symbol in symbols:
                score = self._score_match(query_lower, symbol)
                if score > 0:
                    results.append((score, symbol))

                    if len(results) >= limit * 3:  # Get extra for sorting
                        break

            if len(results) >= limit * 3:
                break

        # Sort by score (descending) and return top results
        results.sort(key=lambda x: x[0], reverse=True)
        return [symbol for _, symbol in results[:limit]]

    def _score_match(self, query: str, symbol: SymbolInfo) -> int:
        """
        Score how well a symbol matches a query

        Returns:
            Score (0 = no match, higher = better match)
        """
        score = 0

        # Exact LCSC ID match - highest priority
        if symbol.lcsc_id and symbol.lcsc_id.lower() == query:
            score += 1000

        # Exact name match
        if symbol.name.lower() == query:
            score += 500

        # Exact value match
        if symbol.value.lower() == query:
            score += 400

        # Partial name match
        if query in symbol.name.lower():
            score += 100

        # Partial value match
        if query in symbol.value.lower():
            score += 80

        # Description match
        if query in symbol.description.lower():
            score += 50

        # MPN match
        if symbol.mpn and query in symbol.mpn.lower():
            score += 70

        # Manufacturer match
        if symbol.manufacturer and query in symbol.manufacturer.lower():
            score += 30

        # Category match
        if symbol.category and query in symbol.category.lower():
            score += 20

        return score

    def get_symbol_info(self, library_nickname: str, symbol_name: str) -> Optional[SymbolInfo]:
        """
        Get information about a specific symbol

        Args:
            library_nickname: Library name
            symbol_name: Symbol name

        Returns:
            SymbolInfo or None if not found
        """
        symbols = self.list_symbols(library_nickname)

        for symbol in symbols:
            if symbol.name == symbol_name:
                return symbol

        return None

    def find_symbol(self, symbol_spec: str) -> Optional[SymbolInfo]:
        """
        Find a symbol by specification

        Supports multiple formats:
        - "Library:Symbol" (e.g., "Device:R")
        - "Symbol" (searches all libraries)

        Args:
            symbol_spec: Symbol specification

        Returns:
            SymbolInfo or None if not found
        """
        if ":" in symbol_spec:
            # Format: Library:Symbol
            library_nickname, symbol_name = symbol_spec.split(":", 1)
            return self.get_symbol_info(library_nickname, symbol_name)
        else:
            # Search all libraries
            for library_nickname in self.libraries.keys():
                result = self.get_symbol_info(library_nickname, symbol_spec)
                if result:
                    return result

            return None


class SymbolLibraryCommands:
    """Command handlers for symbol library operations"""

    def __init__(self, library_manager: Optional[SymbolLibraryManager] = None):
        """Initialize with optional library manager"""
        self.library_manager = library_manager or SymbolLibraryManager()

    def list_symbol_libraries(self, params: Dict) -> Dict:
        """List all available symbol libraries"""
        try:
            libraries = self.library_manager.list_libraries()
            return {
                "success": True,
                "libraries": libraries,
                "count": len(libraries)
            }
        except Exception as e:
            logger.error(f"Error listing symbol libraries: {e}")
            return {
                "success": False,
                "message": "Failed to list symbol libraries",
                "errorDetails": str(e)
            }

    def search_symbols(self, params: Dict) -> Dict:
        """Search for symbols by query"""
        try:
            query = params.get("query", "")
            if not query:
                return {
                    "success": False,
                    "message": "Missing query parameter"
                }

            limit = params.get("limit", 20)
            library_filter = params.get("library")

            results = self.library_manager.search_symbols(query, limit, library_filter)

            return {
                "success": True,
                "symbols": [asdict(s) for s in results],
                "count": len(results),
                "query": query
            }
        except Exception as e:
            logger.error(f"Error searching symbols: {e}")
            return {
                "success": False,
                "message": "Failed to search symbols",
                "errorDetails": str(e)
            }

    def list_library_symbols(self, params: Dict) -> Dict:
        """List all symbols in a specific library"""
        try:
            library = params.get("library")
            if not library:
                return {
                    "success": False,
                    "message": "Missing library parameter"
                }

            symbols = self.library_manager.list_symbols(library)

            return {
                "success": True,
                "library": library,
                "symbols": [asdict(s) for s in symbols],
                "count": len(symbols)
            }
        except Exception as e:
            logger.error(f"Error listing library symbols: {e}")
            return {
                "success": False,
                "message": "Failed to list library symbols",
                "errorDetails": str(e)
            }

    def get_symbol_info(self, params: Dict) -> Dict:
        """Get information about a specific symbol"""
        try:
            symbol_spec = params.get("symbol")
            if not symbol_spec:
                return {
                    "success": False,
                    "message": "Missing symbol parameter"
                }

            result = self.library_manager.find_symbol(symbol_spec)

            if result:
                return {
                    "success": True,
                    "symbol_info": asdict(result)
                }
            else:
                return {
                    "success": False,
                    "message": f"Symbol not found: {symbol_spec}"
                }

        except Exception as e:
            logger.error(f"Error getting symbol info: {e}")
            return {
                "success": False,
                "message": "Failed to get symbol info",
                "errorDetails": str(e)
            }


if __name__ == '__main__':
    # Test the symbol library manager
    import json

    logging.basicConfig(level=logging.INFO)

    manager = SymbolLibraryManager()

    print(f"\nFound {len(manager.libraries)} symbol libraries:")
    for name in list(manager.libraries.keys())[:10]:
        print(f"  - {name}")
    if len(manager.libraries) > 10:
        print(f"  ... and {len(manager.libraries) - 10} more")

    # Test search
    if manager.libraries:
        print("\n\nSearching for 'ESP32':")
        results = manager.search_symbols("ESP32", limit=5)
        for symbol in results:
            print(f"  - {symbol.full_ref}: {symbol.description or symbol.value}")
            if symbol.lcsc_id:
                print(f"      LCSC: {symbol.lcsc_id}")
