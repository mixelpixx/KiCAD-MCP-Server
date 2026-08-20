import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

export function registerValidationTools(server: McpServer, callKicadScript: Function) {
  const runKicadCli = z
    .boolean()
    .optional()
    .describe(
      "Confirm the result with kicad-cli, run on a throwaway copy so the file is never " +
        "modified (default true). Set false for a fast structure-only check, or when " +
        "KiCad is not installed.",
    );

  server.tool(
    "validate_schematic",
    "Check that a .kicad_sch file is structurally sound, reporting the line and column of " +
      "every fault. kicad-cli only says whether a file loads; this says where it broke. " +
      "Catches unbalanced parens, unterminated strings, trailing content, and property or " +
      "effects fragments orphaned directly under (kicad_sch ...), which is what a truncated " +
      "property rewrite leaves behind. A paren fault that nets to zero is caught too, by " +
      "the first line whose indentation stops agreeing with its nesting depth. Note that " +
      "column counts characters, so a tab counts once and the number reads lower than an " +
      "editor's ruler on indented lines. Run it after any tool that edits a schematic.",
    {
      schematicPath: z.string().describe("Absolute path to the .kicad_sch file"),
      runKicadCli,
    },
    async (args: { schematicPath: string; runKicadCli?: boolean }) => {
      const result = await callKicadScript("validate_schematic", args);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    },
  );

  server.tool(
    "validate_symbol_library",
    "Check that a .kicad_sym file is structurally sound and will load, reporting the line " +
      "and column of every fault instead of a bare 'Unable to load library'. Beyond paren " +
      "and string structure it reports units whose names no longer match their symbol (a " +
      "rename that missed the NAME_0_1 sub-symbols makes the whole library unloadable), " +
      "(effects ...) or (at ...) fragments a truncated property rewrite left inside a " +
      "(symbol ...), units that escaped their parent to the top level, and duplicate " +
      "symbol names. Note that column counts characters, so a tab counts once and the " +
      "number reads lower than an editor's ruler on indented lines. Run it after any tool " +
      "that edits a library.",
    {
      libraryPath: z.string().describe("Absolute path to the .kicad_sym file"),
      runKicadCli,
    },
    async (args: { libraryPath: string; runKicadCli?: boolean }) => {
      const result = await callKicadScript("validate_symbol_library", args);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    },
  );
}
