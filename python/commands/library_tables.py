"""Read and edit KiCad's sym-lib-table / fp-lib-table.

``register_symbol_library`` and ``register_footprint_library`` can add a row.
Nothing could read one back, drop one, or repoint one, so cleaning up after a
library migration meant hand-editing the table -- and the obvious way to do
that, ``content.replace(")", ...)`` on the closing paren, corrupts a global
table whose last entry ends on the same line.

These tools work on the parsed ``(lib ...)`` spans instead: entries are located
by nickname, edits are applied by slicing exactly that span, and the result is
re-parsed before it is written. A rewrite that would not parse is refused
rather than saved.

``list_library_table`` also resolves each URI -- ``${KIPRJMOD}``, KiCad's own
configured path variables, and the environment -- and reports whether the file
is actually there, which is what turns "ERC reports hundreds of
footprint_link_issues" into "this one row points at a library that moved".

Tools:
  - list_library_table:         read entries, resolve URIs, flag missing files
  - remove_library_table_entry: drop entries by nickname
  - set_library_table_uri:      repoint a nickname at a different file
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.platform_helper import PlatformHelper
from utils.sexpr_format import escape_sexpr_string, unescape_sexpr_string

logger = logging.getLogger("kicad_interface")

# table type -> (file name, root s-expression name)
_TABLES = {
    "symbol": ("sym-lib-table", "sym_lib_table"),
    "footprint": ("fp-lib-table", "fp_lib_table"),
}

# Newest first: KiCad reads the config of the version that wrote it, and a
# machine that has been upgraded keeps the older directories around.
_KICAD_VERSIONS = ("10.0", "9.0", "8.0")

_FIELDS = ("name", "type", "uri", "options", "descr")

_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _kicad_config_dirs() -> List[Path]:
    """Candidate KiCad configuration directories, newest version first."""
    home = Path.home()
    roots = [
        home / "AppData" / "Roaming" / "kicad",
        home / ".config" / "kicad",
        home / "Library" / "Preferences" / "kicad",
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.insert(0, Path(appdata) / "kicad")
    return [root / version for version in _KICAD_VERSIONS for root in roots]


def _match_paren(content: str, open_idx: int) -> int:
    """Index of the ``)`` closing the ``(`` at *open_idx*, or -1 if unbalanced."""
    depth = 0
    in_string = False
    i = open_idx
    while i < len(content):
        ch = content[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _parses(content: str) -> bool:
    """True if the text is one balanced s-expression with nothing trailing."""
    start = content.find("(")
    if start == -1:
        return False
    end = _match_paren(content, start)
    return end != -1 and not content[end + 1 :].strip()


def _field(block: str, field: str) -> str:
    m = re.search(rf'\({field}\s+"((?:[^"\\]|\\.)*)"\)', block)
    return unescape_sexpr_string(m.group(1)) if m else ""


def _parse_entries(content: str) -> List[Dict[str, Any]]:
    """Every ``(lib ...)`` row, with the exact span it occupies in the text."""
    entries = []
    for m in re.finditer(r"\(lib\b", content):
        end = _match_paren(content, m.start())
        if end == -1:
            continue
        block = content[m.start() : end + 1]
        entry: Dict[str, Any] = {f: _field(block, f) for f in _FIELDS}
        entry["start"] = m.start()
        entry["end"] = end + 1
        entries.append(entry)
    return entries


def _resolve_uri(uri: str, table_path: Path, kicad_vars: Dict[str, str]) -> Tuple[str, bool]:
    """Expand a URI's path variables and report whether the target exists."""

    def substitute(match: re.Match) -> str:
        var = match.group(1)
        if var == "KIPRJMOD":
            return str(table_path.parent)
        if var in kicad_vars:
            return kicad_vars[var]
        return os.environ.get(var, match.group(0))

    expanded = _VAR_RE.sub(substitute, uri)
    if _VAR_RE.search(expanded):
        return expanded, False  # an unresolved variable cannot point anywhere
    path = Path(expanded)
    if not path.is_absolute():
        path = table_path.parent / path
    try:
        return str(path.resolve()), path.exists()
    except OSError:
        return str(path), False


def _table_path(params: Dict[str, Any]) -> Tuple[Optional[Path], Optional[str], Optional[str]]:
    """Resolve (path, table_type, error) from tableType / scope / projectPath."""
    table_type = params.get("tableType", "symbol")
    if table_type not in _TABLES:
        return None, None, f"tableType must be 'symbol' or 'footprint', got {table_type!r}"
    filename = _TABLES[table_type][0]

    explicit = params.get("tablePath")
    if explicit:
        return Path(explicit), table_type, None

    scope = params.get("scope", "project")
    if scope == "project":
        project_path = params.get("projectPath")
        if not project_path:
            return None, None, "projectPath is required for scope='project'"
        proj = Path(project_path)
        table_dir = proj if proj.is_dir() else proj.parent
        return table_dir / filename, table_type, None

    if scope != "global":
        return None, None, f"scope must be 'project' or 'global', got {scope!r}"

    for directory in _kicad_config_dirs():
        candidate = directory / filename
        if candidate.exists():
            return candidate, table_type, None
    return (
        None,
        None,
        (
            f"No global {filename} found. Looked in: "
            + ", ".join(str(d) for d in _kicad_config_dirs()[:4])
            + ". Pass tablePath to point at it directly."
        ),
    )


def _load(params: Dict[str, Any]) -> Tuple[Any, ...]:
    """(path, table_type, content, entries, error_response)."""
    path, table_type, error = _table_path(params)
    if error:
        return None, None, None, None, {"success": False, "message": error}
    assert path is not None
    if not path.exists():
        return None, None, None, None, {"success": False, "message": f"Table not found: {path}"}
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return (
            None,
            None,
            None,
            None,
            {"success": False, "message": f"Could not read {path}: {exc}"},
        )
    return path, table_type, content, _parse_entries(content), None


def _write_checked(path: Path, content: str) -> Optional[Dict[str, Any]]:
    """Write only if the result still parses; otherwise report and change nothing."""
    if not _parses(content):
        return {
            "success": False,
            "message": (
                f"Refusing to write {path.name}: the edit would leave unbalanced "
                f"parentheses. The table is unchanged."
            ),
        }
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        return {"success": False, "message": f"Could not write {path}: {exc}"}
    return None


def _public(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {f: entry[f] for f in _FIELDS}


def list_library_table(params: Dict[str, Any]) -> Dict[str, Any]:
    """List the entries of a sym-lib-table or fp-lib-table."""
    path, table_type, content, entries, error = _load(params)
    if error:
        return error

    kicad_vars = PlatformHelper.load_kicad_env_vars()
    rows = []
    missing = 0
    for entry in entries:
        resolved, exists = _resolve_uri(entry["uri"], path, kicad_vars)
        if not exists:
            missing += 1
        row = _public(entry)
        row["resolvedPath"] = resolved
        row["exists"] = exists
        rows.append(row)

    message = f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'} in {path.name}"
    if missing:
        message += f", {missing} pointing at a file that is not there"

    return {
        "success": True,
        "message": message,
        "tablePath": str(path),
        "tableType": table_type,
        "entryCount": len(rows),
        "missingCount": missing,
        "entries": rows,
    }


def remove_library_table_entry(params: Dict[str, Any]) -> Dict[str, Any]:
    """Remove one or more entries from a library table, by nickname."""
    names = params.get("libraryNames")
    if names is None:
        single = params.get("libraryName")
        names = [single] if single else []
    if not names:
        return {"success": False, "message": "libraryName or libraryNames is required"}

    path, table_type, content, entries, error = _load(params)
    if error:
        return error

    wanted = set(names)
    targets = [e for e in entries if e["name"] in wanted]
    if not targets:
        available = ", ".join(e["name"] for e in entries) or "(none)"
        return {
            "success": False,
            "message": f"No entry named {' or '.join(sorted(wanted))} in {path.name}. "
            f"Present: {available}",
        }

    # Deleting shifts every later offset, so cut from the back.
    for entry in sorted(targets, key=lambda e: e["start"], reverse=True):
        start, end = entry["start"], entry["end"]
        line_start = content.rfind("\n", 0, start) + 1
        if not content[line_start:start].strip():
            start = line_start
        if content[end : end + 1] == "\n":
            end += 1
        content = content[:start] + content[end:]

    failure = _write_checked(path, content)
    if failure:
        return failure

    removed = [e["name"] for e in targets]
    not_found = sorted(wanted - set(removed))
    message = f"Removed {', '.join(removed)} from {path.name}"
    if not_found:
        message += f" (not present: {', '.join(not_found)})"

    return {
        "success": True,
        "message": message,
        "tablePath": str(path),
        "tableType": table_type,
        "removed": [_public(e) for e in targets],
        "notFound": not_found,
        "remainingCount": len(entries) - len(targets),
    }


def set_library_table_uri(params: Dict[str, Any]) -> Dict[str, Any]:
    """Repoint an existing table entry at a different file."""
    name = params.get("libraryName")
    new_uri = params.get("uri")
    if not name:
        return {"success": False, "message": "libraryName is required"}
    if not new_uri:
        return {"success": False, "message": "uri is required"}

    path, table_type, content, entries, error = _load(params)
    if error:
        return error

    target = next((e for e in entries if e["name"] == name), None)
    if target is None:
        available = ", ".join(e["name"] for e in entries) or "(none)"
        return {
            "success": False,
            "message": f"No entry named '{name}' in {path.name}. Present: {available}",
        }

    block = content[target["start"] : target["end"]]
    old_uri = target["uri"]
    updated_block, count = re.subn(
        r'\(uri\s+"(?:[^"\\]|\\.)*"\)',
        f'(uri "{escape_sexpr_string(new_uri)}")',
        block,
        count=1,
    )
    if count == 0:
        return {
            "success": False,
            "message": f"Entry '{name}' has no (uri ...) field to replace",
        }

    content = content[: target["start"]] + updated_block + content[target["end"] :]
    failure = _write_checked(path, content)
    if failure:
        return failure

    kicad_vars = PlatformHelper.load_kicad_env_vars()
    resolved, exists = _resolve_uri(new_uri, path, kicad_vars)
    message = f"'{name}' now points at {new_uri}"
    if not exists:
        message += " -- note that no file exists there yet"

    return {
        "success": True,
        "message": message,
        "tablePath": str(path),
        "tableType": table_type,
        "libraryName": name,
        "previousUri": old_uri,
        "uri": new_uri,
        "resolvedPath": resolved,
        "exists": exists,
    }
