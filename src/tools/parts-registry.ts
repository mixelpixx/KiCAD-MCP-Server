/**
 * Open parts registry tools for KiCAD MCP server
 *
 * Lets the AI check an open, gate-verified parts registry BEFORE generating a
 * custom footprint/symbol from scratch (see issue #297). If a verified part
 * already exists it can be searched, inspected, and its KiCAD files downloaded
 * directly to disk — no auth, no API key.
 *
 * The default registry is PartReel (https://partreel.com), a CC-BY / no-auth
 * catalog of 18k+ gate-verified KiCAD parts. The integration is vendor-neutral:
 * point PARTREEL_API_BASE (or PARTS_REGISTRY_API_BASE) at any registry that
 * serves the same simple JSON shape:
 *   GET <base>/parts.json          -> { parts: [ { id, name, ... } ] }
 *   GET <base>/parts/{id}.json     -> { files: {...}, datasheet, license, ... }
 *
 * Uses Node's global fetch (Node 18+); no extra dependencies.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { existsSync, statSync, writeFileSync } from "fs";
import { basename, join } from "path";
import { logger } from "../logger.js";

// ---- registry configuration --------------------------------------------- //

const DEFAULT_API_BASE = "https://partreel.com/api/v1";

/** Base URL of the parts registry API (trailing slashes trimmed). */
function apiBase(): string {
  const raw =
    process.env.PARTREEL_API_BASE || process.env.PARTS_REGISTRY_API_BASE || DEFAULT_API_BASE;
  return raw.replace(/\/+$/, "");
}

// ---- types --------------------------------------------------------------- //

interface RegistryPart {
  id: string;
  name?: string;
  category?: string;
  family?: string;
  manufacturer?: string;
  keywords?: string | string[];
  verified?: boolean;
  pins?: number | string;
  page?: string;
  api?: string;
  // Some registries may surface a 3D flag directly on the list entry.
  model_3d?: unknown;
  has_3d?: unknown;
  files?: { model_3d?: unknown };
}

interface RegistryPartDetail {
  id?: string;
  name?: string;
  description?: string;
  files?: Record<string, string>;
  datasheet?: string;
  license?: string;
  provenance?: Record<string, unknown>;
  parameters?: Record<string, unknown>;
}

// ---- in-module cache for the parts list --------------------------------- //

const PARTS_LIST_TTL_MS = 10 * 60 * 1000; // ~10 minutes

let partsListCache: { fetchedAt: number; base: string; parts: RegistryPart[] } | null = null;

async function fetchJson(url: string): Promise<any> {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} ${res.statusText} for ${url}`);
  }
  return res.json();
}

/** Fetch (and cache) the full parts list. Cache is keyed on the API base. */
async function getPartsList(force = false): Promise<RegistryPart[]> {
  const base = apiBase();
  const fresh =
    partsListCache &&
    partsListCache.base === base &&
    Date.now() - partsListCache.fetchedAt < PARTS_LIST_TTL_MS;

  if (!force && fresh) {
    return partsListCache!.parts;
  }

  const url = `${base}/parts.json`;
  logger.info(`Fetching parts registry index: ${url}`);
  const data = await fetchJson(url);
  const parts: RegistryPart[] = Array.isArray(data?.parts) ? data.parts : [];
  partsListCache = { fetchedAt: Date.now(), base, parts };
  logger.info(`Cached ${parts.length} registry parts`);
  return parts;
}

async function getPartDetail(id: string): Promise<RegistryPartDetail> {
  const url = `${apiBase()}/parts/${encodeURIComponent(id)}.json`;
  logger.info(`Fetching registry part detail: ${url}`);
  return (await fetchJson(url)) as RegistryPartDetail;
}

// ---- helpers ------------------------------------------------------------- //

function keywordsToString(keywords: string | string[] | undefined): string {
  if (!keywords) return "";
  return Array.isArray(keywords) ? keywords.join(" ") : keywords;
}

/** Best-effort detection of whether a list entry advertises a 3D model. */
function listHas3d(p: RegistryPart): boolean {
  return Boolean(p.model_3d || p.has_3d || (p.files && p.files.model_3d));
}

/** Map the requested format to the detail `files` key and a default extension. */
const FORMAT_MAP: Record<string, { fileKey: string; defaultExt: string }> = {
  kicad_mod: { fileKey: "footprint", defaultExt: ".kicad_mod" },
  kicad_sym: { fileKey: "symbol", defaultExt: ".kicad_sym" },
  step: { fileKey: "model_3d", defaultExt: ".step" },
};

function sanitizeId(id: string): string {
  return id.replace(/[^A-Za-z0-9._-]+/g, "_");
}

/** Derive a filename for a downloaded asset from its URL, with a fallback. */
function filenameForAsset(url: string, id: string, defaultExt: string): string {
  try {
    const path = new URL(url).pathname;
    const base = basename(path);
    if (base && /\.[A-Za-z0-9]+$/.test(base)) {
      return base;
    }
  } catch {
    // Not an absolute URL — fall through to the default name.
  }
  return `${sanitizeId(id)}${defaultExt}`;
}

// ---- tool registration --------------------------------------------------- //

export function registerPartsRegistryTools(server: McpServer): void {
  // ── search_parts_registry ─────────────────────────────────────────────── //
  server.tool(
    "search_parts_registry",
    `Search an open, gate-verified parts registry for existing KiCAD parts BEFORE
generating a custom footprint/symbol from scratch.

Default registry: PartReel (https://partreel.com) — 18k+ verified parts, no auth.
Override with the PARTREEL_API_BASE environment variable to point at any
compatible registry. Matches are case-insensitive substrings over the part
name, keywords, family, and manufacturer.`,
    {
      query: z
        .string()
        .describe("Free-text search (e.g. 'STM32F103', 'USB-C receptacle', 'LM358')"),
      category: z
        .string()
        .optional()
        .describe("Optional category/family filter (e.g. 'Connectors', 'MCU')"),
      limit: z.number().optional().default(10).describe("Maximum number of results to return"),
    },
    async (args: { query: string; category?: string; limit?: number }) => {
      const limit = args.limit ?? 10;
      try {
        const parts = await getPartsList();
        const q = args.query.toLowerCase();
        const cat = args.category?.toLowerCase();

        const matches = parts.filter((p) => {
          if (cat) {
            const inCategory =
              (p.category ?? "").toLowerCase().includes(cat) ||
              (p.family ?? "").toLowerCase().includes(cat);
            if (!inCategory) return false;
          }
          const haystack = [
            p.name ?? "",
            keywordsToString(p.keywords),
            p.family ?? "",
            p.manufacturer ?? "",
          ]
            .join(" ")
            .toLowerCase();
          return haystack.includes(q);
        });

        if (matches.length === 0) {
          return {
            content: [
              {
                type: "text",
                text:
                  `No registry parts found for "${args.query}"` +
                  (args.category ? ` in category "${args.category}"` : "") +
                  `.\n\nSearched ${parts.length} parts at ${apiBase()}. ` +
                  `If nothing matches, generating a custom footprint/symbol is the fallback.`,
              },
            ],
          };
        }

        const shown = matches.slice(0, limit);
        const list = shown
          .map((p) => {
            const label = p.name || p.id;
            const meta = [p.category || p.family, p.manufacturer].filter(Boolean).join(" · ");
            const pins =
              p.pins !== undefined && p.pins !== null && `${p.pins}`.length > 0
                ? `${p.pins} pins`
                : "";
            const badges = [
              p.verified ? "✓ verified" : "unverified",
              pins,
              listHas3d(p) ? "3D ✓" : "3D —",
            ]
              .filter(Boolean)
              .join(", ");
            const links = [p.page ? `page: ${p.page}` : "", p.api ? `api: ${p.api}` : ""]
              .filter(Boolean)
              .join("  ");
            return (
              `${p.id}: ${label}${meta ? ` [${meta}]` : ""}\n` +
              `   ${badges}\n` +
              (links ? `   ${links}\n` : "")
            );
          })
          .join("\n");

        return {
          content: [
            {
              type: "text",
              text:
                `Found ${matches.length} registry part(s)` +
                (matches.length > shown.length ? ` (showing first ${shown.length})` : "") +
                `:\n\n${list}\n` +
                `Next: get_registry_part <id> for details, then download_registry_part to save files.`,
            },
          ],
        };
      } catch (error: any) {
        return {
          content: [
            {
              type: "text",
              text: `Failed to search parts registry (${apiBase()}): ${error.message || error}`,
            },
          ],
          isError: true,
        };
      }
    },
  );

  // ── get_registry_part ─────────────────────────────────────────────────── //
  server.tool(
    "get_registry_part",
    `Get full details for one registry part by id: description, downloadable files
(footprint/symbol/3D), datasheet, license, and provenance. Use the id returned
by search_parts_registry.`,
    {
      id: z.string().describe("Registry part id (from search_parts_registry)"),
    },
    async (args: { id: string }) => {
      try {
        const detail = await getPartDetail(args.id);

        const files = detail.files || {};
        const fileLines = Object.keys(files).length
          ? Object.entries(files)
              .map(([k, v]) => `  - ${k}: ${v}`)
              .join("\n")
          : "  (none listed)";

        const provenance = detail.provenance || {};
        const provLines = Object.keys(provenance).length
          ? Object.entries(provenance)
              .map(([k, v]) => `  - ${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
              .join("\n")
          : "  (none listed)";

        const parameters = detail.parameters || {};
        const paramLines = Object.keys(parameters).length
          ? "\n\nParameters:\n" +
            Object.entries(parameters)
              .map(([k, v]) => `  - ${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
              .join("\n")
          : "";

        return {
          content: [
            {
              type: "text",
              text:
                `${detail.name || detail.id || args.id}\n` +
                (detail.description ? `${detail.description}\n` : "") +
                `\nLicense: ${detail.license || "unknown"}\n` +
                (detail.datasheet ? `Datasheet: ${detail.datasheet}\n` : "") +
                `\nFiles:\n${fileLines}\n` +
                `\nProvenance:\n${provLines}` +
                paramLines +
                `\n\nTo save files: download_registry_part id="${detail.id || args.id}" ` +
                `format="kicad_mod|kicad_sym|step" dest_dir="<existing dir>".`,
            },
          ],
        };
      } catch (error: any) {
        return {
          content: [
            {
              type: "text",
              text: `Failed to get registry part "${args.id}" (${apiBase()}): ${error.message || error}`,
            },
          ],
          isError: true,
        };
      }
    },
  );

  // ── download_registry_part ────────────────────────────────────────────── //
  server.tool(
    "download_registry_part",
    `Download a registry part's KiCAD file to a local directory:
  - format="kicad_mod" -> footprint (.kicad_mod text)
  - format="kicad_sym" -> symbol    (.kicad_sym text)
  - format="step"      -> 3D model  (.step / .glb, downloaded from the asset host)
Files are written to dest_dir with a sensible filename; returns the saved path(s).`,
    {
      id: z.string().describe("Registry part id (from search_parts_registry)"),
      format: z
        .enum(["kicad_mod", "kicad_sym", "step"])
        .describe("Which file to download: footprint | symbol | 3D model"),
      dest_dir: z
        .string()
        .describe("Existing destination directory to write the file into (must already exist)"),
    },
    async (args: { id: string; format: "kicad_mod" | "kicad_sym" | "step"; dest_dir: string }) => {
      // Validate destination directory up front.
      if (!existsSync(args.dest_dir) || !statSync(args.dest_dir).isDirectory()) {
        return {
          content: [
            {
              type: "text",
              text: `Destination directory does not exist or is not a directory: ${args.dest_dir}`,
            },
          ],
          isError: true,
        };
      }

      try {
        const detail = await getPartDetail(args.id);
        const files = detail.files || {};
        const mapping = FORMAT_MAP[args.format];
        const url = files[mapping.fileKey];

        if (!url) {
          const available = Object.keys(files).join(", ") || "none";
          return {
            content: [
              {
                type: "text",
                text:
                  `No "${args.format}" file (files.${mapping.fileKey}) available for "${args.id}". ` +
                  `Available files: ${available}.`,
              },
            ],
            isError: true,
          };
        }

        logger.info(`Downloading ${args.format} for ${args.id}: ${url}`);
        const res = await fetch(url);
        if (!res.ok) {
          throw new Error(`HTTP ${res.status} ${res.statusText} for ${url}`);
        }
        const buffer = Buffer.from(await res.arrayBuffer());

        const filename = filenameForAsset(url, args.id, mapping.defaultExt);
        const savedPath = join(args.dest_dir, filename);
        writeFileSync(savedPath, buffer);
        logger.info(`Saved ${buffer.length} bytes to ${savedPath}`);

        return {
          content: [
            {
              type: "text",
              text:
                `✓ Downloaded ${args.format} for "${args.id}"\n` +
                `Source: ${url}\n` +
                `Saved: ${savedPath} (${buffer.length} bytes)` +
                (detail.license ? `\nLicense: ${detail.license}` : ""),
            },
          ],
        };
      } catch (error: any) {
        return {
          content: [
            {
              type: "text",
              text: `Failed to download registry part "${args.id}" (${args.format}): ${error.message || error}`,
            },
          ],
          isError: true,
        };
      }
    },
  );
}
