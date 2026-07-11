"""LLM prompts ported from the TypeScript layer (src/prompts/*.ts)."""

from typing import Any

from kicad_mcp.prompts import component, design, footprint, routing

_MODULES = [component, design, footprint, routing]


def register_prompts(mcp: Any) -> None:
    for module in _MODULES:
        module.register(mcp)


def prompt_count() -> int:
    return sum(len(module._PROMPTS) for module in _MODULES)
