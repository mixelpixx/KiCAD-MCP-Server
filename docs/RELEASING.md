# Releasing

How changes reach `main`, and how `main` becomes a release that users install.

## Branches and tags

- **`main`** is where all work lands, always through a pull request. It is
  protected: a pull request is required, the `CI passed` check must succeed,
  and the pull request must be up to date with `main` before it can merge. The
  rules apply to administrators too, and force pushes and deletion are blocked.
- **`stable`** is the latest release, and the branch the README tells users to
  install. Only the Release workflow moves it, when a version tag is pushed.
  Force pushes and deletion are blocked.
- **`vX.Y.Z` tags** mark releases: annotated tags on commits of `main`.

`main` is not a release channel. It can hold fixes that are merged but not yet
released, and users who clone `stable` do not see them until the next release.

## Merging a pull request

1. Wait for `CI passed` on the pull request. That job succeeds only when every
   other CI job did (TypeScript, Python on every version, the KiCad 8/9/10
   integration tests, Docker, code quality and the docs check).
2. If `main` moved since CI ran, update the branch ("Update branch" on GitHub,
   or `gh pr update-branch <number>`). CI then runs again on the combined
   code. A conflict is resolved on the pull request branch, so the resolution
   is tested before it lands.
3. Merge with the GitHub button or `gh pr merge <number> --merge`. The head
   branch is deleted automatically.

## Cutting a release

1. Check that `main` has everything the release should contain and that its
   CI passed. The CHANGELOG's `## [Unreleased]` section lists what will ship.

2. On a release branch, run the release script:

   ```bash
   git switch -c release/v2.8.2 main
   npm run release -- 2.8.2
   ```

   It refuses to run when the version strings already disagree, when the new
   version is not newer, or when Unreleased is empty. It writes the version into
   every place that holds it (the list is in `scripts/version-files.mjs`), sets
   the README citation year, and moves the Unreleased entries under
   `## [2.8.2] - <today>`. `--dry-run` only lists the files it would change, and
   `--date YYYY-MM-DD` sets the CHANGELOG date.

3. Write `## What's New in v2.8.2` in `README.md`, above the previous release's
   section, and credit contributors there. The GitHub release notes are built
   from this section. Without it they use the CHANGELOG section. Preview them
   with:

   ```bash
   npm run release:notes -- 2.8.2 v2.8.1
   ```

4. Commit as `chore: release v2.8.2`, push the branch, open a pull request and
   merge it once CI passes.

5. Tag the merge commit and push the tag:

   ```bash
   git switch main
   git pull
   git tag -a v2.8.2 -m "v2.8.2 — one-line summary"
   git push origin v2.8.2
   ```

6. The Release workflow (`.github/workflows/release.yml`) does the rest:
   - checks that the tag matches the `package.json` version and is on `main`;
   - publishes the GitHub release from `scripts/release-notes.mjs`;
   - moves `stable` to the tag.

   Follow it on the repository's Actions tab.

A tag with a suffix, such as `v2.9.0-rc.1`, is published as a GitHub
prerelease and does not move `stable`. The release script and the notes are
built for full releases, so a release candidate needs its version strings and
notes prepared by hand.

## When something goes wrong

- **The workflow failed before publishing.** Fix the cause, delete the tag
  (`git push --delete origin v2.8.2`, then `git tag -d v2.8.2`), and tag
  again.
- **The release was published but `stable` did not move.** Re-run the
  workflow from the Actions tab. It leaves an existing release as it is and
  only pushes `stable` forward. A push that would move `stable` backwards is
  refused, so an old tag cannot rewind it.
- **An urgent fix cannot wait for CI.** The rules apply to administrators, so
  there is no quiet bypass. An administrator can switch off "Do not allow
  bypassing the above settings" for `main` under Settings → Branches, push,
  and switch it back on.

## Checks that keep this honest

- `tests-ts/release-tooling.test.ts` fails CI when any version string
  disagrees with `package.json`, and when the newest released CHANGELOG
  section is not the package version. It also pins what the release script and
  the release-notes builder produce.
- `npm run docs:tools:check` fails CI when `docs/TOOL_INVENTORY.md` is out of
  date.
