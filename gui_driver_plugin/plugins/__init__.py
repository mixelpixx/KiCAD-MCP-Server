"""KiCad GUI-driver helper — starts the localhost control channel on plugin scan.

Packaging note (a real bug we fixed once already): PCM installs the zip's
``plugins/`` directory CONTENTS to ``3rdparty/plugins/<identifier>/``, so these
files live at the ``plugins/`` ROOT of the package — do NOT nest them under
``plugins/<name>/`` or the package lands one directory too deep and KiCad
never imports it.

KiCad imports this package during its 3rd-party plugin scan. Starting the control
channel is an OPT-IN: installing the helper must not, by itself, open a localhost
socket that drives the user's GUI. The listener only starts when the environment
variable ``KICAD_GUI_DRIVER_ENABLE`` is truthy (1/true/yes/on) — set it in KiCad's
launch environment when you intend the MCP to drive this KiCad. When enabled, the
listener thread still touches no wx (all wx work is queued to the UI thread via
``wx.CallAfter`` — see ``listener.py``), so starting it at scan time is safe.
"""

from __future__ import annotations

import os
import sys

_ENABLE = os.environ.get("KICAD_GUI_DRIVER_ENABLE", "").strip().lower() in ("1", "true", "yes", "on")

if _ENABLE:
    try:
        from . import listener

        _port = listener.start()
        if _port is None:
            print(
                "kicad-gui-driver: port already in use — another editor window "
                "probably serves it; this instance will not listen.",
                file=sys.stderr,
            )
        else:
            print(f"kicad-gui-driver: listening on 127.0.0.1:{_port} (token-gated).", file=sys.stderr)
    except Exception as exc:  # pragma: no cover - best-effort, never break the scan
        print(f"kicad-gui-driver: listener not started ({exc})", file=sys.stderr)
else:
    print(
        "kicad-gui-driver: installed but idle — set KICAD_GUI_DRIVER_ENABLE=1 in "
        "KiCad's environment to open the (token-gated) control channel.",
        file=sys.stderr,
    )
