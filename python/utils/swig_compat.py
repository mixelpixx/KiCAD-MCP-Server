"""Keep pymupdf from breaking pcbnew's SWIG container iteration.

pcbnew and pymupdf are both SWIG-generated extension modules. When they are
built with the same SWIG runtime version (both use ``swig_runtime_data5`` on
Ubuntu 26.04 with KiCad 9.0.8 and pymupdf 2.1), they share one runtime type
table. Each module's ``SwigPyIterator_swigregister`` call stores its own Python
proxy class for ``swig::SwigPyIterator`` there, and the last module to load
wins: iterators created by either module then use that class. Builds on
different runtime versions (for example pcbnew on ``swig_runtime_data4``) keep
separate tables and are not affected.

pymupdf's ``SwigPyIterator`` has ``__next__`` but no ``next()`` method, while
pcbnew's container wrappers step through items with ``it.next()``. So when
pymupdf is imported *after* pcbnew (``get_board_2d_view`` and the schematic
view rasterize with it on first use), every later iteration over
``BOARD.GetDrawings()``, ``BOARD.GetTracks()``,
``FOOTPRINT.GraphicalItems()`` and similar containers raises::

    AttributeError: 'SwigPyIterator' object has no attribute 'next'

until the Python process restarts.

Two defences, both safe on unaffected builds:

* ``preload_pymupdf()`` imports pymupdf before pcbnew at server startup, so
  pcbnew registers last.
* ``restore_pcbnew_iterator()`` re-registers pcbnew's class after pymupdf has
  loaded, which fixes the table whatever the import order. pcbnew's class has
  both ``next()`` and ``__next__``, so pymupdf's own containers keep iterating.

This module needs only the standard library so it can run before pcbnew loads.
"""

import logging
import sys

logger = logging.getLogger("kicad_interface")


def restore_pcbnew_iterator() -> bool:
    """Make pcbnew's ``SwigPyIterator`` class the registered one again.

    Call it right after importing pymupdf (``fitz``). It does nothing when
    pcbnew has not been imported, and it never imports pcbnew itself. Returns
    True if the class was re-registered.
    """
    pcbnew = sys.modules.get("pcbnew")
    if pcbnew is None:
        return False
    try:
        pcbnew._pcbnew.SwigPyIterator_swigregister(pcbnew.SwigPyIterator)
    except Exception as e:  # missing in an unusual build: leave the table as it is
        logger.debug(f"Could not re-register pcbnew SwigPyIterator: {e}")
        return False
    return True


def preload_pymupdf() -> bool:
    """Import pymupdf ahead of pcbnew. Return True if pymupdf is loaded.

    Meant to run before the first ``import pcbnew``. If pcbnew is already
    loaded, it also re-registers pcbnew's iterator class. A missing or broken
    pymupdf is not an error: the image tools fall back to other rasterizers.
    """
    try:
        import pymupdf  # noqa: F401
    except Exception as e:  # ImportError, or a broken native library
        logger.info(f"pymupdf not preloaded ({e}); image rendering will use fallbacks")
        return False
    restore_pcbnew_iterator()
    return True
