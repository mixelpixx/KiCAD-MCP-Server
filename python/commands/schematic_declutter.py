"""Schematic label declutter — re-orient overlapping net/global labels so their
text lands in free space and becomes readable.

Phase 1: net/global labels only. Free-form text, Ref/Value fields, and symbol
spreading + wire reroute are deliberately separate, later phases.

Why labels and not "placement": a net label's (at x y) IS its electrical
connection point. Moving the anchor off its wire would disconnect the net. So
this tool holds every label's anchor FIXED and only changes its orientation
(0/90/180/270) and justification — which side the text renders toward. That
throws the text into empty space without touching connectivity.

Dry run by default (mirrors suggest_placement): returns proposals
{name, at, from_angle -> to_angle} plus an overlap score, WITHOUT modifying the
schematic. Set apply=true to rewrite the label blocks.

Symbol spreading + wire reroute is a deliberately separate, later phase — it
changes geometry and must rebuild wires/junctions, which is far riskier.

The geometry is kept as module-level pure functions so it is unit-testable
without a live KiCad / kicad-skip environment.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("kicad_interface")

_GRID = 1.27  # 50-mil KiCad schematic grid (mm)
_CHARS_PER_MM = 1.5  # matches schematic_field_layout's label_bbox model
_TEXT_HEIGHT = 1.27
_ORIENTATIONS = (0, 90, 180, 270)


# ──────────────────────────────────────────────────────────────────────────
#  Pure geometry (unit-testable, no KiCad deps)
# ──────────────────────────────────────────────────────────────────────────
def _label_bbox(lx: float, ly: float, angle: float, name: str) -> Dict[str, float]:
    """Axis-aligned bbox of a label's text, anchored at (lx, ly), for one of the
    four orientations. Mirrors schematic_field_layout.label_bbox so overlap
    results stay consistent with the rest of the codebase."""
    length = max(len(name), 1) * _CHARS_PER_MM + 1.0
    half_h = _TEXT_HEIGHT / 2.0
    a = round(angle / 90) * 90 % 360
    if a == 0:  # text extends +x (justify left)
        return {"x_min": lx, "y_min": ly - half_h, "x_max": lx + length, "y_max": ly + half_h}
    if a == 90:  # text extends -y (up)
        return {"x_min": lx - half_h, "y_min": ly - length, "x_max": lx + half_h, "y_max": ly}
    if a == 180:  # text extends -x (justify right)
        return {"x_min": lx - length, "y_min": ly - half_h, "x_max": lx, "y_max": ly + half_h}
    return {"x_min": lx - half_h, "y_min": ly, "x_max": lx + half_h, "y_max": ly + length}


def _bbox_overlaps(a: Dict[str, float], b: Dict[str, float], margin: float = 0.0) -> bool:
    return (
        a["x_min"] - margin < b["x_max"]
        and a["x_max"] + margin > b["x_min"]
        and a["y_min"] - margin < b["y_max"]
        and a["y_max"] + margin > b["y_min"]
    )


def _justify_for_angle(angle: float) -> str:
    """KiCad flips horizontal justification for the left-pointing orientations."""
    a = round(angle / 90) * 90 % 360
    return "right" if a in (180, 270) else "left"


def _best_orientation(
    label: Dict[str, Any],
    obstacles: List[Dict[str, float]],
    margin: float,
) -> Tuple[int, int]:
    """Pick the orientation whose text bbox collides with the fewest obstacles.
    Ties prefer the label's CURRENT angle (stability), then 0/180 over 90/270
    (horizontal text reads easier). Returns (angle, collision_count)."""
    lx, ly, name = label["x"], label["y"], label["name"]
    cur = round(label["angle"] / 90) * 90 % 360

    def collisions(angle: int) -> int:
        bb = _label_bbox(lx, ly, angle, name)
        return sum(1 for ob in obstacles if _bbox_overlaps(bb, ob, margin))

    best_angle, best_n, best_rank = cur, collisions(cur), (0, 0)
    for angle in _ORIENTATIONS:
        n = collisions(angle)
        # rank: prefer current angle, then horizontal orientations
        rank = (0 if angle == cur else 1, 0 if angle in (0, 180) else 1)
        if n < best_n or (n == best_n and rank < best_rank):
            best_angle, best_n, best_rank = angle, n, rank
    return best_angle, best_n


def _count_label_overlaps(
    labels: List[Dict[str, Any]],
    static_obstacles: List[Dict[str, float]],
    margin: float,
) -> int:
    """Total collision incidents: label–label pairs plus label–obstacle hits,
    using each label's current angle."""
    bbs = [_label_bbox(lb["x"], lb["y"], lb["angle"], lb["name"]) for lb in labels]
    n = 0
    for i in range(len(bbs)):
        for j in range(i + 1, len(bbs)):
            if _bbox_overlaps(bbs[i], bbs[j], margin):
                n += 1
        for ob in static_obstacles:
            if _bbox_overlaps(bbs[i], ob, margin):
                n += 1
    return n


def plan_label_declutter(
    labels: List[Dict[str, Any]],
    static_obstacles: List[Dict[str, float]],
    margin: float,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Core solver (pure). `labels` = [{name,x,y,angle,type}]; `static_obstacles`
    = fixed bboxes (component bodies, free text, pins). Greedily re-orients each
    label that currently collides, accounting for the labels already re-oriented
    this pass. Returns (proposals, overlaps_before, overlaps_after)."""
    before = _count_label_overlaps(labels, static_obstacles, margin)

    # Work on a copy of angles; treat other labels (with their working angle) as
    # obstacles too, so we don't just shove the collision next door.
    work = [dict(lb) for lb in labels]
    proposals: List[Dict[str, Any]] = []

    # Process most-collided labels first for a better greedy outcome.
    def cur_collisions(idx: int) -> int:
        lb = work[idx]
        bb = _label_bbox(lb["x"], lb["y"], lb["angle"], lb["name"])
        obs = static_obstacles + [
            _label_bbox(o["x"], o["y"], o["angle"], o["name"])
            for k, o in enumerate(work)
            if k != idx
        ]
        return sum(1 for ob in obs if _bbox_overlaps(bb, ob, margin))

    order = sorted(range(len(work)), key=cur_collisions, reverse=True)
    for idx in order:
        lb = work[idx]
        if cur_collisions(idx) == 0:
            continue
        others = static_obstacles + [
            _label_bbox(o["x"], o["y"], o["angle"], o["name"])
            for k, o in enumerate(work)
            if k != idx
        ]
        new_angle, _ = _best_orientation(lb, others, margin)
        if new_angle != round(lb["angle"] / 90) * 90 % 360:
            proposals.append(
                {
                    "type": lb.get("type", "net"),
                    "name": lb["name"],
                    "at": [round(lb["x"], 3), round(lb["y"], 3)],
                    "from_angle": round(lb["angle"] / 90) * 90 % 360,
                    "to_angle": new_angle,
                    "from_justify": _justify_for_angle(lb["angle"]),
                    "to_justify": _justify_for_angle(new_angle),
                }
            )
            lb["angle"] = new_angle

    after = _count_label_overlaps(work, static_obstacles, margin)
    return proposals, before, after


# ──────────────────────────────────────────────────────────────────────────
#  Raw-text editing for apply
# ──────────────────────────────────────────────────────────────────────────
def _reorient_label_in_text(
    content: str, name: str, x: float, y: float, new_angle: int, new_justify: str
) -> Tuple[str, bool]:
    """Rewrite the (at x y angle) and (justify ...) of the label whose name and
    anchor match (x, y) within grid tolerance. Returns (new_content, changed)."""
    # Match a label / global_label / hierarchical_label block opening with the
    # given quoted name, then its (at X Y A). Tolerant float compare on X/Y.
    name_esc = re.escape(name)
    pat = re.compile(
        r'(\((?:label|global_label|hierarchical_label)\s+"'
        + name_esc
        + r'"\s+\(at\s+)(-?[0-9.]+)\s+(-?[0-9.]+)\s+(-?[0-9.]+)(\))'
    )
    out = []
    last = 0
    changed = False
    for m in pat.finditer(content):
        lx, ly = float(m.group(2)), float(m.group(3))
        if abs(lx - x) > _GRID / 2 or abs(ly - y) > _GRID / 2:
            continue
        # Replace the angle in this (at ...).
        out.append(content[last : m.start()])
        out.append(f"{m.group(1)}{m.group(2)} {m.group(3)} {new_angle}{m.group(5)}")
        last = m.end()
        changed = True
    out.append(content[last:])
    content = "".join(out)
    if changed:
        # Update the FIRST justify after this label's anchor. Best-effort: rewrite
        # the justify token nearest the matched anchor coordinates.
        content = _set_justify_near(content, name, x, y, new_justify)
    return content, changed


def _set_justify_near(content: str, name: str, x: float, y: float, justify: str) -> str:
    """Set the horizontal justify of the label block identified by name+anchor.
    Replaces an existing (justify left|right ...) keeping any vertical token; if
    the label has NO justify token (KiCad omits it for default-left labels),
    injects one as the last child of the (effects ...) group so a 180/270
    reorientation actually flips the text."""
    name_esc = re.escape(name)
    block_pat = re.compile(
        r'\((?:label|global_label|hierarchical_label)\s+"'
        + name_esc
        + r'"\s+\(at\s+(-?[0-9.]+)\s+(-?[0-9.]+)\s+-?[0-9.]+\).*?\(uuid',
        re.DOTALL,
    )
    just_pat = re.compile(r"\(justify\s+(left|right)([^)]*)\)")

    def repl_block(bm: "re.Match[str]") -> str:
        lx, ly = float(bm.group(1)), float(bm.group(2))
        if abs(lx - x) > _GRID / 2 or abs(ly - y) > _GRID / 2:
            return bm.group(0)
        block = bm.group(0)
        if just_pat.search(block):
            return just_pat.sub(lambda jm: f"(justify {justify}{jm.group(2)})", block, count=1)
        return _inject_justify_into_effects(block, justify)

    return block_pat.sub(repl_block, content)


def _inject_justify_into_effects(block: str, justify: str) -> str:
    """Insert (justify <justify>) as the last child of the first (effects ...)
    group in `block`, by paren-matching (quote-aware). Returns block unchanged
    if there is no effects group."""
    idx = block.find("(effects")
    if idx == -1:
        return block
    depth = 0
    in_str = False
    i = idx
    while i < len(block):
        c = block[i]
        if c == '"' and block[i - 1] != "\\":
            in_str = not in_str
        elif not in_str:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return block[:i] + f" (justify {justify})" + block[i:]
        i += 1
    return block


# ──────────────────────────────────────────────────────────────────────────
#  Command handler
# ──────────────────────────────────────────────────────────────────────────
class SchematicDeclutterCommands:
    """Handler for suggest_schematic_declutter."""

    def suggest_schematic_declutter(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Re-orient overlapping net/global labels so their text is readable.

        Args:
            schematicPath: Path to the .kicad_sch file (required).
            margin: Extra clearance in mm when testing overlap (default 0.3).
            references: Optional list limiting which component bodies count as
                obstacles / which sheet area to consider (default: whole sheet).
            apply: If true, rewrite the label orientations. Default false (dry
                run — returns proposals only, schematic untouched).

        Returns:
            {success, proposals:[{name, at, from_angle, to_angle, ...}],
             score:{overlaps_before, overlaps_after}, applied, summary}
        """
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            sch_path = Path(schematic_path)
            if not sch_path.exists():
                return {"success": False, "message": f"Schematic not found: {schematic_path}"}

            margin = float(params.get("margin", 0.3))
            apply = bool(params.get("apply", False))

            labels, obstacles = self._gather(sch_path, params.get("references"))
            if len(labels) < 1:
                return {
                    "success": True,
                    "proposals": [],
                    "score": {"overlaps_before": 0, "overlaps_after": 0},
                    "applied": False,
                    "summary": {"labels": 0, "note": "No net/global labels found."},
                }

            proposals, before, after = plan_label_declutter(labels, obstacles, margin)

            applied = False
            if apply and proposals:
                content = sch_path.read_text(encoding="utf-8")
                n = 0
                for p in proposals:
                    content, changed = _reorient_label_in_text(
                        content,
                        p["name"],
                        p["at"][0],
                        p["at"][1],
                        p["to_angle"],
                        p["to_justify"],
                    )
                    n += 1 if changed else 0
                if n:
                    sch_path.write_text(content, encoding="utf-8")
                applied = True

            return {
                "success": True,
                "proposals": proposals,
                "score": {"overlaps_before": before, "overlaps_after": after},
                "applied": applied,
                "summary": {
                    "labels": len(labels),
                    "obstacles": len(obstacles),
                    "reoriented": len(proposals),
                    "margin_mm": margin,
                    "note": (
                        (
                            "Dry run — schematic unchanged. Re-run with apply=true "
                            "to write the new label orientations."
                        )
                        if not applied
                        else "Applied (label anchors unchanged; nets intact)."
                    ),
                },
            }
        except Exception as e:  # noqa: BLE001
            logger.error(f"suggest_schematic_declutter failed: {e}", exc_info=True)
            return {
                "success": False,
                "message": "suggest_schematic_declutter failed",
                "errorDetails": str(e),
            }

    # -- data gathering (kept thin; geometry lives in the pure functions) ----
    def _gather(
        self, sch_path: Path, references: Optional[List[str]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, float]]]:
        """Collect net/global labels and the static obstacle bboxes (component
        bodies + free text). Reuses the field-layout gatherers."""
        from commands.pin_locator import PinLocator
        from commands.schematic import SchematicManager
        from commands.schematic_field_layout import _gather_components, _gather_labels

        schematic = SchematicManager.load_schematic(str(sch_path))
        if not schematic:
            raise RuntimeError("Failed to load schematic")
        raw = sch_path.read_text(encoding="utf-8")
        locator = PinLocator()

        labels = [
            {
                "name": lb["name"],
                "x": lb["position"]["x"],
                "y": lb["position"]["y"],
                "angle": lb.get("angle", 0),
                "type": lb.get("type", "net"),
            }
            for lb in _gather_labels(schematic)
        ]

        ref_set = set(references) if references else None
        obstacles: List[Dict[str, float]] = []
        for comp in _gather_components(schematic, sch_path, raw, locator):
            if ref_set is not None and comp["reference"] not in ref_set:
                continue
            bb = comp.get("body_bbox")
            if bb:
                obstacles.append(dict(bb))
        return labels, obstacles
