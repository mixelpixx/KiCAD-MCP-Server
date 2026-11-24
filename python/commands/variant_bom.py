"""Export a registered assembly variant with KiCad's native BOM engine."""

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from commands.variant_registry import registered_names
from utils.kicad_cli import kicad_cli_not_found_message, resolve_kicad_cli
from utils.subprocess_flags import no_window_flags


def export_variant_bom(params):
    try:
        names = registered_names(params.get("projectPath"))
        project = Path(params["projectPath"]).absolute()
        variant = params.get("variant")
        if not isinstance(variant, str) or not variant or variant not in names:
            raise ValueError(f"Unknown or empty project variant: {variant!r}")
        if variant.startswith("-"):
            raise ValueError(
                "kicad-cli interprets variant names starting with '-' as command options"
            )
        exclude_dnp = params.get("excludeDnp", False)
        if not isinstance(exclude_dnp, bool):
            raise ValueError("excludeDnp must be a boolean")
        schematic = project.with_suffix(".kicad_sch")
        if not schematic.is_file():
            raise ValueError(f"Root schematic not found: {schematic}")
        raw_output = params.get("outputPath")
        if not isinstance(raw_output, str) or Path(raw_output).suffix.lower() != ".csv":
            raise ValueError("outputPath must name a .csv file")
        output = Path(raw_output).absolute()
        if output.is_symlink() or (output.exists() and not output.is_file()):
            raise ValueError("outputPath must name a regular CSV file, not a directory or link")
        if output.exists() and any(output.samefile(path) for path in (project, schematic)):
            raise ValueError("outputPath aliases an input file")

        cli = resolve_kicad_cli()
        if not cli:
            raise ValueError(kicad_cli_not_found_message())
        output.parent.mkdir(parents=True, exist_ok=True)
        # KiCad may write a partial CSV before reporting an error. Stage beside
        # the destination so publishing the finished export is a single rename.
        with TemporaryDirectory(dir=output.parent) as stage:
            staged = Path(stage) / "bom.csv"
            cmd = [cli, "sch", "export", "bom", "--variant", variant, "--output", str(staged)]
            if exclude_dnp:
                cmd.append("--exclude-dnp")
            cmd.append(str(schematic))
            result = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                creationflags=no_window_flags(),
            )
            if result.returncode:
                detail = (result.stderr or result.stdout).strip()
                raise ValueError(f"kicad-cli sch export bom failed ({result.returncode}): {detail}")
            if not staged.is_file() or not staged.stat().st_size:
                raise ValueError("kicad-cli did not produce a BOM CSV")
            staged.replace(output)
        return {
            "success": True,
            "outputPath": str(output),
            "variant": variant,
            "projectPath": str(project),
        }
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"success": False, "error": str(exc)}
