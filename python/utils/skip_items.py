"""Read a kind of item from a kicad-skip schematic as a plain list.

kicad-skip has dedicated collections for some kinds (symbol, label, global_label, wire,
junction). For the others (hierarchical_label, no_connect, ...) it returns an
ElementCollection when there are two or more, but the bare element itself when there is
exactly one. ``bool()`` on that element raises "__bool__ should return bool, returned str",
so ``getattr(sch, kind, None) or []`` crashes, and iterating it walks the element's own
children (its name, ``at``, ``effects``...) instead of the items.
"""

from typing import Any, List


def skip_items(container: Any, kind: str) -> List[Any]:
    """Every *kind* item directly in *container* (a kicad-skip Schematic), as a list."""
    obj = getattr(container, kind, None)
    if obj is None:
        return []
    # A lone element names its own kind; a collection does not.
    if getattr(obj, "entity_type", None) == kind:
        return [obj]
    return list(obj)
