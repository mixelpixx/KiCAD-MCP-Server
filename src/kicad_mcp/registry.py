"""Toolset registry — the single source of truth for what tools exist.

Every toolset module in ``kicad_mcp.toolsets`` exposes ``_TOOLS`` (the typed
tool functions) and ``register(mcp)``. This module owns the list of toolset
modules, registers them all on a server, and answers catalog/search queries
for the router meta-tools. Tool counts anywhere else (docs, READMEs) are
derived from here, never hand-maintained.
"""

import importlib
from typing import Any, Callable, Dict, List, Tuple

TOOLSET_MODULES = [
    "board",
    "component",
    "datasheet",
    "design_rules",
    "eagle",
    "export",
    "footprint",
    "freerouting",
    "jlcpcb_api",
    "library",
    "library_symbol",
    "project",
    "router",
    "routing",
    "schematic",
    "schematic_batch",
    "schematic_hierarchy",
    "schematic_layout",
    "symbol_creator",
    "ui",
]

CATEGORY_DESCRIPTIONS = {
    "board": "Board setup: size, layers, outline, mounting holes, zones, text, 2D views",
    "component": "PCB component placement, movement, alignment, properties and pads",
    "datasheet": "Component datasheet lookup and retrieval",
    "design_rules": "Design rules, net classes, clearance checks and DRC",
    "eagle": "Eagle project import",
    "export": "Manufacturing outputs: Gerber, drill, PDF, SVG, 3D, BOM, position files",
    "footprint": "Footprint library browsing and footprint editing",
    "freerouting": "Freerouting autorouter integration",
    "jlcpcb_api": "JLCPCB parts search and assembly data",
    "library": "Footprint library management",
    "library_symbol": "Symbol library search and inspection",
    "project": "Project lifecycle: create, open, save, close, snapshot",
    "router": "Tool discovery: categories, search",
    "routing": "Traces, vias, nets, copper pours, differential pairs",
    "schematic": "Schematic editing: components, wires, labels, connections",
    "schematic_batch": "Batched schematic operations",
    "schematic_hierarchy": "Hierarchical sheets",
    "schematic_layout": "Schematic layout and decluttering",
    "symbol_creator": "Custom symbol creation",
    "ui": "KiCAD application state and UI launching",
}


def _module(name: str) -> Any:
    return importlib.import_module(f"kicad_mcp.toolsets.{name}")


def register_all(mcp: Any) -> int:
    """Register every toolset on the server; returns the tool count."""
    count = 0
    for name in TOOLSET_MODULES:
        mod = _module(name)
        mod.register(mcp)
        count += len(mod._TOOLS)
    return count


def tool_count() -> int:
    return sum(len(_module(name)._TOOLS) for name in TOOLSET_MODULES)


def catalog() -> Dict[str, List[Tuple[str, str]]]:
    """category -> [(tool name, first docstring line)]"""
    result: Dict[str, List[Tuple[str, str]]] = {}
    for name in TOOLSET_MODULES:
        tools: List[Callable[..., Any]] = _module(name)._TOOLS
        result[name] = [
            (fn.__name__, (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else "")
            for fn in tools
        ]
    return result


def search(query: str) -> List[Dict[str, str]]:
    """Case-insensitive substring search over tool names and descriptions."""
    q = query.lower()
    matches = []
    for category, tools in catalog().items():
        for tool_name, desc in tools:
            if q in tool_name.lower() or q in desc.lower():
                matches.append({"name": tool_name, "category": category, "description": desc})
    return matches
