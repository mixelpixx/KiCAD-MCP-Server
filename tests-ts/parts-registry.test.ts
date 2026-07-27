import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mkdtempSync, readFileSync, rmSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { getCategory, getToolCategory, isRoutedTool } from "../src/tools/registry.js";
import {
  assetUrlAllowed,
  filenameForAsset,
  registerPartsRegistryTools,
} from "../src/tools/parts-registry.js";

// The parts-registry integration (issue #297) exposes three tools for checking
// the open PartReel registry before generating a custom footprint/symbol.
const PARTS_REGISTRY_TOOLS = [
  "search_parts_registry",
  "get_registry_part",
  "download_registry_part",
];

describe("parts-registry category", () => {
  it("is registered with a name, description, and its three tools", () => {
    const category = getCategory("parts-registry");
    expect(category).toBeDefined();
    expect(category?.description.length).toBeGreaterThan(0);
    expect(category?.tools).toEqual(PARTS_REGISTRY_TOOLS);
  });

  it("maps each tool back to the parts-registry category", () => {
    for (const tool of PARTS_REGISTRY_TOOLS) {
      expect(isRoutedTool(tool)).toBe(true);
      expect(getToolCategory(tool)).toBe("parts-registry");
    }
  });
});

// ---- unit tests: filename derivation -------------------------------------- //

const FP = { fileKey: "footprint", defaultExt: ".kicad_mod", allowedExts: [".kicad_mod"] };
const M3D = { fileKey: "model_3d", defaultExt: ".step", allowedExts: [".step", ".stp", ".glb"] };

describe("filenameForAsset", () => {
  it("keeps the remote basename when its extension matches the requested format", () => {
    expect(filenameForAsset("https://partreel.com/f/R_0603.kicad_mod", "r0603", FP)).toBe(
      "R_0603.kicad_mod",
    );
  });

  it("keeps .glb for a step-format request (web preview variant)", () => {
    expect(filenameForAsset("https://assets.partreel.com/x/part.glb", "part", M3D)).toBe(
      "part.glb",
    );
  });

  it("is case-insensitive about the remote extension", () => {
    expect(filenameForAsset("https://partreel.com/f/PART.KICAD_MOD", "part", FP)).toBe(
      "PART.KICAD_MOD",
    );
  });

  it("falls back to id + default extension when the registry supplies a foreign extension", () => {
    // A hostile index must not turn a footprint request into an executable or dotfile.
    expect(filenameForAsset("https://evil.example/x/payload.ps1", "r0603", FP)).toBe(
      "r0603.kicad_mod",
    );
    expect(filenameForAsset("https://evil.example/x/setup.exe", "r0603", FP)).toBe(
      "r0603.kicad_mod",
    );
    expect(filenameForAsset("https://evil.example/x/.bashrc", "r0603", FP)).toBe("r0603.kicad_mod");
  });

  it("falls back for extensionless paths and non-URLs, sanitizing the id", () => {
    expect(filenameForAsset("https://partreel.com/f/noext", "a b/c", FP)).toBe("a_b_c.kicad_mod");
    expect(filenameForAsset("not a url", "id", M3D)).toBe("id.step");
  });
});

// ---- unit tests: asset host restriction ----------------------------------- //

describe("assetUrlAllowed", () => {
  const BASE = "https://registry.test/api/v1";

  it("allows the API host itself and its subdomains", () => {
    expect(assetUrlAllowed("https://registry.test/f/a.kicad_mod", BASE)).toBe(true);
    expect(assetUrlAllowed("https://assets.registry.test/f/a.step", BASE)).toBe(true);
  });

  it("rejects foreign hosts, lookalike suffixes, and non-URLs", () => {
    expect(assetUrlAllowed("https://evil.example/f/a.kicad_mod", BASE)).toBe(false);
    expect(assetUrlAllowed("https://notregistry.test.evil.example/x", BASE)).toBe(false);
    // Suffix without a dot boundary must not match ("evilregistry.test").
    expect(assetUrlAllowed("https://evilregistry.test/x", BASE)).toBe(false);
    expect(assetUrlAllowed("not a url", BASE)).toBe(false);
  });

  it("rejects protocol downgrades unless the API itself is http (local dev)", () => {
    expect(assetUrlAllowed("http://registry.test/f/a.kicad_mod", BASE)).toBe(false);
    expect(
      assetUrlAllowed("http://localhost:8080/f/a.kicad_mod", "http://localhost:8080/api"),
    ).toBe(true);
  });

  it("honours the PARTS_REGISTRY_ASSET_HOSTS allow-list", () => {
    process.env.PARTS_REGISTRY_ASSET_HOSTS = "cdn.other.example";
    try {
      expect(assetUrlAllowed("https://cdn.other.example/f/a.step", BASE)).toBe(true);
      expect(assetUrlAllowed("https://other.example/f/a.step", BASE)).toBe(false);
    } finally {
      delete process.env.PARTS_REGISTRY_ASSET_HOSTS;
    }
  });
});

// ---- behavior tests: tool handlers over a stubbed fetch ------------------- //

type ToolResult = { content: { type: string; text: string }[]; isError?: boolean };
type ToolHandler = (args: any) => Promise<ToolResult>;

function captureTools(): Map<string, ToolHandler> {
  const tools = new Map<string, ToolHandler>();
  const fakeServer = {
    tool: (name: string, _desc: string, _schema: unknown, handler: ToolHandler) => {
      tools.set(name, handler);
    },
  };
  registerPartsRegistryTools(fakeServer as any);
  return tools;
}

const INDEX = {
  parts: [
    {
      id: "jst_ph_4pin",
      name: "JST PH 4-pin",
      category: "connector",
      keywords: "jst ph header",
      verified: true,
      pins: 4,
    },
    {
      id: "cern_tps26600pwpt",
      name: "TPS26600PWP",
      category: "power",
      manufacturer: "Texas Instruments",
      keywords: ["efuse", "protection"],
      verified: true,
    },
    { id: "r_0603", name: "Resistor 0603", category: "passive", keywords: "resistor smd" },
  ],
};

/** Per-URL fetch stub; every path is deterministic and never touches the network. */
function stubFetch(routes: Record<string, () => Response>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: any) => {
      const url = String(input);
      for (const [prefix, make] of Object.entries(routes)) {
        if (url.startsWith(prefix)) return make();
      }
      throw new Error(`unexpected fetch in test: ${url}`);
    }),
  );
}

describe("parts-registry tool handlers (stubbed fetch)", () => {
  let tools: Map<string, ToolHandler>;
  let dest: string;

  beforeEach(() => {
    // Unique API base per test defeats the in-module parts-list cache.
    process.env.PARTREEL_API_BASE = `https://registry.test/api-${Math.random().toString(36).slice(2)}`;
    tools = captureTools();
    dest = mkdtempSync(join(tmpdir(), "partreel-test-"));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    delete process.env.PARTREEL_API_BASE;
    rmSync(dest, { recursive: true, force: true });
  });

  const base = () => process.env.PARTREEL_API_BASE!;

  it("search filters case-insensitively over name/keywords/manufacturer", async () => {
    stubFetch({ [base()]: () => Response.json(INDEX) });
    const res = await tools.get("search_parts_registry")!({ query: "TEXAS", limit: 10 });
    expect(res.isError).toBeFalsy();
    expect(res.content[0].text).toContain("cern_tps26600pwpt");
    expect(res.content[0].text).not.toContain("jst_ph_4pin");
  });

  it("search honours the category filter and reports no-match cleanly", async () => {
    stubFetch({ [base()]: () => Response.json(INDEX) });
    const hit = await tools.get("search_parts_registry")!({
      query: "jst",
      category: "connector",
      limit: 10,
    });
    expect(hit.content[0].text).toContain("jst_ph_4pin");
    const miss = await tools.get("search_parts_registry")!({
      query: "jst",
      category: "passive",
      limit: 10,
    });
    expect(miss.content[0].text.toLowerCase()).toContain("no registry parts found");
  });

  it("download writes the asset with the format-matched remote filename", async () => {
    const detailUrl = `${base()}/parts/r_0603.json`;
    stubFetch({
      [detailUrl]: () =>
        Response.json({
          id: "r_0603",
          files: { footprint: "https://assets.registry.test/lib/R_0603.kicad_mod" },
          license: "CC-BY-4.0",
        }),
      "https://assets.registry.test/": () => new Response("(footprint content)"),
    });
    const res = await tools.get("download_registry_part")!({
      id: "r_0603",
      format: "kicad_mod",
      dest_dir: dest,
    });
    expect(res.isError).toBeFalsy();
    const saved = join(dest, "R_0603.kicad_mod");
    expect(res.content[0].text).toContain("R_0603.kicad_mod");
    expect(readFileSync(saved, "utf-8")).toBe("(footprint content)");
  });

  it("download falls back to id + format extension when the remote name is foreign", async () => {
    const detailUrl = `${base()}/parts/r_0603.json`;
    stubFetch({
      [detailUrl]: () =>
        Response.json({
          id: "r_0603",
          files: { footprint: "https://assets.registry.test/lib/payload.ps1" },
        }),
      "https://assets.registry.test/": () => new Response("still footprint text"),
    });
    const res = await tools.get("download_registry_part")!({
      id: "r_0603",
      format: "kicad_mod",
      dest_dir: dest,
    });
    expect(res.isError).toBeFalsy();
    expect(readFileSync(join(dest, "r_0603.kicad_mod"), "utf-8")).toBe("still footprint text");
    expect(res.content[0].text).toContain(join(dest, "r_0603.kicad_mod"));
  });

  it("download refuses assets on hosts outside the registry", async () => {
    const detailUrl = `${base()}/parts/r_0603.json`;
    const fetchSpy = vi.fn(async (input: any) => {
      const url = String(input);
      if (url.startsWith(detailUrl)) {
        return Response.json({
          id: "r_0603",
          files: { footprint: "https://evil.example/x/a.kicad_mod" },
        });
      }
      throw new Error(`asset fetch should not happen: ${url}`);
    });
    vi.stubGlobal("fetch", fetchSpy);
    const res = await tools.get("download_registry_part")!({
      id: "r_0603",
      format: "kicad_mod",
      dest_dir: dest,
    });
    expect(res.isError).toBe(true);
    expect(res.content[0].text).toContain("Refusing to download");
    expect(fetchSpy).toHaveBeenCalledTimes(1); // detail only — no asset fetch
  });

  it("download rejects oversized assets by declared content-length", async () => {
    const detailUrl = `${base()}/parts/big.json`;
    stubFetch({
      [detailUrl]: () =>
        Response.json({ id: "big", files: { model_3d: "https://registry.test/big.step" } }),
      "https://registry.test/big.step": () =>
        new Response("x", { headers: { "content-length": String(200 * 1024 * 1024) } }),
    });
    const res = await tools.get("download_registry_part")!({
      id: "big",
      format: "step",
      dest_dir: dest,
    });
    expect(res.isError).toBe(true);
    expect(res.content[0].text).toContain("too large");
  });

  it("download reports a missing format cleanly", async () => {
    const detailUrl = `${base()}/parts/sym_only.json`;
    stubFetch({
      [detailUrl]: () =>
        Response.json({ id: "sym_only", files: { symbol: "https://registry.test/s.kicad_sym" } }),
    });
    const res = await tools.get("download_registry_part")!({
      id: "sym_only",
      format: "step",
      dest_dir: dest,
    });
    expect(res.isError).toBe(true);
    expect(res.content[0].text).toContain('No "step" file');
  });

  it("download validates the destination directory before any fetch", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const res = await tools.get("download_registry_part")!({
      id: "r_0603",
      format: "kicad_mod",
      dest_dir: join(dest, "does-not-exist"),
    });
    expect(res.isError).toBe(true);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("get_registry_part summarizes detail and surfaces fetch errors", async () => {
    const detailUrl = `${base()}/parts/jst_ph_4pin.json`;
    stubFetch({
      [detailUrl]: () =>
        Response.json({
          id: "jst_ph_4pin",
          description: "JST PH 4-pin right angle",
          files: { footprint: "https://registry.test/f.kicad_mod" },
          license: "CC-BY-4.0",
        }),
    });
    const ok = await tools.get("get_registry_part")!({ id: "jst_ph_4pin" });
    expect(ok.isError).toBeFalsy();
    expect(ok.content[0].text).toContain("JST PH 4-pin right angle");
    expect(ok.content[0].text).toContain("CC-BY-4.0");

    stubFetch({
      [detailUrl]: () => new Response("nope", { status: 404, statusText: "Not Found" }),
    });
    const bad = await tools.get("get_registry_part")!({ id: "jst_ph_4pin" });
    expect(bad.isError).toBe(true);
    expect(bad.content[0].text).toContain("404");
  });
});

// ---------------------------------------------------------------------------
// Adversarial download-safety cases (added at merge time).
//
// download_registry_part writes third-party bytes to the user's disk, so the
// two guards on that path deserve explicit hostile input rather than only
// happy-path coverage.
// ---------------------------------------------------------------------------

describe("download safety", () => {
  const FP = {
    fileKey: "footprint",
    defaultExt: ".kicad_mod",
    allowedExts: [".kicad_mod"],
  };

  describe("filenameForAsset cannot escape the output directory", () => {
    it("strips directory components from a traversal path", () => {
      expect(
        filenameForAsset("https://assets.partreel.com/../../../etc/passwd.kicad_mod", "ID", FP),
      ).toBe("passwd.kicad_mod");
    });

    it("neutralises percent-encoded separators", () => {
      // %2F survives URL.pathname undecoded; the character filter must turn it
      // into something that cannot act as a separator.
      const name = filenameForAsset(
        "https://assets.partreel.com/a%2F..%2F..%2Fevil.kicad_mod",
        "ID",
        FP,
      );
      expect(name).not.toContain("/");
      expect(name).not.toContain("\\");
    });

    it("falls back to the sanitised id when the basename has no valid extension", () => {
      expect(filenameForAsset("https://assets.partreel.com/..", "ID", FP)).toBe("ID.kicad_mod");
    });

    it("never returns a name containing a path separator", () => {
      for (const url of [
        "https://assets.partreel.com/sub/dir/ok.kicad_mod",
        "https://assets.partreel.com/..%5C..%5Cwin.kicad_mod",
        "https://assets.partreel.com/./../x.kicad_mod",
      ]) {
        const name = filenameForAsset(url, "ID", FP);
        expect(name.includes("/")).toBe(false);
        expect(name.includes("\\")).toBe(false);
      }
    });
  });

  describe("assetUrlAllowed", () => {
    const base = "https://partreel.com/api";

    it("accepts the API host and its subdomains", () => {
      expect(assetUrlAllowed("https://partreel.com/x.kicad_mod", base)).toBe(true);
      expect(assetUrlAllowed("https://assets.partreel.com/x.kicad_mod", base)).toBe(true);
    });

    it("rejects a host that merely ends with the API host", () => {
      // The bug a naive endsWith("partreel.com") would introduce.
      expect(assetUrlAllowed("https://notpartreel.com/x.kicad_mod", base)).toBe(false);
      expect(assetUrlAllowed("https://evil-partreel.com/x.kicad_mod", base)).toBe(false);
    });

    it("rejects unrelated hosts and plaintext http", () => {
      expect(assetUrlAllowed("https://evil.com/x.kicad_mod", base)).toBe(false);
      expect(assetUrlAllowed("http://partreel.com/x.kicad_mod", base)).toBe(false);
    });

    it("rejects malformed urls rather than throwing", () => {
      expect(assetUrlAllowed("not a url", base)).toBe(false);
      expect(assetUrlAllowed("", base)).toBe(false);
    });
  });
});
