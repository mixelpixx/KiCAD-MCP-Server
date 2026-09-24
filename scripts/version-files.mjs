/**
 * version-files.mjs — every place the release version is written.
 *
 * Shared by scripts/release.mjs, which rewrites these when a release is cut,
 * and tests-ts/version-consistency.test.ts, which fails CI when they disagree.
 * The bump used to be done by hand in eight places, and the README citation
 * said 2.3.0 for five releases before anyone noticed.
 *
 * Each entry names a file and a regular expression whose first group is the
 * version. A pattern must match exactly once: a second match would mean the
 * anchor is ambiguous and a rewrite could touch the wrong line. Patterns are
 * matched against LF-normalised text.
 */

export const VERSION_FILES = [
  {
    file: "package.json",
    what: "package version",
    pattern: /^ {2}"version": "([^"]+)",$/m,
  },
  {
    // The only two-space-indented "version" key is the lockfile's own.
    file: "package-lock.json",
    what: "lockfile version",
    pattern: /^ {2}"version": "([^"]+)",$/m,
  },
  {
    file: "package-lock.json",
    what: 'lockfile packages[""] version',
    pattern: /^ {4}"": \{\n {6}"name": "kicad-mcp",\n {6}"version": "([^"]+)",$/m,
  },
  {
    file: "src/server.ts",
    what: "MCP server version",
    pattern: /name: "kicad-mcp-server",\s*\n\s*version: "([^"]+)",/,
  },
  {
    file: "python/kicad_interface.py",
    what: "Python JSON-RPC serverInfo version",
    pattern: /"serverInfo": \{[^}]*?"version": "([^"]+)"/,
  },
  {
    file: "README.md",
    what: "README current version",
    pattern: /^\*\*Current Version:\*\* (\S+)$/m,
  },
  {
    file: "README.md",
    what: "README citation version",
    pattern: /^ {2}version = \{([^}]+)\}$/m,
  },
  {
    file: "docs/ROADMAP.md",
    what: "roadmap current version",
    pattern: /^\*\*Current Version:\*\* (\S+)$/m,
  },
  {
    // Written by scripts/generate-tool-inventory.mjs from package.json.
    file: "docs/TOOL_INVENTORY.md",
    what: "tool inventory version",
    pattern: /^\*\*Version:\*\* (\S+)$/m,
  },
];

/** The file's text with CRLF turned into LF, and whether it had CRLF. */
export function normalise(raw) {
  return { text: raw.replace(/\r\n/g, "\n"), crlf: raw.includes("\r\n") };
}

/** Put back the line endings `normalise` took out. */
export function restore(text, crlf) {
  return crlf ? text.replace(/\n/g, "\r\n") : text;
}

/**
 * Every match of an entry's pattern in `text`. The `d` flag records where
 * group 1 sits, so a rewrite replaces exactly the version and nothing else.
 */
function matches(text, entry) {
  const flags = new Set([...entry.pattern.flags, "g", "d"]);
  return [...text.matchAll(new RegExp(entry.pattern.source, [...flags].join("")))];
}

/**
 * The version an entry holds in `text`. Throws if the pattern does not match
 * exactly once, naming the file and the place.
 */
export function readVersion(text, entry) {
  const found = matches(text, entry);
  if (found.length !== 1) {
    throw new Error(
      `${entry.file}: expected one ${entry.what}, found ${found.length} (pattern ${entry.pattern})`,
    );
  }
  return found[0][1];
}

/** `text` with the entry's version replaced by `version`. */
export function writeVersion(text, entry, version) {
  readVersion(text, entry); // throws unless the pattern matches exactly once
  const [start, end] = matches(text, entry)[0].indices[1];
  return text.slice(0, start) + version + text.slice(end);
}

const SEMVER = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/;

/** Whether `version` is MAJOR.MINOR.PATCH with an optional -prerelease. */
export function isVersion(version) {
  return SEMVER.test(version);
}

/**
 * Semantic-version order: negative when a < b, 0 when equal, positive when
 * a > b. A prerelease sorts before its release (2.9.0-rc.1 < 2.9.0), and
 * prerelease identifiers compare numerically where both are numbers.
 */
export function compareVersions(a, b) {
  const pa = SEMVER.exec(a);
  const pb = SEMVER.exec(b);
  if (!pa || !pb) throw new Error(`not a version: ${!pa ? a : b}`);
  for (let i = 1; i <= 3; i++) {
    const d = Number(pa[i]) - Number(pb[i]);
    if (d !== 0) return d;
  }
  if (!pa[4] || !pb[4]) return (pa[4] ? -1 : 0) - (pb[4] ? -1 : 0);
  const xa = pa[4].split(".");
  const xb = pb[4].split(".");
  for (let i = 0; i < Math.max(xa.length, xb.length); i++) {
    if (xa[i] === undefined) return -1;
    if (xb[i] === undefined) return 1;
    const na = /^\d+$/.test(xa[i]);
    const nb = /^\d+$/.test(xb[i]);
    if (na && nb && Number(xa[i]) !== Number(xb[i])) return Number(xa[i]) - Number(xb[i]);
    if (na !== nb) return na ? -1 : 1;
    if (xa[i] !== xb[i]) return xa[i] < xb[i] ? -1 : 1;
  }
  return 0;
}
