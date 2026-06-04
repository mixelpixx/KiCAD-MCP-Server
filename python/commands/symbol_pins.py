"""
Symbol pin discovery commands.

Read-only tools for inspecting a symbol's pins straight from the KiCad symbol
libraries, without needing a schematic loaded. Useful as a pre-flight step before
placing components and wiring nets (e.g. discover pin numbers/names before
connect_to_net). Complements ``get_schematic_pin_locations`` (which reports pin
coordinates only *after* a symbol has been placed on a schematic).

Tools:
  - list_symbol_pins:        pins for one symbol, read straight from the library file
  - batch_list_symbol_pins:  pins for many symbols in one call (+ body bounding box)
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from commands.dynamic_symbol_loader import DynamicSymbolLoader

logger = logging.getLogger("kicad_interface")

# Standard symmetric 2-pin passives that qualify for compact output in
# batch_list_symbol_pins (their pin detail is rarely needed when placing).
COMPACT_SYMBOLS = {
    "Device:R",
    "Device:R_Small",
    "Device:R_US",
    "Device:C",
    "Device:C_Small",
    "Device:C_Polarized",
    "Device:C_Polarized_Small",
    "Device:L",
    "Device:L_Small",
    "Device:LED",
    "Device:D",
    "Device:D_Zener",
    "Device:D_Schottky",
    "Device:Ferrite_Bead",
}

# Pin-envelope padding (mm) used to derive a symbol body bounding box (50 mil).
_BODY_PAD_MM = 1.27

# Matches a pin S-expression inside a symbol definition, capturing
# type, x, y, angle, name and number.
_PIN_RE = re.compile(
    r"\(pin\s+(\S+)\s+\S+\s+\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\)"
    r'.*?\(name\s+"([^"]*)".*?\(number\s+"([^"]*)"',
    re.DOTALL,
)


def _parse_symbol_pins(
    loader: DynamicSymbolLoader, library_name: str, symbol_name: str
) -> List[Dict[str, Any]]:
    """Return pin data for a symbol read directly from its library file (no schematic needed).

    Each entry: {"number", "name", "type", "x", "y", "angle"} where x/y/angle are in
    symbol-local coordinates (Y increases upward, per the KiCad library convention).

    Raises ValueError (carrying .suggestions) if the symbol cannot be found — this mirrors
    DynamicSymbolLoader.extract_symbol_from_library's behaviour for close-match hints.
    """
    block = loader.extract_symbol_from_library(library_name, symbol_name)
    if not block:
        err = ValueError(f"Symbol '{library_name}:{symbol_name}' not found")
        err.suggestions = []  # type: ignore[attr-defined]
        raise err
    pins: List[Dict[str, Any]] = []
    for m in _PIN_RE.finditer(block):
        pins.append(
            {
                "number": m.group(6),
                "name": m.group(5),
                "type": m.group(1),
                "x": float(m.group(2)),
                "y": float(m.group(3)),
                "angle": float(m.group(4)),
            }
        )
    return sorted(pins, key=lambda p: (len(p["number"]), p["number"]))


def _body_bbox(pins: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """Bounding box of the pin envelope expanded by _BODY_PAD_MM on each side."""
    coords = [(p["x"], p["y"]) for p in pins if "x" in p]
    if not coords:
        return None
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return {
        "x_min": round(min(xs) - _BODY_PAD_MM, 4),
        "y_min": round(min(ys) - _BODY_PAD_MM, 4),
        "x_max": round(max(xs) + _BODY_PAD_MM, 4),
        "y_max": round(max(ys) + _BODY_PAD_MM, 4),
        "width": round(max(xs) - min(xs) + 2 * _BODY_PAD_MM, 4),
        "height": round(max(ys) - min(ys) + 2 * _BODY_PAD_MM, 4),
    }


class SymbolPinCommands:
    """Handlers for symbol pin discovery tools. Stateless; each call builds its own loader."""

    def list_symbol_pins(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List pin numbers, names and types for one symbol, read from its library."""
        logger.info("Listing symbol pins from library")
        try:
            symbol_spec = params.get("symbol", "")
            schematic_path = params.get("schematicPath")

            if not symbol_spec or ":" not in symbol_spec:
                return {"success": False, "message": "symbol must be 'Library:SymbolName'"}

            library_name, symbol_name = symbol_spec.split(":", 1)
            project_path = Path(schematic_path).parent if schematic_path else None
            loader = DynamicSymbolLoader(project_path=project_path)

            try:
                pins = _parse_symbol_pins(loader, library_name, symbol_name)
            except ValueError as e:
                return {
                    "success": False,
                    "message": str(e),
                    "suggestions": getattr(e, "suggestions", []),
                }

            return {
                "success": True,
                "symbol": symbol_spec,
                "pin_count": len(pins),
                "pins": pins,
            }

        except Exception as e:
            logger.error(f"Error listing symbol pins: {e}")
            return {"success": False, "message": str(e)}

    def batch_list_symbol_pins(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List pins (+ body bounding box) for multiple symbols in a single call."""
        logger.info("Batch listing symbol pins")
        try:
            symbols = params.get("symbols", [])
            schematic_path = params.get("schematicPath")
            compact = bool(params.get("compact", False))

            if not symbols:
                return {"success": False, "message": "symbols list is required"}

            project_path = Path(schematic_path).parent if schematic_path else None
            loader = DynamicSymbolLoader(project_path=project_path)
            results: Dict[str, Any] = {}
            errors: Dict[str, Any] = {}

            for symbol_spec in symbols:
                if ":" not in symbol_spec:
                    errors[symbol_spec] = "symbol must be 'Library:SymbolName'"
                    continue
                library_name, symbol_name = symbol_spec.split(":", 1)
                try:
                    pins = _parse_symbol_pins(loader, library_name, symbol_name)
                except ValueError as e:
                    errors[symbol_spec] = {
                        "message": str(e),
                        "suggestions": getattr(e, "suggestions", []),
                    }
                    continue

                body_bbox = _body_bbox(pins)
                is_symmetric_2pin = len(pins) == 2 and (
                    symbol_spec in COMPACT_SYMBOLS
                    or all(p.get("type", "") == "passive" for p in pins)
                )
                if compact and is_symmetric_2pin:
                    results[symbol_spec] = {
                        "pin_count": len(pins),
                        "body_bbox": body_bbox,
                        "is_symmetric": True,
                        "compact": True,
                        "note": "Pin detail omitted (compact mode, symmetric 2-pin passive). "
                        "Set compact=false to see individual pin coords.",
                    }
                else:
                    results[symbol_spec] = {
                        "pins": pins,
                        "pin_count": len(pins),
                        "body_bbox": body_bbox,
                    }

            return {
                "success": len(errors) == 0,
                "symbols": results,
                "errors": errors if errors else None,
            }

        except Exception as e:
            logger.error(f"Error in batch_list_symbol_pins: {e}")
            return {"success": False, "message": str(e)}
