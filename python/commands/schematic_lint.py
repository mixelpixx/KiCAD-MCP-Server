"""Netlist-safe cosmetic lint for .kicad_sch files (lint_schematic_cosmetic).

Two passes, both applied as raw-text edits that never move a symbol, pin,
wire, junction, or label ANCHOR — only display attributes change, so the
netlist is preserved by construction:

  * hide_pin_names — ensure every top-level embedded lib_symbol definition
    (name contains ':'; sub-units and placed instances skipped) has a
    ``(pin_names ... (hide yes))`` directive, inserting
    ``(pin_names (offset 1.016) (hide yes))`` when the block is absent.
    In label-driven schematics the symbol's internal pin names duplicate the
    net label sitting on the same pin.

  * orient_labels — for every label/global_label/hierarchical_label whose
    anchor coincides with a component pin endpoint, rewrite only the text
    angle and justify so the text reads AWAY from the symbol body. Pin
    sheet positions and outward angles come from PinLocator
    (get_all_symbol_pins / get_pin_angle), which applies the full
    mirror/rotation-aware transform — rotated and mirrored instances are
    handled. Labels not sitting on a pin are counted and left untouched.

Field repositioning (Reference/Value) is autoplace_schematic_fields' job,
not this tool's.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("kicad_interface")

_PASSES = ("hide_pin_names", "orient_labels")

# pin sheet-space outward angle -> (label text angle, justify), field-validated.
_ORIENT = {
    0: (180, "right"),  # pin on left edge  -> text extends left
    180: (0, "left"),  # pin on right edge -> text extends right
    90: (270, "right"),  # pin on top edge   -> text reads upward
    270: (90, "left"),  # pin on bottom edge-> text reads downward
}


def _find_blocks(src: str, opener: str) -> List[Tuple[int, int]]:
    """Spans (start, end_exclusive) of balanced-paren blocks starting with
    ``opener``. String-aware: parens inside quoted strings are ignored."""
    out: List[Tuple[int, int]] = []
    i = 0
    while True:
        j = src.find(opener, i)
        if j < 0:
            break
        depth = 0
        k = j
        in_str = esc = False
        while k < len(src):
            c = src[k]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    out.append((j, k + 1))
                    break
            k += 1
        i = k + 1
    return out


def _hide_pin_names(src: str) -> Tuple[str, int]:
    """Ensure every top-level embedded lib_symbol def hides its pin names.

    Only defs whose name contains ':' (real Lib:Part ids) are touched;
    sub-units like PART_1_1 and placed instances are skipped. Display
    attribute only — no geometry, no connectivity impact. Idempotent.
    """
    n = 0
    lib_blocks = _find_blocks(src, "(lib_symbols")
    if not lib_blocks:
        return src, 0
    lib_s, lib_e = lib_blocks[0]
    section = src[lib_s:lib_e]
    defs = []
    for s, e in _find_blocks(section, '(symbol "'):
        m = re.match(r'\(symbol "([^"]*)"', section[s:e])
        if m and ":" in m.group(1):
            defs.append((s, e))
    # right-to-left so earlier spans stay valid
    for s, e in reversed(defs):
        blk = section[s:e]
        # this def's OWN pin_names = the first (pin_names before any sub-unit
        sub = blk.find('(symbol "', 1)
        header = blk if sub < 0 else blk[:sub]
        pn = header.find("(pin_names")
        if pn >= 0:
            for ps, pe in _find_blocks(blk, "(pin_names"):
                if ps == pn:
                    if "hide" not in blk[ps:pe]:
                        blk = (
                            blk[: pe - 1].rstrip()
                            + "\n\t\t\t\t(hide yes)\n\t\t\t)"
                            + blk[pe:]
                        )
                        n += 1
                    break
        else:
            nl = blk.find("\n")
            blk = (
                blk[: nl + 1]
                + "\t\t\t(pin_names\n\t\t\t\t(offset 1.016)\n\t\t\t\t(hide yes)\n\t\t\t)\n"
                + blk[nl + 1 :]
            )
            n += 1
        section = section[:s] + blk + section[e:]
    return src[:lib_s] + section + src[lib_e:], n


def _build_pin_orient_map(sch_path: Path) -> Dict[Tuple[float, float], int]:
    """(round(x,2), round(y,2)) -> outward angle (0/90/180/270) for every
    placed component pin, via the mirror/rotation-aware PinLocator."""
    from commands.pin_locator import PinLocator
    from commands.schematic import SchematicManager

    # Fresh locator per call: PinLocator caches parsed schematics by path
    # with no mtime invalidation, so a shared instance could serve stale
    # geometry after other edits.
    locator = PinLocator()
    sch = SchematicManager.load_schematic(str(sch_path))

    pin_map: Dict[Tuple[float, float], int] = {}
    for symbol in getattr(sch, "symbol", None) or []:
        try:
            if not hasattr(symbol, "property") or not hasattr(
                symbol.property, "Reference"
            ):
                continue
            ref = symbol.property.Reference.value
            if ref.startswith("_TEMPLATE"):
                continue
            pin_locations = locator.get_all_symbol_pins(sch_path, ref)
            for pin_num, coords in pin_locations.items():
                angle = locator.get_pin_angle(sch_path, ref, pin_num)
                if angle is None:
                    continue
                rounded = int(round(angle / 90.0) * 90) % 360
                if min(abs(angle - rounded) % 360, 360 - abs(angle - rounded) % 360) > 1:
                    continue  # non-cardinal pin; skip
                pin_map[(round(coords[0], 2), round(coords[1], 2))] = rounded
        except Exception as e:
            logger.warning(f"orient_labels: skipping symbol pins: {e}")
    return pin_map


def _orient_labels(
    src: str, pin_map: Dict[Tuple[float, float], int]
) -> Tuple[str, int, int]:
    """Rewrite label text angle + justify from the pin each label sits on.

    The anchor coordinates are never touched. Returns
    (new_src, oriented_count, skipped_not_on_pin).
    """
    n = 0
    skipped = 0
    for opener in ('(global_label "', '(hierarchical_label "', '(label "'):
        for s, e in reversed(_find_blocks(src, opener)):
            blk = src[s:e]
            at = re.search(r"(\(at )(-?[\d.]+) (-?[\d.]+) (-?[\d.]+)(\))", blk)
            if not at:
                continue
            key = (round(float(at.group(2)), 2), round(float(at.group(3)), 2))
            if key not in pin_map:
                skipped += 1
                continue
            angle, justify = _ORIENT[pin_map[key]]
            new = blk
            if float(at.group(4)) != angle:
                new = (
                    new[: at.start()]
                    + f"{at.group(1)}{at.group(2)} {at.group(3)} {angle}{at.group(5)}"
                    + new[at.end() :]
                )
            jm = re.search(r"\(justify [^)]*\)", new)
            if jm:
                new = new[: jm.start()] + f"(justify {justify})" + new[jm.end() :]
            else:
                fm = re.search(r"(\(font\s*\(size [\d.]+ [\d.]+\)\s*\))", new)
                if fm:
                    new = new[: fm.end()] + f"\n\t\t\t(justify {justify})" + new[fm.end() :]
            if new != blk:
                src = src[:s] + new + src[e:]
                n += 1
    return src, n, skipped


class SchematicLintCommands:
    """Handler for the lint_schematic_cosmetic MCP tool."""

    def lint_schematic_cosmetic(self, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from commands.schematic import SchematicLoadError

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not os.path.isfile(schematic_path):
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            passes = params.get("passes", list(_PASSES))
            unknown = [p for p in passes if p not in _PASSES]
            if unknown:
                return {
                    "success": False,
                    "message": (
                        f"Unknown pass(es): {', '.join(unknown)}. "
                        f"Valid passes: {', '.join(_PASSES)}"
                    ),
                }
            dry_run = bool(params.get("dryRun", False))

            with open(schematic_path, "r", encoding="utf-8") as f:
                src = f.read()
            original = src

            counts = {p: 0 for p in _PASSES}
            skipped_labels = 0
            for pass_name in passes:
                if pass_name == "hide_pin_names":
                    src, counts["hide_pin_names"] = _hide_pin_names(src)
                elif pass_name == "orient_labels":
                    try:
                        pin_map = _build_pin_orient_map(Path(schematic_path))
                    except SchematicLoadError as e:
                        return e.to_response()
                    src, counts["orient_labels"], skipped_labels = _orient_labels(
                        src, pin_map
                    )

            changed = src != original
            if changed and not dry_run:
                with open(schematic_path, "w", encoding="utf-8") as f:
                    f.write(src)

            message_parts = []
            if "hide_pin_names" in passes:
                message_parts.append(
                    f"hide_pin_names: {counts['hide_pin_names']} def(s) hidden"
                )
            if "orient_labels" in passes:
                message_parts.append(
                    f"orient_labels: {counts['orient_labels']} label(s) reoriented "
                    f"({skipped_labels} not on a pin, untouched)"
                )
            message = "; ".join(message_parts)
            if dry_run:
                message = f"[dry run] {message}"

            return {
                "success": True,
                "dryRun": dry_run,
                "changed": changed,
                "counts": {p: counts[p] for p in passes},
                "skippedLabels": skipped_labels,
                "message": message,
            }
        except Exception as e:
            import traceback

            logger.error(f"lint_schematic_cosmetic failed: {e}")
            return {
                "success": False,
                "message": f"lint_schematic_cosmetic failed: {e}",
                "errorDetails": traceback.format_exc(),
            }
