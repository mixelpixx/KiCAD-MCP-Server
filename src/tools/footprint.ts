/**
 * Footprint tools for KiCAD MCP server
 *
 * create_footprint      – generate a complete .kicad_mod file in a .pretty library
 * edit_footprint_pad    – update size / position / drill / shape of one pad
 * list_footprint_libraries – list available .pretty libraries
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

// ---- shared sub-schemas ------------------------------------------------- //

const PadPosition = z.object({
  x: z.number().describe("X position in mm"),
  y: z.number().describe("Y position in mm"),
  angle: z.number().optional().describe("Rotation angle in degrees (default 0)"),
});

const PadSize = z.object({
  w: z.number().describe("Width in mm"),
  h: z.number().describe("Height in mm"),
});

const PadSchema = z.object({
  number: z.string().describe("Pad number / name, e.g. '1', '2', 'A1'"),
  type: z
    .enum(["smd", "thru_hole", "np_thru_hole"])
    .describe("Pad type: smd | thru_hole | np_thru_hole"),
  shape: z
    .enum(["rect", "circle", "oval", "roundrect"])
    .optional()
    .describe("Pad shape (default: rect for SMD, circle for THT)"),
  at: PadPosition.describe("Pad centre position"),
  size: PadSize.describe("Pad size in mm"),
  drill: z
    .union([
      z.number().describe("Round drill diameter in mm"),
      z.object({ w: z.number(), h: z.number() }).describe("Oval drill w×h in mm"),
    ])
    .optional()
    .describe("Drill size (required for thru_hole pads)"),
  layers: z
    .array(z.string())
    .optional()
    .describe("Override default layer list, e.g. ['F.Cu','F.Paste','F.Mask']"),
  roundrect_ratio: z
    .number()
    .min(0)
    .max(0.5)
    .optional()
    .describe("Corner radius ratio for roundrect shape (0.0–0.5, default 0.25)"),
});

const RectSchema = z.object({
  x1: z.number().describe("Left X in mm"),
  y1: z.number().describe("Top Y in mm"),
  x2: z.number().describe("Right X in mm"),
  y2: z.number().describe("Bottom Y in mm"),
  width: z.number().optional().describe("Line width in mm"),
});

// ---- tool registration --------------------------------------------------- //

export function registerFootprintTools(server: McpServer, callKicadScript: Function) {
  // ── create_footprint ──────────────────────────────────────────────────── //
  server.tool(
    "create_footprint",
    "Create a new KiCAD footprint (.kicad_mod) inside a .pretty library directory. " +
      "Supports SMD and THT pads, courtyard, silkscreen, and fab-layer rectangles.",
    {
      libraryPath: z
        .string()
        .describe(
          "Path to the .pretty library directory (created if missing). " +
            "E.g. C:/MyProject/MyLib.pretty",
        ),
      name: z.string().describe("Footprint name, e.g. 'R_0603_Custom'"),
      description: z.string().optional().describe("Human-readable description"),
      tags: z.string().optional().describe("Space-separated tag string, e.g. 'resistor SMD 0603'"),
      pads: z
        .array(PadSchema)
        .optional()
        .describe("List of pads to add (can be empty for outlines-only footprints)"),
      courtyard: RectSchema.optional().describe(
        "Courtyard rectangle on F.CrtYd (recommended: 0.25 mm clearance around pads)",
      ),
      silkscreen: RectSchema.optional().describe("Silkscreen rectangle on F.SilkS"),
      fabLayer: RectSchema.optional().describe(
        "Fab-layer rectangle on F.Fab (shows component body)",
      ),
      refPosition: z
        .object({ x: z.number(), y: z.number() })
        .optional()
        .describe("Position of the REF** text (default: 0, -1.27)"),
      valuePosition: z
        .object({ x: z.number(), y: z.number() })
        .optional()
        .describe("Position of the Value text (default: 0, 1.27)"),
      overwrite: z
        .boolean()
        .optional()
        .describe("Replace existing footprint file (default: false)"),
    },
    async (args: {
      libraryPath: string;
      name: string;
      description?: string;
      tags?: string;
      pads?: z.infer<typeof PadSchema>[];
      courtyard?: z.infer<typeof RectSchema>;
      silkscreen?: z.infer<typeof RectSchema>;
      fabLayer?: z.infer<typeof RectSchema>;
      refPosition?: { x: number; y: number };
      valuePosition?: { x: number; y: number };
      overwrite?: boolean;
    }) => {
      const result = await callKicadScript("create_footprint", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ── add_footprint_3d_model ────────────────────────────────────────────── //
  const Xyz = z.object({
    x: z.number(),
    y: z.number(),
    z: z.number(),
  });
  server.tool(
    "add_footprint_3d_model",
    "Attach (or replace) a 3D model — .step/.stp/.wrl — to a .kicad_mod footprint file. " +
      "KiCAD path variables like ${KIPRJMOD} or ${KICAD10_3DMODEL_DIR} are supported. " +
      "Use this after create_footprint so the part shows up in the 3D viewer (Alt+3).",
    {
      footprintPath: z
        .string()
        .describe("Full path to the .kicad_mod file, e.g. C:/MyLib.pretty/MyPart.kicad_mod"),
      modelPath: z
        .string()
        .describe(
          "Path to the 3D model file. Prefer ${KIPRJMOD}/MyProj.3dshapes/MyPart.step for portability.",
        ),
      offset: Xyz.optional().describe("Model offset in mm (default 0,0,0)"),
      scale: Xyz.optional().describe("Model scale factor (default 1,1,1)"),
      rotate: Xyz.optional().describe("Model rotation in degrees (default 0,0,0)"),
      replace: z
        .boolean()
        .optional()
        .describe("Replace an existing model with the same filename (default true)"),
    },
    async (args: {
      footprintPath: string;
      modelPath: string;
      offset?: { x: number; y: number; z: number };
      scale?: { x: number; y: number; z: number };
      rotate?: { x: number; y: number; z: number };
      replace?: boolean;
    }) => {
      const result = await callKicadScript("add_footprint_3d_model", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ── import_3d_model ──────────────────────────────────────────────────── //
  server.tool(
    "import_3d_model",
    "Copy a 3D model file (.step/.stp/.wrl/.x3d/.iges) into the project's *.3dshapes " +
      "library folder and return a portable ${KIPRJMOD}/... path. Feed the returned " +
      "'modelPath' straight into add_footprint_3d_model or add_component_3d_model.",
    {
      modelPath: z.string().describe("Path to the source 3D model file to import"),
      projectPath: z
        .string()
        .describe(
          "Path to the .kicad_pro file or the project directory (used to locate the " +
            ".3dshapes folder and compute ${KIPRJMOD})",
        ),
      libraryDir: z
        .string()
        .optional()
        .describe(
          "Target *.3dshapes directory (absolute, or relative to the project). " +
            "Default: <project>/<project>.3dshapes",
        ),
      newName: z
        .string()
        .optional()
        .describe("Rename the copied file (source extension kept if omitted)"),
      overwrite: z
        .boolean()
        .optional()
        .describe("Overwrite an existing destination file (default false)"),
    },
    async (args: {
      modelPath: string;
      projectPath: string;
      libraryDir?: string;
      newName?: string;
      overwrite?: boolean;
    }) => {
      const result = await callKicadScript("import_3d_model", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ── add_component_3d_model (LIVE / IPC) ──────────────────────────────── //
  server.tool(
    "add_component_3d_model",
    "Attach a 3D model to one or more PLACED footprints on the open board, live via " +
      "the KiCAD IPC API (changes appear instantly, no file conflicts). " +
      "Use this for components already on the PCB; for a library .kicad_mod use add_footprint_3d_model.",
    {
      reference: z
        .union([z.string(), z.array(z.string())])
        .describe("Footprint reference(s), e.g. 'D1', ['D1','D2'], or '*' for all footprints"),
      modelPath: z
        .string()
        .describe("Path to the 3D model, e.g. ${KIPRJMOD}/MyProj.3dshapes/MyPart.step"),
      offset: Xyz.optional().describe("Model offset in mm (default 0,0,0)"),
      scale: Xyz.optional().describe("Model scale factor (default 1,1,1)"),
      rotate: Xyz.optional().describe("Model rotation in degrees (default 0,0,0)"),
      replace: z
        .boolean()
        .optional()
        .describe("Replace an existing model with the same filename (default true)"),
    },
    async (args: {
      reference: string | string[];
      modelPath: string;
      offset?: { x: number; y: number; z: number };
      scale?: { x: number; y: number; z: number };
      rotate?: { x: number; y: number; z: number };
      replace?: boolean;
    }) => {
      const result = await callKicadScript("add_component_3d_model", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ── edit_footprint_pad ────────────────────────────────────────────────── //
  server.tool(
    "edit_footprint_pad",
    "Edit an existing pad inside a .kicad_mod footprint file. " +
      "Updates size, position, drill, or shape without recreating the whole footprint.",
    {
      footprintPath: z
        .string()
        .describe("Full path to the .kicad_mod file, e.g. C:/MyLib.pretty/R_Custom.kicad_mod"),
      padNumber: z.union([z.string(), z.number()]).describe("Pad number to edit, e.g. '1' or 2"),
      size: PadSize.optional().describe("New pad size in mm"),
      at: PadPosition.optional().describe("New pad position in mm"),
      drill: z
        .union([
          z.number().describe("Round drill diameter in mm"),
          z.object({ w: z.number(), h: z.number() }).describe("Oval drill"),
        ])
        .optional()
        .describe("New drill size (for THT pads)"),
      shape: z.enum(["rect", "circle", "oval", "roundrect"]).optional().describe("New pad shape"),
    },
    async (args: {
      footprintPath: string;
      padNumber: string | number;
      size?: { w: number; h: number };
      at?: { x: number; y: number; angle?: number };
      drill?: number | { w: number; h: number };
      shape?: string;
    }) => {
      const result = await callKicadScript("edit_footprint_pad", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ── register_footprint_library ───────────────────────────────────────── //
  server.tool(
    "register_footprint_library",
    "Register a .pretty footprint library in KiCAD's fp-lib-table so KiCAD can find the footprints. " +
      "Run this after create_footprint when KiCAD shows 'library not found in footprint library table'.",
    {
      libraryPath: z.string().describe("Full path to the .pretty directory to register"),
      libraryName: z
        .string()
        .optional()
        .describe("Nickname for the library in KiCAD (default: directory name without .pretty)"),
      description: z.string().optional().describe("Optional description"),
      scope: z
        .enum(["project", "global"])
        .optional()
        .describe(
          "project = writes fp-lib-table next to the .kicad_pro file (default); " +
            "global = writes to the user's global KiCAD config",
        ),
      projectPath: z
        .string()
        .optional()
        .describe(
          "Path to the .kicad_pro file or its directory (required for scope=project " +
            "when the library is not in the project folder)",
        ),
    },
    async (args: {
      libraryPath: string;
      libraryName?: string;
      description?: string;
      scope?: "project" | "global";
      projectPath?: string;
    }) => {
      const result = await callKicadScript("register_footprint_library", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  // ── list_footprint_libraries ─────────────────────────────────────────── //
  server.tool(
    "list_footprint_libraries",
    "List available .pretty footprint libraries and their contents (first 20 footprints per library). " +
      "Searches KiCAD standard install paths by default.",
    {
      searchPaths: z
        .array(z.string())
        .optional()
        .describe(
          "Override default search paths. Each entry should be a directory that contains .pretty subdirs.",
        ),
    },
    async (args: { searchPaths?: string[] }) => {
      const result = await callKicadScript("list_footprint_libraries", args);
      return {
        content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
      };
    },
  );
}
