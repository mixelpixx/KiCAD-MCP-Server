"""Every declared tool parameter must reach a handler that reads it.

Three schema/handler slips of the same shape reached users in one month:
``modify_trace`` declared ``traceUuid`` and read ``uuid`` (#403), ``add_net``
declared ``netClass`` and read ``class``, and #392 found five more in the
JSON-RPC schema. Each one is a tool that advertises a parameter and then
ignores it -- silently when the parameter is optional, with a misleading
"missing X" error when it is required. Nothing failed in CI because every
per-tool test calls the handler with the key the handler happens to read.

There are two schema layers and both are checked:

* the zod schemas in ``src/tools/*.ts`` -- what a Node-fronted MCP client
  sees. Most handlers pass ``args`` straight through to Python; some build an
  object literal first, so the check uses the keys actually sent, parsed from
  the ``callKicadScript(...)`` call.
* ``python/schemas/tool_schemas.py`` -- what the standalone JSON-RPC path's
  ``tools/list`` returns.

A parameter counts as read when its name appears as a string literal in the
handler's source or in any callee the handler forwards ``params`` to (a few
levels deep), or as a parameter of such a callee. That is deliberately loose:
a false "read" costs a missed bug, a false "unread" would be noise that makes
people stop trusting the test.

Measuring found pre-existing cases, so this is a RATCHET, not a clean gate:
the known sets below are frozen and any NEW omission fails. An entry that is
fixed must be removed from the list, which the test also enforces. The frozen
entries are tracked in #407. Do not add to a list to make CI pass; fix the
handler (read the schema's name, keep the old key for existing callers) or
fix the schema.
"""

from __future__ import annotations

import glob
import inspect
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(
        os.environ.get("KICAD_USE_REAL_PCBNEW") == "1",
        reason="source-level check targets the stubbed-pcbnew unit environment",
    ),
]

# --- frozen baselines (#407) -------------------------------------------------

# zod-declared (or object-literal-sent) keys the Python handler never reads.
KNOWN_ZOD_UNREAD: Dict[str, Set[str]] = {
    "add_board_text": {"style"},
    "add_via": {"viaType"},
    "align_components": {"alignmentType", "referenceComponent"},
    "duplicate_component": {"count", "offset"},
    "get_footprint_info": {"library_name"},
    "get_net_pads": {"unit"},
    "get_nets_list": {"includeStats", "unit"},
    "list_libraries": {"search_paths"},
    "list_library_footprints": {"filter", "limit"},
    "place_component_array": {"columnSpacing", "footprint", "rowSpacing", "startReference"},
    "route_differential_pair": {"negativeNet", "negativePad", "positiveNet", "positivePad"},
    "set_design_rules": {"courtyardClearance", "requireCourtyard"},
}

# tool_schemas.py property names the Python handler never reads.
KNOWN_JSONRPC_UNREAD: Dict[str, Set[str]] = {
    "add_schematic_component": {"symbol"},
    "add_via": {"diameter", "netName"},
    "align_components": {"direction"},
    "duplicate_component": {"offsetX", "offsetY", "sourceReference"},
    "export_gerber": {"includeDrillFiles"},
    "export_pdf": {"colorMode"},
    "get_footprint_info": {"footprint"},
    "place_component_array": {"footprint", "startNumber", "startX", "startY"},
    "route_differential_pair": {"negativeName", "points", "positiveName"},
    "route_trace": {"netName", "points"},
    "run_drc": {"includeWarnings"},
    "search_footprints": {"query"},
}

# TypeScript tools that call a Python command with no entry in command_routes:
# every call answers "unknown command".
KNOWN_UNROUTED: Set[str] = {
    "add_component_annotation",
    "add_zone",
    "export_position_file",
    "export_vrml",
    "group_components",
    "replace_component",
}

# --- TypeScript side ---------------------------------------------------------


def _scan_balanced(src: str, start: int) -> Tuple[str, int]:
    """``src[start] == "{"``; return (body, index of the closing brace)."""
    depth = 0
    i = start
    quote: Optional[str] = None
    while i < len(src):
        c = src[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[start + 1 : i], i
        i += 1
    raise ValueError("unbalanced braces")


def _split_top(body: str) -> List[str]:
    """Split an object body at depth-0 commas, string- and bracket-aware."""
    parts: List[str] = []
    depth = 0
    quote: Optional[str] = None
    cur: List[str] = []
    for i, c in enumerate(body):
        if quote:
            cur.append(c)
            if c == quote and body[i - 1] != "\\":
                quote = None
            continue
        if c in "\"'`":
            quote = c
            cur.append(c)
            continue
        if c in "{([":
            depth += 1
        elif c in "})]":
            depth -= 1
        if c == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def _object_keys(body: str) -> Tuple[List[str], bool]:
    """Top-level keys of a TS object literal, and whether it spreads another."""
    keys: List[str] = []
    spread = False
    for entry in _split_top(body):
        entry = re.sub(r"//[^\n]*", "", entry).strip()
        if not entry:
            continue
        if entry.startswith("..."):
            spread = True
            continue
        m = re.match(r"(\w+)\s*:", entry) or re.match(r"(\w+)\s*$", entry)
        if m:
            keys.append(m.group(1))
    return keys, spread


def _zod_keys(src: str, after: int) -> Optional[List[str]]:
    """Top-level keys of the schema object (third ``server.tool`` argument)."""
    i = after
    depth = 0
    quote: Optional[str] = None
    while i < len(src):
        c = src[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            j = i + 1
            while src[j] in " \t\r\n":
                j += 1
            if src[j] != "{":
                return None
            body, _ = _scan_balanced(src, j)
            return _object_keys(body)[0]
        i += 1
    return None


def ts_tools() -> Dict[str, Dict[str, Any]]:
    """{tool: {"payload": keys sent to Python or None, "calls_python": bool}}."""
    out: Dict[str, Dict[str, Any]] = {}
    for path in sorted(glob.glob(str(ROOT / "src" / "tools" / "*.ts"))):
        src = Path(path).read_text(encoding="utf-8")
        starts = [
            (m.group(1), m.start(), m.end())
            for m in re.finditer(r'server\.tool\(\s*"([^"]+)"\s*,', src)
        ]
        for idx, (name, start, end) in enumerate(starts):
            stop = starts[idx + 1][1] if idx + 1 < len(starts) else len(src)
            body = src[start:stop]
            zod = _zod_keys(src, end) or []
            payload: Set[str] = set()
            parsed = False
            unknown = False
            for m in re.finditer(r'callKicadScript\(\s*"([^"]+)"\s*,\s*', body):
                assert m.group(1) == name, f"{name} calls {m.group(1)}"
                k = m.end()
                if re.match(r"(args|params|request)\s*[,)]", body[k:]):
                    payload |= set(zod)
                    parsed = True
                elif body[k] == "{":
                    obj, _ = _scan_balanced(body, k)
                    keys, spread = _object_keys(obj)
                    payload |= set(keys)
                    if spread:
                        payload |= set(zod)
                    parsed = True
                else:
                    unknown = True
            out[name] = {
                "payload": sorted(payload) if parsed and not unknown else None,
                "calls_python": "callKicadScript(" in body,
            }
    return out


# --- Python side -------------------------------------------------------------

_LITERAL = re.compile(r"[\"'](\w+)[\"']")
_FORWARD = re.compile(r"((?:self\.)?[A-Za-z_][\w.]*)\(\s*(?:[^()]*?,\s*)?\*{0,2}\w*params\w*\b")
_BUILTINS = {
    "isinstance",
    "dict",
    "list",
    "str",
    "int",
    "float",
    "print",
    "len",
    "bool",
    "type",
    "repr",
    "set",
    "tuple",
    "sorted",
    "getattr",
    "hasattr",
}


def handler_vocabulary(fn: Callable, depth: int = 0, seen: Optional[Set] = None) -> Set[str]:
    """String literals and parameter names in ``fn`` and in callees it forwards params to."""
    seen = set() if seen is None else seen
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return set()
    vocab = set(_LITERAL.findall(src))
    try:
        vocab |= set(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        pass
    if depth >= 5:
        return vocab
    owner = getattr(fn, "__self__", None)
    func = getattr(fn, "__func__", fn)
    namespace = getattr(func, "__globals__", {}) or {}
    for m in _FORWARD.finditer(src):
        target = m.group(1)
        if target.split(".")[-1] in _BUILTINS:
            continue
        obj: Any = None
        try:
            parts = target.split(".")
            if parts[0] == "self":
                obj = owner
                parts = parts[1:]
            else:
                obj = namespace.get(parts[0])
                parts = parts[1:]
            for part in parts:
                obj = getattr(obj, part)
        except AttributeError:
            obj = None
        if obj is None or not callable(obj) or inspect.isclass(obj):
            continue
        key = getattr(obj, "__qualname__", None) or id(obj)
        if key in seen:
            continue
        seen.add(key)
        vocab |= handler_vocabulary(obj, depth + 1, seen)
    return vocab


# --- fixtures ----------------------------------------------------------------


@pytest.fixture(scope="module")
def tools() -> Dict[str, Dict[str, Any]]:
    return ts_tools()


@pytest.fixture(scope="module")
def routes() -> Dict[str, Callable]:
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        return KiCADInterface().command_routes


@pytest.fixture(scope="module")
def vocabulary(routes) -> Callable[[str], Set[str]]:
    cache: Dict[str, Set[str]] = {}

    def lookup(name: str) -> Set[str]:
        if name not in cache:
            cache[name] = handler_vocabulary(routes[name])
        return cache[name]

    return lookup


def _ratchet(found: Dict[str, Set[str]], known: Dict[str, Set[str]], what: str) -> None:
    new = {t: sorted(v - known.get(t, set())) for t, v in found.items() if v - known.get(t, set())}
    stale = {
        t: sorted(v - found.get(t, set())) for t, v in known.items() if v - found.get(t, set())
    }
    assert not new, (
        f"NEW {what}: {new}. The handler never reads these declared parameter "
        "names. Make the handler read the schema's name (keep the old key for "
        "existing callers) or fix the schema; do not extend the known list."
    )
    assert not stale, f"{what} now read; remove from the known list: {stale}"


# --- tests -------------------------------------------------------------------


def test_parser_sees_the_tool_surface(tools) -> None:
    """Guard the guard: a parser regression must not pass as 'no mismatches'."""
    parsed = [t for t, info in tools.items() if info["payload"] is not None]
    assert len(tools) >= 220, f"only {len(tools)} server.tool() calls parsed"
    assert len(parsed) >= 200, f"only {len(parsed)} payloads parsed"


def test_every_ts_tool_that_calls_python_has_a_route(tools, routes) -> None:
    unrouted = {t for t, info in tools.items() if info["calls_python"] and t not in routes}
    assert not (unrouted - KNOWN_UNROUTED), (
        f"NEW unrouted tools {sorted(unrouted - KNOWN_UNROUTED)}: the TypeScript "
        "tool calls a command that kicad_interface.command_routes does not know, "
        "so every call fails. Add the route (and its handler import)."
    )
    assert not (
        KNOWN_UNROUTED - unrouted
    ), f"now routed; remove from KNOWN_UNROUTED: {sorted(KNOWN_UNROUTED - unrouted)}"


def test_zod_parameters_are_read_by_their_handlers(tools, routes, vocabulary) -> None:
    found: Dict[str, Set[str]] = {}
    for name, info in sorted(tools.items()):
        if info["payload"] is None or name not in routes:
            continue
        missing = {p for p in info["payload"] if p not in vocabulary(name)}
        if missing:
            found[name] = missing
    _ratchet(found, KNOWN_ZOD_UNREAD, "zod parameters never read")


def test_jsonrpc_schema_parameters_are_read_by_their_handlers(routes, vocabulary) -> None:
    from schemas.tool_schemas import TOOL_SCHEMAS

    assert len(TOOL_SCHEMAS) >= 100
    found: Dict[str, Set[str]] = {}
    for name, schema in sorted(TOOL_SCHEMAS.items()):
        if name not in routes:
            continue
        props = schema.get("inputSchema", {}).get("properties", {})
        missing = {p for p in props if p not in vocabulary(name)}
        if missing:
            found[name] = missing
    _ratchet(found, KNOWN_JSONRPC_UNREAD, "JSON-RPC schema parameters never read")
