# KiCAD MCP Tool Inventory

- **Version:** 2.7.0
- **Total first-class MCP tools at the migration baseline:** 219
- **Last verified:** 2026-08-11

The live `tools/list` result is authoritative. Every capability is registered
as an individual MCP tool with its own schemas and annotations. The runtime
registry derives the category index from those same registrations.

## Category counts

| Category                    | Source                                                |   Tools |
| --------------------------- | ----------------------------------------------------- | ------: |
| Project lifecycle           | `src/tools/project.ts`                                |      12 |
| Board                       | `src/tools/board.ts`                                  |      19 |
| Components                  | `src/tools/component.ts`                              |      25 |
| Routing                     | `src/tools/routing.ts`                                |      16 |
| Design rules and DRC        | `src/tools/design-rules.ts`                           |       8 |
| Export and manufacturing    | `src/tools/export.ts`                                 |      27 |
| Schematic                   | `src/tools/schematic.ts`                              |      45 |
| Schematic batch operations  | `src/tools/schematic-batch.ts`                        |       9 |
| Schematic hierarchy         | `src/tools/schematic-hierarchy.ts`                    |       5 |
| Schematic layout            | `src/tools/schematic-layout.ts`                       |       5 |
| Libraries                   | `src/tools/library.ts`, `src/tools/library-symbol.ts` |      11 |
| Footprints                  | `src/tools/footprint.ts`                              |       7 |
| Symbols                     | `src/tools/symbol-creator.ts`                         |       8 |
| Datasheets                  | `src/tools/datasheet.ts`                              |       2 |
| JLCPCB                      | `src/tools/jlcpcb-api.ts`                             |       5 |
| Parts registry              | `src/tools/parts-registry.ts`                         |       3 |
| Vendor PCB import           | `src/tools/pcb-import.ts`                             |       1 |
| Freerouting                 | `src/tools/freerouting.ts`                            |       4 |
| EAGLE import                | `src/tools/eagle.ts`                                  |       1 |
| KiCad UI and backend state  | `src/tools/ui.ts`                                     |       3 |
| **KiCad capabilities**      |                                                       | **216** |
| Supplemental discovery      | `src/tools/router.ts`                                 |       3 |
| **Total first-class tools** |                                                       | **219** |

## Recent capability additions

Releases 2.4.1 through 2.6.0 added working net-class assignment, clearance and
layer-constraint checks; parts-registry lookup and download; live JLCPCB part
details; board lifecycle, graphics, geometry, placement-clearance, vendor-PCB
import, board-origin, hierarchical placement and metadata; and schematic
repair, lint, and global-label workflows. See the [changelog](../CHANGELOG.md)
for behavioral details and compatibility notes.

## Discover exact names and schemas

Use the protocol catalog for exact definitions:

1. Call `tools/list` to retrieve every tool and its input/output schemas.
2. Call `list_tool_categories` to see the capability categories.
3. Call `get_category_tools` with a category name to browse it.
4. Call `search_tools` to find matching names and descriptions.
5. Call the selected tool directly by its MCP name.

The three discovery tools are supplemental. There is no `execute_tool` and no
hidden routed tool set.

## Keeping this inventory correct

New tools must use `registerKiCadTool`; this updates the SDK registration and
runtime catalog together. The contract suite verifies that `tools/list` is
deterministic, contains no duplicate names, and matches the registry. Python
route-parity tests verify that every TypeScript backend command is implemented.
