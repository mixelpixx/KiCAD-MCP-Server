# Docker Packaging

A single self-contained Docker image bundles KiCAD 10, Node 22, Python 3.12,
and Java 21. Your host never needs to install these runtimes.

## Scope

- Linux hosts only, Wayland compositor required for GUI features.
- amd64 architecture.
- Personal-use build; not published to any registry.

## One-time setup

```bash
# 1. Build the runtime image (from repo root)
DOCKER_BUILDKIT=1 docker build --target runtime -t kicad-mcp:runtime .

# 2. Install the wrapper on your PATH
install -m 755 scripts/kicad-mcp.sh ~/.local/bin/kicad-mcp

# 3. Register with Claude Code (absolute path — see note below)
claude mcp add -s user kicad -- "$HOME/.local/bin/kicad-mcp"
```

`~/.local/bin` is not on `PATH` in every default shell config (notably
Arch/Ubuntu/Fedora minimal setups), and Claude Code resolves the command via
a plain `PATH` lookup — so the bare name `kicad-mcp` can fail to launch even
though `install` succeeded. Using the absolute path sidesteps that.

For Claude Desktop, add to `~/.config/Claude/claude_desktop_config.json`,
substituting your actual home directory for `command` (JSON config files
cannot expand `$HOME` or other env vars, so the path must be resolved first):

```json
{
  "mcpServers": {
    "kicad": {
      "command": "/home/YOUR_USERNAME/.local/bin/kicad-mcp"
    }
  }
}
```

## What the wrapper does

- Auto-detects host Wayland socket and DBus session.
- Passes your UID/GID so files written to bind mounts stay yours.
- Bind-mounts these persistent host paths:

| Host | Container | Contents |
| --- | --- | --- |
| `~/.config/kicad`      | `/home/kicad/.config/kicad`      | KiCAD prefs, sym-lib-table, fp-lib-table |
| `~/.local/share/kicad` | `/home/kicad/.local/share/kicad` | PCM-installed plugins, 3rd-party libs (JLCPCB) |
| `~/.kicad-mcp`         | `/home/kicad/.kicad-mcp`         | MCP session logs, JLCPCB DB cache |
| `~/Documents/KiCad`    | (same path)                      | Project workspace |

## Environment overrides

| Env var              | Default                    | Effect                                       |
| -------------------- | -------------------------- | -------------------------------------------- |
| `KICAD_MCP_IMAGE`    | `kicad-mcp:runtime`        | Use a different image tag (e.g. `kicad-mcp:dev`) |
| `KICAD_MCP_PROJECTS` | `$HOME/Documents/KiCad`    | Bind a different host projects directory     |
| `LOG_LEVEL`          | `info`                     | Server log verbosity (`error`/`warn`/`info`/`debug`) |

Example:

```bash
KICAD_MCP_PROJECTS=/mnt/nvme/pcb LOG_LEVEL=debug kicad-mcp
```

## GUI usage

`launch_kicad_ui` opens a KiCAD window on your host Wayland compositor.
Subsequent tools use the IPC backend and updates appear live in the GUI.

The container's KiCAD sees only what you bind-mount. Save projects under
`$KICAD_MCP_PROJECTS` (default `~/Documents/KiCad`) so both container and
host can see them.

Requirements auto-detected by the wrapper:
- `$WAYLAND_DISPLAY` is set and the socket exists at `$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY`
- `$DISPLAY` is set and `/tmp/.X11-unix` exists (XWayland answers this on
  modern Wayland compositors — Hyprland, GNOME, KDE, Sway-with-xwayland)
- Optional: `$XDG_RUNTIME_DIR/bus` (DBus session) for GTK theme
- Optional: `/dev/dri` for GPU acceleration

The wrapper forwards BOTH Wayland and X11 sockets when present. KiCAD is
built on wxWidgets 3, which opens an X11 display directly at startup
regardless of `GDK_BACKEND=wayland`, so a pure Wayland forward is not
enough — the X11 socket is what actually gets KiCAD's window on screen.
GTK widgets still prefer Wayland when the backend list allows.

If your host is a TTY / SSH without any display server, GUI tools will
report an error. All headless tools (`create_project`, `export_gerber`,
`run_drc`, etc.) still work.

## Development / devcontainer

The `dev` stage of the same Dockerfile powers a devcontainer for editing
this repo without installing anything on the host. The devcontainer's
`initializeCommand` auto-creates `~/.config/kicad`, `~/.local/share/kicad`,
and `~/.kicad-mcp` on the host (owned by you) before the container's first
boot, so Docker never has to create them itself as root.

```bash
# With VS Code:
code .
# Then Command Palette → "Dev Containers: Reopen in Container"

# With the devcontainer CLI:
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . bash
```

Inside the devcontainer, use the standard scripts:

```bash
npm run dev           # watch mode TS build
npm run test:ts       # vitest
npm run test:py       # pytest
npm run lint          # eslint + black + mypy + flake8
```

To test the MCP server built from your dev image:

```bash
docker build --target dev -t kicad-mcp:dev .
KICAD_MCP_IMAGE=kicad-mcp:dev kicad-mcp
```

## Uninstall

```bash
claude mcp remove kicad
rm ~/.local/bin/kicad-mcp
docker rmi kicad-mcp:runtime
# If you also built the devcontainer or an intermediate stage:
docker rmi kicad-mcp:dev kicad-mcp:base 2>/dev/null || true
# Optional: also remove persisted state
rm -rf ~/.kicad-mcp
# ~/.config/kicad and ~/.local/share/kicad may also be used by a host
# KiCAD install; only delete if you know you don't need them.
```

## Troubleshooting

**`ModuleNotFoundError: No module named 'pcbnew'`**
The Ubuntu KiCAD PPA changed the install path. Find where it went:

```bash
docker run --rm kicad-mcp:runtime bash -c 'dpkg -L kicad | grep pcbnew.py'
```

Update `PYTHONPATH` in the Dockerfile's `base` stage and rebuild.

**GUI opens but has no icons / wrong theme**
Missing DBus session forward or icon theme. The wrapper attempts to mount
both automatically; check that `$XDG_RUNTIME_DIR/bus` exists on your host.

**KiCAD GUI opens but is very slow (software rendering)**
GPU passthrough failed. Verify `/dev/dri` exists on the host and that
your user is in the `render` and `video` groups.

**Container files are owned by root on the host**
The wrapper uses `--user $(id -u):$(id -g)` — check that env is preserved
if you're launching from a service manager (systemd user unit etc.).
