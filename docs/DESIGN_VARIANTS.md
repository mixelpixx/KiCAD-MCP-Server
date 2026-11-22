# KiCad 10 design variants

These tools work on saved project and schematic files. Save and close the schematic editor before editing through MCP, then reopen it to see the changes. A variant inherits the base schematic: creating an empty one does not copy the sheet, change component values, or mark any parts DNP.

| Tool                    | Purpose                                                                                                                                                                                                                 |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `list_variants`         | Read named variants registered in the `.kicad_pro` and their descriptions. The implicit default design is not listed.                                                                                                   |
| `create_variant`        | Register a new name in `schematic.variants`, optionally with a description.                                                                                                                                             |
| `get_component_variant` | Inspect one reference in one named variant on a specified sheet.                                                                                                                                                        |
| `set_component_variant` | Change that reference's DNP status or fields without modifying the base component. Pass `null` as a field value to remove its override, or `reset: true` alone to remove the entire variant override for the reference. |
| `export_variant_bom`    | Use KiCad's CLI to export the named variant from the project's root schematic to a CSV. Pass `excludeDnp: true` to omit unpopulated parts.                                                                              |

## Example: a build without C9

Call `create_variant`:

```json
{ "projectPath": "C:/design/board.kicad_pro", "name": "Lite", "description": "C9 not fitted" }
```

Call `set_component_variant` (for a child sheet, use the actual child `.kicad_sch` in `schematicPath`):

```json
{
  "projectPath": "C:/design/board.kicad_pro",
  "schematicPath": "C:/design/board.kicad_sch",
  "variant": "Lite",
  "reference": "C9",
  "dnp": true
}
```

Call `export_variant_bom`:

```json
{
  "projectPath": "C:/design/board.kicad_pro",
  "variant": "Lite",
  "outputPath": "C:/design/Lite.csv",
  "excludeDnp": true
}
```

To fit a different value instead, use `dnp: false` and `fields: {"Value": "220n"}`. Read back the reference with `get_component_variant` using the same project, sheet, variant and reference.

## Scope

This is schematic-side support. It does not switch the active variant in an open editor, modify `.kicad_pcb` footprints, or produce variant-specific placement files or Gerbers. For board-side work, synchronize from the schematic in KiCad and verify PCB outputs separately. Existing schematics with older file formats should be resaved in KiCad 10 before editing component overrides.
