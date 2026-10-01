/**
 * Risk-oriented execution policy for KiCAD commands.
 *
 * The MCP server intentionally keeps its complete tool catalog discoverable.
 * This module is the enforcement point before a tool reaches the Python/KiCAD
 * bridge, so a client cannot bypass the selected operating mode by calling a
 * tool directly instead of following a prompt or router suggestion.
 */

export const OPERATING_MODES = ["readonly", "write", "manufacturing", "experimental"] as const;
export type OperatingMode = (typeof OPERATING_MODES)[number];

const READ_ONLY_PREFIXES = ["get_", "list_", "search_", "find_", "check_", "validate_", "query_"];
const READ_ONLY_COMMANDS = new Set([
  // Loading an existing file establishes session state but does not alter the
  // design. Without these, an agent could inspect only a project that another
  // mode had already opened.
  "open_project",
  "open_board",
  "reload_board",
  "load_schematic",
  "run_drc",
  "run_erc",
  "is_dirty",
  "estimate_airwire_lengths",
  "lint_offgrid",
  "lint_schematic_cosmetic",
  "get_backend_state",
  "get_backend_info",
  "check_kicad_ui",
]);

/** Artifacts and release inputs that manufacturing mode may generate. */
const MANUFACTURING_PREFIXES = ["export_"];
const MANUFACTURING_COMMANDS = new Set(["generate_netlist", "export_dsn"]);

export function isOperatingMode(value: unknown): value is OperatingMode {
  return typeof value === "string" && (OPERATING_MODES as readonly string[]).includes(value);
}

export function isReadOnlyCommand(command: string): boolean {
  return READ_ONLY_COMMANDS.has(command) || READ_ONLY_PREFIXES.some((prefix) => command.startsWith(prefix));
}

export function isManufacturingCommand(command: string): boolean {
  return MANUFACTURING_COMMANDS.has(command) || MANUFACTURING_PREFIXES.some((prefix) => command.startsWith(prefix));
}

/** Return a stable reason when a command is unavailable in the selected mode. */
export function commandPolicyError(command: string, mode: OperatingMode): string | undefined {
  if (mode === "write" || mode === "experimental") return undefined;

  if (mode === "readonly") {
    return isReadOnlyCommand(command)
      ? undefined
      : `Command '${command}' is blocked in readonly mode. Set KICAD_MCP_OPERATING_MODE=write to modify a design.`;
  }

  if (isReadOnlyCommand(command) || isManufacturingCommand(command)) return undefined;
  return `Command '${command}' is blocked in manufacturing mode. This mode permits review and export only.`;
}
