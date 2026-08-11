"""Shared S-expression parser for KiCad symbol pin definitions."""

import re
from typing import Any, Dict

from sexpdata import Symbol


def parse_symbol_definition(symbol_def: list) -> Dict[str, Dict]:
    """Extract pin metadata from a ``lib_symbols`` symbol definition."""
    pins: Dict[str, Dict[str, Any]] = {}

    # Sub-symbols are named ``<name>_<unit>_<body-style>``. Unit zero is
    # common to every unit, so carry the enclosing unit while descending.
    unit_name_re = re.compile(r"_(\d+)_(\d+)$")

    def extract_pins_recursive(sexp: Any, current_unit: int) -> None:
        """Recursively collect pins while tracking their enclosing unit."""
        if not isinstance(sexp, list):
            return

        if len(sexp) > 1 and sexp[0] == Symbol("symbol") and isinstance(sexp[1], (str, Symbol)):
            match = unit_name_re.search(str(sexp[1]).strip('"'))
            if match:
                current_unit = int(match.group(1))

        if sexp and sexp[0] == Symbol("pin"):
            pin_data = {
                "x": 0,
                "y": 0,
                "angle": 0,
                "length": 0,
                "name": "",
                "number": "",
                "unit": current_unit,
                "type": str(sexp[1]) if len(sexp) > 1 else "passive",
            }

            for item in sexp:
                if not isinstance(item, list) or not item:
                    continue
                if item[0] == Symbol("at") and len(item) >= 3:
                    pin_data["x"] = float(item[1])
                    pin_data["y"] = float(item[2])
                    if len(item) >= 4:
                        pin_data["angle"] = float(item[3])
                elif item[0] == Symbol("length") and len(item) >= 2:
                    pin_data["length"] = float(item[1])
                elif item[0] == Symbol("name") and len(item) >= 2:
                    pin_data["name"] = str(item[1]).strip('"')
                elif item[0] == Symbol("number") and len(item) >= 2:
                    pin_data["number"] = str(item[1]).strip('"')

            # Some community symbols contain a zero-length ghost pin on top of
            # the real pin. Prefer the longer definition, whose ``at`` point is
            # the actual wire endpoint; ties retain stable first-seen ordering.
            if pin_data["number"]:
                pin_number = str(pin_data["number"])
                existing = pins.get(pin_number)
                if existing is None or pin_data["length"] > existing["length"]:
                    pins[pin_number] = pin_data

        for item in sexp:
            if isinstance(item, list):
                extract_pins_recursive(item, current_unit)

    extract_pins_recursive(symbol_def, 0)
    return pins
