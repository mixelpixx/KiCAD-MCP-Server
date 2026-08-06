"""Structural validation for .kicad_sch and .kicad_sym files.

``kicad-cli`` answers whether a file loads, but not why: a single misplaced
paren anywhere in a 40 000-line library produces ``Unable to load library`` and
nothing else. Recovering from that means bisecting the file by hand.

These tools do the locating. A single string-aware pass over the text reports
the line and column of every structural fault, then a set of KiCad-specific
checks catches the damage that is syntactically legal but still wrong -- a
property sitting directly under ``(kicad_sch ...)`` instead of inside a symbol,
or a unit still named after the symbol it was renamed away from.

``kicad-cli`` is then run on a throwaway copy as the authoritative answer, so a
file that passes here but not there is reported rather than hidden. The copy
matters: ``upgrade`` rewrites in place, and a validator must not touch the file
it is validating.

Tools:
  - validate_schematic:      .kicad_sch structure and orphaned fragments
  - validate_symbol_library: .kicad_sym structure, duplicates, unit naming
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.kicad_cli import resolve_kicad_cli

logger = logging.getLogger("kicad_interface")

# Atom directly after "(" -- the node name. KiCad never puts space there.
_ATOM = re.compile(r"[^\s()\"]+")

# Tokens that only ever appear inside a property or graphic. Finding one as a
# direct child of the root means a property rewrite truncated its block and
# left the tail behind (see the add_symbol_property truncation bug).
_ORPHAN_FRAGMENTS = frozenset({"property", "effects", "hide", "at", "font", "justify"})

# Cap on how much a hierarchical validation may copy to the temp dir.
_MAX_CLI_COPY_BYTES = 64 * 1024 * 1024

_CLI_TIMEOUT_SEC = 180


class _Node:
    """One list in the file, recorded when its "(" is seen."""

    __slots__ = ("name", "line", "column", "parent", "depth", "start")

    def __init__(
        self, name: str, line: int, column: int, parent: Optional[str], depth: int, start: int
    ):
        self.name = name
        self.line = line
        self.column = column
        self.parent = parent
        self.depth = depth
        self.start = start


def _issue(
    severity: str, code: str, message: str, line: int = 0, column: int = 0
) -> Dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "line": line,
        "column": column,
    }


def _scan(content: str) -> Tuple[List[_Node], List[Dict[str, Any]]]:
    """Walk the s-expression text once, returning its nodes and structural faults.

    Quoted tokens are skipped wholesale, so a ``"Cap (X7R)"`` description is
    text rather than an unbalanced paren -- the false positive that makes a
    naive ``count("(") - count(")")`` check useless on real libraries.
    """
    nodes: List[_Node] = []
    issues: List[Dict[str, Any]] = []
    stack: List[_Node] = []

    line = 1
    line_start = 0
    closed_root = False
    i = 0
    n = len(content)

    while i < n:
        ch = content[i]

        if ch == "\n":
            line += 1
            line_start = i + 1
            i += 1
            continue

        if ch == '"':
            j = i + 1
            str_line, str_line_start = line, line_start
            while j < n:
                if content[j] == "\\":
                    j += 2
                    continue
                if content[j] == '"':
                    break
                if content[j] == "\n":
                    line += 1
                    line_start = j + 1
                j += 1
            if j >= n:
                issues.append(
                    _issue(
                        "error",
                        "unterminated_string",
                        "String opened here is never closed",
                        str_line,
                        i - str_line_start + 1,
                    )
                )
                return nodes, issues
            i = j + 1
            continue

        if ch == "(":
            column = i - line_start + 1
            if closed_root:
                issues.append(
                    _issue(
                        "error",
                        "trailing_content",
                        "Content after the top-level form closed",
                        line,
                        column,
                    )
                )
                closed_root = False
            atom = _ATOM.match(content, i + 1)
            node = _Node(
                atom.group(0) if atom else "",
                line,
                column,
                stack[-1].name if stack else None,
                len(stack),
                i,
            )
            nodes.append(node)
            stack.append(node)
            i += 1
            continue

        if ch == ")":
            if stack:
                stack.pop()
                if not stack:
                    closed_root = True
            else:
                issues.append(
                    _issue(
                        "error",
                        "unbalanced_close",
                        "Closing paren with nothing open -- the file has one ')' too many",
                        line,
                        i - line_start + 1,
                    )
                )
            i += 1
            continue

        if closed_root and not ch.isspace():
            issues.append(
                _issue(
                    "error",
                    "trailing_content",
                    "Content after the top-level form closed",
                    line,
                    i - line_start + 1,
                )
            )
            closed_root = False

        i += 1

    for node in stack:
        issues.append(
            _issue(
                "error",
                "unclosed_form",
                f"({node.name} ...) opened here is never closed",
                node.line,
                node.column,
            )
        )

    return nodes, issues


def _indent_divergence(content: str, nodes: List[_Node]) -> Optional[Dict[str, Any]]:
    """Locate a missing/extra paren by where nesting stops matching indentation.

    ``unclosed_form`` can only name the outermost form that stayed open, which
    for a paren dropped in the middle of a file is always line 1 -- true and
    useless. KiCad writes one tab per level, so the first line whose tab count
    disagrees with its actual nesting depth is where the structure broke.
    Returns None for files that are not tab-indented, where this says nothing.
    """
    lines = content.split("\n")
    if not any(line.startswith("\t") for line in lines):
        return None

    for node in nodes:
        line_text = lines[node.line - 1] if node.line - 1 < len(lines) else ""
        prefix = line_text[: node.column - 1]
        if prefix.strip():
            continue  # not the first token on its line
        if prefix and set(prefix) != {"\t"}:
            continue  # space-indented line: the one-tab-per-level rule says nothing
        if len(prefix) != node.depth:
            return _issue(
                "error",
                "indent_depth_mismatch",
                f"({node.name} ...) is indented {len(prefix)} level(s) but nests "
                f"{node.depth} deep -- a paren is missing or extra above this line",
                node.line,
                node.column,
            )
    return None


def _quoted_after(content: str, node: _Node) -> Optional[str]:
    """First quoted token following a node's name, e.g. the name in (symbol "X")."""
    m = re.compile(r'\s*"((?:[^"\\]|\\.)*)"').match(content, node.start + 1 + len(node.name))
    return m.group(1) if m else None


def _check_orphan_fragments(nodes: List[_Node], root: str) -> List[Dict[str, Any]]:
    """Property/effects/at fragments that ended up as direct children of the root."""
    issues = []
    for node in nodes:
        if node.depth == 1 and node.parent == root and node.name in _ORPHAN_FRAGMENTS:
            issues.append(
                _issue(
                    "error",
                    "orphan_fragment",
                    f"({node.name} ...) sits directly under ({root} ...); it belongs "
                    f"inside a symbol. KiCad refuses to open the file.",
                    node.line,
                    node.column,
                )
            )
    return issues


def _check_root(nodes: List[_Node], expected: str) -> List[Dict[str, Any]]:
    if not nodes:
        return [_issue("error", "empty_file", "File contains no s-expression", 1, 1)]
    if nodes[0].name != expected:
        return [
            _issue(
                "error",
                "wrong_root",
                f"Top-level form is ({nodes[0].name} ...), expected ({expected} ...)",
                nodes[0].line,
                nodes[0].column,
            )
        ]
    return []


def _cli_check(subcommand: str, work_dir: Path, target: Path) -> Dict[str, Any]:
    """Run ``kicad-cli <subcommand> upgrade`` on a copy and report the outcome."""
    cli = resolve_kicad_cli()
    if not cli:
        return {"ran": False, "reason": "kicad-cli not found"}
    try:
        proc = subprocess.run(
            [cli, subcommand, "upgrade", str(target)],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=_CLI_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return {"ran": False, "reason": f"kicad-cli timed out after {_CLI_TIMEOUT_SEC}s"}
    except OSError as exc:
        return {"ran": False, "reason": f"kicad-cli could not be executed: {exc}"}

    output = (proc.stdout + proc.stderr).strip()
    return {
        "ran": True,
        "ok": proc.returncode == 0,
        "exitCode": proc.returncode,
        "output": output[:2000],
    }


def _copy_for_cli(root: Path, patterns: Tuple[str, ...], tmp: Path) -> Optional[Path]:
    """Copy the file plus its siblings matching *patterns* into *tmp*.

    A hierarchical schematic only loads if its sub-sheets are reachable, so the
    sheet cannot be validated alone. Returns the copied root, or None if the
    tree is too large to duplicate.
    """
    base = root.parent
    sources = [root]
    for pattern in patterns:
        sources.extend(p for p in base.rglob(pattern) if p != root and p.is_file())

    total = 0
    for src in sources:
        try:
            total += src.stat().st_size
        except OSError:
            continue
    if total > _MAX_CLI_COPY_BYTES:
        return None

    for src in sources:
        try:
            dest = tmp / src.relative_to(base)
        except ValueError:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dest)
        except OSError:
            continue
    return tmp / root.name


def _run_cli_if(
    path: Path, run_cli: bool, subcommand: str, patterns: Tuple[str, ...]
) -> Dict[str, Any]:
    """Confirm with kicad-cli, on a copy, unless the caller opted out."""
    if not run_cli:
        return {"ran": False, "reason": "not requested"}
    with tempfile.TemporaryDirectory(prefix="kicad-validate-") as tmp:
        copy = _copy_for_cli(path, patterns, Path(tmp))
        if copy is None:
            return {"ran": False, "reason": "file tree too large to copy for validation"}
        return _cli_check(subcommand, Path(tmp), copy)


def _read(path: Path) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    if not path.exists():
        return None, {"success": False, "message": f"File not found: {path}"}
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError as exc:
        return None, {"success": False, "message": f"File is not valid UTF-8: {exc}"}
    except OSError as exc:
        return None, {"success": False, "message": f"Could not read {path}: {exc}"}


def _finish(
    path: Path,
    issues: List[Dict[str, Any]],
    extra: Dict[str, Any],
    cli: Dict[str, Any],
) -> Dict[str, Any]:
    # kicad-cli is authoritative: a clean structural scan that it still rejects
    # means a fault this module does not know how to name yet, and reporting
    # "valid" there would be worse than saying nothing.
    if cli.get("ran") and not cli.get("ok") and not any(i["severity"] == "error" for i in issues):
        issues.append(
            _issue(
                "error",
                "kicad_cli_rejected",
                "Structure scan found nothing, but kicad-cli refused the file: "
                + (cli.get("output") or "no output"),
            )
        )

    issues.sort(key=lambda i: (i["line"], i["column"]))
    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]
    valid = not errors

    if valid:
        message = f"{path.name} is valid"
        if warnings:
            message += f" ({len(warnings)} warning(s))"
    else:
        first = errors[0]
        where = f" at line {first['line']}" if first["line"] else ""
        message = (
            f"{path.name} is invalid: {len(errors)} error(s), first{where}: {first['message']}"
        )

    result = {
        "success": True,
        "valid": valid,
        "path": str(path),
        "message": message,
        "errorCount": len(errors),
        "warningCount": len(warnings),
        "issues": issues,
        "kicadCli": cli,
    }
    result.update(extra)
    return result


def validate_symbol_library(params: Dict[str, Any]) -> Dict[str, Any]:
    """Check that a .kicad_sym file is structurally sound and will load."""
    path = Path(params["libraryPath"])
    run_cli = params.get("runKicadCli", True)

    content, error = _read(path)
    if error:
        return error
    assert content is not None

    nodes, issues = _scan(content)
    issues.extend(_check_root(nodes, "kicad_symbol_lib"))

    # Past a paren fault every node's depth is wrong, so the checks below would
    # report hundreds of consequences of the one real problem. Locate the break
    # and stop.
    if issues:
        hint = _indent_divergence(content, nodes)
        if hint:
            issues.append(hint)
        return _finish(
            path, issues, {"semanticChecksRan": False}, _run_cli_if(path, run_cli, "sym", ())
        )

    issues.extend(_check_orphan_fragments(nodes, "kicad_symbol_lib"))

    symbols: Dict[str, _Node] = {}
    symbol_nodes = [n for n in nodes if n.name == "symbol" and n.depth == 1]
    for node in symbol_nodes:
        name = _quoted_after(content, node)
        if name is None:
            issues.append(
                _issue(
                    "error", "unnamed_symbol", "(symbol ...) has no name", node.line, node.column
                )
            )
            continue
        if name in symbols:
            issues.append(
                _issue(
                    "warning",
                    "duplicate_symbol",
                    f"Symbol '{name}' is defined again (first at line "
                    f"{symbols[name].line}); KiCad keeps only one",
                    node.line,
                    node.column,
                )
            )
        else:
            symbols[name] = node

    # A unit is bound to its symbol by name, not by nesting. Renaming a symbol
    # without renaming "OLD_0_1" leaves units that KiCad silently drops, so the
    # symbol loads with no graphics and no pins.
    open_symbol: Optional[str] = None
    for node in nodes:
        if node.depth == 1 and node.name == "symbol":
            open_symbol = _quoted_after(content, node)
        elif node.depth == 2 and node.name == "symbol" and open_symbol:
            unit_name = _quoted_after(content, node)
            parent_name = open_symbol
            if unit_name is not None and not unit_name.startswith(f"{parent_name}_"):
                issues.append(
                    _issue(
                        "error",
                        "unit_name_mismatch",
                        f"Unit '{unit_name}' does not start with '{parent_name}_'; "
                        f"KiCad rejects the whole library (verified against "
                        f"kicad-cli 10.0: 'Unable to load library')",
                        node.line,
                        node.column,
                    )
                )

    cli = _run_cli_if(path, run_cli, "sym", ())
    return _finish(path, issues, {"symbolCount": len(symbols), "semanticChecksRan": True}, cli)


def validate_schematic(params: Dict[str, Any]) -> Dict[str, Any]:
    """Check that a .kicad_sch file is structurally sound and will load."""
    path = Path(params["schematicPath"])
    run_cli = params.get("runKicadCli", True)

    content, error = _read(path)
    if error:
        return error
    assert content is not None

    nodes, issues = _scan(content)
    issues.extend(_check_root(nodes, "kicad_sch"))

    # Past a paren fault every node's depth is wrong, so the checks below would
    # report hundreds of consequences of the one real problem. Locate the break
    # and stop.
    if issues:
        hint = _indent_divergence(content, nodes)
        if hint:
            issues.append(hint)
        return _finish(
            path,
            issues,
            {"semanticChecksRan": False},
            _run_cli_if(path, run_cli, "sch", ("*.kicad_sch",)),
        )

    issues.extend(_check_orphan_fragments(nodes, "kicad_sch"))

    instances = [
        n for n in nodes if n.name == "symbol" and n.depth == 1 and n.parent == "kicad_sch"
    ]
    has_lib_symbols = any(n.name == "lib_symbols" and n.depth == 1 for n in nodes)
    if instances and not has_lib_symbols:
        issues.append(
            _issue(
                "warning",
                "missing_lib_symbols",
                "Schematic places symbols but has no (lib_symbols ...) section; "
                "run update_symbol_from_library to restore the cached definitions",
            )
        )

    cli = _run_cli_if(path, run_cli, "sch", ("*.kicad_sch",))
    return _finish(path, issues, {"componentCount": len(instances), "semanticChecksRan": True}, cli)
