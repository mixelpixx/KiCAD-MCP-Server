/**
 * Parameter translations for tools whose schema predates the Python command
 * that now does the work.
 *
 * `add_zone`, `export_position_file` and `export_vrml` were registered on the
 * server and listed by search_tools, but the Python side never had a route for
 * them: every call failed with "Unknown command". Each has a newer sibling
 * that does the same job, so the tool keeps its schema and the call is sent to
 * that sibling instead. Kept as pure functions, like `command-timeout.ts`, so
 * the mapping is unit-testable without a worker.
 */

type Unit = "mm" | "mil" | "inch";

const MM_PER: Record<Unit, number> = { mm: 1, mil: 0.0254, inch: 25.4 };

export interface AddZoneParams {
  layer: string;
  net: string;
  points: { x: number; y: number }[];
  unit: Unit;
  clearance?: number;
  minWidth?: number;
  padConnection?: "thermal" | "solid" | "none";
}

/** add_zone -> add_copper_pour. Lengths are converted to mm, the unit
 * add_copper_pour takes for clearance and minWidth; points keep their unit. */
export function addZoneToCopperPour(p: AddZoneParams): Record<string, unknown> {
  const toMm = (v: number | undefined) => (v === undefined ? undefined : v * (MM_PER[p.unit] ?? 1));
  return dropUndefined({
    layer: p.layer,
    net: p.net,
    outline: p.points.map((pt) => ({ x: pt.x, y: pt.y, unit: p.unit })),
    clearance: toMm(p.clearance),
    minWidth: toMm(p.minWidth),
    padConnection: p.padConnection,
  });
}

export interface PositionFileParams {
  outputPath: string;
  format?: "CSV" | "ASCII";
  units?: "mm" | "mil" | "inch";
  side?: "top" | "bottom" | "both";
}

/** export_position_file -> export_pos (kicad-cli `pcb export pos`).
 * kicad-cli writes mm or inches only, so a mil request is rejected rather
 * than silently written in another unit. */
export function positionFileToExportPos(
  p: PositionFileParams,
): { params: Record<string, unknown> } | { error: string } {
  if (p.units === "mil") {
    return { error: "units 'mil' is not supported by kicad-cli; use 'mm' or 'inch'" };
  }
  const side = { top: "front", bottom: "back", both: "both" } as const;
  return {
    params: {
      outputPath: p.outputPath,
      format: (p.format ?? "CSV").toLowerCase(),
      units: p.units === "inch" ? "in" : "mm",
      side: side[p.side ?? "both"],
    },
  };
}

export interface VrmlParams {
  outputPath: string;
  includeComponents?: boolean;
  useRelativePaths?: boolean;
}

/** export_vrml -> export_3d_cli with format "vrml". kicad-cli embeds the
 * component models unless a models directory is given; relative model paths
 * need that directory. Leaving the models out is not something kicad-cli's
 * VRML export can do, so includeComponents=false is rejected. */
export function vrmlToExport3dCli(
  p: VrmlParams,
): { params: Record<string, unknown> } | { error: string } {
  if (p.includeComponents === false) {
    return {
      error:
        "includeComponents=false is not supported by kicad-cli's VRML export; " +
        "use export_3d_cli (step/glb/stl) with noComponents instead",
    };
  }
  return {
    params: dropUndefined({
      format: "vrml",
      outputPath: p.outputPath,
      force: true,
      modelsDir: p.useRelativePaths ? "shapes3D" : undefined,
      modelsRelative: p.useRelativePaths ? true : undefined,
    }),
  };
}

function dropUndefined(o: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined));
}
