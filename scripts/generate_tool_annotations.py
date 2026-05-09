#!/usr/bin/env python3
"""
generate_tool_annotations.py — Annotate KiCad IPC API proto messages with Claude

Reads KiCad's protobuf API definitions and uses the Claude API to generate rich,
user-facing descriptions suitable for MCP tool metadata. The output JSON file can
be loaded by an MCP server to annotate auto-generated tools with descriptions that
go beyond what's in the proto files (e.g., unit conventions, commit ownership
semantics, blocking/interactive behavior).

Because the proto content is large and static, it is sent once as a cached prompt
block; only the lightweight annotation-request portion is billed at full rate.
Re-running the script against the same proto revision is therefore very cheap.

Usage
-----
Annotate from a local KiCad source checkout::

    python scripts/generate_tool_annotations.py \\
        --proto-dir /path/to/kicad/api/proto \\
        --output data/tool_annotations.json

Fetch proto files directly from GitLab (no checkout needed)::

    python scripts/generate_tool_annotations.py \\
        --fetch-from-gitlab \\
        --kicad-ref master \\
        --output data/tool_annotations.json

Resume an interrupted run (skips messages already in the output file)::

    python scripts/generate_tool_annotations.py \\
        --proto-dir ./api/proto \\
        --output data/tool_annotations.json \\
        --resume

Preview what would be annotated without calling the API::

    python scripts/generate_tool_annotations.py \\
        --proto-dir ./api/proto \\
        --dry-run

Environment variables
---------------------
ANTHROPIC_API_KEY
    Required. Your Anthropic API key.

Dependencies
------------
    anthropic>=0.40.0
    requests>=2.28.0   (only needed with --fetch-from-gitlab)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GITLAB_RAW_BASE = "https://gitlab.com/kicad/code/kicad/-/raw"

# Relative paths inside the KiCad repo that contain API proto definitions.
# Extend this list when KiCad adds new proto files.
PROTO_RELATIVE_PATHS: list[str] = [
    "api/proto/board/board_commands.proto",
    "api/proto/board/board.proto",
    "api/proto/board/board_types.proto",
    "api/proto/schematic/schematic_commands.proto",
    "api/proto/schematic/schematic_types.proto",
    "api/proto/common/commands/base_commands.proto",
    "api/proto/common/commands/editor_commands.proto",
    "api/proto/common/commands/project_commands.proto",
    "api/proto/common/types/base_types.proto",
    "api/proto/common/types/enums.proto",
]

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_OUTPUT = "tool_annotations.json"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ProtoField:
    name: str
    type_name: str
    number: int
    comment: str = ""
    repeated: bool = False
    optional: bool = False

    def summary(self) -> str:
        qualifier = "repeated " if self.repeated else ("optional " if self.optional else "")
        parts = [f"{qualifier}{self.type_name} {self.name}"]
        if self.comment:
            parts.append(f"  // {self.comment}")
        return "".join(parts)


@dataclass
class ProtoMessage:
    name: str
    comment: str
    fields: list[ProtoField] = field(default_factory=list)
    source_file: str = ""
    is_response: bool = False

    def as_text(self) -> str:
        lines = []
        if self.comment:
            for line in textwrap.wrap(self.comment, width=80):
                lines.append(f"// {line}")
        lines.append(f"message {self.name} {{")
        for f in self.fields:
            lines.append(f"  {f.summary()}")
        lines.append("}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Proto file fetching
# ---------------------------------------------------------------------------


def fetch_proto_from_gitlab(ref: str) -> dict[str, str]:
    """Fetch proto files from KiCad's GitLab. Returns {relative_path: content}."""
    try:
        import requests
    except ImportError:
        sys.exit("requests is required for --fetch-from-gitlab.  Install with: pip install requests")

    files: dict[str, str] = {}
    session = requests.Session()

    for rel_path in PROTO_RELATIVE_PATHS:
        url = f"{GITLAB_RAW_BASE}/{ref}/{rel_path}"
        print(f"  Fetching {rel_path} ...", flush=True)
        resp = session.get(url, timeout=30)
        if resp.status_code == 200:
            files[rel_path] = resp.text
        elif resp.status_code == 404:
            print(f"  WARNING: {rel_path} not found at ref '{ref}' — skipping", file=sys.stderr)
        else:
            sys.exit(f"HTTP {resp.status_code} fetching {url}")

    return files


def load_proto_from_dir(proto_dir: Path) -> dict[str, str]:
    """Load proto files from a local directory. Returns {relative_path: content}."""
    files: dict[str, str] = {}
    for proto_file in sorted(proto_dir.rglob("*.proto")):
        rel = str(proto_file.relative_to(proto_dir))
        files[rel] = proto_file.read_text(encoding="utf-8")
    if not files:
        sys.exit(f"No .proto files found under {proto_dir}")
    return files


# ---------------------------------------------------------------------------
# Proto parser
# ---------------------------------------------------------------------------

# Matches license/copyright headers so we can suppress them from comment text.
_LICENSE_KEYWORDS = frozenset(["copyright", "gnu general public", "program source code", "free software"])

# Matches proto field declarations (handles repeated/optional qualifiers).
_FIELD_RE = re.compile(
    r"^(repeated\s+|optional\s+)?([\w.]+)\s+(\w+)\s*=\s*(\d+)\s*;?\s*(?://(.*))?$"
)


def _is_license_comment(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in _LICENSE_KEYWORDS)


def parse_proto_text(text: str, source_name: str = "") -> list[ProtoMessage]:
    """
    Extract top-level message definitions from proto3 source text.

    Returns a list of ProtoMessage objects in declaration order.
    Comments immediately preceding a message declaration are captured
    as its docstring. Field-level comments (both inline and preceding)
    are attached to each field.
    """
    lines = text.splitlines()
    messages: list[ProtoMessage] = []

    i = 0
    pending_comments: list[str] = []
    in_block = False
    block_buf: list[str] = []

    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        # ── block comment handling ──────────────────────────────────────────
        if "/*" in stripped and "*/" not in stripped:
            in_block = True
            block_buf = [re.sub(r"^\s*/\*+", "", stripped).strip()]
            i += 1
            continue

        if in_block:
            if "*/" in stripped:
                in_block = False
                tail = re.sub(r"\*+/.*$", "", stripped).strip().lstrip("* ").strip()
                if tail:
                    block_buf.append(tail)
                comment_text = " ".join(l for l in block_buf if l)
                if not _is_license_comment(comment_text):
                    pending_comments = block_buf[:]
                else:
                    pending_comments = []
                block_buf = []
            else:
                block_buf.append(stripped.lstrip("* ").strip())
            i += 1
            continue

        # Inline block comment on one line: /* ... */
        if "/*" in stripped and "*/" in stripped:
            m = re.search(r"/\*(.*?)\*/", stripped)
            if m:
                comment_text = m.group(1).strip()
                if not _is_license_comment(comment_text):
                    pending_comments = [comment_text]
                else:
                    pending_comments = []
            i += 1
            continue

        # ── line comment ────────────────────────────────────────────────────
        if stripped.startswith("//"):
            comment_text = stripped.lstrip("/").strip()
            pending_comments.append(comment_text)
            i += 1
            continue

        # ── message declaration ─────────────────────────────────────────────
        msg_match = re.match(r"^message\s+(\w+)\s*\{?\s*$", stripped)
        if msg_match:
            msg_name = msg_match.group(0).split()[1]
            doc = " ".join(l for l in pending_comments if l).strip()
            if _is_license_comment(doc):
                doc = ""
            pending_comments = []

            # Collect fields inside the message body
            proto_fields: list[ProtoField] = []
            brace_depth = 1 if "{" in stripped else 0
            field_comments: list[str] = []
            j = i + 1

            # If the opening brace is on the next line
            if brace_depth == 0 and j < len(lines) and "{" in lines[j]:
                brace_depth = 1
                j += 1

            while j < len(lines) and brace_depth > 0:
                fraw = lines[j]
                fstripped = fraw.strip()

                if fstripped.startswith("//"):
                    field_comments.append(fstripped.lstrip("/").strip())
                    j += 1
                    continue

                opens = fstripped.count("{")
                closes = fstripped.count("}")
                brace_depth += opens - closes

                if brace_depth <= 0:
                    j += 1
                    break

                if brace_depth == 1:
                    fm = _FIELD_RE.match(fstripped)
                    if fm:
                        qualifier = fm.group(1) or ""
                        type_name = (fm.group(2) or "").split(".")[-1]
                        field_name = fm.group(3) or ""
                        field_num = int(fm.group(4) or 0)
                        inline = (fm.group(5) or "").strip()

                        combined = " ".join(field_comments).strip()
                        if inline:
                            combined = (combined + " " + inline).strip()

                        proto_fields.append(
                            ProtoField(
                                name=field_name,
                                type_name=type_name,
                                number=field_num,
                                comment=combined,
                                repeated="repeated" in qualifier,
                                optional="optional" in qualifier,
                            )
                        )
                        field_comments = []
                    elif fstripped and not fstripped.startswith(("/*", "*", "enum", "oneof", "map")):
                        field_comments = []

                j += 1

            messages.append(
                ProtoMessage(
                    name=msg_name,
                    comment=doc,
                    fields=proto_fields,
                    source_file=source_name,
                    is_response=msg_name.endswith(("Response", "Result")),
                )
            )
            i = j
            continue

        # ── anything else resets pending comments ───────────────────────────
        if stripped and not stripped.startswith(("syntax", "package", "import", "option")):
            pending_comments = []

        i += 1

    return messages


def parse_all_protos(files: dict[str, str]) -> dict[str, ProtoMessage]:
    """Parse all proto file contents and return a flat dict of message_name -> ProtoMessage."""
    all_messages: dict[str, ProtoMessage] = {}
    for source_name, content in files.items():
        for msg in parse_proto_text(content, source_name):
            all_messages[msg.name] = msg
    return all_messages


# ---------------------------------------------------------------------------
# Annotation generation via Claude
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a technical writer generating MCP (Model Context Protocol) tool annotations
for the KiCad IPC API. The KiCad IPC API is a protobuf-based API for scripting and
automating the KiCad EDA suite.

Your task: given a set of protobuf message definitions, produce a JSON object mapping
each REQUEST message name to a structured annotation. Skip pure response messages
(those whose names end in Response or Result).

Important KiCad API conventions to include when relevant:
- All coordinates and distances are in **nanometers** (nm). Multiply mm values by 1e6.
- `DocumentSpecifier` identifies which open KiCad document to target (PCB, schematic, etc.).
- `ItemHeader` wraps a DocumentSpecifier plus an optional container KIID and field mask.
- `KIID` is a UUID string identifying a specific design object.
- `BeginCommit`/`EndCommit` must bracket any write operations that should be undoable.
- Messages marked "blocking" cause KiCad to return AS_BUSY until the operation completes.
- Messages marked "interactive" transfer control to the user; KiCad becomes unresponsive
  to further API calls until the user confirms or cancels.
- `WARNING:` comments in the proto indicate destructive or irreversible operations.

Output format — a single JSON object, no markdown fences, no explanation::

{
  "MessageName": {
    "description": "One or two sentences. What does this command do? Who calls it and why?",
    "parameters": {
      "field_name": "What this field controls. Include units, allowed values, or defaults."
    },
    "returns": "What the paired response message contains. Omit if obvious.",
    "warnings": ["Any WARNING or irreversibility notes from the proto, verbatim or paraphrased."],
    "blocking": true,
    "interactive": false
  }
}

Rules:
- Omit `warnings` if the array would be empty.
- Set `blocking` true only for operations explicitly documented as blocking.
- Set `interactive` true only for operations that hand control to the user.
- Keep `description` under 120 characters when possible.
- Field descriptions should mention units (nanometers for coordinates/distances) where applicable.
- If a field has an obvious name and no comment, a one-word description is fine.
"""


def _build_proto_context(messages: dict[str, ProtoMessage]) -> str:
    """Render all parsed messages as structured text for the prompt."""
    sections: list[str] = []
    by_file: dict[str, list[ProtoMessage]] = {}
    for msg in messages.values():
        by_file.setdefault(msg.source_file, []).append(msg)

    for source in sorted(by_file):
        sections.append(f"# {source}")
        for msg in by_file[source]:
            sections.append(msg.as_text())
            sections.append("")

    return "\n".join(sections)


def _filter_command_messages(
    messages: dict[str, ProtoMessage], existing: dict, resume: bool
) -> tuple[dict[str, ProtoMessage], dict[str, ProtoMessage]]:
    """Return (all_messages_for_context, todo_commands) after applying --resume filter."""
    command_messages = {
        name: msg
        for name, msg in messages.items()
        if "_commands" in msg.source_file and not msg.is_response
    }
    if resume:
        already_done = set(existing.get("annotations", {}).keys())
        todo = {n: m for n, m in command_messages.items() if n not in already_done}
        print(f"  Resuming: {len(already_done)} already annotated, {len(todo)} remaining")
    else:
        todo = command_messages
    return command_messages, todo


def _build_full_prompt(proto_context: str, target_names: list[str]) -> str:
    """Build the complete prompt text used by both the SDK and CLI backends."""
    return (
        _SYSTEM_PROMPT
        + "\n\n## KiCad IPC API — proto definitions\n\n"
        + proto_context
        + "\n\n## Annotation request\n\n"
        "Generate MCP annotations for the following request messages:\n"
        + "\n".join(f"- {n}" for n in target_names)
        + "\n\nReturn only the JSON object described in your instructions."
    )


def _parse_response(raw: str) -> dict:
    """Parse a Claude text response to a JSON dict, stripping markdown fences."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Claude returned invalid JSON: {exc}", file=sys.stderr)
        print("--- raw response (first 2000 chars) ---", file=sys.stderr)
        print(raw[:2000], file=sys.stderr)
        sys.exit(1)


def call_claude_sdk(
    messages: dict[str, ProtoMessage],
    model: str,
    existing: dict,
    resume: bool,
) -> dict:
    """
    Annotate messages via the Anthropic Python SDK (requires ANTHROPIC_API_KEY).

    Uses prompt caching on the static proto context block so repeated runs against
    the same proto definitions only bill the small annotation-request portion.
    """
    try:
        import anthropic
    except ImportError:
        sys.exit("anthropic SDK is required.  Install with: pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY is not set. Use --use-cli to call Claude Code instead.")

    client = anthropic.Anthropic(api_key=api_key)

    _, todo = _filter_command_messages(messages, existing, resume)
    if not todo:
        print("  Nothing to annotate.")
        return existing

    proto_context = _build_proto_context(messages)
    target_names = sorted(todo.keys())
    print(f"  Sending {len(target_names)} messages to {model} via SDK ...")

    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    # Cache the large, static proto context block
                    {
                        "type": "text",
                        "text": "## KiCad IPC API — proto definitions\n\n" + proto_context,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": (
                            "## Annotation request\n\n"
                            "Generate MCP annotations for the following request messages:\n"
                            + "\n".join(f"- {n}" for n in target_names)
                            + "\n\nReturn only the JSON object described in your instructions."
                        ),
                    },
                ],
            }
        ],
    )

    usage = response.usage
    if hasattr(usage, "cache_creation_input_tokens"):
        print(
            f"  Tokens — input: {usage.input_tokens}, "
            f"cache_write: {usage.cache_creation_input_tokens}, "
            f"cache_read: {usage.cache_read_input_tokens}, "
            f"output: {usage.output_tokens}"
        )

    new_annotations = _parse_response(response.content[0].text)
    result = dict(existing)
    result.setdefault("annotations", {}).update(new_annotations)
    return result


def call_claude_cli(
    messages: dict[str, ProtoMessage],
    model: str,
    existing: dict,
    resume: bool,
) -> dict:
    """
    Annotate messages by shelling out to the ``claude`` CLI (Claude Code).

    Works with a Claude.ai monthly subscription — no API key required.
    The ``claude`` binary must be on PATH (install Claude Code from claude.ai/code).

    Note: prompt caching is not available via the CLI; the full context is sent
    each time. Use --resume between interrupted runs to avoid redundant work.
    """
    import shutil
    import subprocess

    claude_bin = shutil.which("claude")
    if not claude_bin:
        sys.exit(
            "claude CLI not found on PATH.\n"
            "Install Claude Code from https://claude.ai/code, then re-run."
        )

    _, todo = _filter_command_messages(messages, existing, resume)
    if not todo:
        print("  Nothing to annotate.")
        return existing

    proto_context = _build_proto_context(messages)
    target_names = sorted(todo.keys())
    print(f"  Sending {len(target_names)} messages to claude CLI ...")

    prompt = _build_full_prompt(proto_context, target_names)

    cmd = [claude_bin, "--output-format", "text", "-p", prompt]
    if model:
        cmd += ["--model", model]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        sys.exit("ERROR: claude CLI timed out after 5 minutes.")
    except FileNotFoundError:
        sys.exit(f"ERROR: could not execute {claude_bin}")

    if proc.returncode != 0:
        print(f"ERROR: claude CLI exited {proc.returncode}", file=sys.stderr)
        if proc.stderr:
            print(proc.stderr[:1000], file=sys.stderr)
        sys.exit(1)

    new_annotations = _parse_response(proc.stdout)
    result = dict(existing)
    result.setdefault("annotations", {}).update(new_annotations)
    return result


def call_claude(
    messages: dict[str, ProtoMessage],
    model: str,
    existing: dict,
    resume: bool,
    use_cli: bool,
) -> dict:
    """Dispatch to the appropriate Claude backend."""
    if use_cli:
        return call_claude_cli(messages, model, existing, resume)
    return call_claude_sdk(messages, model, existing, resume)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def load_existing(output_path: Path) -> dict:
    """Load an existing annotations file, returning an empty structure if absent."""
    if output_path.exists():
        try:
            return json.loads(output_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"annotations": {}}


def write_output(data: dict, output_path: Path, kicad_ref: str) -> None:
    data["_meta"] = {
        "kicad_ref": kicad_ref,
        "generator": "generate_tool_annotations.py",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Written: {output_path} ({len(data.get('annotations', {}))} annotations)")


def dry_run(messages: dict[str, ProtoMessage]) -> None:
    print(f"\nDry run — {len(messages)} command messages found:\n")
    for name in sorted(messages):
        msg = messages[name]
        comment = (msg.comment[:72] + "…") if len(msg.comment) > 75 else msg.comment
        source = f"  [{msg.source_file}]"
        print(f"  {name:<40} {comment or '(no comment)'}")
        print(f"  {'':40} {source}")
        if msg.fields:
            for f in msg.fields[:3]:
                print(f"    {f.name}: {f.type_name}")
            if len(msg.fields) > 3:
                print(f"    … and {len(msg.fields) - 3} more field(s)")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="generate_tool_annotations",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--proto-dir",
        metavar="PATH",
        type=Path,
        help="Local directory containing KiCad proto files (e.g. /path/to/kicad/api/proto).",
    )
    source.add_argument(
        "--fetch-from-gitlab",
        action="store_true",
        help="Download proto files directly from KiCad's GitLab repository.",
    )

    p.add_argument(
        "--kicad-ref",
        metavar="REF",
        default="master",
        help="Git ref (branch, tag, or commit) to fetch from GitLab. Default: master.",
    )
    p.add_argument(
        "--output",
        metavar="FILE",
        type=Path,
        default=Path(DEFAULT_OUTPUT),
        help=f"Output JSON file. Default: {DEFAULT_OUTPUT}.",
    )
    p.add_argument(
        "--model",
        metavar="MODEL",
        default=DEFAULT_MODEL,
        help=f"Claude model to use for annotation. Default: {DEFAULT_MODEL}.",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Skip messages that already have annotations in the output file.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse proto files and list what would be annotated; do not call the API.",
    )

    backend = p.add_mutually_exclusive_group()
    backend.add_argument(
        "--use-cli",
        action="store_true",
        help=(
            "Use the 'claude' CLI (Claude Code) instead of the SDK. "
            "Works with a Claude.ai monthly plan — no API key needed. "
            "Requires the 'claude' binary on PATH."
        ),
    )
    backend.add_argument(
        "--use-sdk",
        action="store_true",
        default=True,
        help="Use the Anthropic Python SDK (requires ANTHROPIC_API_KEY). This is the default.",
    )

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    # ── load proto files ─────────────────────────────────────────────────────
    if args.fetch_from_gitlab:
        print(f"Fetching proto files from GitLab (ref={args.kicad_ref}) ...")
        proto_files = fetch_proto_from_gitlab(args.kicad_ref)
        kicad_ref = args.kicad_ref
    else:
        proto_dir = args.proto_dir.expanduser().resolve()
        if not proto_dir.is_dir():
            sys.exit(f"--proto-dir does not exist: {proto_dir}")
        print(f"Loading proto files from {proto_dir} ...")
        proto_files = load_proto_from_dir(proto_dir)
        kicad_ref = "local"

    print(f"  Loaded {len(proto_files)} proto file(s)")

    # ── parse ────────────────────────────────────────────────────────────────
    messages = parse_all_protos(proto_files)
    request_count = sum(1 for m in messages.values() if not m.is_response)
    print(f"  Parsed {len(messages)} messages ({request_count} request, "
          f"{len(messages) - request_count} response/type)")

    if args.dry_run:
        dry_run_cmd = {
            name: msg
            for name, msg in messages.items()
            if "_commands" in msg.source_file and not msg.is_response
        }
        dry_run(dry_run_cmd)
        return 0

    # ── annotate ─────────────────────────────────────────────────────────────
    existing = load_existing(args.output) if args.resume else {"annotations": {}}
    result = call_claude(
        messages,
        args.model,
        existing,
        resume=args.resume,
        use_cli=args.use_cli,
    )

    # ── write ────────────────────────────────────────────────────────────────
    write_output(result, args.output, kicad_ref)
    return 0


if __name__ == "__main__":
    sys.exit(main())
