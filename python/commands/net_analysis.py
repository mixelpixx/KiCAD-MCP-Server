"""Net-level analysis tools for schematic verification.

Builds a complete pin-to-net graph in a single pass using union-find,
then exposes query functions:  get_component_nets, get_net_components,
get_pin_net_name, export_netlist_summary, validate_component_connections.
"""

import logging
import math
import re
from pathlib import Path

logger = logging.getLogger("kicad_mcp")


# ── Coordinate snapping for O(1) lookups ──

_GRID = 0.01  # 0.01mm grid for coordinate rounding


def _snap(v):
    """Round to grid for hash-based lookups."""
    return round(v / _GRID) * _GRID


def _snap_pt(x, y):
    return (_snap(x), _snap(y))


# ── Union-Find (Disjoint Set) ──


class _UnionFind:
    """Weighted union-find with path compression."""

    __slots__ = ("parent", "rank")

    def __init__(self):
        self.parent = {}
        self.rank = {}

    def find(self, x):
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
            return x
        # Path compression
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        # Union by rank
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


# ── Parsing helpers ──


def _parse_wires(content):
    """Extract all wire segments as (x1, y1, x2, y2) tuples."""
    wires = []
    wire_pat = re.compile(r"\(wire\b")
    xy_pat = re.compile(r"\(xy\s+([\d.e+-]+)\s+([\d.e+-]+)\)")
    for wm in wire_pat.finditer(content):
        depth = 0
        i = wm.start()
        block_end = i
        while i < len(content):
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
                if depth == 0:
                    block_end = i + 1
                    break
            i += 1
        block = content[wm.start():block_end]
        xys = xy_pat.findall(block)
        if len(xys) >= 2:
            wires.append(
                (float(xys[0][0]), float(xys[0][1]),
                 float(xys[-1][0]), float(xys[-1][1]))
            )
    return wires


def _parse_labels(content):
    """Extract all labels as (x, y, net_name, label_type) tuples."""
    labels = []
    for lt in ["label", "global_label", "hierarchical_label"]:
        pat = re.compile(
            rf'\({lt}\s+"([^"]*)"(?:\s+\(shape\s+[^)]*\))?\s+\(at\s+([\d.e+-]+)\s+([\d.e+-]+)'
        )
        for m in pat.finditer(content):
            labels.append(
                (float(m.group(2)), float(m.group(3)), m.group(1), lt)
            )
    return labels


def _parse_power_symbols(content):
    """Extract power symbol pin positions as (x, y, net_name) tuples."""
    lib_sym_start = content.find("(lib_symbols")
    lib_sym_end = -1
    if lib_sym_start >= 0:
        depth = 0
        for i in range(lib_sym_start, len(content)):
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
                if depth == 0:
                    lib_sym_end = i
                    break

    results = []
    pwr_pat = re.compile(r'\(symbol\s+\(lib_id\s+"power:([^"]+)"\)')
    for m in pwr_pat.finditer(content):
        pos = m.start()
        if lib_sym_start >= 0 and lib_sym_start <= pos <= lib_sym_end:
            continue
        end = min(pos + 300, len(content))
        snippet = content[pos:end]
        at_m = re.search(r"\(at\s+([\d.e+-]+)\s+([\d.e+-]+)", snippet)
        val_m = re.search(r'\(property\s+"Value"\s+"([^"]*)"', snippet)
        if at_m:
            px, py = float(at_m.group(1)), float(at_m.group(2))
            net_name = val_m.group(1) if val_m else m.group(1)
            results.append((px, py, net_name))
    return results


# ── T-junction spatial index ──


def _build_wire_spatial_index(wires):
    """Build spatial indexes for O(1) T-junction lookups.

    KiCad wires are strictly horizontal or vertical.
    Returns (h_index, v_index) where:
      h_index: snapped_y -> [(x_min, x_max, wire_idx)]
      v_index: snapped_x -> [(y_min, y_max, wire_idx)]
    """
    h_index = {}  # horizontal wires by Y
    v_index = {}  # vertical wires by X
    tol = _GRID * 2  # small tolerance for H/V classification

    for idx, (x1, y1, x2, y2) in enumerate(wires):
        if abs(y1 - y2) < tol:
            # Horizontal wire
            sy = _snap(y1)
            mn, mx = (min(x1, x2), max(x1, x2))
            h_index.setdefault(sy, []).append((mn, mx, idx))
        elif abs(x1 - x2) < tol:
            # Vertical wire
            sx = _snap(x1)
            mn, mx = (min(y1, y2), max(y1, y2))
            v_index.setdefault(sx, []).append((mn, mx, idx))
        # Diagonal wires (shouldn't exist in KiCad) are ignored

    return h_index, v_index


def _find_t_junctions(point, h_index, v_index, wires, uf, tolerance=0.5):
    """Check if a point lies on the mid-segment of any wire (T-junction).

    If found, union the point with both endpoints of that wire.
    """
    px, py = point
    sp = _snap_pt(px, py)

    # Check horizontal wires at this Y
    sy = _snap(py)
    for dy in (sy - _GRID, sy, sy + _GRID):  # check neighboring grid lines
        for x_min, x_max, widx in h_index.get(dy, ()):
            # Point must be strictly interior (not at endpoints)
            if x_min + tolerance < px < x_max - tolerance:
                wx1, wy1, wx2, wy2 = wires[widx]
                if abs(py - wy1) < tolerance:
                    ep1 = _snap_pt(wx1, wy1)
                    ep2 = _snap_pt(wx2, wy2)
                    uf.union(sp, ep1)
                    uf.union(sp, ep2)

    # Check vertical wires at this X
    sx = _snap(px)
    for dx in (sx - _GRID, sx, sx + _GRID):
        for y_min, y_max, widx in v_index.get(dx, ()):
            if y_min + tolerance < py < y_max - tolerance:
                wx1, wy1, wx2, wy2 = wires[widx]
                if abs(px - wx1) < tolerance:
                    ep1 = _snap_pt(wx1, wy1)
                    ep2 = _snap_pt(wx2, wy2)
                    uf.union(sp, ep1)
                    uf.union(sp, ep2)


# ── Core graph builder ──


def _compute_all_pin_endpoints(schematic, schematic_path, pin_locator):
    """Compute pin endpoints for every non-template, non-power symbol.

    Returns list of (ref, pin_num, pin_name, pin_x, pin_y, value, lib_id).
    """
    from commands.pin_locator import PinLocator

    sch_file = Path(schematic_path)
    results = []

    if not hasattr(schematic, "symbol"):
        return results

    for symbol in schematic.symbol:
        if not hasattr(symbol.property, "Reference"):
            continue
        ref = symbol.property.Reference.value
        if ref.startswith("_TEMPLATE") or ref.startswith("#PWR"):
            continue

        lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else ""
        value = (
            symbol.property.Value.value
            if hasattr(symbol.property, "Value")
            else ""
        )
        position = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
        sx = float(position[0])
        sy = float(position[1])
        sym_rot = float(position[2]) if len(position) > 2 else 0.0

        mirror_x = False
        mirror_y = False
        if hasattr(symbol, "mirror"):
            mirror_val = (
                str(symbol.mirror.value)
                if hasattr(symbol.mirror, "value")
                else str(symbol.mirror)
            )
            mirror_x = "x" in mirror_val
            mirror_y = "y" in mirror_val

        pins_def = pin_locator.get_symbol_pins(sch_file, lib_id)
        if not pins_def:
            continue

        for pin_num, pd in pins_def.items():
            prx = pd["x"]
            pry = -pd["y"]  # Y-up to Y-down
            if mirror_x:
                pry = -pry
            if mirror_y:
                prx = -prx
            prx, pry = PinLocator.rotate_point(prx, pry, sym_rot)
            pin_x = sx + prx
            pin_y = sy + pry
            results.append(
                (ref, pin_num, pd.get("name", pin_num), pin_x, pin_y,
                 value, lib_id)
            )

    return results


def build_net_graph(schematic, schematic_path, pin_locator, tolerance=0.5):
    """Build the complete pin-to-net graph using union-find.

    Single pass: O(W + L + P) where W=wires, L=labels, P=pins.
    T-junction detection via spatial index: O(1) per point.

    Returns:
        pin_nets:  dict  (ref, pin_num) -> net_name | None
        net_pins:  dict  net_name -> [(ref, pin_num, pin_name)]
        components: dict ref -> {lib_id, value, pins: {pin_num: {net, name, x, y}}}
        shorted_nets: list of {nets: [name1, name2, ...], labels: [...], power_symbols: [...]}
    """
    with open(schematic_path, "r", encoding="utf-8") as f:
        content = f.read()

    all_wires = _parse_wires(content)
    all_labels = _parse_labels(content)
    power_syms = _parse_power_symbols(content)

    # Phase 1: Union-find over wire connectivity
    uf = _UnionFind()
    h_index, v_index = _build_wire_spatial_index(all_wires)

    # Connect wire endpoints
    for x1, y1, x2, y2 in all_wires:
        ep1 = _snap_pt(x1, y1)
        ep2 = _snap_pt(x2, y2)
        uf.union(ep1, ep2)

    # Check all wire endpoints for T-junctions (endpoint on mid-segment)
    all_endpoints = set()
    for x1, y1, x2, y2 in all_wires:
        all_endpoints.add(_snap_pt(x1, y1))
        all_endpoints.add(_snap_pt(x2, y2))

    for pt in all_endpoints:
        _find_t_junctions(pt, h_index, v_index, all_wires, uf, tolerance)

    # Register label and power symbol positions in union-find
    # (connect them to any touching wire endpoint or mid-segment)
    for lx, ly, _name, _lt in all_labels:
        sp = _snap_pt(lx, ly)
        uf.find(sp)  # ensure point exists in UF
        # Check if label touches a wire endpoint
        if sp in all_endpoints:
            # Already connected via endpoint matching
            pass
        else:
            # Check T-junction (label on mid-segment of wire)
            _find_t_junctions(sp, h_index, v_index, all_wires, uf, tolerance)

    for px, py, _name in power_syms:
        sp = _snap_pt(px, py)
        uf.find(sp)
        if sp not in all_endpoints:
            _find_t_junctions(sp, h_index, v_index, all_wires, uf, tolerance)

    # Phase 2: Assign net names to union-find roots, detect shorts
    root_to_net = {}       # uf root -> canonical net_name (first wins)
    root_to_all = {}       # uf root -> {names: set, labels: list, power: list}
    for lx, ly, name, _lt in all_labels:
        sp = _snap_pt(lx, ly)
        root = uf.find(sp)
        if root not in root_to_net:
            root_to_net[root] = name
        info = root_to_all.setdefault(root, {"names": set(), "labels": [], "power": []})
        info["names"].add(name)
        info["labels"].append({"name": name, "type": _lt, "at": [lx, ly]})
    for px, py, name in power_syms:
        sp = _snap_pt(px, py)
        root = uf.find(sp)
        if root not in root_to_net:
            root_to_net[root] = name
        info = root_to_all.setdefault(root, {"names": set(), "labels": [], "power": []})
        info["names"].add(name)
        info["power"].append({"name": name, "at": [px, py]})

    # Detect shorted nets: roots where 2+ different net names merged
    shorted_nets = []
    for root, info in root_to_all.items():
        if len(info["names"]) > 1:
            shorted_nets.append({
                "nets": sorted(info["names"]),
                "labels": info["labels"],
                "power_symbols": info["power"],
            })

    # Phase 3: Compute pin endpoints and match to nets via O(1) UF lookup
    all_pins = _compute_all_pin_endpoints(
        schematic, schematic_path, pin_locator
    )

    pin_nets = {}    # (ref, pin_num) -> net_name | None
    net_pins = {}    # net_name -> [(ref, pin_num, pin_name)]
    components = {}  # ref -> {lib_id, value, pins: {pin_num: {...}}}

    for ref, pin_num, pin_name, px, py, value, lib_id in all_pins:
        if ref not in components:
            components[ref] = {
                "lib_id": lib_id,
                "value": value,
                "pins": {},
            }

        sp = _snap_pt(px, py)

        # Check if pin is in a connected region (touches wire or label)
        # First try direct UF lookup
        matched_net = None
        if sp in uf.parent:
            root = uf.find(sp)
            matched_net = root_to_net.get(root)
        else:
            # Pin might not exactly match a wire endpoint — check T-junctions
            _find_t_junctions(sp, h_index, v_index, all_wires, uf, tolerance)
            if sp in uf.parent:
                root = uf.find(sp)
                matched_net = root_to_net.get(root)

        # Direct label/power contact (no wire between them)
        if matched_net is None:
            for lx, ly, name, _lt in all_labels:
                if abs(px - lx) < tolerance and abs(py - ly) < tolerance:
                    matched_net = name
                    break
        if matched_net is None:
            for ppx, ppy, pname in power_syms:
                if abs(px - ppx) < tolerance and abs(py - ppy) < tolerance:
                    matched_net = pname
                    break

        pin_nets[(ref, pin_num)] = matched_net
        components[ref]["pins"][pin_num] = {
            "name": pin_name,
            "net": matched_net,
            "x": round(px, 2),
            "y": round(py, 2),
        }
        if matched_net is not None:
            net_pins.setdefault(matched_net, []).append(
                (ref, pin_num, pin_name)
            )

    return pin_nets, net_pins, components, shorted_nets


# ── Query functions (thin wrappers over build_net_graph) ──


def get_component_nets(schematic, schematic_path, pin_locator, reference):
    """Return {pin_num: net_name_or_null} for every pin of a component."""
    _pin_nets, _net_pins, components, _shorted = build_net_graph(
        schematic, schematic_path, pin_locator
    )
    if reference not in components:
        return None, f"Component {reference} not found"

    comp = components[reference]
    pin_map = {}
    for pin_num, info in comp["pins"].items():
        pin_map[pin_num] = {
            "net": info["net"],
            "name": info["name"],
            "x": info["x"],
            "y": info["y"],
        }
    return {
        "reference": reference,
        "lib_id": comp["lib_id"],
        "value": comp["value"],
        "pins": pin_map,
    }, None


def get_net_components(schematic, schematic_path, pin_locator, net_name):
    """Return all component pins on a given net."""
    _pin_nets, net_pins, _components, _shorted = build_net_graph(
        schematic, schematic_path, pin_locator
    )
    if net_name not in net_pins:
        return {"netName": net_name, "connections": [], "count": 0}, None

    connections = []
    for ref, pin_num, pin_name in net_pins[net_name]:
        connections.append({
            "component": ref,
            "pin": pin_num,
            "pinName": pin_name,
        })
    return {
        "netName": net_name,
        "connections": connections,
        "count": len(connections),
    }, None


def get_pin_net_name(schematic, schematic_path, pin_locator, reference, pin):
    """Return just the net name for a single component pin."""
    _pin_nets, _net_pins, components, _shorted = build_net_graph(
        schematic, schematic_path, pin_locator
    )
    if reference not in components:
        return None, f"Component {reference} not found"

    comp = components[reference]
    if pin not in comp["pins"]:
        return None, f"Pin {pin} not found on {reference}"

    info = comp["pins"][pin]
    return {
        "reference": reference,
        "pin": pin,
        "pinName": info["name"],
        "net": info["net"],
    }, None


def export_netlist_summary(schematic, schematic_path, pin_locator):
    """Dump the complete netlist in a simple text format."""
    _pin_nets, net_pins, components, _shorted = build_net_graph(
        schematic, schematic_path, pin_locator
    )

    lines = []

    # Section 1: Components and their pin-net assignments
    lines.append("=== COMPONENTS ===")
    for ref in sorted(components.keys()):
        comp = components[ref]
        lines.append(f"\n{ref}  ({comp['lib_id']})  Value={comp['value']}")
        for pin_num in sorted(comp["pins"].keys()):
            info = comp["pins"][pin_num]
            net_str = info["net"] if info["net"] else "<unconnected>"
            lines.append(f"  Pin {pin_num} ({info['name']}): {net_str}")

    # Section 2: Nets and their connections
    lines.append("\n\n=== NETS ===")
    for net_name in sorted(net_pins.keys()):
        conns = net_pins[net_name]
        lines.append(f"\n{net_name}  ({len(conns)} pins)")
        for ref, pin_num, pin_name in sorted(conns, key=lambda c: c[0]):
            lines.append(f"  {ref} pin {pin_num} ({pin_name})")

    # Section 3: Unconnected pins
    unconnected = []
    for ref in sorted(components.keys()):
        for pin_num, info in components[ref]["pins"].items():
            if info["net"] is None:
                unconnected.append((ref, pin_num, info["name"]))
    if unconnected:
        lines.append(f"\n\n=== UNCONNECTED ({len(unconnected)}) ===")
        for ref, pin_num, pin_name in unconnected:
            lines.append(f"  {ref} pin {pin_num} ({pin_name})")

    return "\n".join(lines), None


def validate_component_connections(
    schematic, schematic_path, pin_locator, reference, expected
):
    """Validate a component's pin-to-net mapping against expectations.

    Args:
        expected: dict of pin_num -> expected_net_name.
            Prefix with "!" to assert pin is NOT on that net.
            Use None or "unconnected" to assert pin has no net.
    """
    _pin_nets, _net_pins, components, _shorted = build_net_graph(
        schematic, schematic_path, pin_locator
    )
    if reference not in components:
        return None, f"Component {reference} not found"

    comp = components[reference]
    results = []
    all_pass = True

    for pin_num, expected_net in expected.items():
        pin_num_str = str(pin_num)
        if pin_num_str not in comp["pins"]:
            results.append({
                "pin": pin_num_str,
                "expected": expected_net,
                "actual": None,
                "pass": False,
                "error": f"Pin {pin_num_str} not found on {reference}",
            })
            all_pass = False
            continue

        actual_net = comp["pins"][pin_num_str]["net"]
        pin_name = comp["pins"][pin_num_str]["name"]

        # Handle negation: "!+5V" means must NOT be on +5V
        if isinstance(expected_net, str) and expected_net.startswith("!"):
            forbidden_net = expected_net[1:]
            passed = actual_net != forbidden_net
            results.append({
                "pin": pin_num_str,
                "pinName": pin_name,
                "expected": expected_net,
                "actual": actual_net,
                "pass": passed,
            })
        elif expected_net is None or expected_net == "unconnected":
            passed = actual_net is None
            results.append({
                "pin": pin_num_str,
                "pinName": pin_name,
                "expected": "unconnected",
                "actual": actual_net,
                "pass": passed,
            })
        else:
            passed = actual_net == expected_net
            results.append({
                "pin": pin_num_str,
                "pinName": pin_name,
                "expected": expected_net,
                "actual": actual_net,
                "pass": passed,
            })

        if not passed:
            all_pass = False

    return {
        "reference": reference,
        "allPass": all_pass,
        "results": results,
        "checkedPins": len(results),
        "failedPins": sum(1 for r in results if not r["pass"]),
    }, None


def find_shorted_nets(schematic, schematic_path, pin_locator):
    """Detect nets that are accidentally merged (two+ named nets on same wire)."""
    _pin_nets, _net_pins, _components, shorted_nets = build_net_graph(
        schematic, schematic_path, pin_locator
    )
    return {
        "shorted": shorted_nets,
        "count": len(shorted_nets),
    }, None


def find_single_pin_nets(
    schematic, schematic_path, pin_locator, exclude_no_connect=True
):
    """Find nets with only one component pin — usually a broken connection.

    Args:
        exclude_no_connect: If True (default), skip nets where the single
            pin has a no-connect flag. (Not yet implemented — reserved.)
    """
    _pin_nets, net_pins, _components, _shorted = build_net_graph(
        schematic, schematic_path, pin_locator
    )

    singles = []
    for net_name, pins in net_pins.items():
        if len(pins) == 1:
            ref, pin_num, pin_name = pins[0]
            singles.append({
                "net": net_name,
                "component": ref,
                "pin": pin_num,
                "pinName": pin_name,
            })

    return {
        "singlePinNets": singles,
        "count": len(singles),
    }, None
