import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { spawn, ChildProcess } from 'child_process';
import { existsSync } from 'fs';
import path from 'path';

// Import all tool definitions for reference
// import { registerBoardTools } from './tools/board.js';
// import { registerComponentTools } from './tools/component.js';
// import { registerRoutingTools } from './tools/routing.js';
// import { registerDesignRuleTools } from './tools/design-rules.js';
// import { registerExportTools } from './tools/export.js';
// import { registerProjectTools } from './tools/project.js';
// import { registerSchematicTools } from './tools/schematic.js';

class KiCADServer {
  private server: Server;
  private pythonProcess: ChildProcess | null = null;
  private kicadScriptPath: string;
  private requestQueue: Array<{ request: any, resolve: Function, reject: Function }> = [];
  private processingRequest = false;

  constructor() {
    // Set absolute path to the Python KiCAD interface script
    // Using a hardcoded path to avoid cwd() issues when running from Cline
    this.kicadScriptPath = 'c:/repo/KiCAD-MCP/python/kicad_interface.py';
    
    // Check if script exists
    if (!existsSync(this.kicadScriptPath)) {
      throw new Error(`KiCAD interface script not found: ${this.kicadScriptPath}`);
    }
    
    // Initialize the server
    this.server = new Server(
      {
        name: 'kicad-mcp-server',
        version: '1.0.0'
      },
      {
        capabilities: {
          tools: {
            // Empty object here, tools will be registered dynamically
          }
        }
      }
    );
    
    // Initialize handler with direct pass-through to Python KiCAD interface
    // We don't register TypeScript tools since we'll handle everything in Python

    // Register tool list handler
    this.server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: [
        // Project tools
        {
          name: 'create_project',
          description: 'Create a new KiCAD project',
          inputSchema: {
            type: 'object',
            properties: {
              projectName: { type: 'string', description: 'Name of the new project' },
              path: { type: 'string', description: 'Path where to create the project' },
              template: { type: 'string', description: 'Optional template to use' }
            },
            required: ['projectName']
          }
        },
        {
          name: 'open_project',
          description: 'Open an existing KiCAD project',
          inputSchema: {
            type: 'object',
            properties: {
              filename: { type: 'string', description: 'Path to the project file' }
            },
            required: ['filename']
          }
        },
        {
          name: 'save_project',
          description: 'Save the current KiCAD project',
          inputSchema: {
            type: 'object',
            properties: {
              filename: { type: 'string', description: 'Optional path to save to' }
            }
          }
        },
        {
          name: 'get_project_info',
          description: 'Get information about the current project',
          inputSchema: {
            type: 'object',
            properties: {}
          }
        },
        
        // Board tools
        {
          name: 'set_board_size',
          description: 'Set the size of the PCB board',
          inputSchema: {
            type: 'object',
            properties: {
              width: { type: 'number', description: 'Board width' },
              height: { type: 'number', description: 'Board height' },
              unit: { type: 'string', description: 'Unit of measurement (mm or inch)' }
            },
            required: ['width', 'height']
          }
        },
        {
          name: 'add_board_outline',
          description: 'Add a board outline to the PCB',
          inputSchema: {
            type: 'object',
            properties: {
              shape: { type: 'string', description: 'Shape of outline (rectangle, circle, polygon, rounded_rectangle)' },
              width: { type: 'number', description: 'Width for rectangle shapes' },
              height: { type: 'number', description: 'Height for rectangle shapes' },
              radius: { type: 'number', description: 'Radius for circle shapes' },
              cornerRadius: { type: 'number', description: 'Corner radius for rounded rectangles' },
              points: { type: 'array', description: 'Array of points for polygon shapes' },
              centerX: { type: 'number', description: 'X coordinate of center' },
              centerY: { type: 'number', description: 'Y coordinate of center' },
              unit: { type: 'string', description: 'Unit of measurement (mm or inch)' }
            }
          }
        },
        
        // Component tools
        {
          name: 'place_component',
          description: 'Place a component on the PCB',
          inputSchema: {
            type: 'object',
            properties: {
              componentId: { type: 'string', description: 'Component ID/footprint to place' },
              position: { type: 'object', description: 'Position coordinates' },
              reference: { type: 'string', description: 'Component reference designator' },
              value: { type: 'string', description: 'Component value' },
              rotation: { type: 'number', description: 'Rotation angle in degrees' },
              layer: { type: 'string', description: 'Layer to place component on' }
            },
            required: ['componentId', 'position']
          }
        },
        
        // Routing tools
        {
          name: 'add_net',
          description: 'Add a new net to the PCB',
          inputSchema: {
            type: 'object',
            properties: {
              name: { type: 'string', description: 'Net name' },
              class: { type: 'string', description: 'Net class' }
            },
            required: ['name']
          }
        },
        {
          name: 'route_trace',
          description: 'Route a trace between two points or pads',
          inputSchema: {
            type: 'object',
            properties: {
              start: { type: 'object', description: 'Start point or pad' },
              end: { type: 'object', description: 'End point or pad' },
              layer: { type: 'string', description: 'Layer to route on' },
              width: { type: 'number', description: 'Track width' },
              net: { type: 'string', description: 'Net name' }
            },
            required: ['start', 'end']
          }
        },
        
        // Schematic tools
        {
          name: 'create_schematic',
          description: 'Create a new KiCAD schematic',
          inputSchema: {
            type: 'object',
            properties: {
              projectName: { type: 'string', description: 'Name of the schematic project' },
              path: { type: 'string', description: 'Path where to create the schematic file' },
              metadata: { type: 'object', description: 'Optional metadata for the schematic' }
            },
            required: ['projectName']
          }
        },
        {
          name: 'load_schematic',
          description: 'Load an existing KiCAD schematic',
          inputSchema: {
            type: 'object',
            properties: {
              filename: { type: 'string', description: 'Path to the schematic file to load' }
            },
            required: ['filename']
          }
        },
        {
          name: 'add_schematic_component',
          description: 'Add a component to a KiCAD schematic',
          inputSchema: {
            type: 'object',
            properties: {
              schematicPath: { type: 'string', description: 'Path to the schematic file' },
              component: { 
                type: 'object', 
                description: 'Component definition',
                properties: {
                  type: { type: 'string', description: 'Component type (e.g., R, C, LED)' },
                  reference: { type: 'string', description: 'Reference designator (e.g., R1, C2)' },
                  value: { type: 'string', description: 'Component value (e.g., 10k, 0.1uF)' },
                  library: { type: 'string', description: 'Symbol library name' },
                  x: { type: 'number', description: 'X position in schematic' },
                  y: { type: 'number', description: 'Y position in schematic' },
                  rotation: { type: 'number', description: 'Rotation angle in degrees' },
                  properties: { type: 'object', description: 'Additional properties' }
                },
                required: ['type', 'reference']
              }
            },
            required: ['schematicPath', 'component']
          }
        },
        {
          name: 'add_schematic_wire',
          description: 'Add a wire connection to a KiCAD schematic',
          inputSchema: {
            type: 'object',
            properties: {
              schematicPath: { type: 'string', description: 'Path to the schematic file' },
              startPoint: { 
                type: 'array', 
                description: 'Starting point coordinates [x, y]',
                items: { type: 'number' },
                minItems: 2,
                maxItems: 2
              },
              endPoint: { 
                type: 'array', 
                description: 'Ending point coordinates [x, y]',
                items: { type: 'number' },
                minItems: 2,
                maxItems: 2
              }
            },
            required: ['schematicPath', 'startPoint', 'endPoint']
          }
        },
        {
          name: 'list_schematic_libraries',
          description: 'List available KiCAD symbol libraries',
          inputSchema: {
            type: 'object',
            properties: {
              searchPaths: { 
                type: 'array', 
                description: 'Optional search paths for libraries',
                items: { type: 'string' }
              }
            }
          }
        },
        {
          name: 'export_schematic_pdf',
          description: 'Export a KiCAD schematic to PDF',
          inputSchema: {
            type: 'object',
            properties: {
              schematicPath: { type: 'string', description: 'Path to the schematic file' },
              outputPath: { type: 'string', description: 'Path for the output PDF file' }
            },
            required: ['schematicPath', 'outputPath']
          }
        }
      ]
    }));

    // Register tool call handler
    this.server.setRequestHandler(CallToolRequestSchema, async (request: any) => {
      const toolName = request.params.name;
      const args = request.params.arguments || {};
      
      // Pass all commands directly to KiCAD Python interface
      try {
        return await this.callKicadScript(toolName, args);
      } catch (error) {
        console.error(`Error executing tool ${toolName}:`, error);
        throw new Error(`Unknown tool: ${toolName}`);
      }
    });
  }

  async start() {
    try {
      console.error('Starting KiCAD MCP server...');
      
      // Start the Python process for KiCAD scripting
      console.error(`Starting Python process with script: ${this.kicadScriptPath}`);
      const pythonExe = 'C:\\Program Files\\KiCad\\9.0\\bin\\python.exe';
      
      console.error(`Using Python executable: ${pythonExe}`);
      this.pythonProcess = spawn(pythonExe, [this.kicadScriptPath], {
        stdio: ['pipe', 'pipe', 'pipe'],
        env: {
          ...process.env,
          PYTHONPATH: 'C:/Program Files/KiCad/9.0/lib/python3/dist-packages'
        }
      });
      
      // Listen for process exit
      this.pythonProcess.on('exit', (code, signal) => {
        console.error(`Python process exited with code ${code} and signal ${signal}`);
        this.pythonProcess = null;
      });
      
      // Listen for process errors
      this.pythonProcess.on('error', (err) => {
        console.error(`Python process error: ${err.message}`);
      });
      
      // Set up error logging for stderr
      if (this.pythonProcess.stderr) {
        this.pythonProcess.stderr.on('data', (data: Buffer) => {
          console.error(`Python stderr: ${data.toString()}`);
        });
      }
      
      // Connect to transport
      const transport = new StdioServerTransport();
      await this.server.connect(transport);
      console.error('KiCAD MCP server running');
      
      // Keep the process running
      process.on('SIGINT', () => {
        if (this.pythonProcess) {
          this.pythonProcess.kill();
        }
        this.server.close().catch(console.error);
        process.exit(0);
      });
      
    } catch (error: unknown) {
      if (error instanceof Error) {
        console.error('Failed to start MCP server:', error.message);
      } else {
        console.error('Failed to start MCP server: Unknown error');
      }
      process.exit(1);
    }
  }

  private async callKicadScript(command: string, params: any): Promise<any> {
    return new Promise((resolve, reject) => {
      // Check if Python process is running
      if (!this.pythonProcess) {
        console.error('Python process is not running');
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
      console.error(`Processing KiCAD command: ${request.command}`);
      
      // Format the command and parameters as JSON
      const requestStr = JSON.stringify(request);
      
      // Set up response handling
      let responseData = '';
      
      // Clear any previous listeners
      if (this.pythonProcess?.stdout) {
        this.pythonProcess.stdout.removeAllListeners('data');
      }
      
      // Set up new listeners
      if (this.pythonProcess?.stdout) {
        this.pythonProcess.stdout.on('data', (data: Buffer) => {
          const chunk = data.toString();
          console.error(`Received data chunk: ${chunk.length} bytes`);
          responseData += chunk;
          
          // Check if we have a complete response
          try {
            // Try to parse the response as JSON
            const result = JSON.parse(responseData);
            
            // If we get here, we have a valid JSON response
            console.error(`Completed KiCAD command: ${request.command} with result: ${JSON.stringify(result)}`);
            
            // Reset processing flag
            this.processingRequest = false;
            
            // Process next request if any
            setTimeout(() => this.processNextRequest(), 0);
            
            // Clear listeners
            if (this.pythonProcess?.stdout) {
              this.pythonProcess.stdout.removeAllListeners('data');
            }
            
            // Resolve with the expected MCP tool response format
            if (result.success) {
              resolve({
                content: [
                  {
                    type: 'text',
                    text: JSON.stringify(result, null, 2)
                  }
                ]
              });
            } else {
              resolve({
                content: [
                  {
                    type: 'text',
                    text: result.errorDetails || result.message || 'Unknown error'
                  }
                ],
                isError: true
              });
            }
          } catch (e) {
            // Not a complete JSON yet, keep collecting data
          }
        });
      }
      
      // Set a timeout
      const timeout = setTimeout(() => {
        console.error(`Command timeout: ${request.command}`);
        
        // Clear listeners
        if (this.pythonProcess?.stdout) {
          this.pythonProcess.stdout.removeAllListeners('data');
        }
        
        // Reset processing flag
        this.processingRequest = false;
        
        // Process next request
        setTimeout(() => this.processNextRequest(), 0);
        
        // Reject the promise
        reject(new Error(`Command timeout: ${request.command}`));
      }, 30000); // 30 seconds timeout
      
      // Write the request to the Python process
      console.error(`Sending request: ${requestStr}`);
      this.pythonProcess?.stdin?.write(requestStr + '\n');
    } catch (error) {
      console.error(`Error processing request: ${error}`);
      
      // Reset processing flag
      this.processingRequest = false;
      
      // Process next request
      setTimeout(() => this.processNextRequest(), 0);
      
      // Reject the promise
      reject(error);
    }
  }
}

// Start the server
const server = new KiCADServer();
server.start().catch(console.error);
