"""Tests for Eagle → KiCad schematic import (commands/eagle.py)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.eagle import (  # noqa: E402
    _count_dangling_wires,
    _prune_dangling_wires,
    _trim_wires,
    generate_kicad_sch,
    parse_eagle_schematic,
)

FIXTURE = Path(__file__).parent / "fixtures" / "eagle" / "minimal.sch"


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


@pytest.mark.skipif(
    not Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe").exists(),
    reason="KiCad CLI not installed",
)
def test_minimal_fixture_exports_pdf(tmp_path: Path) -> None:
    parts, instances, net_wires, net_labels, junctions = parse_eagle_schematic(str(FIXTURE))
    sch = tmp_path / "minimal.kicad_sch"
    generate_kicad_sch(parts, instances, net_wires, net_labels, junctions, str(sch))
    from utils.sexpr_format import prettify

    sch.write_text(prettify(sch.read_text(encoding="utf-8")), encoding="utf-8")
    pdf = tmp_path / "out.pdf"
    import subprocess

    cli = Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")
    result = subprocess.run(
        [str(cli), "sch", "export", "pdf", "--output", str(pdf), str(sch)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert pdf.exists()
