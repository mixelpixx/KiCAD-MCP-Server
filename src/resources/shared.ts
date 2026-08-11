import {
  INTERNAL_ERROR,
  INVALID_PARAMS,
  ProtocolError,
  ResourceNotFoundError,
  type Variables,
} from "@modelcontextprotocol/server";

export interface BackendResult {
  success?: boolean;
  message?: unknown;
  errorDetails?: unknown;
  [key: string]: unknown;
}

export type CommandFunction = (
  command: string,
  params: Record<string, unknown>,
  signal?: AbortSignal,
) => Promise<unknown>;

const NOT_FOUND_PATTERN =
  /\b(?:not found|could not find|does not exist|unknown (?:component|resource))\b/i;

/**
 * Convert a failed backend response into a protocol error. Returning an error
 * document from resources/read makes a failed read look successful to MCP
 * clients and prevents their normal error handling from running.
 */
export function requireBackendSuccess(value: unknown, action: string, uri: URL): BackendResult {
  const result =
    typeof value === "object" && value !== null
      ? (value as BackendResult)
      : ({} satisfies BackendResult);
  if (result?.success === true) return result;

  const detailValue = result?.errorDetails ?? result?.message;
  const details = typeof detailValue === "string" ? detailValue : "KiCad backend returned an error";
  const message = `${action}: ${details}`;

  if (NOT_FOUND_PATTERN.test(details)) {
    throw new ResourceNotFoundError(uri.href, message);
  }

  throw new ProtocolError(INTERNAL_ERROR, message, { uri: uri.href });
}

export function jsonContents(uri: URL, data: unknown) {
  return {
    contents: [
      {
        uri: uri.href,
        text: JSON.stringify(data),
        mimeType: "application/json",
      },
    ],
  };
}

export function templateString(
  variables: Variables,
  name: string,
  uri: URL,
  options: { required?: boolean; defaultValue?: string } = {},
): string | undefined {
  const value = variables[name];
  if (Array.isArray(value)) {
    throw new ProtocolError(INVALID_PARAMS, `Resource parameter '${name}' must occur once`, {
      uri: uri.href,
      parameter: name,
    });
  }

  if (value === undefined || value === "") {
    if (options.defaultValue !== undefined) return options.defaultValue;
    if (!options.required) return undefined;
    throw new ProtocolError(INVALID_PARAMS, `Resource parameter '${name}' is required`, {
      uri: uri.href,
      parameter: name,
    });
  }

  try {
    return decodeURIComponent(value);
  } catch {
    throw new ProtocolError(INVALID_PARAMS, `Resource parameter '${name}' is not URI encoded`, {
      uri: uri.href,
      parameter: name,
    });
  }
}

export function optionalPositiveInteger(
  variables: Variables,
  name: string,
  uri: URL,
): number | undefined {
  const raw = templateString(variables, name, uri);
  if (raw === undefined) return undefined;

  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new ProtocolError(
      INVALID_PARAMS,
      `Resource parameter '${name}' must be a positive integer`,
      {
        uri: uri.href,
        parameter: name,
      },
    );
  }
  return value;
}

export function oneOfTemplateStrings<const T extends string>(
  variables: Variables,
  name: string,
  uri: URL,
  allowed: readonly T[],
  defaultValue: T,
): T {
  const value = templateString(variables, name, uri, { defaultValue });
  if (!allowed.includes(value as T)) {
    throw new ProtocolError(
      INVALID_PARAMS,
      `Resource parameter '${name}' must be one of: ${allowed.join(", ")}`,
      { uri: uri.href, parameter: name },
    );
  }
  return value as T;
}

export function requiredResultString(result: BackendResult, name: string, uri: URL): string {
  const value = result[name];
  if (typeof value !== "string") {
    throw new ProtocolError(INTERNAL_ERROR, `KiCad backend omitted string field '${name}'`, {
      uri: uri.href,
      field: name,
    });
  }
  return value;
}

export const PRIVATE_LIVE_JSON = {
  mimeType: "application/json",
  cacheHint: { ttlMs: 0, cacheScope: "private" as const },
};

export const PRIVATE_LIVE_IMAGE = {
  cacheHint: { ttlMs: 0, cacheScope: "private" as const },
};

export const PUBLIC_LIBRARY_JSON = {
  mimeType: "application/json",
  cacheHint: { ttlMs: 300_000, cacheScope: "public" as const },
};
