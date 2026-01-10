# Schematic Workflow Fix - Issue #26

## Problem Summary

The schematic workflow was completely broken due to incorrect usage of the kicad-skip library:

1. **`create_project`** only created PCB files, no schematic
2. **`create_schematic`** created orphaned schematic files not linked to projects
3. **`add_schematic_component`** called non-existent `schematic.add_symbol()` method
4. Project files didn't reference schematics in their structure

## Root Cause

The kicad-skip library **does not support creating symbols from scratch**. The only way to add symbols is by **cloning existing symbol instances**.

From kicad-skip documentation:
> "symbols: these don't have a new()" because they require complex mappings to library elements, pins, and properties.

## Solution

### 1. Template-Based Approach

Created a template schematic (`python/templates/template_with_symbols.kicad_sch`) with:
- Complete `lib_symbols` section defining R, C, LED symbols
- Three template symbol instances placed off-screen at (-100, -110, -120)
- Template symbols marked as `dnp yes`, `in_bom no`, `on_board no` so they don't interfere

### 2. Updated Files

**python/commands/project.py:**
- Now creates both `.kicad_pcb` AND `.kicad_sch` files
- Project file includes schematic reference in `sheets` array
- Copies template schematic with cloneable symbols

**python/commands/schematic.py:**
- Uses template file instead of creating from scratch
- Proper minimal schematic structure when template unavailable

**python/commands/component_schematic.py:**
- Completely rewritten to use `clone()` API
- Maps component types to template symbols
- Proper UUID generation for each cloned symbol
- Correct position setting: `symbol.at.value = [x, y, rotation]`

### 3. Correct Workflow

```python
from commands.project import ProjectCommands
from commands.schematic import SchematicManager
from commands.component_schematic import ComponentManager

# Step 1: Create project (creates both PCB and schematic)
project_cmd = ProjectCommands()
result = project_cmd.create_project({
    "name": "MyProject",
    "path": "/path/to/project"
})

# Step 2: Load the schematic
sch = SchematicManager.load_schematic(result['project']['schematicPath'])

# Step 3: Add components by cloning templates
component_def = {
    "type": "R",           # Maps to _TEMPLATE_R
    "reference": "R1",     # Component reference
    "value": "10k",        # Component value
    "footprint": "Resistor_SMD:R_0603_1608Metric",
    "x": 50.8,            # Position in mm
    "y": 50.8,            # Position in mm
    "rotation": 0         # Rotation in degrees
}
symbol = ComponentManager.add_component(sch, component_def)

# Step 4: Save the schematic
SchematicManager.save_schematic(sch, result['project']['schematicPath'])
```

## Supported Component Types

Currently supported template symbols:
- `R` - Resistor (maps to `_TEMPLATE_R`)
- `C` - Capacitor (maps to `_TEMPLATE_C`)
- `D` or `LED` - LED (maps to `_TEMPLATE_D`)

To add more component types, update:
1. `python/templates/template_with_symbols.kicad_sch` - Add lib_symbol definition and template instance
2. `python/commands/component_schematic.py` - Add mapping in `TEMPLATE_MAP`

## Testing

Comprehensive test created at `/tmp/test_schematic_workflow.py`:
- Creates project with schematic
- Loads schematic
- Adds R, C, LED components
- Saves schematic
- Validates with `kicad-cli sch export pdf`

All tests passing ✓

## Files Modified

- `python/commands/project.py` - Added schematic creation
- `python/commands/schematic.py` - Fixed template usage
- `python/commands/component_schematic.py` - Rewritten to use clone() API
- `python/templates/empty.kicad_sch` - Minimal template (created)
- `python/templates/template_with_symbols.kicad_sch` - Template with cloneable symbols (created)

## Limitations

1. Can only add components that have templates defined
2. Template symbols remain in schematic (but marked as DNP/not in BOM)
3. Complex symbols (multi-unit, hierarchical) may need custom templates

## Future Improvements

1. Add more component templates (transistors, connectors, ICs)
2. Dynamic template generation from KiCad symbol libraries
3. Auto-hide template symbols in schematic
4. Support for custom user templates

## References

- GitHub Issue: #26
- kicad-skip documentation: https://github.com/psychogenic/kicad-skip
- Test results: `/tmp/test_schematic_workflow/`
