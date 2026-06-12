/**
 * Export tools for KiCAD MCP server
 *
 * These tools handle exporting PCB data to various formats
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { logger } from "../logger.js";

// Command function type for KiCAD script calls
type CommandFunction = (command: string, params: Record<string, unknown>) => Promise<any>;

/**
 * Register export tools with the MCP server
 *
 * @param server MCP server instance
 * @param callKicadScript Function to call KiCAD script commands
 */
export function registerExportTools(server: McpServer, callKicadScript: CommandFunction): void {
  logger.info("Registering export tools");

  // ------------------------------------------------------
  // Export Gerber Tool
  // ------------------------------------------------------
  server.tool(
    "export_gerber",
    "Export PCB Gerber manufacturing files to a directory. Optionally include drill files, map files and choose layer subset.",
    {
      outputDir: z.string().describe("Directory to save Gerber files"),
      layers: z
        .array(z.string())
        .optional()
        .describe("Optional array of layer names to export (default: all)"),
      useProtelExtensions: z
        .boolean()
        .optional()
        .describe("Whether to use Protel filename extensions"),
      generateDrillFiles: z.boolean().optional().describe("Whether to generate drill files"),
      generateMapFile: z.boolean().optional().describe("Whether to generate a map file"),
      useAuxOrigin: z.boolean().optional().describe("Whether to use auxiliary axis as origin"),
    },
    async ({
      outputDir,
      layers,
      useProtelExtensions,
      generateDrillFiles,
      generateMapFile,
      useAuxOrigin,
    }) => {
      logger.debug(`Exporting Gerber files to: ${outputDir}`);
      const result = await callKicadScript("export_gerber", {
        outputDir,
        layers,
        useProtelExtensions,
        generateDrillFiles,
        generateMapFile,
        useAuxOrigin,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Export PDF Tool
  // ------------------------------------------------------
  server.tool(
    "export_pdf",
    "Export the PCB layout as a PDF document, optionally selecting layers, page size and colour mode.",
    {
      outputPath: z.string().describe("Path to save the PDF file"),
      layers: z
        .array(z.string())
        .optional()
        .describe("Optional array of layer names to include (default: all)"),
      blackAndWhite: z.boolean().optional().describe("Whether to export in black and white"),
      frameReference: z.boolean().optional().describe("Whether to include frame reference"),
      pageSize: z
        .enum(["A4", "A3", "A2", "A1", "A0", "Letter", "Legal", "Tabloid"])
        .optional()
        .describe("Page size"),
    },
    async ({ outputPath, layers, blackAndWhite, frameReference, pageSize }) => {
      logger.debug(`Exporting PDF to: ${outputPath}`);
      const result = await callKicadScript("export_pdf", {
        outputPath,
        layers,
        blackAndWhite,
        frameReference,
        pageSize,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Export SVG Tool
  // ------------------------------------------------------
  server.tool(
    "export_svg",
    "Export the PCB layout as an SVG vector image, optionally selecting layers and colour mode.",
    {
      outputPath: z.string().describe("Path to save the SVG file"),
      layers: z
        .array(z.string())
        .optional()
        .describe("Optional array of layer names to include (default: all)"),
      blackAndWhite: z.boolean().optional().describe("Whether to export in black and white"),
      includeComponents: z.boolean().optional().describe("Whether to include component outlines"),
    },
    async ({ outputPath, layers, blackAndWhite, includeComponents }) => {
      logger.debug(`Exporting SVG to: ${outputPath}`);
      const result = await callKicadScript("export_svg", {
        outputPath,
        layers,
        blackAndWhite,
        includeComponents,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Export 3D Model Tool
  // ------------------------------------------------------
  server.tool(
    "export_3d",
    "Export the PCB as a 3D model (STEP, STL, VRML or OBJ) including optional copper, solder mask, silkscreen and component 3D models.",
    {
      outputPath: z.string().describe("Path to save the 3D model file"),
      format: z.enum(["STEP", "STL", "VRML", "OBJ"]).describe("3D model format"),
      includeComponents: z.boolean().optional().describe("Whether to include 3D component models"),
      includeCopper: z.boolean().optional().describe("Whether to include copper layers"),
      includeSolderMask: z.boolean().optional().describe("Whether to include solder mask"),
      includeSilkscreen: z.boolean().optional().describe("Whether to include silkscreen"),
    },
    async ({
      outputPath,
      format,
      includeComponents,
      includeCopper,
      includeSolderMask,
      includeSilkscreen,
    }) => {
      logger.debug(`Exporting 3D model to: ${outputPath}`);
      const result = await callKicadScript("export_3d", {
        outputPath,
        format,
        includeComponents,
        includeCopper,
        includeSolderMask,
        includeSilkscreen,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Export BOM Tool
  // ------------------------------------------------------
  server.tool(
    "export_bom",
    "Export a Bill of Materials (BOM) from the PCB in CSV, XML, HTML or JSON format.",
    {
      outputPath: z.string().describe("Path to save the BOM file"),
      format: z.enum(["CSV", "XML", "HTML", "JSON"]).describe("BOM file format"),
      groupByValue: z.boolean().optional().describe("Whether to group components by value"),
      includeAttributes: z
        .array(z.string())
        .optional()
        .describe("Optional array of additional attributes to include"),
    },
    async ({ outputPath, format, groupByValue, includeAttributes }) => {
      logger.debug(`Exporting BOM to: ${outputPath}`);
      const result = await callKicadScript("export_bom", {
        outputPath,
        format,
        groupByValue,
        includeAttributes,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Export Netlist Tool
  // ------------------------------------------------------
  server.tool(
    "export_netlist",
    "Export the schematic netlist to a file using kicad-cli. Supports KiCad XML (default), Spice (for simulation), Cadstar, and OrcadPCB2 formats. Use this when you need to write a netlist file to disk — for example to produce a SPICE file for simulation or to diff against a reference. To get net/component data inline without writing a file, use generate_netlist instead.",
    {
      schematicPath: z.string().describe("Absolute path to the .kicad_sch schematic file"),
      outputPath: z.string().describe("Absolute path for the output file (e.g. /tmp/design.spice)"),
      format: z
        .enum(["KiCad", "Spice", "Cadstar", "OrcadPCB2"])
        .optional()
        .describe("Netlist format (default: KiCad)"),
    },
    async ({ schematicPath, outputPath, format }) => {
      logger.debug(`Exporting netlist to: ${outputPath}`);
      const result = await callKicadScript("export_netlist", {
        schematicPath,
        outputPath,
        format,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Export Position File Tool
  // ------------------------------------------------------
  server.tool(
    "export_position_file",
    "Export a component placement/position file (pick-and-place) for PCB assembly in CSV or ASCII format.",
    {
      outputPath: z.string().describe("Path to save the position file"),
      format: z.enum(["CSV", "ASCII"]).optional().describe("File format (default: CSV)"),
      units: z.enum(["mm", "mil", "inch"]).optional().describe("Units to use (default: mm)"),
      side: z
        .enum(["top", "bottom", "both"])
        .optional()
        .describe("Which board side to include (default: both)"),
    },
    async ({ outputPath, format, units, side }) => {
      logger.debug(`Exporting position file to: ${outputPath}`);
      const result = await callKicadScript("export_position_file", {
        outputPath,
        format,
        units,
        side,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Export VRML Tool
  // ------------------------------------------------------
  server.tool(
    "export_vrml",
    "Export the PCB as a VRML 3D model for use in web viewers or simulation tools.",
    {
      outputPath: z.string().describe("Path to save the VRML file"),
      includeComponents: z.boolean().optional().describe("Whether to include 3D component models"),
      useRelativePaths: z
        .boolean()
        .optional()
        .describe("Whether to use relative paths for 3D models"),
    },
    async ({ outputPath, includeComponents, useRelativePaths }) => {
      logger.debug(`Exporting VRML to: ${outputPath}`);
      const result = await callKicadScript("export_vrml", {
        outputPath,
        includeComponents,
        useRelativePaths,
      });

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Export Gerbers Tool (kicad-cli, full option set)
  // ------------------------------------------------------
  server.tool(
    "export_gerbers",
    "Plot Gerber files for a PCB via kicad-cli, exposing the full Plot-dialog option set (X2, netlist attributes, DNP handling, soldermask subtraction, precision, drill-file origin, stored board plot settings, etc). Reads the board from disk, so it reflects the last SAVED state of the .kicad_pcb.",
    {
      outputDir: z.string().describe("Output directory for the Gerber files"),
      boardPath: z.string().optional().describe("Path to the .kicad_pcb (default: current board)"),
      layers: z
        .array(z.string())
        .optional()
        .describe("Layers to plot, untranslated names e.g. ['F.Cu','B.Cu','Edge.Cuts']"),
      commonLayers: z
        .array(z.string())
        .optional()
        .describe("Layers to include on every plot (e.g. ['Edge.Cuts'])"),
      drawingSheet: z.string().optional().describe("Path to a drawing sheet override"),
      defineVar: z
        .array(z.string())
        .optional()
        .describe("Project variable overrides as 'KEY=VALUE' strings"),
      excludeRefdes: z.boolean().optional().describe("Exclude reference designator text"),
      excludeValue: z.boolean().optional().describe("Exclude value text"),
      includeBorderTitle: z.boolean().optional().describe("Include border and title block"),
      sketchPadsOnFabLayers: z
        .boolean()
        .optional()
        .describe("Draw pad outlines and numbers on fab layers"),
      hideDnpFootprintsOnFabLayers: z
        .boolean()
        .optional()
        .describe("Don't plot DNP footprint text/graphics on fab layers"),
      sketchDnpFootprintsOnFabLayers: z
        .boolean()
        .optional()
        .describe("Plot DNP footprints in sketch mode on fab layers"),
      crossoutDnpFootprintsOnFabLayers: z
        .boolean()
        .optional()
        .describe("Plot an 'X' over DNP footprint courtyards and strike out their refdes"),
      noX2: z.boolean().optional().describe("Do not use the extended X2 Gerber format"),
      noNetlist: z.boolean().optional().describe("Do not generate netlist attributes"),
      subtractSoldermask: z.boolean().optional().describe("Subtract soldermask from silkscreen"),
      disableApertureMacros: z.boolean().optional().describe("Disable aperture macros"),
      useDrillFileOrigin: z.boolean().optional().describe("Use the drill/place file origin"),
      noProtelExt: z
        .boolean()
        .optional()
        .describe("Use KiCad Gerber file extensions instead of Protel"),
      boardPlotParams: z
        .boolean()
        .optional()
        .describe("Use the Gerber plot settings already stored in the board file"),
      precision: z.number().optional().describe("Gerber coordinate precision: 5 or 6 (default 6)"),
    },
    async (args) => {
      logger.debug(`Exporting Gerbers to: ${args.outputDir}`);
      const result = await callKicadScript("export_gerbers", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Export Drill Files Tool (kicad-cli)
  // ------------------------------------------------------
  server.tool(
    "export_drill",
    "Generate drill files for a PCB via kicad-cli, exposing the full Excellon/Gerber drill option set (format, drill origin, zero suppression, oval format, units, mirror-Y, minimal header, separate PTH/NPTH files, drill map + map format). Reads the last SAVED state of the .kicad_pcb.",
    {
      outputDir: z.string().describe("Output directory for the drill files"),
      boardPath: z.string().optional().describe("Path to the .kicad_pcb (default: current board)"),
      format: z
        .enum(["excellon", "gerber"])
        .optional()
        .describe("Drill file format (default excellon)"),
      drillOrigin: z
        .enum(["absolute", "plot"])
        .optional()
        .describe("Drill coordinate origin (default absolute)"),
      excellonZerosFormat: z
        .enum(["decimal", "suppressleading", "suppresstrailing", "keep"])
        .optional()
        .describe("Excellon zero-suppression format (default decimal)"),
      excellonOvalFormat: z
        .enum(["route", "alternate"])
        .optional()
        .describe("Excellon oval hole format (default alternate)"),
      excellonUnits: z.enum(["in", "mm"]).optional().describe("Excellon output units (default mm)"),
      excellonMirrorY: z.boolean().optional().describe("Mirror the Y axis (Excellon)"),
      excellonMinHeader: z.boolean().optional().describe("Use a minimal Excellon header"),
      excellonSeparateTh: z
        .boolean()
        .optional()
        .describe("Generate independent files for NPTH and PTH holes"),
      generateMap: z.boolean().optional().describe("Generate a drill map / summary file"),
      mapFormat: z
        .enum(["pdf", "gerberx2", "ps", "dxf", "svg"])
        .optional()
        .describe("Drill map format when generateMap is set (default pdf)"),
      gerberPrecision: z
        .number()
        .optional()
        .describe("Gerber coordinate precision (5 or 6) when format=gerber"),
    },
    async (args) => {
      logger.debug(`Exporting drill files to: ${args.outputDir}`);
      const result = await callKicadScript("export_drill", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Export IPC-2581 Tool (kicad-cli)
  // ------------------------------------------------------
  server.tool(
    "export_ipc2581",
    "Export the PCB in IPC-2581 format via kicad-cli. Single-file MES/CAD interchange carrying placement, nets and BOM part data inline. The bomCol* params map schematic fields to the embedded BOM columns (e.g. internal P/N, manufacturer P/N) — useful for assembly/MES imports. Reads the last SAVED state of the .kicad_pcb.",
    {
      outputPath: z.string().describe("Output .xml file path"),
      boardPath: z.string().optional().describe("Path to the .kicad_pcb (default: current board)"),
      drawingSheet: z.string().optional().describe("Path to a drawing sheet override"),
      defineVar: z
        .array(z.string())
        .optional()
        .describe("Project variable overrides as 'KEY=VALUE' strings"),
      precision: z.number().optional().describe("Coordinate precision (default 6)"),
      compress: z.boolean().optional().describe("Compress the output"),
      version: z.string().optional().describe("IPC-2581 standard version (default 'C')"),
      units: z.enum(["mm", "in"]).optional().describe("Units (default mm)"),
      bomColIntId: z
        .string()
        .optional()
        .describe("Schematic field to use for the BOM Internal Id column"),
      bomColMfgPn: z
        .string()
        .optional()
        .describe("Schematic field to use for the BOM Manufacturer Part Number column"),
      bomColMfg: z
        .string()
        .optional()
        .describe("Schematic field to use for the BOM Manufacturer column"),
      bomColDistPn: z
        .string()
        .optional()
        .describe("Schematic field to use for the BOM Distributor Part Number column"),
      bomColDist: z.string().optional().describe("Value to insert into the BOM Distributor column"),
    },
    async (args) => {
      logger.debug(`Exporting IPC-2581 to: ${args.outputPath}`);
      const result = await callKicadScript("export_ipc2581", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Export ODB++ Tool (kicad-cli)
  // ------------------------------------------------------
  server.tool(
    "export_odb",
    "Export the PCB in ODB++ format via kicad-cli. Single job archive (copper, drill, placement, components, nets, outline) widely used by CAM/MES/assembly. Reads the last SAVED state of the .kicad_pcb.",
    {
      outputPath: z.string().describe("Output file path (archive or directory per compression)"),
      boardPath: z.string().optional().describe("Path to the .kicad_pcb (default: current board)"),
      drawingSheet: z.string().optional().describe("Path to a drawing sheet override"),
      defineVar: z
        .array(z.string())
        .optional()
        .describe("Project variable overrides as 'KEY=VALUE' strings"),
      precision: z.number().optional().describe("Coordinate precision (default 2)"),
      compression: z
        .enum(["zip", "tgz", "none"])
        .optional()
        .describe("Output container/compression mode (default zip)"),
      units: z.enum(["mm", "in"]).optional().describe("Units (default mm)"),
    },
    async (args) => {
      logger.debug(`Exporting ODB++ to: ${args.outputPath}`);
      const result = await callKicadScript("export_odb", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Export IPC-D-356 Netlist Tool (kicad-cli)
  // ------------------------------------------------------
  server.tool(
    "export_ipcd356",
    "Generate an IPC-D-356 bare-board electrical-test netlist via kicad-cli. Consumed by flying-probe and bed-of-nails testers. Reads the last SAVED state of the .kicad_pcb.",
    {
      outputPath: z.string().describe("Output .ipc / netlist file path"),
      boardPath: z.string().optional().describe("Path to the .kicad_pcb (default: current board)"),
    },
    async (args) => {
      logger.debug(`Exporting IPC-D-356 netlist to: ${args.outputPath}`);
      const result = await callKicadScript("export_ipcd356", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  // ------------------------------------------------------
  // Export GenCAD Tool (kicad-cli)
  // ------------------------------------------------------
  server.tool(
    "export_gencad",
    "Export the PCB in GenCAD format via kicad-cli. Assembly/test interchange format. Exposes padstack flip, unique pin/footprint shape generation, drill-file origin, and store-origin-coordinate options. Reads the last SAVED state of the .kicad_pcb.",
    {
      outputPath: z.string().describe("Output .cad file path"),
      boardPath: z.string().optional().describe("Path to the .kicad_pcb (default: current board)"),
      defineVar: z
        .array(z.string())
        .optional()
        .describe("Project variable overrides as 'KEY=VALUE' strings"),
      flipBottomPads: z.boolean().optional().describe("Flip bottom footprint padstacks"),
      uniquePins: z.boolean().optional().describe("Generate unique pin names"),
      uniqueFootprints: z
        .boolean()
        .optional()
        .describe("Generate a new shape for each footprint instance (do not reuse shapes)"),
      useDrillOrigin: z.boolean().optional().describe("Use drill/place file origin as origin"),
      storeOriginCoord: z.boolean().optional().describe("Save the origin coordinates in the file"),
    },
    async (args) => {
      logger.debug(`Exporting GenCAD to: ${args.outputPath}`);
      const result = await callKicadScript("export_gencad", args);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result),
          },
        ],
      };
    },
  );

  logger.info("Export tools registered");
}
