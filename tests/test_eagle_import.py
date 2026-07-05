"""Tests for Eagle → KiCad schematic import (commands/eagle.py)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.eagle import (  # noqa: E402
    EagleCommands,
    _count_dangling_wires,
    _prune_dangling_wires,
    _trim_wires,
    generate_kicad_sch,
    parse_eagle_schematic,
)
from utils.kicad_cli import resolve_kicad_cli  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "eagle" / "minimal.sch"

# Gate cli-dependent tests on the same resolver the importer uses, so they run
# on any discoverable install (registry / Program Files / custom roots), not
# only the hardcoded Program Files path.
_KICAD_CLI = resolve_kicad_cli()


def test_parse_minimal_eagle_fixture() -> None:
    parts, instances, net_wires, net_labels, junctions = parse_eagle_schematic(str(FIXTURE))
    assert "R1" in parts
    assert len(instances) == 1
    assert len(net_wires) >= 2
    assert len(net_labels) >= 2
    assert junctions == []


def test_generate_kicad_sch_from_minimal_fixture(tmp_path: Path) -> None:
    parts, instances, net_wires, net_labels, junctions = parse_eagle_schematic(str(FIXTURE))
    out = tmp_path / "minimal.kicad_sch"
    sch_uuid, dangling = generate_kicad_sch(
        parts, instances, net_wires, net_labels, junctions, str(out)
    )
    assert sch_uuid
    assert dangling == 0
    text = out.read_text(encoding="utf-8")
    assert "(kicad_sch" in text
    assert "eagle_import:" in text
    assert "(symbol (lib_id" in text
    assert "(wire" in text
    assert "(label" in text


def test_trim_and_prune_remove_isolated_stub() -> None:
    conn = {(0.0, 0.0), (10.0, 0.0)}
    wires = [(0.0, 0.0, 10.0, 0.0), (10.0, 0.0, 15.0, 0.0)]
    trimmed = _trim_wires(wires, conn)
    pruned = _prune_dangling_wires(trimmed, conn)
    assert _count_dangling_wires(pruned, conn) == 0
    assert len(pruned) == 1


@pytest.mark.skipif(_KICAD_CLI is None, reason="KiCad CLI not installed")
def test_minimal_fixture_exports_pdf(tmp_path: Path) -> None:
    parts, instances, net_wires, net_labels, junctions = parse_eagle_schematic(str(FIXTURE))
    sch = tmp_path / "minimal.kicad_sch"
    generate_kicad_sch(parts, instances, net_wires, net_labels, junctions, str(sch))
    from utils.sexpr_format import prettify

    sch.write_text(prettify(sch.read_text(encoding="utf-8")), encoding="utf-8")
    pdf = tmp_path / "out.pdf"
    import subprocess

    result = subprocess.run(
        [str(_KICAD_CLI), "sch", "export", "pdf", "--output", str(pdf), str(sch)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert pdf.exists()


@pytest.mark.skipif(_KICAD_CLI is None, reason="KiCad CLI not installed")
def test_import_result_reports_ground_truth_erc(tmp_path: Path) -> None:
    """The result's erc block must reflect what kicad-cli actually measures.

    The internal dangling_wires count runs against the importer's own
    connection model, which can accept endpoints eeschema does not — it once
    reported 0 while real ERC flagged wire_dangling errors. The erc block
    exists so callers get KiCad's numbers, not the model's.
    """
    ec = EagleCommands()
    parts, instances, net_wires, net_labels, junctions = parse_eagle_schematic(str(FIXTURE))
    sch = tmp_path / "minimal.kicad_sch"
    generate_kicad_sch(parts, instances, net_wires, net_labels, junctions, str(sch))
    from utils.sexpr_format import prettify

    sch.write_text(prettify(sch.read_text(encoding="utf-8")), encoding="utf-8")

    report = ec._erc_check(str(sch))
    assert report is not None, "ERC must run when kicad-cli is resolvable"
    assert report["ran"] is True
    assert set(report) == {"ran", "errors", "warnings", "wire_dangling"}
    assert isinstance(report["errors"], int)
    assert isinstance(report["wire_dangling"], int)
    # The report file is cleaned up after parsing.
    assert not Path(str(sch) + ".erc.rpt").exists()
