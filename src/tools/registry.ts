/**
 * Runtime tool catalog.
 *
 * Every MCP tool is recorded by registerKiCadTool at the same point where it
 * is registered with the SDK. This keeps the discovery router in lockstep
 * with the actual MCP tool list instead of maintaining a second, stale list.
 */

export interface ToolDefinition {
  name: string;
  title: string;
  description: string;
  category: string;
}

export interface ToolCategory {
  name: string;
  description: string;
  tools: string[];
}

const CATEGORY_DESCRIPTIONS: Readonly<Record<string, string>> = {
  project: "Project lifecycle, persistence, and snapshots",
  board: "Board configuration, layers, outlines, zones, and visualization",
  component: "PCB component placement, inspection, editing, and alignment",
  routing: "Nets, tracks, vias, zones, and differential-pair routing",
  design_rules: "Board design rules and DRC validation",
  export: "Fabrication, assembly, documentation, and 3D exports",
  schematic: "Schematic authoring, inspection, connectivity, ERC, and synchronization",
  library: "Footprint and symbol library discovery",
  schematic_hierarchy: "Hierarchical schematic sheets and sub-sheets",
  schematic_layout: "Schematic field placement and decluttering",
  schematic_batch: "Batch schematic authoring and migration",
  jlcpcb: "JLCPCB catalog search and local database management",
  datasheet: "Datasheet discovery and enrichment",
  footprint: "Footprint creation, editing, libraries, and 3D models",
  symbol: "Symbol creation, editing, import, and export",
  ui: "KiCad UI process and backend status",
  autoroute: "Freerouting DSN/SES autorouting",
  eagle: "EAGLE project import",
  parts_registry: "Verified open-parts registry search, inspection, and asset download",
  pcb_import: "Vendor PCB layout import and conversion",
};

const definitions = new Map<string, ToolDefinition>();
const categories = new Map<string, ToolCategory>();

/** Router tools are supplemental discovery tools, not a KiCad capability category. */
const INTERNAL_CATEGORIES = new Set(["router"]);

export function registerToolDefinition(definition: ToolDefinition): void {
  const existing = definitions.get(definition.name);
  if (existing) {
    if (
      existing.category !== definition.category ||
      existing.description !== definition.description ||
      existing.title !== definition.title
    ) {
      throw new Error(`Conflicting catalog metadata for MCP tool: ${definition.name}`);
    }
    return;
  }

  definitions.set(definition.name, definition);
  if (INTERNAL_CATEGORIES.has(definition.category)) {
    return;
  }

  let category = categories.get(definition.category);
  if (!category) {
    category = {
      name: definition.category,
      description:
        CATEGORY_DESCRIPTIONS[definition.category] ??
        `${definition.category.replaceAll("_", " ")} tools`,
      tools: [],
    };
    categories.set(definition.category, category);
  }
  category.tools.push(definition.name);
}

export function getCategory(name: string): ToolCategory | undefined {
  return categories.get(name);
}

export function getToolCategory(toolName: string): string | undefined {
  const category = definitions.get(toolName)?.category;
  return category && !INTERNAL_CATEGORIES.has(category) ? category : undefined;
}

export function getToolDefinition(toolName: string): ToolDefinition | undefined {
  return definitions.get(toolName);
}

export function getAllCategories(): ToolCategory[] {
  return [...categories.values()];
}

/** All KiCad tools are first-class MCP tools; this returns the discoverable set. */
export function getRoutedToolNames(): string[] {
  return [...definitions.values()]
    .filter((definition) => !INTERNAL_CATEGORIES.has(definition.category))
    .map((definition) => definition.name);
}

/** Kept as a compatibility export. The server no longer hides a routed subset. */
export const directToolNames: readonly string[] = [];

export function isDirectTool(_toolName: string): boolean {
  return false;
}

export function isRoutedTool(toolName: string): boolean {
  return getToolCategory(toolName) !== undefined;
}

export interface SearchResult {
  category: string;
  tool: string;
  description: string;
}

export function searchTools(query: string): SearchResult[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return [];
  }

  return [...definitions.values()]
    .filter((definition) => !INTERNAL_CATEGORIES.has(definition.category))
    .filter(
      (definition) =>
        definition.name.toLowerCase().includes(normalized) ||
        definition.title.toLowerCase().includes(normalized) ||
        definition.description.toLowerCase().includes(normalized) ||
        definition.category.toLowerCase().includes(normalized),
    )
    .slice(0, 20)
    .map((definition) => ({
      category: definition.category,
      tool: definition.name,
      description: definition.description,
    }));
}

export function getRegistryStats() {
  const toolNames = getRoutedToolNames();
  return {
    total_categories: categories.size,
    total_routed_tools: toolNames.length,
    total_direct_tools: 0,
    total_tools: toolNames.length,
    categories: getAllCategories().map((category) => ({
      name: category.name,
      tool_count: category.tools.length,
    })),
  };
}

/** Test-only reset for creating more than one isolated server catalog. */
export function resetToolRegistryForTests(): void {
  definitions.clear();
  categories.clear();
}
