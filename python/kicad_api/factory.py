"""
Backend factory for creating appropriate KiCAD API backend

Auto-detects available backends and provides fallback mechanism.
"""
import os
import logging
from typing import Optional
from pathlib import Path

from kicad_api.base import KiCADBackend, APINotAvailableError

logger = logging.getLogger(__name__)


def create_backend(backend_type: Optional[str] = None) -> KiCADBackend:
    """
    Create appropriate KiCAD backend

    Args:
        backend_type: Backend to use:
            - 'ipc': Use IPC API (recommended)
            - 'swig': Use legacy SWIG bindings
            - None or 'auto': Auto-detect (try IPC first, fall back to SWIG)

    Returns:
        KiCADBackend instance

    Raises:
        APINotAvailableError: If no backend is available

    Environment Variables:
        KICAD_BACKEND: Override backend selection ('ipc', 'swig', or 'auto')
    """
    # Check environment variable override
    if backend_type is None:
        backend_type = os.environ.get('KICAD_BACKEND', 'auto').lower()

    logger.info(f"Requested backend: {backend_type}")

    # Try specific backend if requested
    if backend_type == 'ipc':
        return _create_ipc_backend()
    elif backend_type == 'swig':
        return _create_swig_backend()
    elif backend_type == 'auto':
        return _auto_detect_backend()
    else:
        raise ValueError(f"Unknown backend type: {backend_type}")


def _create_ipc_backend() -> KiCADBackend:
    """
    Create IPC backend

    Returns:
        IPCBackend instance

    Raises:
        APINotAvailableError: If kicad-python not available
    """
    try:
        from kicad_api.ipc_backend import IPCBackend
        logger.info("Creating IPC backend")
        return IPCBackend()
    except ImportError as e:
        logger.error(f"IPC backend not available: {e}")
        raise APINotAvailableError(
            "IPC backend requires 'kicad-python' package. "
            "Install with: pip install kicad-python"
        ) from e


def _create_swig_backend() -> KiCADBackend:
    """
    Create SWIG backend

    Returns:
        SWIGBackend instance

    Raises:
        APINotAvailableError: If pcbnew not available
    """
    try:
        from kicad_api.swig_backend import SWIGBackend
        logger.info("Creating SWIG backend")
        logger.warning(
            "SWIG backend is DEPRECATED and will be removed in KiCAD 10.0. "
            "Please migrate to IPC backend."
        )
        return SWIGBackend()
    except ImportError as e:
        logger.error(f"SWIG backend not available: {e}")
        raise APINotAvailableError(
            "SWIG backend requires 'pcbnew' module. "
            "Ensure KiCAD Python module is in PYTHONPATH."
        ) from e


def _auto_detect_backend() -> KiCADBackend:
    """
    Auto-detect best available backend

    Priority:
        1. IPC API (if kicad-python available and KiCAD running)
        2. SWIG API (if pcbnew available)

    Returns:
        Best available KiCADBackend

    Raises:
        APINotAvailableError: If no backend available
    """
    logger.info("Auto-detecting available KiCAD backend...")

    # Try IPC first (preferred)
    try:
        backend = _create_ipc_backend()
        # Test connection
        if backend.connect():
            logger.info("✓ IPC backend available and connected")
            return backend
        else:
            logger.warning("IPC backend available but connection failed")
    except (ImportError, APINotAvailableError) as e:
        logger.debug(f"IPC backend not available: {e}")

    # Fall back to SWIG
    try:
        backend = _create_swig_backend()
        logger.warning(
            "Using deprecated SWIG backend. "
            "For best results, use IPC API with KiCAD running."
        )
        return backend
    except (ImportError, APINotAvailableError) as e:
        logger.error(f"SWIG backend not available: {e}")

    # No backend available
    raise APINotAvailableError(
        "No KiCAD backend available. Please install either:\n"
        "  - kicad-python (recommended): pip install kicad-python\n"
        "  - Ensure KiCAD Python module (pcbnew) is in PYTHONPATH"
    )


def get_available_backends() -> dict:
    """
    Check which backends are available

    Returns:
        Dictionary with backend availability:
            {
                'ipc': {'available': bool, 'version': str or None},
                'swig': {'available': bool, 'version': str or None}
            }
    """
    results = {}

    # Check IPC
    try:
        import kicad
        results['ipc'] = {
            'available': True,
            'version': getattr(kicad, '__version__', 'unknown')
        }
    except ImportError:
        results['ipc'] = {'available': False, 'version': None}

    # Check SWIG
    try:
        import pcbnew
        results['swig'] = {
            'available': True,
            'version': pcbnew.GetBuildVersion()
        }
    except ImportError:
        results['swig'] = {'available': False, 'version': None}

    return results


if __name__ == "__main__":
    # Quick diagnostic
    import json
    print("KiCAD Backend Availability:")
    print(json.dumps(get_available_backends(), indent=2))

    print("\nAttempting to create backend...")
    try:
        backend = create_backend()
        print(f"✓ Created backend: {type(backend).__name__}")
        if backend.connect():
            print(f"✓ Connected to KiCAD: {backend.get_version()}")
        else:
            print("✗ Failed to connect to KiCAD")
    except Exception as e:
        print(f"✗ Error: {e}")
