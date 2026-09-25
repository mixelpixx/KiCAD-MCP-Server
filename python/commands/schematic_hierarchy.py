"""
Schematic hierarchical-sheet commands.

Tools:
  - add_hierarchical_sheet:       insert a hierarchical-sheet reference into a parent schematic
  - remove_hierarchical_sheet:    remove a hierarchical-sheet reference (reverse of add)
  - create_hierarchical_subsheet: create a sub-sheet file and link it in one call

The command class holds a back-reference to KiCADInterface so it can reuse the existing
create_schematic handler. fix_subsheet_instances gives the symbols of a newly linked sheet
their instance entries (utils.symbol_instances).
"""

import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List

from utils.sexpr_format import QUOTED_VALUE, escape_sexpr_string, unescape_sexpr_string
from utils.sheet_tree import instance_paths, project_name, sheet_tree, sub_sheets
from utils.symbol_instances import add_missing_instances

logger = logging.getLogger("kicad_interface")


class SchematicHierarchyCommands:
    """Handlers for hierarchical sheet insertion and subsheet scaffolding."""

    def __init__(self, iface):
        self.iface = iface

    def add_hierarchical_sheet(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a hierarchical sheet reference block into a parent schematic."""
        logger.info("Adding hierarchical sheet")
        try:
            schematic_path = params.get("schematicPath")
            subsheet_path = params.get("subsheetPath")
            sheet_name = params.get("sheetName", "Sheet")
            position = params.get("position", {})
            size = params.get("size", {})

            if not schematic_path or not subsheet_path:
                return {"success": False, "message": "schematicPath and subsheetPath are required"}

            x = float(position.get("x", 50))
            y = float(position.get("y", 50))
            w = float(size.get("width", 80))
            h = float(size.get("height", 50))

            parent_file = Path(schematic_path)
            try:
                rel_str = str(
                    Path(subsheet_path).resolve().relative_to(parent_file.parent.resolve())
                ).replace("\\", "/")
            except ValueError:
                rel_str = str(subsheet_path).replace("\\", "/")

            sheet_block_uuid = str(uuid.uuid4())
            name_x, name_y = round(x + 2.54, 4), round(y - 1.27, 4)
            file_x, file_y = round(x + 2.54, 4), round(y + h + 1.27, 4)

            # KiCad files a sheet's page number inside its (sheet ...) block,
            # once per use of the parent: (instances (project "<name>"
            # (path "/<chain to the parent>" (page "N")))). The root's
            # (sheet_instances ...) holds only (path "/" (page "1")).
            root, parent_paths = instance_paths(parent_file)
            project = project_name(parent_file)
            page_files = sheet_tree(root) if root is not None else [parent_file]
            used_pages = [1]
            for sheet in page_files:
                try:
                    text = Path(sheet).read_text(encoding="utf-8")
                except OSError:
                    continue
                used_pages += [int(p) for p in re.findall(r'\(page\s+"(\d+)"\)', text)]
            next_page = max(used_pages) + 1
            pages = list(range(next_page, next_page + len(parent_paths)))
            instance_entries = "".join(
                f'        (path "{path}" (page "{page}"))\n'
                for path, page in zip(parent_paths, pages)
            )

            sheet_block = (
                f"  (sheet (at {x} {y}) (size {w} {h}) (fields_autoplaced yes)\n"
                f"    (stroke (width 0.0006) (type default))\n"
                f"    (fill (color 0 0 0 0.0000))\n"
                f'    (uuid "{sheet_block_uuid}")\n'
                f'    (property "Sheetname" "{escape_sexpr_string(sheet_name)}"'
                f" (at {name_x} {name_y} 0)\n"
                f"      (effects (font (size 1.27 1.27)) (justify left bottom))\n"
                f"    )\n"
                f'    (property "Sheetfile" "{escape_sexpr_string(rel_str)}"'
                f" (at {file_x} {file_y} 0)\n"
                f"      (effects (font (size 1.27 1.27)) (justify left top))\n"
                f"    )\n"
                f"    (instances\n"
                f'      (project "{escape_sexpr_string(project)}"\n'
                f"{instance_entries}"
                f"      )\n"
                f"    )\n"
                f"  )\n"
            )

            content = parent_file.read_text(encoding="utf-8")

            insert_at = content.rfind("(sheet_instances")
            if insert_at == -1:
                # A sub-sheet written without (sheet_instances ...): insert
                # before the file's closing parenthesis.
                insert_at = content.rstrip().rfind(")")
                if insert_at <= 0:
                    return {"success": False, "message": "Could not parse schematic"}
                line_start = content.rfind("\n", 0, insert_at) + 1
                if content[line_start:insert_at].strip():
                    content = content[:insert_at] + "\n" + sheet_block + content[insert_at:]
                else:
                    content = content[:line_start] + sheet_block + content[line_start:]
            else:
                # rfind returns a raw character offset; on files where
                # (sheet_instances does not start its own line (sexpdata-written
                # schematics keep several forms on one line) splicing there lands
                # the sheet block mid-line, where line-based consumers like
                # add_sheet_pin can never find it (#298). Snap to a line boundary.
                line_start = content.rfind("\n", 0, insert_at) + 1
                if content[line_start:insert_at].strip():
                    # (sheet_instances shares its line with earlier content:
                    # break the line so the sheet block and (sheet_instances each
                    # start a line of their own.
                    content = content[:insert_at] + "\n" + sheet_block + "  " + content[insert_at:]
                else:
                    # (sheet_instances starts its line: insert the block at the
                    # line start so (sheet_instances keeps its own indentation.
                    content = content[:line_start] + sheet_block + content[line_start:]

            parent_file.write_text(content, encoding="utf-8")

            # Ensure each sub-sheet component has the hierarchical instance entry.
            self.fix_subsheet_instances(str(parent_file), content)

            return {
                "success": True,
                "sheet_uuid": sheet_block_uuid,
                "sheet_name": sheet_name,
                "subsheet_path": rel_str,
                "page": pages[0],
                "pages": pages,
            }

        except Exception as e:
            logger.error(f"Error adding hierarchical sheet: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    @staticmethod
    def _find_sheet_blocks(content: str) -> List[tuple]:
        """Return (start, end) spans of every top-level (sheet ...) block.

        Matches '(sheet ' (with whitespace) so it never catches '(sheet_instances'.
        """
        spans: List[tuple] = []
        for m in re.finditer(r"\(sheet\s", content):
            start = m.start()
            depth = 0
            for i in range(start, len(content)):
                if content[i] == "(":
                    depth += 1
                elif content[i] == ")":
                    depth -= 1
                    if depth == 0:
                        spans.append((start, i + 1))
                        break
        return spans

    def remove_hierarchical_sheet(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Remove a hierarchical-sheet reference from a parent schematic.

        Identify the sheet by sheetName (matches the 'Sheetname' property, or
        the 'Sheet name' spelling older MCP builds wrote) or by subsheetPath
        (matches the 'Sheetfile'/'Sheet file' property basename). Removes the
        (sheet ...) block, which carries the sheet's page entries in its
        nested (instances ...), plus any (path .../<uuid>) entry older MCP
        builds put in (sheet_instances). The reverse of add_hierarchical_sheet.
        Does NOT delete the sub-sheet file on disk.
        """
        logger.info("Removing hierarchical sheet")
        try:
            schematic_path = params.get("schematicPath")
            sheet_name = params.get("sheetName")
            subsheet_path = params.get("subsheetPath")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not sheet_name and not subsheet_path:
                return {
                    "success": False,
                    "message": "provide sheetName or subsheetPath to identify the sheet to remove",
                }

            parent_file = Path(schematic_path)
            content = parent_file.read_text(encoding="utf-8")
            target_base = Path(subsheet_path).name if subsheet_path else None

            match = None
            for start, end in self._find_sheet_blocks(content):
                block = content[start:end]
                # Compare against the ESCAPED form: that is what is on disk, so
                # a sheet named `Foo "Bar"` must still be findable by its plain
                # name. Both forms are checked because sheets written before
                # escaping landed still hold the raw text.
                escaped_name = escape_sexpr_string(sheet_name) if sheet_name else None
                if sheet_name and (
                    f'"Sheetname" "{escaped_name}"' in block
                    or f'"Sheet name" "{escaped_name}"' in block
                    or f'"Sheetname" "{sheet_name}"' in block
                    or f'"Sheet name" "{sheet_name}"' in block
                ):
                    match = (start, end, block)
                    break
                if (
                    target_base
                    and f'"{target_base}"' in block
                    and ("Sheetfile" in block or "Sheet file" in block)
                ):
                    match = (start, end, block)
                    break

            if not match:
                ident = sheet_name or target_base
                return {
                    "success": False,
                    "message": f"no (sheet ...) block matching '{ident}' found in {parent_file.name}",
                }

            start, end, block = match
            uuid_match = re.search(r'\(uuid\s+"?([0-9a-fA-F-]+)"?\)', block)
            sheet_uuid = uuid_match.group(1) if uuid_match else None

            # Drop the (sheet ...) block plus the blank line it leaves behind.
            new_content = content[:start] + content[end:]
            new_content = re.sub(r"\n[ \t]*\n[ \t]*\n", "\n\n", new_content)

            removed_instance = "(instances" in block
            if sheet_uuid:
                new_content, n = re.subn(
                    r'[ \t]*\(path\s+"[^"]*'
                    + re.escape(sheet_uuid)
                    + r'[^"]*"\s+\(page\s+"[^"]*"\)\)[ \t]*\n?',
                    "",
                    new_content,
                )
                removed_instance = removed_instance or n > 0

            parent_file.write_text(new_content, encoding="utf-8")

            return {
                "success": True,
                "removed_sheet": sheet_name or target_base,
                "sheet_uuid": sheet_uuid,
                "removed_instance_path": removed_instance,
                "message": (f"Removed sheet '{sheet_name or target_base}' from {parent_file.name}"),
            }

        except Exception as e:
            logger.error(f"Error removing hierarchical sheet: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def create_hierarchical_subsheet(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new sub-sheet file and link it into a parent schematic in one call."""
        logger.info("Creating hierarchical subsheet")
        try:
            parent_path = params.get("parentSchematicPath")
            subsheet_path = params.get("subsheetPath")
            sheet_name = params.get("sheetName", "Sheet")
            position = params.get("position", {})
            size = params.get("size", {})
            metadata = params.get("metadata", {})

            if not parent_path or not subsheet_path:
                return {
                    "success": False,
                    "message": "parentSchematicPath and subsheetPath are required",
                }

            create_result = self.iface._handle_create_schematic(
                {"filename": subsheet_path, "metadata": metadata}
            )
            if not create_result.get("success"):
                return {
                    "success": False,
                    "message": f"Failed to create sub-sheet: {create_result.get('message')}",
                }

            link_result = self.add_hierarchical_sheet(
                {
                    "schematicPath": parent_path,
                    "subsheetPath": subsheet_path,
                    "sheetName": sheet_name,
                    "position": position,
                    "size": size,
                }
            )
            if not link_result.get("success"):
                return {
                    "success": False,
                    "message": f"Created sub-sheet but failed to link: {link_result.get('message')}",
                    "subsheet_created": create_result.get("file_path", subsheet_path),
                }

            return {
                "success": True,
                "subsheet_path": create_result.get("file_path", subsheet_path),
                "subsheet_uuid": create_result.get("schematic_uuid"),
                "sheet_block_uuid": link_result.get("sheet_uuid"),
                "sheet_name": sheet_name,
                "page": link_result.get("page"),
                "message": (
                    f"Created sub-sheet '{sheet_name}' at {subsheet_path} "
                    f"and linked it into {parent_path} (page {link_result.get('page')})"
                ),
            }
        except Exception as e:
            logger.error(f"Error in create_hierarchical_subsheet: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    _BUILTIN_SHEET_PROPERTIES = ("Sheet name", "Sheetname", "Sheet file", "Sheetfile")

    @staticmethod
    def _escape_sexpr_string(value: str) -> str:
        """Escape a string for a double-quoted s-expression token."""
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _match_sheet_block(self, content, sheet_name, subsheet_path):
        """Find the (sheet ...) block identified by sheetName or subsheetPath.

        Matching mirrors remove_hierarchical_sheet: sheetName against the
        'Sheetname' property KiCad writes (or the 'Sheet name' spelling older
        MCP builds wrote), subsheetPath by 'Sheetfile'/'Sheet file' basename.
        Returns (start, end) or None.
        """
        target_base = Path(subsheet_path).name if subsheet_path else None
        for start, end in self._find_sheet_blocks(content):
            block = content[start:end]
            if sheet_name and (
                f'"Sheetname" "{sheet_name}"' in block or f'"Sheet name" "{sheet_name}"' in block
            ):
                return start, end
            if (
                target_base
                and f'"{target_base}"' in block
                and ("Sheetfile" in block or "Sheet file" in block)
            ):
                return start, end
        return None

    def set_sheet_property(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add or update a custom property on a hierarchical sheet.

        Text-surgery insertion into the (sheet ...) block, preserving the
        file's formatting. The property is created (hidden by default) if it
        does not exist, otherwise its value is updated in place. The built-in
        "Sheetname"/"Sheetfile" properties cannot be set here — use
        add/remove_hierarchical_sheet to manage the sheet link itself.
        """
        logger.info("Setting hierarchical sheet property")
        try:
            schematic_path = params.get("schematicPath")
            sheet_name = params.get("sheetName")
            subsheet_path = params.get("sheetPath") or params.get("subsheetPath")
            key = params.get("key")
            value = params.get("value")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not sheet_name and not subsheet_path:
                return {
                    "success": False,
                    "message": "provide sheetName or sheetPath to identify the sheet",
                }
            if not isinstance(key, str) or not key:
                return {"success": False, "message": "key is required"}
            if value is None:
                return {"success": False, "message": "value is required"}
            if key in self._BUILTIN_SHEET_PROPERTIES:
                return {
                    "success": False,
                    "message": (
                        f"'{key}' is a built-in sheet property; use "
                        "add_hierarchical_sheet / remove_hierarchical_sheet to "
                        "manage the sheet link"
                    ),
                }

            parent_file = Path(schematic_path)
            if not parent_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }
            content = parent_file.read_text(encoding="utf-8")

            match = self._match_sheet_block(content, sheet_name, subsheet_path)
            if match is None:
                ident = sheet_name or Path(subsheet_path).name
                return {
                    "success": False,
                    "message": f"no (sheet ...) block matching '{ident}' found in {parent_file.name}",
                }
            start, end = match
            block = content[start:end]

            value_str = str(value)
            escaped_key = re.escape(key)
            escaped_value = self._escape_sexpr_string(value_str)
            existing = re.search(
                r'(\(property\s+"' + escaped_key + r'"\s+")((?:[^"\\]|\\.)*)(")',
                block,
            )
            if existing:
                new_block = block[: existing.start(2)] + escaped_value + block[existing.end(2) :]
                created = False
            else:
                # Anchor the new property at the sheet origin; created hidden
                # (it is metadata, not display text).
                at_match = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)", block)
                x = float(at_match.group(1)) if at_match else 0.0
                y = float(at_match.group(2)) if at_match else 0.0
                property_block = (
                    f'    (property "{self._escape_sexpr_string(key)}" "{escaped_value}" '
                    f"(at {x} {y} 0)\n"
                    f"      (effects (font (size 1.27 1.27)) (hide yes))\n"
                    f"    )\n  "
                )
                # Insert before the block's closing paren, after any trailing
                # whitespace, keeping the original bytes otherwise intact.
                insert_at = len(block) - 1
                while insert_at > 0 and block[insert_at - 1] in (" ", "\t", "\n"):
                    insert_at -= 1
                new_block = (
                    block[:insert_at] + "\n" + property_block + block[insert_at:].lstrip(" \t")
                )
                created = True

            parent_file.write_text(content[:start] + new_block + content[end:], encoding="utf-8")
            return {
                "success": True,
                "key": key,
                "value": value_str,
                "created": created,
                "message": (
                    f"{'Created' if created else 'Updated'} sheet property "
                    f"'{key}' on sheet "
                    f"'{sheet_name or Path(subsheet_path).name}'"
                ),
            }
        except Exception as e:
            logger.error(f"Error setting sheet property: {e}")
            return {"success": False, "message": str(e)}

    def get_sheet_properties(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List hierarchical sheets and their properties.

        With sheetName/sheetPath, returns that sheet only; otherwise every
        sheet in the schematic. Each entry carries name, file, uuid,
        position, and the full property map (built-ins included).
        """
        logger.info("Getting hierarchical sheet properties")
        try:
            schematic_path = params.get("schematicPath")
            sheet_name = params.get("sheetName")
            subsheet_path = params.get("sheetPath") or params.get("subsheetPath")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            parent_file = Path(schematic_path)
            if not parent_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }
            content = parent_file.read_text(encoding="utf-8")

            spans = self._find_sheet_blocks(content)
            if sheet_name or subsheet_path:
                match = self._match_sheet_block(content, sheet_name, subsheet_path)
                if match is None:
                    ident = sheet_name or Path(subsheet_path).name
                    return {
                        "success": False,
                        "message": f"no (sheet ...) block matching '{ident}' found in {parent_file.name}",
                    }
                spans = [match]

            sheets = []
            for start, end in spans:
                block = content[start:end]
                properties: Dict[str, str] = {}
                for m in re.finditer(
                    r"\(property\s+" + QUOTED_VALUE + r"\s+" + QUOTED_VALUE, block
                ):
                    properties[unescape_sexpr_string(m.group(1))] = unescape_sexpr_string(
                        m.group(2)
                    )
                uuid_match = re.search(r'\(uuid\s+"?([0-9a-fA-F-]+)"?\)', block)
                at_match = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)", block)
                sheets.append(
                    {
                        "name": properties.get("Sheet name") or properties.get("Sheetname"),
                        "file": properties.get("Sheet file") or properties.get("Sheetfile"),
                        "uuid": uuid_match.group(1) if uuid_match else None,
                        "position": {
                            "x": float(at_match.group(1)) if at_match else None,
                            "y": float(at_match.group(2)) if at_match else None,
                        },
                        "properties": properties,
                    }
                )
            return {"success": True, "sheets": sheets, "count": len(sheets)}
        except Exception as e:
            logger.error(f"Error getting sheet properties: {e}")
            return {"success": False, "message": str(e)}

    def fix_subsheet_instances(self, parent_path: str, parent_content: str) -> List[str]:
        """Give every symbol on the parent's sub-sheets an instance entry per use.

        Runs after add_hierarchical_sheet links a sheet. Every placed symbol
        needs one ``(path ...)`` entry for each use of its sheet, and the path
        starts at the root: ``/<root>/<block>``
        for a sheet on the root, ``/<root>/<block>/<block>`` one level down.
        Sheets below the linked one are covered too, since linking a sheet adds
        a use to everything under it.

        This used to build ``/<parent>/<block>`` from the parent alone, which is
        wrong below level 2. It matched only the ``Sheet file`` spelling, not
        the ``Sheetfile`` KiCad writes, and it read the parent's uuid only when
        unquoted. It also copied the existing reference into a second use of a
        sheet, and left the sheets below the linked one alone (#428).

        Returns the paths of the files rewritten.
        """
        try:
            parent = Path(parent_path)
            sheets: List[Path] = []
            seen = set()
            for _block_uuid, name in sub_sheets(parent_content):
                child = parent.parent / name
                if not child.is_file():
                    logger.warning(f"Sub-sheet not found: {child}")
                    continue
                for sheet in sheet_tree(child):
                    key = str(sheet.resolve())
                    if key not in seen:
                        seen.add(key)
                        sheets.append(sheet)
            modified = add_missing_instances(sheets)
            for path in modified:
                logger.info(f"Added hierarchical instance entries in {path}")
            return modified
        except Exception as e:
            logger.error(f"Error fixing sub-sheet instances: {e}")
            return []
