/**
 * KiCAD MCP Server implementation
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import express from 'express';
import { spawn, ChildProcess } from 'child_process';
import { existsSync } from 'fs';
import { logger } from './logger.js';

// Import tool registration functions
import { registerProjectTools } from './tools/project.js';
import { registerBoardTools } from './tools/board.js';
import { registerComponentTools } from './tools/component.js';
import { registerRoutingTools } from './tools/routing.js';
import { registerDesignRuleTools } from './tools/design-rules.js';
import { registerExportTools } from './tools/export.js';

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
 * KiCAD MCP Server class
 */
export class KiCADMcpServer {
  private server: McpServer;
  private pythonProcess: ChildProcess | null = null;
  private kicadScriptPath: string;
  private stdioTransport!: StdioServerTransport;
  private requestQueue: Array<{ request: any, resolve: Function, reject: Function }> = [];
  private processingRequest = false;
  
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
    
    // Register all tools
    registerProjectTools(this.server, this.callKicadScript.bind(this));
    registerBoardTools(this.server, this.callKicadScript.bind(this));
    registerComponentTools(this.server, this.callKicadScript.bind(this));
    registerRoutingTools(this.server, this.callKicadScript.bind(this));
    registerDesignRuleTools(this.server, this.callKicadScript.bind(this));
    registerExportTools(this.server, this.callKicadScript.bind(this));
    
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
  }
  
  /**
   * Start the MCP server and the Python KiCAD interface
   */
  async start(): Promise<void> {
    try {
      logger.info('Starting KiCAD MCP server...');
      
      // Start the Python process for KiCAD scripting
      logger.info(`Starting Python process with script: ${this.kicadScriptPath}`);
      const pythonExe = process.env.PYTHONPATH ? 
        'C:\\Program Files\\KiCad\\9.0\\bin\\python.exe' : 'python';
      
      logger.info(`Using Python executable: ${pythonExe}`);
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
      
      // Add request to queue
      this.requestQueue.push({
        request: { command, params },
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
      
      // Set up response handling
      let responseData = '';
      
      // Clear any previous listeners
      if (this.pythonProcess?.stdout) {
        this.pythonProcess.stdout.removeAllListeners('data');
        this.pythonProcess.stdout.removeAllListeners('end');
      }
      
      // Set up new listeners
      if (this.pythonProcess?.stdout) {
        this.pythonProcess.stdout.on('data', (data: Buffer) => {
          const chunk = data.toString();
          logger.debug(`Received data chunk: ${chunk.length} bytes`);
          responseData += chunk;
          
          // Check if we have a complete response
          try {
            // Try to parse the response as JSON
            const result = JSON.parse(responseData);
            
            // If we get here, we have a valid JSON response
            logger.debug(`Completed KiCAD command: ${request.command} with result: ${result.success ? 'success' : 'failure'}`);
            
            // Reset processing flag
            this.processingRequest = false;
            
            // Process next request if any
            setTimeout(() => this.processNextRequest(), 0);
            
            // Clear listeners
            if (this.pythonProcess?.stdout) {
              this.pythonProcess.stdout.removeAllListeners('data');
              this.pythonProcess.stdout.removeAllListeners('end');
            }
            
            // Resolve the promise with the result
            resolve(result);
          } catch (e) {
            // Not a complete JSON yet, keep collecting data
          }
        });
      }
      
      // Set a timeout
      const timeout = setTimeout(() => {
        logger.error(`Command timeout: ${request.command}`);
        
        // Clear listeners
        if (this.pythonProcess?.stdout) {
          this.pythonProcess.stdout.removeAllListeners('data');
          this.pythonProcess.stdout.removeAllListeners('end');
        }
        
        // Reset processing flag
        this.processingRequest = false;
        
        // Process next request
        setTimeout(() => this.processNextRequest(), 0);
        
        // Reject the promise
        reject(new Error(`Command timeout: ${request.command}`));
      }, 30000); // 30 seconds timeout
      
      // Write the request to the Python process
      logger.debug(`Sending request: ${requestStr}`);
      this.pythonProcess?.stdin?.write(requestStr + '\n');
    } catch (error) {
      logger.error(`Error processing request: ${error}`);
      
      // Reset processing flag
      this.processingRequest = false;
      
      // Process next request
      setTimeout(() => this.processNextRequest(), 0);
      
      // Reject the promise
      reject(error);
    }
  }
}
