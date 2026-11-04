"""Keep pymupdf from breaking pcbnew's SWIG container iteration.

pcbnew and pymupdf are both SWIG-generated extension modules, and SWIG
extension modules in one process share a single runtime type table. The Python
proxy class for ``swig::SwigPyIterator`` is registered there by whichever
module loads first, and iterators created by the other module use that class.

pymupdf's ``SwigPyIterator`` has ``__next__`` but no ``next()`` method, while
pcbnew's container wrappers step through items with ``it.next()``. So when
pymupdf is imported *after* pcbnew (``get_board_2d_view`` and the schematic
view rasterize with it on first use), every later iteration over
``BOARD.GetDrawings()``, ``BOARD.GetTracks()``,
``FOOTPRINT.GraphicalItems()`` and similar containers raises::

    AttributeError: 'SwigPyIterator' object has no attribute 'next'

until the Python process restarts. Importing pymupdf *before* pcbnew leaves
pcbnew's iterator class, which has both methods, in the shared table, so both
modules keep working.

This module needs only the standard library so it can run before pcbnew loads.
"""

import logging
import sys

logger = logging.getLogger("kicad_interface")


def preload_pymupdf() -> bool:
    """Import pymupdf ahead of pcbnew. Return True if pymupdf is loaded.

    Must be called before the first ``import pcbnew``. Calling it later does
    nothing useful but is harmless. A missing or broken pymupdf is not an
    error: the image tools fall back to other rasterizers.
    """
    if "pcbnew" in sys.modules and "pymupdf" not in sys.modules:
        logger.warning(
            "pcbnew was imported before pymupdf; board item iteration may fail "
            "after the first image render"
        )
    try:
        import pymupdf  # noqa: F401
    except Exception as e:  # ImportError, or a broken native library
        logger.info(f"pymupdf not preloaded ({e}); image rendering will use fallbacks")
        return False
    return True
