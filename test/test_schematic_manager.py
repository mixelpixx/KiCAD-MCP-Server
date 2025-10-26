#!/usr/bin/env python3
"""
Test script for the schematic manager implementation using KiCAD python
"""

import sys
import os
import traceback

# Add the parent directory to the module search path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def main():
    """Test the SchematicManager functions"""
    print("=== Testing SchematicManager functionality ===")
    
    try:
        # Set up test output directory
        test_dir = os.path.join(os.path.dirname(__file__), 'schematic_test_output')
        if not os.path.exists(test_dir):
            os.makedirs(test_dir)
            
        print("Test directory:", test_dir)
        
        # Import our SchematicManager
        print("Importing SchematicManager...")
        from python.commands.schematic import SchematicManager
        print("Successfully imported SchematicManager")
        
        # Create a new schematic
        print("\nCreating new schematic...")
        schematic_name = "TestSchemManager"
        metadata = {
            "description": "Test schematic",
            "author": "Test script"
        }
        sch = SchematicManager.create_schematic(schematic_name, metadata)
        print("Successfully created schematic object")
        
        # Save the schematic
        schematic_path = os.path.join(test_dir, f"{schematic_name}.kicad_sch")
        print(f"\nSaving schematic to: {schematic_path}")
        success = SchematicManager.save_schematic(sch, schematic_path)
        
        if success:
            print(f"Successfully saved schematic to: {schematic_path}")
        else:
            print("Failed to save schematic")
            return
            
        # Load the schematic
        print("\nLoading schematic from file...")
        loaded_sch = SchematicManager.load_schematic(schematic_path)
        
        if loaded_sch:
            print("Successfully loaded schematic")
            
            # Get metadata
            print("\nGetting schematic metadata...")
            metadata = SchematicManager.get_schematic_metadata(loaded_sch)
            print(f"Metadata: {metadata}")
        else:
            print("Failed to load schematic")
            
        # Verify the file exists
        if os.path.exists(schematic_path):
            print(f"\nSCHEMATIC TEST SUCCESSFUL: File created at: {schematic_path}")
            print(f"File size: {os.path.getsize(schematic_path)} bytes")
        else:
            print(f"\nERROR: File not found at: {schematic_path}")
        
    except ImportError as e:
        print(f"ERROR: Failed to import required modules: {e}")
        traceback.print_exc()
    except Exception as e:
        print(f"ERROR: An unexpected error occurred: {e}")
        traceback.print_exc()
        
    print("\n=== Test completed ===")

if __name__ == "__main__":
    main()
