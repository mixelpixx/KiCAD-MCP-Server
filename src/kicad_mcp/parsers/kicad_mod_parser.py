"""
Parser for KiCad .kicad_mod footprint files.

Extracts the fields that the MCP get_footprint_info tool exposes to clients:
  name        – footprint name  (str)
  library     – library nickname, injected by caller  (str)
  description – (descr "…") token  (str | None)
  keywords    – (tags "…") token  (str | None)
  pads        – list of pad objects: [{number, type, shape}, …]  (list[dict])
  layers      – sorted unique list of canonical layer names used  (list[str])
  courtyard   – {"width": float, "height": float} from F.CrtYd geometry  (dict | None)
  attributes  – {"type": str, "board_only": bool, …}  (dict | None)

KiCad S-expression file format reference:
  https://dev-docs.kicad.org/en/file-formats/sexpr-intro/index.html#_footprint
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("kicad_interface")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_kicad_mod(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Parse a .kicad_mod file and return a dict whose keys match the fields
    expected by the TypeScript MCP tool handler (src/tools/library.ts).

    Returns None if the file does not exist or cannot be read.
    """
    path = Path(file_path)
    if not path.exists():
        logger.debug(f"parse_kicad_mod: file not found: {file_path}")
        return None

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning(f"parse_kicad_mod: cannot read {file_path}: {e}")
        return None

    logger.debug(f"parse_kicad_mod: parsing {path.name} ({len(content)} chars)")

    result: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Footprint name: (footprint "NAME" …
    # Per spec, in a library file the name is the ENTRY_NAME only (no lib prefix).
    # ------------------------------------------------------------------
    m = re.search(r'^\s*\(footprint\s+"((?:[^"\\]|\\.)*)"', content, re.MULTILINE)
    if not m:
        # Older / unquoted format
        m = re.search(r"^\s*\(footprint\s+(\S+)", content, re.MULTILINE)
    result["name"] = _unescape(m.group(1)) if m else path.stem
    logger.debug(f"parse_kicad_mod: name={result['name']!r}")

    # ------------------------------------------------------------------
    # Description: (descr "…")
    # ------------------------------------------------------------------
    m = re.search(r'\(descr\s+"((?:[^"\\]|\\.)*)"\)', content)
    result["description"] = _unescape(m.group(1)) if m else None
    logger.debug(f"parse_kicad_mod: description={result['description']!r}")

    # ------------------------------------------------------------------
    # Keywords / tags: (tags "…")
    # ------------------------------------------------------------------
    m = re.search(r'\(tags\s+"((?:[^"\\]|\\.)*)"\)', content)
    result["keywords"] = _unescape(m.group(1)) if m else None
    logger.debug(f"parse_kicad_mod: keywords={result['keywords']!r}")

    # ------------------------------------------------------------------
    # Attributes: (attr TYPE [board_only] [exclude_from_pos_files] [exclude_from_bom])
    # TYPE is smd | through_hole (no quotes)
    # ------------------------------------------------------------------
    m = re.search(r"\(attr\s+([^)]+)\)", content)
    if m:
        tokens = m.group(1).split()
        result["attributes"] = {
            "type": tokens[0] if tokens else "unspecified",
            "board_only": "board_only" in tokens,
            "exclude_from_pos_files": "exclude_from_pos_files" in tokens,
            "exclude_from_bom": "exclude_from_bom" in tokens,
        }
    else:
        result["attributes"] = None
    logger.debug(f"parse_kicad_mod: attributes={result['attributes']!r}")

    # ------------------------------------------------------------------
    # Pads: (pad "NUMBER" TYPE SHAPE …)
    # Return each pad as an object; deduplicate by number (first wins).
    # ------------------------------------------------------------------
    result["pads"] = _extract_pads(content)
    logger.debug(f"parse_kicad_mod: pads count={len(result['pads'])}, pads={result['pads']}")

    # ------------------------------------------------------------------
    # Layers: all unique canonical layer names across the whole file.
    # Sources:
    #   (layer "NAME")          – single-layer items (fp_line, fp_text, …)
    #   (layers "A" "B" …)      – pad layer lists
    # ------------------------------------------------------------------
    layers: set = set()
    for m in re.finditer(r'\(layer\s+"([^"]+)"\)', content):
        layers.add(m.group(1))
    for m in re.finditer(r"\(layers\s+([^)]+)\)", content):
        for lyr in re.findall(r'"([^"]+)"', m.group(1)):
            layers.add(lyr)
    result["layers"] = sorted(layers)
    logger.debug(f"parse_kicad_mod: layers={result['layers']}")

    # ------------------------------------------------------------------
    # Courtyard: derive bounding box from F.CrtYd geometry.
    # Prefer fp_rect (most common for standard footprints), fall back to
    # fp_line segments.
    # ------------------------------------------------------------------
    result["courtyard"] = _extract_courtyard(content)
    logger.debug(f"parse_kicad_mod: courtyard={result['courtyard']!r}")

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_pads(content: str) -> List[Dict[str, Any]]:
    """
    Parse all (pad …) blocks and return a list of pad objects.

    Each object has:
      number  – pad number string, e.g. "1", "A1", "GND"
      type    – thru_hole | smd | np_thru_hole | connect
      shape   – rect | circle | oval | roundrect | trapezoid | custom

    Pads are deduplicated by number (first occurrence wins) so that the
    list represents the logical pads of the footprint, not duplicated
    copper entries.
    """
    pads: List[Dict[str, Any]] = []
    seen_numbers: dict = {}

    # KiCad 6+ quoted format: (pad "NUMBER" TYPE SHAPE …)
    quoted_pattern = re.compile(
        r'\(pad\s+"([^"]*)"\s+'
        r"(thru_hole|smd|np_thru_hole|connect)\s+"
        r"(rect|circle|oval|roundrect|trapezoid|custom)\b"
    )
    for m in quoted_pattern.finditer(content):
        number, ptype, shape = m.group(1), m.group(2), m.group(3)
        if number not in seen_numbers:
            seen_numbers[number] = True
            pads.append({"number": number, "type": ptype, "shape": shape})

    if not pads:
        # Older / unquoted format: (pad NUMBER TYPE SHAPE …)
        unquoted_pattern = re.compile(
            r"\(pad\s+(\S+)\s+"
            r"(thru_hole|smd|np_thru_hole|connect)\s+"
            r"(rect|circle|oval|roundrect|trapezoid|custom)\b"
        )
        for m in unquoted_pattern.finditer(content):
            number, ptype, shape = m.group(1), m.group(2), m.group(3)
            if number not in seen_numbers:
                seen_numbers[number] = True
                pads.append({"number": number, "type": ptype, "shape": shape})

    return pads


def _unescape(s: str) -> str:
    """Reverse KiCad S-expression string escaping."""
    return s.replace('\\"', '"').replace("\\\\", "\\")


def _extract_blocks(content: str, token: str) -> List[str]:
    """
    Return all S-expression blocks that start with `(token ` by tracking
    parenthesis depth.  This correctly handles nested parens inside blocks.
    """
    blocks: List[str] = []
    pattern = re.compile(r"\(" + re.escape(token) + r"\b")

    for match in pattern.finditer(content):
        start = match.start()
        depth = 0
        i = start
        while i < len(content):
            ch = content[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    blocks.append(content[start : i + 1])
                    break
            i += 1

    return blocks


def _extract_courtyard(content: str) -> Optional[Dict[str, float]]:
    """
    Compute the courtyard bounding box from F.CrtYd geometry.

    Strategy:
      1. Try fp_rect blocks on F.CrtYd — derive width/height from start/end.
      2. Fall back to fp_line segments on F.CrtYd — compute bounding box of
         all endpoints.
    """
    xs: List[float] = []
    ys: List[float] = []

    # --- fp_rect pass ---
    for block in _extract_blocks(content, "fp_rect"):
        if "F.CrtYd" not in block:
            continue
        s = re.search(r"\(start\s+([-\d.]+)\s+([-\d.]+)\)", block)
        e = re.search(r"\(end\s+([-\d.]+)\s+([-\d.]+)\)", block)
        if s and e:
            xs += [float(s.group(1)), float(e.group(1))]
            ys += [float(s.group(2)), float(e.group(2))]
            logger.debug(
                f"_extract_courtyard: fp_rect F.CrtYd "
                f"start=({s.group(1)},{s.group(2)}) end=({e.group(1)},{e.group(2)})"
            )

    # --- fp_line pass (only if fp_rect found nothing) ---
    if not xs:
        for block in _extract_blocks(content, "fp_line"):
            if "F.CrtYd" not in block:
                continue
            for m in re.finditer(r"\((?:start|end)\s+([-\d.]+)\s+([-\d.]+)\)", block):
                xs.append(float(m.group(1)))
                ys.append(float(m.group(2)))

    if not xs:
        logger.debug("_extract_courtyard: no F.CrtYd geometry found")
        return None

    width = round(abs(max(xs) - min(xs)), 6)
    height = round(abs(max(ys) - min(ys)), 6)
    logger.debug(f"_extract_courtyard: result width={width} height={height}")
    return {"width": width, "height": height}
