"""Schematic-domain command handlers for KiCADInterface.

Extracted verbatim from kicad_interface.py as a mixin to keep that dispatcher
file manageable. These methods are mixed into KiCADInterface, so ``self`` is the
full interface instance: every ``self.board``, ``self._auto_save_board()``,
cross-handler call, and the command_routes table resolve exactly as before.
No behavior change — pure relocation.
"""

import base64
import glob
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pcbnew
import sexpdata

from commands.library_schematic import LibraryManager as SchematicLibraryManager
from commands.schematic import SchematicManager
from commands.wire_manager import WireManager

logger = logging.getLogger("kicad_interface")


def _svg_to_png(svg_path: str, width: int, height: int) -> Optional[bytes]:
    """Convert SVG to PNG. No cffi dependency.

    Priority:
      1. pymupdf (fitz) — bundled MuPDF renderer, pure Python, no system deps
      2. Inkscape CLI — accurate KiCAD SVG rendering
      3. ImageMagick convert — broad availability fallback
    Returns PNG bytes or None if all converters fail.
    """
    import subprocess
    import tempfile

    try:
        import fitz

        doc = fitz.open(svg_path)
        page = doc[0]
        mat = fitz.Matrix(width / page.rect.width, height / page.rect.height)
        return page.get_pixmap(matrix=mat).tobytes("png")
    except Exception:
        pass

    out_path = os.path.join(tempfile.mkdtemp(), "out.png")

    try:
        r = subprocess.run(
            [
                "inkscape",
                svg_path,
                "--export-type=png",
                f"--export-width={width}",
                f"--export-height={height}",
                f"--export-filename={out_path}",
            ],
            capture_output=True,
            timeout=60,
        )
        if r.returncode == 0 and os.path.exists(out_path):
            with open(out_path, "rb") as f:
                return f.read()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        r = subprocess.run(
            ["convert", "-density", "150", svg_path, "-resize", f"{width}x{height}", out_path],
            capture_output=True,
            timeout=60,
        )
        if r.returncode == 0 and os.path.exists(out_path):
            with open(out_path, "rb") as f:
                return f.read()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


class SchematicHandlersMixin:
    """Schematic-domain handlers mixed into KiCADInterface."""

    def _handle_create_schematic(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new schematic"""
        logger.info("Creating schematic")
        try:
            # Support multiple parameter naming conventions for compatibility:
            # - TypeScript tools use: name, path
            # - Python schema uses: filename, title
            # - Legacy uses: projectName, path, metadata
            project_name = params.get("projectName") or params.get("name") or params.get("title")

            # Handle filename parameter - it may contain full path
            filename = params.get("filename")
            if filename:
                # If filename provided, extract name and path from it
                if filename.endswith(".kicad_sch"):
                    filename = filename[:-10]  # Remove .kicad_sch extension
                path = os.path.dirname(filename) or "."
                project_name = project_name or os.path.basename(filename)
            else:
                path = params.get("path", ".")
            metadata = params.get("metadata", {})

            if not project_name:
                return {
                    "success": False,
                    "message": "Schematic name is required. Provide 'name', 'projectName', or 'filename' parameter.",
                }

            sch_path = path if path and path != "." else None
            schematic = SchematicManager.create_schematic(
                project_name, path=sch_path, metadata=metadata
            )
            # Resolve the saved file path the same way create_schematic does: when
            # `path` is already a full ".kicad_sch" file path, use it directly;
            # otherwise treat it as a directory and append the file name. This keeps
            # the save target in step with the created file and avoids doubling the
            # name into ".../V4.kicad_sch/V4.kicad_sch" (issue #242).
            if sch_path and sch_path.endswith(".kicad_sch"):
                file_path = sch_path
            else:
                base_name = (
                    project_name
                    if project_name.endswith(".kicad_sch")
                    else f"{project_name}.kicad_sch"
                )
                normalized_path = path or "."
                file_path = os.path.join(normalized_path, base_name)
            success = SchematicManager.save_schematic(schematic, file_path)

            return {"success": success, "file_path": file_path}
        except Exception as e:
            logger.error(f"Error creating schematic: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_load_schematic(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Load an existing schematic"""
        logger.info("Loading schematic")
        try:
            filename = params.get("filename")

            if not filename:
                return {"success": False, "message": "Filename is required"}

            schematic = SchematicManager.load_schematic(filename)
            success = schematic is not None

            if success:
                metadata = SchematicManager.get_schematic_metadata(schematic)
                return {"success": success, "metadata": metadata}
            else:
                return {"success": False, "message": "Failed to load schematic"}
        except Exception as e:
            logger.error(f"Error loading schematic: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_add_schematic_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a component to a schematic using text-based injection (no sexpdata)"""
        logger.info("Adding component to schematic")
        try:
            from pathlib import Path

            from commands.dynamic_symbol_loader import DynamicSymbolLoader

            schematic_path = params.get("schematicPath")
            component = params.get("component", {})

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not component:
                return {"success": False, "message": "Component definition is required"}

            comp_type = component.get("type", "R")
            library = component.get("library", "Device")
            reference = component.get("reference", "X?")
            value = component.get("value", comp_type)
            footprint = component.get("footprint", "")
            x = component.get("x", 0)
            y = component.get("y", 0)
            unit = component.get("unit", 1)

            # Derive project path from schematic path for project-local library resolution.
            # Walk up from the schematic file to find the directory that owns the project
            # (contains sym-lib-table or a .kicad_pro file).  Schematics stored in a
            # sub-folder (e.g. sheets/) would otherwise resolve to the wrong directory and
            # miss any project-local sym-lib-table entries.
            schematic_file = Path(schematic_path)
            derived_project_path = schematic_file.parent
            for ancestor in schematic_file.parents:
                if (ancestor / "sym-lib-table").exists() or list(ancestor.glob("*.kicad_pro")):
                    derived_project_path = ancestor
                    break

            loader = DynamicSymbolLoader(project_path=derived_project_path)
            loader.add_component(
                schematic_file,
                library,
                comp_type,
                reference=reference,
                value=value,
                footprint=footprint,
                x=x,
                y=y,
                unit=unit,
                project_path=derived_project_path,
            )

            return {
                "success": True,
                "component_reference": reference,
                "symbol_source": f"{library}:{comp_type}",
            }
        except Exception as e:
            logger.error(f"Error adding component to schematic: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_delete_schematic_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Remove a placed symbol from a schematic using text-based manipulation (no skip writes)"""
        logger.info("Deleting schematic component")
        try:
            import re
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            # String-aware paren matcher (see _find_matching_paren): a naive
            # counter over-runs on unescaped parens inside quoted strings (e.g.
            # MCU pin names like "PA13(JTMS"), which would extend lib_symbols to
            # EOF and make every placed-symbol lookup fail.
            find_matching_paren = self._find_matching_paren

            # Skip lib_symbols section
            lib_sym_pos = content.find("(lib_symbols")
            lib_sym_end = find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1

            # Find ALL placed symbol blocks matching the reference (handles duplicates).
            # Use content-string search so multi-line KiCAD format is handled correctly:
            # KiCAD writes (symbol\n\t\t(lib_id "...") across two lines, which a
            # line-by-line regex would never match.
            blocks_to_delete = []  # list of (char_start, char_end) into content
            search_start = 0
            # Match the opening of any placed-symbol block. KiCAD may emit the
            # children of (symbol ...) in any order — most commonly
            # `(symbol (lib_id "..."))`, but symbols whose library entry has been
            # rescued / customised carry an additional `(lib_name "...")` first:
            # `(symbol (lib_name "...") (lib_id "...") ...)`. Matching just
            # `(symbol\s+(` covers both, and the lib_symbols range check below
            # still excludes library-definition symbols (which use the
            # `(symbol "name" ...)` form with a quoted string, not a paren).
            pattern = re.compile(r"\(symbol\s+\(")
            while True:
                m = pattern.search(content, search_start)
                if not m:
                    break
                pos = m.start()
                # Skip blocks inside lib_symbols
                if lib_sym_pos >= 0 and lib_sym_pos <= pos <= lib_sym_end:
                    search_start = lib_sym_end + 1
                    continue
                end = find_matching_paren(content, pos)
                if end < 0:
                    search_start = pos + 1
                    continue
                block_text = content[pos : end + 1]
                if re.search(
                    r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"',
                    block_text,
                ):
                    blocks_to_delete.append((pos, end))
                search_start = end + 1

            if not blocks_to_delete:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic (note: this tool removes schematic symbols, use delete_component for PCB footprints)",
                }

            # Delete from back to front to preserve character offsets
            for b_start, b_end in sorted(blocks_to_delete, reverse=True):
                # Include any leading newline/whitespace before the block
                trim_start = b_start
                while trim_start > 0 and content[trim_start - 1] in (" ", "\t"):
                    trim_start -= 1
                if trim_start > 0 and content[trim_start - 1] == "\n":
                    trim_start -= 1
                content = content[:trim_start] + content[b_end + 1 :]

            with open(sch_file, "w", encoding="utf-8") as f:
                f.write(content)

            deleted_count = len(blocks_to_delete)
            logger.info(f"Deleted {deleted_count} instance(s) of {reference} from {sch_file.name}")
            return {
                "success": True,
                "reference": reference,
                "deleted_count": deleted_count,
                "schematic": str(sch_file),
            }

        except Exception as e:
            logger.error(f"Error deleting schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    @staticmethod
    def _escape_sexpr_string(value: str) -> str:
        """Escape a string for safe insertion into an S-expression double-quoted token."""
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _find_matching_paren(s: str, start: int) -> int:
        """Return the index of the closing paren matching the opening paren at `start`.

        String-aware: parens inside double-quoted tokens are ignored. KiCAD does
        NOT backslash-escape bare parens inside quoted strings — e.g. MCU pin
        names like "PA13(JTMS" or descriptions like "Vin(fwd) 40V" appear raw in
        .kicad_sch / .kicad_sym files. A naive depth counter treats such an
        in-string "(" as real structure, so it never rebalances and runs to EOF.
        When that happens to the (lib_symbols ...) block, every placed symbol —
        which follows lib_symbols — looks like it lives *inside* it and gets
        skipped, so reference lookups silently fail for the whole schematic.

        Returns -1 if no match is found.
        """
        depth = 0
        i = start
        in_string = False
        while i < len(s):
            ch = s[i]
            if in_string:
                if ch == "\\":
                    i += 2  # skip escaped char (e.g. \" or \\)
                    continue
                if ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return -1

    def _handle_edit_schematic_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Update properties of a placed symbol in a schematic.

        Supports updating the standard fields (footprint / value / reference rename),
        repositioning field labels, and managing **arbitrary custom properties**
        (MPN, Manufacturer, Distributor part numbers, Voltage, Dielectric, Tolerance,
        LCSC, etc.) used by BOM/CPL exporters and JLCPCB / Digi-Key sourcing.

        Uses text-based in-place editing — preserves position, UUID, and all
        unrelated fields.
        """
        logger.info("Editing schematic component")
        try:
            import re
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            new_footprint = params.get("footprint")
            new_value = params.get("value")
            new_reference = params.get("newReference")
            # dict: {"Reference": {"x": 1, "y": 2, "angle": 0}}
            field_positions = params.get("fieldPositions")
            # dict: {"MPN": "RC0603FR-0710KL"}  OR  {"MPN": {"value": "...", "hide": true}}
            properties = params.get("properties")
            # list[str]: ["OldField"] — protected built-ins are rejected
            remove_properties = params.get("removeProperties")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}
            if not any(
                [
                    new_footprint is not None,
                    new_value is not None,
                    new_reference is not None,
                    field_positions is not None,
                    properties is not None,
                    remove_properties is not None,
                ]
            ):
                return {
                    "success": False,
                    "message": (
                        "At least one of footprint, value, newReference, fieldPositions, "
                        "properties, or removeProperties must be provided"
                    ),
                }

            # Reject removal attempts targeting protected built-in fields up-front
            if remove_properties:
                blocked = [n for n in remove_properties if n in self._PROTECTED_PROPERTY_FIELDS]
                if blocked:
                    return {
                        "success": False,
                        "message": (
                            f"Cannot remove built-in field(s) {blocked}: use the dedicated "
                            "value/footprint/newReference parameters or set the value to ''"
                        ),
                    }

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            # Skip lib_symbols section
            lib_sym_pos = content.find("(lib_symbols")
            lib_sym_end = (
                self._find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1
            )

            # Find placed symbol blocks that match the reference. KiCAD may
            # serialise the children of (symbol ...) in different orders —
            # `(symbol (lib_id "..."))` is the common case but rescued or
            # locally-customised symbols carry an extra `(lib_name "...")`
            # before the lib_id: `(symbol (lib_name "...") (lib_id "..."))`.
            # Match any opening paren after `(symbol`; the lib_symbols range
            # check below excludes library-definition symbols, which use the
            # `(symbol "name" ...)` form (quoted string, not paren).
            block_start = block_end = None
            search_start = 0
            pattern = re.compile(r"\(symbol\s+\(")
            while True:
                m = pattern.search(content, search_start)
                if not m:
                    break
                pos = m.start()
                # Skip if inside lib_symbols section
                if lib_sym_pos >= 0 and lib_sym_pos <= pos <= lib_sym_end:
                    search_start = lib_sym_end + 1
                    continue
                end = self._find_matching_paren(content, pos)
                if end < 0:
                    search_start = pos + 1
                    continue
                block_text = content[pos : end + 1]
                if re.search(
                    r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"',
                    block_text,
                ):
                    block_start, block_end = pos, end
                    break
                search_start = end + 1

            if block_start is None or block_end is None:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic",
                }

            # Apply property replacements within the found block
            block_text = content[block_start : block_end + 1]

            # Determine the parent symbol position so that newly-added properties
            # default to a sensible location (anchored near the component).
            # KiCAD always emits the symbol's own (at x y angle) before any
            # (property ...) child blocks, so the FIRST (at ...) inside the
            # symbol block is the symbol origin regardless of whether
            # (lib_name ...) precedes (lib_id ...).
            comp_at = re.search(
                r"\(at\s+([\d\.\-]+)\s+([\d\.\-]+)",
                block_text,
            )
            comp_origin: Tuple[float, float] = (
                (float(comp_at.group(1)), float(comp_at.group(2))) if comp_at else (0.0, 0.0)
            )

            if new_footprint is not None:
                escaped_fp = self._escape_sexpr_string(str(new_footprint))
                block_text = re.sub(
                    r'(\(property\s+"Footprint"\s+)"[^"]*"',
                    rf'\1"{escaped_fp}"',
                    block_text,
                )
            if new_value is not None:
                escaped_v = self._escape_sexpr_string(str(new_value))
                block_text = re.sub(
                    r'(\(property\s+"Value"\s+)"[^"]*"',
                    rf'\1"{escaped_v}"',
                    block_text,
                )
            if new_reference is not None:
                escaped_r = self._escape_sexpr_string(str(new_reference))
                block_text = re.sub(
                    r'(\(property\s+"Reference"\s+)"[^"]*"',
                    rf'\1"{escaped_r}"',
                    block_text,
                )
                # Also update the (reference "...") leaves inside the symbol's
                # (instances) → (project) → (path) subtree. KiCad reads those
                # entries — not the (property "Reference" ...) field — when
                # generating netlists and syncing the PCB via "Update PCB from
                # Schematic", so leaving them stale produces a silent
                # reference mismatch where eeschema shows the new ref but ERC
                # / netlist export / PCB sync all use the old one. See #126.
                instances_pos = block_text.find("(instances")
                if instances_pos >= 0:
                    instances_end = self._find_matching_paren(block_text, instances_pos)
                    if instances_end >= 0:
                        instances_block = block_text[instances_pos : instances_end + 1]
                        updated_instances = re.sub(
                            r'(\(reference\s+)"' + re.escape(reference) + r'"',
                            rf'\1"{escaped_r}"',
                            instances_block,
                        )
                        block_text = (
                            block_text[:instances_pos]
                            + updated_instances
                            + block_text[instances_end + 1 :]
                        )
            if field_positions is not None:
                for field_name, pos in field_positions.items():
                    x = pos.get("x", 0)
                    y = pos.get("y", 0)
                    angle = pos.get("angle", 0)
                    block_text = re.sub(
                        r'(\(property\s+"'
                        + re.escape(field_name)
                        + r'"\s+"[^"]*"\s+)\(at\s+[\d\.\-]+\s+[\d\.\-]+\s+[\d\.\-]+\s*\)',
                        rf"\1(at {x} {y} {angle})",
                        block_text,
                    )
                    justify = pos.get("justify")
                    if justify is not None:
                        block_text = self._set_justify_on_property(
                            block_text, field_name, str(justify)
                        )

            properties_added: Dict[str, Any] = {}
            properties_updated: Dict[str, Any] = {}
            if properties:
                if not isinstance(properties, dict):
                    return {
                        "success": False,
                        "message": "properties must be a dict mapping property name -> value or spec",
                    }
                for name, spec in properties.items():
                    if not isinstance(name, str) or not name:
                        return {
                            "success": False,
                            "message": f"Invalid property name: {name!r}",
                        }
                    # Normalise scalar values to a spec dict with just {"value": ...}
                    if not isinstance(spec, dict):
                        spec = {"value": spec}
                    try:
                        block_text, action = self._set_property_in_block(
                            block_text, name, spec, comp_origin
                        )
                    except ValueError as ve:
                        return {"success": False, "message": str(ve)}
                    target = properties_added if action == "added" else properties_updated
                    target[name] = spec.get("value")

            properties_removed: list = []
            if remove_properties:
                if not isinstance(remove_properties, list):
                    return {
                        "success": False,
                        "message": "removeProperties must be a list of property names",
                    }
                for name in remove_properties:
                    block_text, removed = self._remove_property_from_block(block_text, name)
                    if removed:
                        properties_removed.append(name)

            content = content[:block_start] + block_text + content[block_end + 1 :]

            with open(sch_file, "w", encoding="utf-8") as f:
                f.write(content)

            changes: Dict[str, Any] = {
                k: v
                for k, v in {
                    "footprint": new_footprint,
                    "value": new_value,
                    "reference": new_reference,
                }.items()
                if v is not None
            }
            if field_positions is not None:
                changes["fieldPositions"] = field_positions
            if properties_added:
                changes["propertiesAdded"] = properties_added
            if properties_updated:
                changes["propertiesUpdated"] = properties_updated
            if properties_removed:
                changes["propertiesRemoved"] = properties_removed

            logger.info(f"Edited schematic component {reference}: {changes}")
            return {"success": True, "reference": reference, "updated": changes}

        except Exception as e:
            logger.error(f"Error editing schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_set_schematic_component_property(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add or update a single property on a placed schematic symbol.

        Convenience wrapper around `edit_schematic_component` for the very common
        case of setting one BOM/sourcing field at a time. The property is created
        if it does not already exist, otherwise its value (and optionally its
        position / visibility) is updated in place.
        """
        logger.info("Setting schematic component property")
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return {"success": False, "message": "name is required"}
        if "value" not in params:
            return {"success": False, "message": "value is required"}

        spec: Dict[str, Any] = {"value": params["value"]}
        for key in ("x", "y", "angle", "hide", "fontSize", "justify"):
            if params.get(key) is not None:
                spec[key] = params[key]

        return self._handle_edit_schematic_component(
            {
                "schematicPath": params.get("schematicPath"),
                "reference": params.get("reference"),
                "properties": {name: spec},
            }
        )

    def _handle_remove_schematic_component_property(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Remove a single custom property from a placed schematic symbol.

        Built-in fields (Reference, Value, Footprint, Datasheet) cannot be
        removed — use `edit_schematic_component` to clear them instead.
        """
        logger.info("Removing schematic component property")
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return {"success": False, "message": "name is required"}
        return self._handle_edit_schematic_component(
            {
                "schematicPath": params.get("schematicPath"),
                "reference": params.get("reference"),
                "removeProperties": [name],
            }
        )

    def _handle_get_schematic_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return full component info: position and all field values with their (at x y angle) positions."""
        logger.info("Getting schematic component info")
        try:
            import re
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            # String-aware paren matcher (see _find_matching_paren): a naive
            # counter over-runs on unescaped parens inside quoted strings (e.g.
            # MCU pin names like "PA13(JTMS"), which would extend lib_symbols to
            # EOF and make every placed-symbol lookup fail.
            find_matching_paren = self._find_matching_paren

            # Skip lib_symbols section
            lib_sym_pos = content.find("(lib_symbols")
            lib_sym_end = find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1

            # Find the placed symbol block for this reference. KiCAD may emit
            # the children of (symbol ...) in different orders — most commonly
            # `(symbol (lib_id "..."))`, but symbols whose library entry has
            # been rescued / customised carry an extra `(lib_name "...")` first
            # (`(symbol (lib_name "...") (lib_id "..."))`). Match `(symbol\s+(`
            # — any opening paren — to handle both. The lib_symbols range check
            # below excludes library-definition symbols, which use the
            # `(symbol "name" ...)` form (quoted string, not paren).
            block_start = block_end = None
            search_start = 0
            pattern = re.compile(r"\(symbol\s+\(")
            while True:
                m = pattern.search(content, search_start)
                if not m:
                    break
                pos = m.start()
                if lib_sym_pos >= 0 and lib_sym_pos <= pos <= lib_sym_end:
                    search_start = lib_sym_end + 1
                    continue
                end = find_matching_paren(content, pos)
                if end < 0:
                    search_start = pos + 1
                    continue
                block_text = content[pos : end + 1]
                if re.search(
                    r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"',
                    block_text,
                ):
                    block_start, block_end = pos, end
                    break
                search_start = end + 1

            if block_start is None or block_end is None:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic",
                }

            block_text = content[block_start : block_end + 1]

            # Extract component position: the first (at x y angle) inside the
            # symbol block. KiCAD always writes the symbol's own (at) before
            # any (property ...) child blocks, so the first match is the
            # symbol origin regardless of the (lib_name)/(lib_id) ordering.
            comp_at = re.search(
                r"\(at\s+([\d\.\-]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s*\)",
                block_text,
            )
            if comp_at:
                comp_pos = {
                    "x": float(comp_at.group(1)),
                    "y": float(comp_at.group(2)),
                    "angle": float(comp_at.group(3)),
                }
            else:
                comp_pos = None

            # Extract all properties with their at positions
            prop_pattern = re.compile(
                r'\(property\s+"([^"]*)"\s+"([^"]*)"\s+\(at\s+([\d\.\-]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s*\)'
            )
            fields = {}
            for m in prop_pattern.finditer(block_text):
                name, value, x, y, angle = (
                    m.group(1),
                    m.group(2),
                    m.group(3),
                    m.group(4),
                    m.group(5),
                )
                fields[name] = {
                    "value": value,
                    "x": float(x),
                    "y": float(y),
                    "angle": float(angle),
                }

            return {
                "success": True,
                "reference": reference,
                "position": comp_pos,
                "fields": fields,
            }

        except Exception as e:
            logger.error(f"Error getting schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_add_schematic_wire(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a wire to a schematic using WireManager, with optional pin snapping"""
        logger.info("Adding wire to schematic")
        try:
            from pathlib import Path

            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            points = params.get("waypoints")
            properties = params.get("properties", {})
            snap_to_pins = params.get("snapToPins", True)
            snap_tolerance = params.get("snapTolerance", 1.0)

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not points or len(points) < 2:
                return {
                    "success": False,
                    "message": "At least 2 waypoints are required",
                }

            # Make a mutable copy of points
            points = [list(p) for p in points]

            # Pin snapping: adjust first and last endpoints to nearest pin
            snapped_info = []
            if snap_to_pins:
                from commands.pin_locator import PinLocator

                locator = PinLocator()
                sch_path = Path(schematic_path)

                # Load schematic to iterate all symbols
                from skip import Schematic as SkipSchematic

                sch = SkipSchematic(str(sch_path))

                # Collect all pin locations: list of (ref, pin_num, [x, y])
                all_pins = []
                for symbol in sch.symbol:
                    if not hasattr(symbol.property, "Reference"):
                        continue
                    ref = symbol.property.Reference.value
                    if ref.startswith("_TEMPLATE"):
                        continue
                    pin_locs = locator.get_all_symbol_pins(sch_path, ref)
                    for pin_num, coords in pin_locs.items():
                        all_pins.append((ref, pin_num, coords))

                def find_nearest_pin(point: Any, tolerance: Any) -> Any:
                    """Find the nearest pin within tolerance of a point."""
                    best = None
                    best_dist = tolerance
                    for ref, pin_num, coords in all_pins:
                        dx = point[0] - coords[0]
                        dy = point[1] - coords[1]
                        dist = (dx * dx + dy * dy) ** 0.5
                        if dist <= best_dist:
                            best_dist = dist
                            best = (ref, pin_num, coords)
                    return best

                # Snap first endpoint
                match = find_nearest_pin(points[0], snap_tolerance)
                if match:
                    ref, pin_num, coords = match
                    logger.info(
                        f"Snapped start point {points[0]} -> {coords} (pin {ref}/{pin_num})"
                    )
                    snapped_info.append(
                        f"start snapped to {ref}/{pin_num} at [{coords[0]}, {coords[1]}]"
                    )
                    points[0] = list(coords)

                # Snap last endpoint
                match = find_nearest_pin(points[-1], snap_tolerance)
                if match:
                    ref, pin_num, coords = match
                    logger.info(f"Snapped end point {points[-1]} -> {coords} (pin {ref}/{pin_num})")
                    snapped_info.append(
                        f"end snapped to {ref}/{pin_num} at [{coords[0]}, {coords[1]}]"
                    )
                    points[-1] = list(coords)

            # Extract wire properties
            stroke_width = properties.get("stroke_width", 0)
            stroke_type = properties.get("stroke_type", "default")

            # Use WireManager for S-expression manipulation
            if len(points) == 2:
                success = WireManager.add_wire(
                    Path(schematic_path),
                    points[0],
                    points[1],
                    stroke_width=stroke_width,
                    stroke_type=stroke_type,
                )
            else:
                success = WireManager.add_polyline_wire(
                    Path(schematic_path),
                    points,
                    stroke_width=stroke_width,
                    stroke_type=stroke_type,
                )

            if success:
                message = "Wire added successfully"
                if snapped_info:
                    message += "; " + "; ".join(snapped_info)
                return {"success": True, "message": message}
            else:
                return {"success": False, "message": "Failed to add wire"}
        except Exception as e:
            logger.error(f"Error adding wire to schematic: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_list_schematic_libraries(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List available symbol libraries"""
        logger.info("Listing schematic libraries")
        try:
            search_paths = params.get("searchPaths")

            libraries = SchematicLibraryManager.list_available_libraries(search_paths)
            return {"success": True, "libraries": libraries}
        except Exception as e:
            logger.error(f"Error listing schematic libraries: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_check_wire_collisions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Detect wires passing through component bodies without connecting to pins"""
        logger.info("Checking wire collisions")
        try:
            from commands.schematic_analysis import check_wire_collisions

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            result = check_wire_collisions(schematic_path)
            return {"success": True, **result}
        except ImportError:
            return {
                "success": False,
                "message": "schematic_analysis module not available",
            }
        except Exception as e:
            logger.error(f"Error checking wire collisions: {e}")
            return {"success": False, "message": str(e)}

    def _handle_export_schematic_pdf(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export schematic to PDF"""
        logger.info("Exporting schematic to PDF")
        try:
            schematic_path = params.get("schematicPath")
            output_path = params.get("outputPath")

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not output_path:
                return {"success": False, "message": "Output path is required"}

            if not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            import subprocess

            cmd = [
                "kicad-cli",
                "sch",
                "export",
                "pdf",
                "--output",
                output_path,
                schematic_path,
            ]

            if params.get("blackAndWhite"):
                cmd.insert(-1, "--black-and-white")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode == 0:
                return {"success": True, "file": {"path": output_path}}
            else:
                return {
                    "success": False,
                    "message": f"kicad-cli failed: {result.stderr}",
                }

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except Exception as e:
            logger.error(f"Error exporting schematic to PDF: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_add_schematic_net_label(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a net label to schematic using WireManager.

        When componentRef and pinNumber are supplied the label is placed at the
        exact pin endpoint retrieved via PinLocator, ignoring the provided
        position.  The response includes the actual coordinates used and
        whether the label landed on a pin endpoint.
        """
        logger.info("Adding net label to schematic")
        try:
            from pathlib import Path

            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")
            position = params.get("position")
            label_type = params.get("labelType", "label")
            orientation = params.get("orientation", 0)
            component_ref = params.get("componentRef")
            pin_number = params.get("pinNumber")

            if not all([schematic_path, net_name]):
                return {
                    "success": False,
                    "message": "Missing required parameters: schematicPath, netName",
                }

            snapped_to_pin: Optional[Dict[str, Any]] = None

            if component_ref and pin_number:
                # Snap position to exact pin endpoint using PinLocator
                from commands.pin_locator import PinLocator

                locator = PinLocator()
                pin_loc = locator.get_pin_location(
                    Path(schematic_path), component_ref, str(pin_number)
                )
                if pin_loc is None:
                    return {
                        "success": False,
                        "message": (
                            f"Could not locate pin {pin_number} on {component_ref}. "
                            "Check the reference and pin number."
                        ),
                    }
                position = pin_loc
                snapped_to_pin = {"component": component_ref, "pin": str(pin_number)}
                logger.info(
                    f"Snapped label '{net_name}' to pin {component_ref}/{pin_number} at {position}"
                )
            elif position is None:
                return {
                    "success": False,
                    "message": (
                        "Missing position. Either provide position [x, y] or "
                        "componentRef + pinNumber to snap to a pin endpoint."
                    ),
                }

            # Collect existing net names BEFORE adding the new label so we can
            # detect case-mismatch collisions against pre-existing nets only.
            existing_net_names: List[str] = []
            try:
                pre_schematic = SchematicManager.load_schematic(schematic_path)
                if pre_schematic is not None:
                    if hasattr(pre_schematic, "label"):
                        for lbl in pre_schematic.label:
                            if hasattr(lbl, "value"):
                                existing_net_names.append(lbl.value)
                    if hasattr(pre_schematic, "global_label"):
                        for lbl in pre_schematic.global_label:
                            if hasattr(lbl, "value"):
                                existing_net_names.append(lbl.value)
            except Exception:
                # Non-fatal: if we can't read existing nets, skip the warning
                existing_net_names = []

            # Use WireManager for S-expression manipulation
            success = WireManager.add_label(
                Path(schematic_path),
                net_name,
                position,
                label_type=label_type,
                orientation=orientation,
            )

            if not success:
                return {"success": False, "message": "Failed to add net label"}

            # Compute case-mismatch warnings against pre-existing net names.
            # A collision is: existing name != new name, but lowercases match.
            new_name_lower = net_name.lower()
            case_warnings: List[str] = [
                f"Net '{existing}' already exists — label '{net_name}' may be a case mismatch."
                for existing in existing_net_names
                if existing.lower() == new_name_lower and existing != net_name
            ]

            response: Dict[str, Any] = {
                "success": True,
                "message": f"Added net label '{net_name}' at {position}",
                "actual_position": position,
            }
            if snapped_to_pin:
                response["snapped_to_pin"] = snapped_to_pin
                response["message"] = (
                    f"Added net label '{net_name}' at exact pin endpoint "
                    f"{component_ref}/{pin_number} ({position[0]}, {position[1]})"
                )
            if case_warnings:
                response["case_warnings"] = case_warnings
            return response

        except Exception as e:
            logger.error(f"Error adding net label: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_get_schematic_pin_locations(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Return exact pin endpoint coordinates for a schematic component"""
        logger.info("Getting schematic pin locations")
        try:
            from pathlib import Path

            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")

            if not all([schematic_path, reference]):
                return {
                    "success": False,
                    "message": "Missing required parameters: schematicPath, reference",
                }

            locator = PinLocator()
            all_pins = locator.get_all_symbol_pins(Path(schematic_path), reference)

            if not all_pins:
                return {
                    "success": False,
                    "message": f"No pins found for {reference} — check reference and schematic path",
                }

            # Enrich with pin names and angles from the symbol definition
            pins_def = (
                locator.get_symbol_pins(
                    Path(schematic_path),
                    locator._get_lib_id(Path(schematic_path), reference),
                )
                if hasattr(locator, "_get_lib_id")
                else {}
            )

            result = {}
            for pin_num, coords in all_pins.items():
                entry = {"x": coords[0], "y": coords[1]}
                if pin_num in pins_def:
                    entry["name"] = pins_def[pin_num].get("name", pin_num)
                    entry["angle"] = (
                        locator.get_pin_angle(Path(schematic_path), reference, pin_num) or 0
                    )
                result[pin_num] = entry

            return {"success": True, "reference": reference, "pins": result}

        except Exception as e:
            logger.error(f"Error getting pin locations: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_schematic_view(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get a rasterised image of the schematic (SVG export → optional PNG conversion)"""
        logger.info("Getting schematic view")
        import base64
        import subprocess
        import tempfile

        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path or not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            fmt = params.get("format", "png")
            width = params.get("width", 1200)
            height = params.get("height", 900)

            # Step 1: Export schematic to SVG via kicad-cli
            with tempfile.TemporaryDirectory() as tmpdir:
                svg_path = os.path.join(tmpdir, "schematic.svg")
                cmd = [
                    "kicad-cli",
                    "sch",
                    "export",
                    "svg",
                    "--output",
                    tmpdir,
                    "--no-background-color",
                    schematic_path,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

                if result.returncode != 0:
                    return {
                        "success": False,
                        "message": f"kicad-cli SVG export failed: {result.stderr}",
                    }

                # kicad-cli may name the file after the schematic, find it
                import glob

                svg_files = glob.glob(os.path.join(tmpdir, "*.svg"))
                if not svg_files:
                    return {
                        "success": False,
                        "message": "No SVG file produced by kicad-cli",
                    }
                svg_path = svg_files[0]

                if fmt == "svg":
                    with open(svg_path, "r", encoding="utf-8") as f:
                        svg_data = f.read()
                    return {"success": True, "imageData": svg_data, "format": "svg"}

                # Step 2: Convert SVG to PNG (cffi-free)
                png_data = _svg_to_png(svg_path, width, height)
                if png_data is None:
                    with open(svg_path, "r", encoding="utf-8") as f:
                        svg_data = f.read()
                    return {
                        "success": True,
                        "imageData": svg_data,
                        "format": "svg",
                        "message": "No PNG converter available — returning SVG. Install pymupdf, inkscape, or imagemagick.",
                    }

                return {
                    "success": True,
                    "imageData": base64.b64encode(png_data).decode("utf-8"),
                    "format": "png",
                    "width": width,
                    "height": height,
                }

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except Exception as e:
            logger.error(f"Error getting schematic view: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_components(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List all components in a schematic"""
        logger.info("Listing schematic components")
        try:
            from pathlib import Path

            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Optional filters
            filter_params = params.get("filter", {})
            lib_id_filter = filter_params.get("libId", "")
            ref_prefix_filter = filter_params.get("referencePrefix", "")

            locator = PinLocator()
            components = []

            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                # Skip template symbols
                if ref.startswith("_TEMPLATE"):
                    continue

                lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else ""

                # Apply filters
                if lib_id_filter and lib_id_filter not in lib_id:
                    continue
                if ref_prefix_filter and not ref.startswith(ref_prefix_filter):
                    continue

                value = symbol.property.Value.value if hasattr(symbol.property, "Value") else ""
                footprint = (
                    symbol.property.Footprint.value if hasattr(symbol.property, "Footprint") else ""
                )
                position = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                uuid_val = symbol.uuid.value if hasattr(symbol, "uuid") else ""

                comp = {
                    "reference": ref,
                    "libId": lib_id,
                    "value": value,
                    "footprint": footprint,
                    "position": {"x": float(position[0]), "y": float(position[1])},
                    "rotation": float(position[2]) if len(position) > 2 else 0,
                    "uuid": str(uuid_val),
                }

                # Get pins if available
                try:
                    all_pins = locator.get_all_symbol_pins(sch_file, ref)
                    if all_pins:
                        pins_def = locator.get_symbol_pins(sch_file, lib_id) or {}
                        pin_list = []
                        for pin_num, coords in all_pins.items():
                            pin_info = {
                                "number": pin_num,
                                "position": {"x": coords[0], "y": coords[1]},
                            }
                            if pin_num in pins_def:
                                pin_info["name"] = pins_def[pin_num].get("name", pin_num)
                            pin_list.append(pin_info)
                        comp["pins"] = pin_list
                except Exception:
                    pass  # Pin lookup is best-effort

                components.append(comp)

            return {"success": True, "components": components, "count": len(components)}

        except Exception as e:
            logger.error(f"Error listing schematic components: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_nets(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List all nets in a schematic with their connections"""
        logger.info("Listing schematic nets")
        try:
            from commands.wire_connectivity import (
                _build_adjacency,
                _discover_sub_sheets,
                _load_sexp,
                _parse_labels_sexp,
                _parse_virtual_connections,
                _parse_wires,
                count_pins_on_net,
                get_connections_for_net,
            )

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Collect net names from the top-level sheet using sexpdata.
            # Falls back to kicad-skip's label collections when the file
            # cannot be read (e.g. mocked schematics in unit tests).
            net_names: set = set()
            sexp_loaded = False
            try:
                sexp = _load_sexp(schematic_path)
                sexp_loaded = True
                _, label_to_points = _parse_labels_sexp(sexp)
                net_names.update(label_to_points.keys())
            except Exception as e:
                logger.debug(
                    f"Could not parse labels from {schematic_path} via sexp ({e}); "
                    "falling back to kicad-skip label collections"
                )
                for attr in ("label", "global_label"):
                    if not hasattr(schematic, attr):
                        continue
                    for label in getattr(schematic, attr):
                        if hasattr(label, "value"):
                            net_names.add(label.value)

            # Collect net names from all sub-sheets (only when the parent
            # sheet was readable; fake/mock paths skip recursion entirely).
            if sexp_loaded:
                sub_sheets = _discover_sub_sheets(schematic_path)
                for sub_path in sub_sheets:
                    try:
                        sub_sexp = _load_sexp(sub_path)
                        _, sub_label_to_points = _parse_labels_sexp(sub_sexp)
                        net_names.update(sub_label_to_points.keys())
                    except Exception as e:
                        logger.warning(f"Error reading sub-sheet {sub_path}: {e}")

            # Pre-build shared wire graph structures for efficiency
            all_wires = _parse_wires(schematic)
            if all_wires:
                adjacency, iu_to_wires = _build_adjacency(all_wires)
            else:
                adjacency, iu_to_wires = [], {}
            point_to_label, label_to_points = _parse_virtual_connections(schematic, schematic_path)

            nets = []
            for net_name in sorted(net_names):
                connections = get_connections_for_net(schematic, schematic_path, net_name)
                pin_count = count_pins_on_net(
                    schematic,
                    schematic_path,
                    net_name,
                    all_wires,
                    iu_to_wires,
                    adjacency,
                    point_to_label,
                    label_to_points,
                )
                nets.append(
                    {
                        "name": net_name,
                        "connections": connections,
                        "connected_pin_count": pin_count,
                    }
                )

            return {"success": True, "nets": nets, "count": len(nets)}

        except Exception as e:
            logger.error(f"Error listing schematic nets: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_wires(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List all wires in a schematic"""
        logger.info("Listing schematic wires")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            wires = []
            if hasattr(schematic, "wire"):
                for wire in schematic.wire:
                    if hasattr(wire, "pts") and hasattr(wire.pts, "xy"):
                        points = []
                        for point in wire.pts.xy:
                            if hasattr(point, "value"):
                                points.append(
                                    {
                                        "x": float(point.value[0]),
                                        "y": float(point.value[1]),
                                    }
                                )

                        if len(points) >= 2:
                            wires.append(
                                {
                                    "start": points[0],
                                    "end": points[-1],
                                }
                            )

            return {"success": True, "wires": wires, "count": len(wires)}

        except Exception as e:
            logger.error(f"Error listing schematic wires: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_labels(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List all net labels and power flags in a schematic"""
        logger.info("Listing schematic labels")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            net_name = params.get("netName")
            label_type = params.get("labelType")

            _valid_label_types = {"net", "global", "power"}
            if label_type is not None and label_type not in _valid_label_types:
                return {"success": False, "message": "labelType must be one of: net, global, power"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            labels = []

            # Regular labels
            if hasattr(schematic, "label"):
                for label in schematic.label:
                    if hasattr(label, "value"):
                        pos = (
                            label.at.value
                            if hasattr(label, "at") and hasattr(label.at, "value")
                            else [0, 0]
                        )
                        labels.append(
                            {
                                "name": label.value,
                                "type": "net",
                                "position": {"x": float(pos[0]), "y": float(pos[1])},
                            }
                        )

            # Global labels
            if hasattr(schematic, "global_label"):
                for label in schematic.global_label:
                    if hasattr(label, "value"):
                        pos = (
                            label.at.value
                            if hasattr(label, "at") and hasattr(label.at, "value")
                            else [0, 0]
                        )
                        labels.append(
                            {
                                "name": label.value,
                                "type": "global",
                                "position": {"x": float(pos[0]), "y": float(pos[1])},
                            }
                        )

            # Power symbols (components with power flag)
            if hasattr(schematic, "symbol"):
                for symbol in schematic.symbol:
                    if not hasattr(symbol.property, "Reference"):
                        continue
                    ref = symbol.property.Reference.value
                    if ref.startswith("_TEMPLATE"):
                        continue
                    if not ref.startswith("#PWR"):
                        continue
                    value = (
                        symbol.property.Value.value if hasattr(symbol.property, "Value") else ref
                    )
                    pos = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                    labels.append(
                        {
                            "name": value,
                            "type": "power",
                            "position": {"x": float(pos[0]), "y": float(pos[1])},
                        }
                    )

            # Apply filters
            if net_name is not None:
                labels = [lbl for lbl in labels if lbl["name"] == net_name]
            if label_type is not None:
                labels = [lbl for lbl in labels if lbl["type"] == label_type]

            return {"success": True, "labels": labels, "count": len(labels)}

        except Exception as e:
            logger.error(f"Error listing schematic labels: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_move_schematic_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Move a schematic component to a new position, dragging connected wires."""
        logger.info("Moving schematic component")
        try:
            from commands.wire_dragger import WireDragger

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            position = params.get("position", {})
            new_x = position.get("x")
            new_y = position.get("y")
            preserve_wires = params.get("preserveWires", True)

            if not schematic_path or not reference:
                return {
                    "success": False,
                    "message": "schematicPath and reference are required",
                }
            if new_x is None or new_y is None:
                return {
                    "success": False,
                    "message": "position with x and y is required",
                }

            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_data = sexpdata.loads(f.read())

            # Find symbol and record old position
            found = WireDragger.find_symbol(sch_data, reference)
            if found is None:
                return {"success": False, "message": f"Component {reference} not found"}
            _, old_x, old_y = found[0], found[1], found[2]
            old_position = {"x": old_x, "y": old_y}

            drag_summary = {}
            if preserve_wires:
                # Compute pin world positions before and after the move
                pin_positions = WireDragger.compute_pin_positions(
                    sch_data, reference, float(new_x), float(new_y)
                )
                # Build old→new coordinate map (deduplicate coincident pins)
                old_to_new = {}
                for _pin, (old_xy, new_xy) in pin_positions.items():
                    if old_xy in old_to_new:
                        logger.warning(
                            f"move_schematic_component: pin {_pin!r} of {reference!r} "
                            f"shares old position {old_xy} with another pin; "
                            f"keeping first entry, skipping duplicate"
                        )
                        continue
                    old_to_new[old_xy] = new_xy

                drag_summary = WireDragger.drag_wires(sch_data, old_to_new)

                # Synthesize wires for touching-pin connections after dragging,
                # so drag_wires doesn't accidentally move and collapse the new wire.
                wires_synthesized = WireDragger.synthesize_touching_pin_wires(
                    sch_data, reference, pin_positions
                )
                drag_summary["wires_synthesized"] = wires_synthesized

            # Update symbol position
            WireDragger.update_symbol_position(sch_data, reference, float(new_x), float(new_y))

            WireManager.sync_junctions(sch_data)

            with open(schematic_path, "w", encoding="utf-8") as f:
                f.write(sexpdata.dumps(sch_data))

            return {
                "success": True,
                "oldPosition": old_position,
                "newPosition": {"x": new_x, "y": new_y},
                "wiresMoved": drag_summary.get("endpoints_moved", 0),
                "wiresRemoved": drag_summary.get("wires_removed", 0),
                "wiresSynthesized": drag_summary.get("wires_synthesized", 0),
                "labelsMoved": drag_summary.get("labels_moved", 0),
            }

        except Exception as e:
            logger.error(f"Error moving schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_rotate_schematic_component(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Rotate and/or mirror a schematic component, dragging connected wires."""
        logger.info("Rotating schematic component")
        try:
            import sexpdata as _sexpdata
            from commands.wire_dragger import WireDragger

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            angle = params.get("angle", 0)
            mirror = params.get("mirror")  # "x", "y", or None

            if not schematic_path or not reference:
                return {
                    "success": False,
                    "message": "schematicPath and reference are required",
                }

            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_data = _sexpdata.loads(f.read())

            found = WireDragger.find_symbol(sch_data, reference)
            if found is None:
                return {"success": False, "message": f"Component {reference} not found"}

            # Determine new mirror state: explicit param overrides; None preserves existing
            _, _, _, _, _, old_mirror_x, old_mirror_y = found
            if mirror is None:
                new_mirror_x = old_mirror_x
                new_mirror_y = old_mirror_y
                effective_mirror = "x" if old_mirror_x else ("y" if old_mirror_y else None)
            else:
                new_mirror_x = mirror == "x"
                new_mirror_y = mirror == "y"
                effective_mirror = mirror

            # Compute pin world positions before and after the transform
            pin_positions = WireDragger.compute_pin_positions_for_rotation(
                sch_data, reference, float(angle), new_mirror_x, new_mirror_y
            )

            # Build old→new map (skip pins that don't move)
            old_to_new = {}
            for _pin, (old_xy, new_xy) in pin_positions.items():
                if old_xy == new_xy:
                    continue
                if old_xy in old_to_new:
                    logger.warning(
                        f"rotate: pin {_pin!r} of {reference!r} shares old position "
                        f"{old_xy} with another pin; skipping duplicate"
                    )
                    continue
                old_to_new[old_xy] = new_xy

            # Drag connected wires to follow pins
            drag_summary = WireDragger.drag_wires(sch_data, old_to_new)

            # Update the symbol's rotation and mirror token in sexpdata
            WireDragger.update_symbol_rotation_mirror(
                sch_data, reference, float(angle), effective_mirror
            )

            WireManager.sync_junctions(sch_data)

            with open(schematic_path, "w", encoding="utf-8") as f:
                f.write(_sexpdata.dumps(sch_data))

            return {
                "success": True,
                "reference": reference,
                "angle": angle,
                "mirror": effective_mirror,
                "wiresMoved": drag_summary.get("endpoints_moved", 0),
                "wiresRemoved": drag_summary.get("wires_removed", 0),
                "labelsMoved": drag_summary.get("labels_moved", 0),
            }

        except Exception as e:
            logger.error(f"Error rotating schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_annotate_schematic(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Annotate unannotated components in schematic (R? -> R1, R2, ...)"""
        logger.info("Annotating schematic")
        try:
            import re

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Collect existing references by prefix
            existing_refs = {}  # prefix -> set of numbers
            unannotated = []  # (symbol, prefix)

            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                if ref.startswith("_TEMPLATE"):
                    continue

                # Split reference into prefix and number
                match = re.match(r"^([A-Za-z_]+)(\d+)$", ref)
                if match:
                    prefix = match.group(1)
                    num = int(match.group(2))
                    if prefix not in existing_refs:
                        existing_refs[prefix] = set()
                    existing_refs[prefix].add(num)
                elif ref.endswith("?"):
                    prefix = ref[:-1]
                    unannotated.append((symbol, prefix))

            if not unannotated:
                return {
                    "success": True,
                    "annotated": [],
                    "message": "All components already annotated",
                }

            annotated = []
            for symbol, prefix in unannotated:
                if prefix not in existing_refs:
                    existing_refs[prefix] = set()

                # Find next available number
                next_num = 1
                while next_num in existing_refs[prefix]:
                    next_num += 1

                old_ref = symbol.property.Reference.value
                new_ref = f"{prefix}{next_num}"
                symbol.setAllReferences(new_ref)
                existing_refs[prefix].add(next_num)

                uuid_val = str(symbol.uuid.value) if hasattr(symbol, "uuid") else ""
                annotated.append(
                    {
                        "uuid": uuid_val,
                        "oldReference": old_ref,
                        "newReference": new_ref,
                    }
                )

            SchematicManager.save_schematic(schematic, schematic_path)
            return {"success": True, "annotated": annotated}

        except Exception as e:
            logger.error(f"Error annotating schematic: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_delete_schematic_wire(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a wire from the schematic matching start/end points"""
        logger.info("Deleting schematic wire")
        try:
            schematic_path = params.get("schematicPath")
            start = params.get("start", {})
            end = params.get("end", {})

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            from pathlib import Path

            from commands.wire_manager import WireManager

            start_point = [start.get("x", 0), start.get("y", 0)]
            end_point = [end.get("x", 0), end.get("y", 0)]

            deleted = WireManager.delete_wire(Path(schematic_path), start_point, end_point)
            if deleted:
                return {"success": True}
            else:
                return {"success": False, "message": "No matching wire found"}

        except Exception as e:
            logger.error(f"Error deleting schematic wire: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_delete_schematic_net_label(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a net label from the schematic"""
        logger.info("Deleting schematic net label")
        try:
            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")
            position = params.get("position")

            if not schematic_path or not net_name:
                return {
                    "success": False,
                    "message": "schematicPath and netName are required",
                }

            from pathlib import Path

            from commands.wire_manager import WireManager

            pos_list = None
            if position:
                pos_list = [position.get("x", 0), position.get("y", 0)]

            deleted = WireManager.delete_label(Path(schematic_path), net_name, pos_list)
            if deleted:
                return {"success": True}
            else:
                return {"success": False, "message": f"Label '{net_name}' not found"}

        except Exception as e:
            logger.error(f"Error deleting schematic net label: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_move_schematic_net_label(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Move a net label to a new position in the schematic."""
        logger.info("Moving schematic net label")
        try:
            import sexpdata as _sexpdata
            from sexpdata import Symbol

            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")
            new_position = params.get("newPosition", {})
            new_x = new_position.get("x")
            new_y = new_position.get("y")
            current_position = params.get("currentPosition")
            label_type = params.get("labelType")

            if not schematic_path or not net_name:
                return {"success": False, "message": "schematicPath and netName are required"}
            if new_x is None or new_y is None:
                return {"success": False, "message": "newPosition with x and y is required"}

            _valid_types = {"label", "global_label", "hierarchical_label"}
            if label_type is not None and label_type not in _valid_types:
                return {
                    "success": False,
                    "message": f"labelType must be one of: {', '.join(sorted(_valid_types))}",
                }

            _SYM_AT = Symbol("at")
            target_syms = (
                {Symbol(label_type)}
                if label_type is not None
                else {Symbol(t) for t in _valid_types}
            )

            TOLERANCE = 0.5

            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_data = _sexpdata.loads(f.read())

            for item in sch_data:
                if not (isinstance(item, list) and len(item) >= 2 and item[0] in target_syms):
                    continue
                if item[1] != net_name:
                    continue

                at_idx = next(
                    (
                        j
                        for j, p in enumerate(item)
                        if isinstance(p, list) and len(p) >= 3 and p[0] == _SYM_AT
                    ),
                    None,
                )
                if at_idx is None:
                    continue

                at_entry = item[at_idx]
                old_x, old_y = float(at_entry[1]), float(at_entry[2])

                if current_position is not None:
                    cx = current_position.get("x", 0)
                    cy = current_position.get("y", 0)
                    if not (abs(old_x - cx) < TOLERANCE and abs(old_y - cy) < TOLERANCE):
                        continue

                rotation = at_entry[3] if len(at_entry) > 3 else 0
                item[at_idx] = [_SYM_AT, float(new_x), float(new_y), rotation]

                with open(schematic_path, "w", encoding="utf-8") as f:
                    f.write(_sexpdata.dumps(sch_data))

                return {
                    "success": True,
                    "oldPosition": {"x": old_x, "y": old_y},
                    "newPosition": {"x": float(new_x), "y": float(new_y)},
                }

            return {"success": False, "message": f"Label '{net_name}' not found"}

        except Exception as e:
            logger.error(f"Error moving schematic net label: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_export_schematic_svg(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export schematic to SVG using kicad-cli"""
        logger.info("Exporting schematic SVG")
        import glob
        import shutil
        import subprocess

        try:
            schematic_path = params.get("schematicPath")
            output_path = params.get("outputPath")

            if not schematic_path or not output_path:
                return {
                    "success": False,
                    "message": "schematicPath and outputPath are required",
                }

            if not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            # kicad-cli's --output flag for SVG export expects a directory, not a file path.
            # The output file is auto-named based on the schematic name.
            output_dir = os.path.dirname(output_path)
            if not output_dir:
                output_dir = "."

            os.makedirs(output_dir, exist_ok=True)

            cmd = [
                "kicad-cli",
                "sch",
                "export",
                "svg",
                schematic_path,
                "-o",
                output_dir,
            ]

            if params.get("blackAndWhite"):
                cmd.append("--black-and-white")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed: {result.stderr}",
                }

            # kicad-cli names the file after the schematic, so find the generated SVG
            svg_files = glob.glob(os.path.join(output_dir, "*.svg"))
            if not svg_files:
                return {
                    "success": False,
                    "message": "No SVG file produced by kicad-cli",
                }

            generated_svg = svg_files[0]

            # Move/rename to the user-specified output path if it differs
            if os.path.abspath(generated_svg) != os.path.abspath(output_path):
                shutil.move(generated_svg, output_path)

            return {"success": True, "file": {"path": output_path}}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except Exception as e:
            logger.error(f"Error exporting schematic SVG: {e}")
            return {"success": False, "message": str(e)}

    def _handle_get_wire_connections(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Find net name and all component pins reachable from a point or component pin."""
        logger.info("Getting wire connections")
        try:
            from pathlib import Path

            from commands.pin_locator import PinLocator
            from commands.wire_connectivity import get_wire_connections

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "Missing required parameter: schematicPath"}

            reference = params.get("reference")
            pin = params.get("pin")
            x = params.get("x")
            y = params.get("y")

            has_ref_pin = reference is not None and pin is not None
            has_coords = x is not None and y is not None

            if has_ref_pin and has_coords:
                return {
                    "success": False,
                    "message": "Supply either {reference, pin} or {x, y}, not both",
                }

            if not has_ref_pin and not has_coords:
                if reference is not None or pin is not None:
                    return {
                        "success": False,
                        "message": "Both reference and pin are required together",
                    }
                return {
                    "success": False,
                    "message": "Must supply either {reference, pin} or {x, y}",
                }

            if has_ref_pin:
                location = PinLocator().get_pin_location(Path(schematic_path), reference, str(pin))
                if location is None:
                    return {
                        "success": False,
                        "message": f"Pin {pin} not found on {reference}",
                    }
                x, y = location[0], location[1]
            else:
                try:
                    x, y = float(x), float(y)
                except (TypeError, ValueError):
                    return {"success": False, "message": "Parameters x and y must be numeric"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            if not hasattr(schematic, "wire"):
                return {"success": False, "message": "Schematic has no wires"}

            result = get_wire_connections(schematic, schematic_path, x, y)
            if result is None:
                return {
                    "success": False,
                    "message": f"No wire found at ({x},{y}) — point may not be connected",
                }

            return {"success": True, **result}

        except Exception as e:
            logger.error(f"Error getting wire connections: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_texts(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List all free-form text annotations (SCH_TEXT) in a schematic."""
        logger.info("Listing schematic text annotations")
        try:
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            texts = WireManager.list_texts(sch_file)
            if texts is None:
                return {"success": False, "message": "Failed to parse schematic"}

            # Optional text filter
            filter_text = params.get("text")
            if filter_text is not None:
                texts = [t for t in texts if filter_text.lower() in t["text"].lower()]

            return {"success": True, "texts": texts, "count": len(texts)}

        except Exception as e:
            logger.error(f"Error listing schematic texts: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_add_schematic_text(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a free-form text annotation (SCH_TEXT) to a schematic."""
        logger.info("Adding text annotation to schematic")
        try:
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            text = params.get("text")
            position = params.get("position")
            angle = params.get("angle", 0)
            font_size = params.get("fontSize", 1.27)
            bold = params.get("bold", False)
            italic = params.get("italic", False)
            justify = params.get("justify", "left")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not text:
                return {"success": False, "message": "text is required"}
            if not position or len(position) != 2:
                return {"success": False, "message": "position [x, y] is required"}
            if justify not in ("left", "center", "right"):
                return {"success": False, "message": "justify must be left, center, or right"}
            if font_size <= 0:
                return {"success": False, "message": "fontSize must be positive"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            success = WireManager.add_text(
                sch_file,
                text,
                position,
                angle=angle,
                font_size=font_size,
                bold=bold,
                italic=italic,
                justify=justify,
            )

            if success:
                return {
                    "success": True,
                    "message": f"Added text '{text}' at ({position[0]}, {position[1]})",
                    "position": {"x": position[0], "y": position[1]},
                    "angle": angle,
                }
            return {"success": False, "message": "Failed to add text annotation"}

        except Exception as e:
            logger.error(f"Error adding schematic text: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_add_schematic_hierarchical_label(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a hierarchical label to a sub-sheet schematic."""
        logger.info("Adding hierarchical label to schematic")
        try:
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            text = params.get("text")
            position = params.get("position")
            shape = params.get("shape", "bidirectional")
            orientation = params.get("orientation", 0)

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not text:
                return {"success": False, "message": "text is required"}
            if not position or len(position) != 2:
                return {"success": False, "message": "position [x, y] is required"}
            if shape not in ("input", "output", "bidirectional"):
                return {
                    "success": False,
                    "message": "shape must be input, output, or bidirectional",
                }

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            success = WireManager.add_hierarchical_label(
                sch_file, text, position, shape=shape, orientation=orientation
            )

            if success:
                return {
                    "success": True,
                    "message": (
                        f"Added hierarchical_label '{text}' " f"at {position} shape={shape}"
                    ),
                }
            return {"success": False, "message": "Failed to add hierarchical label"}

        except Exception as e:
            logger.error(f"Error adding hierarchical label: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_add_sheet_pin(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a sheet pin to a sheet block on the parent schematic."""
        logger.info("Adding sheet pin to schematic")
        try:
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            sheet_name = params.get("sheetName")
            pin_name = params.get("pinName")
            pin_type = params.get("pinType", "bidirectional")
            position = params.get("position")
            orientation = params.get("orientation", 0)

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not sheet_name:
                return {"success": False, "message": "sheetName is required"}
            if not pin_name:
                return {"success": False, "message": "pinName is required"}
            if not position or len(position) != 2:
                return {"success": False, "message": "position [x, y] is required"}
            if pin_type not in ("input", "output", "bidirectional"):
                return {
                    "success": False,
                    "message": "pinType must be input, output, or bidirectional",
                }

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            modified, success = WireManager.add_sheet_pin(
                content,
                sheet_name,
                pin_name,
                pin_type,
                position,
                orientation=orientation,
            )

            if not success:
                return {
                    "success": False,
                    "message": f"Sheet '{sheet_name}' not found in {schematic_path}",
                }

            with open(sch_file, "w", encoding="utf-8") as f:
                f.write(modified)

            return {
                "success": True,
                "message": (
                    f"Added sheet pin '{pin_name}' ({pin_type}) " f"to sheet '{sheet_name}'"
                ),
            }

        except Exception as e:
            logger.error(f"Error adding sheet pin: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_run_erc(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run Electrical Rules Check on a schematic via kicad-cli"""
        logger.info("Running ERC on schematic")
        import os
        import subprocess
        import tempfile

        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path or not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": "Schematic file not found",
                    "errorDetails": f"Path does not exist: {schematic_path}",
                }

            kicad_cli = self.design_rule_commands._find_kicad_cli()
            if not kicad_cli:
                return {
                    "success": False,
                    "message": "kicad-cli not found",
                    "errorDetails": "Install KiCAD 8.0+ or add kicad-cli to PATH.",
                }

            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
                json_output = tmp.name

            try:
                cmd = [
                    kicad_cli,
                    "sch",
                    "erc",
                    "--format",
                    "json",
                    "--output",
                    json_output,
                    schematic_path,
                ]
                logger.info(f"Running ERC command: {' '.join(cmd)}")

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

                # kicad-cli returns non-zero when ERC violations are found —
                # this is normal, not an error.  Only fail when no JSON was
                # produced (genuine CLI failure).
                if not os.path.exists(json_output) or os.path.getsize(json_output) == 0:
                    logger.error(f"ERC command produced no output: {result.stderr}")
                    return {
                        "success": False,
                        "message": "ERC command failed - no output produced",
                        "errorDetails": result.stderr,
                    }

                with open(json_output, "r", encoding="utf-8") as f:
                    erc_data = json.load(f)

                violations = []
                severity_counts = {"error": 0, "warning": 0, "info": 0}

                # KiCad 9 nests violations under sheets[].violations
                # instead of (or in addition to) the top-level violations
                # array used by KiCad 8.
                all_violations = erc_data.get("violations", [])
                for sheet in erc_data.get("sheets", []):
                    all_violations.extend(sheet.get("violations", []))

                for v in all_violations:
                    vseverity = v.get("severity", "error")
                    items = v.get("items", [])
                    loc = {}
                    if items and "pos" in items[0]:
                        loc = {
                            "x": items[0]["pos"].get("x", 0),
                            "y": items[0]["pos"].get("y", 0),
                        }
                    violations.append(
                        {
                            "type": v.get("type", "unknown"),
                            "severity": vseverity,
                            "message": v.get("description", ""),
                            "location": loc,
                        }
                    )
                    if vseverity in severity_counts:
                        severity_counts[vseverity] += 1

                return {
                    "success": True,
                    "message": f"ERC complete: {len(violations)} violation(s)",
                    "summary": {
                        "total": len(violations),
                        "by_severity": severity_counts,
                    },
                    "violations": violations,
                }

            finally:
                if os.path.exists(json_output):
                    os.unlink(json_output)

        except subprocess.TimeoutExpired:
            return {"success": False, "message": "ERC timed out after 120 seconds"}
        except Exception as e:
            logger.error(f"Error running ERC: {str(e)}")
            return {"success": False, "message": str(e)}

    def _build_hierarchical_pad_net_map(self, project_sch_path: str):
        """Walk all .kicad_sch files in the project and build a {(ref, pin_num): net_name} map.

        Handles hierarchical schematics by scanning every sub-sheet file.  Net names
        from global_label / hierarchical_label / local label / power symbols are all
        collected.  Wire connectivity is traced via BFS so labels not placed directly
        on a pin endpoint still reach through wire segments.

        Returns: (pad_net_map, net_names_set)
        """
        from collections import defaultdict
        from pathlib import Path

        from commands.pin_locator import PinLocator
        from skip import Schematic

        TOLERANCE = 0.5  # mm; schematic grid is 1.27 mm so 0.5 is safe

        def snap(x, y):
            """Round to 2 dp to use exact dict lookup instead of O(n²) scan."""
            return (round(float(x), 2), round(float(y), 2))

        def nearby_net(pt, point_net, tol=TOLERANCE):
            """Return net name for the nearest occupied grid point, or None."""
            x, y = pt
            # Try exact snap first (fast path)
            key = snap(x, y)
            if key in point_net:
                return point_net[key]
            # Slow fallback for off-grid placements
            for (lx, ly), name in point_net.items():
                if abs(x - lx) < tol and abs(y - ly) < tol:
                    return name
            return None

        project_dir = Path(project_sch_path).parent
        pad_net_map: dict = {}
        all_net_names: set = set()
        pin_locator = PinLocator()

        sch_files = sorted(project_dir.rglob("*.kicad_sch"))
        logger.info(f"_build_hierarchical_pad_net_map: scanning {len(sch_files)} schematic files")

        for sch_path in sch_files:
            try:
                sch = Schematic(str(sch_path))
            except Exception as e:
                logger.warning(f"Could not load {sch_path}: {e}")
                continue

            # ── 1. Collect explicit label positions → net name ──────────────
            point_net: dict = {}  # snap(x,y) -> net_name

            for attr in ("label", "global_label", "hierarchical_label"):
                for lbl in getattr(sch, attr, None) or []:
                    try:
                        pos = lbl.at.value
                        name = lbl.value
                        if name:
                            k = snap(pos[0], pos[1])
                            point_net[k] = name
                            all_net_names.add(name)
                    except Exception:
                        pass

            # Power symbols (#PWR / #FLG): value property IS the net name; use pin 1 pos
            for sym in getattr(sch, "symbol", None) or []:
                try:
                    ref = sym.property.Reference.value
                    if not (ref.startswith("#PWR") or ref.startswith("#FLG")):
                        continue
                    net_name = sym.property.Value.value
                    if not net_name:
                        continue
                    all_pins = pin_locator.get_all_symbol_pins(sch_path, ref)
                    for _pin_num, (px, py) in all_pins.items():
                        k = snap(px, py)
                        point_net[k] = net_name
                        all_net_names.add(net_name)
                except Exception:
                    pass

            # ── 2. Build wire adjacency and BFS-propagate net names ──────────
            wire_segments = []
            for wire in getattr(sch, "wire", None) or []:
                try:
                    pts = []
                    for pt in wire.pts.xy:
                        pts.append(snap(pt.value[0], pt.value[1]))
                    if len(pts) >= 2:
                        wire_segments.append(pts)
                except Exception:
                    pass

            # Adjacency: connect endpoints of different segments that share a grid point
            point_adj: dict = defaultdict(set)
            for seg in wire_segments:
                # Connect consecutive points within the segment
                for i in range(len(seg) - 1):
                    point_adj[seg[i]].add(seg[i + 1])
                    point_adj[seg[i + 1]].add(seg[i])

            # All unique wire points
            all_wire_pts = set()
            for seg in wire_segments:
                all_wire_pts.update(seg)

            # BFS: propagate known net names through wire connections
            queue = [pt for pt in all_wire_pts if pt in point_net]
            visited = set(queue)
            while queue:
                pt = queue.pop()
                net = point_net[pt]
                for neighbor in point_adj[pt]:
                    if neighbor not in point_net:
                        point_net[neighbor] = net
                        all_net_names.add(net)
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)

            # ── 3. Match component pin positions to net names ────────────────
            for sym in getattr(sch, "symbol", None) or []:
                try:
                    ref = sym.property.Reference.value
                    if ref.startswith("#"):
                        continue
                except Exception:
                    continue

                pin_positions = pin_locator.get_all_symbol_pins(sch_path, ref)
                for pin_num, (px, py) in pin_positions.items():
                    net = nearby_net((px, py), point_net)
                    if net:
                        pad_net_map[(ref, pin_num)] = net

        logger.info(
            f"_build_hierarchical_pad_net_map: {len(pad_net_map)} pin→net assignments, "
            f"{len(all_net_names)} unique nets"
        )
        return pad_net_map, all_net_names

    def _handle_sync_schematic_to_board(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Sync schematic netlist to PCB board (equivalent to KiCAD F8 'Update PCB from Schematic').
        Reads net connections from the schematic and assigns them to the matching pads in the PCB.
        """
        logger.info("Syncing schematic to board")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            board_path = params.get("boardPath")

            # Determine board to work with
            board = None
            if board_path:
                board = self._safe_load_board(board_path)
                if board is None:
                    return {
                        "success": False,
                        "message": f"Could not load board from {board_path}",
                        "errorDetails": (
                            "pcbnew.LoadBoard failed or returned a dehydrated "
                            "SWIG proxy that could not be recovered"
                        ),
                    }
            elif self.board:
                board = self.board
                board_path = board.GetFileName() if not board_path else board_path
            else:
                return {
                    "success": False,
                    "message": "No board loaded. Use open_project first or provide boardPath.",
                }

            if not board_path:
                board_path = board.GetFileName()

            # Determine schematic path if not provided
            if not schematic_path:
                sch = Path(board_path).with_suffix(".kicad_sch")
                if sch.exists():
                    schematic_path = str(sch)
                else:
                    project_dir = Path(board_path).parent
                    sch_files = list(project_dir.glob("*.kicad_sch"))
                    if sch_files:
                        schematic_path = str(sch_files[0])

            if not schematic_path or not Path(schematic_path).exists():
                return {
                    "success": False,
                    "message": f"Schematic not found. Provide schematicPath. Tried: {schematic_path}",
                }

            # Build hierarchical pad→net map (walks all sub-sheets)
            pad_net_map, net_names = self._build_hierarchical_pad_net_map(schematic_path)

            # Add missing footprints from the schematic to the board *before*
            # we add nets and assign pads — F8 in KiCad does this implicitly
            # ("Update PCB from Schematic"), but our previous implementation
            # only mutated nets, leaving newly-added schematic symbols with no
            # PCB footprint at all.
            added_footprints, skipped_footprints = self._add_missing_footprints_from_schematic(
                board, schematic_path
            )

            # Add all nets to board
            netinfo = board.GetNetInfo()
            nets_by_name = netinfo.NetsByName()
            added_nets = []
            for net_name in net_names:
                if not nets_by_name.has_key(net_name):
                    net_item = pcbnew.NETINFO_ITEM(board, net_name)
                    board.Add(net_item)
                    added_nets.append(net_name)

            # Refresh nets map after additions
            netinfo = board.GetNetInfo()
            nets_by_name = netinfo.NetsByName()

            # Assign nets to pads (now also covers any footprints we just added)
            assigned_pads = 0
            unmatched = []
            for fp in board.GetFootprints():
                ref = fp.GetReference()
                for pad in fp.Pads():
                    pad_num = pad.GetNumber()
                    key = (ref, str(pad_num))
                    if key in pad_net_map:
                        net_name = pad_net_map[key]
                        if nets_by_name.has_key(net_name):
                            pad.SetNet(nets_by_name[net_name])
                            assigned_pads += 1
                    else:
                        unmatched.append(f"{ref}/{pad_num}")

            board.Save(board_path)

            # If board was loaded fresh, update internal reference
            if params.get("boardPath"):
                self.board = board
                self._update_command_handlers()

            logger.info(
                f"sync_schematic_to_board: {len(added_nets)} nets added, "
                f"{len(added_footprints)} footprints added, {assigned_pads} pads assigned"
            )
            return {
                "success": True,
                "message": (
                    f"PCB updated from schematic: {len(added_footprints)} footprints added, "
                    f"{len(added_nets)} nets added, {assigned_pads} pads assigned"
                ),
                "nets_added": added_nets,
                "nets_total": len(net_names),
                "pads_assigned": assigned_pads,
                "unmatched_pads_sample": unmatched[:10],
                "footprints_added": added_footprints,
                "footprints_skipped": skipped_footprints,
            }

        except Exception as e:
            logger.error(f"Error in sync_schematic_to_board: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _extract_components_from_schematic(self, schematic_path: str) -> List[Dict[str, str]]:
        """Run kicad-cli netlist export and return the flat list of components.

        Each entry: {"reference": str, "value": str, "footprint": str}
        Empty list on any failure (kicad-cli missing, parse error, etc.) — the
        caller treats that as "no missing footprints to add".
        """
        import subprocess
        import tempfile
        import xml.etree.ElementTree as ET

        kicad_cli = self._find_kicad_cli_static()
        if not kicad_cli:
            logger.warning("kicad-cli not found — sync will not add new footprints")
            return []

        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            cmd = [
                kicad_cli,
                "sch",
                "export",
                "netlist",
                "--format",
                "kicadxml",
                "--output",
                tmp_path,
                schematic_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                logger.warning(
                    f"kicad-cli netlist export failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}"
                )
                return []

            tree = ET.parse(tmp_path)
            root = tree.getroot()
            components = []
            for comp in root.findall("./components/comp"):
                components.append(
                    {
                        "reference": comp.get("ref", ""),
                        "value": comp.findtext("value", ""),
                        "footprint": comp.findtext("footprint", ""),
                    }
                )
            return components
        except Exception as e:
            logger.warning(f"Failed to extract components from schematic: {e}")
            return []
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _add_missing_footprints_from_schematic(
        self, board: Any, schematic_path: str
    ) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """Add footprints to ``board`` for any schematic component not yet present.

        New footprints are placed at the board origin so the user can move them
        into position. Power/flag references (``#PWR``, ``#FLG``) are skipped —
        they have no PCB representation.

        Returns ``(added, skipped)``: each entry is
        ``{"reference": str, "footprint": str, "reason": str?}``.
        """
        from pathlib import Path

        from commands.library import LibraryManager

        added: List[Dict[str, str]] = []
        skipped: List[Dict[str, str]] = []

        components = self._extract_components_from_schematic(schematic_path)
        if not components:
            return added, skipped

        existing_refs = {fp.GetReference() for fp in board.GetFootprints()}
        project_dir = Path(schematic_path).parent
        library_manager = LibraryManager(project_path=project_dir)

        for comp in components:
            ref = comp["reference"]
            fp_str = comp["footprint"]
            if not ref or ref.startswith("#"):
                # Power flags / global indicators — no PCB footprint expected.
                continue
            if ref in existing_refs:
                continue
            if not fp_str or ":" not in fp_str:
                skipped.append(
                    {
                        "reference": ref,
                        "footprint": fp_str,
                        "reason": "no Library:Name footprint set on schematic symbol",
                    }
                )
                continue

            lib_name, fp_name = fp_str.split(":", 1)
            library_path = library_manager.libraries.get(lib_name)
            if not library_path:
                skipped.append(
                    {
                        "reference": ref,
                        "footprint": fp_str,
                        "reason": f"library '{lib_name}' not in fp-lib-table",
                    }
                )
                continue

            try:
                module = pcbnew.FootprintLoad(library_path, fp_name)
            except Exception as e:
                skipped.append(
                    {"reference": ref, "footprint": fp_str, "reason": f"FootprintLoad failed: {e}"}
                )
                continue

            if not module:
                skipped.append(
                    {
                        "reference": ref,
                        "footprint": fp_str,
                        "reason": f"footprint '{fp_name}' not in '{lib_name}'",
                    }
                )
                continue

            module.SetReference(ref)
            if comp["value"]:
                module.SetValue(comp["value"])
            module.SetFPID(pcbnew.LIB_ID(lib_name, fp_name))
            # Place at board origin; user / autoplacer can position from there.
            module.SetPosition(pcbnew.VECTOR2I(0, 0))

            board.Add(module)
            existing_refs.add(ref)
            added.append({"reference": ref, "footprint": fp_str})

        if added:
            logger.info(f"_add_missing_footprints_from_schematic: added {len(added)} footprints")
        return added, skipped

    def _handle_get_schematic_view_region(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export a cropped region of the schematic as an image"""
        logger.info("Exporting schematic view region")
        import base64
        import os
        import subprocess
        import tempfile

        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path or not os.path.exists(schematic_path):
                return {"success": False, "message": "Schematic file not found"}

            x1 = float(params.get("x1", 0))
            y1 = float(params.get("y1", 0))
            x2 = float(params.get("x2", 297))
            y2 = float(params.get("y2", 210))
            x1, x2 = min(x1, x2), max(x1, x2)
            y1, y2 = min(y1, y2), max(y1, y2)
            out_format = params.get("format", "png")
            width = int(params.get("width", 800))
            height = int(params.get("height", 600))

            kicad_cli = self.design_rule_commands._find_kicad_cli()
            if not kicad_cli:
                return {"success": False, "message": "kicad-cli not found"}

            tmp_dir = tempfile.mkdtemp()
            svg_output = None

            try:
                cmd = [
                    kicad_cli,
                    "sch",
                    "export",
                    "svg",
                    "--output",
                    tmp_dir,
                    schematic_path,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

                if result.returncode != 0:
                    return {
                        "success": False,
                        "message": f"SVG export failed: {result.stderr}",
                    }

                # kicad-cli names the file after the schematic
                svg_files = [f for f in os.listdir(tmp_dir) if f.endswith(".svg")]
                if not svg_files:
                    return {
                        "success": False,
                        "message": "kicad-cli produced no SVG output",
                    }
                svg_output = os.path.join(tmp_dir, svg_files[0])

                import xml.etree.ElementTree as ET

                tree = ET.parse(svg_output)
                root = tree.getroot()

                # KiCad schematic SVGs use mm as viewBox units directly
                vb = root.get("viewBox", "")
                if vb:
                    parts = vb.split()
                    if len(parts) == 4:
                        orig_vb_x = float(parts[0])
                        orig_vb_y = float(parts[1])

                        new_x = orig_vb_x + x1
                        new_y = orig_vb_y + y1
                        new_w = x2 - x1
                        new_h = y2 - y1

                        root.set("viewBox", f"{new_x} {new_y} {new_w} {new_h}")
                        root.set("width", str(width))
                        root.set("height", str(height))

                # Write modified SVG
                cropped_svg_path = os.path.join(tmp_dir, "cropped.svg")
                tree.write(cropped_svg_path, xml_declaration=True, encoding="utf-8")

                if out_format == "svg":
                    with open(cropped_svg_path, "r", encoding="utf-8") as f:
                        svg_data = f.read()
                    return {"success": True, "imageData": svg_data, "format": "svg"}
                else:
                    png_data = _svg_to_png(cropped_svg_path, width, height)
                    if png_data is None:
                        return {
                            "success": False,
                            "message": "No PNG converter available. Install pymupdf, inkscape, or imagemagick.",
                        }
                    return {
                        "success": True,
                        "imageData": base64.b64encode(png_data).decode("utf-8"),
                        "format": "png",
                    }
            finally:
                import shutil

                shutil.rmtree(tmp_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"Error in get_schematic_view_region: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_find_wires_crossing_symbols(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Find wires that cross over component symbol bodies"""
        logger.info("Finding wires crossing symbols in schematic")
        try:
            from pathlib import Path

            from commands.schematic_analysis import find_wires_crossing_symbols

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            result = find_wires_crossing_symbols(Path(schematic_path))
            return {
                "success": True,
                "collisions": result,
                "count": len(result),
                "message": f"Found {len(result)} wire(s) crossing symbols",
            }
        except Exception as e:
            logger.error(f"Error checking wire collisions: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_find_orphaned_wires(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Find wire segments with at least one dangling (unconnected) endpoint"""
        logger.info("Finding orphaned wires in schematic")
        try:
            from pathlib import Path

            from commands.schematic_analysis import find_orphaned_wires

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            result = find_orphaned_wires(Path(schematic_path))
            return {
                "success": True,
                **result,
                "message": f"Found {result['count']} orphaned wire(s)",
            }
        except Exception as e:
            logger.error(f"Error finding orphaned wires: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_floating_labels(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List net labels that are not connected to any component pin"""
        logger.info("Listing floating net labels in schematic")
        try:
            from commands.wire_connectivity import list_floating_labels

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            labels = list_floating_labels(schematic, schematic_path)
            return {
                "success": True,
                "floating_labels": labels,
                "count": len(labels),
                "message": f"Found {len(labels)} floating label(s)",
            }
        except Exception as e:
            logger.error(f"Error listing floating labels: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_snap_to_grid(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Snap schematic element coordinates to the nearest grid point"""
        logger.info("Snapping schematic elements to grid")
        try:
            from pathlib import Path

            from commands.schematic_snap import snap_to_grid

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            grid_size = float(params.get("gridSize", 1.27))
            elements = params.get("elements")  # None → defaults inside snap_to_grid

            result = snap_to_grid(Path(schematic_path), grid_size=grid_size, elements=elements)
            total = result["snapped"] + result["already_on_grid"]
            return {
                "success": True,
                **result,
                "message": (
                    f"Snapped {result['snapped']} element(s) to {grid_size} mm grid "
                    f"({result['already_on_grid']} of {total} were already on grid)"
                ),
            }
        except Exception as e:
            logger.error(f"Error snapping to grid: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}
