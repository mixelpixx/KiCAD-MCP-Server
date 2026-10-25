/**
 * Tool Registry for KiCAD MCP Server
 *
 * Centralizes all tool definitions and provides lookup/search functionality
 */

import { z } from "zod";

export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: z.ZodObject<any> | z.ZodType<any>;
  // Handler will be registered separately in the existing tool files
}

export interface ToolCategory {
  name: string;
  description: string;
  tools: string[]; // Tool names in this category
}

/**
 * Tool category definitions
 * Each category groups related tools for better organization
 */
export const toolCategories: ToolCategory[] = [
  {
    name: "board",
    description:
      "Board configuration: layers, mounting holes, text and graphics, SVG logos, zones, visualization",
    tools: [
      "add_layer",
      "set_active_layer",
      "get_layer_list",
      "add_mounting_hole",
      "add_board_text",
      "list_graphics",
      "delete_graphic",
      "update_graphic",
      "import_svg_logo",
      "add_zone",
      "get_board_extents",
      "get_board_2d_view",
      "set_board_origin",
      "get_board_origin",
      "launch_kicad_ui",
    ],
  },
  {
    name: "component",
    description:
      "Advanced component operations: edit, delete, duplicate, arrays and alignment, search, pads, courtyard and placement checks, placement suggestions, group, annotate",
    tools: [
      "rotate_component",
      "delete_component",
      "edit_component",
      "duplicate_component",
      "place_component_array",
      "align_components",
      "set_footprint_type",
      "find_component",
      "get_component_list",
      "get_component_properties",
      "get_component_pads",
      "get_pad_position",
      "get_pads",
      "get_net_pads",
      "get_ratsnest",
      "estimate_airwire_lengths",
      "check_placement_clearance",
      "check_courtyard_overlaps",
      "suggest_placement",
      "move_footprint_text",
      "add_component_annotation",
      "group_components",
      "replace_component",
      "hierarchical_place",
    ],
  },
  {
    name: "export",
    description: "File export for fabrication and documentation: Gerber, PDF, BOM, 3D models",
    tools: [
      "export_gerber",
      "export_gerbers",
      "export_drill",
      "export_ipc2581",
      "export_odb",
      "export_ipcd356",
      "export_gencad",
      "export_pos",
      "export_pcb_pdf",
      "export_pcb_svg",
      "export_pcb_dxf",
      "export_gerber_single",
      "export_3d_cli",
      "export_sch_bom",
      "export_sch_pdf",
      "export_sch_svg",
      "export_sch_dxf",
      "export_sch_hpgl",
      "export_sch_ps",
      "export_sch_python_bom",
      "export_pdf",
      "export_svg",
      "export_3d",
      "export_bom",
      "export_netlist",
      "export_position_file",
      "export_vrml",
    ],
  },
  {
    name: "drc",
    description: "Design rule checking and electrical validation: DRC, net classes, clearances",
    tools: [
      "set_design_rules",
      "get_design_rules",
      "run_drc",
      "create_netclass",
      "assign_net_to_class",
      "set_layer_constraints",
      "check_clearance",
      "get_drc_violations",
    ],
  },
  {
    name: "schematic",
    description:
      "Schematic operations: create, inspect, add/edit/delete components and their properties, wire connections, net labels, netlists, annotation, ERC",
    tools: [
      "create_schematic",
      "add_schematic_component",
      "list_schematic_components",
      "move_schematic_component",
      "rotate_schematic_component",
      "annotate_schematic",
      "add_schematic_wire",
      "delete_schematic_wire",
      "add_schematic_net_label",
      "delete_schematic_net_label",
      "add_no_connect",
      "connect_to_net",
      "connect_passthrough",
      "get_net_connections",
      "list_schematic_nets",
      "list_schematic_wires",
      "list_schematic_labels",
      "get_wire_connections",
      "generate_netlist",
      "sync_schematic_to_board",
      "backannotate_footprints",
      "get_schematic_view",
      "export_schematic_svg",
      "export_schematic_pdf",
      "add_schematic_text",
      "list_schematic_texts",
      // Kept after the original entries so search_tools results, which follow
      // this order, stay as they were.
      "get_schematic_component",
      "edit_schematic_component",
      "set_schematic_component_property",
      "remove_schematic_component_property",
      "delete_schematic_component",
      "get_schematic_pin_locations",
      "move_schematic_net_label",
      "get_net_at_point",
      "get_schematic_view_region",
      "run_erc",
    ],
  },
  {
    name: "library",
    description:
      "Footprint library access: register and list footprint libraries, search, browse, get footprint information, maintain library tables",
    tools: [
      "list_libraries",
      "list_footprint_libraries",
      "register_footprint_library",
      "search_footprints",
      "list_library_footprints",
      "get_footprint_info",
      // Library table maintenance: the read/remove/repoint counterparts to
      // register_symbol_library and register_footprint_library.
      "list_library_table",
      "remove_library_table_entry",
      "set_library_table_uri",
    ],
  },
  {
    name: "symbol_library",
    description:
      "Symbol library access and maintenance: search/browse sym-lib-table libraries, create/edit/rename/import/export symbols in a .kicad_sym file, repair malformed vendor symbols, and sync placed schematic instances to their library definitions",
    tools: [
      "list_symbol_libraries",
      "search_symbols",
      "list_library_symbols",
      "get_symbol_info",
      "create_symbol",
      "delete_symbol",
      "rename_symbol",
      "import_symbol",
      "export_symbol",
      "list_symbols_in_library",
      "register_symbol_library",
      "add_symbol_property",
      "repair_flat_symbols",
      "update_symbol_from_library",
      "add_library_symbol_property",
      "replace_instance_lib_ids",
      "find_duplicate_symbols",
    ],
  },
  {
    name: "symbol_pins",
    description:
      "Read a symbol's pins straight from the library (no schematic needed), and set their electrical types",
    tools: ["list_symbol_pins", "batch_list_symbol_pins", "set_symbol_pin_type"],
  },
  {
    name: "schematic_hierarchy",
    description:
      "Hierarchical schematic sheets: insert/remove a sheet, scaffold a sub-sheet, add hierarchical labels and sheet pins, read and write sheet properties",
    tools: [
      "add_hierarchical_sheet",
      "remove_hierarchical_sheet",
      "create_hierarchical_subsheet",
      "add_schematic_hierarchical_label",
      "add_sheet_pin",
      "set_sheet_property",
      "get_sheet_properties",
    ],
  },
  {
    name: "schematic_layout",
    description:
      "Schematic layout and lint: move and autoplace Ref/Value fields, suggest decluttering, find overlapping elements, wires crossing symbols, floating labels and orphaned wires, inspect a region, and find/snap off-grid coordinates",
    tools: [
      "set_schematic_property_position",
      "batch_set_schematic_property_positions",
      "autoplace_schematic_fields",
      "suggest_schematic_declutter",
      "lint_schematic_cosmetic",
      "lint_offgrid",
      "snap_to_grid",
      "find_overlapping_elements",
      "find_wires_crossing_symbols",
      "list_floating_labels",
      "find_orphaned_wires",
      "get_elements_in_region",
    ],
  },
  {
    name: "schematic_batch",
    description:
      "Batch schematic authoring: add/edit/replace components, batch no-connects, batch connect, add-and-connect",
    tools: [
      "batch_add_components",
      "batch_edit_schematic_components",
      "replace_schematic_component",
      "batch_add_no_connects",
      "batch_connect",
      "batch_add_and_connect",
    ],
  },
  {
    name: "routing",
    description:
      "Tracks, vias, zones and nets: route arcs, pad-to-pad and differential pairs; modify, delete, query and copy routing; vias, stitching vias, copper pours and zone refill; net list and net colors",
    tools: [
      "route_arc_trace",
      "route_pad_to_pad",
      "route_differential_pair",
      "modify_trace",
      "delete_trace",
      "query_traces",
      "copy_routing_pattern",
      "add_via",
      "add_gnd_stitching_vias",
      "add_copper_pour",
      "query_zones",
      "refill_zones",
      "get_nets_list",
      "set_net_color",
    ],
  },
  {
    name: "autoroute",
    description: "Freerouting autorouter: automatic PCB routing via Specctra DSN/SES",
    tools: ["autoroute", "export_dsn", "import_ses", "check_freerouting"],
  },
  {
    name: "validation",
    description:
      "File integrity checks: locate structural damage in schematics and symbol libraries before KiCad refuses to open them",
    tools: ["validate_schematic", "validate_symbol_library"],
  },
  {
    name: "footprint",
    description:
      "Footprint creation and 3D models: create a footprint, edit its pads, copy a 3D model into the project, attach 3D models to footprint files or to placed footprints",
    tools: [
      "create_footprint",
      "edit_footprint_pad",
      "import_3d_model",
      "add_footprint_3d_model",
      "add_component_3d_model",
    ],
  },
  {
    name: "import",
    description:
      "Import designs from other tools: Eagle projects, and vendor PCB files (PADS, Altium, Eagle, CADSTAR, Fabmaster, P-CAD, SolidWorks PCB, Allegro)",
    tools: ["import_eagle_project", "import_pcb"],
  },
  {
    name: "jlcpcb",
    description:
      "JLCPCB/LCSC parts: download and search the local JLCPCB catalog, part details and stats, cheaper or in-stock alternatives, and LCSC datasheet lookup and enrichment",
    tools: [
      "download_jlcpcb_database",
      "get_jlcpcb_database_stats",
      "search_jlcpcb_parts",
      "get_jlcpcb_part",
      "suggest_jlcpcb_alternatives",
      "get_datasheet_url",
      "enrich_datasheets",
    ],
  },
  {
    name: "parts-registry",
    description:
      "Open gate-verified parts registry (PartReel by default, no auth): search existing KiCAD parts and download footprint/symbol/3D files before generating custom ones",
    tools: ["search_parts_registry", "get_registry_part", "download_registry_part"],
  },
  {
    name: "digikey",
    description:
      "Digi-Key Product Information V4: search parts for stock, price and lifecycle, and sweep a symbol library for obsolete or unavailable parts (needs DIGIKEY_CLIENT_ID / DIGIKEY_CLIENT_SECRET in the server environment)",
    tools: [
      "digikey_test_connection",
      "digikey_search_parts",
      "digikey_check_library_availability",
    ],
  },
  {
    name: "gui-driver",
    description:
      "GUI-driver: drive KiCad's live GUI (menus, toolbars, dialogs, plugins) over a token-gated localhost helper. Opt-in — deploy with install_gui_driver and enable via KICAD_GUI_DRIVER_ENABLE. Destructive items are advisory-flagged, not gated.",
    tools: [
      "install_gui_driver",
      "kicad_gui_tree",
      "kicad_gui_click",
      "kicad_run_action_plugin",
      "kicad_gui_wait_for",
      "kicad_gui_screenshot",
      "kicad_pcb_snapshot",
      "kicad_reload_and_open_plugin",
      "kicad_run_drc",
      "kicad_gui_tree_atspi",
      "kicad_gui_click_atspi",
    ],
  },
];

/**
 * Core tools: always visible, including in toolbox mode (see toolboxes.ts),
 * where they are what a client sees before it opens any toolbox.
 * These are the most frequently used tools.
 */
export const directToolNames = [
  // Project lifecycle
  "create_project",
  "open_project",
  "open_board",
  "reload_board",
  "close_project",
  "save_project",
  "save_as",
  "save_board",
  "is_dirty",
  "discard_or_reload",
  "snapshot_project",
  "get_project_info",

  // Core PCB operations
  "place_component",
  "move_component",
  "batch_move_components",
  "add_net",
  "route_trace",
  "get_board_info",
  "set_board_size",

  // Board setup
  "add_board_outline",
  "replace_board_outline",
  "clear_board_outline",
  "get_component_geometry",

  // Schematic essentials (always visible so AI uses them correctly)
  "add_schematic_component",
  "list_schematic_components",
  "annotate_schematic",
  "connect_passthrough",
  "connect_to_net",
  "add_schematic_net_label",

  // Schematic <-> PCB sync (F8 equivalent)
  "sync_schematic_to_board",
  "create_board_from_schematic",

  // UI management
  "get_backend_state",
  "check_kicad_ui",
];

/**
 * Tools that find other tools. All six are always registered; which of them a
 * client sees depends on the toolbox setting (see toolboxes.ts):
 * - every tool visible (the default): search_tools and the two category
 *   browsers; the toolbox controls are hidden, since nothing is closed;
 * - toolbox mode: search_tools and the three toolbox controls; list_toolboxes
 *   replaces the two category browsers.
 */
export const discoveryToolNames = [
  "search_tools",
  "list_tool_categories",
  "get_category_tools",
  "list_toolboxes",
  "open_toolbox",
  "close_toolbox",
];

// Build lookup maps at module load time
const categoryMap = new Map<string, ToolCategory>();
const toolCategoryMap = new Map<string, string>();

export function initializeRegistry() {
  // Build category map
  for (const category of toolCategories) {
    categoryMap.set(category.name, category);

    // Build tool -> category map
    for (const toolName of category.tools) {
      toolCategoryMap.set(toolName, category.name);
    }
  }
}

/**
 * Get a category by name
 */
export function getCategory(name: string): ToolCategory | undefined {
  return categoryMap.get(name);
}

/**
 * Get the category name for a tool
 */
export function getToolCategory(toolName: string): string | undefined {
  return toolCategoryMap.get(toolName);
}

/**
 * Get all categories
 */
export function getAllCategories(): ToolCategory[] {
  return toolCategories;
}

/**
 * Get every tool name reachable through a category.
 *
 * NOTE: this is not disjoint from `directToolNames`. Seven schematic
 * essentials appear in both — always visible to the client *and* findable
 * via search_tools. That overlap is deliberate; see `directToolNames`.
 */
export function getRoutedToolNames(): string[] {
  const allRoutedTools: string[] = [];
  for (const category of toolCategories) {
    allRoutedTools.push(...category.tools);
  }
  return allRoutedTools;
}

/**
 * Distinct tool names across categories, the direct list and the discovery
 * tools: every tool the server registers.
 *
 * The headline "N tools" figure must come from here, not from
 * routed.length + direct.length — that sum double-counts the overlap above.
 */
export function getDistinctToolNames(): string[] {
  return [...new Set([...getRoutedToolNames(), ...directToolNames, ...discoveryToolNames])];
}

/**
 * Check if a tool is a direct tool
 */
export function isDirectTool(toolName: string): boolean {
  return directToolNames.includes(toolName);
}

/**
 * Check if a tool is a routed tool
 */
export function isRoutedTool(toolName: string): boolean {
  return toolCategoryMap.has(toolName);
}

/**
 * Search for tools by keyword
 * Searches tool names, descriptions, and category names
 */
export interface SearchResult {
  category: string;
  tool: string;
  description: string;
}

export function searchTools(query: string): SearchResult[] {
  const q = query.toLowerCase();
  const matches: SearchResult[] = [];

  // Search direct tools first
  for (const toolName of directToolNames) {
    if (toolName.toLowerCase().includes(q)) {
      matches.push({
        category: "direct",
        tool: toolName,
        description: `${toolName} (direct tool — call directly by name)`,
      });
    }
  }

  for (const toolName of discoveryToolNames) {
    if (toolName.toLowerCase().includes(q)) {
      matches.push({
        category: "discovery",
        tool: toolName,
        description: `${toolName} (finds and organizes the other tools)`,
      });
    }
  }

  // Search routed tools by name and category
  for (const category of toolCategories) {
    const categoryMatch =
      category.name.toLowerCase().includes(q) || category.description.toLowerCase().includes(q);

    for (const toolName of category.tools) {
      if (toolName.toLowerCase().includes(q) || categoryMatch) {
        matches.push({
          category: category.name,
          tool: toolName,
          description: `${toolName} (${category.name})`,
        });
      }
    }
  }

  return matches.slice(0, 20); // Limit results
}

/**
 * Get statistics about the tool registry
 */
export function getRegistryStats() {
  const routedToolCount = getRoutedToolNames().length;
  const directToolCount = directToolNames.length;

  return {
    total_categories: toolCategories.length,
    total_routed_tools: routedToolCount,
    total_direct_tools: directToolCount,
    total_discovery_tools: discoveryToolNames.length,
    // Distinct, not routed+direct: seven tools are in both lists on purpose,
    // and summing overstated the headline count by exactly those seven.
    total_tools: getDistinctToolNames().length,
    categories: toolCategories.map((c) => ({
      name: c.name,
      tool_count: c.tools.length,
    })),
  };
}

// Initialize on module load
initializeRegistry();
