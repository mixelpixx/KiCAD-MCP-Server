/**
 * Logger for KiCAD MCP server
 */

import { existsSync, mkdirSync, appendFileSync, statSync, renameSync, rmSync } from "fs";
import { join } from "path";
import * as os from "os";

// Log levels
type LogLevel = "error" | "warn" | "info" | "debug";

// Default log directory
const DEFAULT_LOG_DIR = join(os.homedir(), ".kicad-mcp", "logs");

/** Parse a non-negative integer env var, or fall back to a default. */
function envInt(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined) return fallback;
  const value = Number.parseInt(raw, 10);
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

/**
 * Logger class for KiCAD MCP server
 */
class Logger {
  private logLevel: LogLevel = "info";
  private logDir: string = DEFAULT_LOG_DIR;
  // Size cap for the per-day log files (issue #181). Same env knobs as the
  // Python side; KICAD_MCP_LOG_MAX_BYTES=0 disables rotation.
  private maxBytes: number = envInt("KICAD_MCP_LOG_MAX_BYTES", 10 * 1024 * 1024);
  private backupCount: number = envInt("KICAD_MCP_LOG_BACKUP_COUNT", 3);

  /**
   * Rotate the day's log file when it exceeds maxBytes so it can't grow
   * without bound. Best-effort — never throws (logging must not break).
   */
  private rotateIfNeeded(logFile: string): void {
    if (this.maxBytes <= 0) return;
    try {
      if (!existsSync(logFile) || statSync(logFile).size < this.maxBytes) return;
      if (this.backupCount <= 0) {
        rmSync(logFile, { force: true });
        return;
      }
      // Drop the oldest, shift .k -> .k+1, then current -> .1
      const oldest = `${logFile}.${this.backupCount}`;
      if (existsSync(oldest)) rmSync(oldest, { force: true });
      for (let i = this.backupCount - 1; i >= 1; i--) {
        const src = `${logFile}.${i}`;
        if (existsSync(src)) renameSync(src, `${logFile}.${i + 1}`);
      }
      renameSync(logFile, `${logFile}.1`);
    } catch {
      // best-effort: if rotation fails, keep logging to the existing file
    }
  }

  /**
   * Set the log level
   * @param level Log level to set
   */
  setLogLevel(level: LogLevel): void {
    this.logLevel = level;
  }

  /**
   * Set the log directory
   * @param dir Directory to store log files
   */
  setLogDir(dir: string): void {
    this.logDir = dir;

    // Ensure log directory exists
    if (!existsSync(this.logDir)) {
      mkdirSync(this.logDir, { recursive: true });
    }
  }

  /**
   * Log an error message
   * @param message Message to log
   */
  error(message: string): void {
    this.log("error", message);
  }

  /**
   * Log a warning message
   * @param message Message to log
   */
  warn(message: string): void {
    if (["error", "warn", "info", "debug"].includes(this.logLevel)) {
      this.log("warn", message);
    }
  }

  /**
   * Log an info message
   * @param message Message to log
   */
  info(message: string): void {
    if (["info", "debug"].includes(this.logLevel)) {
      this.log("info", message);
    }
  }

  /**
   * Log a debug message
   * @param message Message to log
   */
  debug(message: string): void {
    if (this.logLevel === "debug") {
      this.log("debug", message);
    }
  }

  /**
   * Log a message with the specified level
   * @param level Log level
   * @param message Message to log
   */
  private log(level: LogLevel, message: string): void {
    const now = new Date();
    const pad = (n: number, w = 2) => String(n).padStart(w, "0");
    const timestamp =
      `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ` +
      `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())},${pad(now.getMilliseconds(), 3)}`;
    const formattedMessage = `[${timestamp}] [${level.toUpperCase()}] ${message}`;

    // Log to console.error (stderr) only - stdout is reserved for MCP protocol
    // All log levels go to stderr to avoid corrupting STDIO MCP transport
    console.error(formattedMessage);

    // Log to file
    try {
      // Ensure log directory exists
      if (!existsSync(this.logDir)) {
        mkdirSync(this.logDir, { recursive: true });
      }

      const logFile = join(this.logDir, `kicad-mcp-${new Date().toISOString().split("T")[0]}.log`);
      this.rotateIfNeeded(logFile);
      appendFileSync(logFile, formattedMessage + "\n");
    } catch (error) {
      console.error(`Failed to write to log file: ${error}`);
    }
  }
}

// Create and export logger instance
export const logger = new Logger();
