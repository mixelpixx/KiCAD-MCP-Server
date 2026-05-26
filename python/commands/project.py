"""
Project-related command implementations for KiCAD interface
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import uuid as uuid_module
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pcbnew  # type: ignore

logger = logging.getLogger("kicad_interface")

# Candidate KiCad installation roots, newest first
_KICAD_INSTALL_ROOTS: List[Path] = []
if sys.platform == "win32":
    for _v in ("10.0", "9.0", "8.0"):
        _p = Path(f"C:/Program Files/KiCad/{_v}")
        if _p.exists():
            _KICAD_INSTALL_ROOTS.append(_p)
else:
    for _v in ("10.0", "9.0", "8.0"):
        for _base in ("/usr/share/kicad", f"/usr/local/share/kicad", f"/opt/kicad/{_v}"):
            _p = Path(_base)
            if _p.exists():
                _KICAD_INSTALL_ROOTS.append(_p)
                break


def _kicad_share_dir() -> Optional[Path]:
    """Return the KiCad share/kicad directory for the newest installed version."""
    for root in _KICAD_INSTALL_ROOTS:
        candidate = root / "share" / "kicad"
        if candidate.exists():
            return candidate
    return None


def _kicad_cli() -> Optional[Path]:
    """Return path to kicad-cli executable, or None."""
    for root in _KICAD_INSTALL_ROOTS:
        cli = root / "bin" / ("kicad-cli.exe" if sys.platform == "win32" else "kicad-cli")
        if cli.exists():
            return cli
    return None


def _minimal_sch_content() -> str:
    """Return a minimal valid KiCad schematic suitable for upgrading with kicad-cli."""
    new_uuid = str(uuid_module.uuid4())
    return (
        f'(kicad_sch\n'
        f'\t(version 20250114)\n'
        f'\t(generator "eeschema")\n'
        f'\t(generator_version "9.0")\n'
        f'\t(uuid "{new_uuid}")\n'
        f'\t(paper "A4")\n'
        f'\t(lib_symbols\n'
        f'\t)\n'
        f'\t(sheet_instances\n'
        f'\t\t(path "/"\n'
        f'\t\t\t(page "1")\n'
        f'\t\t)\n'
        f'\t)\n'
        f')\n'
    )


def _minimal_pcb_content() -> str:
    """Return a minimal valid KiCad PCB suitable for upgrading with kicad-cli."""
    new_uuid = str(uuid_module.uuid4())
    return (
        f'(kicad_pcb\n'
        f'\t(version 20241229)\n'
        f'\t(generator "pcbnew")\n'
        f'\t(generator_version "9.0")\n'
        f'\t(general\n'
        f'\t\t(thickness 1.6)\n'
        f'\t)\n'
        f'\t(paper "A4")\n'
        f'\t(layers\n'
        f'\t\t(0 "F.Cu" signal)\n'
        f'\t\t(31 "B.Cu" signal)\n'
        f'\t\t(32 "B.Adhes" user "B.Adhesive")\n'
        f'\t\t(33 "F.Adhes" user "F.Adhesive")\n'
        f'\t\t(34 "B.Paste" user)\n'
        f'\t\t(35 "F.Paste" user)\n'
        f'\t\t(36 "B.SilkS" user "B.Silkscreen")\n'
        f'\t\t(37 "F.SilkS" user "F.Silkscreen")\n'
        f'\t\t(38 "B.Mask" user)\n'
        f'\t\t(39 "F.Mask" user)\n'
        f'\t\t(40 "Dwgs.User" user "User.Drawings")\n'
        f'\t\t(41 "Cmts.User" user "User.Comments")\n'
        f'\t\t(42 "Eco1.User" user "User.Eco1")\n'
        f'\t\t(43 "Eco2.User" user "User.Eco2")\n'
        f'\t\t(44 "Edge.Cuts" user)\n'
        f'\t\t(45 "Margin" user)\n'
        f'\t\t(46 "B.CrtYd" user "B.Courtyard")\n'
        f'\t\t(47 "F.CrtYd" user "F.Courtyard")\n'
        f'\t\t(48 "B.Fab" user)\n'
        f'\t\t(49 "F.Fab" user)\n'
        f'\t)\n'
        f'\t(setup\n'
        f'\t\t(pad_to_mask_clearance 0)\n'
        f'\t)\n'
        f'\t(net 0 "")\n'
        f')\n'
    )


def _upgrade_with_kicad_cli(file_path: str, doc_type: str) -> bool:
    """
    Run `kicad-cli {doc_type} upgrade --force FILE` to convert to the latest KiCad format.
    Returns True on success.  doc_type is "sch" or "pcb".
    """
    cli = _kicad_cli()
    if not cli:
        logger.warning("kicad-cli not found; skipping format upgrade")
        return False
    try:
        result = subprocess.run(
            [str(cli), doc_type, "upgrade", "--force", file_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            logger.info(f"kicad-cli {doc_type} upgrade OK: {file_path}")
            return True
        else:
            logger.warning(
                f"kicad-cli {doc_type} upgrade failed (rc={result.returncode}): "
                f"{result.stderr.strip()}"
            )
            return False
    except Exception as e:
        logger.warning(f"kicad-cli {doc_type} upgrade error: {e}")
        return False


def _kicad_pro_content(project_name: str, board_filename: str, sch_filename: str) -> str:
    """Return a properly structured .kicad_pro JSON matching KiCad 10 format."""
    data = {
        "board": {
            "design_settings": {
                "defaults": {},
                "diff_pair_dimensions": [],
                "drc_exclusions": [],
                "rules": {},
                "track_widths": [],
                "via_dimensions": [],
            }
        },
        "boards": [],
        "libraries": {
            "pinned_footprint_libs": [],
            "pinned_symbol_libs": [],
        },
        "meta": {
            "filename": f"{project_name}.kicad_pro",
            "version": 1,
        },
        "net_settings": {
            "classes": [],
            "meta": {"version": 0},
        },
        "pcbnew": {
            "page_layout_descr_file": "",
        },
        "sheets": [],
        "text_variables": {},
    }
    return json.dumps(data, indent=2) + "\n"


class ProjectCommands:
    """Handles project-related KiCAD operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

    def create_project(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new KiCAD project.

        Files are created as minimal valid S-expressions, then converted to the
        current installed KiCad format by running:
            kicad-cli sch upgrade --force  <file.kicad_sch>
            kicad-cli pcb upgrade --force  <file.kicad_pcb>
        This guarantees the files are in the native KiCad format for the
        installed version (e.g. schematic version 20260306 for KiCad 10.0.3),
        without relying on templates that may carry an older format number.
        """
        try:
            project_name = params.get("name") or params.get("projectName", "New_Project")
            path = params.get("path", os.getcwd())
            template = params.get("template")

            project_dir = os.path.join(path, project_name)
            os.makedirs(project_dir, exist_ok=True)

            project_path   = os.path.join(project_dir, f"{project_name}.kicad_pro")
            board_path     = os.path.join(project_dir, f"{project_name}.kicad_pcb")
            schematic_path = os.path.join(project_dir, f"{project_name}.kicad_sch")

            # ── Schematic ──────────────────────────────────────────────────────
            # Write a minimal valid schematic, then upgrade to the current format
            # via kicad-cli.  This is equivalent to KiCad creating the file itself.
            with open(schematic_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(_minimal_sch_content())
            _upgrade_with_kicad_cli(schematic_path, "sch")
            logger.info(f"Schematic: {schematic_path}")

            # ── PCB ────────────────────────────────────────────────────────────
            # Same strategy: minimal PCB + kicad-cli upgrade.
            # If a user-supplied template is provided, use that.
            pcb_written = False
            if template:
                tmpl = os.path.expanduser(template)
                if tmpl.endswith(".kicad_pcb") and os.path.exists(tmpl):
                    shutil.copy(tmpl, board_path)
                    pcb_written = True
            if not pcb_written:
                with open(board_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(_minimal_pcb_content())
                _upgrade_with_kicad_cli(board_path, "pcb")
                logger.info(f"PCB: {board_path}")

            # ── Project file ───────────────────────────────────────────────────
            with open(project_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(_kicad_pro_content(
                    project_name,
                    os.path.basename(board_path),
                    os.path.basename(schematic_path),
                ))

            logger.info(f"Created KiCad project: {project_path}")
            return {
                "success": True,
                "message": f"Created project: {project_name}",
                "project": {
                    "name": project_name,
                    "path": project_path,
                    "boardPath": board_path,
                    "schematicPath": schematic_path,
                },
            }

        except Exception as e:
            logger.error(f"Error creating project: {str(e)}")
            return {
                "success": False,
                "message": "Failed to create project",
                "errorDetails": str(e),
            }

    def open_project(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Open an existing KiCAD project"""
        try:
            filename = params.get("filename")
            if not filename:
                return {
                    "success": False,
                    "message": "No filename provided",
                    "errorDetails": "The filename parameter is required",
                }

            # Expand user path and make absolute
            filename = os.path.abspath(os.path.expanduser(filename))

            # If it's a project file, get the board file
            if filename.endswith(".kicad_pro"):
                board_path = filename.replace(".kicad_pro", ".kicad_pcb")
            else:
                board_path = filename

            # Load the board
            board = pcbnew.LoadBoard(board_path)
            self.board = board

            return {
                "success": True,
                "message": f"Opened project: {os.path.basename(board_path)}",
                "project": {
                    "name": os.path.splitext(os.path.basename(board_path))[0],
                    "path": filename,
                    "boardPath": board_path,
                },
            }

        except Exception as e:
            logger.error(f"Error opening project: {str(e)}")
            return {
                "success": False,
                "message": "Failed to open project",
                "errorDetails": str(e),
            }

    def save_project(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Save the current KiCAD project"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            filename = params.get("filename")
            if filename:
                # Save to new location
                filename = os.path.abspath(os.path.expanduser(filename))
                self.board.SetFileName(filename)

            # Save the board
            pcbnew.SaveBoard(self.board.GetFileName(), self.board)

            return {
                "success": True,
                "message": f"Saved project to: {self.board.GetFileName()}",
                "project": {
                    "name": os.path.splitext(os.path.basename(self.board.GetFileName()))[0],
                    "path": self.board.GetFileName(),
                },
            }

        except Exception as e:
            logger.error(f"Error saving project: {str(e)}")
            return {
                "success": False,
                "message": "Failed to save project",
                "errorDetails": str(e),
            }

    def get_project_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get information about the current project"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            title_block = self.board.GetTitleBlock()
            filename = self.board.GetFileName()

            return {
                "success": True,
                "project": {
                    "name": os.path.splitext(os.path.basename(filename))[0],
                    "path": filename,
                    "title": title_block.GetTitle(),
                    "date": title_block.GetDate(),
                    "revision": title_block.GetRevision(),
                    "company": title_block.GetCompany(),
                    "comment1": title_block.GetComment(0),
                    "comment2": title_block.GetComment(1),
                    "comment3": title_block.GetComment(2),
                    "comment4": title_block.GetComment(3),
                },
            }

        except Exception as e:
            logger.error(f"Error getting project info: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get project information",
                "errorDetails": str(e),
            }
