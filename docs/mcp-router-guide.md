# MCP Tool Router Pattern Guide

A practical guide for building MCP servers with 50-500+ tools without destroying context windows or confusing the LLM.

---

## The Problem

When your MCP server exposes too many tools:

1. **Token bloat**: 50 tools ≈ 30-50K tokens consumed before the user says anything
2. **Selection errors**: Claude sees `add_component`, `place_component`, `add_footprint`, `place_footprint` and guesses wrong
3. **Context starvation**: Less room for actual conversation and results
4. **Accuracy degradation**: More tools = more confusion about which to use

Real-world example: A KiCAD MCP server with 52 tools consumes ~40K tokens. An IDA Pro MCP server could easily hit 100+ tools.

---

## Solution Overview

Implement a **router pattern** within your MCP server that:

1. Exposes only essential tools directly (10-15 tools)
2. Provides discovery tools for everything else
3. Routes execution through a single `execute_tool` endpoint

**Result**: Claude sees ~18 tools instead of 100+, but can still access everything.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     MCP Client (Claude)                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      Your MCP Server                         │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              DIRECT TOOLS (Always Visible)              ││
│  │  • create_project    • open_project    • save_project   ││
│  │  • add_component     • add_track       • get_info       ││
│  │  • (10-15 high-frequency tools)                         ││
│  └─────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────┐│
│  │                    ROUTER TOOLS                         ││
│  │  • list_tool_categories   • get_category_tools          ││
│  │  • execute_tool           • search_tools                ││
│  └─────────────────────────────────────────────────────────┘│
│                              │                               │
│                              ▼                               │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              ROUTED TOOLS (Hidden)                      ││
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   ││
│  │  │  export  │ │   drc    │ │  zones   │ │ advanced │   ││
│  │  │ (8 tools)│ │(5 tools) │ │(6 tools) │ │(12 tools)│   ││
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘   ││
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐                ││
│  │  │schematic │ │  layers  │ │ graphics │  ... more      ││
│  │  │(15 tools)│ │(4 tools) │ │(10 tools)│                ││
│  │  └──────────┘ └──────────┘ └──────────┘                ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation

### Step 1: Define Your Tool Registry

Create a central registry that organizes all tools by category.

```typescript
// src/tools/registry.ts

export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: {
    type: "object";
    properties: Record<string, unknown>;
    required?: string[];
  };
  handler: (params: any) => Promise<any>;
}

export interface ToolCategory {
  name: string;
  description: string;
  tools: ToolDefinition[];
}

// Define all your categories
export const toolCategories: ToolCategory[] = [
  {
    name: "export",
    description: "Generate output files: Gerber, drill, BOM, PDF, 3D models (STEP/VRML), SVG",
    tools: [
      {
        name: "export_gerber",
        description: "Export Gerber files for PCB fabrication",
        inputSchema: {
          type: "object",
          properties: {
            output_dir: { 
              type: "string", 
              description: "Output directory path" 
            },
            layers: { 
              type: "array", 
              items: { type: "string" },
              description: "Layers to export (default: all copper + silkscreen + mask)"
            },
            format: {
              type: "string",
              enum: ["rs274x", "x2"],
              description: "Gerber format version"
            }
          },
          required: ["output_dir"]
        },
        handler: async (params) => {
          // Your implementation
          return { success: true, files: ["..."] };
        }
      },
      {
        name: "export_drill",
        description: "Export Excellon drill files",
        inputSchema: {
          type: "object",
          properties: {
            output_dir: { type: "string" },
            format: { type: "string", enum: ["excellon", "excellon2"] }
          },
          required: ["output_dir"]
        },
        handler: async (params) => { /* ... */ }
      },
      {
        name: "export_bom",
        description: "Export bill of materials as CSV or XML",
        inputSchema: { /* ... */ },
        handler: async (params) => { /* ... */ }
      },
      // ... more export tools
    ]
  },
  {
    name: "drc",
    description: "Design rule checking: clearance validation, electrical rules, manufacturing constraints",
    tools: [
      {
        name: "run_drc",
        description: "Run full design rule check on current board",
        inputSchema: {
          type: "object",
          properties: {
            report_all: { 
              type: "boolean", 
              description: "Report all violations or stop at first" 
            }
          }
        },
        handler: async (params) => { /* ... */ }
      },
      {
        name: "get_drc_errors",
        description: "Get current DRC violations without re-running check",
        inputSchema: { type: "object", properties: {} },
        handler: async (params) => { /* ... */ }
      },
      {
        name: "set_design_rules",
        description: "Configure design rules: clearance, track width, via size, etc.",
        inputSchema: {
          type: "object",
          properties: {
            min_clearance: { type: "number", description: "Minimum clearance in mm" },
            min_track_width: { type: "number", description: "Minimum track width in mm" },
            min_via_diameter: { type: "number", description: "Minimum via diameter in mm" },
            min_via_drill: { type: "number", description: "Minimum via drill size in mm" }
          }
        },
        handler: async (params) => { /* ... */ }
      }
    ]
  },
  {
    name: "zones",
    description: "Copper zones/pours: ground planes, power fills, keep-out areas",
    tools: [
      {
        name: "add_zone",
        description: "Add copper zone/pour to PCB",
        inputSchema: {
          type: "object",
          properties: {
            net_name: { type: "string", description: "Net to connect (e.g., 'GND', 'VCC')" },
            layer: { type: "string", description: "Layer name (e.g., 'F.Cu', 'B.Cu')" },
            points: {
              type: "array",
              items: {
                type: "object",
                properties: {
                  x: { type: "number" },
                  y: { type: "number" }
                }
              },
              description: "Polygon vertices in mm"
            },
            priority: { type: "number", description: "Fill priority (higher fills first)" }
          },
          required: ["net_name", "layer", "points"]
        },
        handler: async (params) => { /* ... */ }
      },
      {
        name: "fill_zones",
        description: "Recalculate and fill all copper zones",
        inputSchema: { type: "object", properties: {} },
        handler: async (params) => { /* ... */ }
      },
      {
        name: "remove_zone",
        description: "Remove a copper zone by ID",
        inputSchema: {
          type: "object",
          properties: {
            zone_id: { type: "string", description: "Zone identifier" }
          },
          required: ["zone_id"]
        },
        handler: async (params) => { /* ... */ }
      }
    ]
  },
  // Add more categories...
];
```

### Step 2: Build Lookup Maps

Create efficient lookups for routing.

```typescript
// src/tools/registry.ts (continued)

// Build lookup maps at module load time
const categoryMap = new Map<string, ToolCategory>();
const toolMap = new Map<string, { category: string; tool: ToolDefinition }>();

export function initializeRegistry() {
  for (const category of toolCategories) {
    categoryMap.set(category.name, category);
    for (const tool of category.tools) {
      toolMap.set(tool.name, { category: category.name, tool });
    }
  }
}

export function getCategory(name: string): ToolCategory | undefined {
  return categoryMap.get(name);
}

export function getTool(name: string): { category: string; tool: ToolDefinition } | undefined {
  return toolMap.get(name);
}

export function getAllCategories(): ToolCategory[] {
  return toolCategories;
}

export function searchTools(query: string): Array<{
  category: string;
  tool: string;
  description: string;
}> {
  const q = query.toLowerCase();
  const matches: Array<{ category: string; tool: string; description: string }> = [];

  for (const category of toolCategories) {
    for (const tool of category.tools) {
      if (
        tool.name.toLowerCase().includes(q) ||
        tool.description.toLowerCase().includes(q) ||
        category.name.toLowerCase().includes(q)
      ) {
        matches.push({
          category: category.name,
          tool: tool.name,
          description: tool.description
        });
      }
    }
  }

  return matches;
}

// Initialize on load
initializeRegistry();
```

### Step 3: Create Router Tools

These are the tools that enable discovery and execution.

```typescript
// src/tools/router.ts

import { 
  getAllCategories, 
  getCategory, 
  getTool, 
  searchTools 
} from "./registry.js";

export const routerTools = {
  list_tool_categories: {
    name: "list_tool_categories",
    description: 
      "List all available tool categories. Use this to discover what operations " +
      "are available beyond the basic tools exposed directly.",
    inputSchema: {
      type: "object" as const,
      properties: {},
      required: []
    },
    handler: async () => {
      const categories = getAllCategories();
      return {
        total_categories: categories.length,
        total_tools: categories.reduce((sum, c) => sum + c.tools.length, 0),
        categories: categories.map(c => ({
          name: c.name,
          description: c.description,
          tool_count: c.tools.length
        }))
      };
    }
  },

  get_category_tools: {
    name: "get_category_tools",
    description:
      "Get detailed information about tools in a specific category, " +
      "including their parameters. Use after list_tool_categories to " +
      "see what's available in a category.",
    inputSchema: {
      type: "object" as const,
      properties: {
        category: {
          type: "string",
          description: "Category name from list_tool_categories"
        }
      },
      required: ["category"]
    },
    handler: async (params: { category: string }) => {
      const category = getCategory(params.category);
      if (!category) {
        return {
          error: `Unknown category: ${params.category}`,
          available_categories: getAllCategories().map(c => c.name)
        };
      }
      return {
        category: category.name,
        description: category.description,
        tools: category.tools.map(t => ({
          name: t.name,
          description: t.description,
          parameters: t.inputSchema
        }))
      };
    }
  },

  execute_tool: {
    name: "execute_tool",
    description:
      "Execute a tool from any category. First use list_tool_categories " +
      "and get_category_tools to discover available tools and their parameters.",
    inputSchema: {
      type: "object" as const,
      properties: {
        tool_name: {
          type: "string",
          description: "Tool name (from get_category_tools)"
        },
        params: {
          type: "object",
          description: "Tool parameters (see get_category_tools for schema)"
        }
      },
      required: ["tool_name"]
    },
    handler: async (input: { tool_name: string; params?: Record<string, unknown> }) => {
      const entry = getTool(input.tool_name);
      if (!entry) {
        return {
          error: `Unknown tool: ${input.tool_name}`,
          hint: "Use list_tool_categories and get_category_tools to find available tools"
        };
      }

      try {
        const result = await entry.tool.handler(input.params || {});
        return {
          tool: input.tool_name,
          category: entry.category,
          result
        };
      } catch (err) {
        return {
          error: `Tool execution failed: ${(err as Error).message}`,
          tool: input.tool_name,
          category: entry.category
        };
      }
    }
  },

  search_tools: {
    name: "search_tools",
    description:
      "Search for tools by keyword across all categories. " +
      "Useful when you know what you want to do but not which category it's in.",
    inputSchema: {
      type: "object" as const,
      properties: {
        query: {
          type: "string",
          description: "Search term (e.g., 'gerber', 'zone', 'differential', 'export')"
        }
      },
      required: ["query"]
    },
    handler: async (params: { query: string }) => {
      const matches = searchTools(params.query);
      return {
        query: params.query,
        count: matches.length,
        matches: matches.slice(0, 20) // Limit results
      };
    }
  }
};
```

### Step 4: Define Direct Tools

These are your high-frequency tools that stay visible always.

```typescript
// src/tools/direct.ts

import { ToolDefinition } from "./registry.js";

// These tools are ALWAYS visible to Claude - no routing needed
// Pick your 10-15 most common operations

export const directTools: ToolDefinition[] = [
  // === PROJECT LIFECYCLE ===
  {
    name: "create_project",
    description: "Create a new project with initial files and configuration",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Project name" },
        path: { type: "string", description: "Directory path for project" },
        template: { 
          type: "string", 
          description: "Optional template to use",
          enum: ["blank", "arduino", "raspberry-pi"]
        }
      },
      required: ["name", "path"]
    },
    handler: async (params) => {
      // Implementation
      return { success: true, project_path: `${params.path}/${params.name}` };
    }
  },
  {
    name: "open_project",
    description: "Open an existing project",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: "Path to project file or directory" }
      },
      required: ["path"]
    },
    handler: async (params) => { /* ... */ }
  },
  {
    name: "save_project",
    description: "Save all project files",
    inputSchema: {
      type: "object",
      properties: {}
    },
    handler: async (params) => { /* ... */ }
  },
  {
    name: "get_project_info",
    description: "Get current project information: path, files, status",
    inputSchema: {
      type: "object",
      properties: {}
    },
    handler: async (params) => { /* ... */ }
  },

  // === PRIMARY OPERATIONS (your core workflow) ===
  {
    name: "add_component",
    description: "Add a component at specified position",
    inputSchema: {
      type: "object",
      properties: {
        type: { type: "string", description: "Component type or library reference" },
        reference: { type: "string", description: "Reference designator (e.g., R1, U1)" },
        x: { type: "number", description: "X position" },
        y: { type: "number", description: "Y position" },
        rotation: { type: "number", description: "Rotation in degrees", default: 0 }
      },
      required: ["type", "reference", "x", "y"]
    },
    handler: async (params) => { /* ... */ }
  },
  {
    name: "move_component",
    description: "Move a component to new position",
    inputSchema: {
      type: "object",
      properties: {
        reference: { type: "string", description: "Component reference (e.g., R1)" },
        x: { type: "number", description: "New X position" },
        y: { type: "number", description: "New Y position" }
      },
      required: ["reference", "x", "y"]
    },
    handler: async (params) => { /* ... */ }
  },
  {
    name: "list_components",
    description: "List all components with their positions and properties",
    inputSchema: {
      type: "object",
      properties: {
        filter: { type: "string", description: "Optional filter (e.g., 'R*' for resistors)" }
      }
    },
    handler: async (params) => { /* ... */ }
  },

  // === SECONDARY OPERATIONS (still common) ===
  {
    name: "add_connection",
    description: "Add a connection/trace between two points",
    inputSchema: {
      type: "object",
      properties: {
        start: {
          type: "object",
          properties: { x: { type: "number" }, y: { type: "number" } }
        },
        end: {
          type: "object",
          properties: { x: { type: "number" }, y: { type: "number" } }
        },
        net: { type: "string", description: "Net name" }
      },
      required: ["start", "end"]
    },
    handler: async (params) => { /* ... */ }
  },
  {
    name: "list_nets",
    description: "List all nets/connections",
    inputSchema: {
      type: "object",
      properties: {}
    },
    handler: async (params) => { /* ... */ }
  },
  {
    name: "get_info",
    description: "Get general information about current state",
    inputSchema: {
      type: "object",
      properties: {}
    },
    handler: async (params) => { /* ... */ }
  }
];
```

### Step 5: Register with MCP Server

Wire everything together in your main server file.

```typescript
// src/index.ts

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

import { directTools } from "./tools/direct.js";
import { routerTools } from "./tools/router.js";
import { initializeRegistry } from "./tools/registry.js";

// Initialize the tool registry
initializeRegistry();

const server = new Server(
  {
    name: "your-mcp-server",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// Combine all visible tools
const allVisibleTools = [
  ...directTools,
  ...Object.values(routerTools)
];

// Build a handler map for quick lookup
const toolHandlers = new Map<string, (params: any) => Promise<any>>();

for (const tool of directTools) {
  toolHandlers.set(tool.name, tool.handler);
}
for (const tool of Object.values(routerTools)) {
  toolHandlers.set(tool.name, tool.handler);
}

// List tools handler - returns only direct + router tools
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: allVisibleTools.map(tool => ({
      name: tool.name,
      description: tool.description,
      inputSchema: tool.inputSchema,
    })),
  };
});

// Call tool handler
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  const handler = toolHandlers.get(name);
  if (!handler) {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            error: `Unknown tool: ${name}`,
            hint: "Use list_tool_categories and search_tools to find available tools"
          })
        }
      ],
      isError: true,
    };
  }

  try {
    const result = await handler(args || {});
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify(result, null, 2)
        }
      ],
    };
  } catch (error) {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            error: `Tool execution failed: ${(error as Error).message}`
          })
        }
      ],
      isError: true,
    };
  }
});

// Start the server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("MCP Server running on stdio");
}

main().catch(console.error);
```

---

## Choosing Direct vs Routed Tools

### Direct Tools (Always Visible)

Include tools that are:

- Used in 80%+ of sessions
- Essential for basic workflows
- Required for project lifecycle (open, save, create)
- Needed for the core operation loop

**Examples by domain:**

| Domain | Direct Tools |
|--------|-------------|
| **KiCAD** | create_project, open_project, save_project, add_component, move_component, add_track, list_components, list_nets, get_board_info |
| **IDA Pro** | open_database, save_database, get_function, list_functions, add_comment, rename, get_xrefs, decompile |
| **Git** | status, add, commit, push, pull, checkout, branch, log |
| **Database** | connect, query, list_tables, describe_table |

### Routed Tools (Hidden Behind Router)

Include tools that are:

- Used in <50% of sessions
- Part of specialized workflows
- End-of-workflow operations (export, report)
- Advanced features
- Bulk or batch operations

**Examples:**

| Category | Why Route It |
|----------|-------------|
| `export` | Only used at end of workflow |
| `drc/validation` | Used during review phase |
| `advanced_*` | Specialty operations |
| `bulk_*` | Batch operations |
| `config/settings` | One-time setup |

---

## Category Design Guidelines

### Good Category Names

- Short, memorable (1-2 words)
- Verb-oriented or domain-specific
- Clear scope

```
✓ export, import, drc, zones, routing, schematic, layers, analysis
✗ miscellaneous, utilities, other, stuff, tools2
```

### Good Category Descriptions

Include:

- What the category does
- Key operations included
- When you'd use it

```typescript
// Good
{
  name: "export",
  description: "Generate manufacturing files: Gerber, drill, BOM, PDF, 3D models (STEP/VRML), SVG"
}

// Bad
{
  name: "export",
  description: "Export tools"
}
```

### Suggested Category Structure (Generic)

```typescript
const categories = [
  // Core operations (might be direct tools instead)
  { name: "project", description: "Project lifecycle: create, open, save, close" },
  
  // Domain-specific operations
  { name: "analysis", description: "Analyze and inspect: find patterns, validate, check" },
  { name: "modification", description: "Modify and transform: edit, rename, restructure" },
  { name: "navigation", description: "Navigate and search: find, list, filter, locate" },
  
  // Output operations
  { name: "export", description: "Export and generate: reports, files, documentation" },
  { name: "import", description: "Import from external sources: files, formats, APIs" },
  
  // Configuration
  { name: "config", description: "Configuration and settings: preferences, rules, templates" },
  
  // Advanced/specialized
  { name: "advanced", description: "Advanced operations: batch processing, automation, scripting" },
];
```

---

## IDA Pro Example Structure

For an IDA Pro MCP server with 100+ tools:

### Direct Tools (~12)

```typescript
const directTools = [
  "open_database",      // Load IDB
  "save_database",      // Save IDB
  "get_function",       // Get function by address/name
  "list_functions",     // List all functions
  "decompile",          // Decompile function (Hex-Rays)
  "add_comment",        // Add comment at address
  "rename",             // Rename address/function
  "get_xrefs_to",       // Get cross-references to address
  "get_xrefs_from",     // Get cross-references from address
  "get_strings",        // List strings
  "search_bytes",       // Search for byte pattern
  "get_segments",       // List segments
];
```

### Routed Categories

```typescript
const categories = [
  {
    name: "disassembly",
    description: "Disassembly operations: undefine, make code/data, change types",
    tools: ["make_code", "make_data", "undefine", "set_type", "make_array", "make_struct"]
  },
  {
    name: "functions",
    description: "Function management: create, delete, modify boundaries, set types",
    tools: ["create_function", "delete_function", "set_func_end", "set_func_type", "add_func_arg"]
  },
  {
    name: "types",
    description: "Type system: structs, enums, typedefs, parse headers",
    tools: ["create_struct", "add_struct_member", "create_enum", "parse_header", "import_types"]
  },
  {
    name: "patching",
    description: "Binary patching: modify bytes, assemble, apply patches",
    tools: ["patch_bytes", "patch_word", "patch_dword", "assemble", "apply_patches"]
  },
  {
    name: "scripting",
    description: "IDAPython scripting: run scripts, evaluate expressions",
    tools: ["run_script", "eval_python", "get_global", "set_global"]
  },
  {
    name: "signatures",
    description: "Signatures and patterns: FLIRT, Lumina, create signatures",
    tools: ["apply_flirt", "query_lumina", "create_sig", "find_pattern"]
  },
  {
    name: "debugging",
    description: "Debugger control: breakpoints, stepping, memory",
    tools: ["set_breakpoint", "step_into", "step_over", "read_memory", "write_memory", "get_regs"]
  },
  {
    name: "export",
    description: "Export: ASM listing, pseudocode, database info, reports",
    tools: ["export_asm", "export_c", "export_json", "generate_report"]
  },
  {
    name: "import",
    description: "Import: symbols, types, comments from external sources",
    tools: ["import_symbols", "import_pdb", "import_map", "import_comments"]
  },
  {
    name: "analysis",
    description: "Analysis control: reanalyze, find patterns, auto-analysis settings",
    tools: ["reanalyze", "find_crypto", "find_strings", "analyze_calls", "set_analysis_options"]
  },
];
```

---

## Usage Flow Examples

### Example 1: User wants to export Gerbers

```
User: "Export gerbers for this board"

Claude's thinking:
1. Don't see an export_gerber tool directly
2. Call search_tools({ query: "gerber" })
   → Returns: { category: "export", tool: "export_gerber", ... }
3. Call execute_tool({ tool_name: "export_gerber", params: { output_dir: "./gerbers" }})
   → Returns: { success: true, files: [...] }

Claude: "I've exported the Gerber files to ./gerbers/"
```

### Example 2: User wants to place a component

```
User: "Add a 0805 resistor at position 10,20"

Claude's thinking:
1. See add_component in direct tools
2. Call add_component({ type: "R_0805", reference: "R1", x: 10, y: 20 })
   → Returns: { success: true, reference: "R1" }

Claude: "Added R1 (0805 resistor) at position (10, 20)"
```

### Example 3: User wants to do something unfamiliar

```
User: "I need to add length matching to these traces"

Claude's thinking:
1. Don't see length matching in direct tools
2. Call search_tools({ query: "length matching" })
   → Returns: { category: "advanced_routing", tool: "add_length_tuning", ... }
3. Call get_category_tools({ category: "advanced_routing" })
   → Returns full parameter schema for add_length_tuning
4. Call execute_tool({ tool_name: "add_length_tuning", params: {...} })

Claude: "I've added length tuning meanders to match the trace lengths"
```

---

## Testing Your Router

### Unit Tests

```typescript
// tests/router.test.ts

import { describe, it, expect } from "vitest";
import { 
  searchTools, 
  getCategory, 
  getTool,
  getAllCategories 
} from "../src/tools/registry.js";
import { routerTools } from "../src/tools/router.js";

describe("Tool Registry", () => {
  it("should find tools by keyword", () => {
    const results = searchTools("export");
    expect(results.length).toBeGreaterThan(0);
    expect(results.some(r => r.tool.includes("export"))).toBe(true);
  });

  it("should return category info", () => {
    const category = getCategory("export");
    expect(category).toBeDefined();
    expect(category!.tools.length).toBeGreaterThan(0);
  });

  it("should return tool info with category", () => {
    const tool = getTool("export_gerber");
    expect(tool).toBeDefined();
    expect(tool!.category).toBe("export");
  });
});

describe("Router Tools", () => {
  it("list_tool_categories returns all categories", async () => {
    const result = await routerTools.list_tool_categories.handler({});
    expect(result.categories.length).toBe(getAllCategories().length);
  });

  it("get_category_tools returns tools for valid category", async () => {
    const result = await routerTools.get_category_tools.handler({ 
      category: "export" 
    });
    expect(result.tools).toBeDefined();
    expect(result.tools.length).toBeGreaterThan(0);
  });

  it("get_category_tools returns error for invalid category", async () => {
    const result = await routerTools.get_category_tools.handler({ 
      category: "nonexistent" 
    });
    expect(result.error).toBeDefined();
  });

  it("execute_tool runs valid tool", async () => {
    const result = await routerTools.execute_tool.handler({
      tool_name: "export_gerber",
      params: { output_dir: "/tmp/test" }
    });
    expect(result.error).toBeUndefined();
  });

  it("execute_tool returns error for invalid tool", async () => {
    const result = await routerTools.execute_tool.handler({
      tool_name: "nonexistent_tool",
      params: {}
    });
    expect(result.error).toBeDefined();
  });
});
```

### Integration Test

Test with an actual MCP client:

```bash
# Using MCP Inspector
npx @modelcontextprotocol/inspector your-server

# Or with Claude Desktop - add to config
{
  "mcpServers": {
    "your-server": {
      "command": "node",
      "args": ["./dist/index.js"]
    }
  }
}
```

---

## Advanced: Combining with Anthropic's Tool Search Tool

If you control the client (building your own app with Claude API), you can use Anthropic's native Tool Search Tool for even better results:

```python
import anthropic

client = anthropic.Anthropic()

response = client.beta.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=4096,
    betas=["advanced-tool-use-2025-11-20"],
    tools=[
        # Tool search tool for dynamic discovery
        {
            "type": "tool_search_tool_regex_20251119",
            "name": "tool_search_tool_regex"
        },
        # Always-loaded tools
        {
            "name": "create_project",
            "description": "Create new project",
            "input_schema": {...},
            "defer_loading": False  # Always visible
        },
        # Deferred tools - only loaded when searched
        {
            "name": "export_gerber",
            "description": "Export Gerber files for PCB fabrication",
            "input_schema": {...},
            "defer_loading": True  # Hidden until searched
        },
        # ... 100 more deferred tools
    ],
    messages=[{"role": "user", "content": "Export gerbers for my board"}]
)
```

This approach works at the API level rather than MCP level, giving you:

- Native search with regex or BM25
- Automatic tool expansion
- Works with any MCP client

See [Tool Search Tool Documentation](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool) for details.

---

## References

### MCP Documentation

- [MCP Specification](https://modelcontextprotocol.io/specification/2025-03-26)
- [MCP Tools Documentation](https://modelcontextprotocol.info/docs/concepts/tools/)
- [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP GitHub Organization](https://github.com/modelcontextprotocol)

### Anthropic Advanced Tool Use

- [Advanced Tool Use Blog Post](https://www.anthropic.com/engineering/advanced-tool-use)
- [Tool Search Tool Documentation](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
- [Programmatic Tool Calling Documentation](https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling)
- [Claude Code Issue: Tool Search Support](https://github.com/anthropics/claude-code/issues/12836)

### Example Implementations

- [KiCAD MCP Server](https://github.com/mixelpixx/KiCAD-MCP-Server) - 52+ tools with natural language PCB design
- [MCP Servers Repository](https://github.com/modelcontextprotocol/servers) - Official reference implementations

---

## Checklist

Before shipping your router-based MCP server:

- [ ] Direct tools cover 80% of common use cases
- [ ] Categories have clear, descriptive names
- [ ] Category descriptions explain what's included
- [ ] All tools have good descriptions
- [ ] `search_tools` finds tools by common keywords
- [ ] `execute_tool` handles errors gracefully
- [ ] Unit tests pass for registry and router
- [ ] Tested with actual MCP client (Claude Desktop, Cline, etc.)
- [ ] README documents the router pattern for users

---

## Summary

| Before | After |
|--------|-------|
| 100 tools visible | 15-18 tools visible |
| ~60K+ tokens consumed | ~10K tokens consumed |
| Tool selection confusion | Clear categories |
| Context starvation | Room for conversation |

The router pattern gives you unlimited tool capacity while keeping Claude focused and efficient.
