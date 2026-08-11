#!/usr/bin/env bash
# KiCad MCP Server installer for Ubuntu/Debian systems.

set -euo pipefail

readonly MIN_NODE_MAJOR=20
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
readonly REQUIREMENTS_LOCK="$REPO_ROOT/requirements-lock.txt"
readonly DIST_CLI="$REPO_ROOT/dist/cli.js"

info() { printf '[INFO] %s\n' "$1"; }
success() { printf '[OK] %s\n' "$1"; }
warn() { printf '[WARN] %s\n' "$1" >&2; }
fail() { printf '[ERROR] %s\n' "$1" >&2; exit 1; }
command_exists() { command -v "$1" >/dev/null 2>&1; }

[[ "${OSTYPE:-}" == linux-gnu* ]] || fail "This installer only supports Linux."
command_exists apt-get || fail "This installer requires an Ubuntu/Debian system with apt-get."
[[ -f "$REQUIREMENTS_LOCK" ]] || fail "Pinned dependency lock not found: $REQUIREMENTS_LOCK"
[[ -f "$REPO_ROOT/package-lock.json" ]] || fail "npm lockfile not found: $REPO_ROOT/package-lock.json"

install_node_20() {
  info "Installing Node.js 20 from the signed NodeSource apt repository..."
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg

  local key_tmp keyring_tmp
  key_tmp="$(mktemp)"
  keyring_tmp="$(mktemp)"

  # Download data only. Never execute a mutable remote setup script as root.
  curl --fail --silent --show-error --location \
    https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
    --output "$key_tmp"
  gpg --batch --yes --dearmor --output "$keyring_tmp" "$key_tmp"
  sudo install -o root -g root -m 0644 "$keyring_tmp" /usr/share/keyrings/nodesource.gpg
  printf '%s\n' \
    'deb [signed-by=/usr/share/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main' |
    sudo tee /etc/apt/sources.list.d/nodesource.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y nodejs
  rm -f -- "$key_tmp" "$keyring_tmp"
}

info "Checking KiCad..."
if ! command_exists kicad-cli; then
  info "Installing KiCad 9 and its libraries..."
  sudo apt-get update
  sudo apt-get install -y software-properties-common
  sudo add-apt-repository --yes ppa:kicad/kicad-9.0-releases
  sudo apt-get update
  sudo apt-get install -y kicad kicad-libraries
fi
success "KiCad detected: $(kicad-cli version 2>/dev/null | head -n 1)"

command_exists python3 || fail "python3 was not installed with KiCad."
if ! python3 -c 'import pcbnew; print(pcbnew.GetBuildVersion())' >/dev/null 2>&1; then
  fail "python3 cannot import pcbnew. Install KiCad's Python bindings before continuing."
fi
success "KiCad Python bindings are available."

if ! command_exists node; then
  install_node_20
else
  node_major="$(node -p 'Number(process.versions.node.split(".")[0])')"
  if [[ ! "$node_major" =~ ^[0-9]+$ ]] || (( node_major < MIN_NODE_MAJOR )); then
    warn "Node.js $(node --version) is too old; Node.js 20 or newer is required."
    install_node_20
  fi
fi

node_major="$(node -p 'Number(process.versions.node.split(".")[0])')"
[[ "$node_major" =~ ^[0-9]+$ ]] && (( node_major >= MIN_NODE_MAJOR )) ||
  fail "Node.js 20 or newer is required; found $(node --version 2>/dev/null || echo unknown)."
success "Node.js detected: $(node --version)"

info "Installing the locked Node.js dependency tree..."
cd "$REPO_ROOT"
npm ci

info "Building the TypeScript CLI..."
npm run build
[[ -f "$DIST_CLI" ]] || fail "Build completed without the expected entrypoint: $DIST_CLI"

info "Creating and validating the private Python runtime from requirements-lock.txt..."
kicad_python="$(command -v python3)"
KICAD_PYTHON="$kicad_python" node "$DIST_CLI" setup
success "The private KiCad MCP Python runtime is ready."

node_path="$(command -v node)"
config_path="$REPO_ROOT/linux-mcp-config.json"
python3 - "$node_path" "$DIST_CLI" "$config_path" "$kicad_python" <<'PY'
import json
import pathlib
import sys

node, cli, output, kicad_python = sys.argv[1:]
config = {
    "mcpServers": {
        "kicad": {
            "command": node,
            "args": [cli, "serve"],
            "env": {
                "KICAD_PYTHON": kicad_python,
                "NODE_ENV": "production",
                "KICAD_MCP_LOG_LEVEL": "info",
            },
        }
    }
}
pathlib.Path(output).write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
PY

success "Installation complete."
info "MCP configuration example: $config_path"
info "Server command: $node_path $DIST_CLI serve"
