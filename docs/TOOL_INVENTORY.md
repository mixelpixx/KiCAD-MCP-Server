# KiCAD MCP Tool Inventory

- **Version:** 2.7.0
- **Total first-class MCP tools:** 183
- **Last verified:** 2026-08-11

The live `tools/list` result is authoritative. Every capability is registered
as an individual MCP tool with its own schemas and annotations. The runtime
registry derives the category index from those same registrations.

## Category counts

| Category                    | Source                                                |   Tools |
| --------------------------- | ----------------------------------------------------- | ------: |
| Project lifecycle           | `src/tools/project.ts`                                |       6 |
| Board                       | `src/tools/board.ts`                                  |      12 |
| Components                  | `src/tools/component.ts`                              |      16 |
| Routing                     | `src/tools/routing.ts`                                |      16 |
| Design rules and DRC        | `src/tools/design-rules.ts`                           |       5 |
| Export and manufacturing    | `src/tools/export.ts`                                 |      27 |
| Schematic                   | `src/tools/schematic.ts`                              |      43 |
| Schematic batch operations  | `src/tools/schematic-batch.ts`                        |       9 |
| Schematic hierarchy         | `src/tools/schematic-hierarchy.ts`                    |       2 |
| Schematic layout            | `src/tools/schematic-layout.ts`                       |       4 |
| Libraries                   | `src/tools/library.ts`, `src/tools/library-symbol.ts` |      10 |
| Footprints                  | `src/tools/footprint.ts`                              |       7 |
| Symbols                     | `src/tools/symbol-creator.ts`                         |       8 |
| Datasheets                  | `src/tools/datasheet.ts`                              |       2 |
| JLCPCB                      | `src/tools/jlcpcb-api.ts`                             |       5 |
| Freerouting                 | `src/tools/freerouting.ts`                            |       4 |
| EAGLE import                | `src/tools/eagle.ts`                                  |       1 |
| KiCad UI and backend state  | `src/tools/ui.ts`                                     |       3 |
| **KiCad capabilities**      |                                                       | **180** |
| Supplemental discovery      | `src/tools/router.ts`                                 |       3 |
| **Total first-class tools** |                                                       | **183** |

## Discover exact names and schemas

Use the protocol catalog for exact definitions:

1. Call `tools/list` to retrieve every tool and its input/output schemas.
2. Call `list_tool_categories` to see the 18 capability categories.
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
