# Install KiCad MCP without cloning the repository

> **Pre-release status:** `@theavi/kicad-mcp@2.7.0` is not yet published on npm, so the plugin installation commands below currently return `E404`. Use the source installers in the repository until the maintainer release checklist is complete. Release-tag CI now verifies the real published launcher before a release can pass.

KiCad MCP is distributed as two layers:

1. `@theavi/kicad-mcp` is the local npm runtime. It detects KiCad, creates a private Python environment in the user's application-data directory, and starts the MCP stdio server.
2. The `kicad` plugin supplies the MCP configuration and the professional PCB-design workflow to Codex or Claude Code.

This architecture is intentional. KiCad and the board files live on the user's computer, so a remote connector alone cannot control them. The plugin removes client configuration; the local runtime provides access to the desktop application and filesystem.

## Requirements

- KiCad 9 or newer, including its Python/`pcbnew` support
- Node.js 20 or newer with `npx` on `PATH`
- Codex or Claude Code

No Git clone, TypeScript build, repository-local virtual environment, or hand-written MCP configuration is required.

## Codex installation

Add the GitHub repository as a plugin marketplace:

```shell
codex plugin marketplace add mixelpixx/KiCAD-MCP-Server
```

Open `/plugins` in Codex, choose the **KiCad MCP** marketplace, and install **KiCad PCB Designer**. Start a new Codex task after installation.

The plugin launches:

```shell
npx -y @theavi/kicad-mcp@2.7.0 serve
```

The first launch can take several minutes while the private Python environment is created. Later launches reuse it.

## Claude Code installation

Inside Claude Code, add the marketplace and install the plugin:

```text
/plugin marketplace add mixelpixx/KiCAD-MCP-Server
/plugin install kicad@kicad-mcp
/reload-plugins
```

Use `/mcp` to confirm that the `kicad` server connected. Claude Code loads plugin-provided MCP servers automatically when the plugin is enabled.

## First prompt

```text
Create a KiCad project for a 12 V input, 5 V/2 A buck converter board.
Use a 2-layer 60 mm x 40 mm PCB, screw terminals, reverse-polarity and input-surge protection,
status LEDs, mounting holes, and test points. Explain assumptions, use real orderable parts,
run ERC and DRC, and generate Gerbers, drill files, BOM, and position files.
```

## Runtime commands

The npm package can also be used directly:

```shell
npx -y @theavi/kicad-mcp@2.7.0 setup
npx -y @theavi/kicad-mcp@2.7.0 doctor
npx -y @theavi/kicad-mcp@2.7.0 serve
```

- `setup` installs or updates the private runtime.
- `doctor` prints detected paths and health information without modifying KiCad projects.
- `serve` performs setup when necessary and starts the MCP server over stdio.

Set `KICAD_PYTHON` if KiCad is installed in a non-standard location. Set `KICAD_MCP_HOME` to override the private runtime directory.

## What happens on first launch

1. The plugin starts the published npm package through `npx`.
2. The launcher locates the newest usable KiCad Python executable and verifies that it can import `pcbnew`.
3. It creates a private virtual environment with access to KiCad's bundled packages.
4. It installs the pinned runtime requirements and records the package version, KiCad Python path, and requirements hash.
5. It starts the TypeScript MCP server. The server starts its Python bridge and communicates with it through newline-delimited JSON.
6. Codex or Claude Code communicates with the TypeScript process through MCP JSON-RPC over stdio.

Bootstrap messages go to stderr so they cannot corrupt the MCP JSON-RPC stream on stdout.

## Maintainer release checklist

The repository artifacts do not make the public installation commands work until version `2.7.0` (or the selected release version) is published to npm and the marketplace repository is publicly reachable.

1. Update the version consistently in `package.json`, both plugin manifests, both MCP configuration files, and both marketplace files.
2. Run `npm ci`, `npm test`, and `npm pack --dry-run`.
3. Test the generated tarball on clean Windows, macOS, and Linux virtual machines with supported KiCad versions.
4. Confirm that the publisher controls the `@theavi` npm scope, then publish the public scoped package with `npm publish --access public`.
5. Tag the Git commit and publish checksums and release notes on GitHub.
6. Test both marketplace install flows from the public repository.
7. Optionally submit the plugins to the official Codex/OpenAI and Anthropic directories. Directory acceptance is controlled by those platforms.

For a production release, add CI jobs that build and test the npm tarball, validate the two plugin manifests, exercise MCP initialization, and maintain a KiCad/client compatibility matrix. Sign any future native installer or executable and publish its checksums.

## Current limitations

- The zero-repository flow still needs KiCad and Node.js installed locally.
- The first start requires network access to npm and Python package indexes.
- Plugin installation does not make AI output equivalent to review by a qualified electrical engineer. ERC/DRC and the bundled workflow reduce errors but do not certify safety, EMC, signal integrity, thermal behavior, or manufacturability.
- A pure hosted HTTP connector would need a separate authenticated local agent to reach KiCad and local design files; hosting the current server remotely would not remove the local-runtime requirement.
