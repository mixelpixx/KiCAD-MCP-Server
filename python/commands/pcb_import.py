"""
Vendor PCB → KiCad (.kicad_pcb) import via KiCad 10's native ``kicad-cli pcb import``.

KiCad 10.0 ships built-in importers for several non-KiCad PCB formats (PADS,
Altium, Eagle, CADSTAR, Fabmaster, P-CAD, SolidWorks PCB, plus binary Cadence
Allegro ``.brd`` files detected via ``--format auto``). This module exposes a
single MCP command, ``import_pcb``, that shells out to that CLI subcommand.

GOTCHA: the ``--format`` enum accepted by kicad-cli is
``auto|pads|altium|eagle|cadstar|fabmaster|pcad|solidworks`` — there is no
"allegro"/"cadence"/"brd" literal. Binary Cadence Allegro ``.brd`` files MUST
be imported with ``--format auto`` (kicad-cli auto-detects Allegro's binary
magic and reports "using Allegro format" on stdout); passing an explicit
``--format allegro`` errors with "Invalid format: allegro".

This only imports PCB/layout data. kicad-cli has no schematic-side importer
for Cadence Concept HDL / OrCAD Capture schematics — only the PCB half of a
proprietary-format board round-trips through this tool.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Any, Dict, Optional

logger = logging.getLogger("kicad_interface")

# Formats accepted by `kicad-cli pcb import --format`.
VALID_FORMATS = {"auto", "pads", "altium", "eagle", "cadstar", "fabmaster", "pcad", "solidworks"}
VALID_REPORT_FORMATS = {"none", "json", "text"}

_USING_FORMAT_RE = re.compile(r"using (\S+) format", re.IGNORECASE)


class PcbImportCommands:
    """Handles the `import_pcb` MCP command (kicad-cli pcb import wrapper)."""

    def __init__(self) -> None:
        from utils.kicad_cli import resolve_kicad_cli

        self._kicad_cli = resolve_kicad_cli()

    def import_pcb(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert a vendor PCB file to a KiCad `.kicad_pcb` file.

        Params
        ------
        inputFile    : path to the vendor board file (required)
        outputFile   : destination .kicad_pcb path   (optional; defaults beside inputFile)
        format       : auto|pads|altium|eagle|cadstar|fabmaster|pcad|solidworks (optional; default "auto")
        reportFormat : none|json|text                (optional; default "none")
        """
        from utils.kicad_cli import kicad_cli_not_found_message

        input_file: Optional[str] = params.get("inputFile")
        output_file: Optional[str] = params.get("outputFile")
        fmt: str = params.get("format") or "auto"
        report_format: str = params.get("reportFormat") or "none"

        if not input_file:
            return {"success": False, "error": "inputFile is required"}
        if not os.path.exists(input_file):
            return {"success": False, "error": f"inputFile not found: {input_file}"}
        if fmt not in VALID_FORMATS:
            return {
                "success": False,
                "error": f"Invalid format: {fmt!r}. Must be one of {sorted(VALID_FORMATS)}",
            }
        if report_format not in VALID_REPORT_FORMATS:
            return {
                "success": False,
                "error": f"Invalid reportFormat: {report_format!r}. Must be one of {sorted(VALID_REPORT_FORMATS)}",
            }

        cli = self._kicad_cli
        if not cli:
            return {"success": False, "error": kicad_cli_not_found_message()}

        if not output_file:
            input_stem = os.path.splitext(os.path.basename(input_file))[0]
            output_file = os.path.join(os.path.dirname(os.path.abspath(input_file)), input_stem + ".kicad_pcb")

        report_file: Optional[str] = None
        if report_format != "none":
            report_file = output_file + ".import-report." + ("json" if report_format == "json" else "txt")

        cmd = [cli, "pcb", "import", "--format", fmt, "-o", output_file]
        if report_format != "none":
            cmd += ["--report-format", report_format, "--report-file", report_file]
        cmd.append(input_file)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except Exception as e:  # noqa: BLE001 - surface subprocess failures as tool errors
            return {"success": False, "error": str(e)}

        if result.returncode != 0 or not os.path.exists(output_file):
            return {
                "success": False,
                "error": result.stderr.strip() or result.stdout.strip() or "kicad-cli exited non-zero",
            }

        detected_format = fmt
        match = _USING_FORMAT_RE.search(result.stdout or "")
        if match:
            detected_format = match.group(1)

        response: Dict[str, Any] = {
            "success": True,
            "outputFile": output_file,
            "format": detected_format,
        }

        if report_file:
            try:
                with open(report_file, "r", encoding="utf-8", errors="replace") as fh:
                    response["report"] = fh.read()
            except OSError as e:
                logger.warning("Could not read import report %s: %s", report_file, e)
                response["report"] = None
            finally:
                try:
                    if os.path.exists(report_file):
                        os.remove(report_file)
                except OSError:
                    pass

        return response
