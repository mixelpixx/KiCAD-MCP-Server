#!/usr/bin/env python3
"""
Simple test script for the kicad-skip library functionality
This test doesn't depend on KiCAD's Python modules like pcbnew.
"""

import sys
import os
import traceback

def main():
    """Test basic kicad-skip functionality"""
    print("=== Testing kicad-skip schematic functionality ===")
    
    # Set up test output directory
    test_dir = os.path.join(os.path.dirname(__file__), 'schematic_test_output')
    if not os.path.exists(test_dir):
        os.makedirs(test_dir)
        
    print("Test directory:", test_dir)
    
    try:
        # Import skip module
        print("Importing skip module...")
        from skip import Schematic
        print("Successfully imported skip module")
        
        # Create a new schematic
        print("Creating new schematic...")
        sch = Schematic()
        sch.version = "20230121"
        sch.generator = "KiCAD-MCP-Server-Test"
        print("Created schematic object with version:", sch.version)
        
        # Add resistor component
        print("Adding resistor component...")
        resistor = sch.add_symbol(
            lib="Device",
            name="R",
            reference="R1",
            at=[100, 100],
            unit=1
        )
        resistor.property.Value.value = "10k"
        print("Added resistor:", resistor.reference, resistor.property.Value.value)
        
        # Add capacitor component
        print("Adding capacitor component...")
        capacitor = sch.add_symbol(
            lib="Device",
            name="C",
            reference="C1",
            at=[200, 100],
            unit=1
        )
        capacitor.property.Value.value = "0.1uF"
        print("Added capacitor:", capacitor.reference, capacitor.property.Value.value)
        
        # Add wire connection
        print("Adding wire connection...")
        wire = sch.add_wire(start=[100, 150], end=[200, 150])
        print("Added wire from", wire.start, "to", wire.end)
        
        # Save the schematic
        schematic_path = os.path.join(test_dir, "skip_test.kicad_sch")
        print(f"Saving schematic to: {schematic_path}")
        sch.save(schematic_path)
        print(f"Schematic saved to: {schematic_path}")
        
        # Verify the file exists
        if os.path.exists(schematic_path):
            print(f"SUCCESS: Schematic file created at: {schematic_path}")
            print(f"File size: {os.path.getsize(schematic_path)} bytes")
        else:
            print(f"ERROR: Failed to create schematic file at: {schematic_path}")
            
    except ImportError as e:
        print(f"ERROR: Failed to import required modules: {e}")
        traceback.print_exc()
    except Exception as e:
        print(f"ERROR: An unexpected error occurred: {e}")
        traceback.print_exc()
    
    print("=== Test completed ===")

if __name__ == "__main__":
    main()
