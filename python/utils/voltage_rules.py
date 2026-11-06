"""Clearance and creepage rules graded by working voltage between net classes.

A board with several voltage domains needs different spacing between each pair
of domains: an 800 V stack node and the logic ground need far more room than
two 400 V nodes of the same module. A single binary HV/LV class can't express
that. This module turns a short description, the classes with their voltages
plus a spacing table, into one ``.kicad_dru`` rule per pair of classes.

The output lives in a managed block of the ``.kicad_dru`` file, between two
comment markers, so a re-run replaces it and every other rule in the file is
left as written.

KiCad behaviours this relies on, checked with ``kicad-cli pcb drc`` on KiCad
9.0.9 and 10.0.8:

- An ``A.hasNetclass('X') && B.hasNetclass('Y')`` condition matches the pair in
  either order, so one rule per unordered pair is enough.
- ``(constraint creepage (min ...))`` is enforced and reported as "creepage".
- ``#`` starts a comment.
- String comparisons in conditions take ``*`` wildcards: ``B.NetName !=
  'unconnected-*'`` leaves out KiCad's nets for unwired pins.
- **A ``.kicad_dru`` that does not parse is ignored as a whole, silently.**
  kicad-cli exits 0 and reports no rule violations at all. A broken rule
  elsewhere in the file would therefore disable every rule written here, so
  the file is checked before it is written and the write is refused if the rest
  of the file is unbalanced.
- Of two rules matching the same items, the later one wins, even when it is
  looser. The managed block is kept at the end of the file so its rules are
  not overridden by earlier hand-written ones.
"""

from __future__ import annotations

import os
import re
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

BEGIN = "# kicad-mcp voltage rules: begin (managed by set_voltage_clearance_rules; edits here are replaced)"
END = "# kicad-mcp voltage rules: end"
RULE_PREFIX = "V:"
# KiCad string comparisons in rule conditions take * and ? wildcards.
UNCONNECTED = "unconnected-*"

_CLASS_NAME_OK = re.compile(r"^[^'\"\\()\n\r]+$")


class VoltageRuleError(ValueError):
    """Bad input; the message is meant for the caller."""


# --------------------------------------------------------------------------- #
# Syntax check
# --------------------------------------------------------------------------- #


def check_balanced(text: str) -> Optional[str]:
    """None if *text*'s parentheses balance, else a description of the problem.

    Skips ``"..."`` strings (with backslash escapes) and ``#`` comments to end
    of line, the two places a parenthesis is not structure.
    """
    depth = 0
    line = 1
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
        elif c == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif c == '"':
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\":
                    i += 1
                elif text[i] == "\n":
                    line += 1
                i += 1
            if i >= n:
                return f"unterminated string (line {line})"
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth < 0:
                return f"unexpected ')' at line {line}"
        i += 1
    if depth > 0:
        return f"{depth} unclosed '(' at end of file"
    return None


# --------------------------------------------------------------------------- #
# Spacing table and pairs
# --------------------------------------------------------------------------- #


def _number(value: Any, what: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise VoltageRuleError(f"{what} must be a number, got {value!r}")
    if number < 0:
        raise VoltageRuleError(f"{what} must not be negative, got {number}")
    return number


def normalise_table(table: Sequence[Dict[str, Any]]) -> List[Dict[str, float]]:
    """Validate the spacing table and sort it by ``upTo``.

    Each row: ``{"upTo": V, "clearance": mm, "creepage"?: mm}``, meaning
    "a working voltage up to V needs this much". Larger voltages must not need
    less spacing; a table that says so is almost certainly a typo.
    """
    if not table:
        raise VoltageRuleError("spacing must have at least one row")
    rows = []
    for k, row in enumerate(table):
        if not isinstance(row, dict):
            raise VoltageRuleError(f"spacing[{k}] must be an object")
        out = {
            "upTo": _number(row.get("upTo"), f"spacing[{k}].upTo"),
            "clearance": _number(row.get("clearance"), f"spacing[{k}].clearance"),
        }
        if row.get("creepage") is not None:
            out["creepage"] = _number(row["creepage"], f"spacing[{k}].creepage")
        rows.append(out)
    rows.sort(key=lambda r: r["upTo"])
    for prev, cur in zip(rows, rows[1:]):
        if cur["upTo"] == prev["upTo"]:
            raise VoltageRuleError(f"two spacing rows for upTo={cur['upTo']}")
        for key in ("clearance", "creepage"):
            if key in prev and key in cur and cur[key] < prev[key]:
                raise VoltageRuleError(
                    f"spacing {key} falls from {prev[key]} mm (≤{prev['upTo']} V) to "
                    f"{cur[key]} mm (≤{cur['upTo']} V); a higher voltage cannot need less"
                )
    return rows


def spacing_for(voltage: float, rows: List[Dict[str, float]]) -> Dict[str, float]:
    """The first row whose ``upTo`` covers *voltage*. Raises when none does:
    extrapolating a safety table is the caller's decision, not this module's."""
    for row in rows:
        if voltage <= row["upTo"]:
            return row
    raise VoltageRuleError(
        f"working voltage {voltage:g} V is above the spacing table's last row "
        f"({rows[-1]['upTo']:g} V); add a row that covers it"
    )


def _check_class_name(name: Any, where: str) -> str:
    if not isinstance(name, str) or not name or not _CLASS_NAME_OK.match(name):
        raise VoltageRuleError(
            f"{where}: net class name {name!r} is empty or contains one of ' \" \\ ( ) newline"
        )
    return name


def plan_rules(
    classes: Sequence[Dict[str, Any]],
    spacing: Sequence[Dict[str, Any]],
    pairs: Optional[Sequence[Dict[str, Any]]] = None,
    other_nets_voltage: Optional[float] = 0.0,
) -> List[Dict[str, Any]]:
    """One entry per pair of domains that needs a rule.

    ``classes``: ``[{"name": "HV_STACK", "voltage": 800}, ...]``. Each voltage is
    the worst-case potential against one reference shared by all classes, so the
    working voltage between two classes is ``|Va - Vb|``.

    ``pairs``: ``[{"a": "X", "b": "Y", "voltage": V}]`` overrides that for one pair.
    Use it when two classes sit in separate domains (across an isolation barrier)
    and no shared reference describes both worst cases.

    ``other_nets_voltage``: potential of every net in none of the listed classes,
    used for one "class vs everything else" rule per class. ``None`` skips those rules.
    """
    if not classes:
        raise VoltageRuleError("classes must list at least one net class")
    rows = normalise_table(spacing)
    volts: Dict[str, float] = {}
    for k, c in enumerate(classes):
        if not isinstance(c, dict):
            raise VoltageRuleError(f"classes[{k}] must be an object")
        name = _check_class_name(c.get("name"), f"classes[{k}]")
        if name in volts:
            raise VoltageRuleError(f"net class {name!r} listed twice")
        volts[name] = _number(c.get("voltage"), f"classes[{k}].voltage")

    overrides: Dict[Tuple[str, str], float] = {}
    for k, p in enumerate(pairs or []):
        a = _check_class_name(p.get("a"), f"pairs[{k}].a")
        b = _check_class_name(p.get("b"), f"pairs[{k}].b")
        for name in (a, b):
            if name not in volts:
                raise VoltageRuleError(f"pairs[{k}] names {name!r}, which is not in classes")
        if a == b:
            raise VoltageRuleError(f"pairs[{k}] pairs {a!r} with itself")
        overrides[tuple(sorted((a, b)))] = _number(p.get("voltage"), f"pairs[{k}].voltage")

    names = list(volts)
    plan: List[Dict[str, Any]] = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            key = tuple(sorted((a, b)))
            voltage = overrides.get(key, abs(volts[a] - volts[b]))
            source = "pair" if key in overrides else "difference"
            plan.append(_entry(a, b, voltage, source, rows))
    if other_nets_voltage is not None:
        other = _number(other_nets_voltage, "otherNetsVoltage")
        for a in names:
            plan.append(_entry(a, None, abs(volts[a] - other), "other nets", rows))
    return plan


def _entry(a: str, b: Optional[str], voltage: float, source: str, rows) -> Dict[str, Any]:
    row = spacing_for(voltage, rows)
    entry = {
        "a": a,
        "b": b if b is not None else "(other nets)",
        "voltage": voltage,
        "source": source,
        "clearance": row["clearance"],
    }
    if "creepage" in row:
        entry["creepage"] = row["creepage"]
    return entry


# --------------------------------------------------------------------------- #
# Rendering and file edit
# --------------------------------------------------------------------------- #


def _fmt(mm: float) -> str:
    return f"{mm:.4f}".rstrip("0").rstrip(".") + "mm"


def render_block(plan: List[Dict[str, Any]], all_classes: Sequence[str]) -> str:
    lines = [BEGIN]
    for e in plan:
        a = e["a"]
        if e["b"] == "(other nets)":
            others = " || ".join(f"B.hasNetclass('{c}')" for c in all_classes)
            # KiCad names an unwired pin's net "unconnected-(R1-Pad2)". Such a
            # pin floats with its own part, so it isn't "other nets" (low-voltage
            # logic): without this a floating pin of a high-voltage part was held
            # to the full spacing from that part's own pads.
            condition = f"A.hasNetclass('{a}') && !({others}) && B.NetName != '{UNCONNECTED}'"
            name = f"{RULE_PREFIX}{a}-other"
        else:
            condition = f"A.hasNetclass('{a}') && B.hasNetclass('{e['b']}')"
            name = f"{RULE_PREFIX}{a}-{e['b']}"
        lines.append(f"# {a} vs {e['b']}: {e['voltage']:g} V working ({e['source']})")
        lines.append(f'(rule "{name}"')
        lines.append(f'  (condition "{condition}")')
        lines.append(f"  (constraint clearance (min {_fmt(e['clearance'])}))")
        if "creepage" in e:
            lines.append(f"  (constraint creepage (min {_fmt(e['creepage'])}))")
        lines.append(")")
    lines.append(END)
    return "\n".join(lines)


def replace_block(existing: str, block: str) -> str:
    """Put *block* at the end of *existing*, replacing an earlier managed block."""
    text = existing
    start = text.find(BEGIN)
    if start != -1:
        end = text.find(END, start)
        if end == -1:
            raise VoltageRuleError(
                "the .kicad_dru has the managed block's begin marker but not its end "
                "marker; fix the file by hand before running this again"
            )
        text = text[:start] + text[end + len(END) :]
    text = re.sub(r"\n{3,}", "\n\n", text).rstrip()
    if not text:
        text = "(version 1)"
    return text + "\n\n" + block + "\n"


def write_rules(dru_path: str, block: str) -> Dict[str, Any]:
    """Write *block* into *dru_path*, refusing if the rest of the file doesn't parse."""
    existing = "(version 1)\n"
    if os.path.exists(dru_path):
        with open(dru_path, "r", encoding="utf-8") as f:
            existing = f.read()
    new_text = replace_block(existing, block)
    rest = new_text.replace(block, "")
    problem = check_balanced(rest)
    if problem:
        raise VoltageRuleError(
            f"{dru_path} does not parse ({problem}). KiCad silently ignores every rule "
            "in a .kicad_dru it cannot parse, so these rules would have no effect. "
            "Fix the file first."
        )
    problem = check_balanced(block)
    if problem:  # would be a bug here, not bad input
        raise RuntimeError(f"generated rules do not parse: {problem}")
    directory = os.path.dirname(dru_path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".dru-", suffix=".kicad_dru")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_text)
        os.replace(tmp, dru_path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return {"druFile": dru_path}
