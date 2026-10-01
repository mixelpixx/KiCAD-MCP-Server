import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";
import {
  directToolNames,
  discoveryToolNames,
  getRegistryStats,
  getRoutedToolNames,
  toolCategories,
} from "../src/tools/registry.js";

// Every tool registered with server.tool() must also appear in the registry.
// If it does not, search_tools cannot find it, getRegistryStats() does not
// count it, and in toolbox mode (src/tools/toolboxes.ts) no toolbox can show
// it, so a client cannot reach it at all.
//
// This slipped through twice in one day -- #340 shipped import_pcb and #342
// shipped three schematic-hierarchy tools, all unregistered. The README count
// guard could not catch it, because omitting the registration leaves the README
// and the registry consistently wrong at the same number.
//
// This started as a ratchet over 75 pre-existing omissions. #345 gave the
// symbol-library tools their own category (75 -> 60), and the toolbox change
// placed the last 60, so it is now a plain gate.
//
// Parsing source text is deliberate: the point is to compare what is wired
// into the server against what the registry claims, so reading the registry
// through both paths would defeat it.

const TOOLS_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "tools");

function registeredToolNames(): Set<string> {
  return new Set<string>([...getRoutedToolNames(), ...directToolNames, ...discoveryToolNames]);
}

function serverToolNames(): Map<string, string> {
  // name -> declaring file, for a useful failure message
  const found = new Map<string, string>();
  for (const file of readdirSync(TOOLS_DIR)) {
    if (!file.endsWith(".ts")) continue;
    const src = readFileSync(join(TOOLS_DIR, file), "utf-8");
    const re = /server\.tool\(\s*"([a-z0-9_]+)"/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(src)) !== null) {
      if (!found.has(m[1])) found.set(m[1], file);
    }
  }
  return found;
}

describe("registry completeness", () => {
  it("finds the server.tool registrations at all", () => {
    // Guards the regex itself: a refactor that changes the call shape must
    // fail loudly here rather than silently making the checks below vacuous.
    expect(serverToolNames().size).toBeGreaterThan(150);
  });

  it("every tool registered on the server is in the registry", () => {
    const registered = registeredToolNames();
    const missing: string[] = [];
    for (const [name, file] of serverToolNames()) {
      if (!registered.has(name)) missing.push(`${name} (${file})`);
    }

    expect(
      missing,
      "These tools are registered on the MCP server but missing from " +
        "src/tools/registry.ts, so search_tools cannot find them and toolbox " +
        "mode hides them. Add each to the toolCategories entry it belongs to, " +
        "or to directToolNames if it must always be visible.",
    ).toEqual([]);
  });

  it("every registry entry is actually registered on the server", () => {
    // The reverse direction: a registry entry with no server.tool() would be
    // advertised by search_tools and then fail when called.
    const onServer = serverToolNames();
    const ghosts = [...registeredToolNames()].filter((n) => !onServer.has(n));
    expect(ghosts, "Registry advertises tools the server does not register").toEqual([]);
  });

  it("total_tools counts distinct tools, not category+direct with overlap", () => {
    // Seven schematic essentials are deliberately in BOTH a category and
    // directToolNames -- always visible, and still discoverable by search.
    // That overlap is intended; double-counting it is not. total_tools used to
    // be routed.length + direct.length, overstating the headline figure (and
    // therefore the README) by exactly those seven.
    const distinct = new Set<string>([...directToolNames, ...discoveryToolNames]);
    for (const category of toolCategories) {
      for (const tool of category.tools) distinct.add(tool);
    }
    expect(getRegistryStats().total_tools).toBe(distinct.size);
  });

  it("no tool name is claimed by two categories", () => {
    const seen = new Map<string, string>();
    const clashes: string[] = [];
    for (const category of toolCategories) {
      for (const tool of category.tools) {
        const prior = seen.get(tool);
        if (prior) clashes.push(`${tool}: '${prior}' and '${category.name}'`);
        else seen.set(tool, category.name);
      }
    }
    expect(clashes).toEqual([]);
  });
});
