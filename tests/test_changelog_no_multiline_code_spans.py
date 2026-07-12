"""Regression guard: CHANGELOG.md must not contain an inline code span that
straddles a line break.

An inline code span like `` `(version 1) (generator\n"eeschema")` `` (opening
backtick on one line, closing backtick on the next) trips prettier's markdown
list-continuation indentation logic: every time CHANGELOG.md is reformatted —
which happens on essentially every PR that touches it, since the pre-commit
hook runs prettier on the whole file — the line starting mid-span loses its
leading indentation. This was found live on three separate entries (confirmed
reproducible: copy a known-good CHANGELOG.md, add any unrelated new entry
above the affected paragraph, run prettier, and the affected line's
indentation drops), two of which a maintainer had to manually fix during
review before this was traced to a root cause.

The fix is never to let an inline code span cross a line break — keep the
whole span on one physical line, wrapping (if needed) at a point outside it.
"""

from pathlib import Path
from typing import Optional

import pytest

CHANGELOG = Path(__file__).parent.parent / "CHANGELOG.md"


@pytest.mark.unit
def test_changelog_has_no_multiline_inline_code_spans():
    lines = CHANGELOG.read_text(encoding="utf-8").splitlines()

    open_span_from: Optional[int] = None
    offenders = []
    in_fence = False
    for lineno, line in enumerate(lines, start=1):
        if line.strip().startswith("```"):
            # Fenced code blocks are exempt; only inline `code` spans are
            # unsafe. Track the fence STATE, not just the fence lines — a
            # lone backtick in fenced content must not count as an open span.
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if open_span_from is not None:
            offenders.append((open_span_from, lineno))
            open_span_from = None
        if line.count("`") % 2 == 1:
            open_span_from = lineno

    assert offenders == [], (
        "CHANGELOG.md has an inline code span that crosses a line break "
        "(opens on one line, closes on the next), which prettier's markdown "
        "formatter mis-indents on the very next reformat: "
        + ", ".join(f"lines {a}-{b}" for a, b in offenders)
        + ". Rewrite so the whole `code span` stays on one physical line "
        "(wrap at a point outside the backticks if the line is long)."
    )
