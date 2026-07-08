"""
Replace instance lib_ids in KiCad schematics — library migration helper.

Handles the mechanical work of swapping lib_id references in schematic
instances, including mirror-variant angle correction (__m0/__m90/__m180/__m270).
Matching logic belongs in callers (Hermes skills), not here.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

MIRROR_TO_ANGLE = {"__m0": 0, "__m90": 90, "__m180": 180, "__m270": 270}


class SymbolSchematicCommands:
    """Commands for schematic symbol instance manipulation."""

    def replace_instance_lib_ids(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Replace lib_id references in schematic instances.

        Params
        ------
        schematic_path : path to .kicad_sch file (required)
        mapping        : dict {old_full_lib_id: new_full_lib_id} (required)
                         e.g. {"eagle_import:1-RCL-EIGEN_C": "FOG_components:C_100nF_0402"}
        source_library : old library prefix (default "eagle_import")
        target_library : new library prefix (default "FOG_components")
        """
        sch_path = params.get("schematic_path")
        mapping: Dict[str, str] = params.get("mapping", {})
        source_lib = params.get("source_library", "eagle_import")
        target_lib = params.get("target_library", "FOG_components")

        if not sch_path:
            return {"success": False, "error": "schematic_path is required"}
        if not mapping:
            return {"success": False, "error": "mapping dict is required"}
        if not os.path.exists(sch_path):
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
            def _replace(m: re.Match) -> str:
                nonlocal replaced
                full = m.group(0)
                lib_id = m.group(1)
                x, y = m.group(2), m.group(3)
                old_angle = int(m.group(4))

                # strip mirror suffix, track angle offset
                base = lib_id
                angle_offset = 0
                for suffix, offset in MIRROR_TO_ANGLE.items():
                    if base.endswith(suffix):
                        base = base[: -len(suffix)]
                        angle_offset = offset
                        break

                full_key = f"{source_lib}:{lib_id}"
                if full_key not in mapping:
                    return full

                new_lib = mapping[full_key].split(":", 1)[-1]
                new_angle = (old_angle + angle_offset) % 360

                result = full.replace(
                    f"{source_lib}:{lib_id}", f"{target_lib}:{new_lib}", 1
                )
                if angle_offset != 0:
                    result = result.replace(
                        f"(at {x} {y} {old_angle})",
                        f"(at {x} {y} {new_angle})",
                        1,
                    )
                replaced += 1
                return result

            pattern = re.compile(
                r'\(symbol\s*\n\s*\(lib_id "'
                + re.escape(source_lib)
                + r':([^"]+)"\)\s*\n\s*\(at ([\d.-]+) ([\d.-]+) (\d+)\)',
                re.DOTALL,
            )

            inst_part = pattern.sub(_replace, inst_part)

            new_content = lib_part + inst_part
            Path(sch_path).write_text(new_content, encoding="utf-8", newline="\n")

            remaining = inst_part.count(f"{source_lib}:")

            return {
                "success": True,
                "replaced": replaced,
                "remaining_eagle": remaining,
                "message": (
                    f"Replaced {replaced} instance lib_ids, {remaining} remaining"
                ),
            }

        except Exception:
            logger.exception("replace_instance_lib_ids failed")
            return {"success": False, "error": "Replacement error (see log)"}
