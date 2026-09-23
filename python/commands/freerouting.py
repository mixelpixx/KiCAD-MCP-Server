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
from typing import Any, Dict, Iterable, List, Optional, Tuple

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


_TRACKS_CLEARED_NOTE = (
    "An SES import that fails after parsing has usually already removed the "
    "board's unlocked tracks, so the board in memory may have lost them; nothing "
    "was saved. Reopen the board from disk before saving or routing again."
)


_DSN_KEEPOUT_RE = re.compile(r'(\(keepout "[^"]*" \(polygon signal 0\s+)([-\d.\s]+?)(\))')


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


def _build_freerouting_cmd(
    jar_path: str,
    dsn_path: str,
    ses_path: str,
    passes: int,
    use_docker: bool,
    single_thread: bool = False,
) -> List[str]:
    """Build the command to run Freerouting.

    ``single_thread`` forces ``-mt 1`` (single-threaded optimisation).
    Freerouting 2.x's multi-threaded optimiser is documented to produce
    clearance violations in some cases (the runtime even prints a warning);
    best-of-N callers should pass this so each attempt's score reflects a
    valid routed board, not an artefact of MT optimisation.
    """
    extra = ["-mt", "1"] if single_thread else []
    required_java = _jar_required_java(jar_path)
    if use_docker:
        docker_exe = _find_docker()
        if docker_exe is None:
            raise RuntimeError("Docker/Podman executable not found")
        board_dir = os.path.dirname(dsn_path)
        dsn_name = os.path.basename(dsn_path)
        ses_name = os.path.basename(ses_path)
        jar_name = os.path.basename(jar_path)
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


class FreeroutingCommands:
    """Handles Freerouting autoroute operations."""

    def __init__(self, board: Any = None) -> None:
        self.board = board

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
            return self._autoroute_staged(
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
        dsn_size = os.path.getsize(dsn_path)
        logger.info(f"DSN exported: {dsn_size} bytes")

        # Step 2: Run Freerouting (single or multiple attempts)
        mode_label = "docker" if use_docker else "direct"
        total_start = time.time()
        attempt_results: List[Dict[str, Any]] = []
        best_score = -1
        best_attempt_idx = -1
        best_proc_stdout = ""

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
                    "errorDetails": "Increase timeout or reduce board complexity",
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
            attempt_results.append(
                {
                    "attempt": idx + 1,
                    "max_passes": attempt_passes,
                    "elapsed_seconds": attempt_elapsed,
                    "ok": True,
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

        # Restore the winning SES as the canonical output file
        if attempts > 1:
            shutil.copy2(best_ses_path, ses_path)

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
            result = pcbnew.ImportSpecctraSES(self.board, import_copy)
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
        try:
            with preserve_project_settings(board_path):
                self.board.Save(board_path)
        except Exception as e:
            logger.warning(f"Board save after autoroute failed: {e}")

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

        try:
            result = pcbnew.ExportSpecctraDSN(self.board, output_path)
            if not _api_ok(result):
                return {
                    "success": False,
                    "message": "DSN export failed",
                    "errorDetails": (f"ExportSpecctraDSN returned: {result}"),
                }
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
            try:
                with preserve_project_settings(board_path):
                    self.board.Save(board_path)
            except Exception as e:
                logger.warning(f"Board save after SES import failed: {e}")

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
