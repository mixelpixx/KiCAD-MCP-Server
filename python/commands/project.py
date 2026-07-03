"""
Project-related command implementations for KiCAD interface
"""

import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

import pcbnew  # type: ignore
from utils.kicad_project import write_kicad_pro

logger = logging.getLogger("kicad_interface")


class ProjectCommands:
    """Handles project-related KiCAD operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

    def create_project(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new KiCAD project"""
        try:
            # Accept both 'name' (from MCP tool) and 'projectName' (legacy)
            project_name = params.get("name") or params.get("projectName", "New_Project")
            path = params.get("path", os.getcwd())
            template = params.get("template")

            # Generate the full project path
            project_path = os.path.join(path, project_name)
            if not project_path.endswith(".kicad_pro"):
                project_path += ".kicad_pro"

            # Create project directory if it doesn't exist
            os.makedirs(os.path.dirname(project_path), exist_ok=True)

            # Create a new board
            board = pcbnew.BOARD()

            # Set project properties
            board.GetTitleBlock().SetTitle(project_name)

            # Set current date with proper parameter
            from datetime import datetime

            current_date = datetime.now().strftime("%Y-%m-%d")
            board.GetTitleBlock().SetDate(current_date)

            # If template is specified, try to load it
            if template:
                template_path = os.path.expanduser(template)
                if os.path.exists(template_path):
                    template_board = pcbnew.LoadBoard(template_path)
                    # Copy settings from template
                    board.SetDesignSettings(template_board.GetDesignSettings())
                    board.SetLayerStack(template_board.GetLayerStack())

            # Save the board
            board_path = project_path.replace(".kicad_pro", ".kicad_pcb")
            board.SetFileName(board_path)
            pcbnew.SaveBoard(board_path, board)

            # Create schematic from a blank KiCad 10 template (empty lib_symbols,
            # no placed symbols). The old template_with_symbols_expanded.kicad_sch
            # pre-seeded _TEMPLATE_* symbols that leaked into every new project;
            # the live add tool synthesizes its own lib_symbols via the dynamic
            # loader, so a blank start is correct (issue #221, also closes #243).
            schematic_path = project_path.replace(".kicad_pro", ".kicad_sch")
            template_sch_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..",
                "templates",
                "blank.kicad_sch",
            )

            if os.path.exists(template_sch_path):
                # Copy template schematic
                shutil.copy(template_sch_path, schematic_path)

                # Regenerate UUID to ensure uniqueness for each created project
                import re
                import uuid as uuid_module

                with open(schematic_path, "r", encoding="utf-8") as f:
                    content = f.read()
                schematic_root_uuid = str(uuid_module.uuid4())
                content = re.sub(
                    r"\(uuid [0-9a-fA-F-]+\)",
                    f"(uuid {schematic_root_uuid})",
                    content,
                    count=1,  # Only replace first (schematic) UUID
                )
                with open(schematic_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)

                logger.info(f"Created schematic from template: {schematic_path}")
            else:
                # Fallback: create minimal schematic
                logger.warning(
                    f"Template not found at {template_sch_path}, creating minimal schematic"
                )
                import uuid as uuid_module

                schematic_root_uuid = str(uuid_module.uuid4())
                with open(schematic_path, "w", encoding="utf-8", newline="\n") as f:
                    # KiCad 10 schematic header (matches what eeschema writes for a
                    # new file). The older 20250114 token is the KiCad 9 format and
                    # is stale under KiCad 10 (issue #221).
                    f.write(
                        '(kicad_sch (version 20260306) (generator "eeschema")'
                        ' (generator_version "10.0")\n\n'
                    )
                    f.write(f"  (uuid {schematic_root_uuid})\n\n")
                    f.write('  (paper "A4")\n\n')
                    f.write("  (lib_symbols\n  )\n\n")
                    f.write('  (sheet_instances\n    (path "/" (page "1"))\n  )\n')
                    f.write(")\n")

            # Write a conformant KiCad 10 .kicad_pro (issue #220). The old
            # hand-rolled stub carried only board.filename plus a sheets entry
            # with the literal id "root"; KiCad regenerated defaults on open and
            # discarded any intended configuration. write_kicad_pro emits the
            # full structure KiCad 10 itself writes for a new project, with the
            # sheets entry pointing at the real schematic root-sheet UUID.
            write_kicad_pro(project_path, sheet_uuid=schematic_root_uuid)

            self.board = board

            # Normalize returned paths to a single separator (forward slashes).
            # os.path.join mixes separators on Windows when the caller passes a
            # path with forward slashes (issue #224): the joined filename used a
            # backslash while the rest used forward slashes. The on-disk writes
            # above keep the OS-native paths; only the reported paths are
            # normalized so callers get consistent, predictable values.
            return {
                "success": True,
                "message": f"Created project: {project_name}",
                "project": {
                    "name": project_name,
                    "path": Path(project_path).as_posix(),
                    "boardPath": Path(board_path).as_posix(),
                    "schematicPath": Path(schematic_path).as_posix(),
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
