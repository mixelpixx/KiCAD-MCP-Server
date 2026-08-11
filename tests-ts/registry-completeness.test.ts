import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * The v2 catalog is populated at the same call site that registers each MCP
 * tool. Source-level checks therefore guard the registration boundary itself:
 * capability modules must use registerKiCadTool, never the legacy SDK helper.
 */

const TOOLS_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "tools");

interface DeclaredTool {
  category: string;
  name: string;
  file: string;
}

function toolSources(): Array<{ file: string; source: string }> {
  return readdirSync(TOOLS_DIR)
    .filter((file) => file.endsWith(".ts"))
    .map((file) => ({ file, source: readFileSync(join(TOOLS_DIR, file), "utf-8") }));
}

function declaredTools(): DeclaredTool[] {
  const declarations: DeclaredTool[] = [];
  const pattern = /registerKiCadTool\(\s*server\s*,\s*"([a-z0-9_]+)"\s*,\s*"([a-z0-9_]+)"/g;

  for (const { file, source } of toolSources()) {
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(source)) !== null) {
      declarations.push({ category: match[1], name: match[2], file });
    }
  }
  return declarations;
}

describe("runtime registry completeness", () => {
  it("finds the co-located v2 tool registrations", () => {
    expect(declaredTools().length).toBeGreaterThan(150);
  });

  it("has no legacy server.tool registrations", () => {
    const legacy = toolSources()
      .filter(({ source }) => /\bserver\.tool\s*\(/.test(source))
      .map(({ file }) => file);
    expect(legacy).toEqual([]);
  });

  it("declares every tool name exactly once", () => {
    const owners = new Map<string, DeclaredTool>();
    const duplicates: string[] = [];
    for (const declaration of declaredTools()) {
      const previous = owners.get(declaration.name);
      if (previous) {
        duplicates.push(
          `${declaration.name}: ${previous.category} (${previous.file}) and ` +
            `${declaration.category} (${declaration.file})`,
        );
      } else {
        owners.set(declaration.name, declaration);
      }
    }
    expect(duplicates).toEqual([]);
  });

  it("includes the v2.7 parts-registry and PCB-import tools in the catalog boundary", () => {
    const byName = new Map(declaredTools().map((tool) => [tool.name, tool.category]));
    expect(byName.get("search_parts_registry")).toBe("parts_registry");
    expect(byName.get("get_registry_part")).toBe("parts_registry");
    expect(byName.get("download_registry_part")).toBe("parts_registry");
    expect(byName.get("import_pcb")).toBe("pcb_import");
  });
});
