#!/usr/bin/env bash
set -euo pipefail

MODE=""
ASSUME_YES=0
SERVER_NAME="kicad"
CLAUDE_CONFIG_PATH=""

SCRIPT_NAME="$(basename "$0")"

usage() {
  cat <<EOF
Usage:
  $SCRIPT_NAME --verify [--name NAME] [--claude-config PATH]
  $SCRIPT_NAME --dry-run [--name NAME] [--claude-config PATH]
  $SCRIPT_NAME --apply [--name NAME] [--claude-config PATH] [--yes]

Options:
  --verify               Check prerequisites and print detected paths
  --dry-run              Show config and merged Claude Desktop config without writing
  --apply                Write/update Claude Desktop config
  --yes                  Do not prompt before writing (only with --apply)
  --name NAME            MCP server name (default: kicad)
  --claude-config PATH   Path to Claude Desktop config file
                         (default: ${XDG_CONFIG_HOME:-$HOME/.config}/Claude/claude_desktop_config.json)

Environment:
  KICAD_PYTHON           Override the Python executable used for KiCad
EOF
}

# --- Terminal formatting ---
if [[ -t 1 ]]; then
  BOLD=$'\033[1m'
  DIM=$'\033[2m'
  RESET=$'\033[0m'
  GREEN=$'\033[32m'
  YELLOW=$'\033[33m'
  RED=$'\033[31m'
  CYAN=$'\033[36m'
else
  BOLD="" DIM="" RESET="" GREEN="" YELLOW="" RED="" CYAN=""
fi

SYM_OK="${GREEN}✓${RESET}"
SYM_WARN="${YELLOW}⚠${RESET}"
SYM_FAIL="${RED}✗${RESET}"

fail() { echo "${SYM_FAIL} ${RED}Error:${RESET} $1" >&2; exit 1; }
info() { echo "${SYM_OK} $1"; }
warn() { echo "${SYM_WARN} ${YELLOW}$1${RESET}"; }

section() {
  echo
  echo "${DIM}────────────────────────────────────────────────────${RESET}"
  echo "${BOLD}${CYAN}$1${RESET}"
  echo "${DIM}────────────────────────────────────────────────────${RESET}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify)
      MODE="verify"
      shift
      ;;
    --dry-run)
      MODE="dry-run"
      shift
      ;;
    --apply)
      MODE="apply"
      shift
      ;;
    --yes)
      ASSUME_YES=1
      shift
      ;;
    --name)
      [[ $# -ge 2 ]] || fail "--name requires a value"
      SERVER_NAME="$2"
      shift 2
      ;;
    --claude-config)
      [[ $# -ge 2 ]] || fail "--claude-config requires a value"
      CLAUDE_CONFIG_PATH="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

[[ -n "$MODE" ]] || { usage; exit 1; }
[[ -n "$SERVER_NAME" ]] || fail "Server name must not be empty"
[[ "$(uname -s)" == "Linux" ]] || fail "This setup script only supports Linux"

if [[ -z "$CLAUDE_CONFIG_PATH" ]]; then
  CLAUDE_CONFIG_PATH="${XDG_CONFIG_HOME:-$HOME/.config}/Claude/claude_desktop_config.json"
fi

case "$CLAUDE_CONFIG_PATH" in
  "~/"*)
    CLAUDE_CONFIG_PATH="$HOME/${CLAUDE_CONFIG_PATH#~/}"
    ;;
esac

CLAUDE_CONFIG_DIR="$(dirname "$CLAUDE_CONFIG_PATH")"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/package.json" ]]; then
  REPO_ROOT="$SCRIPT_DIR"
else
  REPO_ROOT="$(pwd)"
fi

DIST_JS="$REPO_ROOT/dist/index.js"

HELPER_PYTHON="$(command -v python3 || true)"
[[ -n "$HELPER_PYTHON" ]] || fail "python3 not found in PATH"

NODE_PATH="$(command -v node || true)"
[[ -n "$NODE_PATH" ]] || fail "node not found in PATH"

[[ -f "$DIST_JS" ]] || fail "Missing build artifact: $DIST_JS. Run 'npm install && npm run build' first."

KICAD_PYTHON_OVERRIDE="${KICAD_PYTHON:-}"
PYTHON_CANDIDATES=()

# The server gives a repository virtual environment precedence over
# KICAD_PYTHON, so verify that same interpreter when one is present.
PROJECT_VENV_PYTHON=""
for venv_python in "$REPO_ROOT/venv/bin/python" "$REPO_ROOT/.venv/bin/python"; do
  if [[ -e "$venv_python" ]]; then
    [[ -x "$venv_python" ]] || fail "Virtual environment Python is not executable: $venv_python"
    PROJECT_VENV_PYTHON="$venv_python"
    break
  fi
done

if [[ -n "$PROJECT_VENV_PYTHON" ]]; then
  if [[ -n "$KICAD_PYTHON_OVERRIDE" && "$KICAD_PYTHON_OVERRIDE" != "$PROJECT_VENV_PYTHON" ]]; then
    warn "A project virtual environment takes precedence over KICAD_PYTHON: $PROJECT_VENV_PYTHON"
  fi
  PYTHON_CANDIDATES+=("$PROJECT_VENV_PYTHON")
elif [[ -n "$KICAD_PYTHON_OVERRIDE" ]]; then
  [[ -x "$KICAD_PYTHON_OVERRIDE" ]] || fail "KICAD_PYTHON is not executable: $KICAD_PYTHON_OVERRIDE"
  PYTHON_CANDIDATES+=("$KICAD_PYTHON_OVERRIDE")
else
  # Keep this order aligned with the server's Linux Python discovery.
  PYTHON_CANDIDATES+=(
    "/usr/lib/kicad/bin/python3"
    "/usr/local/lib/kicad/bin/python3"
    "/opt/kicad/bin/python3"
    "$HELPER_PYTHON"
    "/usr/bin/python3"
    "/bin/python3"
  )
fi

BASE_PYTHONPATH_CANDIDATES=(
  "/usr/lib/kicad/lib/python3/dist-packages"
  "/usr/share/kicad/scripting/plugins"
  "/usr/local/lib/kicad/lib/python3/dist-packages"
  "$HOME/.local/lib/kicad/lib/python3/dist-packages"
  "/usr/lib/python3/dist-packages"
  "/usr/local/lib/python3/dist-packages"
)

detect_pcbnew() {
  local python_exe="$1"
  local extra_path="$2"

  "$python_exe" - "$extra_path" <<'PY'
import importlib.util
import json
import os
import sys
import sysconfig

extra_path = sys.argv[1]
if extra_path and extra_path not in sys.path:
    sys.path.insert(0, extra_path)

import pcbnew

spec = importlib.util.find_spec("pcbnew")
if spec is None:
    raise RuntimeError("Imported pcbnew, but could not locate the module")

if spec.submodule_search_locations:
    package_dir = os.path.abspath(next(iter(spec.submodule_search_locations)))
    pythonpath = os.path.dirname(package_dir)
elif spec.origin:
    pythonpath = os.path.dirname(os.path.abspath(spec.origin))
else:
    raise RuntimeError("Imported pcbnew, but could not determine its module path")

# PYTHONPATH precedes site-packages at startup. Keep the selected venv's
# packages first so system extensions (for example _cffi_backend) cannot
# shadow the versions installed alongside their Python packages in the venv.
pythonpaths = []
if sys.prefix != sys.base_prefix:
    for key in ("purelib", "platlib"):
        path = sysconfig.get_path(key)
        if path and path not in pythonpaths:
            pythonpaths.append(path)
if pythonpath not in pythonpaths:
    pythonpaths.append(pythonpath)

result = {
    "python_executable": sys.executable,
    "python_version": sys.version.split()[0],
    "pythonpath": os.pathsep.join(pythonpaths),
    "pcbnew_version": (
        pcbnew.GetBuildVersion() if hasattr(pcbnew, "GetBuildVersion") else "unknown"
    ),
    "pcbnew_module": getattr(pcbnew, "__file__", None),
}
print(json.dumps(result))
PY
}

KICAD_PYTHON=""
DETECT_JSON=""

for candidate in "${PYTHON_CANDIDATES[@]}"; do
  [[ -x "$candidate" ]] || continue

  candidate_version="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
  candidate_pythonpaths=("" "${BASE_PYTHONPATH_CANDIDATES[@]}")
  if [[ -n "$candidate_version" ]]; then
    candidate_pythonpaths+=(
      "/usr/lib/python${candidate_version}/dist-packages"
      "/usr/local/lib/python${candidate_version}/dist-packages"
      "/usr/lib/python${candidate_version}/site-packages"
      "/usr/local/lib/python${candidate_version}/site-packages"
      "/usr/lib64/python${candidate_version}/site-packages"
      "$HOME/.local/lib/python${candidate_version}/dist-packages"
      "$HOME/.local/lib/python${candidate_version}/site-packages"
    )
  fi

  for candidate_pythonpath in "${candidate_pythonpaths[@]}"; do
    if [[ -n "$candidate_pythonpath" && ! -d "$candidate_pythonpath" ]]; then
      continue
    fi

    attempt_json="$(detect_pcbnew "$candidate" "$candidate_pythonpath" 2>/dev/null || true)"
    if [[ -n "$attempt_json" ]] && "$HELPER_PYTHON" -c \
      'import json,sys; value=json.loads(sys.argv[1]); assert value["python_executable"]' \
      "$attempt_json" 2>/dev/null; then
      KICAD_PYTHON="$candidate"
      DETECT_JSON="$attempt_json"
      break 2
    fi
  done
done

if [[ -z "$DETECT_JSON" ]]; then
  if [[ -n "$PROJECT_VENV_PYTHON" ]]; then
    fail "Project virtual environment could not import pcbnew: $PROJECT_VENV_PYTHON"
  elif [[ -n "$KICAD_PYTHON_OVERRIDE" ]]; then
    fail "KICAD_PYTHON could not import pcbnew: $KICAD_PYTHON_OVERRIDE"
  fi
  fail "Could not find a Python executable that imports pcbnew. Install KiCad's Python bindings or set KICAD_PYTHON."
fi

PYTHON_EXE="$($HELPER_PYTHON -c 'import json,sys; print(json.loads(sys.argv[1])["python_executable"])' "$DETECT_JSON")"
PYTHON_VERSION="$($HELPER_PYTHON -c 'import json,sys; print(json.loads(sys.argv[1])["python_version"])' "$DETECT_JSON")"
PYTHONPATH_VALUE="$($HELPER_PYTHON -c 'import json,sys; print(json.loads(sys.argv[1])["pythonpath"])' "$DETECT_JSON")"
PCBNEW_VERSION="$($HELPER_PYTHON -c 'import json,sys; print(json.loads(sys.argv[1])["pcbnew_version"])' "$DETECT_JSON")"
PCBNEW_MODULE="$($HELPER_PYTHON -c 'import json,sys; print(json.loads(sys.argv[1])["pcbnew_module"] or "")' "$DETECT_JSON")"

# Import in a fresh process with the exact PYTHONPATH written to the client
# config: a successful discovery probe alone does not verify this environment.
DEPENDENCY_ERRORS="$(PYTHONPATH="$PYTHONPATH_VALUE" "$KICAD_PYTHON" - <<'PY'
import contextlib
import importlib
import sys

# Import names differ from distribution names. Keep these in sync with the
# production requirements.txt (fitz is PyMuPDF's rendering module).
requirements = {
    "pcbnew": "KiCad Python bindings",
    "kipy": "kicad-python",
    "sexpdata": "sexpdata",
    "skip": "kicad-skip",
    "PIL": "Pillow",
    "fitz": "pymupdf",
    "cairosvg": "cairosvg",
    "colorlog": "colorlog",
    "pydantic": "pydantic",
    "requests": "requests",
    "dotenv": "python-dotenv",
}
errors = []
for module, package in requirements.items():
    try:
        with contextlib.redirect_stdout(sys.stderr):
            importlib.import_module(module)
    except Exception as exc:
        errors.append(f"  {package} ({module}): {exc}")
print("\n".join(errors))
PY
)"

show_dependency_errors() {
  warn "Missing or broken Python dependencies in the generated environment:"
  printf '%s\n' "$DEPENDENCY_ERRORS"
  echo "Install the requirements into the selected interpreter, then rerun --verify:"
  printf '  %q -m pip install -r %q\n' "$KICAD_PYTHON" "$REPO_ROOT/requirements.txt"
}

CONFIG_FRAGMENT_JSON="$($HELPER_PYTHON - "$NODE_PATH" "$DIST_JS" "$KICAD_PYTHON" "$PYTHONPATH_VALUE" <<'PY'
import json
import sys

fragment = {
    "command": sys.argv[1],
    "args": [sys.argv[2]],
    "env": {
        "KICAD_PYTHON": sys.argv[3],
        "PYTHONPATH": sys.argv[4],
        "LOG_LEVEL": "info",
    },
}
print(json.dumps(fragment, indent=2))
PY
)"

show_detected() {
  section "Prerequisites"
  echo "  ${SYM_OK} python3          $HELPER_PYTHON"
  echo "  ${SYM_OK} node             $NODE_PATH"
  echo "  ${SYM_OK} build artifact   $DIST_JS"
  echo "  ${SYM_OK} KiCad Python     $KICAD_PYTHON"
  echo "  ${SYM_OK} pcbnew import    $PCBNEW_VERSION"
  if [[ -z "$DEPENDENCY_ERRORS" ]]; then
    echo "  ${SYM_OK} python deps      all requirements importable"
  else
    echo "  ${SYM_FAIL} python deps      missing or broken requirements"
  fi

  section "Configuration"
  echo "  Server name:       ${BOLD}$SERVER_NAME${RESET}"
  echo "  Repo root:         $REPO_ROOT"
  echo "  Python executable: $PYTHON_EXE"
  echo "  Python version:    $PYTHON_VERSION"
  echo "  pcbnew module:     $PCBNEW_MODULE"
  echo "  PYTHONPATH:        $PYTHONPATH_VALUE"
  echo "  Claude config:     $CLAUDE_CONFIG_PATH"
}

merge_config() {
  "$HELPER_PYTHON" - "$CLAUDE_CONFIG_PATH" "$CONFIG_FRAGMENT_JSON" "$SERVER_NAME" <<'PY'
import json
import os
import sys

config_path = sys.argv[1]
fragment = json.loads(sys.argv[2])
server_name = sys.argv[3]

existing = {}
status = {
    "config_exists": False,
    "config_valid": True,
    "had_mcpServers": False,
    "had_entry": False,
}

if os.path.exists(config_path):
    status["config_exists"] = True
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            text = f.read().strip()
            existing = json.loads(text) if text else {}
    except Exception:
        print(json.dumps({"error": "Existing Claude config is not valid JSON", "status": status}))
        sys.exit(2)

if not isinstance(existing, dict):
    print(json.dumps({"error": "Existing Claude config root is not a JSON object", "status": status}))
    sys.exit(2)

if "mcpServers" in existing:
    status["had_mcpServers"] = True
    if not isinstance(existing["mcpServers"], dict):
        print(json.dumps({"error": "'mcpServers' exists but is not an object", "status": status}))
        sys.exit(2)
else:
    existing["mcpServers"] = {}

if server_name in existing["mcpServers"]:
    status["had_entry"] = True

existing["mcpServers"][server_name] = fragment
print(json.dumps({"status": status, "merged": existing}, indent=2))
PY
}

if [[ "$MODE" == "verify" ]]; then
  show_detected
  section "Proposed Claude Desktop entry ('$SERVER_NAME')"
  echo "$CONFIG_FRAGMENT_JSON"
  if [[ -n "$DEPENDENCY_ERRORS" ]]; then
    show_dependency_errors
    exit 1
  fi
  exit 0
fi

MERGE_RESULT="$(merge_config 2>&1)" || {
  echo "$MERGE_RESULT"
  exit 1
}

MERGED_JSON="$($HELPER_PYTHON -c 'import json,sys; print(json.dumps(json.loads(sys.stdin.read())["merged"], indent=2))' <<<"$MERGE_RESULT")"
CONFIG_EXISTS="$($HELPER_PYTHON -c 'import json,sys; print("true" if json.loads(sys.stdin.read())["status"]["config_exists"] else "false")' <<<"$MERGE_RESULT")"
HAD_ENTRY="$($HELPER_PYTHON -c 'import json,sys; print("true" if json.loads(sys.stdin.read())["status"]["had_entry"] else "false")' <<<"$MERGE_RESULT")"

show_detected

section "Proposed MCP entry ('$SERVER_NAME')"
echo "$CONFIG_FRAGMENT_JSON"

section "Claude Desktop config"
if [[ "$CONFIG_EXISTS" == "true" ]]; then
  if [[ "$HAD_ENTRY" == "true" ]]; then
    warn "Existing config already has mcpServers.$SERVER_NAME — it will be replaced."
  else
    info "Existing config will be preserved; mcpServers.$SERVER_NAME will be added."
  fi
else
  info "Config does not exist yet. A new file will be created."
fi
echo
echo "${DIM}Merged config preview:${RESET}"
echo "$MERGED_JSON"

if [[ "$MODE" == "dry-run" ]]; then
  if [[ -n "$DEPENDENCY_ERRORS" ]]; then
    show_dependency_errors
  fi
  exit 0
fi

if [[ -n "$DEPENDENCY_ERRORS" ]]; then
  show_dependency_errors
  fail "Configuration not written. Fix the Python dependencies first."
fi

mkdir -p "$CLAUDE_CONFIG_DIR"

if [[ $ASSUME_YES -ne 1 ]]; then
  echo
  read -r -p "Write this configuration to $CLAUDE_CONFIG_PATH ? [y/N] " REPLY
  case "$REPLY" in
    y|Y|yes|YES) ;;
    *)
      echo "Aborted."
      exit 0
      ;;
  esac
fi

ORIG_MODE=""
if [[ -f "$CLAUDE_CONFIG_PATH" ]]; then
  ORIG_MODE="$(stat -c '%a' "$CLAUDE_CONFIG_PATH")"
  BACKUP_PATH="${CLAUDE_CONFIG_PATH}.bak.$(date +%Y%m%d-%H%M%S)"
  cp "$CLAUDE_CONFIG_PATH" "$BACKUP_PATH"
  info "Backup written to ${DIM}$BACKUP_PATH${RESET}"
fi

TMP_PATH="${CLAUDE_CONFIG_PATH}.tmp.$$"
(umask 077 && printf '%s\n' "$MERGED_JSON" > "$TMP_PATH")
if [[ -n "$ORIG_MODE" ]]; then
  chmod "$ORIG_MODE" "$TMP_PATH"
fi
mv "$TMP_PATH" "$CLAUDE_CONFIG_PATH"

section "Done"
info "Claude Desktop configuration updated successfully."

echo
echo "${BOLD}Next steps:${RESET}"
echo "  1. Fully quit Claude Desktop"
echo "  2. Reopen Claude Desktop"
echo "  3. In a new chat, check: + → Connectors"
echo "  4. Verify with:"
echo "     Use the ${BOLD}$SERVER_NAME${RESET} MCP server to run ${BOLD}check_kicad_ui${RESET}."
echo
