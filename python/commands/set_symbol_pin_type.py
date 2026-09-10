"""Change the electrical type (and graphic style) of pins in a .kicad_sym library.

The server can read pins (``list_symbol_pins``, ``batch_list_symbol_pins``) but
had no way to write them, so bulk fixes were done with ``sed`` over the whole
library file. That is unsafe for three reasons this module addresses:

* A blind substitution rewrites *every* matching pin in the file, including
  symbols the caller never meant to touch.
* ``sed`` cannot see which symbol or which pin number it is standing on, so
  "make only the shield pins passive" is not expressible.
* Nothing checks the replacement token. KiCad silently refuses to load a
  library containing an unknown pin type, and the error it reports points at
  the file, not at the pin.

Imported libraries are the usual reason to need this. Parts converted from
Eagle or pulled from SnapEDA arrive with every pin marked ``unspecified`` or
``bidirectional``; ERC then reports conflicts on nets that are electrically
fine, and the noise hides the real errors.

Two properties of the write matter as much as the parsing, because this is a
bulk edit over a file that may be megabytes of a user's part library:

* It is atomic. ``sed -i`` -- the thing being replaced -- writes a temporary
  file and renames it, so an interrupted run leaves either the old library or
  the new one. Anything that opens the target for truncation empties it before
  the first replacement byte is written, and then has nothing to restore.
* It preserves the file's newline style. Rewriting a library checked out with
  LF endings on a Windows host would turn a 32-pin edit into a diff touching
  every line of the file, which is unreviewable.

A timestamped copy of the library is kept in a sibling ``.mcp-backups/``
directory before it is rewritten, following the convention
``kicad_interface._auto_save_board`` already uses for boards (``.gitignore``
covers ``*-backups/``). Atomicity and the backup guard different failures:
the rename means a crash cannot leave a truncated library, but it does nothing
about an edit that succeeds and was not what the caller meant. Omitting
``symbols`` is the natural way to call this tool and flattens every pin in the
library, so that is the likely mistake, and a library that is not in git has no
other undo. The copy is best effort -- a library that cannot be backed up is
still edited, because refusing the requested edit over a failed backup helps
nobody.
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from utils.file_io import read_text_preserve_newline as _read_text
from utils.file_io import write_text_atomic as _write_text
from utils.pin_types import PIN_STYLES, PIN_TYPES
from utils.sexpr_format import match_paren

logger = logging.getLogger("kicad_interface")

_HEAD = re.compile(r"\(\s*([A-Za-z_][\w]*)")
# Whitespace after "(" is allowed here for the same reason _HEAD allows it: the
# walker finds these pins either way, and a stricter head regex would make them
# fall out of the loop silently -- neither changed nor reported.
_PIN_HEAD = re.compile(r"\(\s*pin\s+([A-Za-z_][\w]*)\s+([A-Za-z_][\w]*)")

#: Upper bound on the per-pin records returned in ``changes``. A whole-library
#: pass changes thousands of pins, and this is an MCP tool -- the response is
#: spent from the model's context window, so an uncapped list costs the caller
#: ~100k tokens on precisely the bulk operation the tool exists for.
#: ``changeCount`` always carries the true total and ``changesTruncated`` says
#: when the list was cut.
_MAX_REPORTED_CHANGES = 200

#: Timestamped copies kept per library in ``.mcp-backups/``, matching
#: ``kicad_interface._auto_save_backup_keep``.
_BACKUP_KEEP = 20


def _prune_backups(backup_dir: Path, base_name: str) -> None:
    """Keep only the most recent ``_BACKUP_KEEP`` copies of *base_name*."""
    try:
        entries = [p for p in backup_dir.iterdir() if p.name.startswith(base_name + ".")]
        entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for old in entries[_BACKUP_KEEP:]:
            try:
                old.unlink()
            except OSError:
                pass
    except OSError as e:
        logger.debug("Backup pruning skipped: %s", e)


def _backup(path: Path) -> Optional[Path]:
    """Copy *path* into a sibling ``.mcp-backups/``; return the copy, or None.

    Best effort by design: a system library in a read-only directory should
    still be editable by a caller who has permission to write it.
    """
    try:
        backup_dir = path.parent / ".mcp-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        dest = backup_dir / f"{path.name}.{stamp}"
        shutil.copy2(path, dest)
    except OSError as e:
        logger.warning("Could not back up %s before editing it: %s", path, e)
        return None
    _prune_backups(backup_dir, path.name)
    return dest


def _read_string(text: str, i: int) -> Tuple[Optional[str], int]:
    """Read the quoted token starting at or after *i*; return (value, end)."""
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    if i >= len(text) or text[i] != '"':
        return None, i
    out: List[str] = []
    i += 1
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            out.append(text[i + 1])
            i += 2
            continue
        if ch == '"':
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    return None, i


def _child_string(block: str, key: str) -> Optional[str]:
    """Value of a direct child list ``(key "value" ...)``, or None.

    Only direct children count: a pin's ``(name ...)`` must not be confused with
    the ``(name ...)`` of a font or an effects block nested inside it.
    """
    depth = 0
    in_string = False
    i = 0
    while i < len(block):
        ch = block[i]
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
            if depth == 2:
                m = _HEAD.match(block, i)
                if m and m.group(1) == key:
                    value, _ = _read_string(block, m.end())
                    if value is not None:
                        return value
        elif ch == ")":
            depth -= 1
        i += 1
    return None


def iter_library_pins(text: str) -> Iterator[Dict[str, Any]]:
    """Yield ``{"offset", "symbol", "unit"}`` for every pin in a .kicad_sym.

    ``symbol`` is the top-level symbol the pin belongs to; ``unit`` is the
    enclosing body sub-symbol (``R_0402_1_1``), which is where pins actually
    live. Walking with a stack rather than a regex keeps a pin attributed to
    its own symbol even though the two names differ.
    """
    depth = 0
    in_string = False
    stack: List[Tuple[int, Optional[str]]] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == ")":
            depth -= 1
            while stack and stack[-1][0] > depth:
                stack.pop()
            i += 1
            continue
        if ch != "(":
            i += 1
            continue
        depth += 1
        m = _HEAD.match(text, i)
        token = m.group(1) if m else ""
        if token == "symbol" and m:
            name, _ = _read_string(text, m.end())
            stack.append((depth, name))
        elif token == "pin" and stack:
            yield {"offset": i, "symbol": stack[0][1], "unit": stack[-1][1]}
        i += 1


def iter_library_symbols(text: str) -> Iterator[Dict[str, Optional[str]]]:
    """Yield ``{"name", "extends"}`` for every top-level symbol in a .kicad_sym.

    Which symbols a library contains and which symbols have pins are different
    questions, and the pin walk can only answer the second. A derived symbol --
    ``(symbol "R_Small_US" (extends "R_Small") ...)`` -- has no pins of its own
    by design, so learning names from the pins alone reports it as a name that
    is not in the library, which sends the caller hunting for a typo instead of
    telling them to edit the parent.
    """
    depth = 0
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == ")":
            depth -= 1
            i += 1
            continue
        if ch != "(":
            i += 1
            continue
        depth += 1
        m = _HEAD.match(text, i)
        if depth == 2 and m and m.group(1) == "symbol":
            name, _ = _read_string(text, m.end())
            end = match_paren(text, i)
            if end == -1:
                yield {"name": name, "extends": None}
                i += 1
                continue
            yield {"name": name, "extends": _child_string(text[i : end + 1], "extends")}
            # Skip the body: its sub-symbols are units, not top-level symbols.
            depth -= 1
            i = end + 1
            continue
        i += 1


def _pin_structure(text: str) -> List[Tuple[Optional[str], Optional[str]]]:
    """The (symbol, unit) of every pin, in file order."""
    return [(p["symbol"], p["unit"]) for p in iter_library_pins(text)]


def _splice(text: str, edits: List[Tuple[int, int, str]]) -> str:
    """Apply *edits* -- ascending, non-overlapping ``(start, stop, text)`` -- at once.

    Rebuilding the string once instead of slicing it per edit is what makes a
    whole-library pass finish. ``text[:start] + new + text[stop:]`` in a loop
    copies the entire file for every pin, so the cost grows with pins times file
    size: on KiCad's 16 MB MCU_ST_STM32H7 (28191 pins) that is ~440 GB of
    copying, measured at 169 s, against ~8 s for a single join.
    """
    parts: List[str] = []
    cursor = 0
    for start, stop, replacement in edits:
        parts.append(text[cursor:start])
        parts.append(replacement)
        cursor = stop
    parts.append(text[cursor:])
    return "".join(parts)


def _edits_landed(updated: str, edits: List[Tuple[int, int, str]]) -> bool:
    """True if every replacement sits where splicing should have put it.

    ``edits`` is in ascending offset order, so each replacement ends up at its
    own offset displaced by the total length change of the edits before it --
    ``(pin unspecified line`` is four characters longer than
    ``(pin passive line``. If the offsets are not ascending they slide under
    each other and the replacements land inside neighbouring tokens.
    """
    shift = 0
    for start, stop, replacement in edits:
        if not updated.startswith(replacement, start + shift):
            return False
        shift += len(replacement) - (stop - start)
    return True


def _root_token(text: str) -> Optional[str]:
    m = _HEAD.search(text)
    return m.group(1) if m else None


def _as_set(value: Any) -> Optional[Set[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        return {value}
    return {str(v) for v in value}


def _pinless_advice(name: str, extends: Optional[str]) -> str:
    """Why a symbol that exists contributed no pins, and what to do about it."""
    if extends:
        return f"{name} extends {extends} and has no pins of its own -- edit {extends} instead"
    return f"{name} is in this library but has no pins"


def set_symbol_pin_type(params: Dict[str, Any]) -> Dict[str, Any]:
    """Set the electrical type and/or graphic style of pins in a symbol library."""
    lib_path = Path(params.get("libraryPath", ""))
    new_type = params.get("type")
    new_style = params.get("style")
    from_type = params.get("fromType")
    dry_run = bool(params.get("dryRun", False))

    if new_type is None and new_style is None:
        return {
            "success": False,
            "message": "Nothing to do: pass type, style, or both",
        }
    if new_type is not None and new_type not in PIN_TYPES:
        return {
            "success": False,
            "message": (
                f"'{new_type}' is not a KiCad pin type. KiCad refuses to load a "
                f"library containing one it does not know. Valid: {', '.join(PIN_TYPES)}"
            ),
            "validTypes": list(PIN_TYPES),
        }
    if new_style is not None and new_style not in PIN_STYLES:
        return {
            "success": False,
            "message": (
                f"'{new_style}' is not a KiCad pin graphic style. "
                f"Valid: {', '.join(PIN_STYLES)}"
            ),
            "validStyles": list(PIN_STYLES),
        }
    if from_type is not None and from_type not in PIN_TYPES:
        # Unvalidated, a transposed fromType ("unspecfied") matches no pin and
        # the call reports success having changed nothing -- the silent no-op
        # this tool exists to replace.
        return {
            "success": False,
            "message": (
                f"'{from_type}' is not a KiCad pin type, so fromType would match no pin "
                f"and report success having changed nothing. Valid: {', '.join(PIN_TYPES)}"
            ),
            "validTypes": list(PIN_TYPES),
        }

    if not lib_path.is_file():
        return {"success": False, "message": f"Library not found: {lib_path}"}

    try:
        text, newline = _read_text(lib_path)
    except OSError as e:
        return {"success": False, "message": f"Could not read {lib_path}: {e}"}

    root = _root_token(text)
    if root != "kicad_symbol_lib":
        return {
            "success": False,
            "message": (
                f"{lib_path.name} is not a symbol library "
                f"(root form is '{root}', expected 'kicad_symbol_lib')"
            ),
        }

    want_symbols = _as_set(params.get("symbols"))
    want_numbers = _as_set(params.get("pinNumbers"))
    want_names = _as_set(params.get("pinNames"))

    library_symbols: Dict[str, Optional[str]] = {}
    for entry in iter_library_symbols(text):
        entry_name = entry["name"]
        if entry_name is not None:
            library_symbols.setdefault(entry_name, entry["extends"])

    seen_symbols: Set[str] = set()
    seen_numbers: Set[str] = set()
    seen_names: Set[str] = set()
    touched_symbols: Set[str] = set()
    changes: List[Dict[str, Any]] = []
    edits: List[Tuple[int, int, str]] = []
    unchanged = 0
    backup_path: Optional[Path] = None

    for pin in iter_library_pins(text):
        symbol = pin["symbol"]
        if symbol:
            seen_symbols.add(symbol)
        if want_symbols is not None and symbol not in want_symbols:
            continue

        head = _PIN_HEAD.match(text, pin["offset"])
        if not head:
            logger.warning(
                "%s: the pin at offset %d has no '(pin <type> <style>' head; leaving it alone",
                lib_path.name,
                pin["offset"],
            )
            continue
        cur_type, cur_style = head.group(1), head.group(2)

        end = match_paren(text, pin["offset"])
        if end == -1:
            return {
                "success": False,
                "message": (
                    f"Unbalanced parentheses in {lib_path.name}: the pin at offset "
                    f"{pin['offset']} is never closed. Refusing to write."
                ),
            }
        block = text[pin["offset"] : end + 1]
        number = _child_string(block, "number") or ""
        name = _child_string(block, "name") or ""

        if number:
            seen_numbers.add(number)
        if name:
            seen_names.add(name)
        if want_numbers is not None and number not in want_numbers:
            continue
        if want_names is not None and name not in want_names:
            continue
        if from_type is not None and cur_type != from_type:
            continue

        to_type = new_type or cur_type
        to_style = new_style or cur_style
        if to_type == cur_type and to_style == cur_style:
            unchanged += 1
            continue

        edits.append((head.start(), head.end(), f"(pin {to_type} {to_style}"))
        if symbol:
            touched_symbols.add(symbol)
        if len(changes) < _MAX_REPORTED_CHANGES:
            changes.append(
                {
                    "symbol": symbol,
                    "unit": pin["unit"],
                    "number": number,
                    "name": name,
                    "fromType": cur_type,
                    "toType": to_type,
                    "fromStyle": cur_style,
                    "toStyle": to_style,
                }
            )

    if want_symbols:
        missing_symbols = sorted(want_symbols - set(library_symbols))
        pinless_symbols = sorted((want_symbols & set(library_symbols)) - seen_symbols)
    else:
        missing_symbols = []
        pinless_symbols = []
    missing_numbers = sorted(want_numbers - seen_numbers) if want_numbers else []
    missing_names = sorted(want_names - seen_names) if want_names else []

    if edits and not dry_run:
        updated = _splice(text, edits)
        # A paren count cannot move here -- the replacement is always
        # "(pin <token> <token>" and neither token can contain one -- so counting
        # them proves nothing. These two check the post-condition that actually
        # matters: each splice sits where its offset said, and the file still
        # holds the same pins under the same symbols.
        if not _edits_landed(updated, edits) or _pin_structure(updated) != _pin_structure(text):
            return {
                "success": False,
                "message": "Internal error: the edit changed the file structure. Nothing written.",
            }
        backup_path = _backup(lib_path)
        try:
            _write_text(lib_path, updated, newline)
        except OSError as e:
            return {
                "success": False,
                "message": (
                    f"Could not write {lib_path}: {e}. The library is unchanged -- the new "
                    "text is built in a temporary file that only replaces the original once "
                    "it is complete."
                ),
            }

        # The file is already on disk, so a cache that refuses to clear must not
        # turn a successful write into a reported failure -- the caller would
        # retry an edit that has in fact happened.
        try:
            from commands.symbol_creator import _invalidate_symbol_caches

            _invalidate_symbol_caches()
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Symbol caches not invalidated after pin edit: %s", e)

    total_changes = len(edits)
    touched = sorted(touched_symbols)
    if total_changes:
        verb = "Would change" if dry_run else "Changed"
        message = f"{verb} {total_changes} pin(s) across {len(touched)} symbol(s)"
    elif missing_symbols:
        message = f"No pins changed: symbol(s) not in this library: {', '.join(missing_symbols)}"
    elif pinless_symbols:
        message = "No pins changed: " + "; ".join(
            _pinless_advice(name, library_symbols.get(name)) for name in pinless_symbols
        )
    elif unchanged:
        message = f"No pins changed: all {unchanged} matching pin(s) already have that type"
    elif missing_numbers or missing_names:
        absent = []
        if missing_numbers:
            absent.append(f"pin number(s) {', '.join(missing_numbers)}")
        if missing_names:
            absent.append(f"pin name(s) {', '.join(missing_names)}")
        message = f"No pins changed: no {' or '.join(absent)} in the symbols searched"
    else:
        message = "No pins matched the given filters"

    return {
        "success": True,
        "message": message,
        "libraryPath": str(lib_path),
        "dryRun": dry_run,
        "changeCount": total_changes,
        "alreadyCorrect": unchanged,
        "symbolsChanged": touched,
        "backupPath": str(backup_path) if backup_path else None,
        "changes": changes,
        "changesTruncated": total_changes > len(changes),
        "missingSymbols": missing_symbols,
        "symbolsWithoutOwnPins": pinless_symbols,
        "missingPinNumbers": missing_numbers,
        "missingPinNames": missing_names,
    }
