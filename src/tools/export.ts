/**
 * Export tools for KiCAD MCP server
 * 
 * These tools handle exporting PCB data to various formats
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { logger } from '../logger.js';

// Command function type for KiCAD script calls
type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

/**
 * Register export tools with the MCP server
 * 
 * @param server MCP server instance
 * @param callKicadScript Function to call KiCAD script commands
 */
export function registerExportTools(server: McpServer, callKicadScript: CommandFunction): void {
  logger.info('Registering export tools');
  
  // ------------------------------------------------------
  // Export Gerber Tool
  // ------------------------------------------------------
  server.tool(
    "export_gerber",
    {
      outputDir: z.string().describe("Directory to save Gerber files"),
      layers: z.array(z.string()).optional().describe("Optional array of layer names to export (default: all)"),
      useProtelExtensions: z.boolean().optional().describe("Whether to use Protel filename extensions"),
      generateDrillFiles: z.boolean().optional().describe("Whether to generate drill files"),
      generateMapFile: z.boolean().optional().describe("Whether to generate a map file"),
      useAuxOrigin: z.boolean().optional().describe("Whether to use auxiliary axis as origin")
    },
    async ({ outputDir, layers, useProtelExtensions, generateDrillFiles, generateMapFile, useAuxOrigin }) => {
      logger.debug(`Exporting Gerber files to: ${outputDir}`);
      const result = await callKicadScript("export_gerber", {
        outputDir,
        layers,
        useProtelExtensions,
        generateDrillFiles,
        generateMapFile,
        useAuxOrigin
      });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Export PDF Tool
  // ------------------------------------------------------
  server.tool(
    "export_pdf",
    {
      outputPath: z.string().describe("Path to save the PDF file"),
      layers: z.array(z.string()).optional().describe("Optional array of layer names to include (default: all)"),
      blackAndWhite: z.boolean().optional().describe("Whether to export in black and white"),
      frameReference: z.boolean().optional().describe("Whether to include frame reference"),
      pageSize: z.enum(["A4", "A3", "A2", "A1", "A0", "Letter", "Legal", "Tabloid"]).optional().describe("Page size")
    },
    async ({ outputPath, layers, blackAndWhite, frameReference, pageSize }) => {
      logger.debug(`Exporting PDF to: ${outputPath}`);
      const result = await callKicadScript("export_pdf", {
        outputPath,
        layers,
        blackAndWhite,
        frameReference,
        pageSize
      });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Export SVG Tool
  // ------------------------------------------------------
  server.tool(
    "export_svg",
    {
      outputPath: z.string().describe("Path to save the SVG file"),
      layers: z.array(z.string()).optional().describe("Optional array of layer names to include (default: all)"),
      blackAndWhite: z.boolean().optional().describe("Whether to export in black and white"),
      includeComponents: z.boolean().optional().describe("Whether to include component outlines")
    },
    async ({ outputPath, layers, blackAndWhite, includeComponents }) => {
      logger.debug(`Exporting SVG to: ${outputPath}`);
      const result = await callKicadScript("export_svg", {
        outputPath,
        layers,
        blackAndWhite,
        includeComponents
      });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Export 3D Model Tool
  // ------------------------------------------------------
  server.tool(
    "export_3d",
    {
      outputPath: z.string().describe("Path to save the 3D model file"),
      format: z.enum(["STEP", "STL", "VRML", "OBJ"]).describe("3D model format"),
      includeComponents: z.boolean().optional().describe("Whether to include 3D component models"),
      includeCopper: z.boolean().optional().describe("Whether to include copper layers"),
      includeSolderMask: z.boolean().optional().describe("Whether to include solder mask"),
      includeSilkscreen: z.boolean().optional().describe("Whether to include silkscreen")
    },
    async ({ outputPath, format, includeComponents, includeCopper, includeSolderMask, includeSilkscreen }) => {
      logger.debug(`Exporting 3D model to: ${outputPath}`);
      const result = await callKicadScript("export_3d", {
        outputPath,
        format,
        includeComponents,
        includeCopper,
        includeSolderMask,
        includeSilkscreen
      });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Export BOM Tool
  // ------------------------------------------------------
  server.tool(
    "export_bom",
    {
      outputPath: z.string().describe("Path to save the BOM file"),
      format: z.enum(["CSV", "XML", "HTML", "JSON"]).describe("BOM file format"),
      groupByValue: z.boolean().optional().describe("Whether to group components by value"),
      includeAttributes: z.array(z.string()).optional().describe("Optional array of additional attributes to include")
    },
    async ({ outputPath, format, groupByValue, includeAttributes }) => {
      logger.debug(`Exporting BOM to: ${outputPath}`);
      const result = await callKicadScript("export_bom", {
        outputPath,
        format,
        groupByValue,
        includeAttributes
      });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Export Netlist Tool
  // ------------------------------------------------------
  server.tool(
    "export_netlist",
    {
      outputPath: z.string().describe("Path to save the netlist file"),
      format: z.enum(["KiCad", "Spice", "Cadstar", "OrcadPCB2"]).optional().describe("Netlist format (default: KiCad)")
    },
    async ({ outputPath, format }) => {
      logger.debug(`Exporting netlist to: ${outputPath}`);
      const result = await callKicadScript("export_netlist", {
        outputPath,
        format
      });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Export Position File Tool
  // ------------------------------------------------------
  server.tool(
    "export_position_file",
    {
      outputPath: z.string().describe("Path to save the position file"),
      format: z.enum(["CSV", "ASCII"]).optional().describe("File format (default: CSV)"),
      units: z.enum(["mm", "inch"]).optional().describe("Units to use (default: mm)"),
      side: z.enum(["top", "bottom", "both"]).optional().describe("Which board side to include (default: both)")
    },
    async ({ outputPath, format, units, side }) => {
      logger.debug(`Exporting position file to: ${outputPath}`);
      const result = await callKicadScript("export_position_file", {
        outputPath,
        format,
        units,
        side
      });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  // ------------------------------------------------------
  // Export VRML Tool
  // ------------------------------------------------------
  server.tool(
    "export_vrml",
    {
      outputPath: z.string().describe("Path to save the VRML file"),
      includeComponents: z.boolean().optional().describe("Whether to include 3D component models"),
      useRelativePaths: z.boolean().optional().describe("Whether to use relative paths for 3D models")
    },
    async ({ outputPath, includeComponents, useRelativePaths }) => {
      logger.debug(`Exporting VRML to: ${outputPath}`);
      const result = await callKicadScript("export_vrml", {
        outputPath,
        includeComponents,
        useRelativePaths
      });
      
      return {
        content: [{
          type: "text",
          text: JSON.stringify(result)
        }]
      };
    }
  );

  logger.info('Export tools registered');
}
