import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  Client,
  INTERNAL_ERROR,
  INVALID_PARAMS,
  InMemoryTransport,
  type GetPromptResult,
} from "@modelcontextprotocol/client";
import { McpServer } from "@modelcontextprotocol/server";
import { registerComponentPrompts } from "../src/prompts/component.js";
import { registerDesignPrompts } from "../src/prompts/design.js";
import { registerFootprintPrompts } from "../src/prompts/footprint.js";
import { registerRoutingPrompts } from "../src/prompts/routing.js";
import { registerBoardResources } from "../src/resources/board.js";
import { registerComponentResources } from "../src/resources/component.js";
import { registerLibraryResources } from "../src/resources/library.js";
import { registerProjectResources } from "../src/resources/project.js";
import type { BackendResult, CommandFunction } from "../src/resources/shared.js";

async function connect(server: McpServer) {
  const client = new Client({ name: "prompt-resource-test-client", version: "1.0.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return {
    client,
    close: async () => {
      await client.close();
      await server.close();
    },
  };
}

function getText(result: GetPromptResult): string {
  const content = result.messages[0]?.content;
  if (!content || content.type !== "text") throw new Error("Expected a text prompt response");
  return content.text;
}

describe("KiCad prompts", () => {
  let client: Client;
  let close: () => Promise<void>;

  beforeAll(async () => {
    const server = new McpServer({ name: "prompt-test", version: "1.0.0" });
    registerComponentPrompts(server);
    registerDesignPrompts(server);
    registerFootprintPrompts(server);
    registerRoutingPrompts(server);
    ({ client, close } = await connect(server));
  });

  afterAll(async () => close());

  const cases: Array<{
    name: string;
    args: Record<string, string>;
    expected: string[];
  }> = [
    {
      name: "component_selection",
      args: { requirements: "PROMPT_MARKER_COMPONENT_SELECTION" },
      expected: ["PROMPT_MARKER_COMPONENT_SELECTION"],
    },
    {
      name: "component_placement_strategy",
      args: { components: "PROMPT_MARKER_COMPONENT_PLACEMENT" },
      expected: ["PROMPT_MARKER_COMPONENT_PLACEMENT"],
    },
    {
      name: "component_replacement_analysis",
      args: { component_info: "PROMPT_MARKER_REPLACEMENT" },
      expected: ["PROMPT_MARKER_REPLACEMENT"],
    },
    {
      name: "component_troubleshooting",
      args: { issue_description: "PROMPT_MARKER_TROUBLESHOOTING" },
      expected: ["PROMPT_MARKER_TROUBLESHOOTING"],
    },
    {
      name: "component_sourcing_properties",
      args: { component_info: "PROMPT_MARKER_SOURCING" },
      expected: ["PROMPT_MARKER_SOURCING"],
    },
    {
      name: "component_value_calculation",
      args: { circuit_requirements: "PROMPT_MARKER_VALUE_CALC" },
      expected: ["PROMPT_MARKER_VALUE_CALC"],
    },
    {
      name: "pcb_layout_review",
      args: { pcb_design_info: "PROMPT_MARKER_LAYOUT_REVIEW" },
      expected: ["PROMPT_MARKER_LAYOUT_REVIEW"],
    },
    {
      name: "layer_stackup_planning",
      args: { design_requirements: "PROMPT_MARKER_STACKUP" },
      expected: ["PROMPT_MARKER_STACKUP"],
    },
    {
      name: "design_rule_development",
      args: { project_requirements: "PROMPT_MARKER_RULES" },
      expected: ["PROMPT_MARKER_RULES"],
    },
    {
      name: "component_selection_guidance",
      args: { circuit_requirements: "PROMPT_MARKER_GUIDANCE" },
      expected: ["PROMPT_MARKER_GUIDANCE"],
    },
    {
      name: "pcb_design_optimization",
      args: {
        design_info: "PROMPT_MARKER_DESIGN_INFO",
        optimization_goals: "PROMPT_MARKER_OPTIMIZATION_GOALS",
      },
      expected: ["PROMPT_MARKER_DESIGN_INFO", "PROMPT_MARKER_OPTIMIZATION_GOALS"],
    },
    {
      name: "routing_strategy",
      args: { board_info: "PROMPT_MARKER_ROUTING" },
      expected: ["PROMPT_MARKER_ROUTING"],
    },
    {
      name: "differential_pair_routing",
      args: { differential_pairs: "PROMPT_MARKER_DIFF_PAIR" },
      expected: ["PROMPT_MARKER_DIFF_PAIR"],
    },
    {
      name: "high_speed_routing",
      args: { high_speed_signals: "PROMPT_MARKER_HIGH_SPEED" },
      expected: ["PROMPT_MARKER_HIGH_SPEED"],
    },
    {
      name: "power_distribution",
      args: { power_requirements: "PROMPT_MARKER_POWER" },
      expected: ["PROMPT_MARKER_POWER"],
    },
    {
      name: "via_usage",
      args: { board_info: "PROMPT_MARKER_VIAS" },
      expected: ["PROMPT_MARKER_VIAS"],
    },
    {
      name: "create_footprint_guide",
      args: {
        component: "PROMPT_MARKER_FOOTPRINT_COMPONENT",
        libraryPath: "PROMPT_MARKER_LIBRARY_PATH",
      },
      expected: ["PROMPT_MARKER_FOOTPRINT_COMPONENT", "PROMPT_MARKER_LIBRARY_PATH"],
    },
    {
      name: "footprint_ipc_checklist",
      args: { footprintPath: "PROMPT_MARKER_FOOTPRINT_PATH" },
      expected: ["PROMPT_MARKER_FOOTPRINT_PATH"],
    },
  ];

  it("registers all expected prompts", async () => {
    const result = await client.listPrompts();
    expect(result.prompts.map((prompt) => prompt.name).sort()).toEqual(
      cases.map((entry) => entry.name).sort(),
    );
  });

  for (const entry of cases) {
    it(`${entry.name} consumes and interpolates its validated arguments`, async () => {
      const text = getText(await client.getPrompt({ name: entry.name, arguments: entry.args }));
      for (const marker of entry.expected) expect(text).toContain(marker);
      expect(text).not.toMatch(/\{\{[^}]+\}\}/);
    });
  }

  it("uses a clear fallback when the optional footprint library path is omitted", async () => {
    const text = getText(
      await client.getPrompt({
        name: "create_footprint_guide",
        arguments: { component: "SOT-23" },
      }),
    );
    expect(text).toContain("Not specified");
    expect(text).not.toContain("undefined");
  });
});

describe("KiCad resources", () => {
  let client: Client;
  let close: () => Promise<void>;
  let forcedFailure: BackendResult | undefined;
  let lastSignal: AbortSignal | undefined;
  const calls: Array<{ command: string; params: Record<string, unknown> }> = [];

  const backend: CommandFunction = async (command, params, signal) => {
    lastSignal = signal;
    calls.push({ command, params });
    if (forcedFailure) return forcedFailure;

    const results: Record<string, BackendResult> = {
      get_project_info: { success: true, project: { name: "Demo" } },
      get_backend_state: { success: true, backend: "ipc", loadedProject: true },
      get_board_info: {
        success: true,
        board: { size: { width: 10 }, layers: ["F.Cu"], title: "Demo Board" },
      },
      get_component_list: {
        success: true,
        components: [{ reference: "R1", value: "10k", x: 1, y: 2 }],
      },
      get_layer_list: { success: true, layers: ["F.Cu", "B.Cu"] },
      get_board_extents: { success: true, width: 10, height: 20 },
      get_board_2d_view: {
        success: true,
        format: "svg",
        imageData: Buffer.from("<svg>preview</svg>").toString("base64"),
      },
      get_nets_list: { success: true, nets: [{ name: "GND" }] },
      get_component_properties: { success: true, reference: "R1", value: "10k" },
      get_component_pads: { success: true, pads: [{ number: "1", net: "GND" }] },
      search_footprints: { success: true, footprints: ["R_0603"] },
      list_libraries: { success: true, libraries: ["Resistor_SMD"] },
      get_footprint_info: { success: true, info: { name: "R_0603" } },
      get_symbol_info: { success: true, symbol_info: { full_ref: "Device:R" } },
    };
    return results[command] ?? { success: false, message: `Unexpected command: ${command}` };
  };

  beforeAll(async () => {
    const server = new McpServer({ name: "resource-test", version: "1.0.0" });
    registerProjectResources(server, backend);
    registerBoardResources(server, backend);
    registerComponentResources(server, backend);
    registerLibraryResources(server, backend);
    ({ client, close } = await connect(server));
  });

  afterAll(async () => close());

  it("advertises only RFC 6570-compliant resource templates", async () => {
    const { resourceTemplates } = await client.listResourceTemplates();
    const templates = Object.fromEntries(
      resourceTemplates.map((resource) => [resource.name, resource.uriTemplate]),
    );
    expect(templates.board_extents).toBe("kicad://board/extents{?unit}");
    expect(templates.board_2d_view).toBe("kicad://board/2d-view{?format,width,height,layers}");
    expect(templates.component_library).toBe("kicad://library/footprints{?filter,library,limit}");
    expect(Object.values(templates).join("\n")).not.toMatch(/\{\w+\?\}/);
  });

  it("uses only commands present in the Python backend command router", () => {
    const resourceSources = ["project.ts", "board.ts", "component.ts", "library.ts"]
      .map((file) => readFileSync(resolve("src/resources", file), "utf8"))
      .join("\n");
    const commands = [...resourceSources.matchAll(/callKicadScript\(\s*"([a-z0-9_]+)"/g)].map(
      (match) => match[1],
    );
    const commandRouter = readFileSync(resolve("python/kicad_interface.py"), "utf8");

    expect(commands.length).toBeGreaterThan(0);
    for (const command of new Set(commands)) {
      expect(commandRouter, `Missing Python command route for ${command}`).toMatch(
        new RegExp(`"${command}"\\s*:`),
      );
    }
  });

  it("does not advertise resources that have no backend implementation", async () => {
    const [{ resources }, { resourceTemplates }] = await Promise.all([
      client.listResources(),
      client.listResourceTemplates(),
    ]);
    const names = [...resources, ...resourceTemplates].map((resource) => resource.name);
    expect(names).not.toEqual(
      expect.arrayContaining([
        "project_files",
        "board_3d_view",
        "component_groups",
        "component_visualization",
        "component_3d_model",
      ]),
    );
  });

  it("maps project status to the implemented backend-state command", async () => {
    calls.length = 0;
    lastSignal = undefined;
    const result = await client.readResource({ uri: "kicad://project/status" });
    expect(calls.at(-1)).toEqual({ command: "get_backend_state", params: {} });
    expect(lastSignal).toBeInstanceOf(AbortSignal);
    expect(result.contents[0]).toMatchObject({ mimeType: "application/json" });
  });

  it("parses RFC 6570 board-view query variables and respects SVG fallback", async () => {
    calls.length = 0;
    const result = await client.readResource({
      uri: "kicad://board/2d-view?format=png&width=640&height=480&layers=F.Cu%2CB.Cu",
    });
    expect(calls.at(-1)).toEqual({
      command: "get_board_2d_view",
      params: {
        format: "png",
        width: 640,
        height: 480,
        layers: ["F.Cu", "B.Cu"],
        responseMode: "inline",
      },
    });
    expect(result.contents[0]).toMatchObject({
      mimeType: "image/svg+xml",
      text: "<svg>preview</svg>",
    });
  });

  it("maps component connections to get_component_pads", async () => {
    calls.length = 0;
    await client.readResource({ uri: "kicad://component/R1/connections" });
    expect(calls.at(-1)).toEqual({
      command: "get_component_pads",
      params: { reference: "R1" },
    });
  });

  it("maps footprint-library search variables to search_footprints", async () => {
    calls.length = 0;
    await client.readResource({
      uri: "kicad://library/footprints?filter=0603&library=Resistor_SMD&limit=12",
    });
    expect(calls.at(-1)).toEqual({
      command: "search_footprints",
      params: { pattern: "0603", library: "Resistor_SMD", limit: 12 },
    });
  });

  it("rejects invalid template values with Invalid Params", async () => {
    await expect(
      client.readResource({ uri: "kicad://board/2d-view?width=-1" }),
    ).rejects.toMatchObject({ code: INVALID_PARAMS });
  });

  it("turns backend failures into protocol errors instead of successful error documents", async () => {
    forcedFailure = { success: false, errorDetails: "renderer crashed" };
    await expect(client.readResource({ uri: "kicad://board/info" })).rejects.toMatchObject({
      code: INTERNAL_ERROR,
    });
    forcedFailure = undefined;
  });

  it("uses the MCP resource-not-found error shape for missing resources", async () => {
    forcedFailure = {
      success: false,
      message: "Component not found",
      errorDetails: "Could not find component: U404",
    };
    await expect(
      client.readResource({ uri: "kicad://component/U404/details" }),
    ).rejects.toMatchObject({
      code: INVALID_PARAMS,
      data: { uri: "kicad://component/U404/details" },
    });
    forcedFailure = undefined;
  });
});
