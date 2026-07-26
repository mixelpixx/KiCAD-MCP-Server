import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";
import { getRegistryStats } from "../src/tools/registry.js";

// The README's headline tool count is hand-maintained prose and has drifted
// twice (see #329 review). Pin it to the registry so it self-corrects —
// same trick as tests/test_interface_construction.py uses for schema/route parity.
describe("README tool counts", () => {
  it("headline count matches getRegistryStats()", () => {
    const readme = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "..", "README.md"),
      "utf-8",
    );
    const stats = getRegistryStats();
    const m = readme.match(/(\d+) tools across (\d+) categories/);
    expect(m, "README should state 'N tools across M categories'").toBeTruthy();
    expect(Number(m![1]), "README tool count").toBe(stats.total_tools);
    expect(Number(m![2]), "README category count").toBe(stats.total_categories);
  });
});
