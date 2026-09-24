import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";
import {
  VERSION_FILES,
  compareVersions,
  normalise,
  readVersion,
} from "../scripts/version-files.mjs";
import { RELEASE_FILES, planRelease, releaseReminders } from "../scripts/release.mjs";
import { buildReleaseNotes, headingAnchor } from "../scripts/release-notes.mjs";

// The release version is written in nine places. They were bumped by hand,
// and the README citation said 2.3.0 for five releases. scripts/release.mjs
// now rewrites them together; these tests keep them agreeing between releases
// and pin what the release script and the release notes produce.

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (path: string): string => normalise(readFileSync(join(ROOT, path), "utf-8")).text;
const packageVersion = readVersion(read("package.json"), VERSION_FILES[0]);

describe("version strings", () => {
  it.each(VERSION_FILES.map((entry: any) => [entry.file, entry.what, entry]))(
    "%s (%s) matches package.json",
    (_file, _what, entry) => {
      expect(readVersion(read(entry.file), entry)).toBe(packageVersion);
    },
  );

  it("the newest released CHANGELOG section is the package version", () => {
    const newest = read("CHANGELOG.md").match(/^## \[([^\]]+)\] - \d{4}-\d{2}-\d{2}$/m);
    expect(newest?.[1]).toBe(packageVersion);
  });

  it("the package version has release notes", () => {
    const notes = buildReleaseNotes({
      readme: read("README.md"),
      changelog: read("CHANGELOG.md"),
      version: packageVersion,
    });
    expect(notes.trim().length).toBeGreaterThan(0);
  });
});

/** A miniature repository holding every file a release touches. */
function fixture(version = "1.2.3", unreleased = "### Bug Fixes\n\n- A fix.\n\n") {
  return {
    "package.json": `{\n  "name": "kicad-mcp",\n  "version": "${version}",\n  "type": "module"\n}\n`,
    "package-lock.json":
      `{\n  "name": "kicad-mcp",\n  "version": "${version}",\n  "lockfileVersion": 3,\n` +
      `  "packages": {\n    "": {\n      "name": "kicad-mcp",\n      "version": "${version}",\n` +
      `      "license": "MIT"\n    },\n    "node_modules/same-version-dep": {\n` +
      `      "version": "${version}",\n      "license": "MIT"\n    }\n  }\n}\n`,
    "src/server.ts": `this.server = new McpServer({\n  name: "kicad-mcp-server",\n  version: "${version}",\n});\n`,
    "python/kicad_interface.py": `"serverInfo": {\n    "name": "kicad-mcp-server",\n    "version": "${version}",\n},\n`,
    "README.md": `**Current Version:** ${version}\n\n@software{x,\n  year = {2025},\n  version = {${version}}\n}\n`,
    "docs/ROADMAP.md": `**Current Version:** ${version}\n`,
    "docs/TOOL_INVENTORY.md": `**Version:** ${version}\n`,
    "CHANGELOG.md": `# Changelog\n\n## [Unreleased]\n\n${unreleased}## [${version}] - 2026-01-01\n\n- Old.\n`,
  } as Record<string, string>;
}

describe("planRelease", () => {
  it("writes the version everywhere, the citation year, and cuts the CHANGELOG", () => {
    const files = fixture();
    const next = { ...files, ...planRelease(files, "1.2.4", "2027-02-03") };

    for (const entry of VERSION_FILES) {
      expect(readVersion(next[entry.file], entry), `${entry.file}: ${entry.what}`).toBe("1.2.4");
    }
    // A dependency that happens to share the version is not the project's.
    expect(next["package-lock.json"]).toContain(
      '"node_modules/same-version-dep": {\n      "version": "1.2.3"',
    );
    expect(next["README.md"]).toContain("  year = {2027},");
    expect(next["CHANGELOG.md"]).toBe(
      "# Changelog\n\n## [Unreleased]\n\n## [1.2.4] - 2027-02-03\n\n### Bug Fixes\n\n- A fix.\n\n" +
        "## [1.2.3] - 2026-01-01\n\n- Old.\n",
    );
  });

  it("refuses an empty Unreleased section", () => {
    expect(() => planRelease(fixture("1.2.3", ""), "1.2.4", "2027-02-03")).toThrow(
      /nothing to release/,
    );
  });

  it("refuses a version that is not newer", () => {
    expect(() => planRelease(fixture(), "1.2.3", "2027-02-03")).toThrow(/not newer/);
    expect(() => planRelease(fixture(), "1.2.2", "2027-02-03")).toThrow(/not newer/);
    expect(() => planRelease(fixture(), "1.3.0-rc.1", "2027-02-03")).not.toThrow();
  });

  it("refuses to start from version strings that already disagree", () => {
    const files = fixture();
    files["docs/ROADMAP.md"] = "**Current Version:** 1.2.0\n";
    expect(() => planRelease(files, "1.2.4", "2027-02-03")).toThrow(/docs\/ROADMAP\.md/);
  });

  it("refuses an ambiguous anchor rather than guess", () => {
    const files = fixture();
    files["docs/ROADMAP.md"] += "**Current Version:** 1.2.3\n";
    expect(() => planRelease(files, "1.2.4", "2027-02-03")).toThrow(/expected one/);
  });

  it("changes only the version lines of the real repository", () => {
    const files = Object.fromEntries(RELEASE_FILES.map((path: string) => [path, read(path)]));
    files["CHANGELOG.md"] = files["CHANGELOG.md"].replace(
      "## [Unreleased]\n",
      "## [Unreleased]\n\n### Bug Fixes\n\n- A pretend fix.\n",
    );
    const year = files["README.md"].match(/^ {2}year = \{(\d{4})\},$/m)![1];
    const [major, minor, patch] = packageVersion.split(/[.-]/).map(Number);
    const version = `${major}.${minor}.${patch + 1}`;

    const changed = planRelease(files, version, `${year}-12-31`);

    let changedLines = 0;
    for (const [path, text] of Object.entries(changed) as [string, string][]) {
      if (path === "CHANGELOG.md") continue;
      const before = files[path].split("\n");
      const after = text.split("\n");
      expect(after.length, path).toBe(before.length);
      changedLines += after.filter((line, i) => line !== before[i]).length;
    }
    expect(changedLines).toBe(VERSION_FILES.length);
    expect(changed["CHANGELOG.md"]).toBe(
      files["CHANGELOG.md"].replace(
        "## [Unreleased]\n",
        `## [Unreleased]\n\n## [${version}] - ${year}-12-31\n`,
      ),
    );
  });

  it("reminds about a missing README section", () => {
    expect(releaseReminders(fixture(), "1.2.4")).toHaveLength(1);
    const files = fixture();
    files["README.md"] += "\n## What's New in v1.2.4\n\nText.\n";
    expect(releaseReminders(files, "1.2.4")).toEqual([]);
  });
});

describe("compareVersions", () => {
  it("orders releases and prereleases the way semver does", () => {
    const ordered = [
      "2.8.1",
      "2.9.0-alpha",
      "2.9.0-rc.1",
      "2.9.0-rc.2",
      "2.9.0-rc.10",
      "2.9.0",
      "2.10.0",
    ];
    const shuffled = [...ordered].reverse();
    expect(shuffled.sort(compareVersions)).toEqual(ordered);
  });
});

describe("release notes", () => {
  const changelog =
    "# Changelog\n\n## [Unreleased]\n\n## [1.2.4] - 2027-02-03\n\n### Bug Fixes\n\n- A fix.\n\n" +
    "## [1.2.3] - 2026-01-01\n\n- Old.\n";

  it("are the README section with its headings raised and links added", () => {
    const readme =
      "# Title\n\n## What's New in v1.2.4\n\nIntro.\n\n### A heading\n\n- Point.\n\n" +
      "Full details in the [CHANGELOG](CHANGELOG.md).\n\n## What's New in v1.2.3\n\nOld.\n";
    const notes = buildReleaseNotes({
      readme,
      changelog,
      version: "1.2.4",
      previousTag: "v1.2.3",
      repo: "owner/repo",
    });
    expect(notes).toBe(
      "Intro.\n\n## A heading\n\n- Point.\n\n" +
        "Full details: [CHANGELOG.md](https://github.com/owner/repo/blob/v1.2.4/CHANGELOG.md#124---2027-02-03)" +
        " · Diff: [v1.2.3...v1.2.4](https://github.com/owner/repo/compare/v1.2.3...v1.2.4)\n",
    );
  });

  it("fall back to the CHANGELOG section", () => {
    const notes = buildReleaseNotes({ readme: "# Title\n", changelog, version: "1.2.4" });
    expect(notes).toContain("## Bug Fixes\n\n- A fix.");
    expect(notes).not.toContain("Old.");
  });

  it("refuse a version with neither", () => {
    expect(() => buildReleaseNotes({ readme: "", changelog, version: "9.9.9" })).toThrow();
  });

  it("link to GitHub's anchor for the CHANGELOG heading", () => {
    expect(headingAnchor("[2.8.1] - 2026-09-23")).toBe("281---2026-09-23");
  });
});
