"""Conformant KiCad 10 ``.kicad_pro`` project files (issue #220).

``create_project`` used to hand-write a 122-byte stub containing only a
``board.filename`` and a ``sheets`` entry with the literal id ``"root"``.
KiCad opened it, silently regenerated defaults, and discarded any intended
configuration — net classes, design settings, ERC/DRC config and text
variables were all absent from the file we shipped.

The structure below is captured verbatim from what KiCad 10.0 itself writes
for a brand-new project (``pcbnew.GetSettingsManager()`` →
``LoadProject(<new path>)`` → ``SaveProject()``, KiCad 10.0.0, 2026-07-03):
``meta.version 3``, the full section set (``board``, ``boards``,
``component_class_settings``, ``cvpcb``, ``libraries``, ``meta``,
``net_settings``, ``pcbnew``, ``schematic``, ``sheets``, ``text_variables``,
``tuning_profiles``), and the Default net class with KiCad's stock values
(``net_settings.meta.version 5``). KiCad tolerates missing keys by
regenerating them, but shipping the real structure is what makes the file a
faithful starting point instead of an empty shell.

``sheets`` is populated with the schematic root-sheet UUID and the name
``"Root"`` — the format eeschema writes (the old stub's literal ``"root"``
id never matched the schematic).
"""

import copy
import json
import os
from typing import Any, Dict, Optional


def new_project_settings(project_filename: str, sheet_uuid: Optional[str] = None) -> Dict[str, Any]:
    """Return the full KiCad 10 project structure for a new project.

    Args:
        project_filename: basename recorded in ``meta.filename``
            (e.g. ``"MyBoard.kicad_pro"``).
        sheet_uuid: UUID of the root schematic sheet. When given, ``sheets``
            is populated the way eeschema records it; when None the list is
            left empty and KiCad fills it on first save.
    """
    settings = copy.deepcopy(_KICAD10_DEFAULT_PROJECT)
    settings["meta"]["filename"] = project_filename
    if sheet_uuid:
        settings["sheets"] = [[str(sheet_uuid), "Root"]]
    return settings


def write_kicad_pro(path: str, sheet_uuid: Optional[str] = None) -> None:
    """Write a conformant KiCad 10 ``.kicad_pro`` file to ``path``."""
    settings = new_project_settings(os.path.basename(path), sheet_uuid)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(settings, fh, indent=2)
        fh.write("\n")


# Captured from KiCad 10.0's own SaveProject() output for a fresh project.
# Do not hand-edit values here without re-capturing from a real KiCad — the
# point of this module is that the file matches what KiCad itself writes.
_KICAD10_DEFAULT_PROJECT: Dict[str, Any] = {
    "board": {
        "3dviewports": [],
        "ipc2581": {
            "dist": "",
            "distpn": "",
            "internal_id": "",
            "mfg": "",
            "mpn": "",
        },
        "layer_pairs": [],
        "layer_presets": [],
        "viewports": [],
    },
    "boards": [],
    "component_class_settings": {
        "assignments": [],
        "meta": {"version": 0},
        "sheet_component_classes": {"enabled": False},
    },
    "cvpcb": {"equivalence_files": []},
    "libraries": {
        "pinned_footprint_libs": [],
        "pinned_symbol_libs": [],
    },
    "meta": {"filename": "", "version": 3},
    "net_settings": {
        "classes": [
            {
                "bus_width": 12,
                "clearance": 0.2,
                "diff_pair_gap": 0.25,
                "diff_pair_via_gap": 0.25,
                "diff_pair_width": 0.2,
                "line_style": 0,
                "microvia_diameter": 0.3,
                "microvia_drill": 0.1,
                "name": "Default",
                "pcb_color": "rgba(0, 0, 0, 0.000)",
                "priority": 2147483647,
                "schematic_color": "rgba(0, 0, 0, 0.000)",
                "track_width": 0.2,
                "tuning_profile": "",
                "via_diameter": 0.6,
                "via_drill": 0.3,
                "wire_width": 6,
            }
        ],
        "meta": {"version": 5},
        "net_colors": None,
        "netclass_assignments": None,
        "netclass_patterns": [],
    },
    "pcbnew": {
        "last_paths": {
            "idf": "",
            "netlist": "",
            "plot": "",
            "specctra_dsn": "",
            "vrml": "",
        },
        "page_layout_descr_file": "",
    },
    "schematic": {
        "bus_aliases": {},
        "legacy_lib_dir": "",
        "legacy_lib_list": [],
        "top_level_sheets": [],
    },
    "sheets": [],
    "text_variables": {},
    "tuning_profiles": {
        "meta": {"version": 0},
        "tuning_profiles_impedance_geometric": [],
    },
}
