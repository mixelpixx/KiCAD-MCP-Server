"""Shared dispatch plumbing for the generated toolset modules."""

import threading
from typing import Any, Dict

from pydantic import BaseModel

# The TypeScript layer processed tool calls strictly one at a time (a queued
# request pipeline). KiCADInterface inherited that assumption and is not
# thread-safe, so the same serialization is enforced here: the SDK runs sync
# tools on worker threads, and this lock keeps dispatch single-file.
_DISPATCH_LOCK = threading.Lock()


def _plain(value: Any) -> Any:
    """Convert pydantic models (nested params) back to the plain dicts
    the command implementations expect."""
    if isinstance(value, BaseModel):
        return {k: _plain(v) for k, v in value.model_dump(exclude_none=True).items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def dispatch_command(command: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Route a tool call into the command router.

    None-valued arguments are dropped to match the TypeScript layer, which
    never forwarded undefined optionals.
    """
    from kicad_mcp.dispatch import get_interface

    clean = {k: _plain(v) for k, v in params.items() if v is not None}
    with _DISPATCH_LOCK:
        result = get_interface().handle_command(command, clean)
    if not isinstance(result, dict):
        return {"result": result}
    return result
