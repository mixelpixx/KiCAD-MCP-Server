"""One text-size model for the schematic layout tools.

``schematic_declutter``, ``schematic_field_layout`` and ``schematic_legibility``
all need to know how much of the sheet a piece of text takes. Three slightly
different models gave three different answers about the same label, so the
numbers live here and the tools share them.

The advance per character was measured off KiCad renders of a released
three-sheet design (AP63205WU, "U10 SW", "22uF 10V"): KiCad's stroke font
advances about 0.95 x the text size per character at the default 1.27 mm. The
box height is 1.2 x the size (ascenders and descenders). A global or
hierarchical label also has its flag outline, about 1.5 x the size wider than
its text.

Boxes are axis-aligned, in sheet mm with y down, and the dict form
(``x_min``/``y_min``/``x_max``/``y_max``) is the one the layout tools pass
around.
"""

from typing import Dict

DEFAULT_SIZE = 1.27  # KiCad's default schematic text size, mm
CHAR_ADVANCE = 0.95  # width per character, x text size
LINE_HEIGHT = 1.2  # box height, x text size
LABEL_FLAG = 1.5  # extra width of a global/hierarchical label's flag outline, x text size


def text_width(text: str, size: float = DEFAULT_SIZE) -> float:
    """Width of one line of text (an empty string takes one character)."""
    return max(len(text), 1) * size * CHAR_ADVANCE


def text_height(size: float = DEFAULT_SIZE) -> float:
    """Height of one line of text."""
    return size * LINE_HEIGHT


def label_bbox(
    lx: float, ly: float, angle: float, name: str, size: float = DEFAULT_SIZE, margin: float = 0.0
) -> Dict[str, float]:
    """Box of a net label anchored at (lx, ly) for one of the four orientations.

    The text runs away from the anchor along the label's direction: +x at 0
    (justify left), up at 90, -x at 180 (justify right), down at 270. *margin*
    lengthens the box for callers that keep labels apart (the layout tools use
    1 mm so neighbouring labels never touch).
    """
    length = text_width(name, size) + margin
    half_h = text_height(size) / 2.0
    a = round(angle / 90) * 90 % 360
    if a == 0:
        return {"x_min": lx, "y_min": ly - half_h, "x_max": lx + length, "y_max": ly + half_h}
    if a == 90:
        return {"x_min": lx - half_h, "y_min": ly - length, "x_max": lx + half_h, "y_max": ly}
    if a == 180:
        return {"x_min": lx - length, "y_min": ly - half_h, "x_max": lx, "y_max": ly + half_h}
    return {"x_min": lx - half_h, "y_min": ly, "x_max": lx + half_h, "y_max": ly + length}


def field_bbox(fx: float, fy: float, text: str, size: float = DEFAULT_SIZE) -> Dict[str, float]:
    """Box of a horizontal field centred on (fx, fy)."""
    half_w = text_width(str(text), size) / 2.0
    half_h = text_height(size) / 2.0
    return {"x_min": fx - half_w, "y_min": fy - half_h, "x_max": fx + half_w, "y_max": fy + half_h}
