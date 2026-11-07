"""Compare every via's net with a reference board.

KiCad can change a via's net when a board is saved, with no error and nothing
for DRC to flag: a via is connected to whatever its net now is, so the board
is self-consistent, just wrong. Seen in practice on KiCad 10:
- a via placed on a net inside a zone of another net took the zone's net on
  save (fixed for ``add_via`` by making it a free via);
- after an autorouter (SES) import, a GND via came back on ISENSE_ADC and two
  VBAT vias came back as GND.
The way to catch it is to compare with a known-good version of the board, via
by via. This module does that comparison on the saved files.

Vias are matched by UUID, then (for the rest) by position and layer pair,
since an import can give vias new UUIDs.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

IU_PER_MM = 1_000_000


@dataclass(frozen=True)
class Via:
    uuid: str
    x: int  # internal units (nm)
    y: int
    top: str
    bottom: str
    net: str
    drill: int

    def describe(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "position_mm": [self.x / IU_PER_MM, self.y / IU_PER_MM],
            "layers": f"{self.top}-{self.bottom}",
        }


def read_vias(board: Any) -> List[Via]:
    """Every via on a pcbnew BOARD."""
    out = []
    for item in board.GetTracks():
        if item.GetClass() != "PCB_VIA":
            continue
        via = item.Cast() if hasattr(item, "Cast") else item
        pos = via.GetPosition()
        out.append(
            Via(
                uuid=via.m_Uuid.AsString(),
                x=int(pos.x),
                y=int(pos.y),
                top=board.GetLayerName(via.TopLayer()),
                bottom=board.GetLayerName(via.BottomLayer()),
                net=via.GetNetname() if via.GetNetCode() > 0 else "",
                drill=int(via.GetDrillValue()) if hasattr(via, "GetDrillValue") else 0,
            )
        )
    return out


def compare_vias(reference: List[Via], current: List[Via]) -> Dict[str, Any]:
    """Pair vias of two boards and report net changes, moves, additions and removals."""
    ref_by_uuid = {v.uuid: v for v in reference}
    pairs: List[Tuple[Via, Via, str]] = []
    unmatched_cur: List[Via] = []
    for v in current:
        r = ref_by_uuid.pop(v.uuid, None)
        if r is not None:
            pairs.append((r, v, "uuid"))
        else:
            unmatched_cur.append(v)
    # Second pass: same place, same layer pair. Several vias stacked at one
    # point are paired in file order.
    ref_by_place: Dict[Tuple[int, int, str, str], List[Via]] = {}
    for r in ref_by_uuid.values():
        ref_by_place.setdefault((r.x, r.y, r.top, r.bottom), []).append(r)
    added: List[Via] = []
    for v in unmatched_cur:
        bucket = ref_by_place.get((v.x, v.y, v.top, v.bottom))
        if bucket:
            pairs.append((bucket.pop(0), v, "position"))
        else:
            added.append(v)
    removed = [r for bucket in ref_by_place.values() for r in bucket]

    net_changed = []
    moved = []
    transitions: Counter = Counter()
    for r, v, how in pairs:
        if r.net != v.net:
            entry = v.describe()
            entry.update({"reference_net": r.net, "board_net": v.net, "matched_by": how})
            net_changed.append(entry)
            transitions[f"{r.net or '<no net>'} -> {v.net or '<no net>'}"] += 1
        if how == "uuid" and (r.x, r.y) != (v.x, v.y):
            entry = v.describe()
            entry["moved_from_mm"] = [r.x / IU_PER_MM, r.y / IU_PER_MM]
            moved.append(entry)

    def listing(vias: List[Via]) -> List[Dict[str, Any]]:
        return [dict(v.describe(), net=v.net) for v in vias]

    return {
        "vias_reference": len(reference),
        "vias_board": len(current),
        "vias_compared": len(pairs),
        "net_changed_count": len(net_changed),
        "net_changed": net_changed,
        "net_transitions": dict(transitions),
        "moved_count": len(moved),
        "moved": moved,
        "added_count": len(added),
        "added": listing(added),
        "removed_count": len(removed),
        "removed": listing(removed),
    }


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=60
    )


def reference_file(board_path: str, reference: str, tmpdir: str) -> Tuple[Optional[str], str]:
    """Resolve *reference* to a readable board file.

    An existing path is used as is. Anything else is taken as a git revision
    (``HEAD``, ``HEAD~1``, a sha, a tag) of the same board file, written to
    *tmpdir*. Returns (path or None, description or error).
    """
    if os.path.isfile(reference):
        return reference, f"file {reference}"
    board = Path(board_path).resolve()
    top = _git(board.parent, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return None, (
            f"'{reference}' is not a file, and {board.parent} is not in a git repository, "
            "so it cannot be read as a revision"
        )
    rel = board.relative_to(Path(top.stdout.strip()).resolve()).as_posix()
    shown = subprocess.run(
        ["git", "-C", str(board.parent), "show", f"{reference}:{rel}"],
        capture_output=True,
        timeout=60,
    )
    if shown.returncode != 0:
        return None, (
            f"git could not read {rel} at '{reference}': "
            f"{shown.stderr.decode('utf-8', 'replace').strip()}"
        )
    out = Path(tmpdir) / board.name
    out.write_bytes(shown.stdout)
    return str(out), f"git {reference}:{rel}"


def audit_via_nets(board_path: str, reference: str) -> Dict[str, Any]:
    """Compare the vias of the saved board at *board_path* with *reference*."""
    import pcbnew

    if not os.path.isfile(board_path):
        return {"success": False, "message": f"Board file not found: {board_path}"}
    with tempfile.TemporaryDirectory(prefix="via-audit-") as tmp:
        ref_path, ref_desc = reference_file(board_path, reference, tmp)
        if ref_path is None:
            return {"success": False, "message": f"Failed to read the reference: {ref_desc}"}
        ref_board = pcbnew.LoadBoard(ref_path)
        ref_vias = read_vias(ref_board)
    cur_vias = read_vias(pcbnew.LoadBoard(board_path))
    result = compare_vias(ref_vias, cur_vias)
    n = result["net_changed_count"]
    summary = (
        f"{n} via(s) changed net since the reference"
        + (
            ": " + ", ".join(f"{k} ({c})" for k, c in result["net_transitions"].items())
            if n
            else ""
        )
        + f". {result['vias_compared']} compared, {result['added_count']} added, "
        f"{result['removed_count']} removed, {result['moved_count']} moved."
    )
    return {"success": True, "message": summary, "reference": ref_desc, **result}
