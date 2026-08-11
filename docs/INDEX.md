# Documentation Index

- [MCP 2026-07-28 migration](MCP_2026_MIGRATION.md) - implemented protocol features, compatibility posture, and extension decisions

KiCAD MCP Server -- AI-assisted PCB design via Model Context Protocol

**Version:** 2.7.0 | **Tools:** 219 first-class | **Last Updated:** 2026-08-11

---

## Getting Started

| Document                                        | Description                                                    |
| ----------------------------------------------- | -------------------------------------------------------------- |
| [README](../README.md)                          | Project overview, installation, configuration, quick start     |
| [Client Configuration](CLIENT_CONFIGURATION.md) | MCP client setup (Claude Desktop, Cline, Claude Code)          |
| [Platform Guide](PLATFORM_GUIDE.md)             | Linux vs Windows vs macOS differences                          |
| [PCB Design Workflow](PCB_DESIGN_WORKFLOW.md)   | End-to-end design guide from project creation to manufacturing |

---

## Tool References

| Document                                                                | Description                                        |
| ----------------------------------------------------------------------- | -------------------------------------------------- |
| [Tool Inventory](TOOL_INVENTORY.md)                                     | Runtime-verified category counts for all 219 tools |
| [Schematic Tools Reference](SCHEMATIC_TOOLS_REFERENCE.md)               | Schematic components, wiring, analysis, and export |
| [Routing Tools Reference](ROUTING_TOOLS_REFERENCE.md)                   | Traces, vias, differential pairs, nets, and zones  |
| [Footprint and Symbol Creator Guide](FOOTPRINT_SYMBOL_CREATOR_GUIDE.md) | 8 tools for creating custom footprints and symbols |
| [Freerouting Guide](FREEROUTING_GUIDE.md)                               | 4 autorouter tools -- setup, usage, Docker support |
| [SVG Import Guide](SVG_IMPORT_GUIDE.md)                                 | Import SVG logos onto PCB layers                   |
| [Datasheet Tools Guide](DATASHEET_TOOLS_GUIDE.md)                       | Datasheet enrichment via LCSC                      |

---

## Integration Guides

| Document                                      | Description                                        |
| --------------------------------------------- | -------------------------------------------------- |
| [JLCPCB Integration](JLCPCB_INTEGRATION.md)   | JLCPCB parts catalog, pricing, component selection |
| [JLCPCB Usage Guide](JLCPCB_USAGE_GUIDE.md)   | Detailed JLCPCB setup and usage                    |
| [Library Integration](LIBRARY_INTEGRATION.md) | Footprint and symbol library setup                 |
| [IPC Backend Status](IPC_BACKEND_STATUS.md)   | Real-time KiCAD UI synchronization (experimental)  |

---

## Workflows

| Document                                              | Description                                                                                 |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| [Realtime Workflow](REALTIME_WORKFLOW.md)             | Working with IPC backend for live updates                                                   |
| [Headless Authoring](HEADLESS_AUTHORING.md)           | Driving the server without the KiCad GUI: build recipe, ERC triage, verification discipline |
| [Visual Feedback](VISUAL_FEEDBACK.md)                 | UI visual feedback guide                                                                    |
| [UI Auto Launch](UI_AUTO_LAUNCH.md)                   | Automatic KiCAD UI launch feature                                                           |
| [Tool Discovery Guide](mcp-router-guide.md)           | First-class catalog and supplemental search                                                 |
| [Tool Discovery Architecture](ROUTER_ARCHITECTURE.md) | First-class catalog and discovery design                                                    |
| [Discovery Quick Start](ROUTER_QUICK_START.md)        | Find and call first-class tools directly                                                    |

---

## Troubleshooting

| Document                                                  | Description                    |
| --------------------------------------------------------- | ------------------------------ |
| [Known Issues](KNOWN_ISSUES.md)                           | Current issues and workarounds |
| [Windows Troubleshooting](WINDOWS_TROUBLESHOOTING.md)     | Windows-specific problems      |
| [Linux Compatibility Audit](LINUX_COMPATIBILITY_AUDIT.md) | Linux platform details         |

---

## Project Information

| Document                            | Description                               |
| ----------------------------------- | ----------------------------------------- |
| [Status Summary](STATUS_SUMMARY.md) | Current project status and feature matrix |
| [Roadmap](ROADMAP.md)               | Development roadmap and planned features  |
| [Changelog](../CHANGELOG.md)        | Detailed release notes for all versions   |

---

## For Contributors

| Document                           | Description                              |
| ---------------------------------- | ---------------------------------------- |
| [Contributing](../CONTRIBUTING.md) | How to contribute to the project         |
| [Architecture](ARCHITECTURE.md)    | System architecture and adding new tools |

---

## Archive

Historical planning documents are preserved in [docs/archive/](archive/README.md).
