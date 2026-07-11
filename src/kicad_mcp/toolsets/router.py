"""Tool-discovery meta-tools (hand-written; not generated).

These lived in the TypeScript layer (src/tools/router.ts) against its own
registry; here they answer from kicad_mcp.registry, so they always reflect
exactly what is registered.
"""

from typing import Annotated, Any

from pydantic import Field


def list_tool_categories() -> dict[str, Any]:
    """List all available KiCAD tool categories with their descriptions and tool counts. Use this to discover which tools are available via the router."""
    from kicad_mcp import registry

    cat = registry.catalog()
    return {
        "total_categories": len(cat),
        "total_tools": sum(len(tools) for tools in cat.values()),
        "note": "Use get_category_tools to see tools in each category.",
        "categories": [
            {
                "name": name,
                "description": registry.CATEGORY_DESCRIPTIONS.get(name, ""),
                "tool_count": len(tools),
            }
            for name, tools in cat.items()
        ],
    }


def get_category_tools(
    category: Annotated[str, Field(description="Category name from list_tool_categories")],
) -> dict[str, Any]:
    """Return all tools available in a specific category. Use list_tool_categories first to find valid category names."""
    from kicad_mcp import registry

    cat = registry.catalog()
    if category not in cat:
        return {
            "error": f"Unknown category: {category}",
            "available_categories": sorted(cat),
        }
    return {
        "category": category,
        "description": registry.CATEGORY_DESCRIPTIONS.get(category, ""),
        "tool_count": len(cat[category]),
        "tools": [{"name": name, "description": desc} for name, desc in cat[category]],
        "note": "Call any of these tools directly with appropriate parameters.",
    }


def search_tools(
    query: Annotated[
        str, Field(description="Search term (e.g., 'gerber', 'zone', 'export', 'drc')")
    ],
) -> dict[str, Any]:
    """Search all available KiCAD tools by keyword. Returns matching tool names and their categories."""
    from kicad_mcp import registry

    matches = registry.search(query)
    return {
        "query": query,
        "count": len(matches),
        "matches": matches,
        "note": (
            "Call the tool directly by name."
            if matches
            else "No tools found matching your query. Try list_tool_categories to browse all categories."
        ),
    }


_TOOLS = [
    list_tool_categories,
    get_category_tools,
    search_tools,
]


def register(mcp: Any) -> None:
    for fn in _TOOLS:
        mcp.tool()(fn)
