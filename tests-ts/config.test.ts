import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { loadConfig } from "../src/config.js";

const tempDirectories: string[] = [];

async function temporaryConfig(contents: unknown): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), "kicad-mcp-config-"));
  tempDirectories.push(directory);
  const path = join(directory, "config.json");
  await writeFile(path, JSON.stringify(contents), "utf8");
  return path;
}

afterEach(async () => {
  await Promise.all(
    tempDirectories.splice(0).map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

describe("loadConfig", () => {
  it("rejects an explicitly requested missing file", async () => {
    await expect(loadConfig(join(tmpdir(), "missing-kicad-mcp-config.json"))).rejects.toThrow(
      /Configuration file not found/,
    );
  });

  it("rejects invalid explicit configuration instead of silently using defaults", async () => {
    const path = await temporaryConfig({ logLevel: "verbose" });
    await expect(loadConfig(path)).rejects.toThrow(/Could not load KiCad MCP configuration/);
  });

  it("normalizes empty optional paths while preserving configured server metadata", async () => {
    const path = await temporaryConfig({
      name: "custom-kicad",
      version: "9.9.9",
      pythonPath: "",
      kicadPath: "",
      logDir: "",
    });

    await expect(loadConfig(path)).resolves.toMatchObject({
      name: "custom-kicad",
      version: "9.9.9",
      pythonPath: undefined,
      kicadPath: undefined,
      logDir: undefined,
    });
  });
});
