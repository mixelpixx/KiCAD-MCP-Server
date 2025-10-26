#!/usr/bin/env python3
"""
Manual test script for the schematic functionality
"""

import sys
import os

# Add the parent directory to the module search path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import our schematic modules
from python.commands.schematic import SchematicManager
from python.commands.component_schematic import ComponentManager
from python.commands.connection_schematic import ConnectionManager

def main():
    """Run a basic test of schematic functionality"""
    print("=== Starting manual schematic test ===")
    
    # Set up test output directory
    test_dir = os.path.join(os.path.dirname(__file__), 'schematic_test_output')
    if not os.path.exists(test_dir):
        os.makedirs(test_dir)
    
    # 1. Create a new schematic
    schematic_name = "TestCircuitManual"
    schematic_path = os.path.join(test_dir, f"{schematic_name}.kicad_sch")
    print(f"Creating schematic: {schematic_name}")
    
    schematic = SchematicManager.create_schematic(schematic_name)
    
    # 2. Add components to the schematic
    print("Adding components to schematic...")
    
    # Add resistor R1
    r1_def = {
        "type": "R",
        "reference": "R1",
        "value": "10k",
        "library": "Device",
        "x": 100,
        "y": 100
    }
    r1 = ComponentManager.add_component(schematic, r1_def)
    
    # Add resistor R2
    r2_def = {
        "type": "R",
        "reference": "R2",
        "value": "4.7k",
        "library": "Device",
        "x": 100,
        "y": 200
    }
    r2 = ComponentManager.add_component(schematic, r2_def)
    
    # Add capacitor C1
    c1_def = {
        "type": "C",
        "reference": "C1",
        "value": "0.1uF",
        "library": "Device",
        "x": 200,
        "y": 150
    }
    c1 = ComponentManager.add_component(schematic, c1_def)
    
    # 3. Add wires to connect components
    print("Adding wires to connect components...")
    
    # Connect R1 to R2
    wire1 = ConnectionManager.add_wire(schematic, [150, 100], [150, 200])
    
    # Connect R2 to C1
    wire2 = ConnectionManager.add_wire(schematic, [150, 200], [200, 200])
    
    # Connect C1 to R1
    wire3 = ConnectionManager.add_wire(schematic, [200, 100], [150, 100])
    
    # 4. Save the schematic
    print(f"Saving schematic to: {schematic_path}")
    success = SchematicManager.save_schematic(schematic, schematic_path)
    
    if success:
        print(f"Successfully saved schematic to: {schematic_path}")
    else:
        print("Failed to save schematic")
    
    print("=== Manual schematic test completed ===")

if __name__ == "__main__":
    main()
