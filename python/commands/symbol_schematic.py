"""
Replace instance lib_ids in KiCad schematics — library migration helper.

Handles the mechanical work of swapping lib_id references in schematic
instances, including mirror-variant angle correction (__m0/__m90/__m180/__m270
suffixes produced by the Eagle importer's mirror cache). Which symbol maps to
which — by type, value, footprint — is the caller's decision; this tool only
applies a given mapping.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("kicad_interface")

MIRROR_TO_ANGLE = {"__m0": 0, "__m90": 90, "__m180": 180, "__m270": 270}


class SymbolSchematicCommands:
    """Commands for schematic symbol instance manipulation."""

    def replace_instance_lib_ids(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Replace lib_id references in schematic instances.

        Params
        ------
        schematicPath : path to .kicad_sch file (required)
        mapping       : dict {old_full_lib_id: new_full_lib_id} (required),
                        e.g. {"eagle_import:1-RCL-EIGEN_C": "project_lib:C_100nF_0402"}.
                        Values are used verbatim, so one migration may target
                        several libraries. Mirror-variant instances
                        (…__m90 etc.) need their own entries — the variant
                        chooses both the target symbol and the angle offset.
        sourceLibrary : library prefix whose instances are candidates
                        (default "eagle_import", the Eagle importer's output)

        Only instances are rewritten; the lib_symbols section is preserved
        (use update_symbol_from_library to refresh definitions).
        """
        sch_path = params.get("schematicPath")
        mapping: Dict[str, str] = params.get("mapping", {})
        source_lib = params.get("sourceLibrary", "eagle_import")

        if not sch_path:
            return {"success": False, "error": "schematicPath is required"}
        if not mapping:
            return {"success": False, "error": "mapping dict is required"}
        if not Path(sch_path).exists():
            return {"success": False, "error": f"File not found: {sch_path}"}

        try:
            content = Path(sch_path).read_text(encoding="utf-8")

            # ── find lib_symbols / instance boundary ──
            lib_start = content.find("(lib_symbols")
            if lib_start < 0:
                return {"success": False, "error": "lib_symbols section not found"}

            depth = 0
            lib_end = None
            for i in range(lib_start, len(content)):
                if content[i] == "(":
                    depth += 1
                elif content[i] == ")":
                    depth -= 1
                    if depth == 0:
                        lib_end = i
                        break
            if lib_end is None:
                return {"success": False, "error": "Cannot find end of lib_symbols"}

            lib_part = content[: lib_end + 1]
            inst_part = content[lib_end + 1 :]

            replaced = 0

            # ── per-instance replacer ──
            def _replace(m: "re.Match[str]") -> str:
                nonlocal replaced
                full = m.group(0)
                lib_id = m.group(1)
                x, y = m.group(2), m.group(3)
                old_angle = int(m.group(4))

                full_key = f"{source_lib}:{lib_id}"
                if full_key not in mapping:
                    return full

                # A mirror-variant suffix contributes an angle offset; the
                # mapping entry (keyed on the full suffixed id) supplies the
                # target lib_id.
                angle_offset = 0
                for suffix, offset in MIRROR_TO_ANGLE.items():
                    if lib_id.endswith(suffix):
                        angle_offset = offset
                        break

                # The mapping value is the complete replacement lib_id, used
                # verbatim — different entries may target different libraries.
                new_full_id = mapping[full_key]
                new_angle = (old_angle + angle_offset) % 360

                result = full.replace(full_key, new_full_id, 1)
                if angle_offset != 0:
                    result = result.replace(
                        f"(at {x} {y} {old_angle})",
                        f"(at {x} {y} {new_angle})",
                        1,
                    )
                replaced += 1
                return result

            # Both header layouts KiCad-family writers produce:
            #   (symbol\n  (lib_id "…")\n  (at x y a)   — KiCad GUI / Eagle import
            #   (symbol (lib_id "…") (at x y a)         — this repo's dynamic loader
            pattern = re.compile(
                r'\(symbol\s+\(lib_id "'
                + re.escape(source_lib)
                + r':([^"]+)"\)\s+\(at ([\d.-]+) ([\d.-]+) (\d+)\)',
            )

            inst_part = pattern.sub(_replace, inst_part)

            new_content = lib_part + inst_part
            with Path(sch_path).open("w", encoding="utf-8", newline="\n") as f:
                f.write(new_content)

            remaining = inst_part.count(f'(lib_id "{source_lib}:')

            return {
                "success": True,
                "replaced": replaced,
                "remaining": remaining,
                "message": (
                    f"Replaced {replaced} instance lib_ids, "
                    f"{remaining} {source_lib}: instance(s) remaining"
                ),
            }

        except Exception as e:
            logger.exception("replace_instance_lib_ids failed")
            return {"success": False, "error": f"Replacement error: {e}"}
