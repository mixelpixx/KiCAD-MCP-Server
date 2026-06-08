import { describe, it, expect } from "vitest";
import {
  directToolNames,
  getAllCategories,
  getCategory,
  getRegistryStats,
  getRoutedToolNames,
  getToolCategory,
  isDirectTool,
  isRoutedTool,
  searchTools,
  toolCategories,
} from "../src/tools/registry.js";

describe("tool registry — categories", () => {
  it("getAllCategories returns the exported list", () => {
    const categories = getAllCategories();
    expect(categories).toBe(toolCategories);
    expect(categories.length).toBeGreaterThan(0);
  });

  it("every category has a name, description, and at least one tool", () => {
    for (const category of getAllCategories()) {
      expect(category.name).toBeTruthy();
      expect(category.description.length).toBeGreaterThan(0);
      expect(category.tools.length).toBeGreaterThan(0);
    }
  });

  it("getCategory returns a known category", () => {
    const schematic = getCategory("schematic");
    expect(schematic).toBeDefined();
    expect(schematic?.name).toBe("schematic");
    expect(schematic?.tools).toContain("add_schematic_wire");
  });

  it("getCategory returns undefined for unknown names", () => {
    expect(getCategory("nonexistent_category")).toBeUndefined();
  });
});

describe("tool registry — direct vs routed classification", () => {
  it("isDirectTool identifies direct tools", () => {
    expect(isDirectTool("create_project")).toBe(true);
    expect(isDirectTool("route_trace")).toBe(true);
  });

  it("isDirectTool rejects routed tools", () => {
    expect(isDirectTool("add_schematic_wire")).toBe(false);
  });

  it("isRoutedTool identifies routed tools", () => {
    expect(isRoutedTool("add_schematic_wire")).toBe(true);
    expect(isRoutedTool("export_gerber")).toBe(true);
  });

  it("isRoutedTool rejects direct tools and unknowns", () => {
    expect(isRoutedTool("create_project")).toBe(false);
    expect(isRoutedTool("totally_made_up_tool")).toBe(false);
  });

  it("getToolCategory maps a tool to its category", () => {
    expect(getToolCategory("add_schematic_wire")).toBe("schematic");
    expect(getToolCategory("export_gerber")).toBe("export");
    expect(getToolCategory("nonexistent_tool")).toBeUndefined();
  });
});

describe("tool registry — invariants", () => {
  // Schematic essentials are intentionally exposed both as direct tools (so the
  // AI sees them without first calling list_tool_categories) and via the
  // "schematic" / "schematic_batch" categories (so they surface during routed
  // discovery). See the directToolNames comment in src/tools/registry.ts.
  // Any direct/routed overlap outside this allowlist is unintentional.
  const INTENTIONAL_OVERLAP = new Set([
    "add_schematic_component",
    "list_schematic_components",
    "annotate_schematic",
    "connect_passthrough",
    "connect_to_net",
    "add_schematic_net_label",
    "sync_schematic_to_board",
  ]);

  it("direct/routed overlap is limited to the documented schematic essentials", () => {
    const routed = new Set(getRoutedToolNames());
    const unexpectedOverlap = directToolNames.filter(
      (name) => routed.has(name) && !INTENTIONAL_OVERLAP.has(name),
    );
    expect(unexpectedOverlap).toEqual([]);
  });

  it("no tool name is duplicated across categories", () => {
    const seen = new Map<string, string>();
    const duplicates: string[] = [];
    for (const category of getAllCategories()) {
      for (const tool of category.tools) {
        const previous = seen.get(tool);
        if (previous) {
          duplicates.push(`${tool} (${previous} + ${category.name})`);
        } else {
          seen.set(tool, category.name);
        }
      }
    }
    expect(duplicates).toEqual([]);
  });
});

describe("tool registry — stats", () => {
  it("getRegistryStats totals match the underlying sources", () => {
    const stats = getRegistryStats();
    expect(stats.total_categories).toBe(getAllCategories().length);
    expect(stats.total_routed_tools).toBe(getRoutedToolNames().length);
    expect(stats.total_direct_tools).toBe(directToolNames.length);
    expect(stats.total_tools).toBe(stats.total_routed_tools + stats.total_direct_tools);
  });

  it("getRegistryStats per-category counts match category.tools.length", () => {
    const stats = getRegistryStats();
    for (const entry of stats.categories) {
      const category = getCategory(entry.name);
      expect(category).toBeDefined();
      expect(entry.tool_count).toBe(category!.tools.length);
    }
  });
});

describe("tool registry — search", () => {
  it("searchTools finds routed tools by substring", () => {
    const results = searchTools("schematic");
    expect(results.length).toBeGreaterThan(0);
    expect(results.some((r) => r.tool === "add_schematic_wire")).toBe(true);
  });

  it("searchTools finds direct tools by substring", () => {
    const results = searchTools("create_project");
    expect(results.some((r) => r.category === "direct" && r.tool === "create_project")).toBe(true);
  });

  it("searchTools returns an empty array for no matches", () => {
    expect(searchTools("xyzzy_nonexistent_query")).toEqual([]);
  });

  it("searchTools caps results at 20", () => {
    const results = searchTools("a");
    expect(results.length).toBeLessThanOrEqual(20);
  });
});
