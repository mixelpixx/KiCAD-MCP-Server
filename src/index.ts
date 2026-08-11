/**
 * KiCAD Model Context Protocol Server
 * Main entry point
 */

import { join, dirname, resolve } from "path";
import { fileURLToPath, pathToFileURL } from "url";
import { KiCADMcpServer } from "./server.js";
import { loadConfig } from "./config.js";
import { logger } from "./logger.js";

// Get the current directory
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

/**
 * Main function to start the KiCAD MCP server
 */
export interface StartKiCadMcpOptions {
  configPath?: string;
  prepareBackend?: () => Promise<void>;
}

export async function startKiCadMcpServer(
  options: StartKiCadMcpOptions = {},
): Promise<KiCADMcpServer> {
  const config = await loadConfig(options.configPath);
  const kicadScriptPath = join(dirname(__dirname), "python", "kicad_interface.py");
  const server = new KiCADMcpServer(kicadScriptPath, config);

  // start() attaches MCP stdio synchronously and initializes KiCad in the
  // background, so clients can discover the server during a slow first run.
  await server.start(options.prepareBackend);
  setupGracefulShutdown(server);
  logger.info("KiCad MCP server started with dual-era STDIO transport");
  return server;
}

async function main(): Promise<void> {
  try {
    // Parse command line arguments
    const args = process.argv.slice(2);
    const options = parseCommandLineArgs(args);

    await startKiCadMcpServer({ configPath: options.configPath });
  } catch (error) {
    logger.error(`Failed to start KiCAD MCP server: ${error}`);
    process.exit(1);
  }
}

/**
 * Parse command line arguments
 */
function parseCommandLineArgs(args: string[]) {
  let configPath = undefined;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--config" && i + 1 < args.length) {
      configPath = args[i + 1];
      i++;
    }
  }

  return { configPath };
}

/**
 * Setup graceful shutdown handlers
 */
function setupGracefulShutdown(server: KiCADMcpServer) {
  let shuttingDown = false;
  const shutdownOnce = async (exitCode: number) => {
    if (shuttingDown) return;
    shuttingDown = true;
    await shutdownServer(server, exitCode);
  };

  // Handle stdin close (EOF) when parent process exits
  process.stdin.on("close", async () => {
    logger.info("process.stdin closed. Shutting down...");
    await shutdownOnce(0);
  });

  // Handle termination signals
  process.on("SIGINT", async () => {
    logger.info("Received SIGINT signal. Shutting down...");
    await shutdownOnce(0);
  });

  process.on("SIGTERM", async () => {
    logger.info("Received SIGTERM signal. Shutting down...");
    await shutdownOnce(0);
  });

  // Handle uncaught exceptions
  process.on("uncaughtException", async (error) => {
    logger.error(`Uncaught exception: ${error}`);
    await shutdownOnce(1);
  });

  // Handle unhandled promise rejections
  process.on("unhandledRejection", async (reason) => {
    logger.error(`Unhandled promise rejection: ${reason}`);
    await shutdownOnce(1);
  });
}

/**
 * Shut down the server and exit
 */
async function shutdownServer(server: KiCADMcpServer, exitCode: number) {
  try {
    logger.info("Shutting down KiCAD MCP server...");
    await server.stop();
    logger.info("Server shutdown complete. Exiting...");
    process.exit(exitCode);
  } catch (error) {
    logger.error(`Error during shutdown: ${error}`);
    process.exit(1);
  }
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : undefined;
if (invokedPath === import.meta.url) {
  void main().catch((error) => {
    process.stderr.write(`Unhandled error in main: ${String(error)}\n`);
    process.exit(1);
  });
}

// For testing and programmatic usage
export { KiCADMcpServer };
