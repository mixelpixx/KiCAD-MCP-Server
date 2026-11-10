"""Clearance and creepage rules graded by working voltage between net classes.

A board with several voltage domains needs different spacing between each pair
of domains: an 800 V stack node and the logic ground need far more room than
two 400 V nodes of the same module. A single binary HV/LV class can't express
that. This module turns a short description, the classes with their voltages
plus a spacing table, into one ``.kicad_dru`` rule per pair of classes.

The output lives in a managed block of the ``.kicad_dru`` file, between two
comment markers, so a re-run replaces it and every other rule in the file is
left as written.

A class's potential is either one number (a node that stays at one potential)
or ``[min, max]`` for a node that swings, such as a half-bridge switch node
going 0 to 800 V. The working voltage between two classes is the largest
difference the two ranges can show, ``max(|maxA - minB|, |maxB - minA|)``;
with two single numbers that is ``|Va - Vb|``. Giving a swinging node its
maximum alone under-spaces it against the bus it swings to (800 vs 800 would
read as 0 V).

The spacing table is keyed by one voltage per row. Under IEC 60664-1 clearance
follows from the impulse/peak voltage and creepage from the RMS working
voltage, so the voltage used as the key must suit both columns of the table.
The tool supplies no values; they come from the user's standard and coating.

KiCad 9 or newer: the ``creepage`` constraint and ``hasNetclass()`` arrived in
KiCad 9, and KiCad ignores a ``.kicad_dru`` it cannot parse as a whole, so on
KiCad 8 the block would switch off every rule in the file. The handler checks
the running KiCad's version and refuses on 8.

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
# creepage constraint and hasNetclass() exist from KiCad 9.
MIN_KICAD_MAJOR = 9

_CLASS_NAME_OK = re.compile(r"^[^'\"\\()\n\r]+$")
_VERSION_RE = re.compile(r"^\D*(\d+)\.(\d+)")

Potential = Tuple[float, float]


class VoltageRuleError(ValueError):
    """Bad input; the message is meant for the caller."""


# --------------------------------------------------------------------------- #
# KiCad version
# --------------------------------------------------------------------------- #


def kicad_major_version(build_version: Any) -> Optional[int]:
    """The major number of a ``pcbnew.GetBuildVersion()`` string, e.g. 9 for
    ``"9.0.9-9.0.9~ubuntu24.04.1"`` or ``"(10.0.8)"``; None when unreadable."""
    match = _VERSION_RE.match(str(build_version or "").strip())
    return int(match.group(1)) if match else None


def unsupported_kicad_message(build_version: Any) -> Optional[str]:
    """Why this tool refuses on *build_version*, or None when it may run."""
    major = kicad_major_version(build_version)
    if major is None or major >= MIN_KICAD_MAJOR:
        return None
    return (
        f"set_voltage_clearance_rules needs KiCad {MIN_KICAD_MAJOR} or newer; this is KiCad "
        f"{build_version}. The creepage constraint and hasNetclass() in the generated rules "
        f"arrived in KiCad {MIN_KICAD_MAJOR}, and KiCad ignores a .kicad_dru it cannot parse "
        "as a whole, so writing them here would switch off every rule in the file, including "
        "hand-written ones. Nothing was written."
    )


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


def _signed_number(value: Any, what: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise VoltageRuleError(f"{what} must be a number, got {value!r}")


def potential_range(value: Any, what: str) -> Potential:
    """A node's potential as ``(min, max)`` volts.

    One number is a fixed potential; ``[min, max]`` is a node that swings.
    Negative values are allowed: a -400 V rail is 800 V from a +400 V one.
    """
    if isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise VoltageRuleError(f"{what} must be a number or [min, max], got {value!r}")
        low = _signed_number(value[0], f"{what}[0]")
        high = _signed_number(value[1], f"{what}[1]")
        if low > high:
            raise VoltageRuleError(f"{what} must be [min, max], got [{low:g}, {high:g}]")
        return (low, high)
    fixed = _signed_number(value, what)
    return (fixed, fixed)


def working_voltage(a: Potential, b: Potential) -> float:
    """The largest potential difference two ranges can show."""
    return max(abs(a[1] - b[0]), abs(b[1] - a[0]))


def normalise_table(table: Sequence[Dict[str, Any]]) -> List[Dict[str, float]]:
    """Validate the spacing table and sort it by ``upTo``.

    Each row: ``{"upTo": V, "clearance": mm, "creepage"?: mm}``, meaning
    "a working voltage up to V needs this much". Larger voltages must not need
    less spacing, and once a row gives a creepage every higher row must too;
    a table that says otherwise is almost certainly a typo, and an 800 V pair
    with no creepage rule at all is the outcome to avoid.
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
        if "creepage" in prev and "creepage" not in cur:
            raise VoltageRuleError(
                f"spacing row for ≤{cur['upTo']:g} V has no creepage while the row for "
                f"≤{prev['upTo']:g} V has {prev['creepage']} mm; a higher voltage cannot drop "
                "the creepage rule (pairs in that range would get none)"
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
    other_nets_voltage: Any = 0.0,
) -> List[Dict[str, Any]]:
    """One entry per pair of domains that needs a rule.

    ``classes``: ``[{"name": "HV_STACK", "voltage": 800}, ...]``. Each voltage is
    the node's potential against one reference shared by all classes: one
    number for a node that stays put, ``[min, max]`` for one that swings. The
    working voltage between two classes is ``working_voltage``, the largest
    difference their ranges can show (``|Va - Vb|`` for two fixed nodes).

    ``pairs``: ``[{"a": "X", "b": "Y", "voltage": V}]`` overrides that for one pair.
    Use it when two classes sit in separate domains (across an isolation barrier)
    and no shared reference describes both worst cases.

    ``other_nets_voltage``: potential (number or ``[min, max]``) of every net in
    none of the listed classes, used for one "class vs everything else" rule per
    class. ``None`` skips those rules.
    """
    if not classes:
        raise VoltageRuleError("classes must list at least one net class")
    rows = normalise_table(spacing)
    volts: Dict[str, Potential] = {}
    for k, c in enumerate(classes):
        if not isinstance(c, dict):
            raise VoltageRuleError(f"classes[{k}] must be an object")
        name = _check_class_name(c.get("name"), f"classes[{k}]")
        if name in volts:
            raise VoltageRuleError(f"net class {name!r} listed twice")
        volts[name] = potential_range(c.get("voltage"), f"classes[{k}].voltage")

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
            voltage = overrides.get(key, working_voltage(volts[a], volts[b]))
            source = "pair" if key in overrides else "difference"
            plan.append(_entry(a, b, voltage, source, rows))
    if other_nets_voltage is not None:
        other = potential_range(other_nets_voltage, "otherNetsVoltage")
        for a in names:
            plan.append(_entry(a, None, working_voltage(volts[a], other), "other nets", rows))
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


def render_block(
    plan: List[Dict[str, Any]], all_classes: Sequence[str], exclude_unconnected: bool = False
) -> str:
    """The managed block for *plan*.

    ``exclude_unconnected`` leaves KiCad's ``unconnected-(R1-Pad2)`` nets (unwired
    pins) out of the "other nets" rules. Off by default: an unwired pin of a
    low-voltage IC sits near that IC's potential through its ESD diodes, so it
    needs the full spacing from a high-voltage track. It is for boards where the
    unwired pins near the high-voltage copper belong to the high-voltage parts
    themselves, which otherwise get held to the full spacing from their own pads.
    """
    lines = [BEGIN]
    for e in plan:
        a = e["a"]
        if e["b"] == "(other nets)":
            others = " || ".join(f"B.hasNetclass('{c}')" for c in all_classes)
            condition = f"A.hasNetclass('{a}') && !({others})"
            if exclude_unconnected:
                condition += f" && B.NetName != '{UNCONNECTED}'"
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
