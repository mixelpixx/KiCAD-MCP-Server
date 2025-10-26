/**
 * KiCAD Model Context Protocol Server
 * Main entry point
 */

import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { KiCADMcpServer } from './server.js';
import { loadConfig } from './config.js';
import { logger } from './logger.js';

// Get the current directory
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

/**
 * Main function to start the KiCAD MCP server
 */
async function main() {
  try {
    // Parse command line arguments
    const args = process.argv.slice(2);
    const options = parseCommandLineArgs(args);
    
    // Load configuration
    const config = await loadConfig(options.configPath);
    
    // Path to the Python script that interfaces with KiCAD
    const kicadScriptPath = join(dirname(__dirname), 'python', 'kicad_interface.py');
    
    // Create the server
    const server = new KiCADMcpServer(
      kicadScriptPath,
      config.logLevel
    );
    
    // Start the server
    await server.start();
    
    // Setup graceful shutdown
    setupGracefulShutdown(server);
    
    logger.info('KiCAD MCP server started with STDIO transport');
    
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
    if (args[i] === '--config' && i + 1 < args.length) {
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
  // Handle termination signals
  process.on('SIGINT', async () => {
    logger.info('Received SIGINT signal. Shutting down...');
    await shutdownServer(server);
  });
  
  process.on('SIGTERM', async () => {
    logger.info('Received SIGTERM signal. Shutting down...');
    await shutdownServer(server);
  });
  
  // Handle uncaught exceptions
  process.on('uncaughtException', async (error) => {
    logger.error(`Uncaught exception: ${error}`);
    await shutdownServer(server);
  });
  
  // Handle unhandled promise rejections
  process.on('unhandledRejection', async (reason) => {
    logger.error(`Unhandled promise rejection: ${reason}`);
    await shutdownServer(server);
  });
}

/**
 * Shut down the server and exit
 */
async function shutdownServer(server: KiCADMcpServer) {
  try {
    logger.info('Shutting down KiCAD MCP server...');
    await server.stop();
    logger.info('Server shutdown complete. Exiting...');
    process.exit(0);
  } catch (error) {
    logger.error(`Error during shutdown: ${error}`);
    process.exit(1);
  }
}

// Run the main function if this file is executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error) => {
    logger.error(`Unhandled error in main: ${error}`);
    process.exit(1);
  });
}

// For testing and programmatic usage
export { KiCADMcpServer };
