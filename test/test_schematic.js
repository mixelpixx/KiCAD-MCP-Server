import { spawn } from 'child_process';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

// Get current file directory (ESM equivalent of __dirname)
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Test script for the schematic generation functionality
 * 
 * This script tests the KiCAD MCP server's schematic generation capabilities by:
 * 1. Creating a new schematic
 * 2. Adding components (resistors, capacitors)
 * 3. Adding connections between them
 * 4. Exporting the schematic to PDF
 */

// Directory for test outputs
const TEST_OUTPUT_DIR = path.join(__dirname, 'schematic_test_output');
if (!fs.existsSync(TEST_OUTPUT_DIR)) {
    fs.mkdirSync(TEST_OUTPUT_DIR, { recursive: true });
}

// Function to send a command to the KiCAD MCP server
function sendCommand(serverProcess, command, params) {
    return new Promise((resolve, reject) => {
        // Create request object
        const request = {
            command,
            params
        };
        
        // Convert to JSON and add newline
        const requestStr = JSON.stringify(request) + '\n';
        
        // Write to stdin of server process
        console.log(`Sending request to server: ${requestStr}`);
        serverProcess.stdin.write(requestStr);
        
// Set up response handler
        let responseData = '';
        const responseHandler = (data) => {
            const chunk = data.toString();
            console.log(`Received data: ${chunk}`);
            responseData += chunk;
            try {
                // Try to parse as JSON
                const response = JSON.parse(responseData);
                // Got a complete response
                console.log(`Parsed complete response: ${JSON.stringify(response)}`);
                serverProcess.stdout.removeListener('data', responseHandler);
                resolve(response);
            } catch (e) {
                // Not complete JSON yet, keep collecting
                console.log(`JSON parsing failed, continuing to collect data: ${e.message}`);
            }
        };
        
        // Set a timeout to prevent hanging indefinitely
        const timeoutId = setTimeout(() => {
            console.log("Command timeout after 10 seconds");
            serverProcess.stdout.removeListener('data', responseHandler);
            resolve({ 
              success: false, 
              message: "Timeout waiting for response from server"
            });
        }, 10000); // 10 second timeout
        
        // Listen for response
        serverProcess.stdout.on('data', responseHandler);
        
        // Handle errors
        serverProcess.stderr.on('data', (data) => {
            console.error(`Server stderr: ${data.toString()}`);
        });
    });
}

async function runTest() {
    console.log('\n=== TESTING SCHEMATIC GENERATION ===\n');
    
    // Start the KiCAD MCP server
    console.log('Starting KiCAD MCP server...');
    // Use shell: true to ensure proper command execution in Windows
    const serverProcess = spawn('node', ['dist/kicad-server.js'], {
        stdio: ['pipe', 'pipe', 'pipe'],
        shell: true
    });
    
    // Log server startup messages
    serverProcess.stderr.on('data', (data) => {
        console.log(`Server startup: ${data.toString()}`);
    });
    
    // Give server time to start
    console.log('Waiting for server to start...');
    await new Promise(resolve => setTimeout(resolve, 5000));
    console.log('Server should be ready now');
    
    try {
        // 1. Create a new schematic
        const schematicName = 'TestCircuit';
        const schematicPath = path.join(TEST_OUTPUT_DIR, `${schematicName}.kicad_sch`);
        console.log(`Creating schematic: ${schematicName}...`);
        
        const createResult = await sendCommand(serverProcess, 'create_schematic', {
            projectName: schematicName,
            path: TEST_OUTPUT_DIR,
            metadata: {
                description: 'Test circuit schematic',
                author: 'KiCAD MCP Test'
            }
        });
        
        console.log('Create schematic result:', createResult);
        
        if (!createResult.success) {
            throw new Error(`Failed to create schematic: ${createResult.message}`);
        }
        
        // 2. Add components: resistors, capacitor, and power/ground connections
        console.log('Adding components to schematic...');
        
        // Add resistor R1
        const addR1Result = await sendCommand(serverProcess, 'add_schematic_component', {
            schematicPath: schematicPath,
            component: {
                type: 'R',
                reference: 'R1',
                value: '10k',
                library: 'Device',
                x: 100,
                y: 100
            }
        });
        
        console.log('Add R1 result:', addR1Result);
        
        // Add resistor R2
        const addR2Result = await sendCommand(serverProcess, 'add_schematic_component', {
            schematicPath: schematicPath,
            component: {
                type: 'R',
                reference: 'R2',
                value: '4.7k',
                library: 'Device',
                x: 100,
                y: 200
            }
        });
        
        console.log('Add R2 result:', addR2Result);
        
        // Add capacitor C1
        const addC1Result = await sendCommand(serverProcess, 'add_schematic_component', {
            schematicPath: schematicPath,
            component: {
                type: 'C',
                reference: 'C1',
                value: '0.1uF',
                library: 'Device',
                x: 200,
                y: 150
            }
        });
        
        console.log('Add C1 result:', addC1Result);
        
        // 3. Add wires to connect components
        console.log('Adding wires to connect components...');
        
        // Connect R1 to R2
        const addWire1Result = await sendCommand(serverProcess, 'add_schematic_wire', {
            schematicPath: schematicPath,
            startPoint: [150, 100],
            endPoint: [150, 200]
        });
        
        console.log('Add wire 1 result:', addWire1Result);
        
        // Connect R2 to C1
        const addWire2Result = await sendCommand(serverProcess, 'add_schematic_wire', {
            schematicPath: schematicPath,
            startPoint: [150, 200],
            endPoint: [200, 200]
        });
        
        console.log('Add wire 2 result:', addWire2Result);
        
        // Connect C1 to R1
        const addWire3Result = await sendCommand(serverProcess, 'add_schematic_wire', {
            schematicPath: schematicPath,
            startPoint: [200, 100],
            endPoint: [150, 100]
        });
        
        console.log('Add wire 3 result:', addWire3Result);
        
        // 4. Export to PDF
        console.log('Exporting schematic to PDF...');
        const pdfPath = path.join(TEST_OUTPUT_DIR, `${schematicName}.pdf`);
        
        const exportResult = await sendCommand(serverProcess, 'export_schematic_pdf', {
            schematicPath: schematicPath,
            outputPath: pdfPath
        });
        
        console.log('Export PDF result:', exportResult);
        
        if (exportResult.success) {
            console.log(`PDF successfully created at: ${pdfPath}`);
        } else {
            console.log(`Failed to create PDF: ${exportResult.message}`);
        }
        
        console.log('\n=== SCHEMATIC GENERATION TEST COMPLETED ===\n');
        console.log(`Schematic file: ${schematicPath}`);
        console.log(`PDF file: ${pdfPath}`);
    } catch (error) {
        console.error('Test error:', error);
    } finally {
        // Kill the server process
        serverProcess.kill();
    }
}

// Run the test
runTest().catch(console.error);
