/**
 * Configuration handling for KiCAD MCP server
 */

import { readFile } from "fs/promises";
import { existsSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";
import { z } from "zod";
import { logger } from "./logger.js";
import { isOperatingMode, type OperatingMode } from "./operating-mode.js";

// Get the current directory
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Default config location
const DEFAULT_CONFIG_PATH = join(dirname(__dirname), "config", "default-config.json");

const LOG_LEVEL_VALUES = ["error", "warn", "info", "debug"] as const;
const LogLevelSchema = z.enum(LOG_LEVEL_VALUES);
const OperatingModeSchema = z.enum(["readonly", "write", "manufacturing", "experimental"]);

/**
 * Server configuration schema
 */
const ConfigSchema = z.object({
  name: z.string().default("kicad-mcp-server"),
  version: z.string().default("2.8.2"),
  description: z.string().default("MCP server for KiCAD PCB design operations"),
  pythonPath: z.string().optional(),
  kicadPath: z.string().optional(),
  logLevel: LogLevelSchema.default("info"),
  logDir: z.string().optional(),
  // Keep the existing unrestricted workflow unless the user opts into a
  // narrower policy. This makes the safety change backwards-compatible.
  operatingMode: OperatingModeSchema.default("write"),
});

/**
 * Server configuration type
 */
export type Config = z.infer<typeof ConfigSchema>;

/**
 * Read the log level from the environment (KICAD_MCP_LOG_LEVEL or LOG_LEVEL),
 * normalizing "warning" -> "warn". Returns undefined when unset/invalid so the
 * file/default value is kept.
 */
function getEnvLogLevel(): Config["logLevel"] | undefined {
  for (const envName of ["KICAD_MCP_LOG_LEVEL", "LOG_LEVEL"] as const) {
    const rawLevel = process.env[envName];
    if (!rawLevel) {
      continue;
    }

    const normalized = rawLevel.trim().toLowerCase();
    const level = normalized === "warning" ? "warn" : normalized;
    const parsed = LogLevelSchema.safeParse(level);
    if (!parsed.success) {
      const acceptedValues = [...LOG_LEVEL_VALUES, "warning"].join(", ");
      logger.warn(
        `Ignoring invalid ${envName} value: ${rawLevel}. Expected one of: ${acceptedValues}`,
      );
      continue;
    }

    return parsed.data;
  }

  return undefined;
}

function getEnvOperatingMode(): OperatingMode | undefined {
  const rawMode = process.env.KICAD_MCP_OPERATING_MODE;
  if (!rawMode) return undefined;

  const mode = rawMode.trim().toLowerCase();
  if (isOperatingMode(mode)) return mode;

  logger.warn(
    `Ignoring invalid KICAD_MCP_OPERATING_MODE value: ${rawMode}. Expected one of: ${OPERATING_MODES_TEXT}`,
  );
  return undefined;
}

const OPERATING_MODES_TEXT = ["readonly", "write", "manufacturing", "experimental"].join(", ");

/**
 * Apply environment-based overrides on top of a loaded config. The env log
 * level (if set) wins over the file/default so users can control verbosity
 * without editing the config file.
 */
function applyEnvironmentOverrides(config: Config): Config {
  const envLogLevel = getEnvLogLevel();
  const envOperatingMode = getEnvOperatingMode();
  if (!envLogLevel && !envOperatingMode) {
    return config;
  }
  return {
    ...config,
    ...(envLogLevel ? { logLevel: envLogLevel } : {}),
    ...(envOperatingMode ? { operatingMode: envOperatingMode } : {}),
  };
}

/**
 * Load configuration from file
 *
 * @param configPath Path to the configuration file (optional)
 * @returns Loaded and validated configuration
 */
export async function loadConfig(configPath?: string): Promise<Config> {
  try {
    // Determine which config file to load
    const filePath = configPath || DEFAULT_CONFIG_PATH;

    // Check if file exists
    if (!existsSync(filePath)) {
      logger.warn(`Configuration file not found: ${filePath}, using defaults`);
      return applyEnvironmentOverrides(ConfigSchema.parse({}));
    }

    // Read and parse configuration
    const configData = await readFile(filePath, "utf-8");
    const config = JSON.parse(configData);

    // Validate configuration
    return applyEnvironmentOverrides(ConfigSchema.parse(config));
  } catch (error) {
    logger.error(`Error loading configuration: ${error}`);

    // Return default configuration
    return applyEnvironmentOverrides(ConfigSchema.parse({}));
  }
}
