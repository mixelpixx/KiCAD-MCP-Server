# KiCAD MCP Roadmap

**Vision:** Enable anyone to design professional PCBs through natural conversation with AI

**Current Version:** 2.2.3
**Last Updated:** 2026-03-21

---

## Completed Milestones

### v1.0.0 - Core Foundation (October 2025)
- [x] MCP protocol implementation (JSON-RPC 2.0, MCP 2025-06-18)
- [x] Project management (create, open, save)
- [x] Board operations (size, outline, layers, mounting holes, text)
- [x] Component placement with 153+ footprint libraries
- [x] Basic routing (traces, vias, copper pours)
- [x] Design rule checking
- [x] Export (Gerber, PDF, SVG, 3D, BOM)
- [x] Cross-platform support (Linux, Windows, macOS)
- [x] UI auto-launch and detection

### v2.0.0-alpha - Router and IPC (November-December 2025)
- [x] Tool router pattern -- 70% AI context reduction
- [x] IPC backend for real-time KiCAD UI synchronization (21 commands)
- [x] Hybrid SWIG/IPC backend with automatic fallback
- [x] Comprehensive Windows support with automated setup

### v2.1.0-alpha - Schematics and JLCPCB (January 2026)
- [x] Complete schematic workflow fix (Issue #26)
- [x] Dynamic symbol loading -- access to all ~10,000 KiCad symbols
- [x] Intelligent wiring system with pin discovery and smart routing
- [x] Power symbol support (VCC, GND, +3V3, +5V)
- [x] Wire graph analysis for net connectivity
- [x] JLCPCB parts integration (2.5M+ parts, dual-mode architecture)
- [x] Local symbol library search (contributor: @l3wi)

### v2.2.0 through v2.2.3 - Routing, Creators, Autorouting (February-March 2026)
- [x] 13 new routing/component tools (delete/query/modify traces, arrays, alignment)
- [x] route_pad_to_pad with auto-via insertion for cross-layer connections
- [x] copy_routing_pattern for trace replication
- [x] route_differential_pair for matched signals
- [x] Custom footprint creator (4 tools)
- [x] Custom symbol creator (4 tools)
- [x] Datasheet enrichment tools (LCSC integration)
- [x] 11 schematic inspection/editing tools (contributor: @Mehanik)
- [x] FFC/ribbon cable passthrough workflow (connect_passthrough, sync_schematic_to_board)
- [x] SVG logo import for PCB silkscreen
- [x] ERC validation
- [x] Project snapshot system
- [x] Freerouting autorouter integration with Docker/Podman (contributor: @jflaflamme)
- [x] Project-local library resolution
- [x] Developer mode (KICAD_MCP_DEV=1)

---

## Current Focus: v2.3+

### Documentation Overhaul (In Progress)
- [ ] Per-feature documentation for all 122 tools
- [ ] Architecture guide for contributors
- [ ] End-to-end PCB design workflow guide
- [ ] Documentation index

### Quality and Stability
- [ ] Expand test coverage across all tool categories
- [ ] Performance profiling for large boards
- [ ] Update package.json version to match CHANGELOG

---

## Planned Features

### Supplier Integration
- [ ] Digikey API integration
- [ ] Mouser API integration
- [ ] Smart BOM management with real-time pricing
- [ ] Cost optimization across suppliers

### Design Patterns and Templates
- [ ] Circuit patterns library (voltage regulators, USB, microcontrollers)
- [ ] Board templates (Arduino shields, RPi HATs, Feather wings)
- [ ] Auto-suggest trace widths by current
- [ ] Impedance-controlled trace support

### Advanced Capabilities
- [ ] Panelization support
- [ ] Multi-board project management
- [ ] High-speed design helpers (length matching, via stitching)
- [ ] SPICE simulation integration

### Community and Education
- [ ] Example project gallery with tutorials
- [ ] Video walkthrough series
- [ ] Interactive beginner tutorials
- [ ] Plugin system for custom tools

---

## How to Contribute

See the roadmap items above and want to help? High-value contributions:

1. Testing on Windows/macOS with KiCAD 9
2. Example projects and workflow documentation
3. Bug reports with reproduction steps
4. New tool implementations (see [ARCHITECTURE.md](ARCHITECTURE.md))
5. Design pattern library contributions

Check [CONTRIBUTING.md](../CONTRIBUTING.md) for details.

---

*Maintained by: KiCAD MCP Team and community contributors*
