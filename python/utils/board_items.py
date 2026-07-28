"""Safe deletion of items from a pcbnew BOARD.

Why this module exists (issue #247)
-----------------------------------
``BOARD.Remove()`` is **not** the API for deleting an item. KiCad's own SWIG
wrapper documents what it does (``pcbnew.py``, ``BOARD_ITEM_CONTAINER``)::

    def Remove(self, item):
        \"\"\"Remove a BOARD_ITEM ... set the thisdown flag so that the python
        wrapper owns the C++ BOARD_ITEM\"\"\"
        self.RemoveNative(item)
        if (not IsActionRunning()):
            item.thisown = 1          # <-- Python now owns the C++ object

    def Delete(self, item):
        \"\"\"Remove a BOARD_ITEM ... set the thisdown flag so that the python
        wrapper does not owns the C++ BOARD_ITEM\"\"\"
        item.thisown = 0              # C++ will free it
        self.DeleteNative(item)
        item.this = None

``Remove()`` hands ownership to Python because it is meant for *detaching* an
item you intend to keep or re-add. Code that removes an item and then drops
the reference makes the interpreter run the C++ destructor on an object
KiCad's structures still point at.

Observed consequence on KiCad 10.0 (reproduced against a real install):

* a single ``delete_component`` followed by the next board operation raises
  ``'SwigPyObject' object has no attribute 'thisown'``,
* pure reads fail too — ``'SwigPyObject' object has no attribute 'GetPosition'``,
* the damage is **process-wide**, not board-scoped: even ``pcbnew.FootprintLoad``
  degrades, because SWIG's type registry itself is corrupted,
* on some builds the process segfaults outright instead.

The board object keeps working, which is why the existing
``_is_board_healthy()`` probe never noticed: it only checks BOARD-level
methods, and the BOARD is fine. It is the items it hands back that are dead.

Using ``Delete()`` avoids the whole failure mode: ownership stays in C++, and
the item is freed by the code that knows how.
"""

import logging
from typing import Any

logger = logging.getLogger("kicad_interface")


def clone_footprint(footprint: Any) -> Any:
    """Return an independent copy of ``footprint``, ready for ``board.Add()``.

    Used to load a footprint from disk once and stamp out many instances
    (#248): ``FootprintLoad`` costs the same on every call, so a board with
    thirteen identical resistors otherwise paid for thirteen identical disk
    reads. Cloning is ~1000x cheaper than reloading.

    Two portability wrinkles, both verified against a real KiCad 10.0 install:

    * ``Duplicate()`` gained a required ``addToParentGroup`` argument in
      KiCad 10; KiCad 8/9 take none.
    * It returns a ``BOARD_ITEM`` — SWIG does not down-cast automatically, so
      the result has no ``SetReference``/``SetValue`` until it is passed
      through ``Cast_to_FOOTPRINT``.

    The caller must keep the prototype out of the board: handing it to
    ``board.Add()`` would leave the cache holding a board-owned object.
    """
    import pcbnew  # local: keeps this module importable without KiCad

    try:
        duplicate = footprint.Duplicate(False)  # KiCad 10
    except TypeError:
        duplicate = footprint.Duplicate()  # KiCad 8/9

    if not hasattr(duplicate, "SetReference"):
        cast = getattr(pcbnew, "Cast_to_FOOTPRINT", None)
        if cast is not None:
            duplicate = cast(duplicate)
    return duplicate


def delete_board_item(board: Any, item: Any) -> None:
    """Detach ``item`` from ``board`` and let C++ destroy it.

    Prefers ``BOARD.Delete()``. Falls back to ``Remove()`` plus an explicit
    ``thisown = False`` on builds (or test doubles) that expose no ``Delete``
    — that combination was verified to be equally safe, since the danger is
    solely Python owning and then freeing the C++ object.

    Never raises for a missing ``thisown`` attribute; a caller deleting an
    item must not fail because a proxy lacked a SWIG bookkeeping field.
    """
    delete = getattr(board, "Delete", None)
    if callable(delete):
        delete(item)
        return

    logger.debug("BOARD.Delete unavailable; falling back to Remove + disown")
    board.Remove(item)
    try:
        item.thisown = False
    except AttributeError:
        # Already a raw SwigPyObject, or a mock without the attribute. The
        # Remove() above has still detached it; there is nothing more to do.
        pass
