"""
Freerouting autoroute integration for KiCAD MCP Server.

Exports the board to Specctra DSN format, runs Freerouting CLI,
and imports the routed SES file back into the board.

Supports two execution modes:
  - Direct: java -jar freerouting.jar (Java version read from the JAR; 2.x needs 21+)
  - Docker: docker run eclipse-temurin:<that version>-jre (requires Docker)
"""

import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from utils.project_netclasses import apply_net_classes_to_board, load_project_net_classes
from utils.project_settings_guard import preserve_project_settings

logger = logging.getLogger("kicad_interface")

# Default Freerouting JAR location
DEFAULT_FREEROUTING_JAR = os.environ.get(
    "FREEROUTING_JAR",
    os.path.join(os.path.expanduser("~"), ".kicad-mcp", "freerouting.jar"),
)

# Java release a Freerouting 2.x JAR needs when it cannot be read from the JAR itself
DEFAULT_REQUIRED_JAVA = 21

# Default schedule of `-mp` (max passes) values used when ``attempts`` > 1.
# Cycles through a range that empirically produces enough variation between
# runs to surface a better result than any single fixed value. Ported from
# morningfire-pcb-automation/scripts/routing/freeroute_runner.py.
DEFAULT_PASS_SCHEDULE = [50, 60, 65, 70, 75, 80, 85, 90, 55, 95]


def _jar_required_java(jar_path: str) -> int:
    """Java release the Freerouting JAR was compiled for.

    Read from the class-file major version of the JAR's Main-Class (Java release =
    major - 44). Freerouting 2.4.x targets Java 25 (major 69), so a fixed "21+"
    check passes a JRE that then dies with UnsupportedClassVersionError.
    Falls back to DEFAULT_REQUIRED_JAVA when the JAR cannot be read.
    """
    try:
        with zipfile.ZipFile(jar_path) as jar:
            manifest = jar.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
            main = next(
                line.split(":", 1)[1].strip()
                for line in manifest.splitlines()
                if line.startswith("Main-Class:")
            )
            header = jar.read(main.replace(".", "/") + ".class")[:8]
        if header[:4] == b"\xca\xfe\xba\xbe":
            return max(DEFAULT_REQUIRED_JAVA, int.from_bytes(header[6:8], "big") - 44)
    except Exception:
        pass
    return DEFAULT_REQUIRED_JAVA


def _docker_image(required_java: int) -> str:
    """Temurin JRE image for the Java release the Freerouting JAR needs (never below 21)."""
    return f"eclipse-temurin:{max(required_java, DEFAULT_REQUIRED_JAVA)}-jre"


def _find_java(required: int = DEFAULT_REQUIRED_JAVA) -> Optional[str]:
    """Find a java executable, preferring one that runs Java ``required``+.

    The first hit is often unusable: on macOS ``/usr/bin/java`` is a stub that
    exists with no JRE installed, and a Homebrew JDK is keg-only (not on PATH).
    Falls back to the first executable found so callers can report its version.
    """
    candidates: List[str] = []
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        # shutil.which resolves java.exe on Windows through PATHEXT; a bare
        # os.path.join(JAVA_HOME, "bin", "java") never exists there.
        home_java = shutil.which("java", path=os.path.join(java_home, "bin"))
        if home_java:
            candidates.append(home_java)
    which = shutil.which("java")
    if which:
        candidates.append(which)
    candidates += [
        "/opt/homebrew/opt/openjdk/bin/java",
        "/usr/local/opt/openjdk/bin/java",
        "/usr/bin/java",
        "/usr/local/bin/java",
    ]
    found = [c for c in dict.fromkeys(candidates) if c == which or os.path.isfile(c)]
    for candidate in found:
        if _java_version_ok(candidate, required):
            return candidate
    return found[0] if found else None


def _api_ok(result: Any) -> bool:
    """True when a pcbnew Specctra export/import call reports success.

    ``ExportSpecctraDSN``/``ImportSpecctraSES`` return a bool (``0`` on some older
    builds). Because ``False == 0`` in Python, the previous
    ``result is not True and result != 0`` check read a failed call as success.
    """
    return result is True or (type(result) is int and result == 0)


def _sexpr_end(text: str, start: int) -> int:
    """Index just past the parenthesised expression that opens at ``text[start]``.

    Parentheses inside double-quoted strings are ignored (Specctra files quote
    names with ``"``, and a component or net name may contain a paren). Returns
    -1 when the expression never closes.
    """
    depth = 0
    in_string = False
    for i in range(start, len(text)):
        ch = text[i]
        if ch == '"':
            in_string = not in_string
        elif in_string:
            continue
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


# One DSN name token: quoted (as KiCad writes names that need it) or bare.
DSN_NAME = r'"[^"]*"|[^\s()"]+'
_DSN_NEEDS_QUOTE_RE = re.compile(r"[\t ()%{}]")


def dsn_unquote(token: str) -> str:
    """The name a DSN token stands for: the surrounding quotes removed, if any."""
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        return token[1:-1]
    return token


def dsn_quote(name: str) -> str:
    """Write ``name`` the way KiCad's Specctra export does: in quotes when it has to be.

    KiCad (``OUTPUTFORMATTER::GetQuoteChar``) quotes an empty name, a name starting with
    ``#``, one containing a tab, a space, a parenthesis, ``%``, ``{`` or ``}``, and one
    with ``-`` anywhere but first. So ``F.Cu`` and ``In1.Cu`` stay bare, while
    ``"Bottom side"``, ``"GND-plane"`` and ``"Net-(C5-Pad1)"`` are quoted; the Specctra
    parser would otherwise read ``Bottom side`` as the layer ``Bottom`` plus a stray
    token. Checked against KiCad 10.0.8's export.
    """
    if not name or name[0] == "#" or _DSN_NEEDS_QUOTE_RE.search(name) or "-" in name[1:]:
        return f'"{name}"'
    return name


_DSN_NAME_RE = re.compile(DSN_NAME)


def net_selector(route_nets: Iterable[str], exclude_nets: Iterable[str]):
    """A predicate for net names from include and exclude glob lists.

    Empty ``route_nets`` means every net; ``exclude_nets`` then removes some.
    """
    import fnmatch

    include = [str(p) for p in route_nets or []]
    exclude = [str(p) for p in exclude_nets or []]

    def keep(name: str) -> bool:
        if include and not any(fnmatch.fnmatchcase(name, p) for p in include):
            return False
        return not any(fnmatch.fnmatchcase(name, p) for p in exclude)

    return keep


def filter_dsn_nets(dsn_text: str, keep) -> Tuple[str, List[str]]:
    """Drop the nets ``keep`` rejects from a Specctra DSN's (network) section.

    Freerouting routes every net in (network). Removing a net's (net ...) block leaves
    its pads and existing copper on the board as obstacles but gives the router nothing
    to connect for it. So a board can be routed one domain at a time: the pack-side nets
    first, inside their own region, then the logic nets, without either crossing the
    other's isolation gap. The (class ...) lists are left alone: Freerouting's
    ``Network.insert_net_class`` looks each member up with ``nets.get(name)`` and skips a
    name it does not know, and KiCad's auto-generated names such as ``"Net-(C5-Pad1)"``
    contain parentheses that a rewrite would have to parse. Returns the new text and the
    names removed.
    """
    m = re.search(r"\(network(?=[\s)])", dsn_text)
    if not m:
        return dsn_text, []
    start = m.start()
    end = _sexpr_end(dsn_text, start)
    if end < 0:
        return dsn_text, []
    body = dsn_text[start:end]
    out: List[str] = []
    removed: List[str] = []
    i = len("(network")
    out.append(body[:i])
    while i < len(body):
        j = body.find("(", i)
        if j < 0:
            out.append(body[i:])
            break
        out.append(body[i:j])
        k = _sexpr_end(body, j)
        if k < 0:
            out.append(body[j:])
            break
        child = body[j:k]
        head = re.match(r"\(net\s+", child)
        if head:
            name = dsn_unquote(_DSN_NAME_RE.match(child, head.end()).group(0))
            if not keep(name):
                removed.append(name)
                i = k
                # Drop the line break and indent the block leaves behind.
                while i < len(body) and body[i] in " \t":
                    i += 1
                if i < len(body) and body[i] == "\n":
                    i += 1
                continue
        out.append(child)
        i = k
    text = dsn_text[:start] + "".join(out) + dsn_text[end:]
    return _wiring_of_removed_nets_as_keepouts(text, set(removed)), removed


def _wiring_of_removed_nets_as_keepouts(dsn_text: str, removed) -> str:
    """Turn the existing wires and vias of left-out nets into keepouts.

    A wire whose (net ...) is no longer in (network) is dropped by Freerouting, so the
    copper of a left-out net was invisible to the router: a logic pass routed straight
    through the pack nets' tracks (79 shorts on a real board). Each such wire becomes a
    (keepout "" (path LAYER WIDTH ...)) and each via a circle keepout on every copper
    layer, in the (structure) section; their pads were already obstacles. Layer names
    are taken as the DSN writes them (quoted when KiCad quotes them, see
    :func:`dsn_quote`). KiCad exports an arc as its straight chord, so the keepout of an
    arc misses the bulge; the board keeps the arc itself (see
    :func:`_lock_tracks_of_nets`).
    """
    if not removed:
        return dsn_text
    w = re.search(r"\(wiring(?=[\s)])", dsn_text)
    st = re.search(r"\(structure(?=[\s)])", dsn_text)
    if not w or not st:
        return dsn_text
    w_end = _sexpr_end(dsn_text, w.start())
    if w_end < 0 or _sexpr_end(dsn_text, st.start()) < 0:
        return dsn_text
    layers = [dsn_quote(name) for name in _dsn_layer_names(dsn_text)]
    diam = {}
    for m in re.finditer(r"\(padstack\s+(" + DSN_NAME + ")", dsn_text):
        e = _sexpr_end(dsn_text, m.start())
        c = re.search(r"\(circle\s+(?:" + DSN_NAME + r")\s+([\d.]+)", dsn_text[m.start() : e])
        if c:
            diam[dsn_unquote(m.group(1))] = c.group(1)
    body = dsn_text[w.start() : w_end]
    kept, keepouts = [], []
    i = len("(wiring")
    kept.append(body[:i])
    while i < len(body):
        j = body.find("(", i)
        if j < 0:
            kept.append(body[i:])
            break
        kept.append(body[i:j])
        k = _sexpr_end(body, j)
        if k < 0:
            kept.append(body[j:])
            break
        child = body[j:k]
        net = re.search(r"\(net\s+(" + DSN_NAME + r")\)", child)
        if net and dsn_unquote(net.group(1)) in removed:
            path = re.search(r"\(path\s+(" + DSN_NAME + r")\s+([\d.]+)\s+([^()]*)\)", child)
            via = re.match(r"\(via\s+(" + DSN_NAME + r")\s+([-\d.]+)\s+([-\d.]+)", child)
            if path:
                keepouts.append(
                    f'    (keepout "" (path {path.group(1)} {path.group(2)} '
                    f"{path.group(3).strip()}))"
                )
            elif via and dsn_unquote(via.group(1)) in diam:
                d = diam[dsn_unquote(via.group(1))]
                for layer in layers:
                    keepouts.append(
                        f'    (keepout "" (circle {layer} {d} {via.group(2)} {via.group(3)}))'
                    )
            i = k
            while i < len(body) and body[i] in " \t":
                i += 1
            if i < len(body) and body[i] == "\n":
                i += 1
            continue
        kept.append(child)
        i = k
    text = dsn_text[: w.start()] + "".join(kept) + dsn_text[w_end:]
    return _append_to_structure(text, keepouts)


_PLACEMENT_RE = re.compile(r"\(placement(?=[\s)])")
_PLACE_RE = re.compile(r'\(place\s+("[^"]*"|[^\s()]+)')


def _strip_ses_placement(ses_text: str) -> str:
    """Drop the SES ``(placement ...)`` block before import.

    ``ImportSpecctraSES`` looks up every placed component by reference and aborts
    the whole import (returning False) when one is missing, for example when the
    DSN export renamed duplicate ``REF**`` references to ``REF**_1``,
    ``REF**_2``. Used by ``autoroute``, whose headless Freerouting run never moves
    parts, so the block carries nothing the import needs. ``import_ses`` handles
    SES files that may come from Freerouting's GUI, where parts can be moved, and
    uses :func:`_prune_ses_placement` instead.
    """
    m = _PLACEMENT_RE.search(ses_text)
    if not m:
        return ses_text
    end = _sexpr_end(ses_text, m.start())
    if end < 0:
        return ses_text
    return ses_text[: m.start()] + ses_text[end:]


def _prune_ses_placement(ses_text: str, board_refs: Iterable[str]) -> Tuple[str, List[str]]:
    """Drop only the placement entries KiCad cannot resolve.

    Keeps every ``(place <ref> ...)`` whose reference occurs exactly once on the
    board, so a part moved or flipped in Freerouting's GUI is still applied, and
    drops the entries naming a reference that is missing from the board or not
    unique on it (either would abort the whole import). A ``(component ...)``
    group left without entries is dropped too. Returns the text and the dropped
    references.
    """
    m = _PLACEMENT_RE.search(ses_text)
    if not m:
        return ses_text, []
    block_end = _sexpr_end(ses_text, m.start())
    if block_end < 0:
        return ses_text, []

    counts: Dict[str, int] = {}
    for ref in board_refs:
        counts[ref] = counts.get(ref, 0) + 1

    block = ses_text[m.start() : block_end]
    dropped: List[str] = []
    out: List[str] = []
    pos = 0
    for comp in re.finditer(r"\(component(?=[\s)])", block):
        if comp.start() < pos:
            continue  # nested inside a component group already handled
        comp_end = _sexpr_end(block, comp.start())
        if comp_end < 0:
            break
        group = block[comp.start() : comp_end]
        kept_parts: List[str] = []
        gpos = 0
        kept_any = False
        for place in _PLACE_RE.finditer(group):
            if place.start() < gpos:
                continue
            place_end = _sexpr_end(group, place.start())
            if place_end < 0:
                break
            ref = place.group(1).strip('"')
            kept_parts.append(group[gpos : place.start()])
            if counts.get(ref, 0) == 1:
                kept_parts.append(group[place.start() : place_end])
                kept_any = True
            else:
                dropped.append(ref)
            gpos = place_end
        kept_parts.append(group[gpos:])
        out.append(block[pos : comp.start()])
        if kept_any:
            out.append("".join(kept_parts))
        pos = comp_end
    out.append(block[pos:])
    if not dropped:
        return ses_text, []
    return ses_text[: m.start()] + "".join(out) + ses_text[block_end:], dropped


def _lock_tracks_of_nets(board, nets) -> List[Tuple[Any, bool]]:
    """Lock every track, arc and via of ``nets``; returns (item, lock state before) pairs.

    ImportSpecctraSES removes the board's unlocked tracks and adds the session's wires,
    but keeps locked ones (checked on KiCad 10.0.8: tracks, vias and arcs stay, with
    their UUIDs). A session from a DSN with nets left out (routeNets / excludeNets)
    holds none of their wires, so importing it erased their routing: routing in passes
    (logic first, then the pack nets) kept only the last pass (600 tracks to 66 on a
    real board). Locking them for the import keeps them exactly as they were, arcs,
    UUIDs and group membership included; :func:`_restore_lock_states` puts the lock
    flags back afterwards.
    """
    nets = set(nets)
    locked: List[Tuple[Any, bool]] = []
    for t in board.GetTracks():
        if t.GetNetname() in nets:
            locked.append((t, bool(t.IsLocked())))
            t.SetLocked(True)
    return locked


def _restore_lock_states(locked: Iterable[Tuple[Any, bool]]) -> int:
    """Put back the lock flags recorded by _lock_tracks_of_nets; returns how many."""
    n = 0
    for item, was_locked in locked:
        item.SetLocked(was_locked)
        n += 1
    return n


_TRACKS_CLEARED_NOTE = (
    "An SES import that fails after parsing has usually already removed the "
    "board's unlocked tracks, so the board in memory may have lost them; nothing "
    "was saved. Reopen the board from disk before saving or routing again."
)


_DSN_KEEPOUT_RE = re.compile(r'(\(keepout "[^"]*" \(polygon signal 0\s+)([-\d.\s]+?)(\))')
_DSN_LAYER_RE = re.compile(r"\(layer\s+(" + DSN_NAME + r")\s*\(type\s+(\w+)\)")


def _dsn_layer_names(dsn_text: str) -> List[str]:
    """The layers of the DSN's (structure), in order, by the names KiCad wrote (unquoted).

    The DSN uses the board's own layer names (``Top`` for a renamed F.Cu), quoted when
    they need it (``"GND plane"``).
    """
    st = re.search(r"\(structure(?=[\s)])", dsn_text)
    if not st:
        return []
    end = _sexpr_end(dsn_text, st.start())
    block = dsn_text[st.start() : end if end > 0 else len(dsn_text)]
    return [dsn_unquote(m.group(1)) for m in _DSN_LAYER_RE.finditer(block)]


def _board_layer_names(board, names: Iterable[Any]) -> List[str]:
    """Translate layer names (canonical ``F.Cu`` or the board's own) to the board's names.

    The DSN carries the board's names, so a canonical name has to go through the board:
    with F.Cu renamed to ``Top``, ``"F.Cu"`` must restrict ``Top``, not silently nothing.
    Raises ValueError for a name that is not an enabled copper layer of the board.
    """
    import pcbnew

    enabled = [board.GetLayerName(lid) for lid in board.GetEnabledLayers().CuStack()]
    out: List[str] = []
    for name in names:
        lid = board.GetLayerID(str(name))
        board_name = board.GetLayerName(lid) if lid >= 0 and pcbnew.IsCopperLayer(lid) else None
        if board_name is None or board_name not in enabled:
            raise ValueError(
                f"{name!r} is not a copper layer of this board (its copper layers: {enabled})"
            )
        out.append(board_name)
    return out


def _signal_layer_rules(
    dsn_text: str,
    signal_layers: List[str],
    trace_costs: Optional[Dict[str, float]] = None,
    design_name: str = "kicad-mcp",
) -> Tuple[Optional[str], List[str]]:
    """Freerouting rules text that keeps tracks off every copper layer not in ``signal_layers``.

    KiCad exports every copper layer as ``(type signal)``, so Freerouting runs tracks across
    inner plane layers and cuts them into islands (found on a 4-layer board: In2 in 7 pieces,
    26 plane pads open). The rules file's ``autoroute_settings`` carries a ``layer_rule`` per
    restricted layer with ``(active off)``: an inactive layer gets no traces, vias still pass.

    A board-sized ``wire_keepout`` looks equivalent but is not: Freerouting 2.5's fanout
    stage still runs, but ``DrillPage`` excludes the keepout area from its via candidates,
    so no via can be placed anywhere on the board (A/B on the same DSN: 0 vias, 111 unrouted
    with the keepout; fanout 244/304 pins without it). ``(type power)`` keeps vias but
    switches on power-plane validation of the layer.

    ``trace_costs`` (layer -> factor, e.g. {"In1.Cu": 5}) keeps a layer usable but makes
    traces there cost more, for a plane layer that may carry the odd track where nothing
    else fits: that layer's trace costs are written as the factor along its preferred
    direction and twice that against it (Freerouting's own defaults are 1 along and 1 plus
    the board's aspect ratio against, plus 0.2 per signal layer on the outer layers of a
    board with more than two).

    The file holds only what was asked for. Freerouting reads each ``layer_rule`` key on
    its own, and an explicit value replaces the per-layer default it would otherwise
    compute (``RouterSettings.applyBoardSpecificOptimizations``: preferred directions from
    the board's aspect ratio, the outer-layer surcharge); a layer that is neither
    restricted nor costed therefore gets no rule, and there are no top-level cost settings.

    Both lists must use the names the DSN uses (the board's own; see
    :func:`_board_layer_names`). Raises ValueError for a name that is not a layer of the
    DSN, so a typo cannot silently restrict the wrong layers. Returns (rules text,
    restricted layers); (None, []) when nothing would be restricted or costed.
    """
    costs = {str(k): float(v) for k, v in (trace_costs or {}).items()}
    wanted = [str(n) for n in signal_layers or []]
    if not (wanted or costs):
        return None, []
    layers = _dsn_layer_names(dsn_text)
    unknown = [n for n in wanted + list(costs) if n not in layers]
    if unknown:
        raise ValueError(f"not a layer of this board's DSN: {unknown} (DSN layers: {layers})")
    restricted = [name for name in layers if wanted and name not in wanted]
    rules = []
    for name in layers:
        if name in restricted:
            rules.append(f"    (layer_rule {dsn_quote(name)} (active off))\n")
        elif name in costs:
            k = costs[name]
            rules.append(
                f"    (layer_rule {dsn_quote(name)} (preferred_direction_trace_costs {k:g})"
                f" (against_preferred_direction_trace_costs {2 * k:g}))\n"
            )
    if not rules:
        return None, []
    # Freerouting checks the header's name against the DSN file's stem (a mismatch is
    # only logged).
    text = f"(rules PCB {dsn_quote(design_name)}\n  (autoroute_settings\n" + "".join(rules)
    return text + "  )\n)\n", restricted


def _grow_hole_keepouts(dsn_text: str, grow_um: float) -> str:
    """Enlarge circular board-level keepouts (Edge.Cuts holes) by ``grow_um``.

    KiCad exports internal Edge.Cuts circles (mounting holes, cut-outs) as plain
    keepouts, which Freerouting clears by the ordinary track clearance only — so
    routes land well inside the board's copper-to-edge clearance. Non-circular
    keepouts are left untouched.
    """
    if grow_um <= 0:
        return dsn_text

    def _repl(m: "re.Match[str]") -> str:
        nums = [float(v) for v in m.group(2).split()]
        pts = list(zip(nums[0::2], nums[1::2]))
        if len(set(pts)) < 12:  # KiCad polygonises circles finely; rectangles are 4-5 points
            return m.group(0)
        # bbox centre: vertex averages are skewed by uneven arc steps and the closing point
        cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
        cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
        radii = [((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 for x, y in pts]
        if min(radii) <= 0 or max(radii) / min(radii) > 1.05:
            return m.group(0)
        r = sum(radii) / len(radii)
        n = len(set(pts))
        # a polygon's edges sit inside its vertices: size it so the apothem clears r + grow
        k = (r + grow_um) / math.cos(math.pi / n) / r
        grown = "  ".join(f"{cx + (x - cx) * k:.1f} {cy + (y - cy) * k:.1f}" for x, y in pts)
        return f"{m.group(1)}{grown}{m.group(3)}"

    return _DSN_KEEPOUT_RE.sub(_repl, dsn_text)


def _find_docker() -> Optional[str]:
    """Find docker executable on the system."""
    return shutil.which("docker") or shutil.which("podman")


def _docker_available() -> bool:
    """Check if Docker/Podman is available and running."""
    docker = _find_docker()
    if not docker:
        return False
    try:
        proc = subprocess.run(
            [docker, "info"],
            capture_output=True,
            timeout=10,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _java_version_ok(java_exe: str, required: int = DEFAULT_REQUIRED_JAVA) -> bool:
    """Check if local Java is version ``required``+."""
    try:
        proc = subprocess.run(
            [java_exe, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = proc.stderr or proc.stdout
        # Parse version like: openjdk version "17.0.18"
        for line in output.split("\n"):
            if "version" in line:
                ver = line.split('"')[1] if '"' in line else ""
                major = int(ver.split(".")[0])
                return major >= required
    except Exception:
        pass
    return False


def _hms(seconds: int) -> str:
    """Seconds as HH:MM:SS, the form Freerouting's time settings take."""
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


# Wall-clock time Freerouting needs after its own time budget ends: up to its
# GRACE_PERIOD of 30 s for the router to stop (RoutingJobSchedulerActionThread,
# 2.4.1 and later), writing the session file, plus the JVM start and DSN load
# before the budget begins to count (measured 11-13 s past the budget).
_JOB_TIMEOUT_MARGIN_MIN = 60
_JOB_TIMEOUT_MARGIN_MAX = 120
# Freerouting logs this when a stage ended because the job's time was up.
_TIME_BUDGET_MARKER = "completed with timeout"
# Freerouting does not refuse a router setting it cannot apply: it logs one of
# these and keeps routing (master 842ad835, 2.5.0 CliSettings.applyRouterSetting):
#   WARN   Unknown settings property: router.bogus_setting
#   WARN   Failed to apply CLI router setting: router.bogus_setting: No field found ...
_REJECTED_SETTING_RE = re.compile(
    r"(?:Unknown settings property|Failed to apply CLI router setting): router\.([A-Za-z0-9_.]+)"
)


def _rejected_router_settings(output: str, router_args: Optional[List[str]]) -> List[str]:
    """The routerSettings keys Freerouting reported it could not apply, in the order passed.

    Only keys this call passed are reported (``--router.<key>=...`` in ``router_args``), so a
    warning about one of autoroute's own options cannot show up as the caller's mistake.
    """
    passed = []
    for arg in router_args or []:
        key = arg.split("=", 1)[0][len("--router.") :]
        if key and key not in passed:
            passed.append(key)
    named = set(_REJECTED_SETTING_RE.findall(output or ""))
    return [k for k in passed if k in named]


def _router_time_budget(timeout: Any, requested: Any) -> Optional[int]:
    """The time, in seconds, Freerouting is given to route (``--router.job_timeout``).

    ``timeout`` is how long the caller waits for the process. When that wait
    ends, the process is killed and nothing it routed is kept, because
    Freerouting writes the session file only at the end. So the router is told
    to stop earlier by itself: by default at ``timeout`` minus a margin of a
    tenth of it (at least 60 s, at most 120 s). No default budget is passed
    when it would be shorter than the margin itself (a ``timeout`` under
    120 s): it would cut off runs that finish within the wait, and be too
    short to give a useful partial result.

    ``requested`` is the caller's ``jobTimeout``: a number of seconds to use
    instead (capped below ``timeout`` by the same margin), or 0 to pass no
    time budget at all. Returns None when no budget is to be passed.
    """
    try:
        wait = float(timeout)
    except (TypeError, ValueError):
        return None
    if requested is not None:
        try:
            asked = float(requested)
        except (TypeError, ValueError):
            asked = -1.0
        if asked == 0:
            return None
    else:
        asked = -1.0
    margin = min(_JOB_TIMEOUT_MARGIN_MAX, max(_JOB_TIMEOUT_MARGIN_MIN, wait * 0.1))
    ceiling = wait - margin
    if asked > 0:
        budget = min(asked, ceiling)
    elif ceiling >= margin:
        budget = ceiling
    else:
        return None
    return int(budget) if budget >= 1 else None


# A Freerouting setting key: lower-case words joined by dots, as in its docs/settings.md
# ("autorouter.priority_net_classes"). Nothing else, so a key cannot smuggle in another option.
# Used with fullmatch: "$" would also accept a key ending in a newline.
_ROUTER_SETTING_KEY = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*")
# Settings autoroute sets itself; a caller's value would silently fight it.
_ROUTER_SETTINGS_OWNED = {
    "job_timeout": "jobTimeout",
    "max_passes": "maxPasses",
    "autorouter.max_passes": "maxPasses",
}
# The thread count, in each spelling Freerouting master reads (docs/settings.md: the global
# ceiling, and the autorouter and optimizer stages). With attempts > 1 autoroute forces -mt 1:
# the attempts are compared, and the multi-threaded optimiser is the one known to leave
# clearance violations, so a caller's value must not undo it.
_ROUTER_THREAD_SETTINGS = ("max_threads", "autorouter.max_threads", "optimizer.max_threads")


def _router_setting_args(settings: Any, single_thread: bool = False) -> List[str]:
    """``routerSettings`` as Freerouting command-line options.

    ``{"autorouter.priority_net_classes": ["DIFF", "ANALOG"], "autorouter.plane_as_priority": True}``
    becomes ``--router.autorouter.priority_net_classes=DIFF,ANALOG`` and
    ``--router.autorouter.plane_as_priority=true``. Keys are the names in Freerouting's
    docs/settings.md under ``router``. Raises ValueError for anything that is not a plain
    setting: a key of another shape, a value that is not a string, number, boolean or a list
    of those, or a setting that autoroute has a parameter of its own for. With
    ``single_thread`` (best-of-N attempts) the thread count is refused too.
    """
    if settings is None:
        return []
    if not isinstance(settings, dict):
        raise ValueError("routerSettings must be an object of setting name to value")
    args: List[str] = []
    for key, value in settings.items():
        if not isinstance(key, str) or not _ROUTER_SETTING_KEY.fullmatch(key):
            raise ValueError(
                f"routerSettings key {key!r} is not a Freerouting setting name "
                "(lower-case words joined by dots, e.g. autorouter.priority_net_classes)"
            )
        if key in _ROUTER_SETTINGS_OWNED:
            raise ValueError(
                f"routerSettings key {key!r}: use autoroute's {_ROUTER_SETTINGS_OWNED[key]} parameter"
            )
        if single_thread and key in _ROUTER_THREAD_SETTINGS:
            raise ValueError(
                f"routerSettings key {key!r}: with attempts above 1 autoroute runs Freerouting "
                "single-threaded (-mt 1) so the attempts are comparable; leave the thread count "
                "out, or use attempts: 1"
            )
        items = value if isinstance(value, (list, tuple)) else [value]
        if not items:
            raise ValueError(f"routerSettings {key!r}: empty list")
        parts = []
        for item in items:
            if isinstance(item, bool):
                parts.append("true" if item else "false")
            elif isinstance(item, (int, float)):
                parts.append(str(item))
            elif isinstance(item, str) and item and "\n" not in item:
                parts.append(item)
            else:
                raise ValueError(
                    f"routerSettings {key!r}: value {item!r} is not a string, number or boolean"
                )
        args.append(f"--router.{key}={','.join(parts)}")
    return args


def _no_budget_reason(timeout: Any, requested: Any) -> str:
    """Why no time budget was passed, for the message when the wait runs out."""
    try:
        asked = float(requested) if requested is not None else None
    except (TypeError, ValueError):
        asked = None
    if asked == 0:
        return "No time budget was passed to it (jobTimeout: 0)."
    if asked is not None and asked > 0:
        return (
            f"The jobTimeout of {requested}s was not passed: a timeout of {timeout}s is too "
            f"short to leave room for a budget (Freerouting needs at least "
            f"{_JOB_TIMEOUT_MARGIN_MIN}s after its budget ends to stop and write its result)."
        )
    return (
        f"No time budget was passed to it: a timeout under {2 * _JOB_TIMEOUT_MARGIN_MIN}s "
        "leaves no room for a useful one. A longer timeout gets a time budget, and with it "
        "a partial result."
    )


def _build_freerouting_cmd(
    jar_path: str,
    dsn_path: str,
    ses_path: str,
    passes: int,
    use_docker: bool,
    single_thread: bool = False,
    rules_path: Optional[str] = None,
    job_timeout: Optional[int] = None,
    router_args: Optional[List[str]] = None,
) -> List[str]:
    """Build the command to run Freerouting.

    ``job_timeout`` (seconds) is passed as ``--router.job_timeout=HH:MM:SS``:
    Freerouting then stops routing by itself when the time is up and still
    writes the session file with what it has routed.

    ``single_thread`` forces ``-mt 1`` (single-threaded optimisation).
    Freerouting 2.x's multi-threaded optimiser is documented to produce
    clearance violations in some cases (the runtime even prints a warning);
    best-of-N callers should pass this so each attempt's score reflects a
    valid routed board, not an artefact of MT optimisation.
    """
    extra = ["-mt", "1"] if single_thread else []
    if rules_path:
        extra += ["-dr", rules_path]
    if job_timeout:
        extra.append(f"--router.job_timeout={_hms(job_timeout)}")
    extra += list(router_args or [])
    required_java = _jar_required_java(jar_path)
    if use_docker:
        docker_exe = _find_docker()
        if docker_exe is None:
            raise RuntimeError("Docker/Podman executable not found")
        board_dir = os.path.dirname(dsn_path)
        dsn_name = os.path.basename(dsn_path)
        ses_name = os.path.basename(ses_path)
        jar_name = os.path.basename(jar_path)
        if rules_path:
            extra = [
                a if a != rules_path else f"/work/{os.path.basename(rules_path)}" for a in extra
            ]
        return [
            docker_exe,
            "run",
            "--rm",
            "-v",
            f"{jar_path}:/app/{jar_name}:ro",
            "-v",
            f"{board_dir}:/work",
            _docker_image(required_java),
            "java",
            "-jar",
            f"/app/{jar_name}",
            "-de",
            f"/work/{dsn_name}",
            "-do",
            f"/work/{ses_name}",
            "--gui.enabled=false",
            "-mp",
            str(passes),
            *extra,
        ]
    else:
        java_exe = _find_java(required_java)
        if java_exe is None:
            raise RuntimeError("Java executable not found")
        return [
            java_exe,
            "-jar",
            jar_path,
            "-de",
            dsn_path,
            "-do",
            ses_path,
            "--gui.enabled=false",
            "-mp",
            str(passes),
            *extra,
        ]


# ---------------------------------------------------------------------------
# Best-of-N scoring helpers (ported from morningfire-pcb-automation)
# ---------------------------------------------------------------------------
#
# Approach lifted from
#   https://github.com/NiNjA-CodE/morningfire-pcb-automation
#   scripts/routing/freeroute_runner.py::score_ses
#
# Single-shot Freerouting on dense boards routinely leaves 1–7 nets
# unrouted. Re-running with varied --max-passes values surfaces a better
# solution most of the time; the scoring function below picks the best
# SES across attempts.
# ---------------------------------------------------------------------------

_SES_NET_RE = re.compile(r"\(net\s+(\S+)\s*\n\s*\(wire")


def _describe_exit(code: Any) -> str:
    """Human-readable suffix for a Freerouting exit code (#249).

    A user cancelling the run (or an OOM killer, or a console close) surfaces
    as a raw process exit code -- on Windows a force-killed JVM reports
    4294967295 (0xFFFFFFFF), which reads like a Java failure rather than
    "someone stopped it". Decode the known shapes so the error message says
    what actually happened; return "" when the code carries no extra meaning.
    """
    if not isinstance(code, int):
        return ""
    # Windows NTSTATUS-shaped codes and POSIX negative-signal codes cannot
    # collide (POSIX exit codes are 0..255 or small negatives), so decode
    # both unconditionally rather than gating on os.name -- that also lets
    # the Linux CI exercise the Windows decodings.
    known_nt = {
        0xFFFFFFFF: "process was terminated externally (force-kill)",
        0xC000013A: "process was interrupted (Ctrl+C or console closed)",
        0xC0000005: "JVM crashed with an access violation",
    }
    desc = known_nt.get(code & 0xFFFFFFFF)
    if desc:
        return f" -- {desc}"
    if code < 0:
        import signal

        try:
            name = signal.Signals(-code).name
        except ValueError:
            name = str(-code)
        return f" -- process was killed by signal {name}"
    return ""


def _trim_shared_freerouting_log(max_bytes: int = 5 * 1024 * 1024) -> None:
    """Best-effort cap on Freerouting's own shared DEBUG log (#249).

    Freerouting 2.x writes an unbounded DEBUG log to a fixed path shared by
    every run (observed growing to 9+ MB in three runs). We cannot pass it a
    log level across all bundled JAR versions, so truncate the file when it
    exceeds the cap after a run. Failures (file locked, absent) are ignored.
    """
    try:
        log_path = Path(tempfile.gettempdir()) / "freerouting" / "freerouting.log"
        if log_path.is_file() and log_path.stat().st_size > max_bytes:
            with open(log_path, "w", encoding="utf-8"):
                pass
    except OSError:
        pass


def _score_ses(ses_text: str, target_nets: Iterable[str]) -> Dict[str, Any]:
    """Score a Specctra SES file by routing completeness.

    Score = (nets_routed * 1000) + segments + 50000_if_all_targets_routed

    The ``nets_routed * 1000`` term dominates segment count so an attempt
    that routes one more net always beats an attempt with marginally more
    segments. The target-net bonus is huge so any attempt that routes all
    critical nets wins, regardless of segment count.

    Returns: ``{"score": int, "nets": int, "segments": int, "vias": int,
                "targets_found": [...], "targets_missing": [...]}``
    """
    nets = set(_SES_NET_RE.findall(ses_text))
    # Strip wrapping quotes if Freerouting emits them.
    clean_nets = {n.strip('"') for n in nets}
    segments = len(re.findall(r"\(wire", ses_text))
    vias = len(re.findall(r"\(via ", ses_text))

    targets = set(target_nets) if target_nets else set()
    found = sorted(targets & clean_nets)
    missing = sorted(targets - clean_nets)

    score = len(clean_nets) * 1000 + segments
    if targets and not missing:
        score += 50_000

    return {
        "score": score,
        "nets": len(clean_nets),
        "segments": segments,
        "vias": vias,
        "targets_found": found,
        "targets_missing": missing,
    }


# SES net-name tokens are written as ``(net "NAME" ...`` (quoted), the same form
# the DSN carries; capture the three parts so only the quoted name is rewritten
# and surrounding whitespace is preserved.
_SES_NET_TOKEN_RE = re.compile(r'(\(net\s+")([^"]*)(")')


def _reconcile_ses_net_names(
    ses_text: str, board_net_names: Iterable[str]
) -> Tuple[str, List[str]]:
    """Re-add a leading ``/`` to SES net names that lost it on the DSN round-trip.

    KiCad's global-label nets are named with a leading ``/`` (e.g. ``/GND``). A
    Specctra DSN round-trip through Freerouting can drop that prefix, so
    ``ImportSpecctraSES`` fails the exact-string net lookup and creates a *new*
    slashless net, leaving the original unconnected (issue #246).

    For each ``(net "NAME" ...`` token, if ``NAME`` is not itself a board net but
    ``/NAME`` is, rewrite it to ``/NAME``. Names that already match a board net
    (slashed or not) are left untouched, so this is idempotent and only touches
    genuinely-orphaned names. Returns ``(rewritten_text, remapped_names)``.
    """
    board = set(board_net_names)

    remapped: List[str] = []

    def _repl(match: "re.Match[str]") -> str:
        name = match.group(2)
        if name and name not in board and ("/" + name) in board:
            remapped.append(name)
            return f"{match.group(1)}/{name}{match.group(3)}"
        return match.group(0)

    return _SES_NET_TOKEN_RE.sub(_repl, ses_text), remapped


def _missing_keepout_lines(board) -> List[str]:
    """The rule-area outlines KiCad's Specctra export leaves out, as DSN keepout lines.

    ExportSpecctraDSN writes only the first outline of a rule area. A keepout area drawn
    as several polygons (or one built from a union of halos) silently routes as if only
    its first piece existed. Each further outline is written in the same form KiCad
    writes the first: (keepout|wire_keepout|via_keepout "" (polygon LAYER 0 x y ...)),
    in micrometres with y negated. Holes are not exported (KiCad drops them too), which
    errs on the side of keeping copper out.
    """
    lines: List[str] = []
    for z in board.Zones():
        if not z.GetIsRuleArea():
            continue
        tracks, vias = z.GetDoNotAllowTracks(), z.GetDoNotAllowVias()
        if not (tracks or vias):
            continue
        kind = "keepout" if tracks and vias else ("wire_keepout" if tracks else "via_keepout")
        outline = z.Outline()
        if outline.OutlineCount() < 2:
            continue
        for layer in z.GetLayerSet().CuStack():
            name = dsn_quote(board.GetLayerName(layer))
            for i in range(1, outline.OutlineCount()):
                chain = outline.COutline(i)
                pts = " ".join(
                    f"{chain.CPoint(k).x / 1000:g} {-chain.CPoint(k).y / 1000:g}"
                    for k in range(chain.PointCount())
                )
                lines.append(f'    ({kind} "" (polygon {name} 0 {pts}))')
    return lines


def _append_to_structure(dsn_text: str, lines: Iterable[str]) -> str:
    """Insert ``lines`` (without line endings) at the end of the DSN's (structure) block.

    The block's end is found by parsing, not by its indentation, and the file's own line
    ending is used, so the text is otherwise left exactly as KiCad wrote it.
    """
    lines = list(lines)
    m = re.search(r"\(structure(?=[\s)])", dsn_text)
    if not lines or not m:
        return dsn_text
    end = _sexpr_end(dsn_text, m.start())
    if end < 0:
        return dsn_text
    nl = "\r\n" if "\r\n" in dsn_text else "\n"
    close = end - 1  # the ")" that closes (structure
    line_start = dsn_text.rfind("\n", 0, close) + 1
    block = nl.join(lines) + nl
    if dsn_text[line_start:close].strip():
        # the closing paren shares a line with content: start a new line for the block
        return dsn_text[:close] + nl + block + dsn_text[close:]
    return dsn_text[:line_start] + block + dsn_text[line_start:]


def _append_missing_keepouts(board, dsn_path) -> int:
    """Add the rule-area outlines the DSN export left out to the file; returns how many."""
    lines = _missing_keepout_lines(board)
    if not lines:
        return 0
    # newline="" keeps the file's line endings as KiCad wrote them (no CRLF on Windows).
    with open(dsn_path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    patched = _append_to_structure(text, lines)
    if patched == text:
        return 0
    with open(dsn_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(patched)
    return len(lines)


class FreeroutingCommands:
    """Handles Freerouting autoroute operations."""

    def __init__(
        self,
        board: Any = None,
        on_board_saved: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.board = board
        # Nets left out of the last autoroute's DSN (routeNets / excludeNets), or None.
        self._nets_left_out: Optional[List[str]] = None
        # Told the path after each successful save of self.board, so the
        # interface can record the file's new signature. Without that, its
        # next auto-save takes this save for an external change and refuses.
        self.on_board_saved = on_board_saved

    def _save_board(self, board_path: str, after: str) -> None:
        """Save self.board to board_path; report a successful save."""
        try:
            with preserve_project_settings(board_path):
                self.board.Save(board_path)
        except Exception as e:
            logger.warning(f"Board save after {after} failed: {e}")
            return
        on_board_saved = getattr(self, "on_board_saved", None)
        if on_board_saved is not None:
            on_board_saved(board_path)

    def _apply_project_net_classes(self, board_path: Optional[str]) -> Dict[str, Any]:
        """Push the project's net classes into the loaded board before DSN
        export (#302).

        Net-class definitions live in ``.kicad_pro``, which the headless
        ``LoadBoard()`` path never reads, so without this every net is
        exported under ``kicad_default`` at Default width — a power net
        reaches Freerouting at signal width with no warning. Applying the
        classes to the board's NET_SETTINGS makes ``ExportSpecctraDSN``
        natively emit per-class rules and via padstacks.

        Best-effort: never raises. The returned report goes into the tool
        response so a dropped class is loud, not silent.
        """
        pro_path = os.path.splitext(board_path)[0] + ".kicad_pro" if board_path else ""
        try:
            settings = load_project_net_classes(pro_path)
        except ValueError as exc:
            return {
                "applied": [],
                "warning": f"{exc}; DSN exported with Default-class rules only",
            }
        if settings is None:
            return {
                "applied": [],
                "warning": (
                    "no .kicad_pro found next to the board; net-class rules are "
                    "unknown, so every net is exported at Default width/clearance"
                ),
            }
        custom = [c["name"] for c in settings["classes"] if c.get("name") != "Default"]
        try:
            report = apply_net_classes_to_board(self.board, settings)
        except Exception as exc:
            detail = (
                f"project defines net classes {custom} but they could not be "
                f"applied ({exc}); DSN exported with Default-class rules only"
                if custom
                else f"could not apply project net settings ({exc})"
            )
            return {"applied": [], "warning": detail}
        report["projectFile"] = pro_path
        if report["applied"]:
            logger.info(f"Applied project net classes to board: {report['applied']}")
        return report

    def _apply_edge_clearance(self, dsn_path: str) -> None:
        """Grow hole keepouts in the exported DSN to the board's copper-to-edge clearance."""
        try:
            ds = self.board.GetDesignSettings()
            edge_um = ds.m_CopperEdgeClearance / 1000.0
            with open(dsn_path, "r", encoding="utf-8") as fh:
                text = fh.read()
            if not re.search(r"\(unit um\)", text):  # KiCad writes um; anything else: leave it
                return
            m = re.search(r"\(rule\s*\(width [\d.]+\)\s*\(clearance ([\d.]+)\)", text)
            track_um = float(m.group(1)) if m else 0.0
            grown = _grow_hole_keepouts(text, edge_um - track_um)
            if grown != text:
                with open(dsn_path, "w", encoding="utf-8") as fh:
                    fh.write(grown)
        except Exception as e:
            logger.warning(f"Edge-clearance keepout adjustment skipped: {e}")

    def _resolve_execution_mode(self, jar_path: str) -> Dict[str, Any]:
        """Determine how to run Freerouting: direct or docker.

        Returns dict with 'mode', 'use_docker', or 'error'.
        """
        required = _jar_required_java(jar_path)
        java_exe = _find_java(required)
        if java_exe and _java_version_ok(java_exe, required):
            return {"mode": "direct", "use_docker": False}

        if _docker_available():
            return {"mode": "docker", "use_docker": True}

        if java_exe:
            return {
                "mode": "error",
                "error": (
                    f"Java found at {java_exe} but version < {required}. "
                    f"{os.path.basename(jar_path)} requires Java {required}+. "
                    f"Install Java {required}+ (or set JAVA_HOME to it) or Docker."
                ),
            }
        return {
            "mode": "error",
            "error": (
                f"Neither Java {required}+ nor Docker found. "
                "Install one of them to use Freerouting."
            ),
        }

    def autoroute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run Freerouting autorouter on the current board.

        Single-attempt flow (default):
            1. Export board to Specctra DSN
            2. Run Freerouting CLI on DSN -> SES (one pass with ``maxPasses``)
            3. Import SES back into the board
            4. Save the board

        Best-of-N flow (``attempts > 1``):
            1. Export DSN once
            2. Run Freerouting ``attempts`` times, varying ``--max-passes``
               per the ``passSchedule`` (defaults to a built-in schedule
               of 10 spread-out values).
            3. Score each SES by (nets_routed * 1000) + segments, plus a
               50,000-point bonus when every ``targetNets`` entry routed.
            4. Keep the highest-scoring SES; import that one into the board.

        Single-attempt behaviour is unchanged when ``attempts`` is omitted
        or set to 1, so existing callers do not need updates.

        The best-of-N scoring approach is ported from
        morningfire-pcb-automation
        (https://github.com/NiNjA-CodE/morningfire-pcb-automation,
        scripts/routing/freeroute_runner.py). On dense boards a single
        run regularly leaves 1–7 nets unrouted; cycling through a few
        ``-mp`` values typically gets the count to zero.
        """
        try:
            import pcbnew
        except ImportError:
            return {
                "success": False,
                "message": "pcbnew not available",
                "errorDetails": "KiCAD Python API is required",
            }

        if not self.board:
            return {
                "success": False,
                "message": "No board is loaded",
                "errorDetails": "Load or create a board first",
            }

        board_path = params.get("boardPath")
        if not board_path:
            board_path = self.board.GetFileName()

        if not board_path:
            return {
                "success": False,
                "message": "No board file path available",
                "errorDetails": ("Provide boardPath or open a project first"),
            }

        jar_path = params.get("freeroutingJar", DEFAULT_FREEROUTING_JAR)
        timeout = params.get("timeout", 300)
        passes = params.get("maxPasses", 20)

        # Best-of-N parameters
        attempts_raw = params.get("attempts", 1)
        try:
            attempts = int(attempts_raw) if attempts_raw is not None else 1
        except (TypeError, ValueError):
            return {
                "success": False,
                "message": "Invalid attempts value",
                "errorDetails": f"attempts must be a positive integer; got {attempts_raw!r}",
            }
        if attempts < 1:
            return {
                "success": False,
                "message": "Invalid attempts value",
                "errorDetails": "attempts must be >= 1",
            }
        target_nets = list(params.get("targetNets") or [])
        pass_schedule = list(params.get("passSchedule") or DEFAULT_PASS_SCHEDULE)
        if not pass_schedule:
            pass_schedule = [passes]

        # Validate Freerouting JAR
        if not os.path.isfile(jar_path):
            return {
                "success": False,
                "message": "Freerouting JAR not found",
                "errorDetails": (
                    f"Expected at: {jar_path}. Download from "
                    "https://github.com/freerouting/freerouting/"
                    "releases or set FREEROUTING_JAR env var."
                ),
            }

        # Determine execution mode
        exec_mode = self._resolve_execution_mode(jar_path)
        if exec_mode["mode"] == "error":
            return {
                "success": False,
                "message": "No suitable Java runtime",
                "errorDetails": exec_mode["error"],
            }

        use_docker = exec_mode["use_docker"]

        # Set up file paths. Artifacts are staged in a fresh per-run temp
        # directory instead of the user's project directory (#249): every
        # failure exit used to leave .dsn/.ses/_best.ses litter next to the
        # board, and a stale .ses from an earlier run could satisfy the
        # exists-check below and be imported as if it were this run's output.
        # A fresh directory makes cross-run staleness structurally impossible;
        # keepArtifacts=true copies the files back out for debugging.
        keep_artifacts = bool(params.get("keepArtifacts", False))
        board_dir = os.path.dirname(board_path)
        board_stem = Path(board_path).stem
        staging_dir = tempfile.mkdtemp(prefix="kicad-mcp-autoroute-")
        dsn_path = os.path.join(staging_dir, f"{board_stem}.dsn")
        ses_path = os.path.join(staging_dir, f"{board_stem}.ses")
        best_ses_path = os.path.join(staging_dir, f"{board_stem}_best.ses")
        kept_paths: Dict[str, str] = {}

        try:
            self._nets_left_out = None
            staged = self._autoroute_staged(
                params,
                board_path=board_path,
                board_dir=board_dir,
                board_stem=board_stem,
                dsn_path=dsn_path,
                ses_path=ses_path,
                best_ses_path=best_ses_path,
                keep_artifacts=keep_artifacts,
                kept_paths=kept_paths,
                jar_path=jar_path,
                timeout=timeout,
                passes=passes,
                attempts=attempts,
                target_nets=target_nets,
                pass_schedule=pass_schedule,
                use_docker=use_docker,
            )
            if self._nets_left_out is not None and isinstance(staged, dict):
                staged["netsLeftOut"] = self._nets_left_out
                staged["netsLeftOutCount"] = len(self._nets_left_out)
            return staged
        finally:
            # Runs on every exit -- success, failure return, or exception --
            # so no artefact can outlive the run unless explicitly kept.
            if keep_artifacts:
                for src in (dsn_path, ses_path, best_ses_path):
                    try:
                        if os.path.isfile(src):
                            dest = os.path.join(board_dir, os.path.basename(src))
                            shutil.copy2(src, dest)
                            kept_paths[os.path.basename(src)] = dest
                    except OSError as copy_err:
                        logger.warning(f"Could not keep artifact {src}: {copy_err}")
            shutil.rmtree(staging_dir, ignore_errors=True)
            _trim_shared_freerouting_log()

    def _autoroute_staged(
        self,
        params: Dict[str, Any],
        *,
        board_path: str,
        board_dir: str,
        board_stem: str,
        dsn_path: str,
        ses_path: str,
        best_ses_path: str,
        keep_artifacts: bool,
        kept_paths: Dict[str, str],
        jar_path: str,
        timeout: Any,
        passes: Any,
        attempts: int,
        target_nets: List[Any],
        pass_schedule: List[Any],
        use_docker: bool,
    ) -> Dict[str, Any]:
        """Body of autoroute, running against a staged artifact directory."""
        import pcbnew

        # Apply the project's net classes so the DSN carries per-class
        # width/clearance rules instead of routing everything at Default (#302)
        netclass_report = self._apply_project_net_classes(board_path)
        if netclass_report.get("warning"):
            logger.warning(f"Net-class application: {netclass_report['warning']}")

        # Step 1: Export DSN (once, regardless of attempt count)
        logger.info(f"Exporting DSN to {dsn_path}")
        try:
            result = pcbnew.ExportSpecctraDSN(self.board, dsn_path)
            if not _api_ok(result):
                return {
                    "success": False,
                    "message": "DSN export failed",
                    "errorDetails": (f"ExportSpecctraDSN returned: {result}"),
                }
            added = _append_missing_keepouts(self.board, dsn_path)
            if added:
                logger.info(f"Added {added} rule-area outline(s) the DSN export left out")
        except Exception as e:
            return {
                "success": False,
                "message": "DSN export failed",
                "errorDetails": str(e),
            }

        if not os.path.isfile(dsn_path):
            return {
                "success": False,
                "message": "DSN file was not created",
                "errorDetails": f"Expected at: {dsn_path}",
            }

        self._apply_edge_clearance(dsn_path)
        route_nets = list(params.get("routeNets") or [])
        exclude_nets = list(params.get("excludeNets") or [])
        if route_nets or exclude_nets:
            with open(dsn_path, "r", encoding="utf-8", newline="") as f:
                dsn_text = f.read()
            dsn_text, left_out = filter_dsn_nets(dsn_text, net_selector(route_nets, exclude_nets))
            with open(dsn_path, "w", encoding="utf-8", newline="") as f:
                f.write(dsn_text)
            self._nets_left_out = left_out
            logger.info(f"Net selection: {len(left_out)} net(s) left out of the DSN")
        restricted_layers: List[str] = []
        rules_path: Optional[str] = None
        signal_layers = list(params.get("signalLayers") or [])
        trace_costs = dict(params.get("layerTraceCosts") or {})
        if signal_layers or trace_costs:
            try:
                # Canonical names (F.Cu) become the board's own names, which the DSN uses.
                signal_layers = _board_layer_names(self.board, signal_layers)
                cost_layers = _board_layer_names(self.board, trace_costs)
                trace_costs = dict(zip(cost_layers, trace_costs.values()))
                with open(dsn_path, "r", encoding="utf-8", newline="") as fh:
                    rules_text, restricted_layers = _signal_layer_rules(
                        fh.read(),
                        signal_layers,
                        trace_costs,
                        design_name=os.path.splitext(os.path.basename(dsn_path))[0],
                    )
            except ValueError as e:
                return {
                    "success": False,
                    "message": "signalLayers / layerTraceCosts name a layer this board lacks",
                    "errorDetails": str(e),
                }
            if rules_text:
                rules_path = os.path.splitext(dsn_path)[0] + ".rules"
                with open(rules_path, "w", encoding="utf-8") as fh:
                    fh.write(rules_text)
            else:
                logger.info(f"signalLayers {signal_layers}: nothing to restrict or cost")
        dsn_size = os.path.getsize(dsn_path)
        logger.info(f"DSN exported: {dsn_size} bytes")

        # Step 2: Run Freerouting (single or multiple attempts)
        mode_label = "docker" if use_docker else "direct"
        job_timeout = _router_time_budget(timeout, params.get("jobTimeout"))
        try:
            router_args = _router_setting_args(
                params.get("routerSettings"), single_thread=attempts > 1
            )
        except ValueError as e:
            return {
                "success": False,
                "message": "Invalid routerSettings",
                "errorDetails": str(e),
            }
        best_budget_reached = False
        total_start = time.time()
        attempt_results: List[Dict[str, Any]] = []
        best_score = -1
        best_attempt_idx = -1
        best_proc_stdout = ""
        rejected_settings: List[str] = []

        # If only one attempt, use the legacy maxPasses value (preserves
        # exact backward-compatible behaviour). Otherwise cycle through
        # passSchedule. Always run single-threaded when scoring multiple
        # attempts so the optimiser doesn't introduce clearance violations
        # that would distort the comparison.
        for idx in range(attempts):
            if attempts == 1:
                attempt_passes = passes
                single_thread = False
            else:
                attempt_passes = pass_schedule[idx % len(pass_schedule)]
                single_thread = True

            cmd = _build_freerouting_cmd(
                jar_path,
                dsn_path,
                ses_path,
                attempt_passes,
                use_docker,
                single_thread=single_thread,
                rules_path=rules_path,
                job_timeout=job_timeout,
                router_args=router_args,
            )
            logger.info(
                f"Freerouting attempt {idx + 1}/{attempts} "
                f"(mp={attempt_passes}, mode={mode_label})"
            )

            # Remove the previous attempt's SES before launching: an attempt
            # that exits 0 without writing output must read as "no SES", not
            # silently re-score its predecessor's file (#249).
            try:
                os.remove(ses_path)
            except FileNotFoundError:
                pass

            attempt_start = time.time()
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=os.path.dirname(dsn_path),
                )
                attempt_elapsed = round(time.time() - attempt_start, 1)
            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "message": f"Freerouting timed out after {timeout}s",
                    "errorDetails": (
                        "Increase timeout or reduce board complexity. Nothing it routed was "
                        "kept: "
                        "Freerouting writes its result only when it ends"
                        + (
                            f", and no session file came out of its own time budget of "
                            f"{job_timeout}s (--router.job_timeout). Freerouting before 2.4 "
                            "stops at the budget but writes nothing; use 2.4 or later."
                            if job_timeout
                            else ". " + _no_budget_reason(timeout, params.get("jobTimeout"))
                        )
                    ),
                    "attempts_completed": idx,
                }
            except Exception as e:
                return {
                    "success": False,
                    "message": "Failed to run Freerouting",
                    "errorDetails": str(e),
                    "attempts_completed": idx,
                }

            if proc.returncode != 0:
                # Don't abort the whole best-of-N just because one attempt
                # exits nonzero — record it and move on.
                exit_note = _describe_exit(proc.returncode)
                attempt_results.append(
                    {
                        "attempt": idx + 1,
                        "max_passes": attempt_passes,
                        "elapsed_seconds": attempt_elapsed,
                        "ok": False,
                        "exit_code": proc.returncode,
                        "exit_reason": exit_note.lstrip(" -") or "nonzero exit",
                        "stderr": (proc.stderr or "")[:200],
                    }
                )
                if attempts == 1:
                    return {
                        "success": False,
                        "message": (f"Freerouting exited with code {proc.returncode}{exit_note}"),
                        "errorDetails": proc.stderr or proc.stdout,
                        "elapsed_seconds": attempt_elapsed,
                        "mode": mode_label,
                    }
                continue

            if not os.path.isfile(ses_path):
                attempt_results.append(
                    {
                        "attempt": idx + 1,
                        "max_passes": attempt_passes,
                        "elapsed_seconds": attempt_elapsed,
                        "ok": False,
                        "error": "no SES produced",
                    }
                )
                if attempts == 1:
                    return {
                        "success": False,
                        "message": "Freerouting did not produce SES output",
                        "errorDetails": (f"Expected at: {ses_path}. Stdout: {proc.stdout[:500]}"),
                        "elapsed_seconds": attempt_elapsed,
                    }
                continue

            # Score this attempt
            with open(ses_path, "r", encoding="utf-8", errors="replace") as fh:
                ses_text = fh.read()
            score_info = _score_ses(ses_text, target_nets)
            score = score_info["score"]
            budget_reached = _TIME_BUDGET_MARKER in ((proc.stdout or "") + (proc.stderr or ""))
            for key in _rejected_router_settings(
                (proc.stdout or "") + (proc.stderr or ""), router_args
            ):
                if key not in rejected_settings:
                    rejected_settings.append(key)
            attempt_results.append(
                {
                    "attempt": idx + 1,
                    "max_passes": attempt_passes,
                    "elapsed_seconds": attempt_elapsed,
                    "ok": True,
                    "time_budget_reached": budget_reached,
                    **score_info,
                }
            )
            logger.info(
                f"  attempt {idx + 1}: score={score} "
                f"({score_info['nets']} nets, {score_info['segments']} segs, "
                f"{score_info['vias']} vias)"
            )

            if score > best_score:
                best_score = score
                best_attempt_idx = idx
                best_proc_stdout = proc.stdout or ""
                best_budget_reached = budget_reached
                # Snapshot the SES that produced this score so later
                # attempts (which overwrite ses_path) don't clobber it.
                shutil.copy2(ses_path, best_ses_path)

        elapsed = round(time.time() - total_start, 1)

        if best_attempt_idx == -1:
            return {
                "success": False,
                "message": "All Freerouting attempts failed",
                "errorDetails": "No attempt produced a usable SES file",
                "elapsed_seconds": elapsed,
                "attempts": attempt_results,
            }

        # Restore the winning SES as the canonical output file. Write to a
        # sibling path and rename over ses_path instead of truncating it in
        # place: with rootful Docker and no -u, ses_path is still owned by
        # the container, and an in-place overwrite needs write permission
        # on that file itself. Rename only needs write permission on the
        # containing directory, which the host always has.
        if attempts > 1:
            restore_tmp = ses_path + ".tmp"
            shutil.copy2(best_ses_path, restore_tmp)
            os.replace(restore_tmp, ses_path)

        ses_size = os.path.getsize(ses_path)
        logger.info(
            f"Best SES: attempt {best_attempt_idx + 1}, score={best_score}, "
            f"{ses_size} bytes (total {elapsed}s)"
        )

        # Step 3: Import the winning SES. The placement block is stripped from a
        # copy (a headless run never moves parts, and an unresolvable reference in
        # the block aborts the whole import); the SES itself stays as Freerouting
        # wrote it, which matters when keepArtifacts keeps it.
        logger.info(f"Importing SES from {ses_path}")
        import_copy = ses_path + ".import.ses"
        try:
            with open(ses_path, "r", encoding="utf-8", errors="replace") as fh:
                routed = _strip_ses_placement(fh.read())
            with open(import_copy, "w", encoding="utf-8") as fh:
                fh.write(routed)
            # The left-out nets' copper is not in the session; lock it so the import
            # keeps it (unlocked tracks are cleared), then put the lock flags back.
            kept = _lock_tracks_of_nets(self.board, self._nets_left_out or [])
            try:
                result = pcbnew.ImportSpecctraSES(self.board, import_copy)
            finally:
                if kept:
                    _restore_lock_states(kept)
                    logger.info(f"Kept {len(kept)} track(s)/via(s) of the nets left out of the DSN")
            if not _api_ok(result):
                return {
                    "success": False,
                    "message": "SES import failed",
                    "errorDetails": f"ImportSpecctraSES returned: {result}. {_TRACKS_CLEARED_NOTE}",
                    "elapsed_seconds": elapsed,
                    "attempts": attempt_results,
                }
        except Exception as e:
            return {
                "success": False,
                "message": "SES import failed",
                "errorDetails": f"{e}. {_TRACKS_CLEARED_NOTE}",
                "elapsed_seconds": elapsed,
                "attempts": attempt_results,
            }
        finally:
            try:
                os.remove(import_copy)
            except OSError:
                pass

        # Step 4: Save board
        self._save_board(board_path, "autoroute")

        # Collect stats
        tracks = self.board.GetTracks()
        track_count = 0
        via_count = 0
        for t in tracks:
            if t.GetClass() == "PCB_VIA":
                via_count += 1
            else:
                track_count += 1

        response: Dict[str, Any] = {
            "success": True,
            "message": f"Autoroute completed in {elapsed}s",
            "mode": mode_label,
            # By the board's own layer names (what the DSN and the rules file use).
            "tracksKeptOffLayers": restricted_layers,
            "layerTraceCosts": trace_costs,
            # Artifacts are staged in a temp dir and removed after the run
            # (#249); with keepArtifacts=true they are copied next to the
            # board and these fields point at the kept copies.
            "artifacts_kept": keep_artifacts,
            "dsn_path": (
                os.path.join(board_dir, os.path.basename(dsn_path)) if keep_artifacts else None
            ),
            "ses_path": (
                os.path.join(board_dir, os.path.basename(ses_path)) if keep_artifacts else None
            ),
            "elapsed_seconds": elapsed,
            "board_stats": {
                "tracks": track_count,
                "vias": via_count,
            },
            "netClasses": netclass_report,
            "freerouting_stdout": best_proc_stdout[:1000],
            "job_timeout_seconds": job_timeout,
            "router_settings": router_args,
            "router_settings_rejected": rejected_settings,
            "time_budget_reached": best_budget_reached,
        }
        if attempts > 1:
            response["attempts"] = attempt_results
            response["best_attempt"] = best_attempt_idx + 1
            response["best_score"] = best_score
            response["best_ses_path"] = (
                os.path.join(board_dir, os.path.basename(best_ses_path)) if keep_artifacts else None
            )
        return response

    def export_dsn(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Export the board to Specctra DSN format only."""
        try:
            import pcbnew
        except ImportError:
            return {
                "success": False,
                "message": "pcbnew not available",
                "errorDetails": "KiCAD Python API is required",
            }

        if not self.board:
            return {
                "success": False,
                "message": "No board is loaded",
                "errorDetails": "Load or create a board first",
            }

        board_path = params.get("boardPath") or self.board.GetFileName()
        output_path = params.get("outputPath")

        if not output_path:
            if board_path:
                output_path = os.path.splitext(board_path)[0] + ".dsn"
            else:
                return {
                    "success": False,
                    "message": "No output path",
                    "errorDetails": ("Provide outputPath or have a board open"),
                }

        # Apply the project's net classes so the DSN carries per-class
        # width/clearance rules instead of routing everything at Default (#302)
        netclass_report = self._apply_project_net_classes(board_path)
        if netclass_report.get("warning"):
            logger.warning(f"Net-class application: {netclass_report['warning']}")

        added_keepouts = 0
        try:
            result = pcbnew.ExportSpecctraDSN(self.board, output_path)
            if not _api_ok(result):
                return {
                    "success": False,
                    "message": "DSN export failed",
                    "errorDetails": (f"ExportSpecctraDSN returned: {result}"),
                }
            if os.path.isfile(output_path):
                # Same fix as autoroute, so a DSN exported by hand matches what it sends.
                added_keepouts = _append_missing_keepouts(self.board, output_path)
        except Exception as e:
            return {
                "success": False,
                "message": "DSN export failed",
                "errorDetails": str(e),
            }

        if os.path.isfile(output_path):
            self._apply_edge_clearance(output_path)
        file_size = os.path.getsize(output_path) if os.path.isfile(output_path) else 0
        return {
            "success": True,
            "message": f"Exported DSN to {output_path}",
            "path": output_path,
            "size_bytes": file_size,
            "netClasses": netclass_report,
            "keepoutOutlinesAdded": added_keepouts,
        }

    def _board_net_names(self) -> List[str]:
        """All net names currently on the loaded board (same enumeration as
        ``get_nets_list``). Returns ``[]`` if no board or on any read error."""
        names: List[str] = []
        if not self.board:
            return names
        try:
            netinfo = self.board.GetNetInfo()
            for code in range(netinfo.GetNetCount()):
                net = netinfo.GetNetItem(code)
                if net:
                    names.append(net.GetNetname())
        except Exception as e:
            logger.warning(f"Could not enumerate board net names: {e}")
        return names

    def import_ses(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Import a Specctra SES file into the board."""
        try:
            import pcbnew
        except ImportError:
            return {
                "success": False,
                "message": "pcbnew not available",
                "errorDetails": "KiCAD Python API is required",
            }

        if not self.board:
            return {
                "success": False,
                "message": "No board is loaded",
                "errorDetails": "Load or create a board first",
            }

        ses_path = params.get("sesPath")
        if not ses_path:
            return {
                "success": False,
                "message": "Missing sesPath parameter",
                "errorDetails": ("Provide the path to the .ses file"),
            }

        if not os.path.isfile(ses_path):
            return {
                "success": False,
                "message": "SES file not found",
                "errorDetails": f"File not found: {ses_path}",
            }

        # Reconcile net names that lost their leading '/' on the DSN round-trip
        # so pcbnew's exact-string lookup binds routed tracks to the real board
        # nets instead of creating phantom slashless duplicates (#246). Any
        # failure here falls back to importing the original file unchanged.
        # Placement entries KiCad cannot resolve are dropped too: a reference
        # missing from the board, or not unique on it, aborts the whole import.
        # Entries that do resolve are kept, since a part moved in Freerouting's
        # GUI must still move.
        import_path = ses_path
        reconciled_temp: Optional[str] = None
        remapped: List[str] = []
        placement_skipped: List[str] = []
        try:
            board_net_names = self._board_net_names()
            with open(ses_path, "r", encoding="utf-8") as f:
                ses_text = f.read()
            fixed_text, remapped = _reconcile_ses_net_names(ses_text, board_net_names)
            board_refs = [fp.GetReference() for fp in self.board.GetFootprints()]
            fixed_text, placement_skipped = _prune_ses_placement(fixed_text, board_refs)
            if placement_skipped:
                logger.warning(
                    "Skipped SES placement for references missing or duplicated on the "
                    "board: %s",
                    sorted(set(placement_skipped)),
                )
            if fixed_text != ses_text:
                fd, reconciled_temp = tempfile.mkstemp(
                    suffix=".ses", prefix="reconciled-", dir=os.path.dirname(ses_path) or None
                )
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(fixed_text)
                import_path = reconciled_temp
                if remapped:
                    logger.info(
                        "Reconciled %d SES net name(s) to their '/'-prefixed board nets: %s",
                        len(remapped),
                        sorted(set(remapped)),
                    )
        except Exception as e:
            logger.warning(f"SES net-name reconciliation skipped ({e}); importing original file")
            import_path = ses_path

        try:
            result = pcbnew.ImportSpecctraSES(self.board, import_path)
            if not _api_ok(result):
                return {
                    "success": False,
                    "message": "SES import failed",
                    "errorDetails": f"ImportSpecctraSES returned: {result}. {_TRACKS_CLEARED_NOTE}",
                }
        except Exception as e:
            return {
                "success": False,
                "message": "SES import failed",
                "errorDetails": f"{e}. {_TRACKS_CLEARED_NOTE}",
            }
        finally:
            if reconciled_temp and os.path.isfile(reconciled_temp):
                try:
                    os.remove(reconciled_temp)
                except OSError:
                    pass

        board_path = params.get("boardPath") or self.board.GetFileName()
        if board_path:
            self._save_board(board_path, "SES import")

        tracks = self.board.GetTracks()
        track_count = sum(1 for t in tracks if t.GetClass() != "PCB_VIA")
        via_count = sum(1 for t in tracks if t.GetClass() == "PCB_VIA")

        response: Dict[str, Any] = {
            "success": True,
            "message": f"Imported SES from {ses_path}",
            "board_stats": {
                "tracks": track_count,
                "vias": via_count,
            },
        }
        if remapped:
            # Report the net-name repairs so callers can see the '/'-prefix fix ran.
            response["netsRemapped"] = sorted(set(remapped))
        if placement_skipped:
            # Those parts kept their board position; the routes imported anyway.
            response["placementSkipped"] = sorted(set(placement_skipped))
        return response

    def check_freerouting(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Check if Freerouting and Java/Docker are available."""
        jar_path = params.get("freeroutingJar", DEFAULT_FREEROUTING_JAR)

        # Check local Java against the release the JAR was built for
        required = _jar_required_java(jar_path)
        java_exe = _find_java(required)
        java_version = None
        java_ok = False
        if java_exe:
            try:
                proc = subprocess.run(
                    [java_exe, "-version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                java_version = (proc.stderr or proc.stdout).strip().split("\n")[0]
                java_ok = _java_version_ok(java_exe, required)
            except Exception:
                pass

        # Check Docker/Podman
        docker_exe = _find_docker()
        has_docker = _docker_available()

        jar_exists = os.path.isfile(jar_path)
        ready = jar_exists and (java_ok or has_docker)

        mode = "none"
        if java_ok:
            mode = "direct"
        elif has_docker:
            mode = "docker"

        return {
            "success": True,
            "message": "Freerouting dependency check",
            "java": {
                "found": java_exe is not None,
                "path": java_exe,
                "version": java_version,
                # None when there is no JAR to read the requirement from; the
                # checks above then fall back to DEFAULT_REQUIRED_JAVA.
                "required_version": required if jar_exists else None,
                "version_ok": java_ok,
                # kept for existing callers; now means "meets the JAR's requirement"
                "java_21_ok": java_ok,
            },
            "docker": {
                "available": has_docker,
                "path": docker_exe,
                "image": _docker_image(required),
            },
            "freerouting": {
                "jar_found": jar_exists,
                "jar_path": jar_path,
            },
            "execution_mode": mode,
            "ready": ready,
        }
