#!/usr/bin/env bash
# kicad-mcp — invokes the KiCAD MCP Server container as a stdio MCP server.
# Auto-detects Wayland, DBus, and GPU on the host.
set -euo pipefail

IMAGE="${KICAD_MCP_IMAGE:-kicad-mcp:runtime}"
PROJECTS_DIR="${KICAD_MCP_PROJECTS:-$HOME/Documents/KiCad}"
LOG_LEVEL="${LOG_LEVEL:-info}"

UID_HOST="$(id -u)"
GID_HOST="$(id -g)"

# Ensure persistence dirs exist on host BEFORE docker tries to bind-mount them
# (docker would create them as root otherwise).
install -d \
    "$HOME/.config/kicad" \
    "$HOME/.local/share/kicad" \
    "$HOME/.kicad-mcp" \
    "$PROJECTS_DIR"

# ─── Wayland forwarding (only when host has a Wayland session) ─────────────
wayland_args=()
if [[ -n "${WAYLAND_DISPLAY:-}" && -n "${XDG_RUNTIME_DIR:-}" ]] \
   && [[ -S "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}" ]]; then
    wayland_args+=(
        -e "WAYLAND_DISPLAY=${WAYLAND_DISPLAY}"
        -e "XDG_RUNTIME_DIR=/run/user/${UID_HOST}"
        -e "GDK_BACKEND=wayland"
        -e "QT_QPA_PLATFORM=wayland"
        -v "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}:/run/user/${UID_HOST}/${WAYLAND_DISPLAY}"
    )
    # Also forward user DBus session for GTK theme / portals
    if [[ -S "${XDG_RUNTIME_DIR}/bus" ]]; then
        wayland_args+=(
            -v "${XDG_RUNTIME_DIR}/bus:/run/user/${UID_HOST}/bus"
            -e "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${UID_HOST}/bus"
        )
    fi
fi

# ─── GPU passthrough (best-effort) ─────────────────────────────────────────
gpu_args=()
if [[ -e /dev/dri ]]; then
    gpu_args+=(--device /dev/dri)
    for g in render video; do
        gid="$(getent group "$g" | cut -d: -f3 || true)"
        if [[ -n "$gid" ]]; then
            gpu_args+=(--group-add "$gid")
        fi
    done
fi

exec docker run --rm -i \
    --user "${UID_HOST}:${GID_HOST}" \
    -e "HOME=/home/kicad" \
    -e "LOG_LEVEL=${LOG_LEVEL}" \
    -e "KICAD_MCP_PROJECTS=${PROJECTS_DIR}" \
    -v "$HOME/.config/kicad:/home/kicad/.config/kicad" \
    -v "$HOME/.local/share/kicad:/home/kicad/.local/share/kicad" \
    -v "$HOME/.kicad-mcp:/home/kicad/.kicad-mcp" \
    -v "$PROJECTS_DIR:$PROJECTS_DIR" \
    "${wayland_args[@]}" \
    "${gpu_args[@]}" \
    "$IMAGE" "$@"
