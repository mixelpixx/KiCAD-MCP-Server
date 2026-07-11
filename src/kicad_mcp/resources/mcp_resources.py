"""Register the KiCAD project-state resources on the MCP SDK server.

The definitions and read handlers in resource_definitions.py predate the SDK
(they served the legacy stdio loop) and stay the single implementation; this
module adapts them to ``@mcp.resource()``. Readers return str (text/JSON) or
bytes (the board preview PNG) and the SDK builds the protocol envelope.
"""

import base64
from typing import Any, Callable, Union

from kicad_mcp.resources.resource_definitions import (
    RESOURCE_DEFINITIONS,
    handle_resource_read,
)


def _read(uri: str) -> Union[str, bytes]:
    from kicad_mcp.dispatch import get_interface
    from kicad_mcp.toolsets._common import _DISPATCH_LOCK

    with _DISPATCH_LOCK:
        result = handle_resource_read(uri, get_interface())
    contents = result.get("contents") or []
    if not contents:
        return f"Empty resource: {uri}"
    entry = contents[0]
    if "blob" in entry:
        return base64.b64decode(entry["blob"])
    return entry.get("text", "")


def _make_reader(uri: str, definition: dict) -> Callable[[], Union[str, bytes]]:
    def reader() -> Union[str, bytes]:
        return _read(uri)

    reader.__name__ = definition["name"].lower().replace(" ", "_")
    reader.__doc__ = definition["description"]
    return reader


def register_resources(mcp: Any) -> None:
    for definition in RESOURCE_DEFINITIONS:
        mcp.resource(
            definition["uri"],
            name=definition["name"],
            description=definition["description"],
            mime_type=definition["mimeType"],
        )(_make_reader(definition["uri"], definition))
