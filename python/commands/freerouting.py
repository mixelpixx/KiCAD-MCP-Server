"""
Freerouting autoroute integration for KiCAD MCP Server.

Exports the board to Specctra DSN format, runs Freerouting CLI,
and imports the routed SES file back into the board.

Supports two execution modes:
  - Direct: java -jar freerouting.jar (requires Java 21+)
  - Docker: docker run eclipse-temurin:21-jre (requires Docker)
"""

import os
import subprocess
import shutil
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger("kicad_interface")

# Default Freerouting JAR location
DEFAULT_FREEROUTING_JAR = os.environ.get(
    "FREEROUTING_JAR",
    os.path.join(
        os.path.expanduser("~"), ".kicad-mcp", "freerouting.jar"
    ),
)

DOCKER_IMAGE = "eclipse-temurin:21-jre"


def _find_java() -> Optional[str]:
    """Find java executable on the system."""
    java = shutil.which("java")
    if java:
        return java
    for candidate in [
        "/usr/bin/java",
        "/usr/local/bin/java",
        os.path.expandvars("$JAVA_HOME/bin/java"),
    ]:
        if os.path.isfile(candidate):
            return candidate
    return None


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


def _java_version_ok(java_exe: str) -> bool:
    """Check if local Java is version 21+."""
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
                return major >= 21
    except Exception:
        pass
    return False


def _build_freerouting_cmd(
    jar_path: str,
    dsn_path: str,
    ses_path: str,
    passes: int,
    use_docker: bool,
) -> List[str]:
    """Build the command to run Freerouting."""
    if use_docker:
        docker_exe = _find_docker()
        board_dir = os.path.dirname(dsn_path)
        dsn_name = os.path.basename(dsn_path)
        ses_name = os.path.basename(ses_path)
        jar_name = os.path.basename(jar_path)
        return [
            docker_exe, "run", "--rm",
            "-v", f"{jar_path}:/app/{jar_name}:ro",
            "-v", f"{board_dir}:/work",
            DOCKER_IMAGE,
            "java", "-jar", f"/app/{jar_name}",
            "-de", f"/work/{dsn_name}",
            "-do", f"/work/{ses_name}",
            "-mp", str(passes),
        ]
    else:
        java_exe = _find_java()
        return [
            java_exe, "-jar", jar_path,
            "-de", dsn_path, "-do", ses_path,
            "-mp", str(passes),
        ]


class FreeroutingCommands:
    """Handles Freerouting autoroute operations."""

    def __init__(self, board=None):
        self.board = board

    def _resolve_execution_mode(
        self, jar_path: str
    ) -> Dict[str, Any]:
        """Determine how to run Freerouting: direct or docker.

        Returns dict with 'mode', 'use_docker', or 'error'.
        """
        java_exe = _find_java()
        if java_exe and _java_version_ok(java_exe):
            return {"mode": "direct", "use_docker": False}

        if _docker_available():
            return {"mode": "docker", "use_docker": True}

        if java_exe:
            return {
                "mode": "error",
                "error": (
                    f"Java found at {java_exe} but version < 21. "
                    "Freerouting 2.x requires Java 21+. "
                    "Install Java 21+ or Docker."
                ),
            }
        return {
            "mode": "error",
            "error": (
                "Neither Java 21+ nor Docker found. "
                "Install one of them to use Freerouting."
            ),
        }

    def autoroute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run Freerouting autorouter on the current board.

        Flow:
        1. Export board to Specctra DSN
        2. Run Freerouting CLI on DSN -> SES
        3. Import SES back into the board
        4. Save the board
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
                "errorDetails": (
                    "Provide boardPath or open a project first"
                ),
            }

        jar_path = params.get(
            "freeroutingJar", DEFAULT_FREEROUTING_JAR
        )
        timeout = params.get("timeout", 300)
        passes = params.get("maxPasses", 20)

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

        # Set up file paths
        board_dir = os.path.dirname(board_path)
        board_stem = Path(board_path).stem
        dsn_path = os.path.join(board_dir, f"{board_stem}.dsn")
        ses_path = os.path.join(board_dir, f"{board_stem}.ses")

        # Step 1: Export DSN
        logger.info(f"Exporting DSN to {dsn_path}")
        try:
            result = pcbnew.ExportSpecctraDSN(self.board, dsn_path)
            if result is not True and result != 0:
                return {
                    "success": False,
                    "message": "DSN export failed",
                    "errorDetails": (
                        f"ExportSpecctraDSN returned: {result}"
                    ),
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

        dsn_size = os.path.getsize(dsn_path)
        logger.info(f"DSN exported: {dsn_size} bytes")

        # Step 2: Run Freerouting
        cmd = _build_freerouting_cmd(
            jar_path, dsn_path, ses_path, passes, use_docker
        )

        mode_label = "docker" if use_docker else "direct"
        logger.info(
            f"Running Freerouting ({mode_label}): {' '.join(cmd)}"
        )
        start_time = time.time()

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=board_dir,
            )
            elapsed = round(time.time() - start_time, 1)

            if proc.returncode != 0:
                return {
                    "success": False,
                    "message": (
                        f"Freerouting exited with code "
                        f"{proc.returncode}"
                    ),
                    "errorDetails": proc.stderr or proc.stdout,
                    "elapsed_seconds": elapsed,
                    "mode": mode_label,
                }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": (
                    f"Freerouting timed out after {timeout}s"
                ),
                "errorDetails": (
                    "Increase timeout or reduce board complexity"
                ),
            }
        except Exception as e:
            return {
                "success": False,
                "message": "Failed to run Freerouting",
                "errorDetails": str(e),
            }

        # Check SES output
        if not os.path.isfile(ses_path):
            return {
                "success": False,
                "message": "Freerouting did not produce SES output",
                "errorDetails": (
                    f"Expected at: {ses_path}. "
                    f"Stdout: {proc.stdout[:500]}"
                ),
                "elapsed_seconds": elapsed,
            }

        ses_size = os.path.getsize(ses_path)
        logger.info(f"SES produced: {ses_size} bytes in {elapsed}s")

        # Step 3: Import SES
        logger.info(f"Importing SES from {ses_path}")
        try:
            result = pcbnew.ImportSpecctraSES(self.board, ses_path)
            if result is not True and result != 0:
                return {
                    "success": False,
                    "message": "SES import failed",
                    "errorDetails": (
                        f"ImportSpecctraSES returned: {result}"
                    ),
                    "elapsed_seconds": elapsed,
                }
        except Exception as e:
            return {
                "success": False,
                "message": "SES import failed",
                "errorDetails": str(e),
                "elapsed_seconds": elapsed,
            }

        # Step 4: Save board
        try:
            self.board.Save(board_path)
        except Exception as e:
            logger.warning(
                f"Board save after autoroute failed: {e}"
            )

        # Collect stats
        tracks = self.board.GetTracks()
        track_count = 0
        via_count = 0
        for t in tracks:
            if t.GetClass() == "PCB_VIA":
                via_count += 1
            else:
                track_count += 1

        return {
            "success": True,
            "message": f"Autoroute completed in {elapsed}s",
            "mode": mode_label,
            "dsn_path": dsn_path,
            "ses_path": ses_path,
            "elapsed_seconds": elapsed,
            "board_stats": {
                "tracks": track_count,
                "vias": via_count,
            },
            "freerouting_stdout": (
                proc.stdout[:1000] if proc.stdout else ""
            ),
        }

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

        board_path = (
            params.get("boardPath") or self.board.GetFileName()
        )
        output_path = params.get("outputPath")

        if not output_path:
            if board_path:
                output_path = (
                    os.path.splitext(board_path)[0] + ".dsn"
                )
            else:
                return {
                    "success": False,
                    "message": "No output path",
                    "errorDetails": (
                        "Provide outputPath or have a board open"
                    ),
                }

        try:
            result = pcbnew.ExportSpecctraDSN(
                self.board, output_path
            )
            if result is not True and result != 0:
                return {
                    "success": False,
                    "message": "DSN export failed",
                    "errorDetails": (
                        f"ExportSpecctraDSN returned: {result}"
                    ),
                }
        except Exception as e:
            return {
                "success": False,
                "message": "DSN export failed",
                "errorDetails": str(e),
            }

        file_size = (
            os.path.getsize(output_path)
            if os.path.isfile(output_path)
            else 0
        )
        return {
            "success": True,
            "message": f"Exported DSN to {output_path}",
            "path": output_path,
            "size_bytes": file_size,
        }

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
                "errorDetails": (
                    "Provide the path to the .ses file"
                ),
            }

        if not os.path.isfile(ses_path):
            return {
                "success": False,
                "message": "SES file not found",
                "errorDetails": f"File not found: {ses_path}",
            }

        try:
            result = pcbnew.ImportSpecctraSES(
                self.board, ses_path
            )
            if result is not True and result != 0:
                return {
                    "success": False,
                    "message": "SES import failed",
                    "errorDetails": (
                        f"ImportSpecctraSES returned: {result}"
                    ),
                }
        except Exception as e:
            return {
                "success": False,
                "message": "SES import failed",
                "errorDetails": str(e),
            }

        board_path = (
            params.get("boardPath") or self.board.GetFileName()
        )
        if board_path:
            try:
                self.board.Save(board_path)
            except Exception as e:
                logger.warning(
                    f"Board save after SES import failed: {e}"
                )

        tracks = self.board.GetTracks()
        track_count = sum(
            1 for t in tracks if t.GetClass() != "PCB_VIA"
        )
        via_count = sum(
            1 for t in tracks if t.GetClass() == "PCB_VIA"
        )

        return {
            "success": True,
            "message": f"Imported SES from {ses_path}",
            "board_stats": {
                "tracks": track_count,
                "vias": via_count,
            },
        }

    def check_freerouting(
        self, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Check if Freerouting and Java/Docker are available."""
        jar_path = params.get(
            "freeroutingJar", DEFAULT_FREEROUTING_JAR
        )

        # Check local Java
        java_exe = _find_java()
        java_version = None
        java_21_ok = False
        if java_exe:
            try:
                proc = subprocess.run(
                    [java_exe, "-version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                java_version = (
                    (proc.stderr or proc.stdout)
                    .strip()
                    .split("\n")[0]
                )
                java_21_ok = _java_version_ok(java_exe)
            except Exception:
                pass

        # Check Docker/Podman
        docker_exe = _find_docker()
        has_docker = _docker_available()

        jar_exists = os.path.isfile(jar_path)
        ready = jar_exists and (java_21_ok or has_docker)

        mode = "none"
        if java_21_ok:
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
                "java_21_ok": java_21_ok,
            },
            "docker": {
                "available": has_docker,
                "path": docker_exe,
                "image": DOCKER_IMAGE,
            },
            "freerouting": {
                "jar_found": jar_exists,
                "jar_path": jar_path,
            },
            "execution_mode": mode,
            "ready": ready,
        }
