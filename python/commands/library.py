"""
Library management for KiCAD footprints

Handles parsing fp-lib-table files, discovering footprints,
and providing search functionality for component placement.
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import glob

logger = logging.getLogger('kicad_interface')


class LibraryManager:
    """
    Manages KiCAD footprint libraries

    Parses fp-lib-table files (both global and project-specific),
    indexes available footprints, and provides search functionality.
    """

    def __init__(self, project_path: Optional[Path] = None):
        """
        Initialize library manager

        Args:
            project_path: Optional path to project directory for project-specific libraries
        """
        self.project_path = project_path
        self.libraries: Dict[str, str] = {}  # nickname -> path mapping
        self.footprint_cache: Dict[str, List[str]] = {}  # library -> [footprint names]
        self._load_libraries()

    def _load_libraries(self):
        """Load libraries from fp-lib-table files"""
        # Load global libraries
        global_table = self._get_global_fp_lib_table()
        if global_table and global_table.exists():
            logger.info(f"Loading global fp-lib-table from: {global_table}")
            self._parse_fp_lib_table(global_table)
        else:
            logger.warning(f"Global fp-lib-table not found at: {global_table}")

        # Load project-specific libraries if project path provided
        if self.project_path:
            project_table = self.project_path / "fp-lib-table"
            if project_table.exists():
                logger.info(f"Loading project fp-lib-table from: {project_table}")
                self._parse_fp_lib_table(project_table)

        logger.info(f"Loaded {len(self.libraries)} footprint libraries")

    def _get_global_fp_lib_table(self) -> Optional[Path]:
        """Get path to global fp-lib-table file"""
        # Try different possible locations
        kicad_config_paths = [
            Path.home() / ".config" / "kicad" / "9.0" / "fp-lib-table",
            Path.home() / ".config" / "kicad" / "8.0" / "fp-lib-table",
            Path.home() / ".config" / "kicad" / "fp-lib-table",
            # Windows paths
            Path.home() / "AppData" / "Roaming" / "kicad" / "9.0" / "fp-lib-table",
            Path.home() / "AppData" / "Roaming" / "kicad" / "8.0" / "fp-lib-table",
            # macOS paths
            Path.home() / "Library" / "Preferences" / "kicad" / "9.0" / "fp-lib-table",
            Path.home() / "Library" / "Preferences" / "kicad" / "8.0" / "fp-lib-table",
        ]

        for path in kicad_config_paths:
            if path.exists():
                return path

        return None

    def _parse_fp_lib_table(self, table_path: Path):
        """
        Parse fp-lib-table file

        Format is S-expression (Lisp-like):
        (fp_lib_table
          (lib (name "Library_Name")(type KiCad)(uri "${KICAD9_FOOTPRINT_DIR}/Library.pretty")(options "")(descr "Description"))
        )
        """
        try:
            with open(table_path, 'r') as f:
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
                    logger.warning(f"  Could not resolve URI for library {nickname}: {uri}")

        except Exception as e:
            logger.error(f"Error parsing fp-lib-table at {table_path}: {e}")

    def _resolve_uri(self, uri: str) -> Optional[str]:
        """
        Resolve environment variables and paths in library URI

        Handles:
        - ${KICAD9_FOOTPRINT_DIR} -> /usr/share/kicad/footprints
        - ${KICAD8_FOOTPRINT_DIR} -> /usr/share/kicad/footprints
        - ${KIPRJMOD} -> project directory
        - Relative paths
        - Absolute paths
        """
        # Replace environment variables
        resolved = uri

        # Common KiCAD environment variables
        env_vars = {
            'KICAD9_FOOTPRINT_DIR': self._find_kicad_footprint_dir(),
            'KICAD8_FOOTPRINT_DIR': self._find_kicad_footprint_dir(),
            'KICAD_FOOTPRINT_DIR': self._find_kicad_footprint_dir(),
            'KISYSMOD': self._find_kicad_footprint_dir(),
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

    def _find_kicad_footprint_dir(self) -> Optional[str]:
        """Find KiCAD footprint directory"""
        # Try common locations
        possible_paths = [
            "/usr/share/kicad/footprints",
            "/usr/local/share/kicad/footprints",
            "C:/Program Files/KiCad/9.0/share/kicad/footprints",
            "C:/Program Files/KiCad/8.0/share/kicad/footprints",
            "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints",
        ]

        # Also check environment variable
        if 'KICAD9_FOOTPRINT_DIR' in os.environ:
            possible_paths.insert(0, os.environ['KICAD9_FOOTPRINT_DIR'])
        if 'KICAD8_FOOTPRINT_DIR' in os.environ:
            possible_paths.insert(0, os.environ['KICAD8_FOOTPRINT_DIR'])

        for path in possible_paths:
            if os.path.isdir(path):
                return path

        return None

    def list_libraries(self) -> List[str]:
        """Get list of available library nicknames"""
        return list(self.libraries.keys())

    def get_library_path(self, nickname: str) -> Optional[str]:
        """Get filesystem path for a library nickname"""
        return self.libraries.get(nickname)

    def list_footprints(self, library_nickname: str) -> List[str]:
        """
        List all footprints in a library

        Args:
            library_nickname: Library name (e.g., "Resistor_SMD")

        Returns:
            List of footprint names (without .kicad_mod extension)
        """
        # Check cache first
        if library_nickname in self.footprint_cache:
            return self.footprint_cache[library_nickname]

        library_path = self.libraries.get(library_nickname)
        if not library_path:
            logger.warning(f"Library not found: {library_nickname}")
            return []

        try:
            footprints = []
            lib_dir = Path(library_path)

            # List all .kicad_mod files
            for fp_file in lib_dir.glob("*.kicad_mod"):
                # Remove .kicad_mod extension
                footprint_name = fp_file.stem
                footprints.append(footprint_name)

            # Cache the results
            self.footprint_cache[library_nickname] = footprints
            logger.debug(f"Found {len(footprints)} footprints in {library_nickname}")

            return footprints

        except Exception as e:
            logger.error(f"Error listing footprints in {library_nickname}: {e}")
            return []

    def find_footprint(self, footprint_spec: str) -> Optional[Tuple[str, str]]:
        """
        Find a footprint by specification

        Supports multiple formats:
        - "Library:Footprint" (e.g., "Resistor_SMD:R_0603_1608Metric")
        - "Footprint" (searches all libraries)

        Args:
            footprint_spec: Footprint specification

        Returns:
            Tuple of (library_path, footprint_name) or None if not found
        """
        # Parse specification
        if ":" in footprint_spec:
            # Format: Library:Footprint
            library_nickname, footprint_name = footprint_spec.split(":", 1)
            library_path = self.libraries.get(library_nickname)

            if not library_path:
                logger.warning(f"Library not found: {library_nickname}")
                return None

            # Check if footprint exists
            fp_file = Path(library_path) / f"{footprint_name}.kicad_mod"
            if fp_file.exists():
                return (library_path, footprint_name)
            else:
                logger.warning(f"Footprint not found: {footprint_spec}")
                return None
        else:
            # Format: Footprint (search all libraries)
            footprint_name = footprint_spec

            # Search in all libraries
            for library_nickname, library_path in self.libraries.items():
                fp_file = Path(library_path) / f"{footprint_name}.kicad_mod"
                if fp_file.exists():
                    logger.info(f"Found footprint {footprint_name} in library {library_nickname}")
                    return (library_path, footprint_name)

            logger.warning(f"Footprint not found in any library: {footprint_name}")
            return None

    def search_footprints(self, pattern: str, limit: int = 20) -> List[Dict[str, str]]:
        """
        Search for footprints matching a pattern

        Args:
            pattern: Search pattern (supports wildcards *, case-insensitive)
            limit: Maximum number of results to return

        Returns:
            List of dicts with 'library', 'footprint', and 'full_name' keys
        """
        results = []
        pattern_lower = pattern.lower()

        # Convert wildcards to regex
        regex_pattern = pattern_lower.replace("*", ".*")
        regex = re.compile(regex_pattern)

        for library_nickname in self.libraries.keys():
            footprints = self.list_footprints(library_nickname)

            for footprint in footprints:
                if regex.search(footprint.lower()):
                    results.append({
                        'library': library_nickname,
                        'footprint': footprint,
                        'full_name': f"{library_nickname}:{footprint}"
                    })

                    if len(results) >= limit:
                        return results

        return results

    def get_footprint_info(self, library_nickname: str, footprint_name: str) -> Optional[Dict[str, str]]:
        """
        Get information about a specific footprint

        Args:
            library_nickname: Library name
            footprint_name: Footprint name

        Returns:
            Dict with footprint information or None if not found
        """
        library_path = self.libraries.get(library_nickname)
        if not library_path:
            return None

        fp_file = Path(library_path) / f"{footprint_name}.kicad_mod"
        if not fp_file.exists():
            return None

        return {
            'library': library_nickname,
            'footprint': footprint_name,
            'full_name': f"{library_nickname}:{footprint_name}",
            'path': str(fp_file),
            'library_path': library_path
        }


class LibraryCommands:
    """Command handlers for library operations"""

    def __init__(self, library_manager: Optional[LibraryManager] = None):
        """Initialize with optional library manager"""
        self.library_manager = library_manager or LibraryManager()

    def list_libraries(self, params: Dict) -> Dict:
        """List all available footprint libraries"""
        try:
            libraries = self.library_manager.list_libraries()
            return {
                "success": True,
                "libraries": libraries,
                "count": len(libraries)
            }
        except Exception as e:
            logger.error(f"Error listing libraries: {e}")
            return {
                "success": False,
                "message": "Failed to list libraries",
                "errorDetails": str(e)
            }

    def search_footprints(self, params: Dict) -> Dict:
        """Search for footprints by pattern"""
        try:
            pattern = params.get("pattern", "*")
            limit = params.get("limit", 20)

            results = self.library_manager.search_footprints(pattern, limit)

            return {
                "success": True,
                "footprints": results,
                "count": len(results),
                "pattern": pattern
            }
        except Exception as e:
            logger.error(f"Error searching footprints: {e}")
            return {
                "success": False,
                "message": "Failed to search footprints",
                "errorDetails": str(e)
            }

    def list_library_footprints(self, params: Dict) -> Dict:
        """List all footprints in a specific library"""
        try:
            library = params.get("library")
            if not library:
                return {
                    "success": False,
                    "message": "Missing library parameter"
                }

            footprints = self.library_manager.list_footprints(library)

            return {
                "success": True,
                "library": library,
                "footprints": footprints,
                "count": len(footprints)
            }
        except Exception as e:
            logger.error(f"Error listing library footprints: {e}")
            return {
                "success": False,
                "message": "Failed to list library footprints",
                "errorDetails": str(e)
            }

    def get_footprint_info(self, params: Dict) -> Dict:
        """Get information about a specific footprint"""
        try:
            footprint_spec = params.get("footprint")
            if not footprint_spec:
                return {
                    "success": False,
                    "message": "Missing footprint parameter"
                }

            # Try to find the footprint
            result = self.library_manager.find_footprint(footprint_spec)

            if result:
                library_path, footprint_name = result
                # Extract library nickname from path
                library_nickname = None
                for nick, path in self.library_manager.libraries.items():
                    if path == library_path:
                        library_nickname = nick
                        break

                info = {
                    "library": library_nickname,
                    "footprint": footprint_name,
                    "full_name": f"{library_nickname}:{footprint_name}",
                    "library_path": library_path
                }

                return {
                    "success": True,
                    "footprint_info": info
                }
            else:
                return {
                    "success": False,
                    "message": f"Footprint not found: {footprint_spec}"
                }

        except Exception as e:
            logger.error(f"Error getting footprint info: {e}")
            return {
                "success": False,
                "message": "Failed to get footprint info",
                "errorDetails": str(e)
            }
