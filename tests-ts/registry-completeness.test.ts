import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";
import {
  directToolNames,
  getRegistryStats,
  getRoutedToolNames,
  toolCategories,
} from "../src/tools/registry.js";

// Every tool registered with server.tool() should also appear in the registry.
// If it does not, it is callable only by a client that already knows the name:
// search_tools cannot find it, and getRegistryStats() does not count it.
//
// This slipped through twice in one day -- #340 shipped import_pcb and #342
// shipped three schematic-hierarchy tools, all unregistered. The README count
// guard could not catch it, because omitting the registration leaves the README
// and the registry consistently wrong at the same number.
//
// Measuring found 75 pre-existing cases, so this is a RATCHET, not a clean
// gate: the known set is frozen below and any NEW omission fails. Shrinking
// the list is tracked separately -- do not add to it to make CI pass.
//
// #345 gave the symbol-library tools their own "symbol_library" category,
// shrinking this baseline from 75 to 60.
//
// Parsing source text is deliberate: the point is to compare what is wired
// into the server against what the registry claims, so reading the registry
// through both paths would defeat it.

const TOOLS_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "tools");

// Frozen baseline of tools registered on the server but absent from the
// registry. Every entry here is a tool users cannot discover via search_tools.
const KNOWN_UNREGISTERED = new Set([
  "add_component_3d_model",
  "add_footprint_3d_model",
  "add_gnd_stitching_vias",
  "add_schematic_hierarchical_label",
  "add_sheet_pin",
  "align_components",
  "check_courtyard_overlaps",
  "copy_routing_pattern",
  "create_footprint",
  "create_netclass",
  "delete_schematic_component",
  "delete_trace",
  "download_jlcpcb_database",
  "duplicate_component",
  "edit_footprint_pad",
  "edit_schematic_component",
  "enrich_datasheets",
  "find_orphaned_wires",
  "find_overlapping_elements",
  "find_wires_crossing_symbols",
  "get_category_tools",
  "get_component_list",
  "get_component_pads",
  "get_datasheet_url",
  "get_elements_in_region",
  "get_jlcpcb_database_stats",
  "get_jlcpcb_part",
  "get_net_at_point",
  "get_nets_list",
  "get_pad_position",
  "get_schematic_component",
  "get_schematic_pin_locations",
  "get_schematic_view_region",
  "import_3d_model",
  "import_eagle_project",
  "import_svg_logo",
  "list_floating_labels",
  "list_footprint_libraries",
  "list_tool_categories",
  "modify_trace",
  "move_schematic_net_label",
  "place_component_array",
  "query_traces",
  "query_zones",
  "refill_zones",
  "register_footprint_library",
  "remove_schematic_component_property",
  "route_arc_trace",
  "route_differential_pair",
  "route_pad_to_pad",
  "run_erc",
  "save_as",
  "search_jlcpcb_parts",
  "search_tools",
  "set_footprint_type",
  "set_schematic_component_property",
  "snap_to_grid",
  "suggest_jlcpcb_alternatives",
  "suggest_placement",
  "suggest_schematic_declutter",
]);

function registeredToolNames(): Set<string> {
  return new Set<string>([...getRoutedToolNames(), ...directToolNames]);
}

function serverToolNames(): Map<string, string> {
  // name -> declaring file, for a useful failure message
  const found = new Map<string, string>();
  for (const file of readdirSync(TOOLS_DIR)) {
    if (!file.endsWith(".ts")) continue;
    const src = readFileSync(join(TOOLS_DIR, file), "utf-8");
    const re = /server\.tool\(\s*"([a-z0-9_]+)"/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(src)) !== null) {
      if (!found.has(m[1])) found.set(m[1], file);
    }
  }
  return found;
}

describe("registry completeness", () => {
  it("finds the server.tool registrations at all", () => {
    // Guards the regex itself: a refactor that changes the call shape must
    // fail loudly here rather than silently making the checks below vacuous.
    expect(serverToolNames().size).toBeGreaterThan(150);
  });

  it("no NEW tool is registered on the server but missing from the registry", () => {
    const registered = registeredToolNames();
    const novel: string[] = [];
    for (const [name, file] of serverToolNames()) {
      if (registered.has(name) || KNOWN_UNREGISTERED.has(name)) continue;
      novel.push(`${name} (${file})`);
    }

    expect(
      novel,
      "These tools are registered on the MCP server but missing from " +
        "src/tools/registry.ts, so search_tools cannot discover them. Add each " +
        "to a toolCategories entry (routed) or to directToolNames " +
        "(always-visible essentials). Do not add them to KNOWN_UNREGISTERED.",
    ).toEqual([]);
  });

  it("the known-unregistered baseline does not grow", () => {
    const registered = registeredToolNames();
    const stillMissing = [...serverToolNames().keys()].filter((n) => !registered.has(n));
    expect(
      stillMissing.length,
      "Baseline should shrink as tools get registered, never grow.",
    ).toBeLessThanOrEqual(KNOWN_UNREGISTERED.size);
  });

  it("every registry entry is actually registered on the server", () => {
    // The reverse direction: a registry entry with no server.tool() would be
    // advertised by search_tools and then fail when called.
    const onServer = serverToolNames();
    const ghosts = [...registeredToolNames()].filter((n) => !onServer.has(n));
    expect(ghosts, "Registry advertises tools the server does not register").toEqual([]);
  });

  it("total_tools counts distinct tools, not category+direct with overlap", () => {
    // Seven schematic essentials are deliberately in BOTH a category and
    // directToolNames -- always visible, and still discoverable by search.
    // That overlap is intended; double-counting it is not. total_tools used to
    // be routed.length + direct.length, overstating the headline figure (and
    // therefore the README) by exactly those seven.
    const distinct = new Set<string>(directToolNames);
    for (const category of toolCategories) {
      for (const tool of category.tools) distinct.add(tool);
    }
    expect(getRegistryStats().total_tools).toBe(distinct.size);
  });

  it("no tool name is claimed by two categories", () => {
    const seen = new Map<string, string>();
    const clashes: string[] = [];
    for (const category of toolCategories) {
      for (const tool of category.tools) {
        const prior = seen.get(tool);
        if (prior) clashes.push(`${tool}: '${prior}' and '${category.name}'`);
        else seen.set(tool, category.name);
      }
    }
    expect(clashes).toEqual([]);
  });
});
