#!/usr/bin/env bash
# kicad-mcp — invokes the KiCAD MCP Server container as a stdio MCP server.
# Auto-detects Wayland (+ XWayland fallback), DBus, and GPU on the host.
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

# ─── Display forwarding ───────────────────────────────────────────────────
# We forward BOTH Wayland and X11 sockets when present. KiCAD is built on
# wxWidgets 3, which calls XOpenDisplay() directly at wxApp init regardless
# of GDK_BACKEND=wayland — so a pure Wayland forward is not enough. On
# Wayland compositors that ship XWayland (Hyprland, GNOME, KDE, Sway with
# xwayland enabled, etc.) the X11 socket in /tmp/.X11-unix is answered by
# XWayland and KiCAD renders through it. GDK_BACKEND=wayland is still
# preferred so GTK widgets go native-Wayland where possible.
display_args=()

# Wayland leg
if [[ -n "${WAYLAND_DISPLAY:-}" && -n "${XDG_RUNTIME_DIR:-}" ]] \
   && [[ -S "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}" ]]; then
    display_args+=(
        -e "WAYLAND_DISPLAY=${WAYLAND_DISPLAY}"
        -e "XDG_RUNTIME_DIR=/run/user/${UID_HOST}"
        -e "GDK_BACKEND=wayland,x11"
        -e "QT_QPA_PLATFORM=wayland;xcb"
        -v "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}:/run/user/${UID_HOST}/${WAYLAND_DISPLAY}"
    )
    # Also forward user DBus session for GTK theme / portals
    if [[ -S "${XDG_RUNTIME_DIR}/bus" ]]; then
        display_args+=(
            -v "${XDG_RUNTIME_DIR}/bus:/run/user/${UID_HOST}/bus"
            -e "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${UID_HOST}/bus"
        )
    fi
fi

# X11 leg (XWayland or native Xorg)
if [[ -n "${DISPLAY:-}" && -d /tmp/.X11-unix ]]; then
    display_args+=(
        -e "DISPLAY=${DISPLAY}"
        -v "/tmp/.X11-unix:/tmp/.X11-unix"
    )
    # If host uses XAUTHORITY, forward it too
    if [[ -n "${XAUTHORITY:-}" && -f "${XAUTHORITY}" ]]; then
        display_args+=(
            -e "XAUTHORITY=/tmp/.Xauthority"
            -v "${XAUTHORITY}:/tmp/.Xauthority:ro"
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
    "${display_args[@]}" \
    "${gpu_args[@]}" \
    "$IMAGE" "$@"
