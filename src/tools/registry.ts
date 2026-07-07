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
    description: "Board configuration: layers, mounting holes, zones, visualization",
    tools: [
      "add_layer",
      "set_active_layer",
      "get_layer_list",
      "add_mounting_hole",
      "add_board_text",
      "list_graphics",
      "delete_graphic",
      "update_graphic",
      "add_zone",
      "get_board_extents",
      "get_board_2d_view",
      "launch_kicad_ui",
    ],
  },
  {
    name: "component",
    description: "Advanced component operations: edit, delete, search, group, annotate",
    tools: [
      "rotate_component",
      "delete_component",
      "edit_component",
      "find_component",
      "get_component_properties",
      "get_pads",
      "get_net_pads",
      "get_ratsnest",
      "estimate_airwire_lengths",
      "check_placement_clearance",
      "move_footprint_text",
      "add_component_annotation",
      "group_components",
      "replace_component",
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
      "add_net_class",
      "assign_net_to_class",
      "set_layer_constraints",
      "check_clearance",
      "get_drc_violations",
    ],
  },
  {
    name: "schematic",
    description:
      "Schematic operations: create, inspect, add/edit/delete components, wire connections, netlists, annotation",
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
      "get_schematic_view",
      "export_schematic_svg",
      "export_schematic_pdf",
      "add_schematic_text",
      "list_schematic_texts",
    ],
  },
  {
    name: "library",
    description: "Footprint library access: search, browse, get footprint information",
    tools: ["list_libraries", "search_footprints", "list_library_footprints", "get_footprint_info"],
  },
  {
    name: "symbol_pins",
    description: "Read a symbol's pins straight from the library (no schematic needed)",
    tools: ["list_symbol_pins", "batch_list_symbol_pins"],
  },
  {
    name: "schematic_hierarchy",
    description: "Hierarchical schematic sheets: insert a sheet, scaffold a sub-sheet",
    tools: ["add_hierarchical_sheet", "create_hierarchical_subsheet"],
  },
  {
    name: "schematic_layout",
    description:
      "Schematic field placement: move Ref/Value fields and autoplace them clear of bodies and labels",
    tools: [
      "set_schematic_property_position",
      "batch_set_schematic_property_positions",
      "autoplace_schematic_fields",
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
    description: "Advanced routing operations: vias, copper pours",
    tools: ["add_via", "add_copper_pour"],
  },
  {
    name: "autoroute",
    description: "Freerouting autorouter: automatic PCB routing via Specctra DSN/SES",
    tools: ["autoroute", "export_dsn", "import_ses", "check_freerouting"],
  },
];

/**
 * Direct tools that are always visible (not routed)
 * These are the most frequently used tools
 */
export const directToolNames = [
  // Project lifecycle
  "create_project",
  "open_project",
  "open_board",
  "reload_board",
  "close_project",
  "save_project",
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
 * Get all routed tool names (excludes direct tools)
 */
export function getRoutedToolNames(): string[] {
  const allRoutedTools: string[] = [];
  for (const category of toolCategories) {
    allRoutedTools.push(...category.tools);
  }
  return allRoutedTools;
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
        description: `${toolName} (direct tool — call directly, no execute_tool needed)`,
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
    total_tools: routedToolCount + directToolCount,
    categories: toolCategories.map((c) => ({
      name: c.name,
      tool_count: c.tools.length,
    })),
  };
}

// Initialize on module load
initializeRegistry();
