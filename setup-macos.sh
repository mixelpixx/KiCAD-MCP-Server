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
  --apply                Write/update Claude Desktop config; offers to install
                         missing Python dependencies first
  --yes                  Do not prompt before writing or installing dependencies
                         (only with --apply)
  --name NAME            MCP server name (default: kicad)
  --claude-config PATH   Path to Claude Desktop config file
                         (default: ~/Library/Application Support/Claude/claude_desktop_config.json)
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

if [[ -z "$CLAUDE_CONFIG_PATH" ]]; then
  CLAUDE_CONFIG_PATH="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
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

DEFAULT_KICAD_PYTHON="/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"

# Prefer a repo-local venv (created per the README's manual macOS setup) so the
# generated config points at the interpreter that has the requirements
# installed. An explicit KICAD_PYTHON env var still wins.
if [[ -z "${KICAD_PYTHON:-}" && -x "$REPO_ROOT/venv/bin/python3" ]]; then
  KICAD_PYTHON="$REPO_ROOT/venv/bin/python3"
fi
KICAD_PYTHON="${KICAD_PYTHON:-$DEFAULT_KICAD_PYTHON}"

command -v python3 >/dev/null 2>&1 || fail "python3 not found"
NODE_PATH="$(command -v node || true)"
[[ -n "$NODE_PATH" ]] || fail "node not found in PATH"

[[ -f "$DIST_JS" ]] || fail "Missing build artifact: $DIST_JS. Run 'npm install && npm run build' first."
[[ -x "$KICAD_PYTHON" ]] || fail "KiCad Python not found or not executable: $KICAD_PYTHON"

DETECT_JSON="$("$KICAD_PYTHON" - <<'PY'
import json, sys, sysconfig
result = {
    "python_executable": sys.executable,
    "python_version": sys.version.split()[0],
    "purelib": sysconfig.get_paths().get("purelib"),
    "in_venv": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
    "pcbnew_ok": False,
    "pcbnew_version": None,
    "pcbnew_error": None,
}
try:
    import pcbnew
    result["pcbnew_ok"] = True
    if hasattr(pcbnew, "GetBuildVersion"):
        result["pcbnew_version"] = pcbnew.GetBuildVersion()
except Exception as e:
    result["pcbnew_error"] = repr(e)
print(json.dumps(result))
PY
)"

PYTHON_EXE="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["python_executable"])' "$DETECT_JSON")"
PYTHON_VERSION="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["python_version"])' "$DETECT_JSON")"
PYTHONPATH_VALUE="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["purelib"])' "$DETECT_JSON")"
PCBNEW_OK="$(python3 -c 'import json,sys; print("true" if json.loads(sys.argv[1])["pcbnew_ok"] else "false")' "$DETECT_JSON")"
PCBNEW_VERSION="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["pcbnew_version"] or "")' "$DETECT_JSON")"
PCBNEW_ERROR="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["pcbnew_error"] or "")' "$DETECT_JSON")"

if [[ "$PCBNEW_OK" != "true" ]]; then
  fail "KiCad Python could not import pcbnew. Details: $PCBNEW_ERROR"
fi

IN_VENV="$(python3 -c 'import json,sys; print("true" if json.loads(sys.argv[1])["in_venv"] else "false")' "$DETECT_JSON")"

# Runtime requirements as "import-name:pip-package" pairs. The Python bridge
# imports several of these at startup; if one is missing the server dies
# before answering the MCP handshake and the client just times out after 30s
# with no visible error (issue #350).
REQUIRED_PY_MODULES="sexpdata:sexpdata skip:kicad-skip PIL:Pillow colorlog:colorlog pydantic:pydantic requests:requests dotenv:python-dotenv cairosvg:cairosvg kipy:kicad-python"

check_missing_packages() {
  "$KICAD_PYTHON" - "$REQUIRED_PY_MODULES" <<'PY'
import importlib, sys
missing = []
for pair in sys.argv[1].split():
    module_name, package_name = pair.split(":", 1)
    try:
        importlib.import_module(module_name)
    except Exception:
        missing.append(package_name)
print(" ".join(missing))
PY
}

MISSING_PACKAGES="$(check_missing_packages)"

REQUIREMENTS_FILE="$REPO_ROOT/requirements.txt"
if [[ "$IN_VENV" == "true" ]]; then
  PIP_INSTALL_CMD=("$KICAD_PYTHON" -m pip install -r "$REQUIREMENTS_FILE")
else
  PIP_INSTALL_CMD=("$KICAD_PYTHON" -m pip install --user -r "$REQUIREMENTS_FILE")
fi

missing_deps_message() {
  warn "The KiCAD MCP server will not start until the missing Python packages are installed:"
  echo "    ${BOLD}${PIP_INSTALL_CMD[*]}${RESET}"
  echo "  ${DIM}Without them the MCP client times out after 30s with no visible error.${RESET}"
}

CONFIG_FRAGMENT_JSON="$(python3 - "$NODE_PATH" "$DIST_JS" "$KICAD_PYTHON" "$PYTHONPATH_VALUE" <<'PY'
import json, sys
fragment = {
    "command": sys.argv[1],
    "args": [sys.argv[2]],
    "env": {
        "KICAD_PYTHON": sys.argv[3],
        "PYTHONPATH": sys.argv[4],
        "LOG_LEVEL": "info"
    }
}
print(json.dumps(fragment, indent=2))
PY
)"

show_detected() {
  section "Prerequisites"
  echo "  ${SYM_OK} python3          $(command -v python3)"
  echo "  ${SYM_OK} node             $NODE_PATH"
  echo "  ${SYM_OK} build artifact   $DIST_JS"
  echo "  ${SYM_OK} KiCad Python     $KICAD_PYTHON"
  echo "  ${SYM_OK} pcbnew import    $PCBNEW_VERSION"
  if [[ -z "$MISSING_PACKAGES" ]]; then
    echo "  ${SYM_OK} python deps      all requirements importable"
  else
    echo "  ${SYM_FAIL} python deps      missing: $MISSING_PACKAGES"
  fi

  section "Configuration"
  echo "  Server name:       ${BOLD}$SERVER_NAME${RESET}"
  echo "  Repo root:         $REPO_ROOT"
  echo "  Python executable: $PYTHON_EXE"
  echo "  Python version:    $PYTHON_VERSION"
  echo "  PYTHONPATH:        $PYTHONPATH_VALUE"
  echo "  Claude config:     $CLAUDE_CONFIG_PATH"
}

merge_config() {
  python3 - "$CLAUDE_CONFIG_PATH" "$CONFIG_FRAGMENT_JSON" "$SERVER_NAME" <<'PY'
import json, os, sys

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

show_claude_code_hint() {
  section "Claude Code (optional)"
  echo "  Claude Code (the CLI) does not read the Claude Desktop config."
  echo "  To register the server there as well, run:"
  echo
  echo "  claude mcp add --scope user $SERVER_NAME \\"
  echo "    --env KICAD_PYTHON=\"$KICAD_PYTHON\" \\"
  echo "    --env PYTHONPATH=\"$PYTHONPATH_VALUE\" \\"
  echo "    --env LOG_LEVEL=info \\"
  echo "    -- \"$NODE_PATH\" \"$DIST_JS\""
}

if [[ "$MODE" == "verify" ]]; then
  show_detected
  section "Proposed Claude Desktop entry ('$SERVER_NAME')"
  echo "$CONFIG_FRAGMENT_JSON"
  show_claude_code_hint
  if [[ -n "$MISSING_PACKAGES" ]]; then
    echo
    missing_deps_message
    exit 1
  fi
  exit 0
fi

MERGE_RESULT="$(merge_config 2>&1)" || {
  echo "$MERGE_RESULT"
  exit 1
}

MERGED_JSON="$(python3 -c 'import json,sys; print(json.dumps(json.loads(sys.stdin.read())["merged"], indent=2))' <<<"$MERGE_RESULT")"
CONFIG_EXISTS="$(python3 -c 'import json,sys; print("true" if json.loads(sys.stdin.read())["status"]["config_exists"] else "false")' <<<"$MERGE_RESULT")"
HAD_ENTRY="$(python3 -c 'import json,sys; print("true" if json.loads(sys.stdin.read())["status"]["had_entry"] else "false")' <<<"$MERGE_RESULT")"

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
  if [[ -n "$MISSING_PACKAGES" ]]; then
    echo
    missing_deps_message
  fi
  exit 0
fi

if [[ -n "$MISSING_PACKAGES" ]]; then
  section "Python dependencies"
  warn "Missing for $KICAD_PYTHON: $MISSING_PACKAGES"
  DO_INSTALL=$ASSUME_YES
  if [[ $ASSUME_YES -ne 1 ]]; then
    echo
    read -r -p "Install them now with '${PIP_INSTALL_CMD[*]}' ? [y/N] " REPLY
    case "$REPLY" in
      y|Y|yes|YES) DO_INSTALL=1 ;;
    esac
  fi
  if [[ $DO_INSTALL -eq 1 ]]; then
    "${PIP_INSTALL_CMD[@]}"
    STILL_MISSING="$(check_missing_packages)"
    [[ -z "$STILL_MISSING" ]] || fail "Still missing after install: $STILL_MISSING"
    info "Python dependencies installed."
  else
    missing_deps_message
  fi
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
  ORIG_MODE="$(stat -f '%Lp' "$CLAUDE_CONFIG_PATH")"
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

show_claude_code_hint
echo
