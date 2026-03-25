/**
 * KiCAD PCB Toolbox — focused MCP server for board layout
 *
 * Tools: board, component, routing, DRC, export, freerouting, UI, project (~35 tools)
 *
 * Configure in Claude settings:
 *   kicad-pcb:
 *     command: node
 *     args: [path/to/dist/pcb.js]
 */

import { join, dirname } from "path";
import { fileURLToPath } from "url";
import { KiCADMcpServer } from "./server.js";
import { loadConfig } from "./config.js";
import { logger } from "./logger.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

async function main() {
  try {
    const args = process.argv.slice(2);
    let configPath: string | undefined;
    for (let i = 0; i < args.length; i++) {
      if (args[i] === "--config" && i + 1 < args.length) {
        configPath = args[++i];
      }
    }

    const config = await loadConfig(configPath);
    const kicadScriptPath = join(dirname(__dirname), "python", "kicad_interface.py");

    const server = new KiCADMcpServer(kicadScriptPath, config.logLevel, "pcb");
    await server.start();

    process.on("SIGINT", async () => { await server.stop(); process.exit(0); });
    process.on("SIGTERM", async () => { await server.stop(); process.exit(0); });

    logger.info("KiCAD PCB toolbox started");
  } catch (error) {
    logger.error(`Failed to start KiCAD PCB toolbox: ${error}`);
    process.exit(1);
  }
}

main().catch((error) => {
  console.error(`Unhandled error: ${error}`);
  process.exit(1);
});
