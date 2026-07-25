"""KiCad GUI-driver helper — starts the localhost control channel on plugin scan.

Packaging note (a real bug we fixed once already): PCM installs the zip's
``plugins/`` directory CONTENTS to ``3rdparty/plugins/<identifier>/``, so these
files live at the ``plugins/`` ROOT of the package — do NOT nest them under
``plugins/<name>/`` or the package lands one directory too deep and KiCad
never imports it.

KiCad imports this package during its 3rd-party plugin scan; starting the
listener is an import side effect (same registration-on-import pattern as
kiHarness/Loom). The listener thread itself touches no wx — all wx work is
queued to the UI thread via ``wx.CallAfter`` (see ``listener.py``), so
starting it at scan time (before the UI is fully built) is safe: by the time
a command arrives and is queued, the frames exist.
"""

from __future__ import annotations

import sys

try:
    from . import listener

    _port = listener.start()
    if _port is None:
        print(
            "kicad-gui-driver: port already in use — another editor window "
            "probably serves it; this instance will not listen.",
            file=sys.stderr,
        )
except Exception as exc:  # pragma: no cover - best-effort, never break the scan
    print(f"kicad-gui-driver: listener not started ({exc})", file=sys.stderr)
