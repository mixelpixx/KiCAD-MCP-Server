#!/usr/bin/env node
/**
 * release-notes.mjs — the GitHub release notes for a version, on stdout.
 *
 * They are the README's "## What's New in v<version>" section, the same text a
 * README reader sees, with its "###" headings raised to "##" and its pointer to
 * the CHANGELOG replaced by absolute links. A release without a README section
 * gets its CHANGELOG section instead. .github/workflows/release.yml runs this
 * when a version tag is pushed; to preview the notes locally:
 *
 *   node scripts/release-notes.mjs 2.8.2 v2.8.1
 *
 * The second argument is the previous release's tag, for the compare link.
 */

import { readFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath, pathToFileURL } from "url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_REPO = "mixelpixx/KiCAD-MCP-Server";

/** The text between `heading` and the next occurrence of `end`, or null. */
function section(text, heading, end) {
  const start = text.indexOf(`${heading}\n`);
  if (start === -1) return null;
  const from = start + heading.length + 1;
  const to = text.indexOf(end, from);
  return text.slice(from, to === -1 ? undefined : to);
}

/** The CHANGELOG's "## [x.y.z] - date" heading line for `version`, or null. */
function changelogHeading(changelog, version) {
  const escaped = version.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const m = changelog.match(new RegExp(`^## \\[${escaped}\\] - \\d{4}-\\d{2}-\\d{2}$`, "m"));
  return m ? m[0] : null;
}

/** GitHub's anchor for a Markdown heading, e.g. "[2.8.1] - 2026-09-23" -> "281---2026-09-23". */
export function headingAnchor(heading) {
  return heading
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s_-]/gu, "")
    .replace(/\s/g, "-");
}

/**
 * The release notes for `version` as Markdown. `readme` and `changelog` are
 * the files' texts; `previousTag` (such as "v2.8.1") adds a compare link.
 */
export function buildReleaseNotes({
  readme,
  changelog,
  version,
  previousTag,
  repo = DEFAULT_REPO,
}) {
  const tag = `v${version}`;
  const heading = changelogHeading(changelog, version);
  let body = section(readme.replace(/\r\n/g, "\n"), `## What's New in ${tag}`, "\n## ");
  if (body === null && heading) {
    body = section(changelog.replace(/\r\n/g, "\n"), heading, "\n## [");
  }
  if (body === null) {
    throw new Error(
      `no "## What's New in ${tag}" in README.md and no "## [${version}]" section in CHANGELOG.md`,
    );
  }
  body = body
    .replace(/^### /gm, "## ")
    .replace(/^Full details in the \[CHANGELOG\]\(CHANGELOG\.md\)\.[ \t]*$/m, "")
    .trim();

  const links = [];
  if (heading) {
    const anchor = headingAnchor(heading.slice(3));
    links.push(
      `Full details: [CHANGELOG.md](https://github.com/${repo}/blob/${tag}/CHANGELOG.md#${anchor})`,
    );
  }
  if (previousTag) {
    links.push(
      `Diff: [${previousTag}...${tag}](https://github.com/${repo}/compare/${previousTag}...${tag})`,
    );
  }
  return `${body}${links.length ? `\n\n${links.join(" · ")}` : ""}\n`;
}

function main(argv) {
  const [version, previousTag] = argv.slice(2);
  if (!version) {
    console.error("usage: node scripts/release-notes.mjs <version> [previous-tag]");
    process.exit(2);
  }
  try {
    process.stdout.write(
      buildReleaseNotes({
        readme: readFileSync(join(ROOT, "README.md"), "utf-8"),
        changelog: readFileSync(join(ROOT, "CHANGELOG.md"), "utf-8"),
        version,
        previousTag: previousTag || undefined,
        repo: process.env.GITHUB_REPOSITORY || DEFAULT_REPO,
      }),
    );
  } catch (err) {
    console.error(`release-notes: ${err.message}`);
    process.exit(1);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv);
}
