#!/usr/bin/env node
/**
 * generate-tool-inventory.mjs — rebuild docs/TOOL_INVENTORY.md from the source.
 *
 * Why this script exists
 * ----------------------
 * The tool inventory used to be written by hand. Hand-written lists go stale
 * quietly: by v2.7.0 the document listed 138 tools while the server registered
 * 229, and the "Access" column still used labels from a router design that was
 * never shipped. A reader could not tell which entries were still true.
 *
 * This script reads the truth from two places and writes the document from it:
 *
 *   1. `src/tools/*.ts` — every `server.tool("name", "description", ...)` call.
 *      This is the set of tools an MCP client can actually call.
 *   2. `dist/tools/registry.js` — the categories used by `search_tools` and
 *      `get_category_tools`. This is the set of tools an AI assistant can
 *      *discover* by keyword. It is smaller than the set above.
 *
 * Descriptions already written by hand in the existing document are kept, so
 * regenerating never throws away human wording. Tools that are new to the
 * document get a short description derived from their code description.
 *
 * Usage
 * -----
 *   npm run build          # the script reads dist/tools/registry.js
 *   npm run docs:tools     # writes docs/TOOL_INVENTORY.md
 *   npm run docs:tools -- --check   # exit 1 if the file is out of date
 */

import { readFileSync, readdirSync, writeFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";
import prettier from "prettier";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const TOOLS_DIR = join(ROOT, "src", "tools");
const DOC_PATH = join(ROOT, "docs", "TOOL_INVENTORY.md");

const { toolCategories, directToolNames, getRegistryStats } = await import(
  new URL("../dist/tools/registry.js", import.meta.url).href
);

/**
 * Human-friendly section titles, in the order they should appear.
 * A source file missing from this map still gets a section — it is simply
 * placed at the end under its file name, so a new tool file can never be
 * dropped from the document by forgetting to update this list.
 */
const SECTIONS = [
  ["project.ts", "Project and Board Files"],
  ["board.ts", "Board Management"],
  ["component.ts", "Component Management"],
  ["routing.ts", "Routing"],
  ["design-rules.ts", "Design Rules and DRC"],
  ["export.ts", "Export and Fabrication Output"],
  ["schematic.ts", "Schematic"],
  ["schematic-batch.ts", "Schematic Batch Operations"],
  ["schematic-hierarchy.ts", "Hierarchical Sheets"],
  ["schematic-layout.ts", "Schematic Layout and Cosmetics"],
  ["validation.ts", "File Validation"],
  ["library.ts", "Footprint Libraries and Library Tables"],
  ["library-symbol.ts", "Symbol Libraries"],
  ["footprint.ts", "Footprint Creator"],
  ["symbol-creator.ts", "Symbol Creator"],
  ["datasheet.ts", "Datasheet Tools"],
  ["jlcpcb-api.ts", "JLCPCB Integration"],
  ["parts-registry.ts", "Parts Registry"],
  ["freerouting.ts", "Freerouting Autorouter"],
  ["eagle.ts", "Eagle Import"],
  ["pcb-import.ts", "PCB Import"],
  ["ui.ts", "KiCad UI and Backend"],
  ["router.ts", "Tool Discovery"],
];

/**
 * Read the second argument of a `server.tool(...)` call.
 *
 * The description is often written as several string literals joined with `+`
 * across many lines, so a single regular expression cannot capture it. This
 * walks the source from the given offset and joins the literals it finds.
 */
function readDescription(src, from) {
  let i = from;
  let out = "";
  for (;;) {
    while (i < src.length && /\s/.test(src[i])) i++;
    if (src[i] !== '"') break;
    i++;
    let buf = "";
    while (i < src.length && src[i] !== '"') {
      if (src[i] === "\\") {
        // Keep the escaped character itself; the escape is a TypeScript
        // detail, not part of the description text.
        buf += src[i + 1] === "n" ? " " : src[i + 1];
        i += 2;
        continue;
      }
      buf += src[i++];
    }
    i++; // closing quote
    out += buf;
    while (i < src.length && /\s/.test(src[i])) i++;
    if (src[i] !== "+") break;
    i++;
  }
  return out.replace(/\s+/g, " ").trim();
}

/** Collect every tool the server registers, grouped by source file. */
function collectTools() {
  const byFile = new Map();
  const seen = new Set();
  for (const file of readdirSync(TOOLS_DIR).sort()) {
    if (!file.endsWith(".ts")) continue;
    const src = readFileSync(join(TOOLS_DIR, file), "utf-8");
    const re = /server\.tool\(\s*"([a-z0-9_]+)"\s*,/g;
    let m;
    while ((m = re.exec(src)) !== null) {
      const name = m[1];
      if (seen.has(name)) continue; // a name is registered once, first wins
      seen.add(name);
      if (!byFile.has(file)) byFile.set(file, []);
      byFile.get(file).push({ name, description: readDescription(src, re.lastIndex) });
    }
  }
  return byFile;
}

/** Descriptions already present in the document, so hand wording survives. */
function existingDescriptions() {
  const kept = new Map();
  let doc;
  try {
    doc = readFileSync(DOC_PATH, "utf-8");
  } catch {
    return kept;
  }
  for (const line of doc.split("\n")) {
    if (!line.startsWith("| `")) continue;
    // Split on pipes that are not escaped, so a description containing an
    // escaped pipe is read back whole rather than truncated.
    const cells = line.split(/(?<!\\)\|/).map((c) => c.trim());
    const m = cells[1] && cells[1].match(/^`([a-z0-9_]+)`$/);
    if (m && cells[2]) kept.set(m[1], cells[2]);
  }
  return kept;
}

/** Shorten a code description to one clause that fits a table cell. */
function shorten(text) {
  if (!text) return "(no description in source)";
  let s = text.split(/(?<=[.!?])\s/)[0].trim();
  if (s.length > 150) s = s.slice(0, 147).replace(/\s+\S*$/, "") + "...";
  return s.replace(/\|/g, "\\|");
}

/** Work out how a tool can be reached: called directly, and found how. */
function accessFor(name) {
  const category = toolCategories.find((c) => c.tools.includes(name));
  const isDirect = directToolNames.includes(name);
  if (category && isDirect) return `Essential + \`${category.name}\``;
  if (category) return `\`${category.name}\``;
  if (isDirect) return "Essential";
  return "Not indexed";
}

function table(tools, kept) {
  const rows = tools.map((t) => [
    "`" + t.name + "`",
    kept.get(t.name) || shorten(t.description),
    accessFor(t.name),
  ]);
  const header = ["Tool", "Description", "Discovery"];
  const lines = [
    "| " + header.join(" | ") + " |",
    "| " + header.map(() => "---").join(" | ") + " |",
    ...rows.map((r) => "| " + r.join(" | ") + " |"),
  ];
  return lines.join("\n");
}

function render() {
  const byFile = collectTools();
  const kept = existingDescriptions();
  const stats = getRegistryStats();

  const ordered = [];
  for (const [file, title] of SECTIONS) {
    if (byFile.has(file)) ordered.push([file, title, byFile.get(file)]);
  }
  for (const [file, tools] of byFile) {
    if (!SECTIONS.some(([f]) => f === file)) ordered.push([file, file, tools]);
  }

  const total = [...byFile.values()].reduce((n, t) => n + t.length, 0);
  const notIndexed = [...byFile.values()]
    .flat()
    .filter((t) => accessFor(t.name) === "Not indexed").length;

  const version = JSON.parse(readFileSync(join(ROOT, "package.json"), "utf-8")).version;
  const today = new Date().toISOString().slice(0, 10);

  const out = [];
  out.push("# KiCAD MCP Server - Complete Tool Inventory");
  out.push("");
  out.push("<!-- Generated by scripts/generate-tool-inventory.mjs. Do not edit by hand:");
  out.push("     run `npm run build && npm run docs:tools` instead. Descriptions already");
  out.push("     in this file are preserved, so improving the wording here is safe. -->");
  out.push("");
  out.push(`**Version:** ${version}`);
  out.push(`**Tools registered on the server:** ${total}`);
  out.push(
    `**Tools indexed for keyword discovery:** ${stats.total_tools} in ${stats.total_categories} categories`,
  );
  out.push(`**Last updated:** ${today}`);
  out.push("");
  out.push("## How to read this document");
  out.push("");
  out.push("Every tool listed here is registered with `server.tool()`, which means an MCP");
  out.push("client can call it by name at any time. There is no router that hides tools.");
  out.push("");
  out.push("The **Discovery** column says how an assistant can *find* the tool when it does");
  out.push("not already know the name:");
  out.push("");
  out.push("- **`category`** - the tool is indexed in that category, so `search_tools` and");
  out.push("  `get_category_tools` can return it.");
  out.push("- **Essential** - the tool is in the always-visible essentials list in");
  out.push("  `src/tools/registry.ts`.");
  out.push("- **Essential + `category`** - both of the above. A small number of very common");
  out.push("  schematic tools are deliberately in both lists.");
  out.push(`- **Not indexed** - the tool works, but \`search_tools\` cannot find it yet.`);
  out.push(
    `  There are ${notIndexed} of these. A test in \`tests-ts/registry-completeness.test.ts\``,
  );
  out.push("  freezes this number so it can only shrink; adding a category entry for one of");
  out.push("  them is a welcome contribution.");
  out.push("");
  out.push("---");
  out.push("");

  for (const [, title, tools] of ordered) {
    const file = ordered.find((o) => o[1] === title)[0];
    out.push(`## ${title} (${tools.length} tools)`);
    out.push("");
    out.push(`_Source: \`src/tools/${file}\`_`);
    out.push("");
    out.push(table(tools, kept));
    out.push("");
    out.push("---");
    out.push("");
  }

  out.push("## Summary by source file");
  out.push("");
  out.push("| Source file | Section | Tools |");
  out.push("| --- | --- | --- |");
  for (const [file, title, tools] of ordered) {
    out.push(`| \`${file}\` | ${title} | ${tools.length} |`);
  }
  out.push(`| **Total** | | **${total}** |`);
  out.push("");
  out.push("## Summary by discovery category");
  out.push("");
  out.push(
    "These are the categories `search_tools` searches. They cover " +
      `${stats.total_tools} of the ${total} registered tools.`,
  );
  out.push("");
  out.push("| Category | Tools indexed |");
  out.push("| --- | --- |");
  for (const c of stats.categories) {
    out.push(`| \`${c.name}\` | ${c.tool_count} |`);
  }
  out.push(`| **Indexed total** | **${stats.total_tools}** |`);
  out.push(`| Registered but not indexed | ${notIndexed} |`);
  out.push(`| **Registered total** | **${total}** |`);
  out.push("");
  return out.join("\n") + "\n";
}

const rendered = await prettier.format(render(), { parser: "markdown" });
if (process.argv.includes("--check")) {
  const current = readFileSync(DOC_PATH, "utf-8");
  // The date line changes every day; ignore it when comparing.
  const strip = (s) => s.replace(/^\*\*Last updated:\*\*.*$/m, "");
  if (strip(current) !== strip(rendered)) {
    console.error("docs/TOOL_INVENTORY.md is out of date. Run: npm run docs:tools");
    process.exit(1);
  }
  console.log("docs/TOOL_INVENTORY.md is up to date.");
} else {
  writeFileSync(DOC_PATH, rendered, "utf-8");
  console.log(`Wrote docs/TOOL_INVENTORY.md`);
}
