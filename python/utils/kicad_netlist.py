"""KiCad's own netlist for a schematic, from ``kicad-cli sch export netlist``.

``sync_schematic_to_board`` used to build the pad-to-net map itself, by
following wires and labels geometrically. That diverges from KiCad wherever
KiCad's connectivity is richer than a label match:
- a net that changes name across a sheet boundary (local label ``CANH`` on the
  root, sheet pin and hierarchical label ``CAN_H`` below) stayed two nets;
- names came out flat (``SWDIO``, not ``/MCU/SWDIO``);
- a label in the middle of a wire did not reach the pins at its ends.

On a 77-part, 9-sheet board this put 224 pads on the wrong net, while the tool
reported success. KiCad's netlist is the reference KiCad itself uses when it
updates a PCB, so this module reads it: components with their symbol paths,
fields and flags, and every net with its pins, including KiCad's
``unconnected-(R1-Pad1)`` nets for unwired pins.

The S-expression format (``kicadsexpr``) is read, not the XML one: the XML
writer unescapes net names, so a pin named ``ADC7/PB6`` gives
``Net-(U2-ADC7/PB6)`` there. Pcbnew and KiCad's parity check use the escaped
``Net-(U2-ADC7{slash}PB6)``, and a board built from the XML names fails parity on
every such net.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("kicad_interface")

SExpr = Union[str, List["SExpr"]]

# What KiCad's writer puts after a backslash inside a quoted token, and the
# character it stands for. Any other escaped character keeps its backslash,
# as KiCad's own lexer leaves it.
_UNESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


def parse_sexpr(text: str) -> SExpr:
    """Parse one S-expression into nested lists of strings.

    Quoted and bare atoms both become ``str``. KiCad's escapes inside quotes
    (``\\n``, ``\\r``, ``\\t``, ``\\"`` and ``\\\\``) are mapped back to the
    characters the writer escaped: a multi-line field value written as
    ``"line1\\nline2"`` comes back with its line feed, not as ``line1nline2``.
    """
    stack: List[List[SExpr]] = [[]]
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "(":
            stack.append([])
            i += 1
        elif c == ")":
            if len(stack) == 1:
                raise ValueError(f"unexpected ')' at offset {i}")
            done = stack.pop()
            stack[-1].append(done)
            i += 1
        elif c == '"':
            j = i + 1
            buf = []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    nxt = text[j + 1]
                    buf.append(_UNESCAPES.get(nxt, "\\" + nxt))
                    j += 2
                    continue
                buf.append(text[j])
                j += 1
            if j >= n:
                raise ValueError("unterminated string")
            stack[-1].append("".join(buf))
            i = j + 1
        elif c.isspace():
            i += 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"':
                j += 1
            stack[-1].append(text[i:j])
            i = j
    if len(stack) != 1 or len(stack[0]) != 1:
        raise ValueError("unbalanced or multiple top-level expressions")
    return stack[0][0]


def _children(node: Any, tag: str) -> List[List[Any]]:
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == tag]


def _child(node: Any, tag: str) -> Optional[List[Any]]:
    found = _children(node, tag)
    return found[0] if found else None


def _text(node: Any, tag: str, default: str = "") -> str:
    """The string value of ``(tag "value")`` under *node*."""
    c = _child(node, tag)
    if c is None or len(c) < 2 or not isinstance(c[1], str):
        return default
    return c[1]


@dataclass
class Netlist:
    #: One entry per symbol: reference, value, footprint, uuid (the symbol's),
    #: path (``/sheet-uuid/.../symbol-uuid``, what a PCB footprint links by),
    #: sheetname, sheetfile, fields ({name: value}), and the flags
    #: exclude_from_bom / dnp / exclude_from_board.
    components: List[Dict[str, Any]] = field(default_factory=list)
    #: (reference, pin number) -> net name, escaped as pcbnew writes it
    pad_nets: Dict[Tuple[str, str], str] = field(default_factory=dict)
    #: Net names in KiCad's order (net code)
    net_names: List[str] = field(default_factory=list)
    #: Sheet paths by name, e.g. "/", "/MCU/"
    sheets: List[str] = field(default_factory=list)


_FLAGS = ("exclude_from_bom", "dnp", "exclude_from_board")


def parse_netlist(text: str) -> Netlist:
    """Parse a ``kicadsexpr`` netlist (as written by ``kicad-cli``)."""
    root = parse_sexpr(text)
    if not isinstance(root, list) or not root or root[0] != "export":
        raise ValueError("not a KiCad netlist (expected (export ...))")
    out = Netlist()
    design = _child(root, "design")
    for sheet in _children(design, "sheet") if design else []:
        out.sheets.append(_text(sheet, "name"))
    components = _child(root, "components")
    for comp in _children(components, "comp") if components else []:
        sheetpath = _child(comp, "sheetpath")
        sheet_tstamps = _text(sheetpath, "tstamps", "/") if sheetpath else "/"
        # (tstamps) is the symbol UUID. KiCad 10 writes one; older exports could
        # join several (one per instance of a reused sheet). Keep the first.
        uuids = _text(comp, "tstamps").replace(",", " ").split()
        uuid = uuids[0] if uuids else ""
        props: Dict[str, Optional[str]] = {}
        for prop in _children(comp, "property"):
            props[_text(prop, "name")] = _text(prop, "value") if _child(prop, "value") else None
        fields: Dict[str, str] = {}
        flds = _child(comp, "fields")
        for f in _children(flds, "field") if flds else []:
            name = _text(f, "name")
            value = next((x for x in f[2:] if isinstance(x, str)), "")
            if name:
                fields[name] = value
        entry: Dict[str, Any] = {
            "reference": _text(comp, "ref"),
            "value": _text(comp, "value"),
            "footprint": _text(comp, "footprint"),
            "uuid": uuid,
            "path": (sheet_tstamps.rstrip("/") + "/" + uuid) if uuid else "",
            "sheetname": props.get("Sheetname") or "",
            "sheetfile": props.get("Sheetfile") or "",
            "fields": fields,
        }
        for flag in _FLAGS:
            entry[flag] = flag in props
        out.components.append(entry)
    nets = _child(root, "nets")
    for net in _children(nets, "net") if nets else []:
        name = _text(net, "name")
        out.net_names.append(name)
        for node in _children(net, "node"):
            out.pad_nets[(_text(node, "ref"), _text(node, "pin"))] = name
    return out


def export_netlist(kicad_cli: str, schematic_path: str, timeout: int = 60) -> Optional[Netlist]:
    """Run kicad-cli and parse the result. None when kicad-cli fails, with the reason logged."""
    with tempfile.TemporaryDirectory(prefix="kicad-netlist-") as tmp:
        out_path = Path(tmp) / "netlist.net"
        cmd = [
            kicad_cli,
            "sch",
            "export",
            "netlist",
            "--format",
            "kicadsexpr",
            "--output",
            str(out_path),
            schematic_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning(f"kicad-cli netlist export could not run: {exc}")
            return None
        if result.returncode != 0 or not out_path.exists():
            logger.warning(
                f"kicad-cli netlist export failed (exit {result.returncode}): "
                f"{(result.stderr or result.stdout).strip()[-500:]}"
            )
            return None
        try:
            return parse_netlist(out_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            logger.warning(f"kicad-cli netlist did not parse: {exc}")
            return None
