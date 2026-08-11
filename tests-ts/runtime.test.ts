import { existsSync, mkdtempSync, rmSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { afterEach, describe, expect, it } from "vitest";
import {
  getKiCadPythonCandidates,
  getRuntimeHome,
  KICAD_PYTHON_IMPORT_PROBE,
  prepareRuntime,
  RUNTIME_PYTHON_IMPORT_PROBE,
  sanitizeRuntimeLog,
  withRuntimeSetupLock,
} from "../src/runtime.js";

const temporaryDirectories: string[] = [];

function makeTemporaryDirectory(): string {
  const directory = mkdtempSync(join(tmpdir(), "kicad-mcp-runtime-test-"));
  temporaryDirectories.push(directory);
  return directory;
}

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

describe("packaged runtime paths", () => {
  it("does not trigger slow pcbnew application initialization in health probes", () => {
    expect(KICAD_PYTHON_IMPORT_PROBE).toContain("import pcbnew");
    expect(RUNTIME_PYTHON_IMPORT_PROBE).toContain("import pcbnew");
    expect(KICAD_PYTHON_IMPORT_PROBE).not.toContain("GetBuildVersion");
    expect(RUNTIME_PYTHON_IMPORT_PROBE).not.toContain("GetBuildVersion");
  });

  it("fails closed when the packaged dependency lock is missing", async () => {
    const packageRoot = makeTemporaryDirectory();

    await expect(prepareRuntime(packageRoot)).rejects.toThrow(
      "The packaged dependency lock is missing",
    );
  });

  it("honors an explicit runtime home", () => {
    expect(getRuntimeHome({ KICAD_MCP_HOME: "X:\\isolated-kicad-mcp" })).toBe(
      "X:\\isolated-kicad-mcp",
    );
  });

  it("prioritizes an explicit existing KiCad Python candidate", () => {
    const candidates = getKiCadPythonCandidates({ KICAD_PYTHON: process.execPath });
    expect(candidates[0]).toBe(process.execPath);
  });

  it("deduplicates Python candidates", () => {
    const candidates = getKiCadPythonCandidates({ KICAD_PYTHON: process.execPath });
    expect(new Set(candidates).size).toBe(candidates.length);
  });

  it("redacts credentials from runtime subprocess logs", () => {
    const message = [
      "Looking in indexes: https://build-user:super-secret@example.test/simple",
      "https://example.test/simple?token=query-secret&package=wheel",
      "Authorization: Bearer header-secret",
      "JLCPCB_API_SECRET=environment-secret",
    ].join("\n");

    const sanitized = sanitizeRuntimeLog(message);

    expect(sanitized).not.toContain("build-user");
    expect(sanitized).not.toContain("super-secret");
    expect(sanitized).not.toContain("query-secret");
    expect(sanitized).not.toContain("header-secret");
    expect(sanitized).not.toContain("environment-secret");
    expect(sanitized).toContain("https://***@example.test/simple");
  });

  it("serializes concurrent runtime setup", async () => {
    const lockPath = join(makeTemporaryDirectory(), "runtime.lock");
    let active = 0;
    let maximumActive = 0;
    const order: string[] = [];

    const setup = (name: string, delayMs: number) =>
      withRuntimeSetupLock(
        lockPath,
        async () => {
          active += 1;
          maximumActive = Math.max(maximumActive, active);
          order.push(`${name}:start`);
          await new Promise((resolve) => setTimeout(resolve, delayMs));
          order.push(`${name}:end`);
          active -= 1;
        },
        () => undefined,
        2_000,
      );

    await Promise.all([setup("first", 75), setup("second", 1)]);

    expect(maximumActive).toBe(1);
    expect(order).toEqual(["first:start", "first:end", "second:start", "second:end"]);
    expect(existsSync(lockPath)).toBe(false);
  });

  it("recovers a runtime lock left by a dead process", async () => {
    const lockPath = join(makeTemporaryDirectory(), "runtime.lock");
    writeFileSync(
      lockPath,
      `${JSON.stringify({
        pid: 2_147_483_647,
        token: "dead-owner",
        createdAt: new Date(0).toISOString(),
      })}\n`,
      "utf8",
    );

    let ran = false;
    await withRuntimeSetupLock(
      lockPath,
      async () => {
        ran = true;
      },
      () => undefined,
      2_000,
    );

    expect(ran).toBe(true);
    expect(existsSync(lockPath)).toBe(false);
  });

  it("releases the runtime lock when setup fails", async () => {
    const lockPath = join(makeTemporaryDirectory(), "runtime.lock");

    await expect(
      withRuntimeSetupLock(
        lockPath,
        async () => {
          throw new Error("installation failed");
        },
        () => undefined,
        2_000,
      ),
    ).rejects.toThrow("installation failed");

    let retryRan = false;
    await withRuntimeSetupLock(lockPath, async () => {
      retryRan = true;
    });

    expect(retryRan).toBe(true);
    expect(existsSync(lockPath)).toBe(false);
  });
});
