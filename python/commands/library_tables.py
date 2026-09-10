"""Read and edit KiCad's sym-lib-table / fp-lib-table.

``register_symbol_library`` and ``register_footprint_library`` can add a row.
Nothing could read one back, drop one, or repoint one, so cleaning up after a
library migration meant hand-editing the table -- and the obvious way to do
that, ``content.replace(")", ...)`` on the closing paren, corrupts a global
table whose last entry ends on the same line.

These tools work on the parsed ``(lib ...)`` spans instead: rows are located as
the direct children of the table (never by scanning raw text, so a parenthesis
inside a quoted ``(descr ...)`` cannot invent a phantom row), edits are applied
by slicing exactly that span, and the result is re-parsed before it is written.
A rewrite that would not parse is refused rather than saved.

Writes are made through a temporary file and ``os.replace`` and keep the file's
original newline style, and the previous contents are copied into
``.mcp-backups/`` first. ``scope="global"`` resolves to the machine-wide table
in KiCad's user config, which every project on the machine loads: a truncated
write there stops KiCad starting at all. Both mutating tools also accept
``dryRun`` to report the edit without performing it.

``list_library_table`` resolves each URI -- ``${KIPRJMOD}``, KiCad's built-in
library directories (``KICAD*_SYMBOL_DIR`` and friends, which KiCad defines
internally and which therefore appear in neither ``kicad_common.json`` nor the
environment), the path variables configured in ``kicad_common.json``, and the
environment -- and reports whether the file is actually there, which is what
turns "ERC reports hundreds of footprint_link_issues" into "this one row points
at a library that moved".

Tools:
  - list_library_table:         read entries, resolve URIs, flag missing files
  - remove_library_table_entry: drop entries by nickname
  - set_library_table_uri:      repoint a nickname at a different file
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from utils.file_io import read_text_preserve_newline as _read_text
from utils.file_io import write_text_atomic as _write_text
from utils.platform_helper import PlatformHelper
from utils.sexpr_format import escape_sexpr_string
from utils.sexpr_format import match_paren as _match_paren
from utils.sexpr_format import unescape_sexpr_string

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

# Leading token of an s-expression file, e.g. "sym_lib_table" in "(sym_lib_table".
_ROOT_RE = re.compile(r'\s*\(\s*([^\s()"]+)')


class _Table(NamedTuple):
    """A loaded library table and everything an edit to it needs to know."""

    path: Path
    table_type: str
    #: Directory ``${KIPRJMOD}`` stands for, or None for a global table where it
    #: has no meaning.
    project_dir: Optional[Path]
    content: str
    #: Newline style the file already uses, so a write does not convert it.
    newline: str
    entries: List[Dict[str, Any]]


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


def _backup(path: Path) -> Optional[str]:
    """Copy the table into a sibling ``.mcp-backups/`` before it is rewritten.

    Same convention as the auto-save backups in ``kicad_interface`` (timestamped
    copies in ``.mcp-backups/``, which ``.gitignore`` already covers), so a
    removal that turns out to have been the wrong one is recoverable -- and in
    particular so is an edit to the machine-wide global table. Best-effort: a
    backup that cannot be written must not block the edit.
    """
    try:
        backup_dir = path.parent / ".mcp-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        target = backup_dir / f"{path.name}.{stamp}"
        shutil.copy2(path, target)
        return str(target)
    except OSError as exc:
        logger.warning(f"Library-table backup failed (continuing): {exc}")
        return None


def _child_spans(content: str, open_idx: int) -> List[Tuple[int, int]]:
    """Spans of the direct child lists of the list opening at *open_idx*.

    String-aware, which is the whole point: a ``(`` inside a quoted value --
    ``(descr "Caps (X7R) 50V")`` is ordinary in an Eagle-imported table -- is
    not a child list, and scanning raw text for ``(lib`` reports it as one.
    """
    spans: List[Tuple[int, int]] = []
    in_string = False
    i = open_idx + 1
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
            end = _match_paren(content, i)
            if end == -1:
                break
            spans.append((i, end + 1))
            i = end
        elif ch == ")":
            break
        i += 1
    return spans


def _parses(content: str) -> bool:
    """True if the text is one balanced s-expression with nothing trailing."""
    start = content.find("(")
    if start == -1:
        return False
    end = _match_paren(content, start)
    return end != -1 and not content[end + 1 :].strip()


def _field(block: str, field: str) -> str:
    """Value of the direct ``(field "...")`` child of *block*, or ""."""
    for start, end in _child_spans(block, 0):
        child = block[start:end]
        if not re.match(rf"\({field}\b", child):
            continue
        # A trailing space before ')' is legal and turns up in hand-edited
        # tables; requiring ')' straight after the quote misreads those.
        m = re.match(rf'\({field}\s+"((?:[^"\\]|\\.)*)"\s*\)', child)
        return unescape_sexpr_string(m.group(1)) if m else ""
    return ""


def _parse_entries(content: str) -> List[Dict[str, Any]]:
    """Every ``(lib ...)`` row, with the exact span it occupies in the text."""
    root = content.find("(")
    if root == -1:
        return []
    entries = []
    for start, end in _child_spans(content, root):
        if not re.match(r"\(lib\b", content[start:end]):
            continue
        block = content[start:end]
        entry: Dict[str, Any] = {f: _field(block, f) for f in _FIELDS}
        entry["start"] = start
        entry["end"] = end
        entries.append(entry)
    return entries


def _is_table_ref(entry: Dict[str, Any]) -> bool:
    """True for KiCad 10's ``(type "Table")`` indirection to another table.

    One such row stands for every library in the table it points at -- the
    stock global table is a single row named "KiCad" covering 200+ libraries --
    so removing it is nothing like removing an ordinary row.
    """
    return entry["type"].strip().lower() == "table"


def _table_ref_count(resolved_uri: str) -> int:
    """How many libraries a ``(type "Table")`` row actually stands for."""
    try:
        target = Path(resolved_uri)
        if not target.is_file():
            return 0
        text, _ = _read_text(target)
    except OSError:
        return 0
    return len(_parse_entries(text))


def _builtin_path_vars(table_type: str) -> Dict[str, str]:
    """KiCad's own library path variables (``KICAD10_SYMBOL_DIR`` and friends).

    KiCad defines these internally, so they are in neither
    ``kicad_common.json``'s ``environment.vars`` (which only holds what the user
    added under Configure Paths) nor the process environment. Resolving a URI
    from those two sources alone leaves every row of a stock table unresolved
    and therefore reported as missing -- 225 of 226 on a default install, which
    reads as "delete these 225 rows".

    ``commands.library_symbol`` and ``commands.library`` already map these
    variables onto the discovered KiCad install; reuse their finders rather than
    keeping a third copy that can drift. Both are independent of instance state,
    so they are bound to an uninitialised manager: ``__init__`` parses every
    library on disk, which listing a table has no business triggering.
    """
    if table_type == "symbol":
        from commands.library_symbol import SymbolLibraryManager

        manager: Any = SymbolLibraryManager.__new__(SymbolLibraryManager)
        base = manager._find_kicad_symbol_dir()
        third_party = manager._find_3rd_party_dir()
        base_names = (
            "KICAD10_SYMBOL_DIR",
            "KICAD9_SYMBOL_DIR",
            "KICAD8_SYMBOL_DIR",
            "KICAD_SYMBOL_DIR",
            "KISYSSYM",
        )
    else:
        from commands.library import LibraryManager

        manager = LibraryManager.__new__(LibraryManager)
        base = manager._find_kicad_footprint_dir()
        third_party = manager._find_kicad_3rdparty_dir()
        base_names = (
            "KICAD10_FOOTPRINT_DIR",
            "KICAD9_FOOTPRINT_DIR",
            "KICAD8_FOOTPRINT_DIR",
            "KICAD_FOOTPRINT_DIR",
            "KISYSMOD",
        )

    path_vars: Dict[str, str] = {}
    if base:
        path_vars.update({name: base for name in base_names})
    if third_party:
        path_vars.update(
            {
                name: third_party
                for name in (
                    "KICAD10_3RD_PARTY",
                    "KICAD9_3RD_PARTY",
                    "KICAD8_3RD_PARTY",
                    "KICAD_3RD_PARTY",
                )
            }
        )
    return path_vars


def _path_vars(table_type: str) -> Dict[str, str]:
    """Every path variable a table URI can reference, user settings winning."""
    path_vars = _builtin_path_vars(table_type)
    path_vars.update(PlatformHelper.load_kicad_env_vars())
    return path_vars


def _resolve_uri(
    uri: str,
    table_path: Path,
    kicad_vars: Dict[str, str],
    project_dir: Optional[Path] = None,
) -> Tuple[str, bool]:
    """Expand a URI's path variables and report whether the target exists."""

    def substitute(match: re.Match) -> str:
        var = match.group(1)
        if var == "KIPRJMOD":
            # Meaningless in a global table; leaving it unresolved reports the
            # row as unresolvable instead of inventing a config-dir path.
            return str(project_dir) if project_dir is not None else match.group(0)
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


def _table_path(
    params: Dict[str, Any],
) -> Tuple[Optional[Path], Optional[str], Optional[Path], Optional[str]]:
    """Resolve (path, table_type, project_dir, error) from tableType/scope/projectPath."""
    table_type = params.get("tableType", "symbol")
    if table_type not in _TABLES:
        return None, None, None, f"tableType must be 'symbol' or 'footprint', got {table_type!r}"
    filename = _TABLES[table_type][0]

    explicit = params.get("tablePath")
    if explicit:
        # A table addressed by path is treated as a project table: its own
        # directory is what ${KIPRJMOD} means for the rows inside it.
        path = Path(explicit)
        return path, table_type, path.parent, None

    scope = params.get("scope", "project")
    if scope == "project":
        project_path = params.get("projectPath")
        if not project_path:
            return None, None, None, "projectPath is required for scope='project'"
        proj = Path(project_path)
        table_dir = proj if proj.is_dir() else proj.parent
        return table_dir / filename, table_type, table_dir, None

    if scope != "global":
        return None, None, None, f"scope must be 'project' or 'global', got {scope!r}"

    for directory in _kicad_config_dirs():
        candidate = directory / filename
        if candidate.exists():
            return candidate, table_type, None, None
    return (
        None,
        None,
        None,
        (
            f"No global {filename} found. Looked in: "
            + ", ".join(str(d) for d in _kicad_config_dirs()[:4])
            + ". Pass tablePath to point at it directly."
        ),
    )


def _load(params: Dict[str, Any]) -> Tuple[Optional[_Table], Optional[Dict[str, Any]]]:
    """(table, error_response)."""
    path, table_type, project_dir, error = _table_path(params)
    if error:
        return None, {"success": False, "message": error}
    assert path is not None and table_type is not None
    if not path.exists():
        return None, {"success": False, "message": f"Table not found: {path}"}
    try:
        content, newline = _read_text(path)
    except OSError as exc:
        return None, {"success": False, "message": f"Could not read {path}: {exc}"}

    # tablePath bypasses scope resolution, so without this a mutating call
    # could be aimed at any balanced s-expression file that happens to contain
    # a matching (lib ...) row -- a .kicad_pcb, say -- and would rewrite it.
    expected_root = _TABLES[table_type][1]
    match = _ROOT_RE.match(content)
    root = match.group(1) if match else ""
    if root.lower() != expected_root:
        return None, {
            "success": False,
            "message": (
                f"{path} is not a {expected_root}: its root element is "
                f"({root or '?'} ...). Only a sym-lib-table or fp-lib-table can be edited."
            ),
        }

    return (
        _Table(
            path=path,
            table_type=table_type,
            project_dir=project_dir,
            content=content,
            newline=newline,
            entries=_parse_entries(content),
        ),
        None,
    )


def _write_checked(
    table: _Table, content: str, *, dry_run: bool = False
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Back up and atomically write, but only if the result still parses.

    Returns ``(backup_path, error_response)``. With *dry_run* the result is
    still validated -- a preview that does not say the edit would be refused is
    worse than no preview -- but nothing is written.
    """
    if not _parses(content):
        return None, {
            "success": False,
            "message": (
                f"Refusing to write {table.path.name}: the edit would leave unbalanced "
                f"parentheses. The table is unchanged."
            ),
        }
    if dry_run:
        return None, None
    backup = _backup(table.path)
    try:
        _write_text(table.path, content, table.newline)
    except OSError as exc:
        return backup, {
            "success": False,
            "message": f"Could not write {table.path}: {exc}",
            "backup": backup,
        }
    return backup, None


def _public(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {f: entry[f] for f in _FIELDS}


def list_library_table(params: Dict[str, Any]) -> Dict[str, Any]:
    """List the entries of a sym-lib-table or fp-lib-table."""
    table, error = _load(params)
    if error:
        return error
    assert table is not None

    kicad_vars = _path_vars(table.table_type)
    rows = []
    missing = 0
    table_refs = 0
    referenced = 0
    for entry in table.entries:
        resolved, exists = _resolve_uri(entry["uri"], table.path, kicad_vars, table.project_dir)
        if not exists:
            missing += 1
        row = _public(entry)
        row["resolvedPath"] = resolved
        row["exists"] = exists
        if _is_table_ref(entry):
            included = _table_ref_count(resolved) if exists else 0
            row["isTableReference"] = True
            row["includedLibraryCount"] = included
            table_refs += 1
            referenced += included
        rows.append(row)

    message = f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'} in {table.path.name}"
    if missing:
        message += f", {missing} pointing at a file that is not there"
    if table_refs:
        message += (
            f'. {table_refs} of them (type "Table") standing for {referenced} further '
            f"libraries that are not listed individually -- removing such a row "
            f"unregisters all of them"
        )

    return {
        "success": True,
        "message": message,
        "tablePath": str(table.path),
        "tableType": table.table_type,
        "entryCount": len(rows),
        "missingCount": missing,
        "tableReferenceCount": table_refs,
        "referencedLibraryCount": referenced,
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

    table, error = _load(params)
    if error:
        return error
    assert table is not None

    wanted = set(names)
    targets = [e for e in table.entries if e["name"] in wanted]
    if not targets:
        available = ", ".join(e["name"] for e in table.entries) or "(none)"
        return {
            "success": False,
            "message": f"No entry named {' or '.join(sorted(wanted))} in {table.path.name}. "
            f"Present: {available}",
        }

    content = table.content
    # Deleting shifts every later offset, so cut from the back.
    for entry in sorted(targets, key=lambda e: e["start"], reverse=True):
        start, end = entry["start"], entry["end"]
        line_start = content.rfind("\n", 0, start) + 1
        if not content[line_start:start].strip():
            start = line_start
        if content[end : end + 1] == "\n":
            end += 1
        content = content[:start] + content[end:]

    dry_run = bool(params.get("dryRun"))
    backup, failure = _write_checked(table, content, dry_run=dry_run)
    if failure:
        return failure

    removed = [e["name"] for e in targets]
    not_found = sorted(wanted - set(removed))
    verb = "Would remove" if dry_run else "Removed"
    message = f"{verb} {', '.join(removed)} from {table.path.name}"
    if not_found:
        message += f" (not present: {', '.join(not_found)})"

    # A (type "Table") row is an indirection, not a library: dropping the one
    # named "KiCad" from a stock global table unregisters every stock library.
    ref_rows = [e for e in targets if _is_table_ref(e)]
    referenced = 0
    if ref_rows:
        kicad_vars = _path_vars(table.table_type)
        for entry in ref_rows:
            resolved, exists = _resolve_uri(entry["uri"], table.path, kicad_vars, table.project_dir)
            if exists:
                referenced += _table_ref_count(resolved)
        message += (
            f'. WARNING: {", ".join(e["name"] for e in ref_rows)} '
            f'{"is a" if len(ref_rows) == 1 else "are"} (type "Table") '
            f"reference{'' if len(ref_rows) == 1 else 's'}, so this unregisters the "
            f"{referenced} libraries listed in the referenced table, not just "
            f"{'one row' if len(ref_rows) == 1 else 'those rows'}"
        )

    return {
        "success": True,
        "message": message,
        "tablePath": str(table.path),
        "tableType": table.table_type,
        "dryRun": dry_run,
        "backup": backup,
        "removed": [_public(e) for e in targets],
        "notFound": not_found,
        "tableReferencesRemoved": [e["name"] for e in ref_rows],
        "referencedLibraryCount": referenced,
        "remainingCount": len(table.entries) - len(targets),
    }


def set_library_table_uri(params: Dict[str, Any]) -> Dict[str, Any]:
    """Repoint an existing table entry at a different file."""
    name = params.get("libraryName")
    new_uri = params.get("uri")
    if not name:
        return {"success": False, "message": "libraryName is required"}
    if not new_uri:
        return {"success": False, "message": "uri is required"}

    table, error = _load(params)
    if error:
        return error
    assert table is not None

    target = next((e for e in table.entries if e["name"] == name), None)
    if target is None:
        available = ", ".join(e["name"] for e in table.entries) or "(none)"
        return {
            "success": False,
            "message": f"No entry named '{name}' in {table.path.name}. Present: {available}",
        }

    block = table.content[target["start"] : target["end"]]
    old_uri = target["uri"]
    # The replacement has to be a function: as a template string, re treats "\\"
    # as one literal backslash and undoes exactly the doubling
    # escape_sexpr_string just applied, so an ordinary Windows path lands in the
    # file as raw \U \m \l escapes -- and one ending in a backslash escapes the
    # closing quote and makes the whole table unparseable.
    replacement = f'(uri "{escape_sexpr_string(new_uri)}")'
    updated_block, count = re.subn(
        r'\(uri\s+"(?:[^"\\]|\\.)*"\s*\)',
        lambda _match: replacement,
        block,
        count=1,
    )
    if count == 0:
        return {
            "success": False,
            "message": f"Entry '{name}' has no (uri ...) field to replace",
        }

    content = table.content[: target["start"]] + updated_block + table.content[target["end"] :]
    dry_run = bool(params.get("dryRun"))
    backup, failure = _write_checked(table, content, dry_run=dry_run)
    if failure:
        return failure

    kicad_vars = _path_vars(table.table_type)
    resolved, exists = _resolve_uri(new_uri, table.path, kicad_vars, table.project_dir)
    message = f"'{name}' {'would now point' if dry_run else 'now points'} at {new_uri}"
    if not exists:
        message += " -- note that no file exists there yet"

    return {
        "success": True,
        "message": message,
        "tablePath": str(table.path),
        "tableType": table.table_type,
        "dryRun": dry_run,
        "backup": backup,
        "libraryName": name,
        "previousUri": old_uri,
        "uri": new_uri,
        "resolvedPath": resolved,
        "exists": exists,
    }
