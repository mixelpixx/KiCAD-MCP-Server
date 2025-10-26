#!/usr/bin/env python3
"""
Debug test script for the schematic manager implementation
"""

import sys
import os
import traceback

# Add the parent directory to the module search path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def main():
    """Test the SchematicManager functions with detailed debug output"""
    print("=== DEBUGGING SchematicManager functionality ===")
    
    # Set up test output directory
    test_dir = os.path.join(os.path.dirname(__file__), 'schematic_test_output')
    if not os.path.exists(test_dir):
        os.makedirs(test_dir)
        
    print("Test directory:", test_dir)
    
    try:
        # Import directly from skip for comparison
        print("Importing skip module...")
        from skip import Schematic
        print("Successfully imported skip module")
        
        # Create a template file directly
        template_path = os.path.join(test_dir, "debug_template.kicad_sch")
        print(f"Creating template file at: {template_path}")
        with open(template_path, 'w') as f:
            f.write("(kicad_sch (version 20230121) (generator \"KiCAD-MCP-Server-Debug\"))\n")
        
        print(f"Template file created, size: {os.path.getsize(template_path)} bytes")
        
        # Load the template with skip directly
        print("Loading template with skip.Schematic...")
        try:
            sch = Schematic(template_path)
            print("Successfully loaded template")
            
            # Save directly
            output_path = os.path.join(test_dir, "direct_save.kicad_sch")
            print(f"Saving with skip.Schematic.save() to: {output_path}")
            sch.save(output_path)
            
            if os.path.exists(output_path):
                print(f"Direct save successful, file size: {os.path.getsize(output_path)} bytes")
            else:
                print("Direct save failed, no file created")
        except Exception as e:
            print(f"Error using skip directly: {e}")
            traceback.print_exc()
            
        print("\n--- Now testing SchematicManager ---\n")
    
        # Import our SchematicManager
        print("Importing SchematicManager...")
        from python.commands.schematic import SchematicManager
        print("Successfully imported SchematicManager")
        
        # Create a new schematic
        print("\nCreating new schematic with SchematicManager...")
        schematic_name = "TestDebugManager"
        metadata = {
            "description": "Debug test schematic",
            "author": "Debug script"
        }
        
        try:
            sch = SchematicManager.create_schematic(schematic_name, metadata)
            print("Successfully created schematic object")
            
            # Print schematic properties
            print("Schematic properties:")
            print(f"  Version: {sch.version}")
            print(f"  Generator: {sch.generator}")
            
            # Save the schematic
            schematic_path = os.path.join(test_dir, f"{schematic_name}.kicad_sch")
            print(f"\nSaving schematic to: {schematic_path}")
            
            try:
                success = SchematicManager.save_schematic(sch, schematic_path)
                
                if success:
                    print(f"Successfully saved schematic to: {schematic_path}")
                    print(f"File size: {os.path.getsize(schematic_path)} bytes")
                else:
                    print("SchematicManager.save_schematic returned False")
            except Exception as e:
                print(f"Error in save_schematic: {e}")
                traceback.print_exc()
                
        except Exception as e:
            print(f"Error in create_schematic: {e}")
            traceback.print_exc()
            
    except ImportError as e:
        print(f"ERROR: Failed to import required modules: {e}")
        traceback.print_exc()
    except Exception as e:
        print(f"ERROR: An unexpected error occurred: {e}")
        traceback.print_exc()
        
    print("\n=== Debug test completed ===")

if __name__ == "__main__":
    main()
