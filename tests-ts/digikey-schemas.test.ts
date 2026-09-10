import { describe, expect, it } from "vitest";
import type { ZodTypeAny } from "zod";
import { registerDigiKeyApiTools } from "../src/tools/digikey-api.js";
import {
  computeCommandTimeout,
  DEFAULT_COMMAND_TIMEOUT_MS,
  LONG_COMMAND_TIMEOUT_MS,
} from "../src/command-timeout.js";

// The central security claim of the Digi-Key integration is that no credential
// can be passed as a tool argument, and that claim lives entirely in the shape
// of the three schemas below. Nothing asserted it: a later edit adding a
// convenience `clientSecret` field would ship green.
//
// The schemas are read back off a stub server rather than exported separately,
// so this checks what is actually registered.

interface RegisteredTool {
  name: string;
  description: string;
  schema: Record<string, ZodTypeAny>;
}

function registeredTools(): RegisteredTool[] {
  const tools: RegisteredTool[] = [];
  const server = {
    tool(name: string, description: string, schema: Record<string, ZodTypeAny>) {
      tools.push({ name, description, schema });
    },
  };
  registerDigiKeyApiTools(server as never, () => Promise.resolve({}));
  return tools;
}

// "keywords" deliberately does not match: the pattern targets credential names
// (clientId, clientSecret, apiKey, accessToken), not any key with "key" in it.
const CREDENTIAL_NAME = /client|secret|api_?key|token|password|credential/i;

/** Every property name in a schema, including inside a nested object schema. */
function schemaKeys(schema: Record<string, ZodTypeAny>): string[] {
  const keys: string[] = [];
  for (const [name, field] of Object.entries(schema)) {
    keys.push(name);
    let inner: unknown = field;
    // Unwrap optional/partial/default/describe layers to reach an object shape.
    for (let depth = 0; depth < 10; depth++) {
      const def = (inner as { _def?: Record<string, unknown> })?._def;
      if (!def) break;
      if (typeof def.shape === "function") {
        keys.push(...Object.keys((def.shape as () => Record<string, unknown>)()));
        break;
      }
      if (def.innerType) inner = def.innerType;
      else if (def.schema) inner = def.schema;
      else break;
    }
  }
  return keys;
}

describe("Digi-Key tool schemas", () => {
  it("registers exactly the three documented tools", () => {
    expect(registeredTools().map((t) => t.name)).toEqual([
      "digikey_test_connection",
      "digikey_search_parts",
      "digikey_check_library_availability",
    ]);
  });

  it("declares no argument that could carry a credential", () => {
    const offenders: string[] = [];
    for (const tool of registeredTools()) {
      for (const key of schemaKeys(tool.schema)) {
        if (CREDENTIAL_NAME.test(key)) offenders.push(`${tool.name}.${key}`);
      }
    }
    expect(
      offenders,
      "Digi-Key credentials come from DIGIKEY_CLIENT_ID / DIGIKEY_CLIENT_SECRET in the " +
        "server environment. A schema field able to carry one puts it in the conversation " +
        "transcript and the MCP log.",
    ).toEqual([]);
  });

  it("declares only the expected arguments", () => {
    // Stricter than the regex above, which can only catch names it anticipated.
    const byName = new Map(registeredTools().map((t) => [t.name, Object.keys(t.schema).sort()]));
    expect(byName.get("digikey_test_connection")).toEqual(["locale"]);
    expect(byName.get("digikey_search_parts")).toEqual([
      "keywords",
      "limit",
      "locale",
      "offset",
      "preferPackaging",
    ]);
    expect(byName.get("digikey_check_library_availability")).toEqual([
      "libraryPath",
      "locale",
      "maxSymbols",
      "preferPackaging",
      "searchByMpnFirst",
      "symbols",
    ]);
  });

  it("looks inside the nested locale object", () => {
    // Guards the unwrapping in schemaKeys: if it stopped reaching nested
    // properties the credential check above would quietly go vacuous for them.
    const search = registeredTools().find((t) => t.name === "digikey_search_parts")!;
    expect(schemaKeys(search.schema)).toEqual(
      expect.arrayContaining(["site", "language", "currency"]),
    );
  });

  it("does not promise that a credential argument is rejected", () => {
    // zod strips unknown keys, so a credential passed anyway is ignored, not
    // refused. The Python side returns a warning naming it; calling that
    // "rejected" would tell a caller their key never left their machine.
    // ("rejected credentials" in the connection-test description is a different
    // thing entirely -- that is Digi-Key rejecting them.)
    const claimsRejection = /reject\w*\s+(as\s+)?(an?\s+)?(tool\s+)?(argument|parameter)/i;
    for (const tool of registeredTools()) {
      expect(tool.description, tool.name).not.toMatch(claimsRejection);
    }
  });
});

describe("the library sweep's timeout budget", () => {
  it("is not left on the 30 s default", () => {
    // At the schema default of 25 symbols the client's own throttle spends
    // several seconds before any network latency, and the fallback can double
    // the request count. Worse than timing out: the Python worker is
    // single-threaded and keeps sweeping, so its late response is delivered to
    // whichever tool call is pending by then.
    const timeout = computeCommandTimeout("digikey_check_library_availability", {});
    expect(timeout).toBeGreaterThan(DEFAULT_COMMAND_TIMEOUT_MS);
    expect(timeout).toBe(LONG_COMMAND_TIMEOUT_MS);
  });

  it("leaves the two cheap Digi-Key tools on the default", () => {
    // Both are a single search, so a long timeout would only delay reporting a
    // hung request.
    expect(computeCommandTimeout("digikey_search_parts", {})).toBe(DEFAULT_COMMAND_TIMEOUT_MS);
    expect(computeCommandTimeout("digikey_test_connection", {})).toBe(DEFAULT_COMMAND_TIMEOUT_MS);
  });
});
