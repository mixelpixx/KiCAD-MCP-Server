import { describe, expect, it } from "vitest";
import {
  addZoneToCopperPour,
  positionFileToExportPos,
  replaceComponentToEditComponent,
  vrmlToExport3dCli,
} from "../src/tools/tool-aliases.js";

const square = [
  { x: 0, y: 0 },
  { x: 10, y: 0 },
  { x: 10, y: 10 },
];

describe("add_zone -> add_copper_pour", () => {
  it("passes the outline with its unit and keeps the zone options", () => {
    expect(
      addZoneToCopperPour({
        layer: "F.Cu",
        net: "GND",
        points: square,
        unit: "mm",
        clearance: 0.3,
        minWidth: 0.25,
        padConnection: "solid",
      }),
    ).toEqual({
      layer: "F.Cu",
      net: "GND",
      outline: square.map((p) => ({ ...p, unit: "mm" })),
      clearance: 0.3,
      minWidth: 0.25,
      padConnection: "solid",
    });
  });

  it("converts clearance and minWidth to mm", () => {
    const r = addZoneToCopperPour({
      layer: "B.Cu",
      net: "GND",
      points: square,
      unit: "mil",
      clearance: 10,
      minWidth: 8,
    });
    expect(r.clearance).toBeCloseTo(0.254);
    expect(r.minWidth).toBeCloseTo(0.2032);
    expect(r).not.toHaveProperty("padConnection");
  });
});

describe("export_position_file -> export_pos", () => {
  it("maps format, units and side to kicad-cli values", () => {
    expect(
      positionFileToExportPos({
        outputPath: "/o.csv",
        format: "ASCII",
        units: "inch",
        side: "top",
      }),
    ).toEqual({ params: { outputPath: "/o.csv", format: "ascii", units: "in", side: "front" } });
  });

  it("defaults to CSV, mm, both sides", () => {
    expect(positionFileToExportPos({ outputPath: "/o.csv" })).toEqual({
      params: { outputPath: "/o.csv", format: "csv", units: "mm", side: "both" },
    });
  });

  it("rejects mil, which kicad-cli cannot write", () => {
    expect(positionFileToExportPos({ outputPath: "/o.csv", units: "mil" })).toHaveProperty("error");
  });
});

describe("export_vrml -> export_3d_cli", () => {
  it("selects the vrml format", () => {
    expect(vrmlToExport3dCli({ outputPath: "/b.wrl" })).toEqual({
      params: { format: "vrml", outputPath: "/b.wrl", force: true },
    });
  });

  it("writes models to a relative directory when asked", () => {
    const r = vrmlToExport3dCli({ outputPath: "/b.wrl", useRelativePaths: true });
    expect(r).toEqual({
      params: {
        format: "vrml",
        outputPath: "/b.wrl",
        force: true,
        modelsDir: "shapes3D",
        modelsRelative: true,
      },
    });
  });

  it("rejects includeComponents=false, which kicad-cli's VRML export cannot do", () => {
    expect(vrmlToExport3dCli({ outputPath: "/b.wrl", includeComponents: false })).toHaveProperty(
      "error",
    );
  });
});

describe("replace_component -> edit_component", () => {
  it("uses newFootprint and newValue", () => {
    expect(
      replaceComponentToEditComponent({
        reference: "R5",
        newComponentId: "anything",
        newFootprint: "Resistor_SMD:R_0805_2012Metric",
        newValue: "4k7",
      }),
    ).toEqual({
      params: { reference: "R5", footprint: "Resistor_SMD:R_0805_2012Metric", value: "4k7" },
    });
  });

  it("uses newComponentId as the footprint when it is Library:Footprint", () => {
    expect(
      replaceComponentToEditComponent({
        reference: "C1",
        newComponentId: "Capacitor_SMD:C_0603_1608Metric",
      }),
    ).toEqual({ params: { reference: "C1", footprint: "Capacitor_SMD:C_0603_1608Metric" } });
  });

  it.each(["R_0603_1608Metric", "Device:R:extra", ":R_0603", "Resistor_SMD:", ""])(
    "refuses newComponentId %j without newFootprint",
    (id) => {
      const r = replaceComponentToEditComponent({ reference: "R5", newComponentId: id });
      expect(r).toHaveProperty("error");
      expect((r as { error: string }).error).toContain("Library:Footprint");
    },
  );
});
