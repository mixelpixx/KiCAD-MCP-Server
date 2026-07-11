"""Central pcbnew availability handling.

Twelve-plus modules in this package ``import pcbnew`` at module level. On a
Python that cannot import the SWIG bindings (wrong interpreter, KiCAD not
installed, or KiCAD 11+ where SWIG is gone) that used to kill the whole
process at import time. :func:`ensure_pcbnew` makes the import always succeed:
when the real module is unavailable it installs a proxy into
``sys.modules['pcbnew']`` whose every attribute access raises ImportError with
platform help text. SWIG-dependent commands then fail per call with a useful
message, while IPC-, kicad-cli- and schematic-file tools keep working.
"""

import logging
import sys
import types
from typing import Any, Optional

logger = logging.getLogger("kicad_interface")


def _help_message() -> str:
    if sys.platform == "win32":
        return """
Windows Troubleshooting:
1. Verify KiCAD is installed: C:\\Program Files\\KiCad\\9.0
2. Check PYTHONPATH environment variable points to:
   C:\\Program Files\\KiCad\\9.0\\lib\\python3\\dist-packages
3. Test with: "C:\\Program Files\\KiCad\\9.0\\bin\\python.exe" -c "import pcbnew"
4. Log file location: %USERPROFILE%\\.kicad-mcp\\logs\\kicad_interface.log
5. Run setup-windows.ps1 for automatic configuration
"""
    elif sys.platform == "darwin":
        return """
macOS Troubleshooting:
1. Verify KiCAD is installed: /Applications/KiCad/KiCad.app
2. Check PYTHONPATH points to KiCAD's Python packages
3. Run: python3 -c "import pcbnew" to test
"""
    return """
Linux Troubleshooting:
1. Verify KiCAD is installed: apt list --installed | grep kicad
2. Check: /usr/lib/kicad/lib/python3/dist-packages exists
3. Test: python3 -c "import pcbnew"
"""


class _PcbnewProxy(types.ModuleType):
    """Stands in for the pcbnew module when the SWIG import failed."""

    def __init__(self, reason: str):
        super().__init__("pcbnew")
        self.__dict__["_reason"] = reason

    def __getattr__(self, name: str) -> Any:
        raise ImportError(self.__dict__["_reason"])

    def __bool__(self) -> bool:
        return False


def ensure_pcbnew() -> Optional[str]:
    """Make ``import pcbnew`` succeed everywhere; return the error text if unavailable.

    Returns None when the real SWIG module imported, otherwise the reason
    string (and ``sys.modules['pcbnew']`` holds the raising proxy).
    """
    if "pcbnew" in sys.modules:
        existing = sys.modules["pcbnew"]
        if isinstance(existing, _PcbnewProxy):
            return existing.__dict__["_reason"]
        return None
    try:
        import pcbnew  # noqa: F401

        logger.info(f"Successfully imported pcbnew module from: {sys.modules['pcbnew'].__file__}")
        return None
    except ImportError as e:
        reason = (
            f"pcbnew (SWIG) is not importable in this Python: {e}\n"
            f"{_help_message()}\n"
            "IPC-, kicad-cli- and schematic-file tools still work without it. "
            "For SWIG board tools, run under a Python that can import pcbnew, "
            "or use the IPC backend (KiCAD running with the IPC API enabled)."
        )
    except Exception as e:  # unexpected loader/DLL failures
        reason = f"Error importing pcbnew module: {e}"
    logger.error(reason)
    sys.modules["pcbnew"] = _PcbnewProxy(reason)
    return reason
