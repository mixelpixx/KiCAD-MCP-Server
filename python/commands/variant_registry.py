"""Manage KiCad 10's schematic.variants registry without loading the board."""

import json
from pathlib import Path

from utils.project_settings_guard import write_project_json_atomic


def _registry(project_path):
    if not isinstance(project_path, (str, Path)) or not str(project_path):
        raise ValueError("projectPath must point to a saved .kicad_pro file")
    path = Path(project_path)
    if path.suffix.lower() != ".kicad_pro":
        raise ValueError("projectPath must point to a .kicad_pro file")
    project = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(project, dict):
        raise ValueError("Invalid KiCad project: expected a JSON object")
    schematic = project.setdefault("schematic", {})
    if not isinstance(schematic, dict):
        raise ValueError("Invalid schematic project settings")
    variants = schematic.setdefault("variants", [])
    if not isinstance(variants, list) or any(
        not isinstance(v, dict) or not isinstance(v.get("name"), str) for v in variants
    ):
        raise ValueError("Invalid schematic.variants registry")
    return path, project, variants


def registered_names(project_path):
    """Return explicit variant names; the implicit base design is not registered."""
    return [entry["name"] for entry in _registry(project_path)[2]]


def list_variants(params):
    try:
        path, _, variants = _registry(params.get("projectPath"))
        return {"success": True, "projectPath": str(path), "variants": variants}
    except (OSError, ValueError) as exc:
        return {"success": False, "error": str(exc)}


def create_variant(params):
    try:
        path, project, variants = _registry(params.get("projectPath"))
        name = params.get("name")
        if not isinstance(name, str) or not name or name.strip() != name or not name.isprintable():
            raise ValueError("name must be non-empty printable text without surrounding whitespace")
        if name.casefold() == "< default >":
            raise ValueError("The default design is implicit; use another variant name")
        if any(v["name"].casefold() == name.casefold() for v in variants):
            raise ValueError(f"Variant already exists: {name}")
        entry = {"name": name}
        if "description" in params:
            if not isinstance(params["description"], str):
                raise ValueError("description must be a string")
            entry["description"] = params["description"]
        variants.append(entry)
        write_project_json_atomic(str(path), project)
        return {"success": True, "projectPath": str(path), "variant": entry}
    except (OSError, ValueError) as exc:
        return {"success": False, "error": str(exc)}
