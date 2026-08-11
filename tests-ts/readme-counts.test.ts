import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// The README's headline tool count is hand-maintained prose and has drifted
// twice (see #329 review). Pin it to the registry so it self-corrects —
// same trick as tests/test_interface_construction.py uses for schema/route parity.
describe("README tool counts", () => {
  it("headline count matches co-located runtime registrations", () => {
    const root = join(dirname(fileURLToPath(import.meta.url)), "..");
    const readme = readFileSync(join(root, "README.md"), "utf-8");
    const toolsDir = join(root, "src", "tools");
    const pattern = /registerKiCadTool\(\s*server\s*,\s*"([a-z0-9_]+)"\s*,\s*"([a-z0-9_]+)"/g;
    const names = new Set<string>();
    const categories = new Set<string>();
    for (const file of readdirSync(toolsDir).filter((name) => name.endsWith(".ts"))) {
      const source = readFileSync(join(toolsDir, file), "utf-8");
      let match: RegExpExecArray | null;
      while ((match = pattern.exec(source)) !== null) {
        if (match[1] === "router") continue;
        categories.add(match[1]);
        names.add(match[2]);
      }
    }
    const m = readme.match(/(\d+) tools across (\d+) categories/);
    expect(m, "README should state 'N tools across M categories'").toBeTruthy();
    expect(Number(m![1]), "README tool count").toBe(names.size);
    expect(Number(m![2]), "README category count").toBe(categories.size);
  });
});
