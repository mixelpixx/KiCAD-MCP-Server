/**
 * KiCAD MCP Server implementation
 */

import { McpServer } from "@modelcontextprotocol/server";
import { serveStdio, type StdioServerHandle } from "@modelcontextprotocol/server/stdio";
import { spawn, execFile, execFileSync, ChildProcess } from "child_process";
import { existsSync, readdirSync } from "fs";
import { join, dirname, delimiter } from "path";
import { logger } from "./logger.js";
import { PythonCommandBridge } from "./python-bridge.js";
import { computeCommandTimeout, DEFAULT_COMMAND_TIMEOUT_MS } from "./command-timeout.js";

// Import tool registration functions
import { registerProjectTools } from "./tools/project.js";
import { registerBoardTools } from "./tools/board.js";
import { registerComponentTools } from "./tools/component.js";
import { registerRoutingTools } from "./tools/routing.js";
import { registerDesignRuleTools } from "./tools/design-rules.js";
import { registerExportTools } from "./tools/export.js";
import { registerSchematicTools } from "./tools/schematic.js";
import { registerLibraryTools } from "./tools/library.js";
import { registerSymbolLibraryTools } from "./tools/library-symbol.js";
import { registerSchematicHierarchyTools } from "./tools/schematic-hierarchy.js";
import { registerSchematicLayoutTools } from "./tools/schematic-layout.js";
import { registerSchematicBatchTools } from "./tools/schematic-batch.js";
import { registerJLCPCBApiTools } from "./tools/jlcpcb-api.js";
import { registerPartsRegistryTools } from "./tools/parts-registry.js";
import { registerDatasheetTools } from "./tools/datasheet.js";
import { registerFootprintTools } from "./tools/footprint.js";
import { registerSymbolCreatorTools } from "./tools/symbol-creator.js";
import { registerUITools } from "./tools/ui.js";
import { registerFreeroutingTools } from "./tools/freerouting.js";
import { registerEagleTools } from "./tools/eagle.js";
import { registerPcbImportTools } from "./tools/pcb-import.js";
import { registerRouterTools } from "./tools/router.js";
import { toolConfirmationStateCodec } from "./tools/tool-registration.js";

// Import resource registration functions
import { registerProjectResources } from "./resources/project.js";
import { registerBoardResources } from "./resources/board.js";
import { registerComponentResources } from "./resources/component.js";
import { registerLibraryResources } from "./resources/library.js";

// Import prompt registration functions
import { registerComponentPrompts } from "./prompts/component.js";
import { registerRoutingPrompts } from "./prompts/routing.js";
import { registerDesignPrompts } from "./prompts/design.js";
import { registerFootprintPrompts } from "./prompts/footprint.js";

const LONG_RUNNING_COMMANDS = new Set([
  "run_drc",
  "run_erc",
  "sync_schematic_to_board",
  "list_schematic_nets",
  "list_schematic_labels",
  "get_schematic_view",
  "autoroute",
  "import_eagle_project",
  "download_jlcpcb_database",
  "enrich_datasheets",
]);

/** Public for contract tests and embedders that need matching request budgets. */
export function commandTimeoutMs(command: string, params?: unknown): number {
  if (command === "download_jlcpcb_database") return 3_600_000;
  if (command === "autoroute") {
    return Math.min(Math.max(computeCommandTimeout(command, params), 1_800_000), 3_600_000);
  }
  if (LONG_RUNNING_COMMANDS.has(command) || command.startsWith("export_")) return 600_000;
  return computeCommandTimeout(command, params);
}

function getWindowsKiCadPythonCandidates(): string[] {
  const roots = [
    process.env.LOCALAPPDATA ? join(process.env.LOCALAPPDATA, "Programs", "KiCad") : undefined,
    "C:\\Program Files\\KiCad",
    "C:\\Program Files (x86)\\KiCad",
  ].filter((root): root is string => Boolean(root));

  const candidates: string[] = [];

  for (const root of roots) {
    if (!existsSync(root)) {
      continue;
    }

    try {
      const versionDirs = readdirSync(root, { withFileTypes: true })
        .filter((entry) => entry.isDirectory())
        .map((entry) => entry.name)
        .sort((a, b) => b.localeCompare(a, undefined, { numeric: true }));

      for (const versionDir of versionDirs) {
        candidates.push(join(root, versionDir, "bin", "python.exe"));
      }
    } catch (error: any) {
      logger.warn(`Failed to inspect KiCAD install directory ${root}: ${error.message}`);
    }
  }

  return [...new Set(candidates)];
}

/**
 * Derive the KiCAD bundled-Python site-packages path for a detected python.exe,
 * so PYTHONPATH follows the *same* install we picked (any version, Program Files
 * or per-user %LOCALAPPDATA%) instead of a hardcoded KiCad 9.0 path.
 *
 * KiCAD on Windows installs python at `<root>/<version>/bin/python.exe`, with
 * pcbnew under `<...>/bin/Lib/site-packages` (older/alt layouts use
 * `<version>/lib/python3/dist-packages`). Returns the first existing candidate,
 * or undefined if pythonExe isn't a KiCAD bundled python.
 */
function deriveKiCadSitePackages(pythonExe: string): string | undefined {
  if (process.platform !== "win32") return undefined;
  const lower = pythonExe.toLowerCase();
  if (!lower.endsWith("python.exe") || !lower.includes("kicad")) return undefined;
  const binDir = dirname(pythonExe); // <root>/<version>/bin
  const versionDir = dirname(binDir); // <root>/<version>
  const candidates = [
    join(binDir, "Lib", "site-packages"),
    join(versionDir, "lib", "python3", "dist-packages"),
  ];
  return candidates.find((p) => existsSync(p));
}

/**
 * Find the Python executable to use.
 * Prioritizes explicit overrides, then project venvs, then KiCAD-bundled Python
 * before falling back to system Python.
 */
function findPythonExecutable(scriptPath: string, configuredPythonPath?: string): string {
  const isWindows = process.platform === "win32";
  const isMac = process.platform === "darwin";
  const isLinux = !isWindows && !isMac;

  if (configuredPythonPath) {
    logger.info(`Using configured Python executable: ${configuredPythonPath}`);
    return configuredPythonPath;
  }

  // An explicit launcher/client override must win over a repository-local
  // environment. The packaged CLI uses this to select its managed runtime.
  if (process.env.KICAD_PYTHON) {
    logger.info(`Using KICAD_PYTHON environment variable: ${process.env.KICAD_PYTHON}`);
    return process.env.KICAD_PYTHON;
  }

  // Get the project root (parent of the python/ directory)
  const projectRoot = dirname(dirname(scriptPath));

  // Check for virtual environment
  const venvPaths = [
    join(projectRoot, "venv", isWindows ? "Scripts" : "bin", isWindows ? "python.exe" : "python"),
    join(projectRoot, ".venv", isWindows ? "Scripts" : "bin", isWindows ? "python.exe" : "python"),
  ];

  for (const venvPath of venvPaths) {
    if (existsSync(venvPath)) {
      logger.info(`Found virtual environment Python at: ${venvPath}`);
      return venvPath;
    }
  }

  // Platform-specific KiCAD bundled Python detection
  if (isWindows) {
    // Windows: Always prefer KiCAD's bundled Python (pcbnew.pyd is compiled for it).
    for (const kicadPython of getWindowsKiCadPythonCandidates()) {
      if (existsSync(kicadPython)) {
        logger.info(`Found KiCAD bundled Python at: ${kicadPython}`);
        return kicadPython;
      }
    }
  } else if (isMac) {
    // macOS: Try KiCAD's bundled Python (check multiple versions and locations)
    const kicadPythonVersions = ["3.9", "3.10", "3.11", "3.12", "3.13"];

    // Standard KiCAD installation paths
    const kicadAppPaths = [
      "/Applications/KiCad/KiCad.app",
      "/Applications/KiCAD/KiCad.app", // Alternative capitalization
      `${process.env.HOME}/Applications/KiCad/KiCad.app`, // User Applications folder
    ];

    // Check all KiCAD app locations with all Python versions
    for (const appPath of kicadAppPaths) {
      for (const version of kicadPythonVersions) {
        const kicadPython = `${appPath}/Contents/Frameworks/Python.framework/Versions/${version}/bin/python3`;
        if (existsSync(kicadPython)) {
          logger.info(`Found KiCAD bundled Python at: ${kicadPython}`);
          return kicadPython;
        }
      }
    }

    // Fallback to Homebrew Python (if pcbnew is installed via pip)
    const homebrewPaths = [
      "/opt/homebrew/bin/python3", // Apple Silicon
      "/usr/local/bin/python3", // Intel Mac
      "/opt/homebrew/bin/python3.12",
      "/opt/homebrew/bin/python3.11",
    ];

    for (const path of homebrewPaths) {
      if (existsSync(path)) {
        logger.info(`Found Homebrew Python at: ${path} (ensure pcbnew is importable)`);
        return path;
      }
    }
  } else if (isLinux) {
    // Linux: Try KiCAD bundled Python locations first
    const linuxKicadPaths = [
      "/usr/lib/kicad/bin/python3",
      "/usr/local/lib/kicad/bin/python3",
      "/opt/kicad/bin/python3",
    ];

    for (const path of linuxKicadPaths) {
      if (existsSync(path)) {
        logger.info(`Found KiCAD bundled Python at: ${path}`);
        return path;
      }
    }

    // Resolve system python3 to full path using 'which'
    try {
      const result = execFileSync("which", ["python3"], { encoding: "utf-8" }).trim();
      if (result && existsSync(result)) {
        logger.info(`Resolved system Python via which: ${result}`);
        return result;
      }
    } catch {
      logger.warn("Failed to resolve python3 via which command");
    }

    // Fallback to common system paths
    const systemPaths = ["/usr/bin/python3", "/bin/python3"];
    for (const path of systemPaths) {
      if (existsSync(path)) {
        logger.info(`Found system Python at: ${path}`);
        return path;
      }
    }
  }

  // Default to system Python (last resort)
  logger.info("Using system Python (no venv found)");
  return isWindows ? "python.exe" : "python3";
}

/**
 * KiCAD MCP Server class
 */
export class KiCADMcpServer {
  private pythonProcess: ChildProcess | null = null;
  private kicadScriptPath: string;
  private stdioHandle: StdioServerHandle | null = null;
  private readonly activeServers = new Set<McpServer>();
  private readonly bridge: PythonCommandBridge;
  private backendStartPromise: Promise<void> | null = null;
  private stopped = false;
  private readonly serverInfo: { name: string; version: string; description: string };
  private readonly configuredPythonPath?: string;
  private readonly configuredKiCadPath?: string;
  private restartTimer: NodeJS.Timeout | null = null;
  private restartAttempts = 0;
  private backendPreparer?: () => Promise<void>;
  private readonly intentionalWorkerStops = new WeakSet<ChildProcess>();
  private readonly pythonStderrStates = new WeakMap<
    ChildProcess,
    { buffer: string; level: "error" | "warn" | "info" | "debug" }
  >();

  /** Resolved when Python prints {"type":"ready"} — stdin loop is live. */
  private readyPromise!: Promise<void>;
  private resolveReady!: () => void;
  private rejectReady!: (err: Error) => void;
  /** Accumulates stdout until the READY marker is seen. */
  private startupBuffer: string = "";
  /** True after READY marker detected; persistent handler takes over. */
  private readyDetected: boolean = false;

  /**
   * Constructor for the KiCAD MCP Server
   * @param kicadScriptPath Path to the Python KiCAD interface script
   * @param logLevel Log level for the server
   */
  constructor(
    kicadScriptPath: string,
    options:
      | "error"
      | "warn"
      | "info"
      | "debug"
      | {
          logLevel?: "error" | "warn" | "info" | "debug";
          logDir?: string;
          name?: string;
          version?: string;
          description?: string;
          pythonPath?: string;
          kicadPath?: string;
        } = "info",
  ) {
    const resolvedOptions = typeof options === "string" ? { logLevel: options } : options;
    // Set up the logger
    logger.setLogLevel(resolvedOptions.logLevel ?? "info");
    if (resolvedOptions.logDir) {
      logger.setLogDir(resolvedOptions.logDir);
    }

    this.serverInfo = {
      name: resolvedOptions.name ?? "kicad-mcp-server",
      version: resolvedOptions.version ?? "2.7.0",
      description: resolvedOptions.description ?? "MCP server for KiCad PCB design operations",
    };
    this.configuredPythonPath = resolvedOptions.pythonPath;
    this.configuredKiCadPath = resolvedOptions.kicadPath;

    // Check if KiCAD script exists
    this.kicadScriptPath = kicadScriptPath;
    if (!existsSync(this.kicadScriptPath)) {
      throw new Error(`KiCAD interface script not found: ${this.kicadScriptPath}`);
    }

    // Create the ready promise (resolved when Python sends {"type":"ready"}).
    this.resetReadyPromise();

    this.bridge = new PythonCommandBridge({
      writeRequest: (request) => {
        const stdin = this.pythonProcess?.stdin;
        if (!stdin || stdin.destroyed || !stdin.writable) {
          throw new Error("Python process for KiCad scripting is not writable");
        }
        stdin.write(`${JSON.stringify(request)}\n`);
      },
      logger,
      onDrainTimeout: (request) => this.terminateHungWorker(request.command),
    });
  }

  private terminateHungWorker(command: string): void {
    const worker = this.pythonProcess;
    if (!worker || worker.killed) return;

    this.terminateWorkerTree(worker, `unresponsive after command: ${command}`);
  }

  private terminateWorkerTree(worker: ChildProcess, reason: string): void {
    logger.warn(`Terminating KiCad Python worker tree (${reason})`);
    if (process.platform === "win32" && worker.pid) {
      execFile(
        "taskkill.exe",
        ["/PID", String(worker.pid), "/T", "/F"],
        { windowsHide: true },
        (error) => {
          if (error && !worker.killed) {
            logger.warn(`taskkill could not terminate the worker tree: ${error.message}`);
            worker.kill();
          }
        },
      );
      return;
    }
    if (worker.pid) {
      try {
        // The worker is spawned as a process-group leader on POSIX so helpers
        // such as freerouting/curl cannot outlive a forced backend restart.
        process.kill(-worker.pid, "SIGKILL");
        return;
      } catch (error) {
        logger.warn(`Could not terminate the worker process group: ${String(error)}`);
      }
    }
    worker.kill("SIGKILL");
  }

  private logPythonStderrLine(
    state: { level: "error" | "warn" | "info" | "debug" },
    line: string,
  ): void {
    const taggedLevel = line.match(/\[(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\]/)?.[1];
    if (taggedLevel === "DEBUG") state.level = "debug";
    else if (taggedLevel === "INFO") state.level = "info";
    else if (taggedLevel === "WARNING" || taggedLevel === "WARN") state.level = "warn";
    else if (taggedLevel === "ERROR" || taggedLevel === "CRITICAL") state.level = "error";

    logger[state.level](`Python: ${line}`);
  }

  private handlePythonStderr(process: ChildProcess, data: Buffer): void {
    const state = this.pythonStderrStates.get(process) ?? { buffer: "", level: "warn" as const };
    state.buffer += data.toString();
    const lines = state.buffer.split(/\r?\n/);
    state.buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line) this.logPythonStderrLine(state, line);
    }
    this.pythonStderrStates.set(process, state);
  }

  private flushPythonStderr(process: ChildProcess): void {
    const state = this.pythonStderrStates.get(process);
    if (state?.buffer) this.logPythonStderrLine(state, state.buffer);
    this.pythonStderrStates.delete(process);
  }

  private resetReadyPromise(): void {
    this.readyDetected = false;
    this.startupBuffer = "";
    this.readyPromise = new Promise((resolve, reject) => {
      this.resolveReady = resolve;
      this.rejectReady = reject;
    });
    // The promise is also awaited per command; attach a passive rejection
    // observer so an early worker failure cannot become an unhandled rejection.
    void this.readyPromise.catch(() => undefined);
  }

  /** Build a fresh MCP server for the protocol era selected by serveStdio. */
  private buildServer(): McpServer {
    const server = new McpServer(this.serverInfo, {
      capabilities: {
        tools: { listChanged: false },
        prompts: { listChanged: false },
        resources: { listChanged: false, subscribe: false },
      },
      instructions:
        "Use read-only inspection tools before edits. Open a project explicitly before board or schematic operations. Confirm consequential changes with the user.",
      cacheHints: {
        "server/discover": { ttlMs: 3_600_000, cacheScope: "public" },
        "tools/list": { ttlMs: 86_400_000, cacheScope: "public" },
        "prompts/list": { ttlMs: 86_400_000, cacheScope: "public" },
        "resources/list": { ttlMs: 3_600_000, cacheScope: "public" },
        "resources/templates/list": { ttlMs: 3_600_000, cacheScope: "public" },
        "resources/read": { ttlMs: 0, cacheScope: "private" },
      },
      inputRequired: {
        legacyShim: true,
        maxRounds: 4,
        roundTimeoutMs: 600_000,
      },
      requestState: {
        verify: (state, ctx) => toolConfirmationStateCodec.verify(state, ctx),
      },
    });
    this.registerAll(server);
    this.activeServers.add(server);
    return server;
  }

  /**
   * Create an unconnected protocol instance for embedding and contract tests.
   * Production stdio still goes through serveStdio so era negotiation occurs.
   */
  createProtocolServer(): McpServer {
    return this.buildServer();
  }

  /**
   * Register all tools, resources, and prompts
   */
  private registerAll(server: McpServer): void {
    logger.info("Registering KiCAD tools, resources, and prompts...");

    // Register router tools FIRST (for tool discovery and execution)
    registerRouterTools(server, this.callKicadScript.bind(this));

    // Register all tools
    registerProjectTools(server, this.callKicadScript.bind(this));
    registerBoardTools(server, this.callKicadScript.bind(this));
    registerComponentTools(server, this.callKicadScript.bind(this));
    registerRoutingTools(server, this.callKicadScript.bind(this));
    registerDesignRuleTools(server, this.callKicadScript.bind(this));
    registerExportTools(server, this.callKicadScript.bind(this));
    registerSchematicTools(server, this.callKicadScript.bind(this));
    registerLibraryTools(server, this.callKicadScript.bind(this));
    registerSymbolLibraryTools(server, this.callKicadScript.bind(this));
    registerSchematicHierarchyTools(server, this.callKicadScript.bind(this));
    registerSchematicLayoutTools(server, this.callKicadScript.bind(this));
    registerSchematicBatchTools(server, this.callKicadScript.bind(this));
    registerJLCPCBApiTools(server, this.callKicadScript.bind(this));
    registerDatasheetTools(server, this.callKicadScript.bind(this));
    registerFootprintTools(server, this.callKicadScript.bind(this));
    registerSymbolCreatorTools(server, this.callKicadScript.bind(this));
    registerUITools(server, this.callKicadScript.bind(this));
    registerFreeroutingTools(server, this.callKicadScript.bind(this));
    registerEagleTools(server, this.callKicadScript.bind(this));
    registerPartsRegistryTools(server);
    registerPcbImportTools(server, this.callKicadScript.bind(this));

    // Register all resources
    registerProjectResources(server, this.callKicadScript.bind(this));
    registerBoardResources(server, this.callKicadScript.bind(this));
    registerComponentResources(server, this.callKicadScript.bind(this));
    registerLibraryResources(server, this.callKicadScript.bind(this));

    // Register all prompts
    registerComponentPrompts(server);
    registerRoutingPrompts(server);
    registerDesignPrompts(server);
    registerFootprintPrompts(server);

    logger.info("All KiCAD tools, resources, and prompts registered");
  }

  /**
   * Validate prerequisites before starting the server
   */
  private async validatePrerequisites(pythonExe: string): Promise<boolean> {
    const isWindows = process.platform === "win32";
    const isLinux = process.platform !== "win32" && process.platform !== "darwin";
    const errors: string[] = [];

    // Check if Python executable exists (for absolute paths) or is executable (for commands)
    const isAbsolutePath =
      pythonExe.startsWith("/") || pythonExe.startsWith("C:") || pythonExe.startsWith("\\");
    let pythonExecutableAvailable = true;

    if (isAbsolutePath) {
      // Absolute path: use existsSync
      if (!existsSync(pythonExe)) {
        pythonExecutableAvailable = false;
        errors.push(`Python executable not found: ${pythonExe}`);

        if (isWindows) {
          errors.push("Windows: Install KiCAD 9.0+ from https://www.kicad.org/download/windows/");
          errors.push("Or run: .\\setup-windows.ps1 for automatic configuration");
        } else if (isLinux) {
          errors.push("Linux: Install KiCAD 9.0+ or set KICAD_PYTHON environment variable");
          errors.push("Set KICAD_PYTHON to specify a custom Python path");
        }
      }
    } else {
      // Command name: verify it's executable via --version test
      logger.info(`Validating command-based Python executable: ${pythonExe}`);
      try {
        const { stdout } = await new Promise<{
          stdout: string;
          stderr: string;
        }>((resolve, reject) => {
          execFile(
            pythonExe,
            ["--version"],
            {
              timeout: 3000,
              env: { ...process.env },
            },
            (error: any, stdout: string, stderr: string) => {
              if (error) {
                reject(error);
              } else {
                resolve({ stdout, stderr });
              }
            },
          );
        });

        logger.info(`Python version check passed: ${stdout.trim()}`);
      } catch (error: any) {
        pythonExecutableAvailable = false;
        errors.push(`Python executable not found in PATH: ${pythonExe}`);
        errors.push(`Error: ${error.message}`);
        errors.push("Set KICAD_PYTHON environment variable to specify full path");

        if (isLinux) {
          errors.push("");
          errors.push("Linux troubleshooting:");
          errors.push("1. Check if python3 is installed: which python3");
          errors.push("2. Install KiCAD: sudo apt install kicad (Ubuntu/Debian)");
          errors.push("3. Set KICAD_PYTHON=/usr/bin/python3 in your MCP config");
        }
      }
    }

    // Check if kicad_interface.py exists
    if (!existsSync(this.kicadScriptPath)) {
      errors.push(`KiCAD interface script not found: ${this.kicadScriptPath}`);
    }

    // Check if dist/index.js exists (if running from compiled code)
    const distPath = join(dirname(dirname(this.kicadScriptPath)), "dist", "index.js");
    if (!existsSync(distPath)) {
      errors.push("Project not built. Run: npm run build");
    }

    // Try to test pcbnew import (quick validation)
    if (pythonExecutableAvailable && existsSync(this.kicadScriptPath)) {
      logger.info("Validating pcbnew module access...");

      try {
        const { stdout, stderr } = await new Promise<{
          stdout: string;
          stderr: string;
        }>((resolve, reject) => {
          execFile(
            pythonExe,
            ["-c", "import pcbnew; print('OK')"],
            {
              timeout: 5000,
              env: { ...process.env },
            },
            (error: any, stdout: string, stderr: string) => {
              if (error) {
                reject(error);
              } else {
                resolve({ stdout, stderr });
              }
            },
          );
        });

        if (!stdout.includes("OK")) {
          errors.push("pcbnew module import test failed");
          errors.push(`Output: ${stdout}`);
          errors.push(`Errors: ${stderr}`);

          if (isWindows) {
            errors.push("");
            errors.push("Windows troubleshooting:");
            errors.push(
              "1. Set PYTHONPATH=C:\\Program Files\\KiCad\\9.0\\lib\\python3\\dist-packages",
            );
            errors.push(
              '2. Test: "C:\\Program Files\\KiCad\\9.0\\bin\\python.exe" -c "import pcbnew"',
            );
            errors.push("3. Run: .\\setup-windows.ps1 for automatic fix");
            errors.push("4. See: docs/WINDOWS_TROUBLESHOOTING.md");
          }
        } else {
          logger.info("✓ pcbnew module validated successfully");
        }
      } catch (error: any) {
        errors.push(`pcbnew validation failed: ${error.message}`);

        if (isWindows) {
          errors.push("");
          errors.push("This usually means:");
          errors.push("- KiCAD is not installed");
          errors.push("- PYTHONPATH is incorrect");
          errors.push("- Python cannot find pcbnew module");
          errors.push("");
          errors.push("Quick fix: Run .\\setup-windows.ps1");
        }
      }
    }

    // Log all errors
    if (errors.length > 0) {
      logger.error("=".repeat(70));
      logger.error("STARTUP VALIDATION FAILED");
      logger.error("=".repeat(70));
      errors.forEach((err) => logger.error(err));
      logger.error("=".repeat(70));

      // Also write to stderr for Claude Desktop to capture
      process.stderr.write("\n" + "=".repeat(70) + "\n");
      process.stderr.write("KiCAD MCP Server - Startup Validation Failed\n");
      process.stderr.write("=".repeat(70) + "\n");
      errors.forEach((err) => process.stderr.write(err + "\n"));
      process.stderr.write("=".repeat(70) + "\n\n");

      return false;
    }

    return true;
  }

  /**
   * Start the MCP server and the Python KiCAD interface
   */
  async start(prepareBackend?: () => Promise<void>): Promise<void> {
    if (this.stdioHandle) {
      return;
    }

    this.stopped = false;
    this.backendPreparer = prepareBackend;
    logger.info("Starting dual-era MCP stdio transport (2026-07-28 + legacy)");
    this.stdioHandle = serveStdio(() => this.createProtocolServer(), {
      legacy: "serve",
      onerror: (error) => logger.error(`MCP stdio error: ${error.message}`),
    });

    // Backend setup can be slow. Serving MCP first keeps discovery responsive;
    // individual KiCad operations await readyPromise in callKicadScript().
    this.backendStartPromise = this.startBackend(prepareBackend).catch((reason) => {
      const error = reason instanceof Error ? reason : new Error(String(reason));
      this.bridge.failAll(error);
      logger.error(`KiCad backend failed to start: ${error.message}`);
      this.scheduleBackendRestart(error);
    });
  }

  /**
   * Restart an unexpectedly failed worker without taking down the MCP transport.
   * A bounded exponential backoff prevents a broken local installation from
   * becoming a tight respawn loop. Calls already waiting on the failed worker
   * are rejected; calls made after the failure wait for the replacement worker.
   */
  private scheduleBackendRestart(reason: Error): void {
    if (this.stopped || this.restartTimer) {
      return;
    }

    const maxRestartAttempts = 3;
    if (this.restartAttempts >= maxRestartAttempts) {
      this.rejectReady(reason);
      logger.error(
        `KiCad backend restart limit reached (${maxRestartAttempts} attempts): ${reason.message}`,
      );
      return;
    }

    // Wake callers that were waiting on the failed generation, then create a
    // fresh readiness gate for commands arriving while the worker restarts.
    this.rejectReady(reason);
    this.resetReadyPromise();

    this.restartAttempts += 1;
    const attempt = this.restartAttempts;
    const delayMs = Math.min(1_000 * 2 ** (attempt - 1), 10_000);
    logger.warn(
      `Restarting KiCad backend in ${delayMs}ms (attempt ${attempt}/${maxRestartAttempts})`,
    );

    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      if (this.stopped) {
        return;
      }

      this.backendStartPromise = this.startBackend(this.backendPreparer).catch((restartReason) => {
        const error =
          restartReason instanceof Error ? restartReason : new Error(String(restartReason));
        this.bridge.failAll(error);
        logger.error(`KiCad backend restart failed: ${error.message}`);
        this.scheduleBackendRestart(error);
      });
    }, delayMs);
    this.restartTimer.unref?.();
  }

  private async startBackend(prepareBackend?: () => Promise<void>): Promise<void> {
    try {
      logger.info("Starting KiCad Python backend...");

      if (prepareBackend) {
        await prepareBackend();
        if (this.stopped) return;
      }

      // Start the Python process for KiCAD scripting
      logger.info(`Starting Python process with script: ${this.kicadScriptPath}`);
      const pythonExe = findPythonExecutable(this.kicadScriptPath, this.configuredPythonPath);

      logger.info(`Using Python executable: ${pythonExe}`);

      // Validate prerequisites
      const isValid = await this.validatePrerequisites(pythonExe);
      if (!isValid) {
        throw new Error("Prerequisites validation failed. See logs above for details.");
      }
      if (this.stopped) return;
      // PYTHONPATH precedence: explicit env override → site-packages derived
      // from the detected KiCAD python (any version / install location) →
      // legacy 9.0 fallback as a last resort.
      const derivedSitePackages = deriveKiCadSitePackages(pythonExe);
      if (derivedSitePackages && !process.env.PYTHONPATH) {
        logger.info(`Using KiCAD site-packages: ${derivedSitePackages}`);
      }
      this.pythonProcess = spawn(pythonExe, [this.kicadScriptPath], {
        stdio: ["pipe", "pipe", "pipe"],
        detached: process.platform !== "win32",
        env: {
          ...process.env,
          PATH: this.configuredKiCadPath
            ? `${this.configuredKiCadPath}${delimiter}${process.env.PATH ?? ""}`
            : process.env.PATH,
          PYTHONPATH:
            process.env.PYTHONPATH ||
            derivedSitePackages ||
            "C:/Program Files/KiCad/9.0/lib/python3/dist-packages",
        },
      });
      const pythonProcess = this.pythonProcess;

      // Listen for process exit
      pythonProcess.on("exit", (code, signal) => {
        if (this.intentionalWorkerStops.delete(pythonProcess)) {
          if (this.pythonProcess === pythonProcess) {
            this.pythonProcess = null;
          }
          logger.debug("KiCad Python worker stopped intentionally");
          return;
        }

        const error = new Error(
          `Python process exited with code ${String(code)} and signal ${String(signal)}`,
        );
        logger.warn(error.message);
        const wasReady = this.readyDetected;
        if (this.pythonProcess === pythonProcess) {
          this.pythonProcess = null;
        }
        if (!wasReady) {
          this.rejectReady(error);
        }
        this.bridge.failAll(error);
        if (wasReady && !this.stopped) {
          this.scheduleBackendRestart(error);
        }
      });

      // Listen for process errors
      pythonProcess.on("error", (err) => {
        logger.error(`Python process error: ${err.message}`);
        if (!this.readyDetected) {
          this.rejectReady(err);
        }
        this.bridge.failAll(err);
      });

      // Set up error logging for stderr
      if (pythonProcess.stderr) {
        pythonProcess.stderr.on("data", (data: Buffer) => {
          this.handlePythonStderr(pythonProcess, data);
        });
        pythonProcess.stderr.on("close", () => this.flushPythonStderr(pythonProcess));
      }

      // ——— Phase 1: stdout handler that detects the READY marker ———
      // Before Python reaches main() it may spend 55-65 s on wxApp init.
      // The stdin loop is only live after main() prints {"type":"ready"}.
      // Until then we buffer everything and scan for that exact JSON line.
      if (pythonProcess.stdout) {
        pythonProcess.stdout.on("data", (data: Buffer) => {
          if (this.readyDetected) {
            // Persistent handler (post-warm-up)
            this.bridge.handleChunk(data);
          } else {
            this.startupBuffer += data.toString();
            const lines = this.startupBuffer.split("\n");
            this.startupBuffer = lines.pop() ?? "";
            for (let i = 0; i < lines.length; i++) {
              const line = lines[i].trim();
              if (!line) continue;
              try {
                const obj = JSON.parse(line);
                if (obj.type === "ready") {
                  logger.info("Python process READY — stdin loop is live");
                  this.readyDetected = true;
                  // Replay any remaining buffered lines through the persistent handler
                  const completeRemaining = lines.slice(i + 1).join("\n");
                  if (completeRemaining.trim()) {
                    this.bridge.handleChunk(Buffer.from(`${completeRemaining}\n`));
                  }
                  if (this.startupBuffer) {
                    this.bridge.handleChunk(Buffer.from(this.startupBuffer));
                    this.startupBuffer = "";
                  }
                  this.resolveReady();
                  return;
                }
              } catch {
                // Not valid JSON yet; keep buffering
              }
            }
          }
        });
      }

      // ——— Phase 2: wait for Python READY ———
      logger.info("Waiting for Python process to be ready...");
      await this.waitForReady(120_000);
      logger.info("Python process is ready.");
      // ——— Phase 3: connect MCP transport immediately ———
      // The transport must be live before any client timeout fires,
      // regardless of how long warm-up takes.
      logger.info("MCP transport is already serving while the backend initializes");
      // ——— Phase 4: background warm-up (does not block MCP) ———
      // Warm-up can take 55-125 s (wxApp + symbol library parse), but
      // the MCP transport is already live so the client timeout does not
      // apply.  Tools invoked during warm-up will work; the first
      // search_symbols may be slower if warm-up hasn't completed yet.
      logger.info("Sending warm-up command (background)...");
      const warmupCommandCompleted = await this.runWarmup(120_000);
      if (!warmupCommandCompleted) {
        // A rejected bridge command may still be executing in the synchronous
        // worker. Quarantine this generation and let its exit handler consume
        // one bounded restart attempt. Starting a replacement here would race
        // the bridge's drain barrier and could kill or feed the wrong worker.
        if (this.pythonProcess === pythonProcess && !pythonProcess.killed) {
          this.terminateWorkerTree(pythonProcess, "warm-up command did not complete");
        }
        return;
      }
      if (this.pythonProcess !== pythonProcess) {
        throw new Error("KiCad backend exited during warm-up");
      }
      this.restartAttempts = 0;
      logger.info("Warm-up complete — pcbnew/wxApp initialised");

      // Write a ready message to stderr (for debugging)
      process.stderr.write("KiCAD MCP SERVER READY\n");

      logger.info("KiCad backend started and ready");
    } catch (error) {
      // A worker that never reached READY must not survive into a retry. Apart
      // from leaking a process, its late READY marker could resolve the next
      // generation's readiness gate and route commands to the wrong worker.
      const failedProcess = this.pythonProcess;
      if (failedProcess && !this.readyDetected) {
        this.pythonProcess = null;
        this.intentionalWorkerStops.add(failedProcess);
        if (!failedProcess.killed) {
          this.terminateWorkerTree(failedProcess, "backend startup failed");
        }
      }
      logger.error(`Failed to start KiCad backend: ${error}`);
      throw error;
    }
  }

  /**
   * Stop the MCP server and clean up resources
   */
  async stop(): Promise<void> {
    if (this.stopped) return;
    this.stopped = true;
    logger.info("Stopping KiCad MCP server...");

    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }

    this.bridge.close(new Error("KiCad MCP server is shutting down"));

    const handle = this.stdioHandle;
    this.stdioHandle = null;
    if (handle) {
      await handle.close();
    }

    for (const server of this.activeServers) {
      if (server.isConnected()) {
        await server
          .close()
          .catch((error) => logger.warn(`Failed to close MCP server cleanly: ${String(error)}`));
      }
    }
    this.activeServers.clear();

    const processToStop = this.pythonProcess;
    this.pythonProcess = null;
    if (processToStop && !processToStop.killed) {
      this.intentionalWorkerStops.add(processToStop);
      this.terminateWorkerTree(processToStop, "server shutdown");
    }

    await this.backendStartPromise?.catch(() => undefined);
    this.backendStartPromise = null;
    logger.info("KiCad MCP server stopped");
  }

  /**
   * Wait for the Python process to print {"type":"ready"} on stdout,
   * signalling that the stdin loop is live and the process can accept
   * commands.
   */
  private async waitForReady(timeoutMs: number, signal?: AbortSignal): Promise<void> {
    if (signal?.aborted) {
      const error = new Error("KiCad command cancelled while waiting for backend readiness");
      error.name = "AbortError";
      throw error;
    }

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error(`Python process did not send READY within ${timeoutMs / 1000} s`));
      }, timeoutMs);

      const onAbort = () => {
        clearTimeout(timeout);
        const error = new Error("KiCad command cancelled while waiting for backend readiness");
        error.name = "AbortError";
        reject(error);
      };
      signal?.addEventListener("abort", onAbort, { once: true });

      void this.readyPromise
        .then(() => {
          clearTimeout(timeout);
          signal?.removeEventListener("abort", onAbort);
          resolve();
        })
        .catch((error) => {
          clearTimeout(timeout);
          signal?.removeEventListener("abort", onAbort);
          reject(error);
        });
    });
  }

  /**
   * Send a _warmup command to the Python process to force full
   * pcbnew/wxApp initialisation.  On macOS this can take 55-65 s;
   * we use a generous timeout so the cost is paid during startup
   * rather than on the first user tool call.
   *
   * Wires into the existing request infrastructure so the persistent
   * stdout handler (already active post-READY) processes the response.
   */
  private async runWarmup(timeoutMs: number): Promise<boolean> {
    if (!this.pythonProcess?.stdin) {
      logger.warn("Python process not running; skipping warm-up");
      return false;
    }

    try {
      const result = (await this.bridge.execute("_warmup", {}, timeoutMs)) as Record<
        string,
        unknown
      >;
      if (result.success) {
        logger.info(
          `Warm-up succeeded: pcbnew ${String(result.version)} (${String(result.elapsed_s)}s)`,
        );
      } else {
        logger.warn(`Warm-up returned failure: ${String(result.message ?? "unknown")}`);
      }
      // A response-level failure means the transport and worker are healthy;
      // IPC-only configurations can continue without optional SWIG warm-up.
      return true;
    } catch (error) {
      logger.warn(`Warm-up failed: ${error instanceof Error ? error.message : String(error)}`);
      return false;
    }
  }

  /**
   * Call the KiCAD scripting interface to execute commands
   *
   * @param command The command to execute
   * @param params The parameters for the command
   * @returns The result of the command execution
   */
  private async callKicadScript(
    command: string,
    params: unknown,
    signal?: AbortSignal,
  ): Promise<unknown> {
    await this.waitForReady(120_000, signal);
    if (!this.pythonProcess) {
      throw new Error("Python process for KiCad scripting is not running");
    }

    const timeout = commandTimeoutMs(command, params);
    if (timeout !== DEFAULT_COMMAND_TIMEOUT_MS) {
      logger.info(`Using extended timeout (${timeout / 1000}s) for command: ${command}`);
    }
    return this.bridge.execute(command, params, timeout, signal);
  }
}
