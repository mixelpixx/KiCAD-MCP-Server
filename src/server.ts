/**
 * KiCAD MCP Server implementation
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import express from 'express';
import { spawn, exec, execSync, ChildProcess } from 'child_process';
import { existsSync } from 'fs';
import { join, dirname } from 'path';
import { logger } from './logger.js';

// Import tool registration functions
import { registerProjectTools } from './tools/project.js';
import { registerBoardTools } from './tools/board.js';
import { registerComponentTools } from './tools/component.js';
import { registerRoutingTools } from './tools/routing.js';
import { registerDesignRuleTools } from './tools/design-rules.js';
import { registerExportTools } from './tools/export.js';
import { registerSchematicTools } from './tools/schematic.js';
import { registerLibraryTools } from './tools/library.js';
import { registerSymbolLibraryTools } from './tools/library-symbol.js';
import { registerJLCPCBApiTools } from './tools/jlcpcb-api.js';
import { registerUITools } from './tools/ui.js';
import { registerRouterTools } from './tools/router.js';

// Import resource registration functions
import { registerProjectResources } from './resources/project.js';
import { registerBoardResources } from './resources/board.js';
import { registerComponentResources } from './resources/component.js';
import { registerLibraryResources } from './resources/library.js';

// Import prompt registration functions
import { registerComponentPrompts } from './prompts/component.js';
import { registerRoutingPrompts } from './prompts/routing.js';
import { registerDesignPrompts } from './prompts/design.js';

/**
 * Find the Python executable to use
 * Prioritizes virtual environment if available, falls back to system Python
 */
function findPythonExecutable(scriptPath: string): string {
  const isWindows = process.platform === 'win32';
  const isMac = process.platform === 'darwin';
  const isLinux = !isWindows && !isMac;

  // Get the project root (parent of the python/ directory)
  const projectRoot = dirname(dirname(scriptPath));

  // Check for virtual environment
  const venvPaths = [
    join(projectRoot, 'venv', isWindows ? 'Scripts' : 'bin', isWindows ? 'python.exe' : 'python'),
    join(projectRoot, '.venv', isWindows ? 'Scripts' : 'bin', isWindows ? 'python.exe' : 'python'),
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
  if (isWindows && process.env.PYTHONPATH?.includes('KiCad')) {
    // Windows: Try KiCAD's bundled Python
    const kicadPython = 'C:\\Program Files\\KiCad\\9.0\\bin\\python.exe';
    if (existsSync(kicadPython)) {
      logger.info(`Found KiCAD bundled Python at: ${kicadPython}`);
      return kicadPython;
    }
  } else if (isMac) {
    // macOS: Try KiCAD's bundled Python (check multiple versions and locations)
    const kicadPythonVersions = ['3.9', '3.10', '3.11', '3.12', '3.13'];

    // Standard KiCAD installation paths
    const kicadAppPaths = [
      '/Applications/KiCad/KiCad.app',
      '/Applications/KiCAD/KiCad.app',  // Alternative capitalization
      `${process.env.HOME}/Applications/KiCad/KiCad.app`,  // User Applications folder
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
      '/opt/homebrew/bin/python3',      // Apple Silicon
      '/usr/local/bin/python3',          // Intel Mac
      '/opt/homebrew/bin/python3.12',
      '/opt/homebrew/bin/python3.11',
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
      '/usr/lib/kicad/bin/python3',
      '/usr/local/lib/kicad/bin/python3',
      '/opt/kicad/bin/python3',
    ];

    for (const path of linuxKicadPaths) {
      if (existsSync(path)) {
        logger.info(`Found KiCAD bundled Python at: ${path}`);
        return path;
      }
    }

    // Resolve system python3 to full path using 'which'
    try {
      const result = execSync('which python3', { encoding: 'utf-8' }).trim();
      if (result && existsSync(result)) {
        logger.info(`Resolved system Python via which: ${result}`);
        return result;
      }
    } catch (e) {
      logger.warn('Failed to resolve python3 via which command');
    }

    // Fallback to common system paths
    const systemPaths = ['/usr/bin/python3', '/bin/python3'];
    for (const path of systemPaths) {
      if (existsSync(path)) {
        logger.info(`Found system Python at: ${path}`);
        return path;
      }
    }
  }

  // Default to system Python (last resort)
  logger.info('Using system Python (no venv found)');
  return isWindows ? 'python.exe' : 'python3';
}

/**
 * KiCAD MCP Server class
 */
export class KiCADMcpServer {
  private server: McpServer;
  private pythonProcess: ChildProcess | null = null;
  private kicadScriptPath: string;
  private stdioTransport!: StdioServerTransport;
  private requestQueue: Array<{ request: any, resolve: Function, reject: Function }> = [];
  private processingRequest = false;
  private responseBuffer: string = '';
  private currentRequestHandler: { resolve: Function, reject: Function, timeoutHandle: NodeJS.Timeout } | null = null;
  
  /**
   * Constructor for the KiCAD MCP Server
   * @param kicadScriptPath Path to the Python KiCAD interface script
   * @param logLevel Log level for the server
   */
  constructor(
    kicadScriptPath: string,
    logLevel: 'error' | 'warn' | 'info' | 'debug' = 'info'
  ) {
    // Set up the logger
    logger.setLogLevel(logLevel);
    
    // Check if KiCAD script exists
    this.kicadScriptPath = kicadScriptPath;
    if (!existsSync(this.kicadScriptPath)) {
      throw new Error(`KiCAD interface script not found: ${this.kicadScriptPath}`);
    }
    
    // Initialize the MCP server
    this.server = new McpServer({
      name: 'kicad-mcp-server',
      version: '1.0.0',
      description: 'MCP server for KiCAD PCB design operations'
    });
    
    // Initialize STDIO transport
    this.stdioTransport = new StdioServerTransport();
    logger.info('Using STDIO transport for local communication');
    
    // Register tools, resources, and prompts
    this.registerAll();
  }
  
  /**
   * Register all tools, resources, and prompts
   */
  private registerAll(): void {
    logger.info('Registering KiCAD tools, resources, and prompts...');

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
    registerJLCPCBApiTools(this.server, this.callKicadScript.bind(this));
    registerUITools(this.server, this.callKicadScript.bind(this));

    // Register all resources
    registerProjectResources(this.server, this.callKicadScript.bind(this));
    registerBoardResources(this.server, this.callKicadScript.bind(this));
    registerComponentResources(this.server, this.callKicadScript.bind(this));
    registerLibraryResources(this.server, this.callKicadScript.bind(this));

    // Register all prompts
    registerComponentPrompts(this.server);
    registerRoutingPrompts(this.server);
    registerDesignPrompts(this.server);

    logger.info('All KiCAD tools, resources, and prompts registered');
    logger.info('Router pattern enabled: 4 router tools + direct tools for discovery');
  }
  
  /**
   * Validate prerequisites before starting the server
   */
  private async validatePrerequisites(pythonExe: string): Promise<boolean> {
    const isWindows = process.platform === 'win32';
    const isLinux = process.platform !== 'win32' && process.platform !== 'darwin';
    const errors: string[] = [];

    // Check if Python executable exists (for absolute paths) or is executable (for commands)
    const isAbsolutePath = pythonExe.startsWith('/') || pythonExe.startsWith('C:') || pythonExe.startsWith('\\');

    if (isAbsolutePath) {
      // Absolute path: use existsSync
      if (!existsSync(pythonExe)) {
        errors.push(`Python executable not found: ${pythonExe}`);

        if (isWindows) {
          errors.push('Windows: Install KiCAD 9.0+ from https://www.kicad.org/download/windows/');
          errors.push('Or run: .\\setup-windows.ps1 for automatic configuration');
        } else if (isLinux) {
          errors.push('Linux: Install KiCAD 9.0+ or set KICAD_PYTHON environment variable');
          errors.push('Set KICAD_PYTHON to specify a custom Python path');
        }
      }
    } else {
      // Command name: verify it's executable via --version test
      logger.info(`Validating command-based Python executable: ${pythonExe}`);
      try {
        const { stdout } = await new Promise<{stdout: string, stderr: string}>((resolve, reject) => {
          exec(`"${pythonExe}" --version`, {
            timeout: 3000,
            env: { ...process.env }
          }, (error: any, stdout: string, stderr: string) => {
            if (error) {
              reject(error);
            } else {
              resolve({ stdout, stderr });
            }
          });
        });

        logger.info(`Python version check passed: ${stdout.trim()}`);
      } catch (error: any) {
        errors.push(`Python executable not found in PATH: ${pythonExe}`);
        errors.push(`Error: ${error.message}`);
        errors.push('Set KICAD_PYTHON environment variable to specify full path');

        if (isLinux) {
          errors.push('');
          errors.push('Linux troubleshooting:');
          errors.push('1. Check if python3 is installed: which python3');
          errors.push('2. Install KiCAD: sudo apt install kicad (Ubuntu/Debian)');
          errors.push('3. Set KICAD_PYTHON=/usr/bin/python3 in your MCP config');
        }
      }
    }

    // Check if kicad_interface.py exists
    if (!existsSync(this.kicadScriptPath)) {
      errors.push(`KiCAD interface script not found: ${this.kicadScriptPath}`);
    }

    // Check if dist/index.js exists (if running from compiled code)
    const distPath = join(dirname(dirname(this.kicadScriptPath)), 'dist', 'index.js');
    if (!existsSync(distPath)) {
      errors.push('Project not built. Run: npm run build');
    }

    // Try to test pcbnew import (quick validation)
    if (existsSync(pythonExe) && existsSync(this.kicadScriptPath)) {
      logger.info('Validating pcbnew module access...');

      const testCommand = `"${pythonExe}" -c "import pcbnew; print('OK')"`;

      try {
        const { stdout, stderr } = await new Promise<{stdout: string, stderr: string}>((resolve, reject) => {
          exec(testCommand, {
            timeout: 5000,
            env: { ...process.env }
          }, (error: any, stdout: string, stderr: string) => {
            if (error) {
              reject(error);
            } else {
              resolve({ stdout, stderr });
            }
          });
        });

        if (!stdout.includes('OK')) {
          errors.push('pcbnew module import test failed');
          errors.push(`Output: ${stdout}`);
          errors.push(`Errors: ${stderr}`);

          if (isWindows) {
            errors.push('');
            errors.push('Windows troubleshooting:');
            errors.push('1. Set PYTHONPATH=C:\\Program Files\\KiCad\\9.0\\lib\\python3\\dist-packages');
            errors.push('2. Test: "C:\\Program Files\\KiCad\\9.0\\bin\\python.exe" -c "import pcbnew"');
            errors.push('3. Run: .\\setup-windows.ps1 for automatic fix');
            errors.push('4. See: docs/WINDOWS_TROUBLESHOOTING.md');
          }
        } else {
          logger.info('✓ pcbnew module validated successfully');
        }
      } catch (error: any) {
        errors.push(`pcbnew validation failed: ${error.message}`);

        if (isWindows) {
          errors.push('');
          errors.push('This usually means:');
          errors.push('- KiCAD is not installed');
          errors.push('- PYTHONPATH is incorrect');
          errors.push('- Python cannot find pcbnew module');
          errors.push('');
          errors.push('Quick fix: Run .\\setup-windows.ps1');
        }
      }
    }

    // Log all errors
    if (errors.length > 0) {
      logger.error('='.repeat(70));
      logger.error('STARTUP VALIDATION FAILED');
      logger.error('='.repeat(70));
      errors.forEach(err => logger.error(err));
      logger.error('='.repeat(70));

      // Also write to stderr for Claude Desktop to capture
      process.stderr.write('\n' + '='.repeat(70) + '\n');
      process.stderr.write('KiCAD MCP Server - Startup Validation Failed\n');
      process.stderr.write('='.repeat(70) + '\n');
      errors.forEach(err => process.stderr.write(err + '\n'));
      process.stderr.write('='.repeat(70) + '\n\n');

      return false;
    }

    return true;
  }

  /**
   * Start the MCP server and the Python KiCAD interface
   */
  async start(): Promise<void> {
    try {
      logger.info('Starting KiCAD MCP server...');

      // Start the Python process for KiCAD scripting
      logger.info(`Starting Python process with script: ${this.kicadScriptPath}`);
      const pythonExe = findPythonExecutable(this.kicadScriptPath);

      logger.info(`Using Python executable: ${pythonExe}`);

      // Validate prerequisites
      const isValid = await this.validatePrerequisites(pythonExe);
      if (!isValid) {
        throw new Error('Prerequisites validation failed. See logs above for details.');
      }
      this.pythonProcess = spawn(pythonExe, [this.kicadScriptPath], {
        stdio: ['pipe', 'pipe', 'pipe'],
        env: {
          ...process.env,
          PYTHONPATH: process.env.PYTHONPATH || 'C:/Program Files/KiCad/9.0/lib/python3/dist-packages'
        }
      });
      
      // Listen for process exit
      this.pythonProcess.on('exit', (code, signal) => {
        logger.warn(`Python process exited with code ${code} and signal ${signal}`);
        this.pythonProcess = null;
      });
      
      // Listen for process errors
      this.pythonProcess.on('error', (err) => {
        logger.error(`Python process error: ${err.message}`);
      });
      
      // Set up error logging for stderr
      if (this.pythonProcess.stderr) {
        this.pythonProcess.stderr.on('data', (data: Buffer) => {
          logger.error(`Python stderr: ${data.toString()}`);
        });
      }

      // Set up persistent stdout handler (instead of adding/removing per request)
      if (this.pythonProcess.stdout) {
        this.pythonProcess.stdout.on('data', (data: Buffer) => {
          this.handlePythonResponse(data);
        });
      }

      // Connect server to STDIO transport
      logger.info('Connecting MCP server to STDIO transport...');
      try {
        await this.server.connect(this.stdioTransport);
        logger.info('Successfully connected to STDIO transport');
      } catch (error) {
        logger.error(`Failed to connect to STDIO transport: ${error}`);
        throw error;
      }
      
      // Write a ready message to stderr (for debugging)
      process.stderr.write('KiCAD MCP SERVER READY\n');
      
      logger.info('KiCAD MCP server started and ready');
    } catch (error) {
      logger.error(`Failed to start KiCAD MCP server: ${error}`);
      throw error;
    }
  }
  
  /**
   * Stop the MCP server and clean up resources
   */
  async stop(): Promise<void> {
    logger.info('Stopping KiCAD MCP server...');
    
    // Kill the Python process if it's running
    if (this.pythonProcess) {
      this.pythonProcess.kill();
      this.pythonProcess = null;
    }
    
    logger.info('KiCAD MCP server stopped');
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
        logger.error('Python process is not running');
        reject(new Error("Python process for KiCAD scripting is not running"));
        return;
      }

      // Determine timeout based on command type
      // DRC and export operations need longer timeouts for large boards
      let commandTimeout = 30000; // Default 30 seconds
      const longRunningCommands = ['run_drc', 'export_gerber', 'export_pdf', 'export_3d', 'save_project', 'refill_zones', 'delete_all_traces'];
      if (longRunningCommands.includes(command)) {
        commandTimeout = 600000; // 10 minutes for long operations
        logger.info(`Using extended timeout (${commandTimeout/1000}s) for command: ${command}`);
      }

      // Add request to queue with timeout info
      this.requestQueue.push({
        request: { command, params, timeout: commandTimeout },
        resolve,
        reject
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
   * Try to parse a complete JSON response from the buffer
   */
  private tryParseResponse(): void {
    if (!this.currentRequestHandler) {
      // No pending request, clear buffer if it has data (shouldn't happen)
      if (this.responseBuffer.trim()) {
        logger.warn(`Received data with no pending request: ${this.responseBuffer.substring(0, 100)}...`);
        this.responseBuffer = '';
      }
      return;
    }

    try {
      // Try to parse the response as JSON
      const result = JSON.parse(this.responseBuffer);

      // If we get here, we have a valid JSON response
      logger.debug(`Completed KiCAD command with result: ${result.success ? 'success' : 'failure'}`);

      // Clear the timeout since we got a response
      if (this.currentRequestHandler.timeoutHandle) {
        clearTimeout(this.currentRequestHandler.timeoutHandle);
      }

      // Get the handler before clearing
      const handler = this.currentRequestHandler;

      // Clear state
      this.responseBuffer = '';
      this.currentRequestHandler = null;
      this.processingRequest = false;

      // Resolve the promise with the result
      handler.resolve(result);

      // Process next request if any
      setTimeout(() => this.processNextRequest(), 0);

    } catch (e) {
      // Not a complete JSON yet, keep collecting data
      // This is normal for large responses that come in chunks
    }
  }

  /**
   * Process the next request in the queue
   */
  private processNextRequest(): void {
    // If no more requests or already processing, return
    if (this.requestQueue.length === 0 || this.processingRequest) {
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

      // Clear response buffer for new request
      this.responseBuffer = '';

      // Set a timeout (use command-specific timeout or default)
      const timeoutDuration = request.timeout || 30000;
      const timeoutHandle = setTimeout(() => {
        logger.error(`Command timeout after ${timeoutDuration/1000}s: ${request.command}`);
        logger.error(`Buffer contents: ${this.responseBuffer.substring(0, 200)}...`);

        // Clear state
        this.responseBuffer = '';
        this.currentRequestHandler = null;
        this.processingRequest = false;

        // Reject the promise
        reject(new Error(`Command timeout after ${timeoutDuration/1000}s: ${request.command}`));

        // Process next request
        setTimeout(() => this.processNextRequest(), 0);
      }, timeoutDuration);

      // Store the current request handler
      this.currentRequestHandler = { resolve, reject, timeoutHandle };

      // Write the request to the Python process
      logger.debug(`Sending request: ${requestStr}`);
      this.pythonProcess?.stdin?.write(requestStr + '\n');
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
