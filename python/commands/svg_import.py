"""
SVG Logo Import for KiCAD PCB

Converts an SVG file into KiCAD PCB graphic polygons (gr_poly) on the silkscreen
or any other given layer. Uses only Python standard library (xml, re, math).
No external dependencies required.

Supported SVG elements:
  <path d="...">           M L H V Z C S Q T A commands (curves are linearised)
  <rect>                   → 4-point polygon
  <circle>                 → N-gon approximation
  <polygon> / <polyline>  → direct point list
  <g> with transform       → nested group transforms are applied

SVG coordinate system: Y increases downward (same as KiCAD mm), so no Y-flip needed.
"""

import re
import math
import uuid
import os
import logging
from typing import List, Tuple, Dict, Any, Optional
import xml.etree.ElementTree as ET

logger = logging.getLogger("kicad_interface")

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------
Point = Tuple[float, float]
Polygon = List[Point]

# ---------------------------------------------------------------------------
# SVG path tokenizer
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(
    r"([MmZzLlHhVvCcSsQqTtAa])|([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
)


def _tokenize_path(d: str) -> List[str]:
    tokens = []
    for tok, num in _TOKEN_RE.findall(d):
        if tok:
            tokens.append(tok)
        elif num:
            tokens.append(num)
    return tokens


def _parse_path_tokens(tokens: List[str]) -> List[Polygon]:
    """
    Parse SVG path tokens into a list of closed and open subpaths.
    Curves are linearised with ~0.5 mm step tolerance.
    Returns a list of point-lists (each is a subpath/polygon).
    """
    polygons: List[Polygon] = []
    current: Polygon = []
    cx, cy = 0.0, 0.0   # current point
    sx, sy = 0.0, 0.0   # subpath start
    last_ctrl = None      # last bezier control point (for S/T commands)
    last_cmd = ""

    i = 0
    cmd = "M"
    num_tokens = []

    # --- helpers ---
    def consume(n: int) -> List[float]:
        nonlocal i
        vals = [float(tokens[i + k]) for k in range(n)]
        i += n
        return vals

    def cubic_bezier_points(p0: Point, p1: Point, p2: Point, p3: Point, steps: int = 16) -> List[Point]:
        pts = []
        for k in range(1, steps + 1):
            t = k / steps
            mt = 1 - t
            x = mt**3*p0[0] + 3*mt**2*t*p1[0] + 3*mt*t**2*p2[0] + t**3*p3[0]
            y = mt**3*p0[1] + 3*mt**2*t*p1[1] + 3*mt*t**2*p2[1] + t**3*p3[1]
            pts.append((x, y))
        return pts

    def quad_bezier_points(p0: Point, p1: Point, p2: Point, steps: int = 12) -> List[Point]:
        pts = []
        for k in range(1, steps + 1):
            t = k / steps
            mt = 1 - t
            x = mt**2*p0[0] + 2*mt*t*p1[0] + t**2*p2[0]
            y = mt**2*p0[1] + 2*mt*t*p1[1] + t**2*p2[1]
            pts.append((x, y))
        return pts

    def arc_points(x1: float, y1: float, rx: float, ry: float, phi_deg: float,
                   large_arc: int, sweep: int, x2: float, y2: float, steps: int = 20) -> List[Point]:
        """Approximate SVG arc as polygon points (endpoint parameterization → centre)."""
        if rx == 0 or ry == 0:
            return [(x2, y2)]
        phi = math.radians(phi_deg)
        cos_phi, sin_phi = math.cos(phi), math.sin(phi)
        dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
        x1p = cos_phi * dx + sin_phi * dy
        y1p = -sin_phi * dx + cos_phi * dy
        rx, ry = abs(rx), abs(ry)
        lam = (x1p / rx)**2 + (y1p / ry)**2
        if lam > 1:
            lam = math.sqrt(lam)
            rx *= lam
            ry *= lam
        num = max(0.0, (rx*ry)**2 - (rx*y1p)**2 - (ry*x1p)**2)
        den = (rx*y1p)**2 + (ry*x1p)**2
        sq = math.sqrt(num / den) if den != 0 else 0
        if large_arc == sweep:
            sq = -sq
        cxp = sq * rx * y1p / ry
        cyp = -sq * ry * x1p / rx
        cx_ = cos_phi * cxp - sin_phi * cyp + (x1 + x2) / 2
        cy_ = sin_phi * cxp + cos_phi * cyp + (y1 + y2) / 2

        def angle(ux, uy, vx, vy):
            a = math.acos(max(-1, min(1, (ux*vx + uy*vy) / (math.hypot(ux, uy) * math.hypot(vx, vy)))))
            if ux*vy - uy*vx < 0:
                a = -a
            return a

        theta1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
        dtheta = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
        if not sweep and dtheta > 0:
            dtheta -= 2 * math.pi
        elif sweep and dtheta < 0:
            dtheta += 2 * math.pi

        pts = []
        for k in range(1, steps + 1):
            t = k / steps
            angle_ = theta1 + t * dtheta
            x_ = cos_phi * rx * math.cos(angle_) - sin_phi * ry * math.sin(angle_) + cx_
            y_ = sin_phi * rx * math.cos(angle_) + cos_phi * ry * math.sin(angle_) + cy_
            pts.append((x_, y_))
        return pts

    # --- main loop ---
    while i < len(tokens):
        tok = tokens[i]
        if tok.lstrip('+-').replace('.', '', 1).replace('e', '', 1).replace('E', '', 1).lstrip('+-').isdigit() or \
           re.match(r'^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$', tok):
            # implicit repeat of last command
            pass
        else:
            cmd = tok
            i += 1
            last_ctrl = None  # reset smooth control on new command letter

        rel = cmd.islower()

        if cmd in ('M', 'm'):
            x, y = consume(2)
            if rel:
                cx, cy = cx + x, cy + y
            else:
                cx, cy = x, y
            if current:
                polygons.append(current)
            current = [(cx, cy)]
            sx, sy = cx, cy
            # subsequent coordinates are implicit L/l
            cmd = 'l' if rel else 'L'

        elif cmd in ('L', 'l'):
            x, y = consume(2)
            if rel:
                cx, cy = cx + x, cy + y
            else:
                cx, cy = x, y
            current.append((cx, cy))

        elif cmd in ('H', 'h'):
            x = float(tokens[i]); i += 1
            cx = cx + x if rel else x
            current.append((cx, cy))

        elif cmd in ('V', 'v'):
            y = float(tokens[i]); i += 1
            cy = cy + y if rel else y
            current.append((cx, cy))

        elif cmd in ('Z', 'z'):
            current.append((sx, sy))  # close
            polygons.append(current)
            current = []
            cx, cy = sx, sy

        elif cmd in ('C', 'c'):
            x1, y1, x2, y2, x, y = consume(6)
            if rel:
                x1 += cx; y1 += cy; x2 += cx; y2 += cy; x += cx; y += cy
            pts = cubic_bezier_points((cx, cy), (x1, y1), (x2, y2), (x, y))
            current.extend(pts)
            last_ctrl = (x2, y2)
            cx, cy = x, y

        elif cmd in ('S', 's'):
            x2, y2, x, y = consume(4)
            if rel:
                x2 += cx; y2 += cy; x += cx; y += cy
            if last_ctrl and last_cmd in ('C', 'c', 'S', 's'):
                x1 = 2 * cx - last_ctrl[0]
                y1 = 2 * cy - last_ctrl[1]
            else:
                x1, y1 = cx, cy
            pts = cubic_bezier_points((cx, cy), (x1, y1), (x2, y2), (x, y))
            current.extend(pts)
            last_ctrl = (x2, y2)
            cx, cy = x, y

        elif cmd in ('Q', 'q'):
            x1, y1, x, y = consume(4)
            if rel:
                x1 += cx; y1 += cy; x += cx; y += cy
            pts = quad_bezier_points((cx, cy), (x1, y1), (x, y))
            current.extend(pts)
            last_ctrl = (x1, y1)
            cx, cy = x, y

        elif cmd in ('T', 't'):
            x, y = consume(2)
            if rel:
                x += cx; y += cy
            if last_ctrl and last_cmd in ('Q', 'q', 'T', 't'):
                x1 = 2 * cx - last_ctrl[0]
                y1 = 2 * cy - last_ctrl[1]
            else:
                x1, y1 = cx, cy
            pts = quad_bezier_points((cx, cy), (x1, y1), (x, y))
            current.extend(pts)
            last_ctrl = (x1, y1)
            cx, cy = x, y

        elif cmd in ('A', 'a'):
            rx, ry, phi, large, sweep, x, y = consume(7)
            large, sweep = int(large), int(sweep)
            if rel:
                x += cx; y += cy
            pts = arc_points(cx, cy, rx, ry, phi, large, sweep, x, y)
            current.extend(pts)
            cx, cy = x, y

        else:
            # Unknown command — skip one token
            i += 1

        last_cmd = cmd.upper()

    if current:
        polygons.append(current)

    return [p for p in polygons if len(p) >= 2]


# ---------------------------------------------------------------------------
# Transform parsing
# ---------------------------------------------------------------------------
def _parse_transform(transform_str: str) -> List[List[float]]:
    """Parse SVG transform attribute, return list of 3×3 matrix rows [a,b,c; d,e,f; 0,0,1]."""
    def identity():
        return [[1, 0, 0], [0, 1, 0], [0, 0, 1]]

    def mat_mul(A, B):
        return [
            [sum(A[r][k] * B[k][c] for k in range(3)) for c in range(3)]
            for r in range(3)
        ]

    result = identity()
    for m in re.finditer(
        r'(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)',
        transform_str
    ):
        func = m.group(1)
        args = [float(v) for v in re.split(r'[\s,]+', m.group(2).strip()) if v]
        mat = identity()
        if func == 'matrix' and len(args) == 6:
            a, b, c, d, e, f = args
            mat = [[a, c, e], [b, d, f], [0, 0, 1]]
        elif func == 'translate':
            tx = args[0]
            ty = args[1] if len(args) > 1 else 0
            mat = [[1, 0, tx], [0, 1, ty], [0, 0, 1]]
        elif func == 'scale':
            sx = args[0]
            sy = args[1] if len(args) > 1 else sx
            mat = [[sx, 0, 0], [0, sy, 0], [0, 0, 1]]
        elif func == 'rotate':
            angle = math.radians(args[0])
            cos, sin = math.cos(angle), math.sin(angle)
            if len(args) == 3:
                cx_, cy_ = args[1], args[2]
                t1 = [[1, 0, cx_], [0, 1, cy_], [0, 0, 1]]
                r  = [[cos, -sin, 0], [sin, cos, 0], [0, 0, 1]]
                t2 = [[1, 0, -cx_], [0, 1, -cy_], [0, 0, 1]]
                mat = mat_mul(mat_mul(t1, r), t2)
            else:
                mat = [[cos, -sin, 0], [sin, cos, 0], [0, 0, 1]]
        elif func == 'skewX':
            mat = [[1, math.tan(math.radians(args[0])), 0], [0, 1, 0], [0, 0, 1]]
        elif func == 'skewY':
            mat = [[1, 0, 0], [math.tan(math.radians(args[0])), 1, 0], [0, 0, 1]]
        result = mat_mul(result, mat)
    return result


def _apply_transform(pts: List[Point], mat: List[List[float]]) -> List[Point]:
    out = []
    for x, y in pts:
        nx = mat[0][0] * x + mat[0][1] * y + mat[0][2]
        ny = mat[1][0] * x + mat[1][1] * y + mat[1][2]
        out.append((nx, ny))
    return out


def _mat_mul(A, B):
    return [
        [sum(A[r][k] * B[k][c] for k in range(3)) for c in range(3)]
        for r in range(3)
    ]


# ---------------------------------------------------------------------------
# SVG element → polygon extractor
# ---------------------------------------------------------------------------
SVG_NS = re.compile(r'\{[^}]+\}')


def _tag(el: ET.Element) -> str:
    return SVG_NS.sub('', el.tag)


def _get_attr(el: ET.Element, name: str, default: Optional[str] = None) -> Optional[str]:
    for key in el.attrib:
        if SVG_NS.sub('', key) == name:
            return el.attrib[key]
    return default


def _identity():
    return [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


def _extract_polygons_from_element(el: ET.Element, parent_mat: List[List[float]]) -> List[Polygon]:
    """Recursively extract all polygons from an SVG element tree."""
    tag = _tag(el)
    display = _get_attr(el, 'display', 'inline')
    visibility = _get_attr(el, 'visibility', 'visible')
    if display == 'none' or visibility == 'hidden':
        return []

    # Accumulate transform
    transform_str = _get_attr(el, 'transform', '')
    if transform_str:
        local_mat = _parse_transform(transform_str)
        mat = _mat_mul(parent_mat, local_mat)
    else:
        mat = parent_mat

    result: List[Polygon] = []

    if tag == 'g' or tag == 'svg':
        for child in el:
            result.extend(_extract_polygons_from_element(child, mat))

    elif tag == 'path':
        d = _get_attr(el, 'd', '')
        if d:
            tokens = _tokenize_path(d)
            polygons = _parse_path_tokens(tokens)
            for poly in polygons:
                result.append(_apply_transform(poly, mat))

    elif tag == 'rect':
        x = float(_get_attr(el, 'x', '0') or 0)
        y = float(_get_attr(el, 'y', '0') or 0)
        w = float(_get_attr(el, 'width', '0') or 0)
        h = float(_get_attr(el, 'height', '0') or 0)
        if w > 0 and h > 0:
            pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
            result.append(_apply_transform(pts, mat))

    elif tag == 'circle':
        cx_ = float(_get_attr(el, 'cx', '0') or 0)
        cy_ = float(_get_attr(el, 'cy', '0') or 0)
        r = float(_get_attr(el, 'r', '0') or 0)
        if r > 0:
            steps = 36
            pts = [(cx_ + r * math.cos(2 * math.pi * k / steps),
                    cy_ + r * math.sin(2 * math.pi * k / steps))
                   for k in range(steps + 1)]
            result.append(_apply_transform(pts, mat))

    elif tag == 'ellipse':
        cx_ = float(_get_attr(el, 'cx', '0') or 0)
        cy_ = float(_get_attr(el, 'cy', '0') or 0)
        rx = float(_get_attr(el, 'rx', '0') or 0)
        ry = float(_get_attr(el, 'ry', '0') or 0)
        if rx > 0 and ry > 0:
            steps = 36
            pts = [(cx_ + rx * math.cos(2 * math.pi * k / steps),
                    cy_ + ry * math.sin(2 * math.pi * k / steps))
                   for k in range(steps + 1)]
            result.append(_apply_transform(pts, mat))

    elif tag in ('polygon', 'polyline'):
        points_str = _get_attr(el, 'points', '')
        if points_str:
            nums = [float(v) for v in re.split(r'[\s,]+', points_str.strip()) if v]
            pts = [(nums[k], nums[k + 1]) for k in range(0, len(nums) - 1, 2)]
            if tag == 'polygon' and pts:
                pts.append(pts[0])  # close
            if pts:
                result.append(_apply_transform(pts, mat))

    elif tag == 'line':
        x1 = float(_get_attr(el, 'x1', '0') or 0)
        y1 = float(_get_attr(el, 'y1', '0') or 0)
        x2 = float(_get_attr(el, 'x2', '0') or 0)
        y2 = float(_get_attr(el, 'y2', '0') or 0)
        pts = [(x1, y1), (x2, y2)]
        result.append(_apply_transform(pts, mat))

    return result


# ---------------------------------------------------------------------------
# Bounding box helper
# ---------------------------------------------------------------------------
def _bounding_box(polygons: List[Polygon]) -> Tuple[float, float, float, float]:
    all_x = [p[0] for poly in polygons for p in poly]
    all_y = [p[1] for poly in polygons for p in poly]
    return min(all_x), min(all_y), max(all_x), max(all_y)


# ---------------------------------------------------------------------------
# gr_poly builder
# ---------------------------------------------------------------------------
def _build_gr_poly(points: List[Point], layer: str, stroke_width: float, filled: bool) -> str:
    pts_lines = []
    row: List[str] = []
    for i, (x, y) in enumerate(points):
        row.append(f"(xy {x:.6f} {y:.6f})")
        if len(row) == 4 or i == len(points) - 1:
            pts_lines.append("\t\t\t" + " ".join(row))
            row = []
    fill_str = "yes" if filled else "none"
    uid = str(uuid.uuid4())
    lines = [
        "\t(gr_poly",
        "\t\t(pts",
    ] + pts_lines + [
        "\t\t)",
        "\t\t(stroke",
        f"\t\t\t(width {stroke_width:.4f})",
        "\t\t\t(type solid)",
        "\t\t)",
        f"\t\t(fill {fill_str})",
        f'\t\t(layer "{layer}")',
        f'\t\t(uuid "{uid}")',
        "\t)",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------
def import_svg_to_pcb(
    pcb_path: str,
    svg_path: str,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    layer: str = "F.SilkS",
    stroke_width: float = 0.0,
    filled: bool = True,
) -> Dict[str, Any]:
    """
    Import an SVG file as graphic polygons into a KiCAD PCB file.

    Args:
        pcb_path:     Path to .kicad_pcb file (will be edited in place)
        svg_path:     Path to SVG file
        x_mm:         X position of logo top-left in mm
        y_mm:         Y position of logo top-left in mm
        width_mm:     Desired width of the logo in mm (aspect ratio preserved)
        layer:        PCB layer name, e.g. "F.SilkS" or "B.SilkS"
        stroke_width: Outline stroke width in mm (0 = no outline)
        filled:       Fill polygons (True) or outline only (False)

    Returns:
        dict with keys: success, message, polygon_count
    """
    if not os.path.exists(pcb_path):
        return {"success": False, "message": f"PCB file not found: {pcb_path}"}
    if not os.path.exists(svg_path):
        return {"success": False, "message": f"SVG file not found: {svg_path}"}

    try:
        # --- 1. Parse SVG ---
        tree = ET.parse(svg_path)
        root = tree.getroot()

        # Determine SVG viewport
        vb = _get_attr(root, 'viewBox')
        if vb:
            parts = [float(v) for v in re.split(r'[\s,]+', vb.strip()) if v]
            svg_x0, svg_y0, svg_w, svg_h = parts[0], parts[1], parts[2], parts[3]
        else:
            w_str = _get_attr(root, 'width', '100') or '100'
            h_str = _get_attr(root, 'height', '100') or '100'
            svg_w = float(re.sub(r'[^\d.]', '', w_str) or 100)
            svg_h = float(re.sub(r'[^\d.]', '', h_str) or 100)
            svg_x0, svg_y0 = 0.0, 0.0

        if svg_w == 0 or svg_h == 0:
            return {"success": False, "message": "SVG has zero width or height"}

        # --- 2. Extract all polygons ---
        polygons = _extract_polygons_from_element(root, _identity())

        if not polygons:
            return {"success": False, "message": "No drawable shapes found in SVG"}

        # --- 3. Compute bounding box of extracted polygons ---
        bx_min, by_min, bx_max, by_max = _bounding_box(polygons)
        poly_w = bx_max - bx_min
        poly_h = by_max - by_min

        if poly_w == 0:
            return {"success": False, "message": "SVG shapes have zero width"}

        # --- 4. Scale and translate to target position ---
        scale = width_mm / poly_w
        height_mm = poly_h * scale

        scaled: List[Polygon] = []
        for poly in polygons:
            pts: List[Point] = []
            for px, py in poly:
                nx = x_mm + (px - bx_min) * scale
                ny = y_mm + (py - by_min) * scale
                pts.append((nx, ny))
            scaled.append(pts)

        # --- 5. Build gr_poly strings ---
        gr_lines = []
        for poly in scaled:
            if len(poly) < 2:
                continue
            gr_lines.append(_build_gr_poly(poly, layer, stroke_width, filled))

        if not gr_lines:
            return {"success": False, "message": "No valid polygons after scaling"}

        # --- 6. Inject into PCB file ---
        with open(pcb_path, "r", encoding="utf-8") as f:
            pcb_content = f.read()

        # Insert before the final closing ')' of the kicad_pcb block
        insert_block = "\n" + "\n".join(gr_lines) + "\n"
        last_paren = pcb_content.rfind(")")
        if last_paren == -1:
            return {"success": False, "message": "PCB file format error: no closing parenthesis found"}

        new_content = pcb_content[:last_paren] + insert_block + pcb_content[last_paren:]

        with open(pcb_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        logger.info(f"SVG logo import: wrote {len(gr_lines)} polygons to {pcb_path}")

        return {
            "success": True,
            "message": (
                f"Imported {len(gr_lines)} polygon(s) from SVG onto layer '{layer}'. "
                f"Logo size: {width_mm:.2f} × {height_mm:.2f} mm at ({x_mm}, {y_mm})."
            ),
            "polygon_count": len(gr_lines),
            "logo_width_mm": round(width_mm, 4),
            "logo_height_mm": round(height_mm, 4),
            "position": {"x": x_mm, "y": y_mm},
            "layer": layer,
        }

    except ET.ParseError as e:
        logger.error(f"SVG parse error: {e}")
        return {"success": False, "message": f"SVG parse error: {e}"}
    except Exception as e:
        logger.error(f"SVG import failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"success": False, "message": str(e)}
