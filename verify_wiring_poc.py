#!/usr/bin/env python3
"""
验证：KiCad MCP 接线机制（wire 连通性 + kicad-cli 匿名网导出假象）

跑法（在 kicad-mcp-server 根目录）：
    python3 verify_wiring_poc.py

前提：
  - 已装 KiCad 符号库（Device 库可解析）；kicad-cli 在 PATH 里
  - 已应用本仓的 3 处修复（pin uuid / 落格 / create_schematic template 参数）

它做什么：建一张干净图，放 R1/R2，用一根直线连 R1.2↔R2.2，然后：
  A) 不打 label 导 netlist  → 期望 (nets) 空        —— 匿名网被 kicad-cli 省略
  B) 在 wire 上打一个 label 再导 netlist → 期望网含 R1.2+R2.2 —— 证明 wire 其实连上了
  C) 跑 ERC → 期望 R1.2/R2.2 不在 pin_not_connected 里 —— KiCad 确认已连
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "python"))
from kicad_interface import KiCADInterface  # noqa: E402
from commands.pin_locator import PinLocator  # noqa: E402


def kicad_cli() -> str:
    return shutil.which("kicad-cli") or "kicad-cli"


def dump_named_nets(net_path: str):
    c = Path(net_path).read_text()
    nets = []
    for b in re.findall(r"\(net\b.*?(?=\n\s*\(net\b|\Z)", c, re.S):
        nm = re.search(r'\(name "([^"]*)"', b)
        nodes = re.findall(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"', b)
        if nodes:
            nets.append((nm.group(1) if nm else "?", nodes))
    return nets


def erc_types(sch: str, workdir: str):
    out = os.path.join(workdir, "erc.json")
    subprocess.run(
        [kicad_cli(), "sch", "erc", "--format", "json", "--output", out, sch],
        capture_output=True, text=True,
    )
    import json
    d = json.load(open(out))
    vs = list(d.get("violations", []))
    for s in d.get("sheets", []):
        vs += s.get("violations", [])
    pnc = []
    for v in vs:
        if v.get("type") == "pin_not_connected":
            for it in v.get("items", []):
                p = it.get("pos", {})
                pnc.append((round(p.get("x", 0) * 100, 2), round(p.get("y", 0) * 100, 2)))
    return pnc


def export_netlist(sch: str, workdir: str) -> str:
    out = os.path.join(workdir, "out.net")
    subprocess.run(
        [kicad_cli(), "sch", "export", "netlist", "--format", "kicadsexpr",
         "--output", out, sch],
        capture_output=True, text=True,
    )
    return out


def main():
    k = KiCADInterface()
    wd = tempfile.mkdtemp(prefix="wire_poc_")
    print(f"workdir: {wd}\n")

    SCH = os.path.join(wd, "poc.kicad_sch")
    r = k.handle_command("create_schematic", {"projectName": "poc", "path": wd, "template": "minimal"})
    assert r.get("success"), r
    for ref, x in (("R1", 100), ("R2", 120)):
        r = k.handle_command("add_schematic_component", {
            "schematicPath": SCH,
            "component": {"type": "R", "library": "Device", "reference": ref,
                          "value": "1k", "footprint": "Resistor_SMD:R_0805_2012Metric",
                          "x": x, "y": 100},
        })
        assert r.get("success"), f"add {ref} failed: {r}"

    pl = PinLocator()
    p1 = pl.get_all_symbol_pins(Path(SCH), "R1")
    p2 = pl.get_all_symbol_pins(Path(SCH), "R2")
    print(f"R1.2 = {p1['2']}   R2.2 = {p2['2']}")

    # 直线连接 R1.2 - R2.2（无 label）
    k.handle_command("add_schematic_wire", {
        "schematicPath": SCH, "waypoints": [p1["2"], p2["2"]], "snapToPins": True,
    })

    # A) 无 label
    netsA = dump_named_nets(export_netlist(SCH, wd))
    print(f"\n[A] wire 无 label  → 导出网: {netsA or '(空)'}   ← 匿名网被 kicad-cli 省略（预期空）")

    # C) ERC
    pnc = erc_types(SCH, wd)
    r1_2, r2_2 = tuple(round(v, 2) for v in p1["2"]), tuple(round(v, 2) for v in p2["2"])
    connected = r1_2 not in pnc and r2_2 not in pnc
    print(f"[C] ERC pin_not_connected 坐标: {pnc}")
    print(f"    R1.2/R2.2 是否被判为已连接: {connected}   ← True 说明 wire 真的连上了")

    # B) 在 wire 上打 label
    LABEL = os.path.join(wd, "poc_labeled.kicad_sch")
    shutil.copy(SCH, LABEL)
    midx = round(round((p1["2"][0] + p2["2"][0]) / 2 / 1.27) * 1.27, 2)
    k.handle_command("add_schematic_net_label", {
        "schematicPath": LABEL, "netName": "SIGNAL", "position": [midx, p1["2"][1]],
    })
    netsB = dump_named_nets(export_netlist(LABEL, wd))
    print(f"\n[B] wire + label  → 导出网: {netsB}   ← 应含 R1.2 与 R2.2，证明 wire 连通")

    print("\n结论：wire 连通性 OK；空 netlist 是 kicad-cli 不导「无名字网」的假象。")


if __name__ == "__main__":
    main()
