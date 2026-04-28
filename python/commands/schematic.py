import logging
import os
import shutil
import uuid
from typing import Any, Optional

from skip import Schematic

logger = logging.getLogger("kicad_interface")


class SchematicManager:
    """Core schematic operations using kicad-skip"""

    @staticmethod
    def create_schematic(
        name: str, metadata: Optional[Any] = None, *, path: Optional[str] = None
    ) -> Any:
        """Create a new empty schematic from template"""
        try:
            # Determine template path (use template_with_symbols for component cloning support)
            template_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..",
                "templates",
                "template_with_symbols.kicad_sch",
            )

            # Determine output path
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
                    f.write('(kicad_sch (version 20250114) (generator "KiCAD-MCP-Server")\n\n')
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
    def load_schematic(file_path: str) -> Optional[Any]:
        """Load an existing schematic"""
        if not os.path.exists(file_path):
            logger.error(f"Schematic file not found at {file_path}")
            return None
        try:
            sch = Schematic(file_path)
            logger.info(f"Loaded schematic from: {file_path}")
            return sch
        except Exception as e:
            logger.error(f"Error loading schematic from {file_path}: {e}")
            return None

    @staticmethod
    def save_schematic(schematic: Any, file_path: str) -> bool:
        """Save a schematic to file"""
        try:
            # kicad-skip uses write method, not save
            schematic.write(file_path)
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
