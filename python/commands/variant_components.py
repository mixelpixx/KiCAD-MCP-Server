"""Scoped reads/edits of KiCad 10 placed-symbol instance variants, not PCB variants."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from commands.variant_registry import registered_names
from utils.sexpr_format import QUOTED_VALUE_SKIP, escape_sexpr_string, unescape_sexpr_string
from utils.sheet_tree import sheet_chains


@dataclass
class _Node:
    start: int
    end: int = 0
    atoms: list[str] = field(default_factory=list)
    children: list[_Node] = field(default_factory=list)

    def named(self, key):
        return [child for child in self.children if child.atoms[0] == key]

    def value(self, key):
        matches = self.named(key)
        if len(matches) != 1 or len(matches[0].atoms) != 2 or matches[0].children:
            raise ValueError(f"Expected one scalar ({key} ...)")
        return _decode(matches[0].atoms[1])


# Record exact character ranges; don't re-serialize lib_symbols, properties,
# unrelated projects, or whitespace. KiCad allows whole-line '#' comments.
_TOKEN = re.compile(
    r"(?P<comment>^[ \t]*\#[^\r\n]*)|[ \t]+|[\r\n]+|[()]|" + QUOTED_VALUE_SKIP + r'|[^()" \t\r\n]+',
    re.M,
)


def _decode(atom):
    return unescape_sexpr_string(atom[1:-1]) if atom.startswith('"') else atom


def _parse(text):
    stack = []
    root = None
    pos = 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match:
            raise ValueError("Invalid or unterminated schematic token")
        token = match[0]
        pos = match.end()
        if token == "(":
            node = _Node(match.start())
            if stack:
                stack[-1].children.append(node)
            elif root is None:
                root = node
            else:
                raise ValueError("Multiple top-level expressions")
            stack.append(node)
        elif token == ")":
            if not stack or not stack[-1].atoms:
                raise ValueError("Unexpected closing parenthesis")
            stack.pop().end = pos
        elif token.isspace() or match.lastgroup == "comment":
            continue
        elif stack:
            stack[-1].atoms.append(token)
        else:
            raise ValueError("Unexpected text outside the schematic")
    if stack or not root or root.atoms != ["kicad_sch"]:
        raise ValueError("Expected one complete kicad_sch expression")
    return root


_VERSION = {"20250922", "20251012", "20251028", "20260101", "20260306"}
_COMMON = {"projectPath", "schematicPath", "reference", "variant"}


def _load(params):
    if not isinstance(params, dict) or any(
        not isinstance(params.get(k), str) or not params[k].strip() for k in _COMMON
    ):
        raise ValueError("Expected projectPath, schematicPath, reference and variant strings")
    project = Path(params["projectPath"])
    sheet = Path(params["schematicPath"])
    if sheet.suffix.lower() != ".kicad_sch" or not sheet.is_file():
        raise ValueError("schematicPath must name an existing .kicad_sch file")
    name = params["variant"]
    if name.casefold() == "< default >" or registered_names(project).count(name) != 1:
        raise ValueError(f"Variant {name!r} is not explicitly registered in the project")
    text = sheet.read_bytes().decode("utf-8")
    root = _parse(text)
    if root.value("version") not in _VERSION:
        raise ValueError("Unsupported schematic version; save in KiCad 10 first")
    root_sheet = project.with_suffix(".kicad_sch")
    allowed_paths = (
        {"/" + root.value("uuid")}
        if root_sheet.resolve() == sheet.resolve()
        else {"/" + "/".join(chain) for chain in sheet_chains(root_sheet, sheet)}
    )
    if not allowed_paths:
        raise ValueError("schematicPath is not a sheet of the specified project")
    units = []
    for symbol in root.named("symbol"):
        for instances in symbol.named("instances"):
            for group in instances.named("project"):
                if len(group.atoms) != 2 or _decode(group.atoms[1]) != project.stem:
                    continue
                for path in group.named("path"):
                    if path.value("reference") != params["reference"]:
                        continue
                    if len(path.atoms) != 2:
                        raise ValueError("Malformed symbol instance path")
                    address = _decode(path.atoms[1])
                    if address not in allowed_paths:
                        continue  # Stale path or another same-named project.
                    unit = int(path.value("unit"))
                    if unit < 1 or any(item[0] == unit for item in units):
                        raise ValueError("Ambiguous or invalid unit for reference")
                    clauses = [v for v in path.named("variant") if v.value("name") == name]
                    if len(clauses) > 1:
                        raise ValueError("Duplicate variant clause on instance")
                    units.append((unit, address, symbol, path, clauses[0] if clauses else None))
    if not units:
        raise ValueError(
            f'No placed instance for {params["reference"]!r} in this project and sheet'
        )
    return sheet, text, sorted(units)


def _states(units):
    result = []
    for unit, address, _, _, clause in units:
        fields = {}
        dnp = None
        if clause:
            flags = {"dnp", "in_bom", "on_board", "exclude_from_sim", "in_pos_files"}
            if len(clause.atoms) != 1 or any(
                c.atoms[0] not in flags | {"name", "field"} for c in clause.children
            ):
                raise ValueError("Unsupported variant clause")
            for key in flags:
                if clause.named(key) and clause.value(key) not in ("yes", "no"):
                    raise ValueError(f"Invalid variant {key} flag")
            if clause.named("dnp"):
                dnp = clause.value("dnp") == "yes"
            for entry in clause.named("field"):
                if len(entry.children) != 2 or len(entry.atoms) != 1:
                    raise ValueError("Unsupported variant field")
                key = entry.value("name")
                if key in fields:
                    raise ValueError("Duplicate variant field")
                fields[key] = entry.value("value")
        result.append(dict(unit=unit, path=address, dnp=dnp, fields=fields))
    return result


def get_component_variant(params):
    """Report explicit overrides on each matching unit; null DNP means inherit."""
    try:
        _, _, units = _load(params)
        if params.keys() - _COMMON:
            raise ValueError("Unexpected get_component_variant parameter")
        return dict(success=True, **params, units=_states(units))
    except (ValueError, OSError) as exc:
        return {"success": False, "error": str(exc)}


def _insert(text, parent, clauses):
    """Insert after the last child, borrowing its existing whitespace style."""
    anchor = parent.children[-1]
    prefix = text[text.rfind("\n", 0, anchor.start) + 1 : anchor.start]
    separator = " "
    if not prefix.strip():
        newline = "\r\n" if text[: anchor.start].rstrip(" \t").endswith("\r\n") else "\n"
        separator = newline + prefix
    return anchor.end, anchor.end, "".join(separator + c for c in clauses)


def _quote(s):
    return '"' + escape_sexpr_string(s) + '"'


def _remove(text, node):
    # Remove the node's own preceding separator, not its parent's closer or a comment.
    start = node.start
    while start and text[start - 1] in " \t":
        start -= 1
    if start and text[start - 1] == "\n":
        previous = text[text.rfind("\n", 0, start - 1) + 1 : start - 1]
        if previous.lstrip().startswith("#"):
            return start, node.end, ""  # A comment must retain its line terminator.
        start -= 1
        if start and text[start - 1] == "\r":
            start -= 1
    return start, node.end, ""


def _edits(text, params, symbol, path, clause):
    """Plan edits only; validate all units before touching the file."""
    changes = []
    additions = []
    removed = set()

    def update(old, expression):
        if old:
            if expression is None:
                removed.add(old.start)
                changes.append(_remove(text, old))
            elif text[old.start : old.end] != expression:
                changes.append((old.start, old.end, expression))
        elif expression is not None:
            additions.append(expression)

    if params.get("reset"):
        return [_remove(text, clause)] if clause else []

    if "dnp" in params:
        base = symbol.value("dnp") if symbol.named("dnp") else "no"
        if base not in ("yes", "no"):
            raise ValueError("Malformed base dnp flag")
        value = "yes" if params["dnp"] else "no"
        old = clause.named("dnp") if clause else []
        if not old or clause.value("dnp") != value or value == base:
            update(old[0] if old else None, f"(dnp {value})" if value != base else None)

    existing = {f.value("name"): f for f in clause.named("field")} if clause else {}
    properties = {
        _decode(p.atoms[1]): _decode(p.atoms[2])
        for p in symbol.named("property")
        if len(p.atoms) == 3
    }
    for key, value in params.get("fields", {}).items():
        if key == "Reference" or key not in properties:
            raise ValueError(f"Field {key!r} is missing or cannot be overridden")
        old = existing.get(key)
        if value is None or value == properties[key]:
            update(old, None)
        elif not old:
            update(None, f"(field (name {_quote(key)}) (value {_quote(value)}))")
        elif old.value("value") != value:
            update(old.named("value")[0], f"(value {_quote(value)})")

    if not clause and additions:
        variant = f'(variant (name {_quote(params["variant"])}) {" ".join(additions)})'
        return [_insert(text, path, [variant])]
    if clause:
        if not additions and all(
            c.atoms[0] == "name" or c.start in removed for c in clause.children
        ):
            return [_remove(text, clause)]
        if additions:
            changes.append(_insert(text, clause, additions))
    return changes


def _write(sheet, before, after, project):
    with tempfile.NamedTemporaryFile(dir=sheet.parent, delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        temp_path.write_bytes(after.encode("utf-8"))
        shutil.copymode(sheet, temp_path)
        for target in (project, project.with_suffix(".kicad_sch"), sheet):
            if target.with_name("~" + target.name + ".lck").exists():
                raise ValueError(f"Close KiCad before editing: {target.name} has an editor lock")
        if sheet.read_bytes() != before.encode("utf-8"):
            raise ValueError("Schematic changed during edit; retry")
        os.replace(temp_path, sheet)
    finally:
        temp_path.unlink(missing_ok=True)


def set_component_variant(params):
    """Patch overrides on every matching placed unit on the explicitly selected sheet."""
    try:
        sheet, text, units = _load(params)
        _states(units)  # Reject ambiguous duplicate fields/flags before planning edits.
        if params.keys() - (_COMMON | {"dnp", "fields", "reset"}):
            raise ValueError("Unexpected set_component_variant parameter")
        for key in ("dnp", "reset"):
            if key in params and not isinstance(params[key], bool):
                raise ValueError(f"{key} must be boolean")
        fields = params.get("fields", {})
        if not isinstance(fields, dict) or any(
            not isinstance(k, str) or not k.strip() or v is not None and not isinstance(v, str)
            for k, v in fields.items()
        ):
            raise ValueError("fields must map nonempty field names to strings or null")
        if any(
            re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", v)
            for v in fields.values()
            if v is not None
        ):
            raise ValueError("Field values may not contain non-text control characters")
        if params.get("reset") and ("dnp" in params or "fields" in params):
            raise ValueError("reset clears the entire clause; do not combine it with overrides")
        if not params.get("reset") and not fields and "dnp" not in params:
            raise ValueError("Specify dnp, fields or reset=true")
        edits = []
        for _, _, symbol, path, clause in units:
            edits.extend(_edits(text, params, symbol, path, clause))
        updated = text
        for start, end, replacement in sorted(edits, reverse=True):
            updated = updated[:start] + replacement + updated[end:]
        if updated != text:
            _parse(updated)  # Fail before replacing the original, not during readback.
            _write(sheet, text, updated, Path(params["projectPath"]))
        result = get_component_variant({k: params[k] for k in _COMMON})
        return {**result, "changed": updated != text}
    except (ValueError, OSError) as exc:
        return {"success": False, "error": str(exc)}
