"""Variant BOM exports use KiCad's native symbol overrides, not a CSV post-filter."""

import csv
import json
import subprocess
from pathlib import Path

import pytest

from commands.variant_bom import export_variant_bom
from utils.kicad_cli import resolve_kicad_cli


@pytest.fixture
def design(tmp_path):
    project = tmp_path / "sample.kicad_pro"
    name = "Service edition"
    project.write_text(json.dumps({"schematic": {"variants": [{"name": name, "description": ""}]}}))
    # Only edit a temporary copy; give C9 a distinct Value and DNP state on this variant.
    template = Path(__file__).parent / "fixtures" / "canonical_schematic.kicad_sch"
    schematic = template.read_text(encoding="utf-8").replace('(project ""', '(project "sample"')
    schematic = schematic.replace(
        '(reference "C9")',
        """(reference "C9")
                    (variant (name "Service edition") (dnp yes)
                        (field (name "Value") (value "220n")))""",
    )
    project.with_suffix(".kicad_sch").write_text(schematic, encoding="utf-8")
    return {"projectPath": str(project), "variant": name, "outputPath": str(tmp_path / "parts.csv")}


@pytest.mark.integration
def test_native_variant_bom(design, tmp_path, monkeypatch):
    monkeypatch.setenv("KICAD_CONFIG_HOME", str(tmp_path / "config"))
    cli = resolve_kicad_cli()
    if not cli or int(subprocess.check_output([cli, "version"], text=True).split(".")[0]) < 10:
        pytest.skip("requires KiCad CLI 10 or later")
    project = Path(design["projectPath"])
    inputs = {path: path.read_bytes() for path in (project, project.with_suffix(".kicad_sch"))}
    result = export_variant_bom(design)
    assert result["success"], result
    with Path(result["outputPath"]).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [(row["Refs"], row["Value"]) for row in rows] == [("C9", "220n")]

    result = export_variant_bom({**design, "excludeDnp": True})
    assert result["success"], result
    with Path(result["outputPath"]).open(encoding="utf-8-sig", newline="") as stream:
        assert list(csv.DictReader(stream)) == []
    assert all(p.read_bytes() == content for p, content in inputs.items())


@pytest.mark.unit
@pytest.mark.parametrize(
    "changes",
    [
        {"variant": "service edition"},
        {"variant": ""},
        {"variant": None},
        {"excludeDnp": "false"},
        {"excludeDnp": 1},
        {"projectPath": None},
        {"outputPath": None},
        {"outputPath": "parts.txt"},
    ],
)
def test_invalid_request_does_not_launch_cli(design, changes, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("unexpected CLI call"))
    result = export_variant_bom({**design, **changes})
    assert not result["success"] and result["error"]


@pytest.mark.unit
def test_flag_like_registered_name_does_not_change_cli_options(design, monkeypatch):
    project = Path(design["projectPath"])
    project.write_text(project.read_text().replace(design["variant"], "--help"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("unexpected CLI call"))
    result = export_variant_bom({**design, "variant": "--help"})
    assert not result["success"] and "variant" in result["error"].lower()


@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid", ["malformed", "wrong_extension", "missing_schematic", "wrong_output"]
)
def test_rejects_invalid_files_without_writing(design, invalid, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("unexpected CLI call"))
    project = Path(design["projectPath"])
    schematic = project.with_suffix(".kicad_sch")
    if invalid == "malformed":
        project.write_text("{invalid")
    elif invalid == "wrong_extension":
        design["projectPath"] = str(schematic)
    elif invalid == "missing_schematic":
        schematic.unlink()
    else:
        design["outputPath"] = str(schematic)
    files = {p: p.read_bytes() for p in project.parent.iterdir()}
    result = export_variant_bom(design)
    assert not result["success"] and result["error"]
    assert files == {p: p.read_bytes() for p in project.parent.iterdir()}


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure", ["nonzero", "no_output", "empty_output", "timeout", "unavailable"]
)
def test_failed_export_preserves_previous_csv(design, monkeypatch, failure):
    output = Path(design["outputPath"])
    output.write_text("unrelated inventory\n")
    before = {p: p.read_bytes() for p in output.parent.iterdir()}

    def run(cmd, **kwargs):
        dest = Path(kwargs.get("cwd", ".")) / cmd[cmd.index("--output") + 1]
        if failure in ("nonzero", "timeout"):
            dest.write_text("partial result")
            if failure == "timeout":
                raise subprocess.TimeoutExpired(cmd, 120)
            return subprocess.CompletedProcess(cmd, 4, "", "bad schematic")
        if failure == "empty_output":
            dest.write_bytes(b"")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(
        "commands.variant_bom.resolve_kicad_cli",
        lambda: None if failure == "unavailable" else "kicad-cli",
    )
    monkeypatch.setattr(subprocess, "run", run)
    result = export_variant_bom(design)
    assert not result["success"] and result["error"]
    if failure == "nonzero":
        assert "bad schematic" in result["error"]
    assert before == {p: p.read_bytes() for p in output.parent.iterdir()}


@pytest.mark.unit
def test_rejects_csv_alias_for_input(design, monkeypatch):
    output = Path(design["outputPath"])
    output.hardlink_to(Path(design["projectPath"]))
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("unexpected CLI call"))
    result = export_variant_bom(design)
    assert not result["success"] and result["error"]
    assert output.samefile(design["projectPath"])
