import logging
import os
import shutil
import traceback
import uuid
from typing import Any, List, Optional

import sexpdata
from skip import Schematic
from utils.sexpr_format import prettify

logger = logging.getLogger("kicad_interface")


class SchematicLoadError(Exception):
    """A schematic could not be loaded by the kicad-skip parser.

    Carries a structured diagnosis so every schematic tool can fail loudly
    and actionably instead of returning plausible-looking empty results.
    ``kind`` is ``"not_found"`` or ``"parse_error"``; ``flat_symbols`` names
    embedded lib symbols with no sub-units (the SnapEDA/SamacSys pattern
    that crashes kicad-skip's LibSymbol parser).
    """

    def __init__(
        self,
        path: str,
        kind: str = "parse_error",
        flat_symbols: Optional[List[str]] = None,
        details: Optional[str] = None,
    ):
        self.path = path
        self.kind = kind
        self.flat_symbols = flat_symbols or []
        self.details = details
        super().__init__(self._message())

    def _message(self) -> str:
        if self.kind == "not_found":
            return f"Schematic file not found: {self.path}"
        if self.flat_symbols:
            names = ", ".join(self.flat_symbols)
            return (
                f"Schematic load failed for {self.path}: embedded flat lib "
                f"symbols [{names}] have no sub-units and break the "
                f"kicad-skip parser; run the repair_flat_symbols tool (if "
                f'available) or wrap each flat symbol\'s pins/graphics in a '
                f'(symbol "NAME_1_1" ...) sub-unit'
            )
        cause = (self.details or "").strip().splitlines()
        return f"Schematic load failed for {self.path}: {cause[-1] if cause else 'unknown parse error'}"

    def to_response(self) -> dict:
        """Standard structured failure dict for handlers."""
        response = {
            "success": False,
            "error": "schematic_load_failed",
            "message": str(self),
            "flatSymbols": list(self.flat_symbols),
        }
        if self.details:
            response["errorDetails"] = self.details
        return response


def find_flat_lib_symbols(file_path: str) -> List[str]:
    """Names of embedded lib symbols that have no ``(symbol "NAME_x_y")``
    sub-unit children — the flat SnapEDA/SamacSys capture pattern that makes
    kicad-skip's LibSymbol raise (``pv.symbol`` -> AttributeError).

    Best-effort: returns [] when the file cannot be read/parsed (a diagnosis
    failure must never mask the original load error).
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = sexpdata.loads(f.read())
        sym = sexpdata.Symbol("symbol")
        lib_symbols = sexpdata.Symbol("lib_symbols")
        extends = sexpdata.Symbol("extends")

        flat: List[str] = []
        for item in data:
            if not (isinstance(item, list) and item and item[0] == lib_symbols):
                continue
            for sym_def in item[1:]:
                if not (
                    isinstance(sym_def, list)
                    and len(sym_def) > 1
                    and sym_def[0] == sym
                ):
                    continue
                name = str(sym_def[1])
                has_subunit = any(
                    isinstance(child, list) and child and child[0] == sym
                    for child in sym_def[2:]
                )
                is_derived = any(
                    isinstance(child, list) and child and child[0] == extends
                    for child in sym_def[2:]
                )
                if not has_subunit and not is_derived:
                    flat.append(name)
            break
        return flat
    except Exception as e:
        logger.warning(f"flat-symbol diagnosis failed for {file_path}: {e}")
        return []


class SchematicManager:
    """Core schematic operations using kicad-skip"""

    @staticmethod
    def create_schematic(
        name: str, metadata: Optional[Any] = None, *, path: Optional[str] = None
    ) -> Any:
        """Create a new empty schematic from template"""
        try:
            # Determine template path. New schematics start from a blank KiCad 10
            # file (empty lib_symbols, no placed symbols) rather than the seeded
            # template_with_symbols.kicad_sch — the live add tool synthesizes its
            # own lib_symbols via the dynamic loader, so the pre-seeded
            # _TEMPLATE_* symbols are not needed and only leaked into user files
            # (issue #221, also closes #243).
            template_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..",
                "templates",
                "blank.kicad_sch",
            )

            # Determine output path. A caller may pass `path` as either a
            # directory or a full ".kicad_sch" file path. When it is already a
            # full file path, use it directly; otherwise treat it as a directory
            # and append the schematic file name. Without this, a full path like
            # "/foo/bar/V4.kicad_sch" was joined again into
            # "/foo/bar/V4.kicad_sch/V4.kicad_sch" (issue #242).
            if path and path.endswith(".kicad_sch"):
                output_path = path
            else:
                base_name = name if name.endswith(".kicad_sch") else f"{name}.kicad_sch"
                output_path = os.path.join(path, base_name) if path else base_name

            if os.path.exists(template_path):
                # Copy template to target location
                shutil.copy(template_path, output_path)

                # Regenerate UUID to ensure uniqueness for each created schematic
                import re

                with open(output_path, "r", encoding="utf-8") as f:
                    content = f.read()
                new_uuid = str(uuid.uuid4())
                content = re.sub(
                    r"\(uuid [0-9a-fA-F-]+\)",
                    f"(uuid {new_uuid})",
                    content,
                    count=1,  # Only replace first (schematic) UUID
                )
                with open(output_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)

                logger.info(f"Created schematic from template: {output_path}")
            else:
                # Fallback: create minimal schematic
                logger.warning(f"Template not found at {template_path}, creating minimal schematic")
                # Generate unique UUID for this schematic
                schematic_uuid = str(uuid.uuid4())
                # Write with explicit UTF-8 encoding and Unix line endings for cross-platform compatibility
                with open(output_path, "w", encoding="utf-8", newline="\n") as f:
                    # KiCad 10 schematic header (matches what eeschema writes for a
                    # new file). The older 20250114 token is the KiCad 9 format and
                    # is stale under KiCad 10 (issue #221).
                    f.write(
                        '(kicad_sch (version 20260101) (generator "eeschema")'
                        ' (generator_version "10.0")\n\n'
                    )
                    f.write(f"  (uuid {schematic_uuid})\n\n")
                    f.write('  (paper "A4")\n\n')
                    f.write("  (lib_symbols\n  )\n\n")
                    f.write('  (sheet_instances\n    (path "/" (page "1"))\n  )\n')
                    f.write(")\n")

            # Load the schematic
            sch = Schematic(output_path)
            logger.info(f"Loaded new schematic: {output_path}")
            return sch

        except Exception as e:
            logger.error(f"Error creating schematic: {e}")
            raise

    @staticmethod
    def load_schematic(file_path: str) -> Any:
        """Load an existing schematic.

        Raises SchematicLoadError (never returns None) when the file is
        missing or kicad-skip cannot parse it, with flat vendor symbols
        diagnosed by name so callers can surface an actionable error.
        """
        if not os.path.exists(file_path):
            logger.error(f"Schematic file not found at {file_path}")
            raise SchematicLoadError(file_path, kind="not_found")
        try:
            sch = Schematic(file_path)
            logger.info(f"Loaded schematic from: {file_path}")
            return sch
        except Exception as e:
            logger.error(f"Error loading schematic from {file_path}: {e}")
            raise SchematicLoadError(
                file_path,
                kind="parse_error",
                flat_symbols=find_flat_lib_symbols(file_path),
                details=traceback.format_exc(),
            ) from e

    @staticmethod
    def save_schematic(schematic: Any, file_path: str) -> bool:
        """Save a schematic to file"""
        try:
            # kicad-skip uses write method, not save
            schematic.write(file_path)
            # kicad-skip emits a semi-minified layout; reformat to KiCad's
            # canonical pretty format so tool writes match eeschema's "Save"
            # and produce minimal, reviewable diffs.
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(prettify(content))
            logger.info(f"Saved schematic to: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving schematic to {file_path}: {e}")
            return False

    @staticmethod
    def get_schematic_metadata(schematic: Any) -> dict[str, Any]:
        """Extract metadata from schematic"""
        # kicad-skip doesn't expose a direct metadata object on Schematic.
        # We can return basic info like version and generator.
        metadata = {
            "version": schematic.version,
            "generator": schematic.generator,
            # Add other relevant properties if needed
        }
        logger.debug("Extracted schematic metadata")
        return metadata


if __name__ == "__main__":
    # Example Usage (for testing)
    # Create a new schematic
    new_sch = SchematicManager.create_schematic("MyTestSchematic")

    # Save the schematic
    test_file = "test_schematic.kicad_sch"
    SchematicManager.save_schematic(new_sch, test_file)

    # Load the schematic
    loaded_sch = SchematicManager.load_schematic(test_file)
    if loaded_sch:
        metadata = SchematicManager.get_schematic_metadata(loaded_sch)
        print(f"Loaded schematic metadata: {metadata}")

    # Clean up test file
    if os.path.exists(test_file):
        os.remove(test_file)
        print(f"Cleaned up {test_file}")
