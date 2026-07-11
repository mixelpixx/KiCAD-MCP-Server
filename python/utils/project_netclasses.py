"""Read ``.kicad_pro`` net-class definitions and apply them to a SWIG board.

KiCad 7+ stores net-class definitions in the project file
(``net_settings.classes``), not the board. ``pcbnew.LoadBoard()`` reads only
the ``.kicad_pcb``, so a board loaded headless carries just the stock
Default class. ``pcbnew.ExportSpecctraDSN()`` then exports every net under a
single ``kicad_default`` DSN class at Default width/clearance, silently
dropping the user's class rules — a power net gets handed to Freerouting at
signal width with no warning (#302).

These helpers rebuild the board's ``NET_SETTINGS`` from the project file so
KiCad's own exporter sees the same classes the GUI would and natively emits
per-class ``(class ...)`` blocks, via padstacks, and rules. Verified against
real KiCad 10: applying a 2.0 mm "Power" class over two nets makes
``ExportSpecctraDSN`` write ``(class Power PWR PWR2 (circuit (use_via
"Via[0-1]_1200:600_um")) (rule (width 2000) (clearance 350)))``, register
the via padstack in the library, and drop the claimed nets from
``kicad_default`` — byte-identical to a project-loaded GUI export.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("kicad_interface")

# net_settings.classes numeric fields (millimetres) -> NETCLASS setter names.
# Same field vocabulary as commands/routing.py's _NETCLASS_NUMERIC_FIELDS.
_NETCLASS_MM_SETTERS: Tuple[Tuple[str, str], ...] = (
    ("clearance", "SetClearance"),
    ("track_width", "SetTrackWidth"),
    ("via_diameter", "SetViaDiameter"),
    ("via_drill", "SetViaDrill"),
    ("microvia_diameter", "SetuViaDiameter"),
    ("microvia_drill", "SetuViaDrill"),
    ("diff_pair_width", "SetDiffPairWidth"),
    ("diff_pair_gap", "SetDiffPairGap"),
)


def load_project_net_classes(pro_path: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse ``net_settings`` from a ``.kicad_pro`` into a normalized dict.

    Returns ``None`` when the file does not exist. Raises ``ValueError`` on
    unreadable/unparseable JSON so the caller can surface the reason instead
    of silently exporting without classes.

    Result shape::

        {
          "classes":     [ {name, track_width, clearance, ...}, ... ],
          "patterns":    [ (pattern, netclass), ... ],
          "assignments": { net_name: [class_name, ...], ... },
        }
    """
    if not pro_path or not os.path.isfile(pro_path):
        return None
    try:
        with open(pro_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read project file {pro_path}: {exc}") from exc

    net_settings = data.get("net_settings") or {}

    classes: List[Dict[str, Any]] = [
        cls
        for cls in (net_settings.get("classes") or [])
        if isinstance(cls, dict) and cls.get("name")
    ]

    patterns: List[Tuple[str, str]] = []
    for entry in net_settings.get("netclass_patterns") or []:
        if isinstance(entry, dict) and entry.get("pattern") and entry.get("netclass"):
            patterns.append((str(entry["pattern"]), str(entry["netclass"])))

    # netclass_assignments maps net name -> list of class names (KiCad 9+
    # serialization); tolerate a bare string value as well.
    assignments: Dict[str, List[str]] = {}
    raw_assignments = net_settings.get("netclass_assignments")
    if isinstance(raw_assignments, dict):
        for net, value in raw_assignments.items():
            if isinstance(value, str):
                names = [value]
            elif isinstance(value, (list, tuple)):
                names = [v for v in value if isinstance(v, str)]
            else:
                continue
            if names:
                assignments[str(net)] = names

    return {"classes": classes, "patterns": patterns, "assignments": assignments}


def _apply_numeric_fields(pcbnew_mod: Any, netclass: Any, cls: Dict[str, Any]) -> bool:
    """Set the mm-valued fields present in ``cls`` on a NETCLASS. Returns
    whether any field was applied."""
    changed = False
    for key, setter in _NETCLASS_MM_SETTERS:
        value = cls.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            getattr(netclass, setter)(pcbnew_mod.FromMM(float(value)))
            changed = True
    return changed


def apply_net_classes_to_board(board: Any, settings: Dict[str, Any]) -> Dict[str, Any]:
    """Push parsed project net classes into ``board``'s ``NET_SETTINGS``.

    May raise on a SWIG API mismatch (older KiCad builds); callers wrap this
    and degrade to a warning rather than failing the export.
    """
    import pcbnew

    net_settings = board.GetDesignSettings().m_NetSettings

    applied: List[str] = []
    default_updated = False
    for cls in settings.get("classes", []):
        name = str(cls["name"])
        if name == "Default":
            # The Default class already exists; update it in place so its
            # project-configured width/clearance reach the DSN's default rule.
            default_updated = _apply_numeric_fields(pcbnew, net_settings.GetDefaultNetclass(), cls)
            continue
        netclass = pcbnew.NETCLASS(name)
        _apply_numeric_fields(pcbnew, netclass, cls)
        priority = cls.get("priority")
        if isinstance(priority, int) and not isinstance(priority, bool):
            netclass.SetPriority(priority)
        net_settings.SetNetclass(name, netclass)
        applied.append(name)

    assignment_count = 0
    for pattern, class_name in settings.get("patterns", []):
        net_settings.SetNetclassPatternAssignment(pattern, class_name)
        assignment_count += 1

    # Explicit per-net assignments are expressed as exact-name patterns:
    # SetNetclassLabelAssignment is not callable from Python (its argument is
    # a C++ std::set<wxString>), and a literal net name is a wildcard pattern
    # matching exactly itself. Nets assigned multiple classes keep only the
    # last one (same-pattern assignments replace); composite-class merging is
    # not modeled here.
    for net_name, class_names in settings.get("assignments", {}).items():
        for class_name in class_names:
            net_settings.SetNetclassPatternAssignment(net_name, class_name)
            assignment_count += 1

    if hasattr(net_settings, "ClearAllCaches"):
        net_settings.ClearAllCaches()
    board.SynchronizeNetsAndNetClasses(False)

    return {
        "applied": applied,
        "defaultUpdated": default_updated,
        "assignments": assignment_count,
    }
