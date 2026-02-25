/**
 * Tool Registry for KiCAD MCP Server
 *
 * Centralizes all tool definitions and provides lookup/search functionality
 */

import { z } from 'zod';

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
    description: "Board configuration: layers, outline, mounting holes, zones, text, visualization",
    tools: [
      "add_layer",
      "set_active_layer",
      "get_layer_list",
      "add_board_outline",
      "add_mounting_hole",
      "add_board_text",
      "add_zone",
      "get_board_extents",
      "get_board_2d_view",
      "launch_kicad_ui",
      "check_kicad_ui"
    ]
  },
  {
    name: "component",
    description: "Component operations: place, move, rotate, edit, delete, search, group, annotate, align, duplicate, arrays, pads",
    tools: [
      "rotate_component",
      "delete_component",
      "edit_component",
      "find_component",
      "get_component_properties",
      "add_component_annotation",
      "group_components",
      "replace_component",
      "get_component_pads",
      "get_pad_position",
      "set_pad_net",
      "get_component_list",
      "align_components",
      "duplicate_component",
      "place_component_array"
    ]
  },
  {
    name: "export",
    description: "File export for fabrication and documentation: Gerber, PDF, SVG, BOM, 3D, netlist, position, VRML, schematic PDF",
    tools: [
      "export_gerber",
      "export_pdf",
      "export_svg",
      "export_3d",
      "export_bom",
      "export_netlist",
      "export_position_file",
      "export_vrml",
      "export_schematic_pdf"
    ]
  },
  {
    name: "drc",
    description: "Design rule checking and electrical validation: DRC, net classes, clearances, layer constraints",
    tools: [
      "set_design_rules",
      "get_design_rules",
      "run_drc",
      "add_net_class",
      "assign_net_to_class",
      "set_layer_constraints",
      "check_clearance",
      "get_drc_violations"
    ]
  },
  {
    name: "schematic",
    description: "Schematic operations: create, load, add components, wire connections, net labels, netlists",
    tools: [
      "create_schematic",
      "load_schematic",
      "add_schematic_component",
      "add_wire",
      "add_schematic_connection",
      "add_schematic_net_label",
      "connect_to_net",
      "get_net_connections",
      "generate_netlist"
    ]
  },
  {
    name: "library",
    description: "Footprint and symbol library access: search, browse, get detailed info",
    tools: [
      "list_libraries",
      "search_footprints",
      "list_library_footprints",
      "get_footprint_info",
      "list_symbol_libraries",
      "search_symbols",
      "list_library_symbols",
      "get_symbol_info"
    ]
  },
  {
    name: "routing",
    description: "Advanced routing: traces, vias, copper pours, differential pairs, trace management, zone refill",
    tools: [
      "add_via",
      "add_copper_pour",
      "delete_trace",
      "delete_all_traces",
      "query_traces",
      "modify_trace",
      "get_nets_list",
      "refill_zones",
      "route_differential_pair",
      "copy_routing_pattern"
    ]
  },
  {
    name: "jlcpcb",
    description: "JLCPCB parts catalog: search parts, get pricing/stock info, find alternatives, database management",
    tools: [
      "download_jlcpcb_database",
      "search_jlcpcb_parts",
      "get_jlcpcb_part",
      "get_jlcpcb_database_stats",
      "suggest_jlcpcb_alternatives"
    ]
  }
];

/**
 * Direct tools that are always visible (not routed)
 * These are the most frequently used tools
 */
export const directToolNames = [
  // Project lifecycle
  "create_project",
  "open_project",
  "save_project",
  "get_project_info",

  // Core PCB operations
  "place_component",
  "move_component",
  "add_net",
  "route_trace",
  "get_board_info",
  "set_board_size"
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

  // This is a placeholder - we'll populate descriptions from actual tool definitions
  // For now, we'll search by name and category
  for (const category of toolCategories) {
    // Check if category name or description matches
    const categoryMatch =
      category.name.toLowerCase().includes(q) ||
      category.description.toLowerCase().includes(q);

    for (const toolName of category.tools) {
      // Check if tool name matches or category matches
      if (toolName.toLowerCase().includes(q) || categoryMatch) {
        matches.push({
          category: category.name,
          tool: toolName,
          description: `${toolName} (${category.name})`
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
    categories: toolCategories.map(c => ({
      name: c.name,
      tool_count: c.tools.length
    }))
  };
}

// Initialize on module load
initializeRegistry();
