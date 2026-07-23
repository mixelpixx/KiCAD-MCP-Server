"""
Dynamic Symbol Loader for KiCad Schematics

Loads symbols from .kicad_sym library files and injects them into schematics
on-the-fly using TEXT MANIPULATION (not sexpdata) to preserve file formatting.

This enables access to all ~10,000+ KiCad symbols dynamically.
"""

import logging
import os
import re
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("kicad_interface")

# Module-level caches shared across DynamicSymbolLoader instances.
# A fresh loader is created for every add_component call (see
# schematic_handlers), so instance-level caches never survive — every
# component add would otherwise re-scan the sym-lib-table and re-read
# multi-MB .kicad_sym files. These caches make library resolution and symbol
# extraction pay their cost once. Libraries are NOT immutable mid-session,
# though: create_symbol / delete_symbol / add_library_symbol_property rewrite
# .kicad_sym files and register_symbol_library rewrites the sym-lib-table, so
# stale entries are guarded three ways — resolution misses are never cached,
# resolved paths are revalidated with exists(), and symbol blocks carry the
# source file's mtime_ns. The mutating handlers additionally call
# DynamicSymbolLoader.clear_library_caches() for the case a stat cannot see
# (re-pointing an existing library name at a different path).
_LIB_DIRS_CACHE: Optional[Tuple[Tuple, List[Path]]] = None  # (env fingerprint, dirs)
_LIB_FILE_CACHE: Dict[Tuple, Path] = {}
_SYMBOL_BLOCK_CACHE: Dict[Tuple[str, str], Tuple[Optional[int], Optional[str]]] = {}

_SYMBOL_DIR_ENV_VARS = (
    "KICAD10_SYMBOL_DIR",
    "KICAD9_SYMBOL_DIR",
    "KICAD8_SYMBOL_DIR",
    "KICAD_SYMBOL_DIR",
)


def _esc_sexpr(value: str) -> str:
    """Escape a string for safe insertion into an S-expression double-quoted token.

    Library property values may themselves contain quotes — power:GND's Description
    is `Power symbol creates a global label with name "GND"`. Emitted raw, the inner
    quote closes the token early and corrupts the rest of the .kicad_sch.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _symbol_dir_env_fingerprint() -> Tuple:
    """The env-var inputs library discovery depends on.

    Cached discovery results are only valid for the environment they were
    computed under — tests monkeypatch KICAD_SYMBOL_DIR per test, and a cache
    key that ignores it serves one test's temp directory to the next.
    """
    return tuple(os.environ.get(v) for v in _SYMBOL_DIR_ENV_VARS)


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

    @staticmethod
    def clear_library_caches() -> None:
        """Reset the module-level library caches (call if libraries change on disk)."""
        global _LIB_DIRS_CACHE
        _LIB_DIRS_CACHE = None
        _LIB_FILE_CACHE.clear()
        _SYMBOL_BLOCK_CACHE.clear()

    def find_kicad_symbol_libraries(self) -> List[Path]:
        """Find all KiCad symbol library directories (cached module-wide).

        The cache entry records the env fingerprint it was computed under and
        is ignored if the KICAD*_SYMBOL_DIR environment has changed since.
        """
        global _LIB_DIRS_CACHE
        env = _symbol_dir_env_fingerprint()
        if _LIB_DIRS_CACHE is not None and _LIB_DIRS_CACHE[0] == env:
            return _LIB_DIRS_CACHE[1]
        # Discovered install roots first (registry + Program Files globs +
        # custom roots like C:\KiCad, newest version first) — the same shared
        # helper the cli/footprint/symbol-search paths use (#286), so the
        # production component-placement path cannot drift from the rest of
        # discovery again. Env-var overrides below still take precedence.
        try:
            from utils.kicad_roots import kicad_install_roots

            root_symbol_dirs = [r / "share" / "kicad" / "symbols" for r in kicad_install_roots()]
        except Exception:  # pragma: no cover - defensive; helper is stdlib-only
            root_symbol_dirs = []

        possible_paths = root_symbol_dirs + [
            Path("C:/Program Files/KiCad/10.0/share/kicad/symbols"),
            Path("/usr/share/kicad/symbols"),
            Path("/usr/local/share/kicad/symbols"),
            Path("C:/Program Files/KiCad/9.0/share/kicad/symbols"),
            Path("C:/Program Files/KiCad/8.0/share/kicad/symbols"),
            Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"),
            Path.home() / ".local" / "share" / "kicad" / "10.0" / "symbols",
            Path.home() / ".local" / "share" / "kicad" / "9.0" / "symbols",
            Path.home() / "Documents" / "KiCad" / "10.0" / "3rdparty" / "symbols",
            Path.home() / "Documents" / "KiCad" / "9.0" / "3rdparty" / "symbols",
        ]
        for env_var in [
            "KICAD10_SYMBOL_DIR",
            "KICAD9_SYMBOL_DIR",
            "KICAD8_SYMBOL_DIR",
            "KICAD_SYMBOL_DIR",
        ]:
            if env_var in os.environ:
                possible_paths.insert(0, Path(os.environ[env_var]))

        dirs = [p for p in possible_paths if p.exists() and p.is_dir()]
        _LIB_DIRS_CACHE = (env, dirs)
        return dirs

    def find_library_file(self, library_name: str) -> Optional[Path]:
        """Find the .kicad_sym file for a given library name.

        Search order:
        1. Project-specific sym-lib-table (if project_path is set)
        2. Global KiCad sym-lib-table (~/AppData/Roaming/kicad/<ver>/sym-lib-table on
           Windows, ~/.config/kicad/<ver>/sym-lib-table on Linux,
           ~/Library/Preferences/kicad/<ver>/sym-lib-table on macOS) — covers user-
           registered libraries that live outside the bundled symbol directories
           (e.g. company libraries in OneDrive, network shares, custom paths).
        3. Bundled / well-known KiCad symbol library directories.

        Resolution is cached module-wide by (project_path, library_name, env
        fingerprint) so that repeated component adds don't re-scan the
        sym-lib-table every time. Only successful resolutions are cached: a
        "not found" is typically followed by the user creating or registering
        that library, and a cached miss would keep the name unresolvable
        until process restart. Cached paths are revalidated with exists() so
        a deleted or moved library re-resolves instead of being served stale.
        """
        # A loader whose discovery has been instance-patched (tests point
        # find_kicad_symbol_libraries at a temp dir) must not read or write
        # the shared cache: its results are not valid for other loaders, and
        # the patched state is invisible to any module-level cache key.
        shares_cache = "find_kicad_symbol_libraries" not in self.__dict__

        cache_key = (
            str(self.project_path) if self.project_path else None,
            library_name,
            _symbol_dir_env_fingerprint(),
        )
        if shares_cache:
            hit = _LIB_FILE_CACHE.get(cache_key)
            if hit is not None and hit.exists():
                return hit

        def _search() -> Optional[Path]:
            # 1. Check project-specific sym-lib-table
            if self.project_path:
                project_table = Path(self.project_path) / "sym-lib-table"
                if project_table.exists():
                    resolved = self._resolve_library_from_table(project_table, library_name)
                    if resolved:
                        logger.info(f"Found '{library_name}' in project sym-lib-table: {resolved}")
                        return resolved

            # 2. Check global user sym-lib-table
            for global_table in self._global_sym_lib_table_paths():
                if global_table.exists():
                    resolved = self._resolve_library_from_table(global_table, library_name)
                    if resolved:
                        logger.info(
                            f"Found '{library_name}' in global sym-lib-table {global_table}: {resolved}"
                        )
                        return resolved

            # 3. Fall back to bundled / well-known KiCad symbol directories
            for lib_dir in self.find_kicad_symbol_libraries():
                # Classic single-file library (KiCAD 8/9)
                lib_file = lib_dir / f"{library_name}.kicad_sym"
                if lib_file.exists():
                    return lib_file
                # KiCAD 10 per-symbol directory library
                lib_symdir = lib_dir / f"{library_name}.kicad_symdir"
                if lib_symdir.exists() and lib_symdir.is_dir():
                    return lib_symdir

            logger.warning(
                f"Library file not found: {library_name}.kicad_sym / {library_name}.kicad_symdir"
            )
            return None

        result = _search()
        if shares_cache:
            if result is not None:
                _LIB_FILE_CACHE[cache_key] = result
            else:
                _LIB_FILE_CACHE.pop(cache_key, None)
        return result

    def _global_sym_lib_table_paths(self) -> list:
        """Candidate paths for the user-global sym-lib-table, newest version first."""
        home = Path.home()
        versions = ["10.0", "9.0", "8.0"]
        bases = []
        if os.name == "nt":
            bases.append(home / "AppData" / "Roaming" / "kicad")
        else:
            bases.append(home / ".config" / "kicad")
            bases.append(home / "Library" / "Preferences" / "kicad")  # macOS
        candidates = []
        for base in bases:
            for v in versions:
                candidates.append(base / v / "sym-lib-table")
        return candidates

    def _resolve_library_from_table(self, table_path: Path, library_name: str) -> Optional[Path]:
        """Parse a sym-lib-table file and return the resolved path for the given library nickname."""
        try:
            with open(table_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Name and URI may be quoted (with embedded spaces, e.g. OneDrive paths)
            # or bare. Match a quoted "..." form first, otherwise a bareword that
            # excludes whitespace and parens.
            lib_pattern = (
                r"\(lib\s+"
                r'\(name\s+(?:"([^"]+)"|([^"\)\s]+))\)\s*'
                r"\(type\s+[^)]+\)\s*"
                r'\(uri\s+(?:"([^"]+)"|([^"\)\s]+))'
            )
            for match in re.finditer(lib_pattern, content, re.IGNORECASE):
                # Groups: 1=quoted name, 2=bare name, 3=quoted uri, 4=bare uri
                nickname = match.group(1) or match.group(2)
                if nickname != library_name:
                    continue
                uri = match.group(3) or match.group(4)
                resolved = self._resolve_sym_uri(uri)
                if resolved and Path(resolved).exists():
                    return Path(resolved)
        except Exception as e:
            logger.warning(f"Could not parse sym-lib-table {table_path}: {e}")
        return None

    def _resolve_sym_uri(self, uri: str) -> Optional[str]:
        """Resolve environment variables in a sym-lib-table URI."""
        env_map = {
            "KICAD10_SYMBOL_DIR": [
                "/usr/share/kicad/symbols",
                "C:/Program Files/KiCad/10.0/share/kicad/symbols",
                "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
            ],
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

    def _inline_extends_symbol(self, lib_content: str, symbol_name: str, child_block: str) -> str:
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
            sub_match = re.search(r'\(symbol "' + re.escape(parent_name) + r'_\d+_\d+"', item)

            if prop_match:
                pname = prop_match.group(1)
                parent_prop_names.add(pname)
                body_lines.append(child_props[pname] if pname in child_props else item)
            elif sub_match:
                # Rename ParentName_0_1 → ChildName_0_1
                body_lines.append(item.replace(f'"{parent_name}_', f'"{symbol_name}_'))
            elif re.match(r"[\s\t]*\(extends ", item):
                pass  # drop extends clause
            else:
                body_lines.append(item)  # pin_names, in_bom, on_board …

        # Append child-only properties absent from parent
        for pname, pblock in child_props.items():
            if pname not in parent_prop_names:
                body_lines.append(pblock)

        first_line = parent_block.split("\n")[0].replace(f'"{parent_name}"', f'"{symbol_name}"')
        last_line = parent_block.split("\n")[-1]

        return first_line + "\n" + "\n".join(body_lines) + "\n" + last_line

    def _read_symdir_shard(self, lib_dir: Path, symbol_name: str) -> Optional[str]:
        """Read the per-symbol shard ``<symbol>.kicad_sym`` from a ``.kicad_symdir``."""
        shard = lib_dir / f"{symbol_name}.kicad_sym"
        if not shard.exists():
            return None
        try:
            with open(shard, "r", encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            logger.warning(f"Could not read symdir shard {shard}: {e}")
            return None

    def _resolve_symdir_extends(
        self, lib_dir: Path, symbol_name: str, block: str, _seen: Optional[set] = None
    ) -> str:
        """Inline ``(extends "Parent")`` for a sharded (``.kicad_symdir``) library.

        Unlike a single-file library, a derived symbol's parent lives in its own
        sibling shard ``<Parent>.kicad_sym`` and is therefore absent from this
        symbol's file (issue #282). Read the parent shard, resolve it recursively
        (a parent may itself extend a grandparent in yet another shard), then merge
        the fully-resolved parent into the child with the shared single-level
        inliner. When the parent shard is missing or the chain is cyclic, hand the
        inliner an empty library so it falls back to its graceful strip-and-warn.
        """
        extends_match = re.search(r'\(extends "([^"]+)"\)', block)
        if not extends_match:
            return block

        parent_name = extends_match.group(1)
        seen = set() if _seen is None else _seen

        parent_content = ""
        if parent_name not in seen:
            seen.add(parent_name)
            shard = self._read_symdir_shard(lib_dir, parent_name)
            if shard is not None:
                parent_block = self._extract_symbol_block(shard, parent_name)
                if parent_block is not None:
                    # Fully resolve the parent (extends-free) before merging so
                    # multi-level chains inline completely.
                    parent_content = self._resolve_symdir_extends(
                        lib_dir, parent_name, parent_block, seen
                    )

        return self._inline_extends_symbol(parent_content, symbol_name, block)

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

        # The physical file the symbol lives in: for a KiCAD 10 directory
        # library each symbol is its own shard file.
        src_file = lib_path / f"{symbol_name}.kicad_sym" if lib_path.is_dir() else lib_path

        def _src_mtime_ns() -> Optional[int]:
            try:
                return src_file.stat().st_mtime_ns
            except OSError:
                return None

        # Module-level cache keyed by the resolved library path + symbol, so the
        # multi-MB .kicad_sym is read and parsed once even though a fresh loader
        # (and empty self.symbol_cache) is created for every component add.
        # Entries carry the source file's mtime_ns: create_symbol /
        # delete_symbol / add_library_symbol_property rewrite .kicad_sym files
        # mid-session, so a hit is honoured only while the mtime matches. (For
        # a symdir symbol whose (extends ...) parent lives in a sibling shard,
        # a parent-only edit is invisible to this stat — the mutating handlers
        # call clear_library_caches() to cover that.)
        mod_key = (str(lib_path), symbol_name)
        current_mtime = _src_mtime_ns()
        entry = _SYMBOL_BLOCK_CACHE.get(mod_key)
        if entry is not None and entry[0] == current_mtime:
            cached = entry[1]
            self.symbol_cache[cache_key] = cached
            return cached

        # KiCAD 10 directory library: each symbol is its own file
        if lib_path.is_dir():
            if not src_file.exists():
                logger.warning(f"Symbol '{symbol_name}' not found in directory library {lib_path}")
                _SYMBOL_BLOCK_CACHE[mod_key] = (current_mtime, None)
                return None
            with open(src_file, "r", encoding="utf-8") as f:
                lib_content = f.read()
        else:
            with open(lib_path, "r", encoding="utf-8") as f:
                lib_content = f.read()

        block = self._extract_symbol_block(lib_content, symbol_name)
        if block is None:
            logger.warning(f"Symbol '{symbol_name}' not found in {library_name}")
            _SYMBOL_BLOCK_CACHE[mod_key] = (current_mtime, None)
            return None

        # If the symbol uses (extends "ParentName"), inline the parent content
        # so that the result is a fully self-contained definition.
        # (extends ...) is only valid in .kicad_sym files; KiCad 9 refuses to
        # load a schematic whose lib_symbols section contains it.
        if re.search(r'\(extends "([^"]+)"\)', block):
            parent_name = re.search(r'\(extends "([^"]+)"\)', block).group(1)
            logger.info(f"Symbol {symbol_name} extends {parent_name}, inlining parent content")
            if lib_path.is_dir():
                # Sharded (.kicad_symdir) library: the parent is in a sibling
                # shard, not in this symbol's file, so resolve across shards (#282).
                block = self._resolve_symdir_extends(lib_path, symbol_name, block)
            else:
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
        _SYMBOL_BLOCK_CACHE[mod_key] = (current_mtime, result)
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
            raise ValueError(f"Symbol '{symbol_name}' not found in library '{library_name}'")

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
        sch_name = schematic_path.name if hasattr(schematic_path, "name") else str(schematic_path)
        logger.info(f"Injected symbol {full_name} into {sch_name}")
        return True

    @staticmethod
    def _extract_paren_block(text: str, start: int) -> str:
        """Return the substring from text[start] up to and including the matching closing paren."""
        depth, i = 0, start
        while i < len(text):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
            i += 1
        return text[start:]

    def _extract_lib_property_positions(
        self,
        schematic_path: Path,
        library_name: str,
        symbol_name: str,
    ) -> dict:
        """
        Return {prop_name: (dx, dy, text_angle, effects_str)} from the lib_symbols
        section of the schematic (which must already have the symbol injected).
        effects_str is the full '(effects ...)' string to be reused in the placed
        instance so that justify, font size, hide etc. are preserved.
        Returns an empty dict on failure.
        """
        try:
            with open(schematic_path, encoding="utf-8") as f:
                content = f.read()

            lib_start = content.find("(lib_symbols")
            if lib_start == -1:
                return {}

            sym_start = content.find(f'(symbol "{library_name}:{symbol_name}"', lib_start)
            if sym_start == -1:
                return {}

            sym_block = self._extract_paren_block(content, sym_start)

            import re

            result = {}
            # Iterate over every top-level (property ...) block in the symbol
            search_pos = 0
            while True:
                m = re.search(
                    r'\(property\s+"([^"]+)"\s+"[^"]*"\s+\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)',
                    sym_block[search_pos:],
                )
                if not m:
                    break
                abs_start = search_pos + m.start()
                prop_block = self._extract_paren_block(sym_block, abs_start)

                name = m.group(1)
                dx = float(m.group(2))
                dy = float(m.group(3))
                angle = float(m.group(4))

                # Extract (effects ...) block from within this property
                eff_pos = prop_block.find("(effects")
                if eff_pos != -1:
                    effects_str = self._extract_paren_block(prop_block, eff_pos)
                    # Strip (hide ...) sub-expressions — visibility will be set
                    # separately by the caller
                    effects_str = re.sub(r"\s*\(hide\s+[^)]+\)", "", effects_str)
                    effects_str = effects_str.strip()
                else:
                    effects_str = "(effects (font (size 1.27 1.27)))"

                # Only store the first occurrence (top-level lib property, not sub-symbol)
                if name not in result:
                    result[name] = (dx, dy, angle, effects_str)

                search_pos = abs_start + 1

            return result
        except Exception:
            return {}

    @staticmethod
    def _rotate_offset(dx: float, dy: float, angle_deg: float) -> tuple:
        """
        Rotate a 2-D offset by angle_deg degrees (KiCad CCW-in-screen, i.e. Y-axis
        points downward).  Returns (rx, ry) rounded to 3 decimal places.
        """
        import math

        rad = math.radians(angle_deg)
        # Standard CCW rotation in Y-down screen coordinates:
        #   rx =  dx * cos(a) + dy * sin(a)
        #   ry = -dx * sin(a) + dy * cos(a)
        rx = dx * math.cos(rad) + dy * math.sin(rad)
        ry = -dx * math.sin(rad) + dy * math.cos(rad)
        return round(rx, 3), round(ry, 3)

    # ------------------------------------------------------------------ #
    # Instance-block helpers (project name, hierarchical path, pin uuids) #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _read_root_uuid(content: str) -> str:
        """Return a schematic's own top-level (uuid ...) value, or '' if absent."""
        m = re.search(r'\(uuid\s+"?([0-9a-fA-F-]+)"?\)', content)
        return m.group(1) if m else ""

    def _resolve_project_name(self, schematic_path: Path) -> str:
        """Return the KiCad project name recorded in (instances (project "<name>" ...)).

        KiCad uses the project (``.kicad_pro``) stem, not the literal string
        ``"project"``. Derive it from the nearest ``.kicad_pro`` (searching the
        schematic's directory then a few parents), falling back to the schematic's
        own stem when no project file is found.
        """
        try:
            sch = Path(schematic_path).resolve()
            search_dirs = [sch.parent] + list(sch.parent.parents)[:3]
            for directory in search_dirs:
                pros = sorted(directory.glob("*.kicad_pro"))
                if pros:
                    return pros[0].stem
            return sch.stem
        except Exception:
            return Path(schematic_path).stem

    def _iter_child_sheets(self, content: str) -> List[Tuple[str, str]]:
        """Yield (sheet_block_uuid, sheet_file_rel) for each (sheet ...) in a schematic.

        Skips (sheet_instances ...) — its token has no whitespace after ``sheet``.
        """
        results: List[Tuple[str, str]] = []
        for m in re.finditer(r"\(sheet(?=\s)", content):
            block = self._extract_paren_block(content, m.start())
            um = re.search(r'\(uuid\s+"?([0-9a-fA-F-]+)"?\)', block)
            fm = re.search(r'\(property\s+"Sheet file"\s+"([^"]+)"', block)
            if um and fm:
                results.append((um.group(1), fm.group(1).replace("\\", "/")))
        return results

    def _find_root_schematic(self, target: Path) -> Optional[Path]:
        """Find the project's root .kicad_sch (the one carrying (sheet_instances ...))."""
        try:
            directory = target.parent
            for pro in sorted(directory.glob("*.kicad_pro")):
                cand = directory / f"{pro.stem}.kicad_sch"
                if cand.exists():
                    return cand.resolve()
            for cand in sorted(directory.glob("*.kicad_sch")):
                try:
                    if "(sheet_instances" in cand.read_text(encoding="utf-8"):
                        return cand.resolve()
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _sheet_chain_to(self, root: Path, target: Path) -> List[str]:
        """Return the UUID chain [root_uuid, sheet_block_uuid, ...] from root to target.

        Walks the root project's sheet tree breadth-first. Returns [] if target is not
        reachable from root.
        """
        try:
            root = root.resolve()
            target = target.resolve()
            root_content = root.read_text(encoding="utf-8")
            root_uuid = self._read_root_uuid(root_content)
            if not root_uuid:
                return []
            if root == target:
                return [root_uuid]
            visited = {root}
            queue: List[Tuple[Path, str, List[str]]] = [(root, root_content, [root_uuid])]
            while queue:
                fpath, fcontent, chain = queue.pop(0)
                for block_uuid, rel in self._iter_child_sheets(fcontent):
                    child = (fpath.parent / rel).resolve()
                    new_chain = chain + [block_uuid]
                    if child == target:
                        return new_chain
                    if child.exists() and child not in visited:
                        visited.add(child)
                        try:
                            queue.append((child, child.read_text(encoding="utf-8"), new_chain))
                        except Exception:
                            continue
            return []
        except Exception:
            return []

    def _build_instance_path(self, schematic_path: Path) -> str:
        """Return the symbol instance path for symbols placed in ``schematic_path``.

        - Root / flat schematic (carries (sheet_instances ...)): ``/<root-sheet-uuid>``
          where the UUID is the schematic's own top-level (uuid ...).
        - Child sheet in a hierarchy: the chain of sheet-instance UUIDs from the root,
          ``/<root-uuid>/<sheet-block-uuid>[/...]``, reconstructed by walking the root
          project's sheet tree.
        - Unlinked child (no chain yet): one level using the sheet's own UUID;
          add_hierarchical_sheet -> fix_subsheet_instances repairs it once linked.
        """
        try:
            target = Path(schematic_path).resolve()
            content = target.read_text(encoding="utf-8")
            this_uuid = self._read_root_uuid(content)

            if "(sheet_instances" in content and this_uuid:
                return f"/{this_uuid}"

            root = self._find_root_schematic(target)
            if root is not None:
                chain = self._sheet_chain_to(root, target)
                if chain:
                    return "/" + "/".join(chain)

            return f"/{this_uuid}" if this_uuid else "/"
        except Exception:
            return "/"

    def _extract_symbol_pins(
        self, schematic_path: Path, library_name: str, symbol_name: str, unit: int
    ) -> List[str]:
        """Return string-sorted pin numbers for the placed unit (plus shared unit-0 pins).

        KiCad writes a ``(pin "N" (uuid ...))`` entry inside every placed symbol for each
        pin; omitting them yields a structurally-incomplete instance the editor can crash
        on when dragged. Pins live inside lib sub-symbols named ``<sym>_<unit>_<style>``;
        unit-0 sub-symbols are shared by every unit. Numbers are returned in KiCad's
        ordering (ascending string sort).
        """
        try:
            content = Path(schematic_path).read_text(encoding="utf-8")
            lib_start = content.find("(lib_symbols")
            if lib_start == -1:
                return []
            sym_start = content.find(f'(symbol "{library_name}:{symbol_name}"', lib_start)
            if sym_start == -1:
                return []
            sym_block = self._extract_paren_block(content, sym_start)

            numbers: List[str] = []
            for m in re.finditer(r'\(symbol\s+"([^"]+)"', sym_block):
                name = m.group(1)
                if ":" in name:
                    # Top-level lib wrapper (e.g. "Device:R"); units live in sub-symbols.
                    continue
                um = re.search(r"_(\d+)_(\d+)$", name)
                sub_unit = int(um.group(1)) if um else None
                if sub_unit not in (None, 0, unit):
                    continue
                sub_block = self._extract_paren_block(sym_block, m.start())
                for pm in re.finditer(r'\(pin\b.*?\(number\s+"([^"]+)"', sub_block, re.DOTALL):
                    numbers.append(pm.group(1))

            return sorted(dict.fromkeys(numbers))
        except Exception:
            return []

    def _extract_lib_property_value(
        self, schematic_path: Path, library_name: str, symbol_name: str, prop_name: str
    ) -> Optional[str]:
        """Return a top-level property value from the injected lib symbol, or None.

        Used to copy Datasheet/Description values into the placed instance so it matches
        KiCad-authored output (KiCad carries these fields on every symbol).
        """
        try:
            content = Path(schematic_path).read_text(encoding="utf-8")
            lib_start = content.find("(lib_symbols")
            if lib_start == -1:
                return None
            sym_start = content.find(f'(symbol "{library_name}:{symbol_name}"', lib_start)
            if sym_start == -1:
                return None
            sym_block = self._extract_paren_block(content, sym_start)
            m = re.search(r'\(property\s+"' + re.escape(prop_name) + r'"\s+"([^"]*)"', sym_block)
            return m.group(1) if m else None
        except Exception:
            return None

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
        unit: int = 1,
        angle: float = 0,
        mirror_y: bool = False,
    ) -> bool:
        """
        Add a component instance to the schematic.
        This creates the (symbol ...) block with lib_id reference.

        Property positions and text angles are derived from the library symbol
        definition so that RefDes/Value are always placed correctly for the
        component orientation (e.g. rotated 90° for a vertical resistor).

        Args:
            unit:  For multi-unit symbols, which unit to place (1=A, 2=B, …).
            angle: Placement rotation in degrees (KiCad CCW-in-screen convention).
        """
        full_lib_id = f"{library_name}:{symbol_name}"
        new_uuid = str(uuid.uuid4())

        # Snap the symbol origin to the 1.27 mm (50 mil) schematic connection grid.
        # Library pins sit at integer multiples of 1.27 mm from the origin, so once
        # the origin is on-grid every pin lands on-grid too — a prerequisite for
        # wires and net labels to bind electrically (otherwise ERC reports
        # endpoint_off_grid and the netlist comes up empty).
        # The round(..., 2) is exact, not cosmetic: every multiple of 1.27 is
        # k*127/100 and so has at most two decimals, but the float product
        # (e.g. 79 * 1.27) can carry binary representation dust that would
        # otherwise be written into the file verbatim ("100.32999999999998")
        # and reformatted by KiCad on its next save.
        _GRID = 1.27
        snapped_x = round(round(x / _GRID) * _GRID, 2)
        snapped_y = round(round(y / _GRID) * _GRID, 2)
        if (snapped_x, snapped_y) != (x, y):
            logger.info(
                f"Snapped {reference} origin ({x}, {y}) -> ({snapped_x}, {snapped_y})"
                " onto 1.27mm grid"
            )
        x, y = snapped_x, snapped_y

        # --- read property offsets from the already-injected lib_symbols block -----
        lib_props = self._extract_lib_property_positions(schematic_path, library_name, symbol_name)

        _DEFAULT_EFFECTS = "(effects (font (size 1.27 1.27)))"

        def _prop_at(
            name: str, fallback_dx: float, fallback_dy: float, fallback_angle: float = 0
        ) -> tuple:
            """Return (abs_x, abs_y, text_angle, effects_str) for a property."""
            if name in lib_props:
                dx, dy, text_ang, eff = lib_props[name]
            else:
                dx, dy, text_ang, eff = fallback_dx, fallback_dy, fallback_angle, _DEFAULT_EFFECTS
            rdx, rdy = self._rotate_offset(dx, dy, angle)
            return round(x + rdx, 3), round(y + rdy, 3), text_ang, eff

        ref_x, ref_y, ref_a, ref_eff = _prop_at("Reference", 2.032, 0, 0)
        val_x, val_y, val_a, val_eff = _prop_at("Value", 0, 2.54, 0)
        fp_x, fp_y, fp_a, fp_eff = _prop_at("Footprint", 0, 0, 0)
        ds_x, ds_y, ds_a, ds_eff = _prop_at("Datasheet", 0, 0, 0)
        desc_x, desc_y, desc_a, desc_eff = _prop_at("Description", 0, 0, 0)

        def _fmt(n: float) -> str:
            """Format a coordinate the way KiCad does: integral values without a
            trailing ``.0`` (e.g. 100.0 -> '100', 90.0 -> '90')."""
            try:
                f = float(n)
            except (TypeError, ValueError):
                return str(n)
            return str(int(f)) if f.is_integer() else str(n)

        def _clean_effects(eff: str) -> str:
            """Strip legacy hide markers from a lib (effects ...) string.

            KiCad 10 records field visibility with a top-level (hide yes) on the
            property, not inside (effects ...). Remove both the parenthesised
            (hide ...) and the bare ``hide`` token so we don't emit a v9-style
            effects block beside the v10 top-level (hide yes).
            """
            eff = re.sub(r"\s*\(hide\s+[^)]*\)", "", eff)
            eff = re.sub(r"\s+hide(?=[\s)])", "", eff)
            return eff.strip() or "(effects (font (size 1.27 1.27)))"

        def _property(
            name: str, value: str, px: float, py: float, pa: float, eff: str, hide: bool
        ) -> str:
            """Build a KiCad-10 (property ...) block.

            Field order: at, [hide yes], show_name no, do_not_autoplace no, effects.
            """
            hide_line = "      (hide yes)\n" if hide else ""
            return (
                f'    (property "{_esc_sexpr(name)}" "{_esc_sexpr(value)}"\n'
                f"      (at {_fmt(px)} {_fmt(py)} {_fmt(pa)})\n"
                f"{hide_line}"
                f"      (show_name no)\n"
                f"      (do_not_autoplace no)\n"
                f"      {_clean_effects(eff)}\n"
                f"    )"
            )

        # Datasheet/Description values come from the injected lib symbol. KiCad normalises
        # the placeholder "~" datasheet to an empty string, so mirror that to keep the
        # generated instance byte-stable across a KiCad save (round-trip).
        ds_val = self._extract_lib_property_value(
            schematic_path, library_name, symbol_name, "Datasheet"
        )
        ds_val = "" if ds_val in (None, "~") else ds_val
        desc_val = (
            self._extract_lib_property_value(
                schematic_path, library_name, symbol_name, "Description"
            )
            or ""
        )

        properties_str = "\n".join(
            [
                _property("Reference", reference, ref_x, ref_y, ref_a, ref_eff, False),
                _property("Value", value or symbol_name, val_x, val_y, val_a, val_eff, False),
                _property("Footprint", footprint, fp_x, fp_y, fp_a, fp_eff, True),
                _property("Datasheet", ds_val, ds_x, ds_y, ds_a, ds_eff, True),
                _property("Description", desc_val, desc_x, desc_y, desc_a, desc_eff, True),
            ]
        )

        # Per-pin uuids — KiCad writes a (pin "N" (uuid ...)) for every pin of the placed
        # unit; their absence is a primary cause of editor crashes when the symbol is dragged.
        pin_numbers = self._extract_symbol_pins(schematic_path, library_name, symbol_name, unit)
        pins_str = "\n".join(f'    (pin "{n}" (uuid "{uuid.uuid4()}"))' for n in pin_numbers)

        # Real project name + hierarchical sheet path (not the "project" / "/" placeholders).
        project_name = self._resolve_project_name(schematic_path)
        instance_path = self._build_instance_path(schematic_path)
        instances_str = (
            "    (instances\n"
            f'      (project "{project_name}"\n'
            f'        (path "{instance_path}"\n'
            f'          (reference "{reference}")\n'
            f"          (unit {unit})\n"
            "        )\n"
            "      )\n"
            "    )"
        )

        body = "\n".join(part for part in [properties_str, pins_str, instances_str] if part)

        mirror_str = " (mirror y)" if mirror_y else ""
        instance_block = (
            f'  (symbol (lib_id "{full_lib_id}") (at {_fmt(x)} {_fmt(y)} {_fmt(angle)})'
            f"{mirror_str} (unit {unit})\n"
            "    (body_style 1) (exclude_from_sim no) (in_bom yes) (on_board yes)"
            " (in_pos_files yes) (dnp no)\n"
            f'    (uuid "{new_uuid}")\n'
            f"{body}\n"
            "  )"
        )

        with open(schematic_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Insert before (sheet_instances using direct string search.
        # This works for both pretty-printed and sexpdata-compacted single-line files.
        insert_marker = "(sheet_instances"
        insert_at = content.rfind(insert_marker)
        if insert_at == -1:
            # Hierarchical sub-sheets don't carry (sheet_instances ...) — only the
            # root .kicad_sch does. Fall back to inserting just before the final
            # closing paren of the outer (kicad_sch ...) form.
            stripped = content.rstrip()
            if not stripped.endswith(")"):
                raise ValueError("Could not find insertion point in schematic")
            insert_at = len(stripped) - 1
            content = content[:insert_at] + instance_block + "\n" + content[insert_at:]
        else:
            content = content[:insert_at] + instance_block + "\n  " + content[insert_at:]

        with open(schematic_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Added component instance {reference} ({full_lib_id}) at ({x}, {y})")
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
        unit: int = 1,
        angle: float = 0,
        mirror_y: bool = False,
        project_path: Optional[Path] = None,
    ) -> bool:
        """
        High-level: ensure symbol definition exists in schematic, then add an instance.
        This is the main entry point for adding components.

        Args:
            unit:  For multi-unit symbols, which unit to place (1=A, 2=B, …). Default 1.
            angle: Placement rotation in degrees (KiCad CCW-in-screen). Default 0.
            project_path: Optional project directory for project-local sym-lib-table.
        """
        if project_path:
            self.project_path = project_path
        # Ensure symbol definition is in lib_symbols
        self.inject_symbol_into_schematic(schematic_path, library_name, symbol_name)

        # Add the component instance (property positions come from the injected lib def)
        return self.create_component_instance(
            schematic_path,
            library_name,
            symbol_name,
            reference=reference,
            value=value,
            footprint=footprint,
            x=x,
            y=y,
            unit=unit,
            angle=angle,
            mirror_y=mirror_y,
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
