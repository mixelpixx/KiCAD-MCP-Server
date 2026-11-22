"""The reference a schematic placement writes, shared by the single and batch tools.

A power symbol (``power:GND``, or a project-library symbol with the ``(power)``
flag) placed without a reference, or with the ``#PWR?`` placeholder, gets the
next unused ``#PWRnn`` in the project (``power:PWR_FLAG``: ``#FLGnn``), counting
every sheet and every instance path (#524). Every other symbol needs an explicit
reference: leaving it out used to place a part silently named ``X?``.

``add_schematic_component`` and the batch tools (``batch_add_components``,
``batch_add_and_connect``) both resolve references here, so the two cannot
drift apart again.
"""

import logging
from pathlib import Path
from typing import Any, Optional, Tuple

from utils.sheet_tree import instance_paths
from utils.symbol_instances import (
    ReferenceAllocator,
    definition_is_power,
    power_lib_ids,
    project_references,
)

logger = logging.getLogger("kicad_interface")

# A reference that names nothing: the caller left it out.
_NO_REFERENCE = (None, "", "X?")
# Placeholders a power symbol may be given instead of a number.
_POWER_PLACEHOLDERS = ("#PWR?", "#PWR", "#FLG?", "#FLG")


def allocate_power_reference(schematic_file: Path, prefix: str = "#PWR") -> Optional[str]:
    """The next unused ``{prefix}nn`` in the schematic's project (#524).

    Counts every reference on every sheet the root reaches, so a number
    taken on another sheet is never re-picked. It reads the file from disk,
    so a batch that writes each placement before the next gets a new number
    each time. Returns None when the project cannot be read, so the caller
    can fall back to the given reference instead of failing the placement.
    """
    try:
        root, _paths = instance_paths(schematic_file)
        return ReferenceAllocator(project_references(root, schematic_file)).next_free(
            prefix, zero=True
        )
    except Exception as e:
        logger.warning("Could not allocate a %s reference for %s: %s", prefix, schematic_file, e)
        return None


def is_power_symbol(loader: Any, schematic_file: Path, library: str, comp_type: str) -> bool:
    """True when ``library:comp_type`` is a power symbol (#524).

    The ``power:`` library prefix is the usual sign, but a project-library
    symbol can carry the ``(power)`` flag instead. That is checked two ways,
    both read-only: the schematic's own ``lib_symbols`` (the definition is
    already there when the symbol was placed before) and the library
    definition itself (via the loader's cached extraction, which is also how
    the placement resolves the symbol, so a first placement is recognised
    too). A symbol neither check recognises is treated as non-power.
    """
    lib_id = f"{library}:{comp_type}"
    if lib_id.lower().startswith("power:"):
        return True
    try:
        if lib_id.lower() in {
            known.lower() for known in power_lib_ids(schematic_file.read_text(encoding="utf-8"))
        }:
            return True
    except Exception:
        pass
    try:
        block = loader.extract_symbol_from_library(library, comp_type)
    except Exception:
        block = None
    return bool(block) and definition_is_power(block)


def resolve_placement_reference(
    loader: Any, schematic_file: Path, library: str, comp_type: str, reference: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    """``(reference, None)`` to place with, or ``(None, error)`` to refuse.

    An explicit reference other than a placeholder is returned unchanged, and
    the power check runs only when the caller gave no usable reference. A
    power symbol's placeholder becomes the next free number; if the project
    cannot be read, the placeholder is kept rather than failing the placement.
    A non-power symbol without a reference is refused.
    """
    if reference not in _NO_REFERENCE and reference not in _POWER_PLACEHOLDERS:
        return reference, None
    if is_power_symbol(loader, schematic_file, library, comp_type):
        prefix = "#FLG" if comp_type.lower() == "pwr_flag" else "#PWR"
        if reference in _NO_REFERENCE or reference in (f"{prefix}?", prefix):
            allocated = allocate_power_reference(schematic_file, prefix)
            if allocated is not None:
                return allocated, None
            if reference in _NO_REFERENCE:
                return f"{prefix}?", None
        return reference, None
    if reference in _NO_REFERENCE:
        return None, (
            f"Reference is required for {library}:{comp_type}: omit it only for power "
            "symbols (power:GND, …), which are allocated the next free #PWRnn "
            "(power:PWR_FLAG: #FLGnn)."
        )
    return reference, None
