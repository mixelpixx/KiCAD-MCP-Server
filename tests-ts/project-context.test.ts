import { describe, expect, it } from "vitest";
import { z } from "zod";
import { installProjectContextSupport, ProjectContextManager } from "../src/project-context.js";

describe("ProjectContextManager", () => {
  it("mints a handle when a project opens and strips it before Python dispatch", () => {
    const contexts = new ProjectContextManager();
    const opened = contexts.decorateResult("open_project", {
      success: true,
      project: { boardPath: "C:/boards/demo/demo.kicad_pcb" },
    }) as Record<string, unknown>;

    expect(opened.projectHandle).toMatch(/^kicad-project:/);
    expect(opened.projectPath).toBe("C:/boards/demo/demo.kicad_pcb");
    expect(
      contexts.prepareParams("save_project", {
        projectHandle: opened.projectHandle,
        force: true,
      }),
    ).toEqual({ force: true });
  });

  it("rejects stale handles before a project-bound operation", () => {
    const contexts = new ProjectContextManager();
    contexts.decorateResult("open_project", { success: true, boardPath: "A.kicad_pcb" });

    expect(() =>
      contexts.prepareParams("save_project", { projectHandle: "kicad-project:stale" }),
    ).toThrow(/Stale or incorrect projectHandle/);
  });

  it("invalidates the handle after close while retaining it in the close result", () => {
    const contexts = new ProjectContextManager();
    const opened = contexts.decorateResult("open_board", {
      success: true,
      boardPath: "A.kicad_pcb",
    }) as Record<string, unknown>;
    const closed = contexts.decorateResult("close_project", { success: true }) as Record<
      string,
      unknown
    >;

    expect(closed.projectHandle).toBe(opened.projectHandle);
    expect(closed.projectHandleStatus).toBe("closed");
    expect(contexts.snapshot()).toEqual({ projectHandle: null, projectPath: null });
  });

  it("keeps omitted handles backward compatible", () => {
    const contexts = new ProjectContextManager();
    expect(contexts.prepareParams("save_project", { force: false })).toEqual({ force: false });
  });

  it("does not replace the active project path with an export artifact", () => {
    const contexts = new ProjectContextManager();
    contexts.decorateResult("open_project", {
      success: true,
      project: { boardPath: "C:/boards/demo/demo.kicad_pcb" },
    });

    contexts.decorateResult("export_gerber", {
      success: true,
      path: "C:/boards/demo/gerbers/demo-F_Cu.gbr",
    });

    expect(contexts.snapshot().projectPath).toBe("C:/boards/demo/demo.kicad_pcb");
  });
});

describe("installProjectContextSupport", () => {
  it("adds the handle schema and validates before invoking a project-aware handler", async () => {
    const contexts = new ProjectContextManager();
    const registrations = new Map<string, { config: any; handler: any }>();
    const fakeServer = {
      registerTool(name: string, config: unknown, handler: unknown) {
        registrations.set(name, { config, handler });
      },
    };

    installProjectContextSupport(fakeServer as any, contexts);
    (fakeServer as any).registerTool(
      "save_project",
      { inputSchema: z.object({ force: z.boolean().optional() }) },
      async (args: unknown) => args,
    );

    const registration = registrations.get("save_project")!;
    expect(registration.config.inputSchema.safeParse({ projectHandle: "x" }).success).toBe(true);
    await expect(registration.handler({ projectHandle: "x" }, {})).rejects.toThrow(
      /No project is associated/,
    );
  });
});
