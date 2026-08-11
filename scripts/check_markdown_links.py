"""Fail when an active Markdown document links to a missing local target."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\((?P<target>[^)]+)\)")
URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def active_markdown_files() -> list[Path]:
    """Return maintained documents; archived snapshots are intentionally excluded."""
    files = [ROOT / "README.md", ROOT / "CONTRIBUTING.md"]
    files.extend(
        path
        for path in (ROOT / "docs").rglob("*.md")
        if "archive" not in {part.lower() for part in path.parts}
    )
    files.extend((ROOT / ".github").glob("README*.md"))
    return sorted(set(files))


def link_path(raw_target: str) -> str | None:
    """Extract a local filesystem path from a Markdown link destination."""
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    else:
        # Drop an optional Markdown title: path "title" or path 'title'.
        target = re.sub(r"\s+(?:\"[^\"]*\"|'[^']*')\s*$", "", target)

    if not target or target.startswith("#") or URI_SCHEME.match(target):
        return None

    path = unquote(urlsplit(target).path)
    if not path or any(marker in path for marker in ("{", "}", "*")):
        return None
    return path


def main() -> int:
    """Check every local Markdown link and print all failures together."""
    failures: list[str] = []
    documents = active_markdown_files()

    for document in documents:
        text = document.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            path = link_path(match.group("target"))
            if path is None:
                continue

            target = ROOT / path.lstrip("/") if path.startswith("/") else document.parent / path
            if not target.exists():
                line = text.count("\n", 0, match.start()) + 1
                failures.append(
                    f"{document.relative_to(ROOT)}:{line}: missing local target {path!r}"
                )

    if failures:
        print("\n".join(failures))
        return 1

    print(f"Checked local links in {len(documents)} active Markdown files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
