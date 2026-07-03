"""Connectivity-driven component placement optimizer.

DRAFT — proposed new MCP capability.

The existing tools (place_component, move_component, align_components,
check_courtyard_overlaps) give you placement primitives plus *validation*, but
nothing turns the netlist into a suggested layout. This module adds a single
command, ``suggest_placement``, that does the heuristic an engineer does by
eye against the ratsnest:

    1. Build a component-level connection graph from pad nets.
    2. Force-directed relaxation (Fruchterman-Reingold flavoured, adapted for
       PCB): nets pull connected parts together, overlapping courtyards push
       apart, the board outline contains everything. Power/high-current nets
       and IC<->decoupling links are weighted so those parts hug tightest.
    3. Pin-facing rotation: each movable part is rotated (0/90/180/270) to the
       orientation that minimises the pad-level wire length to its neighbours —
       this is what removes airwire crossings.
    4. Snap to grid and return *proposed* {ref:[x,y,rot]} positions. It does
       NOT modify the board unless ``apply=true``.

It reuses ComponentCommands._footprint_courtyard_bbox so the collision model is
identical to check_courtyard_overlaps (AABB on the real courtyard polygon).
Intended loop:

    suggest_placement(dryRun) -> check_courtyard_overlaps(positions=...) ->
    apply -> autoroute(best-of-N) -> run_drc

Quality metric reported is pad-level HPWL (half-perimeter wire length), the
standard placement proxy for routed length — lower is better.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

import pcbnew

logger = logging.getLogger("kicad_interface")

# Net-name fragments treated as high-current / power and pulled short & direct
# (step 4 of the placement priority order). Case-insensitive substring match.
DEFAULT_POWER_NETS = [
    "VBAT",
    "VBUS",
    "VCC",
    "VDD",
    "VIN",
    "VOUT",
    "+5V",
    "+3V3",
    "+3.3V",
    "3V3",
    "5V",
    "12V",
    "PWR",
    "BAT",
    "VSYS",
    "PVDD",
]


class PlacementOptimizerCommands:
    """Mixin providing suggest_placement.

    Expects the host (ComponentCommands) to provide:
      - self.board                      : the loaded BOARD
      - self._footprint_courtyard_bbox  : bbox in mm for a footprint
    so it composes with the existing component handlers.
    """

    # ------------------------------------------------------------------ #
    #  Public command                                                    #
    # ------------------------------------------------------------------ #
    def suggest_placement(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Propose an optimized placement that shortens net length, orients
        parts toward their partners, and removes courtyard overlaps — without
        committing unless asked.

        Args:
            refs: References to move. Default: every non-locked footprint.
            locked: References to hold fixed (connectors, mounting-constrained,
                RF, edge parts). They still pull movable parts. KiCad's own
                IsLocked() footprints are auto-added here.
            iterations: Relaxation passes (default 200).
            grid_mm: Snap proposed positions to this grid (default 0.5).
            margin_mm: Extra keepout between courtyards (default 0.3).
            board_outline: Optional {x1,y1,x2,y2,unit} override; else Edge.Cuts.
            spring_k / repel_k: attraction / repulsion gains.
            power_nets: Net-name fragments to weight as high-current
                (default DEFAULT_POWER_NETS). Set [] to disable.
            power_weight: Pull multiplier for power nets (default 3.0).
            decoupling_boost: Extra pull for 2-pin-passive <-> multi-pin-IC
                links so caps/feedback parts hug their IC (default 2.0).
            rotate: Enable pin-facing rotation (default True).
            rotation_steps: Candidate orientations in degrees
                (default [0, 90, 180, 270]).
            rotation_passes: Greedy rotation sweeps (default 2).
            apply: If True, move + rotate the components. Default False (dry run).

        Returns:
            {success, proposals:{ref:[x,y,rot]}, score:{hpwl_before_mm,
             hpwl_after_mm, improvement_pct, overlaps_before, overlaps_after},
             applied, summary}
        """
        try:
            if not getattr(self, "board", None):
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            iterations = int(params.get("iterations", 200))
            grid_mm = float(params.get("grid_mm", 0.5))
            margin_mm = float(params.get("margin_mm", 0.3))
            spring_k = float(params.get("spring_k", 0.08))
            repel_k = float(params.get("repel_k", 0.6))
            power_nets = [s.upper() for s in params.get("power_nets", DEFAULT_POWER_NETS)]
            power_weight = float(params.get("power_weight", 3.0))
            decoupling_boost = float(params.get("decoupling_boost", 2.0))
            do_rotate = bool(params.get("rotate", True))
            rotation_steps = list(params.get("rotation_steps", [0, 90, 180, 270]))
            rotation_passes = int(params.get("rotation_passes", 2))
            apply = bool(params.get("apply", False))

            locked = set(params.get("locked") or [])
            ref_filter = params.get("refs")
            ref_filter = set(ref_filter) if ref_filter is not None else None

            outline = self._opt_resolve_outline(params.get("board_outline"))
            # Optional tighter box confining the MOVABLE parts (e.g. the area
            # beside one IC). Movers are clamped to this; falls back to outline.
            region = self._opt_resolve_outline(params.get("bounds")) or outline
            net_names = self._opt_net_name_map()

            move_set = set(ref_filter) if ref_filter is not None else None

            # --- Collect EVERY footprint so locked ICs / neighbours still
            #     anchor and pull, even in scoped (refs=...) mode. A part is
            #     "fixed" if it's in `locked`, KiCad-locked, or — when `refs` is
            #     given — not one of the parts we're allowed to move. ---
            nodes: Dict[str, Dict[str, Any]] = {}
            for fp in self.board.GetFootprints():
                ref = fp.GetReference()
                fixed = (ref in locked) or (move_set is not None and ref not in move_set)
                node = self._opt_make_node(fp, fixed)
                if node is not None:
                    nodes[ref] = node

            if len([n for n in nodes.values() if not n["locked"]]) < 2:
                return {
                    "success": False,
                    "message": "Nothing to optimize",
                    "errorDetails": "Need >= 2 movable footprints with courtyards.",
                }

            self._opt_jitter_coincident(nodes, 1.0)

            edges = self._opt_build_edges(
                nodes, net_names, power_nets, power_weight, decoupling_boost
            )

            hpwl_before = self._opt_hpwl(nodes)
            overlaps_before = self._opt_count_overlaps(nodes, margin_mm)

            # --- Relax, then alternate rotation + light re-relax ---
            self._opt_relax(
                nodes,
                edges,
                region,
                iterations=iterations,
                spring_k=spring_k,
                repel_k=repel_k,
                margin_mm=margin_mm,
            )
            if do_rotate:
                for _ in range(max(rotation_passes, 0)):
                    self._opt_rotate_pass(nodes, rotation_steps)
                    self._opt_relax(
                        nodes,
                        edges,
                        region,
                        iterations=max(20, iterations // 4),
                        spring_k=spring_k,
                        repel_k=repel_k,
                        margin_mm=margin_mm,
                    )

            # --- Spread: the springs pack parts into a blob denser than the
            #     silicon physically fits; diffuse them across free board area
            #     (transport, which local pairwise pushing cannot do) before
            #     the final legalize. Skip when explicitly disabled. ---
            if bool(params.get("spread", True)):
                self._opt_spread(
                    nodes,
                    region,
                    iterations=int(params.get("spread_iters", 80)),
                    strength=float(params.get("spread_strength", 0.08)),
                    margin_mm=margin_mm,
                )

            # --- Align: the force solve leaves parts at organic offsets; snap
            #     near-collinear centers onto shared row (Y) and column (X)
            #     lines so the result reads as tidy rows/columns with items
            #     centered — like KiCad's align+distribute. Default on. ---
            if bool(params.get("align", True)):
                self._opt_align(nodes, float(params.get("align_tol_mm", 1.5)))

            # --- Snap to grid, THEN legalize so separation has the last word
            #     (snapping after legalize would re-introduce overlaps). ---
            for n in nodes.values():
                if n["locked"]:
                    continue
                n["x"] = round(n["x"] / grid_mm) * grid_mm
                n["y"] = round(n["y"] / grid_mm) * grid_mm

            # Springs collapse parts into a pile; push overlapping courtyards
            # apart until clear (or iterations run out).
            legalize_iters = int(params.get("legalize_iters", 200))
            self._opt_legalize(nodes, region, margin_mm, legalize_iters)

            hpwl_after = self._opt_hpwl(nodes)
            overlaps_after = self._opt_count_overlaps(nodes, margin_mm)

            proposals = {
                ref: [round(n["x"], 3), round(n["y"], 3), round(n["angle"] % 360, 1)]
                for ref, n in nodes.items()
                if not n["locked"]
            }

            applied = False
            if apply:
                for ref, (px, py, rot) in proposals.items():
                    fp = nodes[ref]["fp"]
                    fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(px), pcbnew.FromMM(py)))
                    fp.SetOrientationDegrees(rot)
                applied = True

            improvement = (
                100.0 * (hpwl_before - hpwl_after) / hpwl_before if hpwl_before > 0 else 0.0
            )

            return {
                "success": True,
                "proposals": proposals,
                "applied": applied,
                "score": {
                    "hpwl_before_mm": round(hpwl_before, 2),
                    "hpwl_after_mm": round(hpwl_after, 2),
                    "improvement_pct": round(improvement, 1),
                    "overlaps_before": overlaps_before,
                    "overlaps_after": overlaps_after,
                },
                "summary": {
                    "movable": len(proposals),
                    "locked": sum(1 for n in nodes.values() if n["locked"]),
                    "nets_considered": len(edges),
                    "iterations": iterations,
                    "rotated": do_rotate,
                    "grid_mm": grid_mm,
                    "margin_mm": margin_mm,
                    "note": (
                        (
                            "Dry run — board unchanged. Validate via "
                            "check_courtyard_overlaps(positions=proposals), "
                            "then re-run with apply=true."
                        )
                        if not applied
                        else "Applied to board (not saved)."
                    ),
                },
            }
        except Exception as e:  # noqa: BLE001
            logger.error(f"suggest_placement failed: {e}", exc_info=True)
            return {
                "success": False,
                "message": "suggest_placement failed",
                "errorDetails": str(e),
            }

    # ------------------------------------------------------------------ #
    #  Node construction                                                 #
    # ------------------------------------------------------------------ #
    def _opt_make_node(self, fp, force_locked) -> Optional[Dict[str, Any]]:
        bbox = self._footprint_courtyard_bbox(fp, None)
        if bbox is None:
            return None
        x1, y1, x2, y2 = bbox
        anchor = fp.GetPosition()
        ax, ay = pcbnew.ToMM(anchor.x), pcbnew.ToMM(anchor.y)
        angle0 = fp.GetOrientationDegrees()

        # Courtyard center expressed in the footprint's *local* (un-rotated)
        # frame, so we can re-project it after a rotation.
        cwx, cwy = (x1 + x2) / 2.0 - ax, (y1 + y2) / 2.0 - ay
        lox, loy = self._opt_rot(cwx, cwy, -angle0)
        hw0, hh0 = max((x2 - x1) / 2.0, 0.01), max((y2 - y1) / 2.0, 0.01)

        # Pad geometry in the footprint-local (un-rotated) frame, so that
        # world pad = anchor + R(angle)*local. PAD.GetPos0() isn't exposed on
        # every KiCad SWIG build, so derive it from the absolute pad position:
        # local = R(-angle0) * (pad_abs - anchor).
        pads = []
        for pad in fp.Pads():
            code = pad.GetNetCode()
            if code <= 0:
                continue
            pp = pad.GetPosition()
            wx = pcbnew.ToMM(pp.x - anchor.x)
            wy = pcbnew.ToMM(pp.y - anchor.y)
            lx, ly = self._opt_rot(wx, wy, -angle0)
            pads.append((code, lx, ly))

        node = {
            "fp": fp,
            "x": ax,
            "y": ay,  # working position = footprint anchor (mm)
            "angle": angle0,
            "angle0": angle0,
            "loff": (lox, loy),  # courtyard-center offset, local frame
            "hw0": hw0,
            "hh0": hh0,  # half-sizes at angle0
            "pads": pads,
            "pins": fp.GetPadCount() if hasattr(fp, "GetPadCount") else len(pads),
            "locked": force_locked or bool(fp.IsLocked()),
        }
        self._opt_apply_angle(node, angle0)  # sets cox/coy, hw/hh
        return node

    def _opt_apply_angle(self, n, angle) -> None:
        """Set a node's orientation and refresh courtyard center-offset + halfs."""
        n["angle"] = angle
        lox, loy = n["loff"]
        n["cox"], n["coy"] = self._opt_rot(lox, loy, angle)
        # Half-sizes swap on odd 90-degree multiples (exact for AABB courtyards).
        quarter = int(round((angle - n["angle0"]) / 90.0)) % 2
        if quarter:
            n["hw"], n["hh"] = n["hh0"], n["hw0"]
        else:
            n["hw"], n["hh"] = n["hw0"], n["hh0"]

    # ------------------------------------------------------------------ #
    #  Edges (weighted connectivity)                                     #
    # ------------------------------------------------------------------ #
    def _opt_build_edges(
        self, nodes, net_names, power_nets, power_weight, decoupling_boost
    ) -> List[Tuple[str, str, float]]:
        """Collapse pad nets into weighted component edges.

        - Base weight 1/(fanout-1) so a star net (GND/VCC) contributes constant
          total pull rather than O(n^2).
        - Power/high-current nets multiplied by power_weight (short & direct).
        - A 2-pin passive linked to a multi-pin IC gets decoupling_boost so the
          cap / feedback resistor hugs the IC.
        """
        net_to_refs: Dict[int, set] = {}
        for ref, n in nodes.items():
            for code, _, _ in n["pads"]:
                net_to_refs.setdefault(code, set()).add(ref)

        # Deterministic order: iterate nets and refs sorted, so edge build order
        # (and thus float-summation order in the relaxation) is reproducible
        # across runs — the dry-run proposal must match the applied run. Python
        # set iteration order varies per process (string hash randomisation).
        weights: Dict[Tuple[str, str], float] = {}
        for code in sorted(net_to_refs):
            refs = sorted(net_to_refs[code])
            fanout = len(refs)
            if fanout < 2:
                continue
            name = net_names.get(code, "").upper()
            pmult = power_weight if any(p in name for p in power_nets) else 1.0
            base = pmult / (fanout - 1)
            for i in range(fanout):
                for j in range(i + 1, fanout):
                    a, b = sorted((refs[i], refs[j]))
                    weights[(a, b)] = weights.get((a, b), 0.0) + base

        edges = []
        for (a, b), w in weights.items():
            pa, pb = nodes[a]["pins"], nodes[b]["pins"]
            if (pa <= 2 < pb) or (pb <= 2 < pa):
                w *= decoupling_boost
            edges.append((a, b, w))
        return edges

    # ------------------------------------------------------------------ #
    #  Force-directed translation                                        #
    # ------------------------------------------------------------------ #
    def _opt_relax(self, nodes, edges, outline, *, iterations, spring_k, repel_k, margin_mm):
        movable = [r for r, n in nodes.items() if not n["locked"]]
        refs = list(nodes)
        for it in range(iterations):
            temp = 1.0 - (it / max(iterations, 1))
            max_step = 5.0 * temp + 0.2  # mm
            fx = {r: 0.0 for r in movable}
            fy = {r: 0.0 for r in movable}

            # Attraction along nets, with a rest length so connected parts
            # settle *adjacent* (just touching + margin) instead of collapsing
            # onto a single point. Spring force = k*w*(dist - rest) along the
            # center-to-center unit vector: attract when farther than rest,
            # gently repel when closer.
            for a, b, w in edges:
                na, nb = nodes[a], nodes[b]
                dx = (nb["x"] + nb["cox"]) - (na["x"] + na["cox"])
                dy = (nb["y"] + nb["coy"]) - (na["y"] + na["coy"])
                dist = math.hypot(dx, dy) or 1e-6
                ra = (na["hw"] + na["hh"]) / 2.0
                rb = (nb["hw"] + nb["hh"]) / 2.0
                rest = ra + rb + margin_mm
                f = spring_k * w * (dist - rest)
                ux, uy = dx / dist, dy / dist
                if a in fx:
                    fx[a] += f * ux
                    fy[a] += f * uy
                if b in fx:
                    fx[b] -= f * ux
                    fy[b] -= f * uy

            # Repulsion only where courtyards (AABB + margin) overlap.
            for i in range(len(refs)):
                na = nodes[refs[i]]
                for j in range(i + 1, len(refs)):
                    nb = nodes[refs[j]]
                    dx = (nb["x"] + nb["cox"]) - (na["x"] + na["cox"])
                    dy = (nb["y"] + nb["coy"]) - (na["y"] + na["coy"])
                    ox = (na["hw"] + nb["hw"] + margin_mm) - abs(dx)
                    oy = (na["hh"] + nb["hh"] + margin_mm) - abs(dy)
                    if ox <= 0 or oy <= 0:
                        continue
                    ra, rb = refs[i], refs[j]
                    if ox < oy:  # push along least-penetration axis
                        push, s = repel_k * ox, (1.0 if dx >= 0 else -1.0)
                        if ra in fx:
                            fx[ra] -= push * s
                        if rb in fx:
                            fx[rb] += push * s
                    else:
                        push, s = repel_k * oy, (1.0 if dy >= 0 else -1.0)
                        if ra in fy:
                            fy[ra] -= push * s
                        if rb in fy:
                            fy[rb] += push * s

            for r in movable:
                n = nodes[r]
                step = math.hypot(fx[r], fy[r])
                if step > max_step and step > 0:
                    scale = max_step / step
                    fx[r] *= scale
                    fy[r] *= scale
                n["x"] += fx[r]
                n["y"] += fy[r]
                if outline is not None:
                    ox1, oy1, ox2, oy2 = outline
                    n["x"] = min(max(n["x"], ox1 + n["hw"] - n["cox"]), ox2 - n["hw"] - n["cox"])
                    n["y"] = min(max(n["y"], oy1 + n["hh"] - n["coy"]), oy2 - n["hh"] - n["coy"])

    # ------------------------------------------------------------------ #
    #  Alignment / tidy (rows + columns, centers aligned)                #
    # ------------------------------------------------------------------ #
    def _opt_align(self, nodes, tol):
        """Snap near-collinear part centers onto shared row/column lines so the
        layout reads as tidy rows and columns instead of organic offsets.

        Parts whose center Y values fall within `tol` are pulled to a common Y
        (a row); likewise center X for columns. Aligning on CENTERS means a big
        IC and a small cap on the same line share a centerline — i.e. centered,
        the way KiCad's Align Centers + Distribute leaves them. A final legalize
        (run by the caller afterwards) fixes any spacing this tightens."""
        movable = [n for n in nodes.values() if not n["locked"]]
        if len(movable) < 2:
            return
        # Rows: cluster on Y (center), columns: cluster on X (center).
        self._opt_cluster_snap(movable, "y", tol)
        self._opt_cluster_snap(movable, "x", tol)

    @staticmethod
    def _opt_cluster_snap(parts, axis, tol):
        """Group parts whose center on `axis` is within tol of the running group,
        then set every member's center to the group mean. Deterministic: sorted
        by center, ties broken by the offset key so order is stable."""
        off = "cox" if axis == "x" else "coy"
        pos = "x" if axis == "x" else "y"

        def center(n):
            return n[pos] + n[off]

        ordered = sorted(parts, key=lambda n: (center(n), n[off]))
        i = 0
        while i < len(ordered):
            group = [ordered[i]]
            j = i + 1
            # Extend while the next center is within tol of the group's last.
            while j < len(ordered) and center(ordered[j]) - center(group[-1]) <= tol:
                group.append(ordered[j])
                j += 1
            mean = sum(center(g) for g in group) / len(group)
            for g in group:
                g[pos] = mean - g[off]
            i = j

    # ------------------------------------------------------------------ #
    #  Density spreading (cell diffusion)                                #
    # ------------------------------------------------------------------ #
    def _opt_spread(self, nodes, region, *, iterations, strength, margin_mm):
        """Diffuse movable parts down the area-density gradient so they occupy
        the whole region instead of a single over-packed blob.

        This is the 'global spreading' half of analytical placement: bin the
        region, build a density field (movable + fixed parts as mass), and move
        each movable part opposite the local gradient. Unlike pairwise pushing,
        the gradient transports a part across many bins toward genuinely free
        area — which is what fixes the whole-board over-pack. A light legalize
        afterwards cleans the residual touching pairs."""
        if region is None:
            return
        rx1, ry1, rx2, ry2 = region
        rw, rh = rx2 - rx1, ry2 - ry1
        if rw <= 0 or rh <= 0:
            return

        movable = [n for n in nodes.values() if not n["locked"]]
        if not movable:
            return

        # Bin grid: aim for a few parts per bin; clamp to a sane range.
        n = len(nodes)
        nx = max(4, min(48, int(math.sqrt(max(n, 1)) * 1.5)))
        ny = max(4, min(48, int(round(nx * rh / rw)))) if rw > 0 else nx
        bw, bh = rw / nx, rh / ny
        bin_area = max(bw * bh, 1e-6)

        def bin_of(cx, cy):
            i = min(max(int((cx - rx1) / bw), 0), nx - 1)
            j = min(max(int((cy - ry1) / bh), 0), ny - 1)
            return i, j

        for it in range(iterations):
            temp = 1.0 - (it / max(iterations, 1))
            # Build density (mm^2 of courtyard area per bin), all parts count
            # as mass so movers also flow around locked ICs.
            dens = [[0.0] * ny for _ in range(nx)]
            for nd in nodes.values():
                area = (2 * nd["hw"]) * (2 * nd["hh"])
                i, j = bin_of(nd["x"] + nd["cox"], nd["y"] + nd["coy"])
                dens[i][j] += area
            # One Jacobi blur pass to smooth the gradient.
            sm = [[0.0] * ny for _ in range(nx)]
            for i in range(nx):
                for j in range(ny):
                    acc, cnt = 0.0, 0
                    for di in (-1, 0, 1):
                        for dj in (-1, 0, 1):
                            a, b = i + di, j + dj
                            if 0 <= a < nx and 0 <= b < ny:
                                acc += dens[a][b]
                                cnt += 1
                    sm[i][j] = acc / cnt
            # Move each movable part opposite the local density gradient.
            for nd in movable:
                cx, cy = nd["x"] + nd["cox"], nd["y"] + nd["coy"]
                i, j = bin_of(cx, cy)
                ip, im = min(i + 1, nx - 1), max(i - 1, 0)
                jp, jm = min(j + 1, ny - 1), max(j - 1, 0)
                gx = (sm[ip][j] - sm[im][j]) / (2 * bw)
                gy = (sm[i][jp] - sm[i][jm]) / (2 * bh)
                # Only spread out of bins fuller than the region average; this
                # keeps already-sparse areas from jittering.
                over = sm[i][j] / bin_area
                step_x = -strength * gx * over * temp
                step_y = -strength * gy * over * temp
                mag = math.hypot(step_x, step_y)
                cap = 0.5 * min(bw, bh)
                if mag > cap and mag > 0:
                    step_x *= cap / mag
                    step_y *= cap / mag
                nd["x"] += step_x
                nd["y"] += step_y
                nd["x"] = min(max(nd["x"], rx1 + nd["hw"] - nd["cox"]), rx2 - nd["hw"] - nd["cox"])
                nd["y"] = min(max(nd["y"], ry1 + nd["hh"] - nd["coy"]), ry2 - nd["hh"] - nd["coy"])

    # ------------------------------------------------------------------ #
    #  Legalization (remove courtyard overlaps)                          #
    # ------------------------------------------------------------------ #
    def _opt_legalize(self, nodes, outline, margin_mm, iterations):
        """Push overlapping courtyards apart until none overlap (or iterations
        run out). No spring pull here — this only separates, preserving the
        relative arrangement the optimizer found. Locked parts don't move, so a
        movable part overlapping a locked one takes the full push."""
        refs = list(nodes)
        prev_overlaps = None
        stall = 0
        for it in range(iterations):
            # Accumulate (summed, not averaged) every pair's separation, then
            # apply once. Summed opposing pushes don't cancel a part out of
            # existence — they expand the whole cluster outward, which is what
            # relieves a wedged part.
            push = {r: [0.0, 0.0] for r in refs}
            overlaps = 0
            for i in range(len(refs)):
                na = nodes[refs[i]]
                for j in range(i + 1, len(refs)):
                    nb = nodes[refs[j]]
                    if na["locked"] and nb["locked"]:
                        continue
                    dx = (nb["x"] + nb["cox"]) - (na["x"] + na["cox"])
                    dy = (nb["y"] + nb["coy"]) - (na["y"] + na["coy"])
                    ox = (na["hw"] + nb["hw"] + margin_mm) - abs(dx)
                    oy = (na["hh"] + nb["hh"] + margin_mm) - abs(dy)
                    if ox <= 0 or oy <= 0:
                        continue
                    overlaps += 1
                    # Separate along the cheaper (least-penetration) axis.
                    if ox < oy:
                        sx = ox if dx >= 0 else -ox
                        sy = 0.0
                    else:
                        sx = 0.0
                        sy = oy if dy >= 0 else -oy
                    a_mov, b_mov = (not na["locked"]), (not nb["locked"])
                    share = 0.5 if (a_mov and b_mov) else 1.0
                    ra, rb = refs[i], refs[j]
                    if a_mov:
                        push[ra][0] -= sx * share
                        push[ra][1] -= sy * share
                    if b_mov:
                        push[rb][0] += sx * share
                        push[rb][1] += sy * share
            if overlaps == 0:
                break

            # Stall detection: if the overlap count stops improving, nudge every
            # contended part radially outward from the cluster centroid to break
            # a symmetric wedge (deterministic — index-based, no RNG).
            if prev_overlaps is not None and overlaps >= prev_overlaps:
                stall += 1
            else:
                stall = 0
            prev_overlaps = overlaps
            if stall >= 3:
                self._opt_explode(nodes, push, 0.4)
                stall = 0

            for r in refs:
                n = nodes[r]
                if n["locked"]:
                    continue
                dx, dy = push[r]
                # Cap per-iteration motion so a big summed push can't blow up.
                mag = math.hypot(dx, dy)
                if mag > 1.5 and mag > 0:
                    dx *= 1.5 / mag
                    dy *= 1.5 / mag
                n["x"] += dx
                n["y"] += dy
                if outline is not None:
                    ox1, oy1, ox2, oy2 = outline
                    n["x"] = min(max(n["x"], ox1 + n["hw"] - n["cox"]), ox2 - n["hw"] - n["cox"])
                    n["y"] = min(max(n["y"], oy1 + n["hh"] - n["coy"]), oy2 - n["hh"] - n["coy"])

    def _opt_explode(self, nodes, push, amount):
        """Add a small outward bias from the movable-parts centroid to any part
        currently being pushed, to break a symmetric stall."""
        movable = [n for n in nodes.values() if not n["locked"]]
        if not movable:
            return
        cx = sum(n["x"] + n["cox"] for n in movable) / len(movable)
        cy = sum(n["y"] + n["coy"] for n in movable) / len(movable)
        for ref, n in nodes.items():
            if n["locked"] or push[ref] == [0.0, 0.0]:
                continue
            vx = (n["x"] + n["cox"]) - cx
            vy = (n["y"] + n["coy"]) - cy
            d = math.hypot(vx, vy) or 1e-6
            push[ref][0] += amount * vx / d
            push[ref][1] += amount * vy / d

    # ------------------------------------------------------------------ #
    #  Pin-facing rotation (greedy, pad-accurate)                        #
    # ------------------------------------------------------------------ #
    def _opt_rotate_pass(self, nodes, steps):
        """For each movable part, pick the orientation (from `steps`) that
        minimises the pad-level HPWL of the nets it touches, holding every other
        part fixed. Emergently orients 2-pad parts toward their partners and
        unwinds crossings."""
        movable = [r for r, n in nodes.items() if not n["locked"]]
        for ref in movable:
            n = nodes[ref]
            nets = {c for c, _, _ in n["pads"]}
            if not nets:
                continue
            # Fixed contribution from every OTHER node, per net.
            other = self._opt_net_extents(nodes, exclude=ref, only=nets)
            best_angle, best_cost = n["angle"], float("inf")
            for da in steps:
                angle = (n["angle0"] + da) % 360
                cost = self._opt_rot_cost(n, angle, other)
                if cost < best_cost - 1e-9:
                    best_cost, best_angle = cost, angle
            self._opt_apply_angle(n, best_angle)

    def _opt_rot_cost(self, n, angle, other_extents) -> float:
        """Sum of net bbox spans for this node's nets at the given orientation,
        combined with the precomputed extents of all other nodes."""
        ax, ay = n["x"], n["y"]
        local = {}  # net -> [minx, miny, maxx, maxy]
        for code, px0, py0 in n["pads"]:
            wx, wy = self._opt_rot(px0, py0, angle)
            wx += ax
            wy += ay
            e = local.get(code)
            if e is None:
                local[code] = [wx, wy, wx, wy]
            else:
                e[0] = min(e[0], wx)
                e[1] = min(e[1], wy)
                e[2] = max(e[2], wx)
                e[3] = max(e[3], wy)
        total = 0.0
        for code, e in local.items():
            o = other_extents.get(code)
            if o is None:
                continue  # net only on this part — no contribution
            minx = min(e[0], o[0])
            miny = min(e[1], o[1])
            maxx = max(e[2], o[2])
            maxy = max(e[3], o[3])
            total += (maxx - minx) + (maxy - miny)
        return total

    def _opt_net_extents(self, nodes, *, exclude=None, only=None):
        """net code -> [minx,miny,maxx,maxy] of world pad positions, excluding
        one ref, optionally restricted to a set of net codes."""
        ext: Dict[int, List[float]] = {}
        for ref, n in nodes.items():
            if ref == exclude:
                continue
            ax, ay, angle = n["x"], n["y"], n["angle"]
            for code, px0, py0 in n["pads"]:
                if only is not None and code not in only:
                    continue
                wx, wy = self._opt_rot(px0, py0, angle)
                wx += ax
                wy += ay
                e = ext.get(code)
                if e is None:
                    ext[code] = [wx, wy, wx, wy]
                else:
                    e[0] = min(e[0], wx)
                    e[1] = min(e[1], wy)
                    e[2] = max(e[2], wx)
                    e[3] = max(e[3], wy)
        return ext

    # ------------------------------------------------------------------ #
    #  Scoring / metrics                                                 #
    # ------------------------------------------------------------------ #
    def _opt_hpwl(self, nodes) -> float:
        """Pad-level half-perimeter wire length over all nets (mm)."""
        ext = self._opt_net_extents(nodes)
        total = 0.0
        for e in ext.values():
            total += (e[2] - e[0]) + (e[3] - e[1])
        return total

    def _opt_count_overlaps(self, nodes, margin_mm) -> int:
        refs = list(nodes)
        count = 0
        for i in range(len(refs)):
            na = nodes[refs[i]]
            for j in range(i + 1, len(refs)):
                nb = nodes[refs[j]]
                dx = abs((nb["x"] + nb["cox"]) - (na["x"] + na["cox"]))
                dy = abs((nb["y"] + nb["coy"]) - (na["y"] + na["coy"]))
                if dx < na["hw"] + nb["hw"] + margin_mm and dy < na["hh"] + nb["hh"] + margin_mm:
                    count += 1
        return count

    # ------------------------------------------------------------------ #
    #  Small helpers                                                     #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _opt_rot(x, y, deg) -> Tuple[float, float]:
        rad = math.radians(deg)
        c, s = math.cos(rad), math.sin(rad)
        return (x * c - y * s, x * s + y * c)

    def _opt_net_name_map(self) -> Dict[int, str]:
        names: Dict[int, str] = {}
        try:
            for code, net in self.board.GetNetInfo().NetsByNetcode().items():
                names[code] = net.GetNetname()
        except Exception:  # noqa: BLE001
            pass
        return names

    def _opt_jitter_coincident(self, nodes, spread) -> None:
        """Deterministically separate parts sharing the exact same point so the
        first repulsion pass has a direction to push (no RNG — index-based)."""
        seen: Dict[Tuple[float, float], int] = {}
        for ref, n in sorted(nodes.items()):
            if n["locked"]:
                continue
            key = (round(n["x"], 3), round(n["y"], 3))
            k = seen.get(key, 0)
            if k:
                ang = 2.0 * math.pi * (k / 8.0)
                n["x"] += spread * math.cos(ang)
                n["y"] += spread * math.sin(ang)
            seen[key] = k + 1

    def _opt_resolve_outline(self, override):
        if override:
            unit = override.get("unit", "mm")
            f = {"inch": 25.4, "mil": 0.0254}.get(unit, 1.0)  # -> mm
            return (override["x1"] * f, override["y1"] * f, override["x2"] * f, override["y2"] * f)
        try:
            box = self.board.GetBoardEdgesBoundingBox()
            if box.GetWidth() > 0 and box.GetHeight() > 0:
                return (
                    pcbnew.ToMM(box.GetLeft()),
                    pcbnew.ToMM(box.GetTop()),
                    pcbnew.ToMM(box.GetRight()),
                    pcbnew.ToMM(box.GetBottom()),
                )
        except Exception:  # noqa: BLE001
            pass
        return None
