import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, dirname, isAbsolute, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const serverPath = join(projectRoot, "dist", "index.js");
const localPython =
  process.platform === "win32"
    ? join(projectRoot, ".venv", "Scripts", "python.exe")
    : join(projectRoot, ".venv", "bin", "python");
const configuredPython = process.env.KICAD_PYTHON || localPython;
const useFixtureBackend = process.env.KICAD_MCP_PROTOCOL_FAKE === "true";
const fixtureBackend = join(projectRoot, "python", "protocol_test_backend.py");
const fixturePythonPath = join(projectRoot, "scripts", "protocol-fixtures");

assert.ok(existsSync(serverPath), `Built server not found: ${serverPath}`);
if (isAbsolute(configuredPython)) {
  assert.ok(
    existsSync(configuredPython),
    `KiCad Python environment not found: ${configuredPython}`,
  );
}
if (useFixtureBackend) {
  assert.ok(existsSync(fixtureBackend), `Protocol fixture backend not found: ${fixtureBackend}`);
}

const serverEnvironment = Object.fromEntries(
  Object.entries(process.env).filter((entry) => typeof entry[1] === "string"),
);
serverEnvironment.KICAD_AUTO_LAUNCH = "false";
serverEnvironment.KICAD_PYTHON = configuredPython;
serverEnvironment.KICAD_MCP_LOG_LEVEL = "error";
if (useFixtureBackend) {
  serverEnvironment.KICAD_SCRIPT_PATH = fixtureBackend;
  serverEnvironment.PYTHONPATH = [fixturePythonPath, serverEnvironment.PYTHONPATH]
    .filter(Boolean)
    .join(delimiter);
}

function textContent(result) {
  const text = result.content?.find((item) => item.type === "text")?.text;
  assert.ok(text, "Tool result did not contain text content");
  return text;
}

function textPayload(result) {
  const text = textContent(result);
  if (result.isError) {
    throw new Error(`Tool returned an MCP error: ${text}`);
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`Tool returned non-JSON text: ${text}`, { cause: error });
  }
}

async function verifyProjectHandle(client) {
  const temporaryProject = await mkdtemp(join(tmpdir(), "kicad-mcp-protocol-"));
  try {
    const created = textPayload(
      await client.callTool({
        name: "create_project",
        arguments: { path: temporaryProject, name: "protocol-test" },
      }),
    );
    assert.equal(created.success, true);
    assert.match(created.projectHandle, /^kicad-project:/);
    assert.equal(
      created.projectPath,
      join(temporaryProject, "protocol-test.kicad_pcb").replaceAll("\\", "/"),
    );

    const info = textPayload(
      await client.callTool({
        name: "get_project_info",
        arguments: { projectHandle: created.projectHandle },
      }),
    );
    assert.equal(info.projectHandle, created.projectHandle);

    const stale = await client.callTool({
      name: "get_project_info",
      arguments: { projectHandle: "kicad-project:stale" },
    });
    assert.equal(stale.isError, true);
    assert.match(textContent(stale), /Stale or incorrect projectHandle/);

    const closed = textPayload(
      await client.callTool({
        name: "close_project",
        arguments: { projectHandle: created.projectHandle, save: false },
      }),
    );
    assert.equal(closed.projectHandle, created.projectHandle);
    assert.equal(closed.projectHandleStatus, "closed");
  } finally {
    assert.equal(dirname(temporaryProject), tmpdir());
    await rm(temporaryProject, { recursive: true, force: true });
  }
}

async function verifyConnection(
  label,
  versionNegotiation,
  expectedEra,
  expectedVersion,
  verifyHandles = false,
) {
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [serverPath],
    cwd: projectRoot,
    env: serverEnvironment,
    stderr: "pipe",
  });
  let serverErrors = "";
  transport.stderr?.on("data", (chunk) => {
    serverErrors += chunk.toString();
  });

  const client = new Client(
    { name: `kicad-mcp-${label}-verification`, version: "1.0.0" },
    versionNegotiation ? { versionNegotiation } : undefined,
  );

  try {
    await client.connect(transport);
    assert.equal(client.getProtocolEra(), expectedEra);
    assert.equal(client.getNegotiatedProtocolVersion(), expectedVersion);

    const listed = await client.listTools();
    assert.ok(
      listed.tools.length > 100,
      `Expected the KiCad tool catalog, got ${listed.tools.length}`,
    );

    const saveProject = listed.tools.find((tool) => tool.name === "save_project");
    assert.ok(saveProject, "save_project was not advertised");
    assert.ok(
      saveProject.inputSchema?.properties?.projectHandle,
      "save_project did not advertise the optional projectHandle",
    );
    if (verifyHandles) await verifyProjectHandle(client);

    return {
      label,
      era: client.getProtocolEra(),
      protocolVersion: client.getNegotiatedProtocolVersion(),
      serverVersion: client.getServerVersion()?.version,
      toolCount: listed.tools.length,
      cache: {
        ttlMs: listed.ttlMs,
        cacheScope: listed.cacheScope,
      },
    };
  } catch (error) {
    if (serverErrors.trim()) {
      error.message += `\nServer stderr:\n${serverErrors.trim()}`;
    }
    throw error;
  } finally {
    await client.close().catch(() => transport.close());
  }
}

const legacy = await verifyConnection("legacy", undefined, "legacy", "2025-11-25");
const modern = await verifyConnection(
  "modern",
  { mode: { pin: "2026-07-28" } },
  "modern",
  "2026-07-28",
  true,
);

assert.equal(modern.cache.ttlMs, 300_000);
assert.equal(modern.cache.cacheScope, "private");

console.log(JSON.stringify({ legacy, modern }, null, 2));
