import { beforeEach, describe, expect, it } from "vitest";
import {
  directToolNames,
  getAllCategories,
  getCategory,
  getRegistryStats,
  getRoutedToolNames,
  getToolCategory,
  getToolDefinition,
  isDirectTool,
  isRoutedTool,
  registerToolDefinition,
  resetToolRegistryForTests,
  searchTools,
} from "../src/tools/registry.js";

function registerFixtureCatalog(): void {
  registerToolDefinition({
    name: "create_project",
    title: "Create Project",
    description: "Create a new KiCad project",
    category: "project",
  });
  registerToolDefinition({
    name: "get_board_info",
    title: "Get Board Info",
    description: "Inspect the current PCB",
    category: "board",
  });
  registerToolDefinition({
    name: "export_gerber",
    title: "Export Gerber",
    description: "Export a Gerber fabrication layer",
    category: "export",
  });
  registerToolDefinition({
    name: "search_tools",
    title: "Search Tools",
    description: "Search the tool catalog",
    category: "router",
  });
}

describe("runtime tool registry", () => {
  beforeEach(() => {
    resetToolRegistryForTests();
    registerFixtureCatalog();
  });

  it("builds categories from first-class tool registrations", () => {
    expect(getAllCategories().map((category) => category.name)).toEqual([
      "project",
      "board",
      "export",
    ]);
    expect(getCategory("board")?.tools).toEqual(["get_board_info"]);
    expect(getToolCategory("export_gerber")).toBe("export");
    expect(getToolDefinition("create_project")?.title).toBe("Create Project");
  });

  it("excludes supplemental router tools from capability categories", () => {
    expect(getToolCategory("search_tools")).toBeUndefined();
    expect(getRoutedToolNames()).not.toContain("search_tools");
    expect(getRegistryStats()).toMatchObject({
      total_categories: 3,
      total_tools: 3,
      total_routed_tools: 3,
      total_direct_tools: 0,
    });
  });

  it("treats every KiCad capability as a directly callable MCP tool", () => {
    expect(directToolNames).toEqual([]);
    expect(isDirectTool("create_project")).toBe(false);
    expect(isRoutedTool("create_project")).toBe(true);
  });

  it("searches name, title, description, and category", () => {
    expect(searchTools("fabrication").map((result) => result.tool)).toEqual(["export_gerber"]);
    expect(searchTools("board").map((result) => result.tool)).toEqual(["get_board_info"]);
    expect(searchTools("unknown")).toEqual([]);
  });

  it("is idempotent for repeated server factories", () => {
    registerFixtureCatalog();
    expect(getRoutedToolNames()).toEqual(["create_project", "get_board_info", "export_gerber"]);
  });

  it("rejects conflicting metadata for the same tool name", () => {
    expect(() =>
      registerToolDefinition({
        name: "create_project",
        title: "Wrong Title",
        description: "Create a new KiCad project",
        category: "project",
      }),
    ).toThrow(/Conflicting catalog metadata/);
  });
});
