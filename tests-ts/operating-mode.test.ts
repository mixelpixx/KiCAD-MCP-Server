import { describe, expect, it } from "vitest";
import { commandPolicyError, isManufacturingCommand, isReadOnlyCommand } from "../src/operating-mode.js";

describe("operating mode policy", () => {
  it("allows inspection and validation in readonly mode", () => {
    expect(isReadOnlyCommand("get_board_info")).toBe(true);
    expect(commandPolicyError("open_project", "readonly")).toBeUndefined();
    expect(commandPolicyError("run_drc", "readonly")).toBeUndefined();
    expect(commandPolicyError("run_erc", "readonly")).toBeUndefined();
  });

  it("blocks design mutations in readonly mode", () => {
    expect(commandPolicyError("route_trace", "readonly")).toContain("blocked in readonly mode");
    expect(commandPolicyError("export_gerber", "readonly")).toContain("blocked in readonly mode");
  });

  it("allows only review and release artifacts in manufacturing mode", () => {
    expect(isManufacturingCommand("export_gerber")).toBe(true);
    expect(commandPolicyError("export_gerber", "manufacturing")).toBeUndefined();
    expect(commandPolicyError("run_drc", "manufacturing")).toBeUndefined();
    expect(commandPolicyError("route_trace", "manufacturing")).toContain("blocked in manufacturing mode");
  });

  it("preserves current behavior in write mode", () => {
    expect(commandPolicyError("route_trace", "write")).toBeUndefined();
    expect(commandPolicyError("export_gerber", "write")).toBeUndefined();
  });
});
