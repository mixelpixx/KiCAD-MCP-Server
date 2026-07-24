"""
Schematic hierarchical-sheet commands.

Tools:
  - add_hierarchical_sheet:       insert a hierarchical-sheet reference into a parent schematic
  - remove_hierarchical_sheet:    remove a hierarchical-sheet reference (reverse of add)
  - create_hierarchical_subsheet: create a sub-sheet file and link it in one call

The command class holds a back-reference to KiCADInterface so it can reuse the existing
create_schematic handler, and exposes fix_subsheet_instances for the batch module to call.
"""

import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List

import sexpdata
from sexpdata import Symbol

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

            sheet_block = (
                f"  (sheet (at {x} {y}) (size {w} {h}) (fields_autoplaced yes)\n"
                f"    (stroke (width 0.0006) (type default))\n"
                f"    (fill (color 0 0 0 0.0000))\n"
                f'    (uuid "{sheet_block_uuid}")\n'
                f'    (property "Sheet name" "{sheet_name}" (at {name_x} {name_y} 0)\n'
                f"      (effects (font (size 1.27 1.27)) (justify left bottom))\n"
                f"    )\n"
                f'    (property "Sheet file" "{rel_str}" (at {file_x} {file_y} 0)\n'
                f"      (effects (font (size 1.27 1.27)) (justify left bottom))\n"
                f"    )\n"
                f"  )\n"
            )

            content = parent_file.read_text(encoding="utf-8")
            parent_uuid_match = re.search(r"\(uuid\s+([0-9a-fA-F-]+)\)", content)
            parent_uuid = parent_uuid_match.group(1) if parent_uuid_match else ""
            existing_pages = re.findall(r'\(page\s+"(\d+)"\)', content)
            next_page = max((int(p) for p in existing_pages), default=0) + 1

            instance_path = (
                f"/{parent_uuid}/{sheet_block_uuid}" if parent_uuid else f"/{sheet_block_uuid}"
            )
            path_entry = f'    (path "{instance_path}" (page "{next_page}"))\n'

            insert_at = content.rfind("(sheet_instances")
            if insert_at == -1:
                return {"success": False, "message": "Could not find (sheet_instances in schematic"}
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

            si_start = content.rfind("(sheet_instances")
            depth = 0
            si_close = len(content) - 1
            for i in range(si_start, len(content)):
                if content[i] == "(":
                    depth += 1
                elif content[i] == ")":
                    depth -= 1
                    if depth == 0:
                        si_close = i
                        break
            content = content[:si_close] + path_entry + "  " + content[si_close:]

            parent_file.write_text(content, encoding="utf-8")

            # Ensure each sub-sheet component has the hierarchical instance entry.
            self.fix_subsheet_instances(str(parent_file), content)

            return {
                "success": True,
                "sheet_uuid": sheet_block_uuid,
                "sheet_name": sheet_name,
                "subsheet_path": rel_str,
                "page": next_page,
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

        Identify the sheet by sheetName (matches the 'Sheetname'/'Sheet name'
        property) or by subsheetPath (matches the 'Sheetfile'/'Sheet file'
        property basename). Removes the (sheet ...) block and any matching
        (path .../<uuid>) entry in (sheet_instances). The reverse of
        add_hierarchical_sheet. Does NOT delete the sub-sheet file on disk.
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
                if sheet_name and (
                    f'"Sheetname" "{sheet_name}"' in block
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

            removed_instance = False
            if sheet_uuid:
                new_content, n = re.subn(
                    r'[ \t]*\(path\s+"[^"]*'
                    + re.escape(sheet_uuid)
                    + r'[^"]*"\s+\(page\s+"[^"]*"\)\)[ \t]*\n?',
                    "",
                    new_content,
                )
                removed_instance = n > 0

            parent_file.write_text(new_content, encoding="utf-8")

            return {
                "success": True,
                "removed_sheet": sheet_name or target_base,
                "sheet_uuid": sheet_uuid,
                "removed_instance_path": removed_instance,
                "message": (
                    f"Removed sheet '{sheet_name or target_base}' from {parent_file.name}"
                ),
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
        modern 'Sheet name' or legacy 'Sheetname' property, subsheetPath by
        'Sheet file'/'Sheetfile' basename. Returns (start, end) or None.
        """
        target_base = Path(subsheet_path).name if subsheet_path else None
        for start, end in self._find_sheet_blocks(content):
            block = content[start:end]
            if sheet_name and (
                f'"Sheetname" "{sheet_name}"' in block
                or f'"Sheet name" "{sheet_name}"' in block
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
        "Sheet name"/"Sheet file" properties cannot be set here — use
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
                new_block = (
                    block[: existing.start(2)] + escaped_value + block[existing.end(2) :]
                )
                created = False
            else:
                # Anchor the new property at the sheet origin; created hidden
                # (it is metadata, not display text).
                at_match = re.search(
                    r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)", block
                )
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
                new_block = block[:insert_at] + "\n" + property_block + block[insert_at:].lstrip(" \t")
                created = True

            parent_file.write_text(
                content[:start] + new_block + content[end:], encoding="utf-8"
            )
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
                    r'\(property\s+"((?:[^"\\]|\\.)*)"\s+"((?:[^"\\]|\\.)*)"', block
                ):
                    unescape = lambda s: s.replace('\\"', '"').replace("\\\\", "\\")
                    properties[unescape(m.group(1))] = unescape(m.group(2))
                uuid_match = re.search(r'\(uuid\s+"?([0-9a-fA-F-]+)"?\)', block)
                at_match = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)", block)
                sheets.append(
                    {
                        "name": properties.get("Sheet name")
                        or properties.get("Sheetname"),
                        "file": properties.get("Sheet file")
                        or properties.get("Sheetfile"),
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
        """Ensure every component in each referenced sub-sheet has an instances entry for the
        sheet-block UUID, so ERC resolves references correctly. Returns modified sub-sheet paths.
        """
        modified_sheets: List[str] = []
        try:
            parent_file = Path(parent_path)
            parent_data = sexpdata.loads(parent_content)

            for item in parent_data:
                if not (isinstance(item, list) and len(item) > 0 and item[0] == Symbol("sheet")):
                    continue

                sheet_block_uuid = None
                sheet_file_rel = None
                for sub in item:
                    if isinstance(sub, list) and len(sub) >= 2 and sub[0] == Symbol("uuid"):
                        sheet_block_uuid = str(sub[1])
                    elif (
                        isinstance(sub, list)
                        and len(sub) >= 3
                        and sub[0] == Symbol("property")
                        and sub[1] == "Sheet file"
                    ):
                        sheet_file_rel = str(sub[2])
                if not sheet_block_uuid or not sheet_file_rel:
                    continue

                sub_sheet_path = parent_file.parent / sheet_file_rel
                if not sub_sheet_path.exists():
                    logger.warning(f"Sub-sheet not found: {sub_sheet_path}")
                    continue

                parent_uuid_match = re.search(r"\(uuid\s+([0-9a-fA-F-]+)\)", parent_content)
                parent_uuid = parent_uuid_match.group(1) if parent_uuid_match else ""
                target_path = (
                    f"/{parent_uuid}/{sheet_block_uuid}" if parent_uuid else f"/{sheet_block_uuid}"
                )

                sub_content = sub_sheet_path.read_text(encoding="utf-8")

                def _balanced_end(s: str, start: int) -> int:
                    depth = 0
                    for j in range(start, len(s)):
                        if s[j] == "(":
                            depth += 1
                        elif s[j] == ")":
                            depth -= 1
                            if depth == 0:
                                return j
                    return len(s) - 1

                result_parts: List[str] = []
                pos = 0
                changed = False
                while True:
                    idx = sub_content.find("(instances", pos)
                    if idx == -1:
                        result_parts.append(sub_content[pos:])
                        break
                    result_parts.append(sub_content[pos:idx])
                    end = _balanced_end(sub_content, idx)
                    block = sub_content[idx : end + 1]

                    if target_path not in block:
                        existing = re.search(r'\(reference\s+"([^"]+)"\)\s*\(unit\s+(\d+)\)', block)
                        if existing:
                            new_entry = (
                                f'(path "{target_path}" (reference "{existing.group(1)}") '
                                f"(unit {existing.group(2)}))"
                            )
                            proj_start = block.find("(project ")
                            if proj_start != -1:
                                proj_end = _balanced_end(block, proj_start)
                                block = block[:proj_end] + " " + new_entry + block[proj_end:]
                                changed = True
                    result_parts.append(block)
                    pos = end + 1

                if changed:
                    sub_sheet_path.write_text("".join(result_parts), encoding="utf-8")
                    modified_sheets.append(str(sub_sheet_path))
                    logger.info(
                        f"Fixed instances in {sub_sheet_path} for sheet-block {sheet_block_uuid}"
                    )

        except Exception as e:
            logger.error(f"Error fixing sub-sheet instances: {e}")
        return modified_sheets
