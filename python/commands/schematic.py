from skip import Schematic
import os

class SchematicManager:
    """Core schematic operations using kicad-skip"""

    @staticmethod
    def create_schematic(name, metadata=None):
        """Create a new empty schematic"""
        # kicad-skip requires a filepath to create a schematic
        # We'll create a blank schematic file by loading an existing file
        # or we can create a template file first.
        
        # Create an empty template file first
        temp_path = f"{name}_template.kicad_sch"
        with open(temp_path, 'w') as f:
            # Write minimal schematic file content
            f.write("(kicad_sch (version 20230121) (generator \"KiCAD-MCP-Server\"))\n")
        
        # Now load it
        sch = Schematic(temp_path)
        sch.version = "20230121"  # Set appropriate version
        sch.generator = "KiCAD-MCP-Server"
        
        # Clean up the template
        os.remove(temp_path)
        # Add metadata if provided
        if metadata:
            for key, value in metadata.items():
                 # kicad-skip doesn't have a direct metadata property on Schematic,
                 # but we can add properties to the root sheet if needed, or
                 # include it in the file path/name convention.
                 # For now, we'll just create the schematic.
                 pass # Placeholder for potential metadata handling

        print(f"Created new schematic: {name}")
        return sch

    @staticmethod
    def load_schematic(file_path):
        """Load an existing schematic"""
        if not os.path.exists(file_path):
            print(f"Error: Schematic file not found at {file_path}")
            return None
        try:
            sch = Schematic(file_path)
            print(f"Loaded schematic from: {file_path}")
            return sch
        except Exception as e:
            print(f"Error loading schematic from {file_path}: {e}")
            return None

    @staticmethod
    def save_schematic(schematic, file_path):
        """Save a schematic to file"""
        try:
            # kicad-skip uses write method, not save
            schematic.write(file_path)
            print(f"Saved schematic to: {file_path}")
            return True
        except Exception as e:
            print(f"Error saving schematic to {file_path}: {e}")
            return False

    @staticmethod
    def get_schematic_metadata(schematic):
        """Extract metadata from schematic"""
        # kicad-skip doesn't expose a direct metadata object on Schematic.
        # We can return basic info like version and generator.
        metadata = {
            "version": schematic.version,
            "generator": schematic.generator,
            # Add other relevant properties if needed
        }
        print("Extracted schematic metadata")
        return metadata

if __name__ == '__main__':
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
