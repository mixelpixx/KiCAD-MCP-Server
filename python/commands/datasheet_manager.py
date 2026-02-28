"""
Datasheet Manager for KiCAD MCP Server

Enriches KiCAD schematic symbols with datasheet URLs derived from LCSC part numbers.
Uses direct text manipulation (like dynamic_symbol_loader.py) to avoid
skip-library-induced schematic corruption.

URL schema: https://www.lcsc.com/datasheet/{LCSC#}.pdf
No API key required.
"""

import re
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("kicad_interface")

LCSC_DATASHEET_URL = "https://www.lcsc.com/datasheet/{lcsc}.pdf"
LCSC_PRODUCT_URL = "https://www.lcsc.com/product-detail/{lcsc}.html"

# Values treated as "empty" datasheet
EMPTY_DATASHEET_VALUES = {"~", "", "~{DATASHEET}"}


class DatasheetManager:
    """
    Enriches KiCAD schematics with LCSC datasheet URLs.

    Reads .kicad_sch files, finds symbol instances that have an LCSC property
    but an empty Datasheet property, and fills in the LCSC datasheet URL.
    """

    @staticmethod
    def _normalize_lcsc(lcsc: str) -> Optional[str]:
        """
        Normalize LCSC number to standard format 'C123456'.

        Accepts: 'C123456', '123456', 'c123456'
        Returns: 'C123456' or None if invalid
        """
        lcsc = lcsc.strip()
        if not lcsc:
            return None
        # Remove leading C/c
        without_prefix = lcsc.lstrip("Cc")
        if without_prefix.isdigit():
            return f"C{without_prefix}"
        return None

    @staticmethod
    def _find_lib_symbols_range(lines: List[str]):
        """
        Find the line range of the (lib_symbols ...) section.
        Returns (start, end) line indices or (None, None) if not found.
        These lines must be excluded from symbol-instance processing.
        """
        lib_sym_start = None
        lib_sym_end = None
        depth = 0

        for i, line in enumerate(lines):
            if "(lib_symbols" in line and lib_sym_start is None:
                lib_sym_start = i
                depth = 0
                for ch in line:
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
            elif lib_sym_start is not None and lib_sym_end is None:
                for ch in line:
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                if depth == 0:
                    lib_sym_end = i
                    break

        return lib_sym_start, lib_sym_end

    @staticmethod
    def _process_symbol_block(
        lines: List[str], block_start: int, block_end: int
    ) -> Optional[Dict]:
        """
        Extract LCSC and Datasheet info from a placed symbol block.

        Returns dict with:
          - lcsc: normalized LCSC number or None
          - datasheet_line: line index of Datasheet property or None
          - datasheet_value: current Datasheet value or None
        """
        lcsc_value = None
        datasheet_line_idx = None
        datasheet_current = None

        for k in range(block_start, block_end + 1):
            line = lines[k]

            lcsc_match = re.search(r'\(property\s+"LCSC"\s+"([^"]*)"', line)
            if lcsc_match:
                lcsc_value = lcsc_match.group(1)

            ds_match = re.search(r'\(property\s+"Datasheet"\s+"([^"]*)"', line)
            if ds_match:
                datasheet_line_idx = k
                datasheet_current = ds_match.group(1)

        return {
            "lcsc": lcsc_value,
            "datasheet_line": datasheet_line_idx,
            "datasheet_value": datasheet_current,
        }

    def enrich_schematic(
        self, schematic_path: Path, dry_run: bool = False
    ) -> Dict:
        """
        Scan a .kicad_sch file and fill in missing LCSC datasheet URLs.

        For each placed symbol that has:
          - (property "LCSC" "C123456") set
          - (property "Datasheet" "~") or empty

        Sets:
          - (property "Datasheet" "https://www.lcsc.com/datasheet/C123456.pdf")

        Args:
            schematic_path: Path to .kicad_sch file
            dry_run: If True, return what would be changed without writing

        Returns:
            {
                "success": True,
                "updated": <count>,
                "already_set": <count>,
                "no_lcsc": <count>,
                "no_datasheet_field": <count>,
                "details": [{"reference": "...", "lcsc": "...", "url": "..."}]
            }
        """
        schematic_path = Path(schematic_path)
        if not schematic_path.exists():
            return {
                "success": False,
                "message": f"Schematic not found: {schematic_path}",
            }

        with open(schematic_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        new_lines = list(lines)

        lib_sym_start, lib_sym_end = self._find_lib_symbols_range(lines)

        updated = 0
        already_set = 0
        no_lcsc = 0
        no_datasheet_field = 0
        details = []

        i = 0
        while i < len(new_lines):
            line = new_lines[i]

            # Skip lib_symbols section
            if lib_sym_start is not None and lib_sym_end is not None:
                if lib_sym_start <= i <= lib_sym_end:
                    i += 1
                    continue

            # Detect placed symbol: (symbol (lib_id "...")
            if re.match(r"\s*\(symbol\s+\(lib_id\s+\"", line):
                block_start = i
                block_depth = 0
                for ch in line:
                    if ch == "(":
                        block_depth += 1
                    elif ch == ")":
                        block_depth -= 1

                j = i + 1
                while j < len(new_lines) and block_depth > 0:
                    for ch in new_lines[j]:
                        if ch == "(":
                            block_depth += 1
                        elif ch == ")":
                            block_depth -= 1
                    if block_depth > 0:
                        j += 1
                    else:
                        break

                block_end = j
                info = self._process_symbol_block(new_lines, block_start, block_end)

                raw_lcsc = info["lcsc"]
                ds_line = info["datasheet_line"]
                ds_value = info["datasheet_value"]

                # Extract reference for reporting
                ref_match = None
                for k in range(block_start, block_end + 1):
                    m = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', new_lines[k])
                    if m:
                        ref_match = m.group(1)
                        break
                reference = ref_match or "?"

                if not raw_lcsc:
                    no_lcsc += 1
                elif ds_line is None:
                    no_datasheet_field += 1
                    logger.warning(
                        f"Symbol {reference} has LCSC={raw_lcsc} but no Datasheet property"
                    )
                else:
                    lcsc_norm = self._normalize_lcsc(raw_lcsc)
                    if not lcsc_norm:
                        no_lcsc += 1
                    elif ds_value not in EMPTY_DATASHEET_VALUES:
                        already_set += 1
                        logger.debug(
                            f"Symbol {reference}: Datasheet already set to {ds_value!r}"
                        )
                    else:
                        url = LCSC_DATASHEET_URL.format(lcsc=lcsc_norm)
                        if not dry_run:
                            new_lines[ds_line] = re.sub(
                                r'(property\s+"Datasheet"\s+)"[^"]*"',
                                f'\\1"{url}"',
                                new_lines[ds_line],
                            )
                        updated += 1
                        details.append(
                            {
                                "reference": reference,
                                "lcsc": lcsc_norm,
                                "url": url,
                                "dry_run": dry_run,
                            }
                        )
                        logger.info(
                            f"{'[DRY RUN] ' if dry_run else ''}Set Datasheet for "
                            f"{reference} ({lcsc_norm}): {url}"
                        )

                i = block_end + 1
                continue

            i += 1

        if not dry_run and updated > 0:
            with open(schematic_path, "w", encoding="utf-8") as f:
                f.write("\n".join(new_lines))
            logger.info(
                f"Saved {schematic_path.name}: {updated} datasheet URLs written"
            )

        return {
            "success": True,
            "updated": updated,
            "already_set": already_set,
            "no_lcsc": no_lcsc,
            "no_datasheet_field": no_datasheet_field,
            "dry_run": dry_run,
            "details": details,
            "schematic": str(schematic_path),
        }

    def get_datasheet_url(self, lcsc: str) -> Optional[str]:
        """
        Return the LCSC datasheet URL for a given LCSC number.
        No network request – pure URL construction.
        """
        norm = self._normalize_lcsc(lcsc)
        if norm:
            return LCSC_DATASHEET_URL.format(lcsc=norm)
        return None

    def get_product_url(self, lcsc: str) -> Optional[str]:
        """Return the LCSC product page URL."""
        norm = self._normalize_lcsc(lcsc)
        if norm:
            return LCSC_PRODUCT_URL.format(lcsc=norm)
        return None
