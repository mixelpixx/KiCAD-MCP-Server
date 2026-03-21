# Freerouting Integration Guide

**Added in:** v2.2.3 (PR #68, contributor: @jflaflamme)

Freerouting is an open-source autorouter that can automatically route PCB traces. This integration lets you run Freerouting directly from MCP tools without leaving your AI-assisted design workflow.

---

## How It Works

The autorouter uses the Specctra DSN/SES interchange format:

1. Export the current PCB to Specctra DSN format
2. Run Freerouting CLI on the DSN file
3. Import the routed SES result back into the PCB
4. Save the board

The `autoroute` tool performs all four steps in a single call.

---

## Prerequisites

### Freerouting JAR

Download the Freerouting executable JAR:

```bash
mkdir -p ~/.kicad-mcp
curl -L -o ~/.kicad-mcp/freerouting.jar \
  https://github.com/freerouting/freerouting/releases/download/v2.0.1/freerouting-2.0.1-executable.jar
```

The default location is `~/.kicad-mcp/freerouting.jar`. You can override this with:
- The `freeroutingJar` parameter on any tool call
- The `FREEROUTING_JAR` environment variable

### Java Runtime (Option A -- Direct Execution)

Freerouting 2.x requires Java 21 or higher.

```bash
# Ubuntu/Debian
sudo apt install openjdk-21-jre

# Verify
java -version
```

### Docker or Podman (Option B -- No Java Install Needed)

If you do not have Java 21+ installed, the integration automatically falls back to Docker or Podman using the `eclipse-temurin:21-jre` image.

```bash
# Pull the image (one-time)
docker pull eclipse-temurin:21-jre

# Or with Podman
podman pull eclipse-temurin:21-jre
```

### Automatic Runtime Detection

The autorouter checks for runtimes in this order:

1. Local Java 21+ (direct execution, fastest)
2. Docker (container execution)
3. Podman (container execution)

If none are available, an error is returned with installation instructions.

---

## Tools Reference

### `check_freerouting`

Verify that prerequisites are installed before running the autorouter.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `freeroutingJar` | string | No | Path to freerouting.jar to check |

**Returns:** Java availability, version, Docker status, JAR location

**Example:**
```
Check if Freerouting is ready on my system.
```

### `autoroute`

Run the full autorouting workflow (export DSN, route, import SES).

**Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `boardPath` | string | No | Current board | Path to .kicad_pcb file |
| `freeroutingJar` | string | No | ~/.kicad-mcp/freerouting.jar | Path to freerouting.jar |
| `maxPasses` | number | No | 20 | Maximum routing passes |
| `timeout` | number | No | 300 | Timeout in seconds |

**Example:**
```
Autoroute the current board using Freerouting with a 5-minute timeout.
```

### `export_dsn`

Export the PCB to Specctra DSN format for manual routing workflows.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `boardPath` | string | No | Path to .kicad_pcb file (default: current board) |
| `outputPath` | string | No | Output DSN file path (default: same directory as board) |

### `import_ses`

Import a routed Specctra SES file back into the PCB.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sesPath` | string | Yes | Path to the .ses file to import |
| `boardPath` | string | No | Path to .kicad_pcb file (default: current board) |

---

## Workflows

### Automated (Recommended)

A single tool call handles everything:

```
1. Open the project
2. Check Freerouting dependencies
3. Run autoroute with max 10 passes
4. Run DRC to verify the result
5. Export Gerbers
```

### Manual DSN/SES Workflow

For advanced users or external autorouters:

```
1. Export the board to Specctra DSN format
2. (Run Freerouting GUI or another autorouter externally)
3. Import the routed SES file
```

This is useful when you want to:
- Use the Freerouting GUI for interactive routing
- Use a different autorouter that supports DSN/SES
- Route the board on a different machine

---

## Configuration

### Environment Variable

Set `FREEROUTING_JAR` in your MCP client configuration to avoid specifying the path on every call:

```json
{
  "mcpServers": {
    "kicad": {
      "command": "node",
      "args": ["/path/to/KiCAD-MCP-Server/dist/index.js"],
      "env": {
        "FREEROUTING_JAR": "/path/to/freerouting.jar"
      }
    }
  }
}
```

---

## Troubleshooting

### "Neither Java 21+ nor Docker found"

Install either Java 21+ or Docker/Podman. See the Prerequisites section above.

### "Java found but version < 21"

Freerouting 2.x requires Java 21+. Either:
- Upgrade your Java installation
- Install Docker as a fallback

### Timeout Errors

For complex boards, increase the timeout:
```
Autoroute with timeout 600 and max passes 30.
```

### Routing Quality

If the autorouter does not route all connections:
- Increase `maxPasses` (default: 20)
- Check that your design rules allow the autorouter enough clearance
- Run DRC after autorouting to identify any violations
- Consider routing critical traces manually first, then autorouting the rest

### Docker Permission Errors

If Docker reports permission errors:
```bash
# Add your user to the docker group
sudo usermod -aG docker $USER
# Log out and back in for the change to take effect
```

---

## Source Files

- TypeScript tool definitions: `src/tools/freerouting.ts`
- Python implementation: `python/commands/freerouting.py`
- Tests: `python/tests/test_freerouting.py`
