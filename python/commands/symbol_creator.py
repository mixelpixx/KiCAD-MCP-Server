"""
Symbol Creator for KiCAD MCP Server

Creates and edits .kicad_sym symbol library files using raw S-Expression text generation.
No sexpdata – pure f-string assembly to guarantee format correctness.

KiCAD 9 .kicad_sym format:
  - Library file starts with (kicad_symbol_lib (version 20241209) ...)
  - Each symbol has a parent block with properties + two sub-symbols:
      SymbolName_0_1  → body graphics (rectangle, polyline, circle, arc)
      SymbolName_1_1  → pins
  - All coordinates in mm, 2.54mm grid typical for schematic symbols
"""

import os
import re
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("kicad_interface")

KICAD9_SYMBOL_LIB_VERSION = "20241209"

# Pin electrical types
PIN_TYPES = {
    "input", "output", "bidirectional", "tri_state", "passive",
    "free", "unspecified", "power_in", "power_out",
    "open_collector", "open_emitter", "no_connect",
}

# Pin graphic shapes
PIN_SHAPES = {
    "line", "inverted", "clock", "inverted_clock", "input_low",
    "clock_low", "output_low", "falling_edge_clock", "non_logic",
}


def _fmt(v: float) -> str:
    return f"{v:g}"


def _esc(s: str) -> str:
    return s.replace('"', '\\"')


class SymbolCreator:
    """Creates and edits KiCAD .kicad_sym symbol library files."""

    # ------------------------------------------------------------------ #
    #  create_symbol                                                       #
    # ------------------------------------------------------------------ #

    def create_symbol(
        self,
        library_path: str,
        name: str,
        reference_prefix: str = "U",
        description: str = "",
        keywords: str = "",
        datasheet: str = "~",
        footprint: str = "",
        in_bom: bool = True,
        on_board: bool = True,
        pins: Optional[List[Dict[str, Any]]] = None,
        rectangles: Optional[List[Dict[str, Any]]] = None,
        polylines: Optional[List[Dict[str, Any]]] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """
        Add a new symbol to a .kicad_sym library (creates the file if missing).

        Parameters
        ----------
        library_path : str
            Path to the .kicad_sym file (created if missing).
        name : str
            Symbol name, e.g. "TMC2209", "MyOpAmp".
        reference_prefix : str
            Schematic reference prefix, e.g. "U", "R", "J".
        description : str
            Human-readable description.
        keywords : str
            Space-separated keyword string for search.
        datasheet : str
            Datasheet URL or "~".
        footprint : str
            Default footprint, e.g. "Package_SO:SOIC-8".
        in_bom : bool
            Include in BOM (default True).
        on_board : bool
            Include in netlist for PCB (default True).
        pins : list of dicts
            Each pin dict:
              name     (str)   – pin name, e.g. "VCC", "GND", "~" for unnamed
              number   (str)   – pin number, e.g. "1", "A1"
              type     (str)   – electrical type: input|output|bidirectional|
                                  passive|power_in|power_out|tri_state|
                                  open_collector|open_emitter|free|unspecified
              at       (dict)  – {"x": float, "y": float, "angle": float}
                                  angle: 0=right, 90=up, 180=left, 270=down
              length   (float) – pin length in mm (default 2.54)
              shape    (str)   – graphic shape: line|inverted|clock|...
                                  (default "line")
        rectangles : list of dicts or None
            Body rectangles: {"x1","y1","x2","y2", "width"(opt), "fill"(opt)}
            fill: "none"|"outline"|"background" (default "background")
        polylines : list of dicts or None
            {"points": [{"x":float,"y":float},...], "width"(opt), "fill"(opt)}
        overwrite : bool
            Replace existing symbol with same name (default False).

        Returns
        -------
        dict with "success", "library_path", "symbol_name", "pin_count"
        """
        lib_path = Path(library_path)
        if lib_path.suffix.lower() != ".kicad_sym":
            lib_path = lib_path.with_suffix(".kicad_sym")

        lib_path.parent.mkdir(parents=True, exist_ok=True)

        # Load or create library
        if lib_path.exists():
            lib_content = lib_path.read_text(encoding="utf-8")
        else:
            lib_content = (
                f'(kicad_symbol_lib\n'
                f'  (version {KICAD9_SYMBOL_LIB_VERSION})\n'
                f'  (generator "kicad-mcp")\n'
                f'  (generator_version "9.0")\n'
                f')\n'
            )

        # Check for duplicate
        if f'(symbol "{name}"' in lib_content:
            if not overwrite:
                return {
                    "success": False,
                    "error": f'Symbol "{name}" already exists in {lib_path}. Use overwrite=true.',
                    "library_path": str(lib_path),
                }
            lib_content = self._remove_symbol(lib_content, name)

        pins = pins or []
        rectangles = rectangles or []
        polylines = polylines or []

        symbol_block = self._build_symbol_block(
            name=name,
            reference_prefix=reference_prefix,
            description=description,
            keywords=keywords,
            datasheet=datasheet,
            footprint=footprint,
            in_bom=in_bom,
            on_board=on_board,
            pins=pins,
            rectangles=rectangles,
            polylines=polylines,
        )

        # Insert before closing paren of library
        lib_content = lib_content.rstrip()
        if lib_content.endswith(")"):
            lib_content = lib_content[:-1].rstrip() + "\n" + symbol_block + "\n)\n"
        else:
            lib_content += "\n" + symbol_block + "\n)\n"

        lib_path.write_text(lib_content, encoding="utf-8")
        logger.info(f"Created symbol '{name}' in {lib_path} ({len(pins)} pins)")

        return {
            "success": True,
            "library_path": str(lib_path),
            "symbol_name": name,
            "pin_count": len(pins),
        }

    # ------------------------------------------------------------------ #
    #  delete_symbol                                                       #
    # ------------------------------------------------------------------ #

    def delete_symbol(self, library_path: str, name: str) -> Dict[str, Any]:
        """Remove a symbol from a .kicad_sym library."""
        lib_path = Path(library_path)
        if not lib_path.exists():
            return {"success": False, "error": f"Library not found: {library_path}"}

        content = lib_path.read_text(encoding="utf-8")
        if f'(symbol "{name}"' not in content:
            return {"success": False, "error": f'Symbol "{name}" not found in {library_path}'}

        new_content = self._remove_symbol(content, name)
        lib_path.write_text(new_content, encoding="utf-8")
        return {"success": True, "library_path": str(lib_path), "deleted": name}

    # ------------------------------------------------------------------ #
    #  list_symbols  (in a single library file)                           #
    # ------------------------------------------------------------------ #

    def list_symbols(self, library_path: str) -> Dict[str, Any]:
        """List all symbols in a .kicad_sym file."""
        lib_path = Path(library_path)
        if not lib_path.exists():
            return {"success": False, "error": f"Library not found: {library_path}"}

        content = lib_path.read_text(encoding="utf-8")
        # Only top-level symbols (not sub-symbols like _0_1 or _1_1)
        names = re.findall(r'^\s*\(symbol "([^"_][^"]*)"', content, re.MULTILINE)
        # Filter out sub-symbols (contain _N_N suffix)
        symbols = [n for n in names if not re.search(r'_\d+_\d+$', n)]
        return {
            "success": True,
            "library_path": str(lib_path),
            "symbol_count": len(symbols),
            "symbols": symbols,
        }

    # ------------------------------------------------------------------ #
    #  register_symbol_library                                             #
    # ------------------------------------------------------------------ #

    def register_symbol_library(
        self,
        library_path: str,
        library_name: Optional[str] = None,
        description: str = "",
        scope: str = "project",
        project_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Register a .kicad_sym library in KiCAD's sym-lib-table.

        Parameters
        ----------
        library_path : str  – path to the .kicad_sym file
        library_name : str  – nickname (default: file stem)
        scope : str         – "project" or "global"
        project_path : str  – .kicad_pro or directory (for scope=project)
        """
        sym_path = Path(library_path)
        name = library_name or sym_path.stem
        uri = str(sym_path).replace("\\", "/")

        if scope == "project":
            if project_path:
                proj = Path(project_path)
                table_dir = proj if proj.is_dir() else proj.parent
            else:
                table_dir = sym_path.parent
            table_path = table_dir / "sym-lib-table"
        else:
            cfg_dirs = [
                Path(os.environ.get("APPDATA", "")) / "kicad" / "9.0",
                Path.home() / ".config" / "kicad" / "9.0",
            ]
            table_path = None
            for d in cfg_dirs:
                candidate = d / "sym-lib-table"
                if candidate.exists():
                    table_path = candidate
                    break
            if table_path is None:
                for d in cfg_dirs:
                    try:
                        d.mkdir(parents=True, exist_ok=True)
                        table_path = d / "sym-lib-table"
                        break
                    except OSError:
                        continue
            if table_path is None:
                return {"success": False, "error": "Could not find/create global sym-lib-table"}

        if table_path.exists():
            content = table_path.read_text(encoding="utf-8")
        else:
            content = "(sym_lib_table\n  (version 7)\n)\n"

        if f'(name "{name}")' in content or uri in content:
            return {
                "success": True,
                "already_registered": True,
                "table_path": str(table_path),
                "library_name": name,
            }

        new_entry = (
            f'  (lib (name "{name}")'
            f'(type "KiCad")'
            f'(uri "{uri}")'
            f'(options "")'
            f'(descr "{_esc(description)}"))'
        )
        content = content.rstrip()
        if content.endswith(")"):
            content = content[:-1].rstrip() + "\n" + new_entry + "\n)\n"
        else:
            content += "\n" + new_entry + "\n)\n"

        table_path.write_text(content, encoding="utf-8")
        logger.info(f"Registered symbol library '{name}' in {table_path}")

        return {
            "success": True,
            "already_registered": False,
            "table_path": str(table_path),
            "library_name": name,
            "uri": uri,
        }

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _build_symbol_block(
        self,
        name: str,
        reference_prefix: str,
        description: str,
        keywords: str,
        datasheet: str,
        footprint: str,
        in_bom: bool,
        on_board: bool,
        pins: List[Dict[str, Any]],
        rectangles: List[Dict[str, Any]],
        polylines: List[Dict[str, Any]],
    ) -> str:
        lines: List[str] = []
        bom_str = "yes" if in_bom else "no"
        board_str = "yes" if on_board else "no"

        lines.append(f'  (symbol "{name}"')
        lines.append(f'    (exclude_from_sim no)')
        lines.append(f'    (in_bom {bom_str})')
        lines.append(f'    (on_board {board_str})')

        # Properties
        lines.extend(_property_block("Reference", reference_prefix, 2.54, 0, visible=True))
        lines.extend(_property_block("Value", name, 0, -2.54, visible=True))
        lines.extend(_property_block("Footprint", footprint, 0, -5.08, visible=False))
        lines.extend(_property_block("Datasheet", datasheet or "~", 0, -7.62, visible=False))
        lines.extend(_property_block("Description", description, 0, -10.16, visible=False))
        if keywords:
            lines.extend(_property_block("ki_keywords", keywords, 0, 0, visible=False))

        # Sub-symbol _0_1: body graphics
        lines.append(f'    (symbol "{name}_0_1"')
        for rect in rectangles:
            lines.extend(_rect_sym_lines(rect))
        for pl in polylines:
            lines.extend(_polyline_lines(pl))
        lines.append(f'    )')

        # Sub-symbol _1_1: pins
        lines.append(f'    (symbol "{name}_1_1"')
        for pin in pins:
            lines.extend(_pin_lines(pin))
        lines.append(f'    )')

        lines.append(f'  )')
        return "\n".join(lines)

    def _remove_symbol(self, content: str, name: str) -> str:
        """Remove a complete symbol block from library content."""
        lines = content.split("\n")
        result = []
        skip = False
        depth = 0

        for line in lines:
            stripped = line.strip()
            if not skip:
                if re.match(rf'^\s*\(symbol "{re.escape(name)}"', line) and \
                        not re.search(r'_\d+_\d+"', line):
                    skip = True
                    depth = stripped.count("(") - stripped.count(")")
                    continue
                result.append(line)
            else:
                depth += stripped.count("(") - stripped.count(")")
                if depth <= 0:
                    skip = False

        return "\n".join(result)


# ------------------------------------------------------------------ #
#  S-Expression helper functions                                       #
# ------------------------------------------------------------------ #

def _property_block(
    key: str, value: str, x: float, y: float, visible: bool = True
) -> List[str]:
    hide = "" if visible else "\n      (hide yes)"
    return [
        f'    (property "{_esc(key)}" "{_esc(value)}"',
        f'      (at {_fmt(x)} {_fmt(y)} 0)',
        f'      (effects',
        f'        (font (size 1.27 1.27))',
        f'      ){hide}',
        f'    )',
    ]


def _rect_sym_lines(rect: Dict[str, Any]) -> List[str]:
    x1 = _fmt(rect.get("x1", -2.54))
    y1 = _fmt(rect.get("y1", -2.54))
    x2 = _fmt(rect.get("x2", 2.54))
    y2 = _fmt(rect.get("y2", 2.54))
    w = _fmt(rect.get("width", 0.254))
    fill = rect.get("fill", "background")
    return [
        f'      (rectangle',
        f'        (start {x1} {y1})',
        f'        (end {x2} {y2})',
        f'        (stroke (width {w}) (type default))',
        f'        (fill (type {fill}))',
        f'      )',
    ]


def _polyline_lines(pl: Dict[str, Any]) -> List[str]:
    pts = pl.get("points", [])
    w = _fmt(pl.get("width", 0.254))
    fill = pl.get("fill", "none")
    lines = [
        f'      (polyline',
        f'        (pts',
    ]
    for pt in pts:
        lines.append(f'          (xy {_fmt(pt["x"])} {_fmt(pt["y"])})')
    lines += [
        f'        )',
        f'        (stroke (width {w}) (type default))',
        f'        (fill (type {fill}))',
        f'      )',
    ]
    return lines


def _pin_lines(pin: Dict[str, Any]) -> List[str]:
    ptype = pin.get("type", "passive").lower()
    shape = pin.get("shape", "line").lower()
    at = pin.get("at", {"x": 0, "y": 0, "angle": 0})
    x = _fmt(at.get("x", 0))
    y = _fmt(at.get("y", 0))
    angle = _fmt(at.get("angle", 0))
    length = _fmt(pin.get("length", 2.54))
    pin_name = pin.get("name", "~")
    pin_number = str(pin.get("number", "1"))

    return [
        f'      (pin {ptype} {shape}',
        f'        (at {x} {y} {angle})',
        f'        (length {length})',
        f'        (name "{_esc(pin_name)}"',
        f'          (effects (font (size 1.27 1.27)))',
        f'        )',
        f'        (number "{_esc(pin_number)}"',
        f'          (effects (font (size 1.27 1.27)))',
        f'        )',
        f'      )',
    ]
