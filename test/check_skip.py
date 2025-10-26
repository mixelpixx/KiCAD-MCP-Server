#!/usr/bin/env python3
"""
Simple script to check if the skip module is available
"""

import sys
import traceback

print("Python executable:", sys.executable)
print("Python version:", sys.version)

try:
    print("Attempting to import skip module...")
    import skip
    print("Successfully imported skip module!")
    print("Skip module version:", getattr(skip, "__version__", "Unknown"))
    print("Skip module path:", skip.__file__)
    
    # Check if Schematic class is available
    print("\nChecking for Schematic class...")
    if hasattr(skip, "Schematic"):
        print("Schematic class is available!")
        
        # Create a schematic object
        print("Creating schematic object...")
        sch = skip.Schematic()
        print("Successfully created schematic object!")
        
        # Check for methods and attributes we use
        print("\nChecking schematic methods/attributes:")
        print("- add_symbol method:", hasattr(sch, "add_symbol"))
        print("- add_wire method:", hasattr(sch, "add_wire"))
        print("- save method:", hasattr(sch, "save"))
        print("- version attribute:", hasattr(sch, "version"))
        
    else:
        print("ERROR: Schematic class is NOT available in the skip module!")
        
    # List all available classes/functions in the skip module
    print("\nAvailable members in skip module:")
    for name in dir(skip):
        if not name.startswith("_"):  # Skip private/internal items
            print(f"- {name}")
            
except ImportError as e:
    print(f"ERROR: Failed to import skip module: {e}")
    traceback.print_exc()
except Exception as e:
    print(f"ERROR: An unexpected error occurred: {e}")
    traceback.print_exc()
