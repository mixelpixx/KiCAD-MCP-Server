#!/usr/bin/env node

import { dirname, resolve } from "path";
import { fileURLToPath, pathToFileURL } from "url";
import { startKiCadMcpServer } from "./index.js";
import { applyRuntimeEnvironment, inspectRuntime, prepareRuntime } from "./runtime.js";

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));

function printHelp(): void {
  process.stdout.write(
    `KiCad MCP Server\n\nUsage:\n  kicad-mcp serve [--config PATH]  Start the MCP stdio server (default)\n  kicad-mcp setup                  Install or update the private Python runtime\n  kicad-mcp doctor                 Print machine and runtime diagnostics\n  kicad-mcp --help                 Show this help\n`,
  );
}

export type CliCommand = "serve" | "setup" | "doctor" | "help";

export interface CliInvocation {
  command: CliCommand;
  configPath?: string;
}

export function parseCliArguments(args: string[]): CliInvocation {
  if (args.length === 0) return { command: "serve" };

  const first = args[0];
  if (first === "--help" || first === "-h" || first === "help") {
    if (args.length > 1) throw new Error("The help command does not accept arguments");
    return { command: "help" };
  }

  // Keep `kicad-mcp --config PATH` as a convenient form of the default
  // `serve` command while documenting the explicit form for MCP clients.
  const command: CliCommand = first.startsWith("-")
    ? "serve"
    : first === "serve" || first === "setup" || first === "doctor"
      ? first
      : (() => {
          throw new Error(`Unknown command: ${first}`);
        })();
  const options = first.startsWith("-") ? args : args.slice(1);

  if (command !== "serve") {
    if (options.length > 0) throw new Error(`${command} does not accept arguments`);
    return { command };
  }

  let configPath: string | undefined;
  for (let index = 0; index < options.length; index += 1) {
    const option = options[index];
    if (option === "--config") {
      const value = options[index + 1];
      if (!value || value.startsWith("-")) {
        throw new Error("--config requires a path");
      }
      configPath = value;
      index += 1;
      continue;
    }
    if (option.startsWith("--config=")) {
      configPath = option.slice("--config=".length);
      if (!configPath) throw new Error("--config requires a path");
      continue;
    }
    throw new Error(`Unknown serve option: ${option}`);
  }

  return { command, configPath };
}

export async function main(args: string[] = process.argv.slice(2)): Promise<void> {
  const { command, configPath } = parseCliArguments(args);

  if (command === "help") {
    printHelp();
    return;
  }

  if (command === "doctor") {
    process.stdout.write(`${JSON.stringify(inspectRuntime(packageRoot), null, 2)}\n`);
    return;
  }

  if (command === "setup") {
    const runtime = await prepareRuntime(packageRoot);
    process.stdout.write(
      `KiCad MCP ${runtime.packageVersion} is ready.\nRuntime: ${runtime.runtimeHome}\nKiCad Python: ${runtime.basePython}\n`,
    );
    return;
  }

  // Attach MCP before first-run environment creation and dependency setup.
  // Bootstrap output stays on stderr, while tool calls await backend readiness.
  await startKiCadMcpServer({
    configPath,
    prepareBackend: async () => {
      const runtime = await prepareRuntime(packageRoot);
      applyRuntimeEnvironment(runtime);
    },
  });
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : undefined;
if (invokedPath === import.meta.url) {
  void main().catch((error) => {
    const message = error instanceof Error ? error.message : String(error);
    process.stderr.write(`[kicad-mcp] ${message}\n`);
    process.exit(1);
  });
}
