import { createHash, randomUUID } from "crypto";
import { spawn, spawnSync } from "child_process";
import {
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  readdirSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "fs";
import { homedir } from "os";
import { delimiter, dirname, join } from "path";

export type RuntimeLogger = (message: string) => void;

export interface PreparedRuntime {
  basePython: string;
  python: string;
  pythonPath?: string;
  kicadBin: string;
  runtimeHome: string;
  packageVersion: string;
}

interface RuntimeState {
  packageVersion: string;
  basePython: string;
  requirementsHash: string;
}

interface CommandResult {
  code: number;
  stdout: string;
  stderr: string;
}

interface RuntimeLockOwner {
  pid: number;
  token: string;
  createdAt: string;
}

const RUNTIME_LOCK_TIMEOUT_MS = 15 * 60 * 1000;
const RUNTIME_LOCK_POLL_MS = 250;

const PYTHON_IMPORT_CHECK = [
  "pcbnew",
  "sexpdata",
  "skip",
  "PIL",
  "cairosvg",
  "colorlog",
  "pydantic",
  "requests",
  "dotenv",
  "kipy",
].join(",");

// Calling pcbnew.GetBuildVersion() lazily initializes wxApp on macOS and can
// take well over a minute. Discovery and health checks need only prove that the
// module loads; the worker performs full initialization during its warm-up.
export const KICAD_PYTHON_IMPORT_PROBE =
  'import pcbnew; print(getattr(pcbnew, "__file__", "pcbnew"))';
export const RUNTIME_PYTHON_IMPORT_PROBE = `import ${PYTHON_IMPORT_CHECK}; print(getattr(pcbnew, "__file__", "pcbnew"))`;

function numericVersionSort(a: string, b: string): number {
  return b.localeCompare(a, undefined, { numeric: true, sensitivity: "base" });
}

function uniqueExisting(paths: Array<string | undefined>): string[] {
  return [...new Set(paths.filter((value): value is string => Boolean(value)))].filter((value) =>
    existsSync(value),
  );
}

export function getRuntimeHome(env: NodeJS.ProcessEnv = process.env): string {
  if (env.KICAD_MCP_HOME) {
    return env.KICAD_MCP_HOME;
  }
  if (process.platform === "win32") {
    return join(env.LOCALAPPDATA || join(homedir(), "AppData", "Local"), "KiCadMCP");
  }
  if (process.platform === "darwin") {
    return join(homedir(), "Library", "Application Support", "KiCadMCP");
  }
  return join(env.XDG_DATA_HOME || join(homedir(), ".local", "share"), "kicad-mcp");
}

export function getKiCadPythonCandidates(env: NodeJS.ProcessEnv = process.env): string[] {
  const candidates: Array<string | undefined> = [env.KICAD_PYTHON];

  if (process.platform === "win32") {
    const roots = [
      env.LOCALAPPDATA ? join(env.LOCALAPPDATA, "Programs", "KiCad") : undefined,
      "C:\\Program Files\\KiCad",
      "C:\\Program Files (x86)\\KiCad",
    ].filter((root): root is string => Boolean(root));

    for (const root of roots) {
      if (!existsSync(root)) continue;
      try {
        const versions = readdirSync(root, { withFileTypes: true })
          .filter((entry) => entry.isDirectory())
          .map((entry) => entry.name)
          .sort(numericVersionSort);
        for (const version of versions) {
          candidates.push(join(root, version, "bin", "python.exe"));
        }
      } catch {
        // Ignore unreadable installation roots and continue with other candidates.
      }
    }
  } else if (process.platform === "darwin") {
    const appRoots = [
      "/Applications/KiCad/KiCad.app",
      "/Applications/KiCAD/KiCad.app",
      join(homedir(), "Applications", "KiCad", "KiCad.app"),
    ];
    for (const appRoot of appRoots) {
      const versionsRoot = join(appRoot, "Contents", "Frameworks", "Python.framework", "Versions");
      candidates.push(join(versionsRoot, "Current", "bin", "python3"));
      if (!existsSync(versionsRoot)) continue;
      try {
        const versions = readdirSync(versionsRoot, { withFileTypes: true })
          .filter((entry) => entry.isDirectory())
          .map((entry) => entry.name)
          .sort(numericVersionSort);
        for (const version of versions) {
          candidates.push(join(versionsRoot, version, "bin", "python3"));
        }
      } catch {
        // Ignore unreadable application bundles.
      }
    }
    candidates.push("/opt/homebrew/bin/python3", "/usr/local/bin/python3");
  } else {
    candidates.push(
      "/usr/lib/kicad/bin/python3",
      "/usr/local/lib/kicad/bin/python3",
      "/opt/kicad/bin/python3",
      "/usr/bin/python3",
      "/bin/python3",
    );
  }

  return uniqueExisting(candidates);
}

export function deriveKiCadPythonPath(pythonExecutable: string): string | undefined {
  if (process.platform === "win32") {
    const binDir = dirname(pythonExecutable);
    const installDir = dirname(binDir);
    return uniqueExisting([
      join(binDir, "Lib", "site-packages"),
      join(installDir, "lib", "python3", "dist-packages"),
    ])[0];
  }

  if (process.platform === "darwin") {
    const versionsDir = dirname(dirname(pythonExecutable));
    const version = versionsDir.split(/[\\/]/).pop();
    return uniqueExisting([
      version ? join(versionsDir, "lib", `python${version}`, "site-packages") : undefined,
    ])[0];
  }

  return undefined;
}

function pythonCanImport(
  pythonExecutable: string,
  pythonPath?: string,
  basePython: string = pythonExecutable,
): boolean {
  const result = spawnSync(pythonExecutable, ["-c", RUNTIME_PYTHON_IMPORT_PROBE], {
    encoding: "utf8",
    timeout: 20_000,
    windowsHide: true,
    env: buildPythonEnvironment(basePython, pythonPath),
  });
  return result.status === 0;
}

export function discoverKiCadPython(env: NodeJS.ProcessEnv = process.env): string {
  const candidates = getKiCadPythonCandidates(env);
  for (const candidate of candidates) {
    const pythonPath = deriveKiCadPythonPath(candidate);
    const result = spawnSync(candidate, ["-c", KICAD_PYTHON_IMPORT_PROBE], {
      encoding: "utf8",
      timeout: 15_000,
      windowsHide: true,
      env: buildPythonEnvironment(candidate, pythonPath, env),
    });
    if (result.status === 0) return candidate;
  }

  throw new Error(
    "KiCad Python was not found. Install KiCad 9 or newer, or set KICAD_PYTHON to a Python executable that can import pcbnew.",
  );
}

function buildPythonEnvironment(
  basePython: string,
  pythonPath?: string,
  sourceEnv: NodeJS.ProcessEnv = process.env,
): NodeJS.ProcessEnv {
  const kicadBin = dirname(basePython);
  const pathKey = Object.keys(sourceEnv).find((key) => key.toLowerCase() === "path") || "PATH";
  const currentPath = sourceEnv[pathKey] || "";
  const currentPythonPath = sourceEnv.PYTHONPATH || "";
  return {
    ...sourceEnv,
    [pathKey]: [kicadBin, currentPath].filter(Boolean).join(delimiter),
    PYTHONPATH: [pythonPath, currentPythonPath].filter(Boolean).join(delimiter),
  };
}

/** Redact credential-shaped values before subprocess output reaches logs. */
export function sanitizeRuntimeLog(message: string): string {
  return message
    .replace(/\b([a-z][a-z0-9+.-]*:\/\/)[^\s/@]+@/gi, "$1***@")
    .replace(
      /([?&](?:access[_-]?key|api[_-]?key|auth|password|secret|signature|token)=)[^&#\s]*/gi,
      "$1***",
    )
    .replace(/(authorization\s*[:=]\s*)(?:(?:basic|bearer)\s+)?[^\s,;]+/gi, "$1***")
    .replace(
      /\b([A-Z][A-Z0-9_]*(?:API_KEY|ACCESS_KEY|PASSWORD|SECRET|TOKEN)[A-Z0-9_]*\s*=)[^\s]*/gi,
      "$1***",
    );
}

async function runCommand(
  command: string,
  args: string[],
  env: NodeJS.ProcessEnv,
  log: RuntimeLogger,
): Promise<CommandResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      env,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let stdoutLogBuffer = "";
    let stderrLogBuffer = "";

    const logCompleteLines = (buffer: string, chunk: string): string => {
      const lines = `${buffer}${chunk}`.split(/\r?\n/);
      const remainder = lines.pop() || "";
      for (const line of lines) {
        if (line) log(sanitizeRuntimeLog(line));
      }
      return remainder;
    };
    const flushLogBuffer = (buffer: string): void => {
      if (buffer) log(sanitizeRuntimeLog(buffer));
    };
    const flushLogs = (): void => {
      flushLogBuffer(stdoutLogBuffer);
      flushLogBuffer(stderrLogBuffer);
      stdoutLogBuffer = "";
      stderrLogBuffer = "";
    };

    child.stdout?.on("data", (chunk: Buffer) => {
      const text = chunk.toString();
      stdout += text;
      stdoutLogBuffer = logCompleteLines(stdoutLogBuffer, text);
    });
    child.stderr?.on("data", (chunk: Buffer) => {
      const text = chunk.toString();
      stderr += text;
      stderrLogBuffer = logCompleteLines(stderrLogBuffer, text);
    });
    child.on("error", (error) => {
      flushLogs();
      reject(error);
    });
    child.on("close", (code) => {
      flushLogs();
      resolve({ code: code ?? 1, stdout, stderr });
    });
  });
}

function readPackageVersion(packageRoot: string): string {
  const packageJson = JSON.parse(readFileSync(join(packageRoot, "package.json"), "utf8")) as {
    version?: string;
  };
  return packageJson.version || "0.0.0";
}

function readState(statePath: string): RuntimeState | undefined {
  try {
    return JSON.parse(readFileSync(statePath, "utf8")) as RuntimeState;
  } catch {
    return undefined;
  }
}

function processIsRunning(pid: number): boolean {
  if (!Number.isSafeInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

function readLockOwner(lockPath: string): RuntimeLockOwner | undefined {
  try {
    const value = JSON.parse(readFileSync(lockPath, "utf8")) as Partial<RuntimeLockOwner>;
    if (
      Number.isSafeInteger(value.pid) &&
      typeof value.token === "string" &&
      typeof value.createdAt === "string"
    ) {
      return value as RuntimeLockOwner;
    }
  } catch {
    // The creator may still be writing the owner record; retry instead of
    // treating a temporarily incomplete lock as stale.
  }
  return undefined;
}

function removeDeadRuntimeLock(lockPath: string, expected: RuntimeLockOwner): void {
  const cleanupPath = `${lockPath}.cleanup`;
  let cleanupFd: number | undefined;
  try {
    // Serializing stale-lock cleanup prevents two waiters from deleting a new
    // owner's lock between their stale-owner check and unlink.
    cleanupFd = openSync(cleanupPath, "wx", 0o600);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") return;
    throw error;
  }

  try {
    const current = readLockOwner(lockPath);
    if (
      current?.pid === expected.pid &&
      current.token === expected.token &&
      !processIsRunning(current.pid)
    ) {
      try {
        unlinkSync(lockPath);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      }
    }
  } finally {
    closeSync(cleanupFd);
    try {
      unlinkSync(cleanupPath);
    } catch {
      // Cleanup is best-effort; the primary lock has already been handled.
    }
  }
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function releaseRuntimeLock(lockPath: string, lockFd: number, token: string): void {
  closeSync(lockFd);
  const current = readLockOwner(lockPath);
  if (current?.token !== token) return;
  try {
    unlinkSync(lockPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
}

/**
 * Serialize setup of one packaged Python runtime across concurrent MCP starts.
 * The owner record lets a later process recover a lock left by a crashed owner.
 */
export async function withRuntimeSetupLock<T>(
  lockPath: string,
  action: () => Promise<T>,
  log: RuntimeLogger = () => undefined,
  timeoutMs: number = RUNTIME_LOCK_TIMEOUT_MS,
): Promise<T> {
  const startedAt = Date.now();
  const owner: RuntimeLockOwner = {
    pid: process.pid,
    token: randomUUID(),
    createdAt: new Date().toISOString(),
  };
  let announcedWait = false;

  while (true) {
    let lockFd: number | undefined;
    try {
      lockFd = openSync(lockPath, "wx", 0o600);
      try {
        writeFileSync(lockFd, `${JSON.stringify(owner)}\n`, "utf8");
      } catch (error) {
        closeSync(lockFd);
        lockFd = undefined;
        try {
          unlinkSync(lockPath);
        } catch (cleanupError) {
          if ((cleanupError as NodeJS.ErrnoException).code !== "ENOENT") throw cleanupError;
        }
        throw error;
      }
    } catch (error) {
      if (lockFd !== undefined) {
        try {
          closeSync(lockFd);
        } catch {
          // The action cleanup may already have closed the descriptor.
        }
      }
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;

      const current = readLockOwner(lockPath);
      if (current && !processIsRunning(current.pid)) {
        removeDeadRuntimeLock(lockPath, current);
        continue;
      }

      if (Date.now() - startedAt >= timeoutMs) {
        throw new Error(
          `Timed out waiting for another KiCad MCP process to finish runtime setup (${lockPath}).`,
        );
      }
      if (!announcedWait) {
        log("Another KiCad MCP process is preparing the Python runtime; waiting for it to finish");
        announcedWait = true;
      }
      await delay(Math.min(RUNTIME_LOCK_POLL_MS, Math.max(1, timeoutMs)));
      continue;
    }

    let result: T;
    try {
      result = await action();
    } catch (error) {
      try {
        releaseRuntimeLock(lockPath, lockFd, owner.token);
      } catch (cleanupError) {
        log(
          `Could not remove the runtime setup lock after an error: ${
            cleanupError instanceof Error ? cleanupError.message : String(cleanupError)
          }`,
        );
      }
      throw error;
    }
    releaseRuntimeLock(lockPath, lockFd, owner.token);
    return result;
  }
}

function writeStateAtomically(statePath: string, state: RuntimeState): void {
  const temporaryPath = `${statePath}.${process.pid}.${randomUUID()}.tmp`;
  try {
    writeFileSync(temporaryPath, `${JSON.stringify(state, null, 2)}\n`, {
      encoding: "utf8",
      flag: "wx",
      mode: 0o600,
    });
    renameSync(temporaryPath, statePath);
  } catch (error) {
    try {
      unlinkSync(temporaryPath);
    } catch {
      // Preserve the write/rename error, which is more useful than cleanup failure.
    }
    throw error;
  }
}

export async function prepareRuntime(
  packageRoot: string,
  log: RuntimeLogger = (message) => process.stderr.write(`[kicad-mcp] ${message}\n`),
): Promise<PreparedRuntime> {
  const unlockedRequirementsPath = join(packageRoot, "requirements.txt");
  const lockedRequirementsPath = join(packageRoot, "requirements-lock.txt");
  if (!existsSync(lockedRequirementsPath)) {
    throw new Error(
      `The packaged dependency lock is missing: ${lockedRequirementsPath}. Reinstall KiCad MCP before preparing the runtime.`,
    );
  }

  const basePython = discoverKiCadPython();
  const pythonPath = deriveKiCadPythonPath(basePython);
  const runtimeHome = getRuntimeHome();
  const runtimeId = createHash("sha256").update(basePython).digest("hex").slice(0, 12);
  const venvDir = join(runtimeHome, `runtime-${runtimeId}`);
  const venvPython = join(
    venvDir,
    process.platform === "win32" ? "Scripts" : "bin",
    process.platform === "win32" ? "python.exe" : "python",
  );
  const requirementsPath = lockedRequirementsPath;
  const statePath = join(venvDir, "runtime.json");
  const lockPath = join(runtimeHome, `runtime-${runtimeId}.lock`);
  const packageVersion = readPackageVersion(packageRoot);
  const requirementsHashBuilder = createHash("sha256").update(
    readFileSync(unlockedRequirementsPath),
  );
  requirementsHashBuilder.update(readFileSync(lockedRequirementsPath));
  const requirementsHash = requirementsHashBuilder.digest("hex");
  const wantedState: RuntimeState = { packageVersion, basePython, requirementsHash };
  const env = buildPythonEnvironment(basePython, pythonPath);

  const preparedResult = (): PreparedRuntime => ({
    basePython,
    python: venvPython,
    pythonPath,
    kicadBin: dirname(basePython),
    runtimeHome,
    packageVersion,
  });
  const runtimeIsCurrent = (): boolean => {
    const currentState = readState(statePath);
    return (
      currentState?.packageVersion === wantedState.packageVersion &&
      currentState?.basePython === wantedState.basePython &&
      currentState?.requirementsHash === wantedState.requirementsHash &&
      existsSync(venvPython) &&
      pythonCanImport(venvPython, pythonPath, basePython)
    );
  };

  if (runtimeIsCurrent()) return preparedResult();

  mkdirSync(runtimeHome, { recursive: true });
  return withRuntimeSetupLock(
    lockPath,
    async () => {
      // The process that held the lock may have completed setup while we were
      // waiting, so always re-read state after acquiring it.
      if (runtimeIsCurrent()) return preparedResult();

      if (!existsSync(venvPython)) {
        log(`Creating private Python environment in ${venvDir}`);
        const createResult = await runCommand(
          basePython,
          ["-m", "venv", "--system-site-packages", venvDir],
          env,
          log,
        );
        if (createResult.code !== 0) {
          throw new Error(
            `Could not create the KiCad MCP Python environment: ${sanitizeRuntimeLog(
              createResult.stderr,
            )}`,
          );
        }
      }

      log("Installing pinned KiCad MCP Python dependencies (first launch can take a few minutes)");
      const installResult = await runCommand(
        venvPython,
        [
          "-m",
          "pip",
          "install",
          "--disable-pip-version-check",
          "--require-hashes",
          "-r",
          requirementsPath,
        ],
        env,
        log,
      );
      if (installResult.code !== 0) {
        throw new Error(
          `Could not install KiCad MCP Python dependencies: ${sanitizeRuntimeLog(
            installResult.stderr,
          )}`,
        );
      }

      if (!pythonCanImport(venvPython, pythonPath, basePython)) {
        throw new Error(
          `The runtime was installed, but ${venvPython} cannot import pcbnew or a required Python package. Run "kicad-mcp doctor" for details.`,
        );
      }

      writeStateAtomically(statePath, wantedState);
      return preparedResult();
    },
    log,
  );
}

export function applyRuntimeEnvironment(runtime: PreparedRuntime): void {
  const pathKey = Object.keys(process.env).find((key) => key.toLowerCase() === "path") || "PATH";
  process.env.KICAD_PYTHON = runtime.python;
  process.env[pathKey] = [runtime.kicadBin, process.env[pathKey] || ""]
    .filter(Boolean)
    .join(delimiter);
  process.env.PYTHONPATH = [runtime.pythonPath, process.env.PYTHONPATH]
    .filter(Boolean)
    .join(delimiter);
}

export function inspectRuntime(packageRoot: string): Record<string, unknown> {
  const runtimeHome = getRuntimeHome();
  const result: Record<string, unknown> = {
    packageVersion: readPackageVersion(packageRoot),
    platform: process.platform,
    node: process.version,
    runtimeHome,
  };

  try {
    const basePython = discoverKiCadPython();
    const pythonPath = deriveKiCadPythonPath(basePython);
    const runtimeId = createHash("sha256").update(basePython).digest("hex").slice(0, 12);
    const runtimePython = join(
      runtimeHome,
      `runtime-${runtimeId}`,
      process.platform === "win32" ? "Scripts" : "bin",
      process.platform === "win32" ? "python.exe" : "python",
    );
    result.kicadPython = basePython;
    result.kicadPythonPath = pythonPath;
    result.runtimePython = runtimePython;
    result.runtimeInstalled = existsSync(runtimePython);
    result.runtimeHealthy =
      existsSync(runtimePython) && pythonCanImport(runtimePython, pythonPath, basePython);
  } catch (error) {
    result.error = error instanceof Error ? error.message : String(error);
    result.runtimeInstalled = false;
    result.runtimeHealthy = false;
  }
  return result;
}
