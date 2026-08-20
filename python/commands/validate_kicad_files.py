"""Structural validation for .kicad_sch and .kicad_sym files.

``kicad-cli`` answers whether a file loads, but not why: a single misplaced
paren anywhere in a 40 000-line library produces ``Unable to load library`` and
nothing else. Recovering from that means bisecting the file by hand.

These tools do the locating. A single string-aware pass over the text reports
the line and column of every structural fault, then a set of KiCad-specific
checks catches the damage that is syntactically legal but still wrong -- a
property sitting directly under ``(kicad_sch ...)`` instead of inside a symbol,
an ``(effects ...)`` tail left inside a ``(symbol ...)`` by a truncated rewrite,
a unit that escaped its parent, or one still named after the symbol it was
renamed away from.

Paren faults that net to zero are the hard case, because nothing counts them and
``kicad-cli`` reports no position for them. Since KiCad writes one tab per
nesting level, the first line whose indentation stops agreeing with its depth is
where the structure broke, and that check runs on every tab-indented file rather
than only when something else already failed.

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

# The same fragments minus "property", which is a perfectly legal direct child
# of (symbol ...) in a .kicad_sym -- these five never are. Checked against all
# 222 libraries KiCad 10 ships (22 776 symbols): the only direct children of a
# (symbol ...) there are property, symbol, embedded_fonts, extends,
# exclude_from_sim, in_bom, on_board, in_pos_files,
# duplicate_pin_numbers_are_jumpers, pin_names, pin_numbers, power and
# body_styles, and of a unit pin, rectangle, polyline, arc, circle, text,
# text_box, bezier and unit_name. kicad-cli 10.0.4 answers "Unable to load
# library" for a perfectly balanced library with (effects ...) or (at ...)
# placed there, which is why these are errors.
#
# .kicad_sch is a different format and this set does NOT apply to it: (at ...)
# is a legal direct child of a placed (symbol ...) in a schematic.
_SYMBOL_ORPHAN_FRAGMENTS = frozenset({"effects", "hide", "at", "font", "justify"})

# A unit that escaped its parent symbol lands at the top level still carrying
# the "<symbol>_<unit>_<style>" name it was given inside it.
_UNIT_NAME = re.compile(r"(?P<stem>.+)_\d+_\d+$")

# Spellings of false a shell or a hand-written script actually produces. JSON
# has a real boolean, but a caller reaching this dispatch directly can pass the
# string "false", which is truthy and would run the kicad-cli it asked to skip.
_FALSE_STRINGS = frozenset({"", "0", "false", "no", "off", "none", "null"})

# Cap on the size of the single file this will duplicate to run kicad-cli on.
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

        # Before dispatching on the character: anything but whitespace out here
        # is content the top-level form does not contain. Checking it after the
        # '"' branch would let a quoted token through, because that branch
        # consumes the whole string and continues. An extra ')' is excluded --
        # unbalanced_close below names that far better.
        if closed_root and not ch.isspace() and ch != ")":
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

        if ch == '"':
            j = i + 1
            str_line, str_line_start = line, line_start
            while j < n:
                if content[j] == "\\":
                    # The escaped character may itself be the newline: skipping
                    # it blind loses a line and shifts every position reported
                    # after this string by one.
                    if j + 1 < n and content[j + 1] == "\n":
                        line += 1
                        line_start = j + 2
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
        if set(prefix) - {"\t"}:
            continue  # space-indented line: the one-tab-per-level rule says nothing
        if not prefix and node.depth:
            # Un-indented but nested: a hand-edited or generated line sitting at
            # column 1 is legal and says nothing about the paren structure. The
            # depth-0 root also has no prefix, and that one must still be
            # checked, so this cannot just test the prefix.
            continue
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


def _check_symbol_child_fragments(nodes: List[_Node]) -> List[Dict[str, Any]]:
    """Property-block tails that ended up as direct children of a (symbol ...).

    .kicad_sym only -- see _SYMBOL_ORPHAN_FRAGMENTS for why this must not be
    applied to a schematic. The truncating property rewrite leaves its tail
    *inside* the symbol it was editing rather than under the root, so the
    root-only check above cannot see the damage this module exists to find.
    """
    issues = []
    for node in nodes:
        if node.parent == "symbol" and node.name in _SYMBOL_ORPHAN_FRAGMENTS:
            issues.append(
                _issue(
                    "error",
                    "orphan_fragment",
                    f"({node.name} ...) sits directly inside a (symbol ...); it belongs in "
                    f"the (property ...) or graphic it was cut out of. KiCad refuses to "
                    f"open the file (kicad-cli 10.0: 'Unable to load library').",
                    node.line,
                    node.column,
                )
            )
    return issues


def _check_escaped_units(symbols: Dict[str, _Node]) -> List[Dict[str, Any]]:
    """Top-level symbols that are really units which escaped their parent.

    A dropped paren above a unit promotes it to the top level, where its name
    still says which symbol it came from. Unlike the fragments above this is a
    warning: the library still loads (kicad-cli 10.0.4 returns 0), which is
    exactly what makes it easy to miss. KiCad reads the unit as a symbol in its
    own right, so the parent is left with none of those graphics or pins and the
    library gains bogus extra entries -- which is also why symbolCount is higher
    than the number of symbols the author meant to write.
    """
    issues = []
    for name, node in symbols.items():
        match = _UNIT_NAME.match(name)
        if not match:
            continue
        stem = match.group("stem")
        parent = symbols.get(stem)
        if parent is None:
            continue
        issues.append(
            _issue(
                "warning",
                "escaped_unit",
                f"Top-level symbol '{name}' is a unit of '{stem}' (line {parent.line}) that "
                f"escaped its parent; KiCad loads it as a separate symbol, leaving '{stem}' "
                f"without those graphics and pins",
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


def _copy_for_cli(root: Path, tmp: Path) -> Optional[Path]:
    """Copy the file under validation into *tmp*, on its own.

    Only that one file is needed. ``kicad-cli sch upgrade`` upgrades exactly the
    file it is given and does not follow (sheet ...) references, so a sheet from
    a hierarchical design validates alone -- verified against kicad-cli 10.0.4,
    which returns 0 for a root sheet whose sub-sheet is absent from the
    directory entirely, and again when the sub-sheet is present but corrupt.
    Copying the siblings in would only make the size cap below depend on
    unrelated projects that happen to share a parent directory, and tripping
    that cap skips the authoritative check altogether.

    Returns the copied file, or None if it alone is too large to duplicate.
    """
    try:
        if root.stat().st_size > _MAX_CLI_COPY_BYTES:
            return None
    except OSError:
        return None

    dest = tmp / root.name
    try:
        shutil.copy2(root, dest)
    except OSError:
        return None
    return dest


def _run_cli_if(path: Path, run_cli: bool, subcommand: str) -> Dict[str, Any]:
    """Confirm with kicad-cli, on a copy, unless the caller opted out."""
    if not run_cli:
        return {"ran": False, "reason": "not requested"}
    with tempfile.TemporaryDirectory(prefix="kicad-validate-") as tmp:
        copy = _copy_for_cli(path, Path(tmp))
        if copy is None:
            return {"ran": False, "reason": "file too large to copy for validation"}
        return _cli_check(subcommand, Path(tmp), copy)


def _wants_cli(params: Dict[str, Any]) -> bool:
    """Whether to run kicad-cli, tolerating a string where a bool was meant."""
    value = params.get("runKicadCli", True)
    if isinstance(value, str):
        return value.strip().lower() not in _FALSE_STRINGS
    return bool(value)


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
    run_cli = _wants_cli(params)

    content, error = _read(path)
    if error:
        return error
    assert content is not None

    nodes, issues = _scan(content)
    issues.extend(_check_root(nodes, "kicad_symbol_lib"))
    unbalanced = bool(issues)

    # A paren fault that nets to zero -- one dropped and a later one spare,
    # which is what a bad slice-and-splice rewrite produces -- leaves the scan
    # above with nothing to report, and kicad-cli gives no line number either.
    # The indentation hint is then the only thing that can say where the file
    # broke, so it runs whatever the scan found rather than only as a footnote
    # to a fault already caught.
    hint = _indent_divergence(content, nodes)
    if hint:
        issues.append(hint)

    # Past an *unbalanced* paren every later node's depth is wrong, so the
    # checks below would report hundreds of consequences of the one real
    # problem. Locate the break and stop.
    if unbalanced:
        return _finish(
            path, issues, {"semanticChecksRan": False}, _run_cli_if(path, run_cli, "sym")
        )

    issues.extend(_check_orphan_fragments(nodes, "kicad_symbol_lib"))
    issues.extend(_check_symbol_child_fragments(nodes))

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

    issues.extend(_check_escaped_units(symbols))

    # A unit is bound to its symbol by name, not by nesting. Renaming a symbol
    # without renaming its "OLD_0_1" units leaves names that no longer match,
    # and KiCad rejects the whole library rather than quietly dropping them:
    # kicad-cli 10.0.4 answers "Unable to load library" for both `sym upgrade`
    # and `sym export svg`.
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

    cli = _run_cli_if(path, run_cli, "sym")
    return _finish(path, issues, {"symbolCount": len(symbols), "semanticChecksRan": True}, cli)


def validate_schematic(params: Dict[str, Any]) -> Dict[str, Any]:
    """Check that a .kicad_sch file is structurally sound and will load."""
    path = Path(params["schematicPath"])
    run_cli = _wants_cli(params)

    content, error = _read(path)
    if error:
        return error
    assert content is not None

    nodes, issues = _scan(content)
    issues.extend(_check_root(nodes, "kicad_sch"))
    unbalanced = bool(issues)

    # See validate_symbol_library: a paren fault that nets to zero leaves the
    # scan with nothing to report, and this hint is the only thing that can
    # localise it, so it does not depend on the scan having found something.
    hint = _indent_divergence(content, nodes)
    if hint:
        issues.append(hint)

    # Past an *unbalanced* paren every later node's depth is wrong, so the
    # checks below would report hundreds of consequences of the one real
    # problem. Locate the break and stop.
    if unbalanced:
        return _finish(
            path,
            issues,
            {"semanticChecksRan": False},
            _run_cli_if(path, run_cli, "sch"),
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

    cli = _run_cli_if(path, run_cli, "sch")
    return _finish(path, issues, {"componentCount": len(instances), "semanticChecksRan": True}, cli)
