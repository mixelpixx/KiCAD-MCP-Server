"""
Footprint Creator for KiCAD MCP Server

Creates and edits .kicad_mod footprint files using raw text/S-Expression generation.
Supports THT and SMD pads, courtyard, silkscreen, and fab layer graphics.

KiCAD 9 .kicad_mod format reference:
  https://dev-docs.kicad.org/en/file-formats/sexpr-footprint/
"""

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("kicad_interface")

KICAD9_FORMAT_VERSION = "20250114"  # .kicad_sch schematic files
KICAD9_FOOTPRINT_VERSION = "20241229"  # .kicad_mod footprint files


def _fmt(v: float) -> str:
    """Format a float without unnecessary trailing zeros."""
    return f"{v:g}"


class FootprintCreator:
    """
    Creates and edits KiCAD .kicad_mod footprint files via text generation.
    No sexpdata – pure f-string assembly to guarantee format correctness.
    """

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def create_footprint(
        self,
        library_path: str,
        name: str,
        description: str = "",
        tags: str = "",
        pads: Optional[List[Dict[str, Any]]] = None,
        courtyard: Optional[Dict[str, Any]] = None,
        silkscreen: Optional[Dict[str, Any]] = None,
        fab_layer: Optional[Dict[str, Any]] = None,
        ref_position: Optional[Dict[str, float]] = None,
        value_position: Optional[Dict[str, float]] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """
        Create a new .kicad_mod footprint file.

        Parameters
        ----------
        library_path : str
            Path to the .pretty directory (created if missing).
        name : str
            Footprint name, e.g. "R_0603_Custom".
        description : str
            Human-readable description.
        tags : str
            Space-separated tag string.
        pads : list of dicts
            Each pad dict supports:
              number      (str)  – pad number / net name, e.g. "1"
              type        (str)  – "smd" | "thru_hole" | "np_thru_hole"
              shape       (str)  – "rect" | "circle" | "oval" | "roundrect"
              at          (dict) – {"x": float, "y": float, "angle": float (opt)}
              size        (dict) – {"w": float, "h": float}
              drill       (float or dict) – scalar for round drill, dict for oval:
                                            {"w": float, "h": float}
              layers      (list) – override default layer list
              roundrect_ratio (float) – 0.0..0.5 for roundrect shape
        courtyard : dict or None
            {"x1": float, "y1": float, "x2": float, "y2": float, "width": float}
        silkscreen : dict or None
            {"x1": float, "y1": float, "x2": float, "y2": float, "width": float}
        fab_layer : dict or None
            {"x1": float, "y1": float, "x2": float, "y2": float, "width": float}
        ref_position : dict or None – {"x": float, "y": float}
        value_position : dict or None – {"x": float, "y": float}
        overwrite : bool
            If False (default), raise if file already exists.

        Returns
        -------
        dict with "success", "path", "pad_count"
        """
        lib = Path(library_path)
        if not lib.suffix == ".pretty":
            lib = lib.with_suffix(".pretty")
        lib.mkdir(parents=True, exist_ok=True)

        mod_path = lib / f"{name}.kicad_mod"
        if mod_path.exists() and not overwrite:
            return {
                "success": False,
                "error": f"Footprint already exists: {mod_path}. Use overwrite=true to replace.",
                "path": str(mod_path),
            }

        pads = pads or []
        lines: List[str] = []

        # ---- header ----
        lines.append(f'(footprint "{name}"')
        lines.append(f"  (version {KICAD9_FOOTPRINT_VERSION})")
        lines.append(f'  (generator "kicad-mcp")')
        lines.append(f'  (generator_version "9.0")')
        lines.append(f'  (layer "F.Cu")')
        if description:
            lines.append(f'  (descr "{_esc(description)}")')
        if tags:
            lines.append(f'  (tags "{_esc(tags)}")')
        lines.append("")

        # ---- reference / value text ----
        ref_x = ref_position.get("x", 0.0) if ref_position else 0.0
        ref_y = ref_position.get("y", -1.27) if ref_position else -1.27
        val_x = value_position.get("x", 0.0) if value_position else 0.0
        val_y = value_position.get("y", 1.27) if value_position else 1.27

        lines.append(f'  (property "Reference" "REF**" (at {_fmt(ref_x)} {_fmt(ref_y)} 0)')
        lines.append(f'    (layer "F.SilkS")')
        lines.append(f'    (uuid "{_new_uuid()}")')
        lines.append(f"    (effects (font (size 1 1) (thickness 0.15)))")
        lines.append(f"  )")
        lines.append(f'  (property "Value" "{_esc(name)}" (at {_fmt(val_x)} {_fmt(val_y)} 0)')
        lines.append(f'    (layer "F.Fab")')
        lines.append(f'    (uuid "{_new_uuid()}")')
        lines.append(f"    (effects (font (size 1 1) (thickness 0.15)))")
        lines.append(f"  )")
        lines.append(f'  (property "Datasheet" "" (at 0 0 0)')
        lines.append(f'    (layer "F.Fab")')
        lines.append(f'    (uuid "{_new_uuid()}")')
        lines.append(f"    (effects (font (size 1 1) (thickness 0.15)))")
        lines.append(f"  )")
        lines.append("")

        # ---- courtyard ----
        if courtyard:
            lines.extend(_rect_lines(courtyard, "F.CrtYd", default_width=0.05))

        # ---- silkscreen ----
        if silkscreen:
            lines.extend(_rect_lines(silkscreen, "F.SilkS", default_width=0.12))

        # ---- fab layer ----
        if fab_layer:
            lines.extend(_rect_lines(fab_layer, "F.Fab", default_width=0.1))

        # ---- pads ----
        for pad in pads:
            lines.extend(_pad_lines(pad))
            lines.append("")

        lines.append(")")

        content = "\n".join(lines) + "\n"
        mod_path.write_text(content, encoding="utf-8")
        logger.info(f"Created footprint: {mod_path} ({len(pads)} pads)")

        return {
            "success": True,
            "path": str(mod_path),
            "name": name,
            "pad_count": len(pads),
        }

    def edit_footprint_pad(
        self,
        footprint_path: str,
        pad_number: str,
        size: Optional[Dict[str, float]] = None,
        at: Optional[Dict[str, float]] = None,
        drill: Optional[Any] = None,
        shape: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Edit an existing pad in a .kicad_mod file.

        Parameters
        ----------
        footprint_path : str
            Full path to the .kicad_mod file.
        pad_number : str
            Pad number to update (e.g. "1", "2").
        size : dict or None – {"w": float, "h": float}
        at : dict or None – {"x": float, "y": float, "angle": float (opt)}
        drill : float or dict or None
        shape : str or None – "rect" | "circle" | "oval" | "roundrect"

        Returns
        -------
        dict with "success", "updated", "pad_number"
        """
        path = Path(footprint_path)
        if not path.exists():
            return {"success": False, "error": f"File not found: {footprint_path}"}

        content = path.read_text(encoding="utf-8")
        updated: List[str] = []

        # Find the pad block for pad_number and apply modifications
        # Strategy: locate "(pad "<pad_number>"" line and patch individual fields
        # We use a simple line-by-line state machine that tracks brace depth
        # to stay inside the correct pad block.

        def patch_pad_block(block: str) -> str:
            nonlocal updated
            changes = []
            if size:
                new_size = f'(size {_fmt(size["w"])} {_fmt(size["h"])})'
                block, n = re.subn(r"\(size\s+[\d.]+\s+[\d.]+\)", new_size, block)
                if n:
                    changes.append(f"size→{new_size}")
            if at:
                angle = at.get("angle", 0)
                new_at = f'(at {_fmt(at["x"])} {_fmt(at["y"])} {_fmt(angle)})'
                block, n = re.subn(r"\(at\s+[-\d.]+\s+[-\d.]+(?:\s+[-\d.]+)?\)", new_at, block)
                if n:
                    changes.append(f"at→{new_at}")
            if drill is not None:
                if isinstance(drill, (int, float)):
                    new_drill = f"(drill {_fmt(drill)})"
                else:
                    new_drill = f'(drill oval {_fmt(drill["w"])} {_fmt(drill["h"])})'
                block, n = re.subn(
                    r"\(drill(?:\s+oval)?\s+[-\d.]+(?:\s+[-\d.]+)?\)", new_drill, block
                )
                if n:
                    changes.append(f"drill→{new_drill}")
                else:
                    # Insert drill before closing paren of pad block
                    block = block.rstrip().rstrip(")") + f"\n    {new_drill}\n  )"
                    changes.append(f"drill (inserted)→{new_drill}")
            if shape:
                block, n = re.subn(
                    r'(pad\s+"[^"]*"\s+\w+\s+)\w+',
                    lambda m: str(m.group(1)) + shape,
                    block,
                    count=1,
                )
                if n:
                    changes.append(f"shape→{shape}")
            updated.extend(changes)
            return block

        # Parse blocks
        result_lines = []
        in_target_pad = False
        pad_depth = 0
        pad_block_lines: List[str] = []

        for line in content.split("\n"):
            stripped = line.strip()
            if not in_target_pad:
                # Detect start of target pad
                if re.match(rf'\(pad\s+"{re.escape(pad_number)}"\s+', stripped):
                    in_target_pad = True
                    pad_depth = stripped.count("(") - stripped.count(")")
                    pad_block_lines = [line]
                else:
                    result_lines.append(line)
            else:
                pad_block_lines.append(line)
                pad_depth += stripped.count("(") - stripped.count(")")
                if pad_depth <= 0:
                    # End of pad block – patch and flush
                    block = "\n".join(pad_block_lines)
                    block = patch_pad_block(block)
                    result_lines.extend(block.split("\n"))
                    in_target_pad = False
                    pad_block_lines = []

        if not updated:
            return {
                "success": False,
                "error": f'Pad "{pad_number}" not found or no changes made in {footprint_path}',
            }

        path.write_text("\n".join(result_lines), encoding="utf-8")
        logger.info(f"Edited pad {pad_number} in {path.name}: {updated}")

        return {
            "success": True,
            "footprint_path": str(path),
            "pad_number": pad_number,
            "updated": updated,
        }

    @staticmethod
    def _find_model_blocks(text: str) -> List[Dict[str, Any]]:
        """Return brace-balanced ``(model ...)`` blocks as {start,end,text,filename}."""
        blocks: List[Dict[str, Any]] = []
        idx = 0
        while True:
            start = text.find("(model", idx)
            if start == -1:
                break
            depth = 0
            i = start
            end = -1
            while i < len(text):
                c = text[i]
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
                i += 1
            if end == -1:
                break
            blk = text[start:end]
            fm = re.search(r'\(model\s+"?([^")\s]+)"?', blk)
            blocks.append(
                {"start": start, "end": end, "text": blk, "filename": fm.group(1) if fm else ""}
            )
            idx = end
        return blocks

    def add_3d_model(
        self,
        footprint_path: str,
        model_path: str,
        offset: Optional[Dict[str, float]] = None,
        scale: Optional[Dict[str, float]] = None,
        rotate: Optional[Dict[str, float]] = None,
        replace: bool = True,
    ) -> Dict[str, Any]:
        """
        Add or replace a 3D model ``(model ...)`` block in a .kicad_mod file.

        Parameters
        ----------
        footprint_path : str
            Full path to the .kicad_mod file.
        model_path : str
            Path to the 3D model (.step/.stp/.wrl). KiCad env vars such as
            ``${KIPRJMOD}`` or ``${KICAD10_3DMODEL_DIR}`` are allowed.
        offset, scale, rotate : dict or None – ``{"x":..,"y":..,"z":..}``.
            Defaults: offset 0/0/0, scale 1/1/1, rotate 0/0/0 (units: mm / deg).
        replace : bool
            If True (default), an existing model with the same filename is replaced
            (avoids duplicates). If False and the same model already exists, nothing
            is changed.
        """
        path = Path(footprint_path)
        if not path.exists():
            return {"success": False, "error": f"File not found: {footprint_path}"}

        off = offset or {}
        scl = scale or {}
        rot = rotate or {}

        model_block = (
            f'\t(model "{model_path}"\n'
            f'\t\t(offset (xyz {_fmt(off.get("x", 0))} {_fmt(off.get("y", 0))} {_fmt(off.get("z", 0))}))\n'
            f'\t\t(scale (xyz {_fmt(scl.get("x", 1))} {_fmt(scl.get("y", 1))} {_fmt(scl.get("z", 1))}))\n'
            f'\t\t(rotate (xyz {_fmt(rot.get("x", 0))} {_fmt(rot.get("y", 0))} {_fmt(rot.get("z", 0))}))\n'
            f"\t)"
        )

        content = path.read_text(encoding="utf-8")
        if "(footprint" not in content:
            return {"success": False, "error": f"Not a footprint file: {footprint_path}"}

        removed = 0
        blocks = self._find_model_blocks(content)
        same = [b for b in blocks if b["filename"] == model_path]
        if same and not replace:
            return {
                "success": True,
                "footprint_path": str(path),
                "added": False,
                "note": "Model with this filename already present (replace=false)",
            }
        # Remove matching blocks (back-to-front so offsets stay valid)
        for b in sorted(same, key=lambda x: x["start"], reverse=True):
            content = content[: b["start"]] + content[b["end"] :]
            removed += 1

        rstripped = content.rstrip()
        insert_pos = rstripped.rfind(")")
        if insert_pos == -1:
            return {"success": False, "error": "Malformed footprint (no closing paren)"}

        new_content = rstripped[:insert_pos] + model_block + "\n" + rstripped[insert_pos:] + "\n"
        path.write_text(new_content, encoding="utf-8")
        logger.info(f"add_3d_model: {model_path} -> {path.name} (replaced {removed})")

        return {
            "success": True,
            "footprint_path": str(path),
            "model": model_path,
            "added": True,
            "replaced": removed,
        }

    def import_3d_model(
        self,
        model_path: str,
        project_path: str,
        library_dir: Optional[str] = None,
        new_name: Optional[str] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """
        Copy a 3D model file into the project's ``*.3dshapes`` library and return
        a portable ``${KIPRJMOD}/...`` path ready for use in a footprint.

        Parameters
        ----------
        model_path : str
            Path to the source 3D model (.step/.stp/.wrl/.wings).
        project_path : str
            Path to the .kicad_pro file or the project directory. Used both to
            locate the default 3dshapes folder and to compute ${KIPRJMOD}.
        library_dir : str or None
            Target ``*.3dshapes`` directory. If relative, it is resolved against
            the project directory. Default: ``<project_dir>/<project>.3dshapes``.
        new_name : str or None
            Rename the copied file (extension kept from source if omitted).
        overwrite : bool
            Overwrite an existing destination file (default False).
        """
        src = Path(model_path)
        if not src.exists() or not src.is_file():
            return {"success": False, "error": f"Source model not found: {model_path}"}

        valid_ext = {".step", ".stp", ".wrl", ".wings", ".x3d", ".igs", ".iges"}
        if src.suffix.lower() not in valid_ext:
            return {
                "success": False,
                "error": f"Unsupported 3D model extension '{src.suffix}'. "
                f"Expected one of: {', '.join(sorted(valid_ext))}",
            }

        # Resolve project directory and name
        pp = Path(project_path)
        if pp.suffix == ".kicad_pro":
            project_dir = pp.parent
            project_name = pp.stem
        elif pp.is_dir():
            project_dir = pp
            pro = next(iter(sorted(pp.glob("*.kicad_pro"))), None)
            project_name = pro.stem if pro else pp.name
        else:
            return {
                "success": False,
                "error": f"projectPath must be a .kicad_pro file or a directory: {project_path}",
            }
        project_dir = project_dir.resolve()

        # Resolve target 3dshapes directory
        if library_dir:
            ld = Path(library_dir)
            target_dir = ld if ld.is_absolute() else (project_dir / ld)
        else:
            target_dir = project_dir / f"{project_name}.3dshapes"
        target_dir = target_dir.resolve()
        target_dir.mkdir(parents=True, exist_ok=True)

        # Destination file
        if new_name:
            dest_name = new_name if Path(new_name).suffix else new_name + src.suffix
        else:
            dest_name = src.name
        dest = target_dir / dest_name

        if dest.exists() and not overwrite and dest.resolve() != src.resolve():
            return {
                "success": False,
                "error": f"Destination already exists (use overwrite=true): {dest}",
            }

        if dest.resolve() != src.resolve():
            shutil.copy2(src, dest)

        # Compute portable ${KIPRJMOD} path
        try:
            rel = dest.resolve().relative_to(project_dir).as_posix()
            kiprjmod_path = "${KIPRJMOD}/" + rel
        except ValueError:
            # Destination is outside the project tree – fall back to absolute
            kiprjmod_path = dest.resolve().as_posix()

        logger.info(f"import_3d_model: {src} -> {dest}")
        return {
            "success": True,
            "source": str(src),
            "destination": str(dest),
            "library_dir": str(target_dir),
            "modelPath": kiprjmod_path,
            "note": "Use 'modelPath' with add_footprint_3d_model or add_component_3d_model.",
        }

    def list_footprint_libraries(self, search_paths: Optional[List[str]] = None) -> Dict[str, Any]:
        """List all .pretty libraries and their footprints."""
        default_paths = [
            r"C:\Program Files\KiCad\9.0\share\kicad\footprints",
            r"C:\Program Files\KiCad\8.0\share\kicad\footprints",
            "/usr/share/kicad/footprints",
            "/usr/local/share/kicad/footprints",
            os.path.expanduser("~/Documents/KiCad/9.0/footprints"),
        ]
        paths = search_paths or default_paths
        libraries = {}
        for base in paths:
            bp = Path(base)
            if not bp.exists():
                continue
            for pretty in sorted(bp.glob("*.pretty")):
                name = pretty.stem
                mods = sorted(p.stem for p in pretty.glob("*.kicad_mod"))
                libraries[name] = {"path": str(pretty), "count": len(mods), "footprints": mods[:20]}
        return {"success": True, "library_count": len(libraries), "libraries": libraries}

    def register_footprint_library(
        self,
        library_path: str,
        library_name: Optional[str] = None,
        description: str = "",
        scope: str = "project",
        project_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Register a .pretty library in KiCAD's fp-lib-table so KiCAD can find it.

        Parameters
        ----------
        library_path : str
            Full path to the .pretty directory.
        library_name : str or None
            Nickname for the library (default: directory stem).
        description : str
            Optional description string.
        scope : str
            "project" (writes fp-lib-table next to .kicad_pro) or
            "global"  (writes to ~/.config/kicad/9.0/fp-lib-table).
        project_path : str or None
            Path to the .kicad_pro file or its directory (needed for scope="project").

        Returns
        -------
        dict with "success", "table_path", "library_name", "already_registered"
        """
        pretty = Path(library_path)
        if not pretty.suffix == ".pretty":
            pretty = pretty.with_suffix(".pretty")

        name = library_name or pretty.stem
        uri = str(pretty).replace("\\", "/")  # KiCAD prefers forward slashes

        # Resolve fp-lib-table path
        if scope == "project":
            if project_path:
                proj = Path(project_path)
                table_dir = proj if proj.is_dir() else proj.parent
            else:
                # Default: same directory as the .pretty library
                table_dir = pretty.parent
            table_path = table_dir / "fp-lib-table"
        else:  # global
            cfg_dirs = [
                Path(os.environ.get("APPDATA", "")) / "kicad" / "9.0",
                Path.home() / ".config" / "kicad" / "9.0",
                Path.home() / ".local" / "share" / "kicad" / "9.0",
            ]
            table_path = None
            for d in cfg_dirs:
                candidate = d / "fp-lib-table"
                if candidate.exists():
                    table_path = candidate
                    break
            if table_path is None:
                # Create in first writable config dir
                for d in cfg_dirs:
                    try:
                        d.mkdir(parents=True, exist_ok=True)
                        table_path = d / "fp-lib-table"
                        break
                    except OSError:
                        continue
            if table_path is None:
                return {"success": False, "error": "Could not find or create global fp-lib-table"}

        # Read existing table or start fresh
        if table_path.exists():
            content = table_path.read_text(encoding="utf-8")
        else:
            content = "(fp_lib_table\n  (version 7)\n)\n"

        # Check if already registered (by name OR by uri)
        if f'(name "{name}")' in content or uri in content:
            return {
                "success": True,
                "already_registered": True,
                "table_path": str(table_path),
                "library_name": name,
            }

        # Insert new lib entry before closing paren
        new_entry = (
            f'  (lib (name "{name}")'
            f'(type "KiCad")'
            f'(uri "{uri}")'
            f'(options "")'
            f'(descr "{_esc(description)}"))'
        )
        # Insert before the last closing paren
        content = content.rstrip()
        if content.endswith(")"):
            content = content[:-1].rstrip() + "\n" + new_entry + "\n)\n"
        else:
            content += "\n" + new_entry + "\n)\n"

        table_path.write_text(content, encoding="utf-8")
        logger.info(f"Registered library '{name}' in {table_path}")

        return {
            "success": True,
            "already_registered": False,
            "table_path": str(table_path),
            "library_name": name,
            "uri": uri,
        }


# ------------------------------------------------------------------ #
#  Internal helpers                                                    #
# ------------------------------------------------------------------ #


def _esc(s: str) -> str:
    """Escape double-quotes inside S-Expression string values."""
    return s.replace('"', '\\"')


def _new_uuid() -> str:
    import uuid

    return str(uuid.uuid4())


_DEFAULT_SMD_LAYERS = ["F.Cu", "F.Paste", "F.Mask"]
_DEFAULT_THT_LAYERS = ["*.Cu", "*.Mask"]


def _pad_lines(pad: Dict[str, Any]) -> List[str]:
    number = str(pad.get("number", "1"))
    ptype = pad.get("type", "smd").lower()  # smd | thru_hole | np_thru_hole
    shape = pad.get("shape", "rect").lower()  # rect | circle | oval | roundrect
    at = pad.get("at", {"x": 0.0, "y": 0.0})
    size = pad.get("size", {"w": 1.0, "h": 1.0})
    drill = pad.get("drill", None)
    layers = pad.get("layers", None)
    rr_ratio = pad.get("roundrect_ratio", 0.25)

    ax = _fmt(at.get("x", 0.0))
    ay = _fmt(at.get("y", 0.0))
    aangle = at.get("angle", None)
    at_str = f"(at {ax} {ay})" if aangle is None else f"(at {ax} {ay} {_fmt(aangle)})"

    sw = _fmt(size.get("w", 1.0))
    sh = _fmt(size.get("h", 1.0))

    if layers is None:
        layers = (
            _DEFAULT_THT_LAYERS if ptype in ("thru_hole", "np_thru_hole") else _DEFAULT_SMD_LAYERS
        )
    layers_str = " ".join(f'"{l}"' for l in layers)

    lines = [f'  (pad "{number}" {ptype} {shape}']
    lines.append(f"    {at_str}")
    lines.append(f"    (size {sw} {sh})")

    if drill is not None:
        if isinstance(drill, (int, float)):
            lines.append(f"    (drill {_fmt(drill)})")
        elif isinstance(drill, dict):
            dw = _fmt(drill.get("w", 1.0))
            dh = _fmt(drill.get("h", 1.0))
            lines.append(f"    (drill oval {dw} {dh})")

    lines.append(f"    (layers {layers_str})")

    if shape == "roundrect":
        lines.append(f"    (roundrect_rratio {_fmt(rr_ratio)})")

    lines.append(f'    (uuid "{_new_uuid()}")')
    lines.append(f"  )")
    return lines


def _rect_lines(rect: Dict[str, Any], layer: str, default_width: float = 0.05) -> List[str]:
    x1 = _fmt(rect.get("x1", -1.0))
    y1 = _fmt(rect.get("y1", -1.0))
    x2 = _fmt(rect.get("x2", 1.0))
    y2 = _fmt(rect.get("y2", 1.0))
    w = _fmt(rect.get("width", default_width))
    return [
        f"  (fp_rect",
        f"    (start {x1} {y1})",
        f"    (end {x2} {y2})",
        f"    (stroke (width {w}) (type default))",
        f"    (fill none)",
        f'    (layer "{layer}")',
        f'    (uuid "{_new_uuid()}")',
        f"  )",
        "",
    ]
