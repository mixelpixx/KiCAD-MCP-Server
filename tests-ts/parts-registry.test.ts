import { describe, it, expect } from "vitest";
import { getCategory, getToolCategory, isRoutedTool } from "../src/tools/registry.js";

// The parts-registry integration (issue #297) exposes three tools for checking
// the open PartReel registry before generating a custom footprint/symbol.
const PARTS_REGISTRY_TOOLS = [
  "search_parts_registry",
  "get_registry_part",
  "download_registry_part",
];

describe("parts-registry category", () => {
  it("is registered with a name, description, and its three tools", () => {
    const category = getCategory("parts-registry");
    expect(category).toBeDefined();
    expect(category?.description.length).toBeGreaterThan(0);
    expect(category?.tools).toEqual(PARTS_REGISTRY_TOOLS);
  });

  it("maps each tool back to the parts-registry category", () => {
    for (const tool of PARTS_REGISTRY_TOOLS) {
      expect(isRoutedTool(tool)).toBe(true);
      expect(getToolCategory(tool)).toBe("parts-registry");
    }
  });

  it("exports a tool registration function", async () => {
    const mod = await import("../src/tools/parts-registry.js");
    expect(typeof mod.registerPartsRegistryTools).toBe("function");
  });
});
