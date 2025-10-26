"""
KiCAD API Abstraction Layer

This module provides a unified interface to KiCAD's Python APIs,
supporting both the legacy SWIG bindings and the new IPC API.

Usage:
    from kicad_api import create_backend

    # Auto-detect best available backend
    backend = create_backend()

    # Or specify explicitly
    backend = create_backend('ipc')  # Use IPC API
    backend = create_backend('swig')  # Use legacy SWIG

    # Connect and use
    if backend.connect():
        board = backend.get_board()
        board.set_size(100, 80)
"""

from kicad_api.factory import create_backend
from kicad_api.base import KiCADBackend

__all__ = ['create_backend', 'KiCADBackend']
__version__ = '2.0.0-alpha.1'
