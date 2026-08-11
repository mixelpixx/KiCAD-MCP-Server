import { describe, expect, it } from "vitest";
import { parseCliArguments } from "../src/cli.js";

describe("KiCad MCP CLI", () => {
  it("defaults to serving and accepts an explicit configuration", () => {
    expect(parseCliArguments([])).toEqual({ command: "serve" });
    expect(parseCliArguments(["serve", "--config", "custom.json"])).toEqual({
      command: "serve",
      configPath: "custom.json",
    });
    expect(parseCliArguments(["--config=custom.json"])).toEqual({
      command: "serve",
      configPath: "custom.json",
    });
  });

  it("parses setup, doctor, and help without starting the server", () => {
    expect(parseCliArguments(["setup"])).toEqual({ command: "setup" });
    expect(parseCliArguments(["doctor"])).toEqual({ command: "doctor" });
    expect(parseCliArguments(["--help"])).toEqual({ command: "help" });
  });

  it("rejects unknown commands, options, and missing values", () => {
    expect(() => parseCliArguments(["launch"])).toThrow("Unknown command");
    expect(() => parseCliArguments(["serve", "--unknown"])).toThrow("Unknown serve option");
    expect(() => parseCliArguments(["serve", "--config"])).toThrow("--config requires a path");
    expect(() => parseCliArguments(["doctor", "extra"])).toThrow(
      "doctor does not accept arguments",
    );
  });
});
