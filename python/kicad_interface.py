#!/usr/bin/env python3
"""Transition shim for the TypeScript host and the legacy test imports.

The implementation moved to the installable ``kicad_mcp`` package under
``src/``. Two consumers still use this exact path:

- The TypeScript server spawns it as a script; it runs the legacy stdio loop.
- The test suite (and any user code) does ``from kicad_interface import X``
  and ``patch("kicad_interface.Y")``. The sys.modules swap below makes the
  name ``kicad_interface`` BE ``kicad_mcp.dispatch`` (the same module
  object), so imports and monkeypatching hit the real globals.

It disappears together with the TypeScript layer.
"""

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import kicad_mcp.dispatch as _dispatch  # noqa: E402

# `import kicad_interface` yields the dispatch module itself, so attribute
# reads AND monkeypatching hit the real globals.
sys.modules["kicad_interface"] = _dispatch

# Loads of this file under other names (importlib.spec_from_file_location in
# tests) see the same public namespace.
globals().update({k: v for k, v in vars(_dispatch).items() if not k.startswith("__")})

if __name__ == "__main__":
    from kicad_mcp.legacy_stdio import main

    main()
