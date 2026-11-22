"""Single-sheet native KiCad 10 symbol instance variants."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def design(tmp_path):
    project = tmp_path / "demo.kicad_pro"
    project.write_text(json.dumps({"schematic": {"variants": [{"name": "Lite"}]}}))
    sheet = project.with_suffix(".kicad_sch")
    source = (Path(__file__).parent / "fixtures/canonical_schematic.kicad_sch").read_text()
    # This fixture has two C9 instances: retain the foreign project verbatim and
    # assign the root-UUID instance to this test's project.
    sheet.write_bytes(source.replace('(project ""', '(project "demo"').encode())
    return dict(projectPath=str(project), schematicPath=str(sheet), reference="C9", variant="Lite")


def test_get_reports_no_overrides_without_touching_files(design):
    from commands.variant_components import get_component_variant

    sheet = Path(design["schematicPath"])
    before = sheet.read_bytes()
    result = get_component_variant(design)
    assert result["success"], result
    assert [(u["unit"], u["dnp"], u["fields"]) for u in result["units"]] == [(1, None, {})]
    assert sheet.read_bytes() == before


def test_set_dnp_and_fields_applies_to_native_bom_only_in_selected_variant(design, tmp_path):
    import csv
    import os
    import subprocess

    from commands.variant_components import set_component_variant
    from utils.kicad_cli import resolve_kicad_cli

    result = set_component_variant(dict(design, dnp=True, fields={"Value": "220nF"}))
    assert result["success"], result
    assert result["units"][0]["dnp"] is True
    assert result["units"][0]["fields"] == {"Value": "220nF"}
    cli = resolve_kicad_cli()
    if not cli or not subprocess.check_output([cli, "version"], text=True).startswith("10."):
        pytest.skip("Requires real kicad-cli 10")

    def bom(*flags):
        output = tmp_path / "bom.csv"
        subprocess.run(
            [
                cli,
                "sch",
                "export",
                "bom",
                "--fields",
                "Reference,Value",
                "--labels",
                "Reference,Value",
                "-o",
                str(output),
                *flags,
                design["schematicPath"],
            ],
            check=True,
            capture_output=True,
            env={**os.environ, "KICAD_CONFIG_HOME": str(tmp_path / "config")},
        )
        with output.open(encoding="utf-8-sig", newline="") as f:
            return {row["Reference"]: row["Value"] for row in csv.DictReader(f)}

    assert bom("--variant", "Lite")["C9"] == "220nF"
    assert "C9" not in bom("--variant", "Lite", "--exclude-dnp")
    assert bom("--exclude-dnp")["C9"] != "220nF"


@pytest.mark.parametrize(
    "case",
    [
        "old",
        "future",
        "orphan",
        "stale-path",
        "wrong-project",
        "locked",
        "unregistered",
        "unterminated",
        "invalid-base",
        "nul",
    ],
)
def test_refuses_unsafe_edits_without_writes(design, case):
    from commands.variant_components import set_component_variant

    sheet = Path(design["schematicPath"])
    text = sheet.read_text()
    if case in ("old", "future"):
        text = text.replace("20260101", "20250114" if case == "old" else "20990101")
    elif case == "orphan":
        sheet = sheet.with_name("detached.kicad_sch")
        design["schematicPath"] = str(sheet)
    elif case == "stale-path":
        text = text.replace(
            'path "/f379cdcf-95e9-40fb-bb22-dbfcc9b050ce"',
            'path "/f379cdcf-95e9-40fb-bb22-dbfcc9b050ce/stale"',
        )
    elif case == "wrong-project":
        text = text.replace('(project "demo"', '(project "somebodyElse"')
    elif case == "locked":
        sheet.with_name("~" + sheet.name + ".lck").touch()
    elif case == "unregistered":
        design["variant"] = "Pocket"
    elif case == "unterminated":
        text = text.rstrip()[:-1]
    elif case == "invalid-base":
        text = text.replace("(dnp no)", "(dnp maybe)")
    elif case == "nul":
        design["fields"] = {"Value": "10\x00nF"}
    sheet.write_text(text)
    before = sheet.read_bytes()
    result = set_component_variant(dict(design, dnp=True))
    assert result.get("success") is False and result.get("error"), result
    assert sheet.read_bytes() == before


@pytest.mark.parametrize(
    "patch",
    [
        {},
        {"dnp": 1},
        {"fields": None},
        {"fields": {"MPN": 8}},
        {"fields": {"unknown": "x"}},
        {"fields": {"Reference": "X1"}},
        {"reset": True, "dnp": False},
        {"typo": True},
        {"variant": None},
        {"schematicPath": ""},
        {"reference": "C900"},
    ],
)
def test_rejects_invalid_arguments(design, patch):
    from commands.variant_components import set_component_variant

    sheet = Path(design["schematicPath"])
    before = sheet.read_bytes()
    result = set_component_variant({**design, **patch})
    assert not result["success"] and result["error"]
    assert sheet.read_bytes() == before


def test_updates_all_units_preserving_foreign_project_fields_flags_and_bytes(design):
    from commands.variant_components import set_component_variant

    sheet = Path(design["schematicPath"])
    text = sheet.read_text()
    # Add an extra placed unit with a misleading base Reference, not a library symbol.
    address = "/f379cdcf-95e9-40fb-bb22-dbfcc9b050ce"
    extra = f"""(symbol (lib_id "Device:C") (unit 2) (dnp yes)
    (property "Reference" "C1") (property "Value" "100n")
    (instances (project "demo" (path "{address}" (reference "C9") (unit 2)))))"""
    other = '(variant (name "Other") (dnp no))'
    keep = "(on_board   no) (in_bom   no)"
    old = f'(variant (name "Lite") {keep} (field (name "Value") (value "old")))'
    text = text.replace("(unit 1)\n\t\t\t\t)", "(unit 1) " + other + " " + old + "\n\t\t\t\t)")
    text = text.replace("\n\t(sheet_instances", "\n" + extra + "\n\t(sheet_instances")
    sheet.write_bytes(text.replace("\n", "\r\n").encode() + b"\n")
    before = sheet.read_bytes()
    value = 'x) "quoted"\\µ\n(field)'
    patch = dict(design, dnp=True, fields={"Value": value})
    result = set_component_variant(patch)
    assert result["success"], result
    assert [(u["unit"], u["dnp"], u["fields"]) for u in result["units"]] == [
        (1, True, {"Value": value}),
        (2, None, {"Value": value}),
    ]
    after = sheet.read_bytes()
    assert before.split(b'(project "demo"')[0] == after.split(b'(project "demo"')[0]
    assert after.count(keep.encode()) == 2 and after.count(other.encode()) == 2
    assert after.endswith(b"\r\n\n")
    assert not set_component_variant(patch)["changed"]
    assert after == sheet.read_bytes()
    removed = set_component_variant(dict(design, dnp=False, fields={"Value": None}))
    assert removed["success"] and removed["units"][0]["fields"] == {}
    assert removed["units"][1]["dnp"] is False
    assert sheet.read_bytes().count(keep.encode()) == 2
    assert set_component_variant(dict(design, reset=True))["success"]
    assert sheet.read_bytes().count(keep.encode()) == 1  # foreign only
    assert sheet.read_bytes().count(other.encode()) == 2


def test_set_reset_restores_original_bytes_with_comments(design):
    from commands.variant_components import set_component_variant

    sheet = Path(design["schematicPath"])
    before = sheet.read_bytes().replace(b"(paper ", b"  # a KiCad comment with (((\n\t(paper ")
    sheet.write_bytes(before)
    assert set_component_variant(dict(design, dnp=True))["success"]
    assert set_component_variant(dict(design, reset=True))["success"]
    assert sheet.read_bytes() == before


def test_repeated_child_sheet_selects_only_live_annotated_path(design):
    from commands.variant_components import set_component_variant

    root = Path(design["schematicPath"])
    child = root.with_name("reused.kicad_sch")
    text = root.read_text()
    prefix = "f379cdcf-95e9-40fb-bb22-dbfcc9b050ce"
    a = "5dfa21f6-f405-48a6-a377-377dc9d56df0"
    b = "9e22e76d-cb1c-446c-ab20-b8d31ed8cb96"
    text = text.replace('(project "sample_project"', '(project "foreign"')
    new_paths = f'(path "/{prefix}/{a}" (reference "C8") (unit 1)) (path "/{prefix}/{b}"'
    child.write_text(text.replace(f'(path "/{prefix}"', new_paths))
    blocks = "".join(f'(sheet (uuid "{u}") (property "Sheetfile" "{child.name}"))' for u in (a, b))
    root.write_text(f'(kicad_sch (version 20260306) (uuid "{prefix}") {blocks})')
    design["schematicPath"] = str(child)
    result = set_component_variant(dict(design, dnp=True))
    assert result["success"], result
    assert [unit["path"] for unit in result["units"]] == [f"/{prefix}/{b}"]
    assert child.read_text().count("(variant ") == 1


def test_reset_never_joins_closing_parenthesis_to_comment(design):
    from commands.variant_components import set_component_variant

    sheet = Path(design["schematicPath"])
    text = sheet.read_text().replace(
        "(unit 1)\n\t\t\t\t)",
        '(unit 1)\n # preserve this comment\n (variant (name "Lite") (dnp yes)))',
    )
    sheet.write_text(text)
    result = set_component_variant(dict(design, reset=True))
    assert result["success"], result
    assert "# preserve this comment\n" in sheet.read_text()


def test_atomic_failure_preserves_original_and_cleans_temporary_file(design, monkeypatch):
    from commands.variant_components import set_component_variant

    sheet = Path(design["schematicPath"])
    before = {p: p.read_bytes() for p in sheet.parent.iterdir()}

    def locked(*args):
        raise PermissionError("in use")

    monkeypatch.setattr("commands.variant_components.os.replace", locked)
    result = set_component_variant(dict(design, dnp=True))
    assert not result["success"] and "in use" in result["error"]
    assert {p: p.read_bytes() for p in sheet.parent.iterdir()} == before


@pytest.mark.parametrize(
    "clause",
    [
        '(variant (name "Lite") (future x))',
        '(variant (name "Lite") extra)',
        '(variant (name "Lite") (dnp no) (dnp yes))',
    ],
)
def test_rejects_unsupported_or_ambiguous_target_clause(design, clause):
    from commands.variant_components import set_component_variant

    sheet = Path(design["schematicPath"])
    before = sheet.read_bytes().replace(
        b"(unit 1)\n\t\t\t\t)", b"(unit 1) " + clause.encode() + b"\n\t\t\t\t)"
    )
    sheet.write_bytes(before)
    assert not set_component_variant(dict(design, reset=True))["success"]
    assert sheet.read_bytes() == before
