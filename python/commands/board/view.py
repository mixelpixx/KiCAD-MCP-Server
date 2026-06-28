"""
Board view command implementations for KiCAD interface
"""

import base64
import io
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import pcbnew
from PIL import Image

logger = logging.getLogger("kicad_interface")


def _svg_to_png(svg_path: str, width: int, height: int) -> Optional[bytes]:
    """Convert SVG to PNG. No cffi dependency.

    Priority:
      1. pymupdf (fitz) — bundled MuPDF renderer, pure Python, no system deps
      2. Inkscape CLI — accurate KiCAD SVG rendering
      3. ImageMagick convert — broad availability fallback
    Returns PNG bytes or None if all converters fail.
    """
    import subprocess
    import tempfile

    try:
        import fitz

        doc = fitz.open(svg_path)
        page = doc[0]
        mat = fitz.Matrix(width / page.rect.width, height / page.rect.height)
        return page.get_pixmap(matrix=mat).tobytes("png")
    except Exception:
        pass

    out_path = os.path.join(tempfile.mkdtemp(), "out.png")

    try:
        r = subprocess.run(
            [
                "inkscape",
                svg_path,
                "--export-type=png",
                f"--export-width={width}",
                f"--export-height={height}",
                f"--export-filename={out_path}",
            ],
            capture_output=True,
            timeout=60,
        )
        if r.returncode == 0 and os.path.exists(out_path):
            with open(out_path, "rb") as f:
                return f.read()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        r = subprocess.run(
            ["convert", "-density", "150", svg_path, "-resize", f"{width}x{height}", out_path],
            capture_output=True,
            timeout=60,
        )
        if r.returncode == 0 and os.path.exists(out_path):
            with open(out_path, "rb") as f:
                return f.read()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


class BoardViewCommands:
    """Handles board viewing operations"""

    def __init__(self, board: Optional[pcbnew.BOARD] = None):
        """Initialize with optional board instance"""
        self.board = board

    def get_board_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get information about the current board"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # Get board dimensions
            board_box = self.board.GetBoardEdgesBoundingBox()
            width_nm = board_box.GetWidth()
            height_nm = board_box.GetHeight()

            # Convert to mm
            width_mm = width_nm / 1000000
            height_mm = height_nm / 1000000

            # Get layer information
            layers = []
            for layer_id in range(pcbnew.PCB_LAYER_ID_COUNT):
                if self.board.IsLayerEnabled(layer_id):
                    layers.append(
                        {
                            "name": self.board.GetLayerName(layer_id),
                            "type": self._get_layer_type_name(self.board.GetLayerType(layer_id)),
                            "id": layer_id,
                        }
                    )

            return {
                "success": True,
                "board": {
                    "filename": self.board.GetFileName(),
                    "size": {"width": width_mm, "height": height_mm, "unit": "mm"},
                    "layers": layers,
                    "title": self.board.GetTitleBlock().GetTitle(),
                    # Note: activeLayer removed - GetActiveLayer() doesn't exist in KiCAD 9.0
                    # Active layer is a UI concept not applicable to headless scripting
                },
            }

        except Exception as e:
            logger.error(f"Error getting board info: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get board information",
                "errorDetails": str(e),
            }

    def get_board_2d_view(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Render PCB to PNG/JPG/SVG via kicad-cli (no pcbnew/cffi dependency).

        responseMode controls how the image is returned:
        - "inline" (default): image bytes are base64-encoded and returned as ``imageData``.
        - "file": image is written next to the .kicad_pcb file and ``filePath`` is returned.
        """
        import glob
        import shutil
        import subprocess
        import tempfile

        try:
            pcb_path = params.get("pcbPath")
            if not pcb_path:
                if self.board:
                    pcb_path = self.board.GetFileName()
                if not pcb_path:
                    return {
                        "success": False,
                        "message": "pcbPath required",
                        "errorDetails": "Provide pcbPath or load a board first",
                    }

            if not os.path.exists(pcb_path):
                return {
                    "success": False,
                    "message": f"PCB file not found: {pcb_path}",
                    "errorDetails": pcb_path,
                }

            width = params.get("width", 1600)
            height = params.get("height", 1200)
            fmt = params.get("format", "png")
            if fmt not in ("png", "jpg", "svg"):
                return {
                    "success": False,
                    "message": f"Unsupported format '{fmt}'. Use 'png', 'jpg', or 'svg'.",
                    "errorDetails": f"Got: {fmt}",
                }
            layers: List[str] = params.get("layers", [])
            response_mode = params.get("responseMode", "inline")

            kicad_cli = shutil.which("kicad-cli") or shutil.which("kicad-cli.exe")
            if not kicad_cli:
                return {
                    "success": False,
                    "message": "kicad-cli not found in PATH",
                    "errorDetails": "Install KiCad and ensure kicad-cli is on PATH",
                }

            with tempfile.TemporaryDirectory() as tmpdir:
                # KiCad 10 changed `pcb export svg`:
                #  - `--output` is now a FILE path, not a directory (a directory
                #    fails with "Failed to create file '<dir>'").
                #  - `--mode-single` is required to merge layers into one SVG
                #    (the default multi-file behavior is deprecated).
                # These flags also work on KiCad 8/9, so we always pass them.
                output_svg = os.path.join(tmpdir, "board.svg")
                cmd = [
                    kicad_cli,
                    "pcb",
                    "export",
                    "svg",
                    "--output",
                    output_svg,
                    "--mode-single",
                    "--black-and-white",
                    # Render the board, not the drawing sheet. kicad-cli's
                    # default (page-size-mode 0) plots only the area inside the
                    # sheet, so board geometry past the page edge is left out.
                    # Mode 2 sizes the output to the board's bounding box;
                    # --exclude-drawing-sheet drops the title block.
                    "--exclude-drawing-sheet",
                    "--page-size-mode",
                    "2",
                ]
                if layers:
                    cmd += ["--layers", ",".join(layers)]
                cmd.append(pcb_path)

                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                except subprocess.TimeoutExpired:
                    return {
                        "success": False,
                        "message": "kicad-cli timed out after 60 s",
                        "errorDetails": " ".join(cmd),
                    }

                # Do NOT gate on the exit code: KiCad 9+/10 returns exit code 2
                # for a deprecation warning even when the SVG is written
                # correctly. Use "was an SVG actually produced?" as the success
                # signal instead — robust across versions and modes.
                svg_files = (
                    [output_svg]
                    if os.path.exists(output_svg)
                    else glob.glob(os.path.join(tmpdir, "*.svg"))
                )
                if not svg_files:
                    return {
                        "success": False,
                        "message": "kicad-cli SVG export failed",
                        "errorDetails": result.stderr.strip() or result.stdout.strip(),
                    }

                svg_path = svg_files[0]

                # --- Render to bytes (shared for both response modes) ---
                board_dir = os.path.dirname(pcb_path)
                board_name = os.path.splitext(os.path.basename(pcb_path))[0]

                if fmt == "svg":
                    with open(svg_path, "rb") as f:
                        image_bytes = f.read()
                    mime_format = "svg"
                else:
                    png_bytes = _svg_to_png(svg_path, width, height)
                    if png_bytes is None:
                        # No PNG converter — fall back to SVG inline
                        with open(svg_path, "r", encoding="utf-8") as f:
                            return {
                                "success": True,
                                "format": "svg",
                                "imageData": base64.b64encode(f.read().encode()).decode("utf-8"),
                                "message": "No PNG converter available — returning SVG. Install pymupdf, inkscape, or imagemagick.",
                            }
                    if fmt == "jpg":
                        img = Image.open(io.BytesIO(png_bytes))
                        buf = io.BytesIO()
                        img.convert("RGB").save(buf, format="JPEG")
                        image_bytes = buf.getvalue()
                    else:
                        image_bytes = png_bytes
                    mime_format = fmt

                # --- Package response according to responseMode ---
                if response_mode == "file":
                    output_path = os.path.join(board_dir, f"{board_name}_2d_view.{mime_format}")
                    with open(output_path, "wb") as f:
                        f.write(image_bytes)
                    return {
                        "success": True,
                        "format": mime_format,
                        "filePath": output_path,
                        "message": f"2D view saved to {output_path}",
                    }
                else:
                    return {
                        "success": True,
                        "format": mime_format,
                        "imageData": base64.b64encode(image_bytes).decode("utf-8"),
                    }

        except FileNotFoundError:
            return {
                "success": False,
                "message": "kicad-cli not found in PATH",
                "errorDetails": "Install KiCad and ensure kicad-cli is on PATH",
            }
        except Exception as e:
            logger.error(f"Error getting board 2D view: {e}")
            return {
                "success": False,
                "message": "Failed to get board 2D view",
                "errorDetails": str(e),
            }

    def _get_layer_type_name(self, type_id: int) -> str:
        """Convert KiCAD layer type constant to name"""
        type_map = {
            pcbnew.LT_SIGNAL: "signal",
            pcbnew.LT_POWER: "power",
            pcbnew.LT_MIXED: "mixed",
            pcbnew.LT_JUMPER: "jumper",
        }
        # Note: LT_USER was removed in KiCAD 9.0
        return type_map.get(type_id, "unknown")

    def get_board_extents(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get the bounding box extents of the board"""
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # Get unit preference (default to mm)
            unit = params.get("unit", "mm")
            scale = (
                1000000 if unit == "mm" else (25400 if unit == "mil" else 25400000)
            )  # mm, mil, or inch to nm

            # Get board bounding box
            board_box = self.board.GetBoardEdgesBoundingBox()

            # Extract bounds in nanometers, then convert
            left = board_box.GetLeft() / scale
            top = board_box.GetTop() / scale
            right = board_box.GetRight() / scale
            bottom = board_box.GetBottom() / scale
            width = board_box.GetWidth() / scale
            height = board_box.GetHeight() / scale

            # Get center point
            center_x = board_box.GetCenter().x / scale
            center_y = board_box.GetCenter().y / scale

            return {
                "success": True,
                "extents": {
                    "left": left,
                    "top": top,
                    "right": right,
                    "bottom": bottom,
                    "width": width,
                    "height": height,
                    "center": {"x": center_x, "y": center_y},
                    "unit": unit,
                },
            }

        except Exception as e:
            logger.error(f"Error getting board extents: {str(e)}")
            return {
                "success": False,
                "message": "Failed to get board extents",
                "errorDetails": str(e),
            }
