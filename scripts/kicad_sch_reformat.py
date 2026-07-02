#!/usr/bin/env python3
"""Re-expand a minified .kicad_sch into KiCad's canonical (eeschema) format.

Interim/migration helper for schematic files that were minified onto a single
line by older versions of this server's write tools.  Produces byte-for-byte the
same layout eeschema's "Save" writes, without launching KiCad.  Reuses the same
formatter the server itself now uses (python/utils/sexpr_format.py), so results
match tool writes exactly.  Only external dependency: ``sexpdata``.

Usage
-----
  # Reformat files in place:
  python scripts/kicad_sch_reformat.py path/to/*.kicad_sch

  # Check-only (exit 1 if any file would change) — CI / pre-commit:
  python scripts/kicad_sch_reformat.py --check path/to/*.kicad_sch

  # As a git clean filter (stdin -> stdout). In .gitattributes:
  #   *.kicad_sch filter=kicadpretty
  # and:
  #   git config filter.kicadpretty.clean \
  #     "python /abs/path/scripts/kicad_sch_reformat.py --stdin"
  python scripts/kicad_sch_reformat.py --stdin < in.kicad_sch > out.kicad_sch
"""
import sys
from pathlib import Path

# Reuse the server's canonical formatter rather than re-implementing it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import sexpdata  # noqa: E402
from utils.sexpr_format import prettify  # noqa: E402


def reformat_text(text: str) -> str:
    # Round-trip through sexpdata to normalize any input spacing, then prettify.
    # sexpdata's round-trip is data-lossless, so no schematic data changes.
    return prettify(sexpdata.dumps(sexpdata.loads(text)))


def main(argv):
    args = list(argv)
    check = "--check" in args
    if check:
        args.remove("--check")
    if "--stdin" in args:
        sys.stdout.write(reformat_text(sys.stdin.read()))
        return 0
    if not args:
        print(__doc__)
        return 2
    changed = 0
    for path in args:
        orig = Path(path).read_text(encoding="utf-8")
        new = reformat_text(orig)
        if new != orig:
            changed += 1
            if check:
                print(f"would reformat: {path}")
            else:
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(new)
                print(f"reformatted: {path}")
    if check:
        return 1 if changed else 0
    print(f"done ({changed} file(s) changed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
