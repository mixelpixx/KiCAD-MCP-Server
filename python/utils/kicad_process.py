"""
KiCAD Process Management Utilities

Detects if KiCAD is running and provides auto-launch functionality.
"""
import os
import subprocess
import logging
import platform
import time
import ctypes
from ctypes import wintypes
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)


class KiCADProcessManager:
    """Manages KiCAD process detection and launching"""

    @staticmethod
    def _windows_list_processes() -> List[dict]:
        """List running processes on Windows using Toolhelp API."""
        processes: List[dict] = []
        try:
            TH32CS_SNAPPROCESS = 0x00000002
            try:
                ulong_ptr = wintypes.ULONG_PTR  # type: ignore[attr-defined]
            except AttributeError:
                ulong_ptr = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

            class PROCESSENTRY32W(ctypes.Structure):
                _fields_ = [
                    ("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ulong_ptr),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * wintypes.MAX_PATH),
                ]

            CreateToolhelp32Snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot
            Process32FirstW = ctypes.windll.kernel32.Process32FirstW
            Process32NextW = ctypes.windll.kernel32.Process32NextW
            CloseHandle = ctypes.windll.kernel32.CloseHandle

            snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if snapshot == wintypes.HANDLE(-1).value:
                return processes

            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)

            if Process32FirstW(snapshot, ctypes.byref(entry)):
                while True:
                    processes.append({
                        "pid": str(entry.th32ProcessID),
                        "name": entry.szExeFile,
                        "command": entry.szExeFile
                    })
                    if not Process32NextW(snapshot, ctypes.byref(entry)):
                        break

            CloseHandle(snapshot)
        except Exception as e:
            logger.error(f"Error listing Windows processes: {e}")

        return processes

    @staticmethod
    def is_running() -> bool:
        """
        Check if KiCAD is currently running

        Returns:
            True if KiCAD process found, False otherwise
        """
        system = platform.system()

        try:
            if system == "Linux":
                # Check for actual pcbnew/kicad binaries (not python scripts)
                # Use exact process name matching to avoid matching our own kicad_interface.py
                result = subprocess.run(
                    ["pgrep", "-x", "pcbnew|kicad"],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    return True
                # Also check with -f for full path matching, but exclude our script
                result = subprocess.run(
                    ["pgrep", "-f", "/pcbnew|/kicad"],
                    capture_output=True,
                    text=True
                )
                # Double-check it's not our own process
                if result.returncode == 0:
                    pids = result.stdout.strip().split('\n')
                    for pid in pids:
                        try:
                            cmdline = subprocess.run(
                                ["ps", "-p", pid, "-o", "command="],
                                capture_output=True,
                                text=True
                            )
                            if "kicad_interface.py" not in cmdline.stdout:
                                return True
                        except:
                            pass
                return False

            elif system == "Darwin":  # macOS
                result = subprocess.run(
                    ["pgrep", "-f", "KiCad|pcbnew"],
                    capture_output=True,
                    text=True
                )
                return result.returncode == 0

            elif system == "Windows":
                processes = KiCADProcessManager._windows_list_processes()
                for proc in processes:
                    name = (proc.get("name") or "").lower()
                    if name in ("pcbnew.exe", "kicad.exe"):
                        return True
                return False

            else:
                logger.warning(f"Process detection not implemented for {system}")
                return False

        except Exception as e:
            logger.error(f"Error checking if KiCAD is running: {e}")
            return False

    @staticmethod
    def get_executable_path() -> Optional[Path]:
        """
        Get path to KiCAD executable

        Returns:
            Path to pcbnew/kicad executable, or None if not found
        """
        system = platform.system()

        # Try to find executable in PATH first
        for cmd in ["pcbnew", "kicad"]:
            result = subprocess.run(
                ["which", cmd] if system != "Windows" else ["where", cmd],
                capture_output=True,
                text=True,
                encoding="mbcs" if system == "Windows" else None,
                errors="ignore" if system == "Windows" else None,
                timeout=5 if system == "Windows" else None
            )
            if result.returncode == 0:
                path = result.stdout.strip().split("\n")[0]
                logger.info(f"Found KiCAD executable: {path}")
                return Path(path)

        # Platform-specific default paths
        if system == "Linux":
            candidates = [
                Path("/usr/bin/pcbnew"),
                Path("/usr/local/bin/pcbnew"),
                Path("/usr/bin/kicad"),
            ]
        elif system == "Darwin":  # macOS
            candidates = [
                Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad"),
                Path("/Applications/KiCad/pcbnew.app/Contents/MacOS/pcbnew"),
            ]
        elif system == "Windows":
            candidates = [
                Path("C:/Program Files/KiCad/9.0/bin/pcbnew.exe"),
                Path("C:/Program Files/KiCad/8.0/bin/pcbnew.exe"),
                Path("C:/Program Files (x86)/KiCad/9.0/bin/pcbnew.exe"),
            ]
        else:
            candidates = []

        for path in candidates:
            if path.exists():
                logger.info(f"Found KiCAD executable: {path}")
                return path

        logger.warning("Could not find KiCAD executable")
        return None

    @staticmethod
    def launch(project_path: Optional[Path] = None, wait_for_start: bool = True) -> bool:
        """
        Launch KiCAD PCB Editor

        Args:
            project_path: Optional path to .kicad_pcb file to open
            wait_for_start: Wait for process to start before returning

        Returns:
            True if launch successful, False otherwise
        """
        try:
            # Check if already running
            if KiCADProcessManager.is_running():
                logger.info("KiCAD is already running")
                return True

            # Find executable
            exe_path = KiCADProcessManager.get_executable_path()
            if not exe_path:
                logger.error("Cannot launch KiCAD: executable not found")
                return False

            # Build command
            cmd = [str(exe_path)]
            if project_path:
                cmd.append(str(project_path))

            logger.info(f"Launching KiCAD: {' '.join(cmd)}")

            # Launch process in background
            system = platform.system()
            if system == "Windows":
                # Windows: Use CREATE_NEW_PROCESS_GROUP to detach
                subprocess.Popen(
                    cmd,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                # Unix: Use nohup or start in background
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )

            # Wait for process to start
            if wait_for_start:
                logger.info("Waiting for KiCAD to start...")
                for i in range(10):  # Wait up to 5 seconds
                    time.sleep(0.5)
                    if KiCADProcessManager.is_running():
                        logger.info("✓ KiCAD started successfully")
                        return True

                logger.warning("KiCAD process not detected after launch")
                # Return True anyway, it might be starting
                return True

            return True

        except Exception as e:
            logger.error(f"Error launching KiCAD: {e}")
            return False

    @staticmethod
    def get_process_info() -> List[dict]:
        """
        Get information about running KiCAD processes

        Returns:
            List of process info dicts with pid, name, and command
        """
        system = platform.system()
        processes = []

        try:
            if system in ["Linux", "Darwin"]:
                result = subprocess.run(
                    ["ps", "aux"],
                    capture_output=True,
                    text=True
                )
                for line in result.stdout.split("\n"):
                    # Only match actual KiCAD binaries, not our MCP server processes
                    if ("pcbnew" in line.lower() or "kicad" in line.lower()) and "kicad_interface.py" not in line and "grep" not in line:
                        # More specific check: must have /pcbnew or /kicad in the path
                        if "/pcbnew" in line or "/kicad" in line or "KiCad.app" in line:
                            parts = line.split()
                            if len(parts) >= 11:
                                processes.append({
                                    "pid": parts[1],
                                    "name": parts[10],
                                    "command": " ".join(parts[10:])
                                })

            elif system == "Windows":
                for proc in KiCADProcessManager._windows_list_processes():
                    name = (proc.get("name") or "").lower()
                    if "pcbnew" in name or "kicad" in name:
                        processes.append(proc)

        except Exception as e:
            logger.error(f"Error getting process info: {e}")

        return processes

def check_and_launch_kicad(project_path: Optional[Path] = None, auto_launch: bool = True) -> dict:
    """
    Check if KiCAD is running and optionally launch it

    Args:
        project_path: Optional path to .kicad_pcb file to open
        auto_launch: If True, launch KiCAD if not running

    Returns:
        Dict with status information
    """
    manager = KiCADProcessManager()

    is_running = manager.is_running()

    if is_running:
        processes = manager.get_process_info()
        return {
            "running": True,
            "launched": False,
            "processes": processes,
            "message": "KiCAD is already running"
        }

    if not auto_launch:
        return {
            "running": False,
            "launched": False,
            "processes": [],
            "message": "KiCAD is not running (auto-launch disabled)"
        }

    # Try to launch
    logger.info("KiCAD not detected, attempting to launch...")
    success = manager.launch(project_path)

    return {
        "running": success,
        "launched": success,
        "processes": manager.get_process_info() if success else [],
        "message": "KiCAD launched successfully" if success else "Failed to launch KiCAD",
        "project": str(project_path) if project_path else None
    }
