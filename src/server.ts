/**
 * KiCAD MCP Server implementation
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import express from "express";
import { spawn, exec, execSync, ChildProcess } from "child_process";
import { existsSync, readdirSync } from "fs";
import { join, dirname } from "path";
import { logger } from "./logger.js";
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
import { registerDigiKeyApiTools } from "./tools/digikey-api.js";
import { registerPartsRegistryTools } from "./tools/parts-registry.js";
import { registerDatasheetTools } from "./tools/datasheet.js";
import { registerFootprintTools } from "./tools/footprint.js";
import { registerSymbolCreatorTools } from "./tools/symbol-creator.js";
import { registerUITools } from "./tools/ui.js";
import { registerFreeroutingTools } from "./tools/freerouting.js";
import { registerEagleTools } from "./tools/eagle.js";
import { registerPcbImportTools } from "./tools/pcb-import.js";
import { registerValidationTools } from "./tools/validation.js";
import { registerRouterTools } from "./tools/router.js";

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
 * Prioritizes project venvs, then explicit overrides, then KiCAD-bundled Python
 * before falling back to system Python.
 */
function findPythonExecutable(scriptPath: string): string {
  const isWindows = process.platform === "win32";
  const isMac = process.platform === "darwin";
  const isLinux = !isWindows && !isMac;

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

  // Allow override via KICAD_PYTHON environment variable (any platform)
  if (process.env.KICAD_PYTHON) {
    logger.info(`Using KICAD_PYTHON environment variable: ${process.env.KICAD_PYTHON}`);
    return process.env.KICAD_PYTHON;
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
      const result = execSync("which python3", { encoding: "utf-8" }).trim();
      if (result && existsSync(result)) {
        logger.info(`Resolved system Python via which: ${result}`);
        return result;
      }
    } catch (e) {
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
  private server: McpServer;
  private pythonProcess: ChildProcess | null = null;
  private kicadScriptPath: string;
  private stdioTransport!: StdioServerTransport;
  private requestQueue: Array<{
    request: {
      command: string;
      params: any;
      timeout: number;
      requestId: number;
    };
    resolve: Function;
    reject: Function;
  }> = [];
  private processingRequest = false;
  private responseBuffer: string = "";
  /** Monotonic bridge-local ID; Python echoes it back as `_requestId` (#373). */
  private nextInternalRequestId = 1;
  private currentRequestHandler: {
    requestId: number;
    resolve: Function;
    reject: Function;
    timeoutHandle: NodeJS.Timeout;
  } | null = null;

  /** Resolved when Python prints {"type":"ready"} — stdin loop is live. */
  private readyPromise: Promise<void>;
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
  constructor(kicadScriptPath: string, logLevel: "error" | "warn" | "info" | "debug" = "info") {
    // Set up the logger
    logger.setLogLevel(logLevel);

    // Check if KiCAD script exists
    this.kicadScriptPath = kicadScriptPath;
    if (!existsSync(this.kicadScriptPath)) {
      throw new Error(`KiCAD interface script not found: ${this.kicadScriptPath}`);
    }

    // Initialize the MCP server
    this.server = new McpServer({
      name: "kicad-mcp-server",
      version: "2.7.0",
      description: "MCP server for KiCAD PCB design operations",
    });
    // Create the ready promise (resolved when Python sends {"type":"ready"})
    this.readyPromise = new Promise((resolve, reject) => {
      this.resolveReady = resolve;
      this.rejectReady = reject;
    });

    // Initialize STDIO transport
    this.stdioTransport = new StdioServerTransport();
    logger.info("Using STDIO transport for local communication");

    // Register tools, resources, and prompts
    this.registerAll();
  }

  /**
   * Register all tools, resources, and prompts
   */
  private registerAll(): void {
    logger.info("Registering KiCAD tools, resources, and prompts...");

    // Register router tools FIRST (for tool discovery and execution)
    registerRouterTools(this.server, this.callKicadScript.bind(this));

    // Register all tools
    registerProjectTools(this.server, this.callKicadScript.bind(this));
    registerBoardTools(this.server, this.callKicadScript.bind(this));
    registerComponentTools(this.server, this.callKicadScript.bind(this));
    registerRoutingTools(this.server, this.callKicadScript.bind(this));
    registerDesignRuleTools(this.server, this.callKicadScript.bind(this));
    registerExportTools(this.server, this.callKicadScript.bind(this));
    registerSchematicTools(this.server, this.callKicadScript.bind(this));
    registerLibraryTools(this.server, this.callKicadScript.bind(this));
    registerSymbolLibraryTools(this.server, this.callKicadScript.bind(this));
    registerSchematicHierarchyTools(this.server, this.callKicadScript.bind(this));
    registerSchematicLayoutTools(this.server, this.callKicadScript.bind(this));
    registerSchematicBatchTools(this.server, this.callKicadScript.bind(this));
    registerJLCPCBApiTools(this.server, this.callKicadScript.bind(this));
    registerDigiKeyApiTools(this.server, this.callKicadScript.bind(this));
    registerPartsRegistryTools(this.server);
    registerDatasheetTools(this.server, this.callKicadScript.bind(this));
    registerFootprintTools(this.server, this.callKicadScript.bind(this));
    registerSymbolCreatorTools(this.server, this.callKicadScript.bind(this));
    registerUITools(this.server, this.callKicadScript.bind(this));
    registerFreeroutingTools(this.server, this.callKicadScript.bind(this));
    registerEagleTools(this.server, this.callKicadScript.bind(this));
    registerPcbImportTools(this.server, this.callKicadScript.bind(this));
    registerValidationTools(this.server, this.callKicadScript.bind(this));

    // Register all resources
    registerProjectResources(this.server, this.callKicadScript.bind(this));
    registerBoardResources(this.server, this.callKicadScript.bind(this));
    registerComponentResources(this.server, this.callKicadScript.bind(this));
    registerLibraryResources(this.server, this.callKicadScript.bind(this));

    // Register all prompts
    registerComponentPrompts(this.server);
    registerRoutingPrompts(this.server);
    registerDesignPrompts(this.server);
    registerFootprintPrompts(this.server);

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
          exec(
            `"${pythonExe}" --version`,
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

      const testCommand = `"${pythonExe}" -c "import pcbnew; print('OK')"`;

      try {
        const { stdout, stderr } = await new Promise<{
          stdout: string;
          stderr: string;
        }>((resolve, reject) => {
          exec(
            testCommand,
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
  async start(): Promise<void> {
    try {
      logger.info("Starting KiCAD MCP server...");

      // ——— Phase 0: connect MCP transport BEFORE anything else ———
      // Python + pcbnew/wxApp initialisation can take 55-125 s. If the
      // transport only connects afterwards, every request the client sends
      // in that window sits unread on our stdin -- clients stack a drain
      // listener per unresolved send, tripping MaxListenersExceededWarning
      // (#377) and connect timeouts. Tools, resources and prompts are all
      // registered in the constructor, so initialize/tools/list/prompts/get
      // need no Python; tool CALLS queue until the backend is ready (see
      // processNextRequest's ready gate).
      logger.info("Connecting MCP server to STDIO transport...");
      try {
        await this.server.connect(this.stdioTransport);
        logger.info("Successfully connected to STDIO transport");
      } catch (error) {
        logger.error(`Failed to connect to STDIO transport: ${error}`);
        throw error;
      }

      // Start the Python process for KiCAD scripting
      logger.info(`Starting Python process with script: ${this.kicadScriptPath}`);
      const pythonExe = findPythonExecutable(this.kicadScriptPath);

      logger.info(`Using Python executable: ${pythonExe}`);

      // Validate prerequisites
      const isValid = await this.validatePrerequisites(pythonExe);
      if (!isValid) {
        throw new Error("Prerequisites validation failed. See logs above for details.");
      }
      // PYTHONPATH precedence: explicit env override → site-packages derived
      // from the detected KiCAD python (any version / install location) →
      // legacy 9.0 fallback as a last resort.
      const derivedSitePackages = deriveKiCadSitePackages(pythonExe);
      if (derivedSitePackages && !process.env.PYTHONPATH) {
        logger.info(`Using KiCAD site-packages: ${derivedSitePackages}`);
      }
      this.pythonProcess = spawn(pythonExe, [this.kicadScriptPath], {
        stdio: ["pipe", "pipe", "pipe"],
        env: {
          ...process.env,
          PYTHONPATH:
            process.env.PYTHONPATH ||
            derivedSitePackages ||
            "C:/Program Files/KiCad/9.0/lib/python3/dist-packages",
        },
      });

      // Listen for process exit
      this.pythonProcess.on("exit", (code, signal) => {
        logger.warn(`Python process exited with code ${code} and signal ${signal}`);
        this.pythonProcess = null;
      });

      // Listen for process errors
      this.pythonProcess.on("error", (err) => {
        logger.error(`Python process error: ${err.message}`);
      });

      // Set up error logging for stderr
      if (this.pythonProcess.stderr) {
        this.pythonProcess.stderr.on("data", (data: Buffer) => {
          logger.error(`Python stderr: ${data.toString()}`);
        });
      }

      // ——— Phase 1: stdout handler that detects the READY marker ———
      // Before Python reaches main() it may spend 55-65 s on wxApp init.
      // The stdin loop is only live after main() prints {"type":"ready"}.
      // Until then we buffer everything and scan for that exact JSON line.
      if (this.pythonProcess.stdout) {
        this.pythonProcess.stdout.on("data", (data: Buffer) => {
          if (this.readyDetected) {
            // Persistent handler (post-warm-up)
            this.handlePythonResponse(data);
          } else {
            this.startupBuffer += data.toString();
            const lines = this.startupBuffer.split("\n");
            for (let i = 0; i < lines.length; i++) {
              const line = lines[i].trim();
              if (!line) continue;
              try {
                const obj = JSON.parse(line);
                if (obj.type === "ready") {
                  logger.info("Python process READY — stdin loop is live");
                  this.readyDetected = true;
                  // Replay any remaining buffered lines through the persistent handler
                  const remaining = lines.slice(i + 1).join("\n");
                  if (remaining.trim()) {
                    this.handlePythonResponse(Buffer.from(remaining));
                  }
                  this.resolveReady();
                  // Drain any tool calls that queued while Python was
                  // initialising (the ready gate in processNextRequest).
                  setTimeout(() => this.processNextRequest(), 0);
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
      // ——— Phase 3: background warm-up (transport already live) ———
      // Warm-up can take 55-125 s (wxApp + symbol library parse), but
      // the MCP transport is already live so the client timeout does not
      // apply.  Tools invoked during warm-up will work; the first
      // search_symbols may be slower if warm-up hasn't completed yet.
      logger.info("Sending warm-up command (background)...");
      await this.runWarmup(120_000);
      logger.info("Warm-up complete — pcbnew/wxApp initialised");

      // Write a ready message to stderr (for debugging)
      process.stderr.write("KiCAD MCP SERVER READY\n");

      logger.info("KiCAD MCP server started and ready");
    } catch (error) {
      logger.error(`Failed to start KiCAD MCP server: ${error}`);
      throw error;
    }
  }

  /**
   * Stop the MCP server and clean up resources
   */
  async stop(): Promise<void> {
    logger.info("Stopping KiCAD MCP server...");

    // Kill the Python process if it's running
    if (this.pythonProcess) {
      this.pythonProcess.kill();
      this.pythonProcess = null;
    }

    logger.info("KiCAD MCP server stopped");
  }

  /**
   * Wait for the Python process to print {"type":"ready"} on stdout,
   * signalling that the stdin loop is live and the process can accept
   * commands.
   */
  private async waitForReady(timeoutMs: number): Promise<void> {
    return new Promise((_resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error(`Python process did not send READY within ${timeoutMs / 1000} s`));
      }, timeoutMs);
      this.readyPromise
        .then(() => {
          clearTimeout(timeout);
          _resolve();
        })
        .catch(reject);
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
  private async runWarmup(timeoutMs: number): Promise<void> {
    return new Promise<void>((resolve) => {
      if (!this.pythonProcess || !this.pythonProcess.stdin) {
        logger.warn("Python process not running — skipping warm-up");
        resolve();
        return;
      }

      // With the transport connected before Python is up (#377), a tool call
      // may already have queued and dispatched the moment READY fired. A real
      // command exercises pcbnew exactly like _warmup would -- and writing
      // into its handler slot would corrupt the in-flight request.
      if (this.processingRequest || this.currentRequestHandler) {
        logger.info("Skipping explicit warm-up — a queued command is already warming the backend");
        resolve();
        return;
      }

      const requestId = this.allocateInternalRequestId();
      const requestStr = JSON.stringify({ command: "_warmup", params: {}, requestId });

      const timeoutHandle = setTimeout(() => {
        // Only abandon our own slot: if the warm-up response already arrived,
        // the handler belongs to a later request (#373).
        if (this.currentRequestHandler?.requestId !== requestId) return;
        logger.warn(
          `Warm-up timed out after ${timeoutMs / 1000} s — ` +
            "continuing without full initialisation",
        );
        this.processingRequest = false;
        this.currentRequestHandler = null;
        resolve();
        setTimeout(() => this.processNextRequest(), 0);
      }, timeoutMs);

      // Use the existing request infrastructure to avoid race conditions
      // with the persistent stdout handler.
      this.processingRequest = true;
      this.currentRequestHandler = {
        requestId,
        resolve: (result: any) => {
          clearTimeout(timeoutHandle);
          if (result?.success) {
            logger.info(`Warm-up succeeded: pcbnew ${result.version} (${result.elapsed_s}s)`);
          } else {
            logger.warn(`Warm-up returned failure: ${result?.message || "unknown"} — continuing`);
          }
          resolve();
        },
        reject: (err: Error) => {
          clearTimeout(timeoutHandle);
          logger.warn(`Warm-up failed: ${err.message} — continuing`);
          resolve(); // don't fail the whole server
        },
        timeoutHandle,
      };

      this.pythonProcess.stdin.write(requestStr + "\n");
    });
  }

  /**
   * Call the KiCAD scripting interface to execute commands
   *
   * @param command The command to execute
   * @param params The parameters for the command
   * @returns The result of the command execution
   */
  private async callKicadScript(command: string, params: any): Promise<any> {
    return new Promise((resolve, reject) => {
      // Check if Python process is running
      if (!this.pythonProcess) {
        logger.error("Python process is not running");
        reject(new Error("Python process for KiCAD scripting is not running"));
        return;
      }

      // Determine timeout based on command type (see src/command-timeout.ts).
      const commandTimeout = computeCommandTimeout(command, params);
      if (commandTimeout !== DEFAULT_COMMAND_TIMEOUT_MS) {
        logger.info(`Using extended timeout (${commandTimeout / 1000}s) for command: ${command}`);
      }

      // Add request to queue with timeout info
      this.requestQueue.push({
        request: {
          command,
          params,
          timeout: commandTimeout,
          requestId: this.allocateInternalRequestId(),
        },
        resolve,
        reject,
      });

      // Process the queue if not already processing
      if (!this.processingRequest) {
        this.processNextRequest();
      }
    });
  }

  /**
   * Handle incoming data from Python process stdout
   * This is a persistent handler that processes all responses
   */
  private handlePythonResponse(data: Buffer): void {
    const chunk = data.toString();
    logger.debug(`Received data chunk: ${chunk.length} bytes`);
    this.responseBuffer += chunk;

    // Try to parse complete JSON responses (may have multiple or partial)
    this.tryParseResponse();
  }

  /**
   * Try to parse complete JSON response frames from the buffer.
   *
   * Responses from the Python side are single-line JSON terminated by '\n'
   * (written via _write_response). The buffer may also contain non-JSON
   * preamble lines (e.g. C-level warnings from pcbnew that leaked to the
   * response fd before the redirect took effect).
   *
   * Consume only newline-delimited frames. Each bridge request carries a
   * process-local request ID which Python echoes back as `_requestId`; a
   * response whose ID does not match the pending request is discarded
   * instead of being delivered to whichever request happens to be pending
   * (#373). Without this, one timeout desynced the pipeline permanently:
   * request A times out, request B dispatches, A's late response resolves
   * B's handler, and every response after that is off by one.
   */
  private tryParseResponse(): void {
    while (true) {
      const newlineIndex = this.responseBuffer.indexOf("\n");
      if (newlineIndex < 0) return; // frame still arriving — keep collecting

      const line = this.responseBuffer.slice(0, newlineIndex).trim();
      this.responseBuffer = this.responseBuffer.slice(newlineIndex + 1);
      if (!line) continue;

      let result: any;
      try {
        result = JSON.parse(line);
      } catch {
        logger.warn(`Stripped non-JSON preamble from Python response: ${line.substring(0, 200)}`);
        continue;
      }

      const responseRequestId =
        result && typeof result === "object" ? result._requestId : undefined;
      const handler = this.currentRequestHandler;
      if (!handler) {
        logger.warn(
          `Discarding Python response ${String(responseRequestId)} with no pending request`,
        );
        continue;
      }

      if (responseRequestId !== handler.requestId) {
        // A late response from a request that already timed out. Discarding
        // it (rather than resolving the current handler with it) is the fix:
        // the pending request's own response is still on its way.
        logger.warn(
          `Discarding stale Python response ${String(responseRequestId)}; ` +
            `waiting for ${handler.requestId}`,
        );
        continue;
      }

      delete result._requestId;
      logger.debug(
        `Completed KiCAD command ${handler.requestId} with result: ` +
          `${result.success ? "success" : "failure"}`,
      );

      clearTimeout(handler.timeoutHandle);
      this.currentRequestHandler = null;
      this.processingRequest = false;
      handler.resolve(result);
      setTimeout(() => this.processNextRequest(), 0);
      return;
    }
  }

  private allocateInternalRequestId(): number {
    return this.nextInternalRequestId++;
  }

  /**
   * Process the next request in the queue
   */
  private processNextRequest(): void {
    // If no more requests or already processing, return
    if (this.requestQueue.length === 0 || this.processingRequest) {
      return;
    }

    // Backend still initialising: hold the queue. Drained when the READY
    // marker fires (see the startup stdout handler). Without this gate, a
    // tool called during the 55-125 s init window would start its 30 s
    // timeout against Python's own startup and always lose (#377).
    if (!this.readyDetected) {
      return;
    }

    // Set processing flag
    this.processingRequest = true;

    // Get the next request
    const { request, resolve, reject } = this.requestQueue.shift()!;

    try {
      logger.debug(`Processing KiCAD command: ${request.command}`);

      // Format the command and parameters as JSON
      const requestStr = JSON.stringify(request);

      // Set a timeout (use command-specific timeout or default)
      const timeoutDuration = request.timeout || 30000;
      const timeoutHandle = setTimeout(() => {
        // The response may have arrived between the timer firing and this
        // callback running; only abandon our own request (#373).
        if (this.currentRequestHandler?.requestId !== request.requestId) return;
        logger.error(`Command timeout after ${timeoutDuration / 1000}s: ${request.command}`);
        logger.error(`Buffer contents: ${this.responseBuffer.substring(0, 200)}...`);

        // Clear state. The buffer is left alone: a partial frame from the
        // timed-out command completes on the next data chunk and is then
        // discarded by ID, not delivered to the next request.
        this.currentRequestHandler = null;
        this.processingRequest = false;

        // Reject the promise
        reject(new Error(`Command timeout after ${timeoutDuration / 1000}s: ${request.command}`));

        // Process next request
        setTimeout(() => this.processNextRequest(), 0);
      }, timeoutDuration);

      // Store the current request handler
      this.currentRequestHandler = { requestId: request.requestId, resolve, reject, timeoutHandle };

      // Write the request to the Python process
      logger.debug(`Sending request: ${requestStr}`);
      this.pythonProcess?.stdin?.write(requestStr + "\n");
    } catch (error) {
      logger.error(`Error processing request: ${error}`);

      // Reset processing flag
      this.processingRequest = false;
      this.currentRequestHandler = null;

      // Process next request
      setTimeout(() => this.processNextRequest(), 0);

      // Reject the promise
      reject(error);
    }
  }
}
