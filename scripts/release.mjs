#!/usr/bin/env node
/**
 * release.mjs — prepare the files for a release: `npm run release -- 2.8.2`.
 *
 * All or nothing, it:
 *   - checks that every version string agrees with package.json (the list is in
 *     version-files.mjs) and that the new version is newer;
 *   - writes the new version into each of them;
 *   - sets the README citation year to the release year;
 *   - moves the CHANGELOG's Unreleased entries under "## [2.8.2] - <date>",
 *     refusing when Unreleased is empty or the version already has a section.
 *
 * It does not write "What's New in v2.8.2" in the README. That text is written
 * by hand, and the GitHub release notes are built from it when it exists
 * (release-notes.mjs), so the script reminds you when it is missing.
 *
 * Usage:
 *   npm run release -- 2.8.2                    # edit the files
 *   npm run release -- 2.8.2 --dry-run          # only list what would change
 *   npm run release -- 2.8.2 --date 2026-10-01  # date for the CHANGELOG heading
 *
 * docs/RELEASING.md has the whole process: release branch, pull request, tag.
 */

import { readFileSync, writeFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath, pathToFileURL } from "url";
import {
  VERSION_FILES,
  compareVersions,
  isVersion,
  normalise,
  readVersion,
  restore,
  writeVersion,
} from "./version-files.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const UNRELEASED = "## [Unreleased]\n";

/** Every file a release reads or writes, as repository paths. */
export const RELEASE_FILES = [...new Set([...VERSION_FILES.map((e) => e.file), "CHANGELOG.md"])];

/**
 * The edits a release makes, without touching the disk.
 *
 * `files` maps each path in RELEASE_FILES to its LF-normalised text. Returns
 * the new text of every file that changes, keyed the same way. Throws with a
 * readable message when the release cannot be prepared.
 */
export function planRelease(files, version, date) {
  if (!isVersion(version)) {
    throw new Error(`"${version}" is not a version like 2.8.2 or 2.9.0-rc.1`);
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    throw new Error(`"${date}" is not a date like 2026-10-01`);
  }

  const current = readVersion(files["package.json"], VERSION_FILES[0]);
  const drift = VERSION_FILES.map((entry) => [entry, readVersion(files[entry.file], entry)]).filter(
    ([, found]) => found !== current,
  );
  if (drift.length) {
    const lines = drift.map(([entry, found]) => `  ${entry.file} (${entry.what}): ${found}`);
    throw new Error(
      `version strings disagree with package.json (${current}):\n${lines.join("\n")}`,
    );
  }
  if (compareVersions(version, current) <= 0) {
    throw new Error(`${version} is not newer than the current version ${current}`);
  }

  const next = { ...files };
  for (const entry of VERSION_FILES) {
    next[entry.file] = writeVersion(next[entry.file], entry, version);
  }
  next["README.md"] = next["README.md"].replace(
    /^( {2}year = \{)\d{4}(\},)$/m,
    `$1${date.slice(0, 4)}$2`,
  );

  const changelog = next["CHANGELOG.md"];
  const start = changelog.indexOf(UNRELEASED);
  if (start === -1) {
    throw new Error("CHANGELOG.md has no '## [Unreleased]' heading");
  }
  const bodyStart = start + UNRELEASED.length;
  const bodyEnd = changelog.indexOf("\n## [", bodyStart);
  if (!changelog.slice(bodyStart, bodyEnd === -1 ? undefined : bodyEnd).trim()) {
    throw new Error("nothing to release: the Unreleased section of CHANGELOG.md is empty");
  }
  if (changelog.includes(`\n## [${version}]`)) {
    throw new Error(`CHANGELOG.md already has a section for ${version}`);
  }
  next["CHANGELOG.md"] =
    changelog.slice(0, bodyStart) + `\n## [${version}] - ${date}\n` + changelog.slice(bodyStart);

  return Object.fromEntries(Object.entries(next).filter(([path, text]) => text !== files[path]));
}

/** Things a release usually wants that the script cannot write itself. */
export function releaseReminders(files, version) {
  const reminders = [];
  if (!files["README.md"].includes(`\n## What's New in v${version}\n`)) {
    reminders.push(
      `README.md has no "## What's New in v${version}" section. Write one above the previous ` +
        "release's (credit contributors there): the GitHub release notes are built from it, " +
        "and without it they fall back to the CHANGELOG section.",
    );
  }
  return reminders;
}

function today() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function main(argv) {
  const args = argv.slice(2);
  const dryRun = args.includes("--dry-run");
  const dateAt = args.indexOf("--date");
  const date = dateAt === -1 ? today() : args[dateAt + 1];
  const version = args.find((arg, i) => !arg.startsWith("--") && args[i - 1] !== "--date");
  if (!version) {
    console.error("usage: npm run release -- <version> [--dry-run] [--date YYYY-MM-DD]");
    process.exit(2);
  }

  const files = {};
  const crlf = {};
  for (const path of RELEASE_FILES) {
    const { text, crlf: hadCrlf } = normalise(readFileSync(join(ROOT, path), "utf-8"));
    files[path] = text;
    crlf[path] = hadCrlf;
  }

  let changed;
  try {
    changed = planRelease(files, version, date);
  } catch (err) {
    console.error(`release: ${err.message}`);
    process.exit(1);
  }

  const current = readVersion(files["package.json"], VERSION_FILES[0]);
  console.log(`${current} -> ${version} (${date})`);
  for (const [path, text] of Object.entries(changed)) {
    if (!dryRun) writeFileSync(join(ROOT, path), restore(text, crlf[path]));
    console.log(`  ${dryRun ? "would edit" : "edited"} ${path}`);
  }
  for (const reminder of releaseReminders(files, version)) console.log(`\nNote: ${reminder}`);
  if (!dryRun) {
    console.log(
      [
        "",
        "Next (docs/RELEASING.md):",
        `  1. git switch -c release/v${version}, commit "chore: release v${version}", push, open a PR.`,
        "  2. Merge it on GitHub once CI passes.",
        `  3. Tag the merge commit on main and push the tag:`,
        `       git tag -a v${version} -m "v${version}" <merge-commit> && git push origin v${version}`,
        "     The Release workflow then publishes the GitHub release and moves the stable branch.",
      ].join("\n"),
    );
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv);
}
