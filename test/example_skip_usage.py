#!/usr/bin/env python3
"""
Example script to inspect and document kicad-skip library capabilities
"""

import sys
import inspect
import os
import traceback

def main():
    """Examine the kicad-skip library functionality"""
    print("=== Examining kicad-skip library ===")
    
    try:
        # Import the module
        print("Importing skip module...")
        import skip
        print(f"Skip module path: {skip.__file__}")
        
        # Display module contents
        print("\nSkip module contents:")
        for item_name in dir(skip):
            if not item_name.startswith('_'):
                try:
                    item = getattr(skip, item_name)
                    if inspect.isclass(item):
                        print(f"  Class: {item_name}")
                        # List methods of the class
                        for method_name in dir(item):
                            if not method_name.startswith('_'):
                                method = getattr(item, method_name)
                                if inspect.ismethod(method) or inspect.isfunction(method):
                                    print(f"    - Method: {method_name}")
                    elif inspect.isfunction(item):
                        print(f"  Function: {item_name}")
                    else:
                        print(f"  Other: {item_name} (type: {type(item).__name__})")
                except Exception as e:
                    print(f"  Error examining {item_name}: {e}")
        
        # Test Schematic class specifically
        print("\nExamining Schematic class:")
        if hasattr(skip, 'Schematic'):
            schematic_class = skip.Schematic
            print(f"Schematic class: {schematic_class}")
            
            # Check initialization parameters
            try:
                sig = inspect.signature(schematic_class.__init__)
                print(f"Schematic.__init__ signature: {sig}")
                
                # List required parameters
                required_params = [
                    name for name, param in sig.parameters.items()
                    if param.default == inspect.Parameter.empty and name != 'self'
                ]
                print(f"Required parameters: {required_params}")
                
                # Display initialization docstring
                print(f"__init__ docstring: {schematic_class.__init__.__doc__}")
            except Exception as e:
                print(f"Error examining Schematic.__init__: {e}")
            
            # Create a simple test file
            test_dir = os.path.dirname(__file__)
            test_file = os.path.join(test_dir, 'test_example.kicad_sch')
            
            with open(test_file, 'w') as f:
                f.write("(kicad_sch (version 20230121) (generator \"Test Example\"))\n")
            
            # Try loading the test file
            print(f"\nLoading test file {test_file}")
            try:
                sch = skip.Schematic(test_file)
                print("Successfully created Schematic object")
                
                # Examine the object's attributes and methods
                print("\nSchematic object attributes:")
                for attr_name in dir(sch):
                    if not attr_name.startswith('_'):
                        try:
                            attr = getattr(sch, attr_name)
                            if callable(attr):
                                print(f"  Method: {attr_name}")
                            else:
                                print(f"  Attribute: {attr_name} = {attr}")
                        except Exception as e:
                            print(f"  Error examining {attr_name}: {e}")
                
                # Check for io-related methods
                print("\nLooking for IO-related methods:")
                for method_name in ['save', 'write', 'to_file', 'export', 'dump']:
                    print(f"  Has '{method_name}' method: {hasattr(sch, method_name)}")
                
                # Examine the representation of the object
                print(f"\nStr representation: {str(sch)}")
                print(f"Repr representation: {repr(sch)}")
                
                # Clean up
                os.remove(test_file)
            except Exception as e:
                print(f"Error testing Schematic: {e}")
                traceback.print_exc()
                
                # Clean up even on error
                if os.path.exists(test_file):
                    os.remove(test_file)
        else:
            print("Schematic class not found in skip module")
        
    except ImportError as e:
        print(f"Failed to import skip module: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        traceback.print_exc()
    
    print("\n=== Examination completed ===")

if __name__ == "__main__":
    main()
