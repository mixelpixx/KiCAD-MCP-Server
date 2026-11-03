/**
 * Operating modes: limit what an agent can do, not just what it sees.
 *
 *   KICAD_MCP_OPERATING_MODE unset or "write"  every tool (the default)
 *   "readonly"       only tools that cannot change the design or project
 *   "manufacturing"  readonly plus the export tools that produce fabrication
 *                    and documentation output
 *
 * The idea and the mode names come from #443/#444 (@b0gdaniy). The design
 * differs from that PR in two ways:
 *
 * - Default-deny lists instead of name prefixes. A tool is allowed in readonly
 *   mode only if READ_ONLY_TOOLS names it, and each entry was checked against
 *   its handler. Deciding by prefix (get_, list_, find_, check_...) would let a
 *   future find_and_replace or check_and_fix through unreviewed; here a new
 *   tool is hidden until someone adds it.
 * - Disallowed tools are hidden, through the same RegisteredTool.enabled flag
 *   toolboxes use (toolboxes.ts). The SDK then rejects calls to them, and the
 *   client's tool list shrinks instead of offering tools that always fail.
 *
 * An unrecognised value fails closed to readonly: a typo must not leave an
 * agent that was told "you cannot change anything" able to.
 */

export const OPERATING_MODE_ENV = "KICAD_MCP_OPERATING_MODE";

export type OperatingMode = "write" | "readonly" | "manufacturing";

export interface OperatingModeSetting {
  mode: OperatingMode;
  /** The raw value when it was not recognised (the mode is then readonly). */
  unrecognised?: string;
}

const ALIASES: Record<string, OperatingMode> = {
  write: "write",
  readonly: "readonly",
  manufacturing: "manufacturing",
};

/** Read a KICAD_MCP_OPERATING_MODE value; "-", "_" and case are ignored. */
export function parseOperatingMode(raw: string | undefined): OperatingModeSetting {
  const value = (raw ?? "").trim();
  if (value === "") return { mode: "write" };
  const mode = ALIASES[value.toLowerCase().replace(/[-_\s]/g, "")];
  return mode ? { mode } : { mode: "readonly", unrecognised: value };
}

/**
 * Tools that never change the design, the project, libraries, library tables
 * or KiCad's configuration, and never launch or drive the KiCad GUI. Loading a
 * project into the session counts as reading. Some write output files outside
 * the design (a DRC report, a rendered preview); that is allowed.
 */
export const READ_ONLY_TOOLS: ReadonlySet<string> = new Set<string>([
  // Discovery
  "search_tools",
  "list_tool_categories",
  "get_category_tools",
  "list_toolboxes",
  "open_toolbox",
  "close_toolbox",
  // Projects, libraries and parts lookups. reload_board re-reads the board from
  // disk; in readonly mode there are no unsaved edits for it to drop.
  "batch_list_symbol_pins",
  "check_kicad_ui",
  "digikey_check_library_availability",
  "digikey_search_parts",
  "digikey_test_connection",
  "find_duplicate_symbols",
  "get_backend_state",
  "get_datasheet_url",
  "get_footprint_info",
  "get_jlcpcb_database_stats",
  "get_jlcpcb_part",
  "get_project_info",
  "get_registry_part",
  "get_symbol_info",
  "is_dirty",
  "list_footprint_libraries",
  "list_libraries",
  "list_library_footprints",
  "list_library_symbols",
  "list_library_table",
  "list_symbol_libraries",
  "list_symbol_pins",
  "list_symbols_in_library",
  "open_board",
  "open_project",
  "reload_board",
  "search_footprints",
  "search_jlcpcb_parts",
  "search_parts_registry",
  "search_symbols",
  "suggest_jlcpcb_alternatives",
  // Board inspection. run_drc and get_drc_violations write a JSON report next
  // to the board; get_board_2d_view can write a preview image there.
  "check_clearance",
  "check_courtyard_overlaps",
  "check_freerouting",
  "check_placement_clearance",
  "estimate_airwire_lengths",
  "find_component",
  "get_board_2d_view",
  "get_board_extents",
  "get_board_info",
  "get_board_origin",
  "get_component_geometry",
  "get_component_list",
  "get_component_pads",
  "get_component_properties",
  "get_design_rules",
  "get_drc_violations",
  "get_layer_list",
  "get_net_pads",
  "get_nets_list",
  "get_pad_position",
  "get_pads",
  "get_ratsnest",
  "list_graphics",
  "query_traces",
  "query_zones",
  "run_drc",
  // Schematic inspection. run_erc, generate_netlist and the view tools work in
  // temporary directories; validate_* run kicad-cli on a copy.
  "find_orphaned_wires",
  "find_overlapping_elements",
  "find_wires_crossing_symbols",
  "generate_netlist",
  "get_elements_in_region",
  "get_net_at_point",
  "get_net_connections",
  "get_schematic_component",
  "get_schematic_pin_locations",
  "get_schematic_view",
  "get_schematic_view_region",
  "get_sheet_properties",
  "get_wire_connections",
  "list_floating_labels",
  "list_schematic_components",
  "list_schematic_labels",
  "list_schematic_nets",
  "list_schematic_texts",
  "list_schematic_wires",
  "run_erc",
  "validate_schematic",
  "validate_symbol_library",
]);

/** Export tools: produce output files from the design without changing it. */
export const EXPORT_TOOLS: ReadonlySet<string> = new Set<string>([
  "export_3d",
  "export_3d_cli",
  "export_bom",
  "export_drill",
  "export_gencad",
  "export_gerber",
  "export_gerber_single",
  "export_gerbers",
  "export_ipc2581",
  "export_ipcd356",
  "export_netlist",
  "export_odb",
  "export_pcb_dxf",
  "export_pcb_pdf",
  "export_pcb_svg",
  "export_pdf",
  "export_pos",
  "export_position_file",
  "export_sch_bom",
  "export_sch_dxf",
  "export_sch_hpgl",
  "export_sch_pdf",
  "export_sch_ps",
  "export_sch_python_bom",
  "export_sch_svg",
  "export_schematic_pdf",
  "export_schematic_svg",
  "export_svg",
  "export_vrml",
]);

/** Whether `mode` allows `tool`. */
export function allowedInMode(tool: string, mode: OperatingMode): boolean {
  if (mode === "write") return true;
  if (READ_ONLY_TOOLS.has(tool)) return true;
  return mode === "manufacturing" && EXPORT_TOOLS.has(tool);
}
