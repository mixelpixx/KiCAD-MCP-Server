# KiCAD MCP Roadmap

**Vision:** Enable anyone to design professional PCBs through natural conversation with AI

**Current Version:** 2.0.0-alpha.2
**Target:** 2.0.0 stable by end of Week 12

---

## 🎯 Week 2: Component Integration & Routing

**Goal:** Make the MCP server useful for real PCB design

### High Priority

**1. Component Library Integration** 🔴
- [ ] Detect KiCAD footprint library paths
- [ ] Add configuration for custom library paths
- [ ] Create footprint search/autocomplete
- [ ] Test component placement end-to-end
- [ ] Document supported footprints

**Deliverable:** Place components with actual footprints from libraries

**2. Routing Operations** 🟡
- [ ] Test `route_trace` with KiCAD 9.0
- [ ] Test `add_via` with KiCAD 9.0
- [ ] Test `add_copper_pour` with KiCAD 9.0
- [ ] Fix any API compatibility issues
- [ ] Add routing examples to docs

**Deliverable:** Successfully route a simple board (LED + resistor)

**3. JLCPCB Parts Database** 🟡
- [ ] Download/parse JLCPCB parts CSV
- [ ] Map parts to KiCAD footprints
- [ ] Create search by part number
- [ ] Add price/stock information
- [ ] Integrate with component placement

**Deliverable:** "Add a 10k resistor (JLCPCB basic part)"

### Medium Priority

**4. Fix get_board_info** 🟢
- [ ] Update layer constants for KiCAD 9.0
- [ ] Add backward compatibility
- [ ] Test with real boards

**5. Example Projects** 🟢
- [ ] LED blinker (555 timer)
- [ ] Arduino Uno shield template
- [ ] Raspberry Pi HAT template
- [ ] Video tutorial of complete workflow

---

## 🚀 Week 3: IPC Backend & Real-time Updates

**Goal:** Eliminate manual reload - see changes instantly

### High Priority

**1. IPC Connection** 🔴
- [ ] Establish socket connection to KiCAD
- [ ] Handle connection errors gracefully
- [ ] Auto-reconnect if KiCAD restarts
- [ ] Fall back to SWIG if IPC unavailable

**2. IPC Operations** 🔴
- [ ] Port project operations to IPC
- [ ] Port board operations to IPC
- [ ] Port component operations to IPC
- [ ] Port routing operations to IPC

**3. Real-time UI Updates** 🔴
- [ ] Changes appear instantly in UI
- [ ] No reload prompt
- [ ] Visual feedback within 100ms
- [ ] Demo video showing real-time design

**Deliverable:** Design a board with live updates as Claude works

### Medium Priority

**4. Dual Backend Support** 🟡
- [ ] Auto-detect if IPC is available
- [ ] Switch between SWIG/IPC seamlessly
- [ ] Document when to use each
- [ ] Performance comparison

---

## 📦 Week 4-5: Smart BOM & Supplier Integration

**Goal:** Optimize component selection for cost and availability

**1. Digikey Integration**
- [ ] API authentication
- [ ] Part search by specs
- [ ] Price/stock checking
- [ ] Parametric search (e.g., "10k resistor, 0603, 1%")

**2. Smart BOM Management**
- [ ] Auto-suggest component substitutions
- [ ] Calculate total board cost
- [ ] Check component availability
- [ ] Generate purchase links

**3. Cost Optimization**
- [ ] Suggest JLCPCB basic parts (free assembly)
- [ ] Warn about expensive/obsolete parts
- [ ] Batch component suggestions

**Deliverable:** "Design a low-cost LED driver under $5 BOM"

---

## 🎨 Week 6-7: Design Patterns & Templates

**Goal:** Accelerate common design tasks

**1. Circuit Patterns Library**
- [ ] Voltage regulators (LDO, switching)
- [ ] USB interfaces (USB-C, micro-USB)
- [ ] Microcontroller circuits (ESP32, STM32, RP2040)
- [ ] Power protection (reverse polarity, ESD)
- [ ] Common interfaces (I2C, SPI, UART)

**2. Board Templates**
- [ ] Arduino form factors (Uno, Nano, Mega)
- [ ] Raspberry Pi HATs
- [ ] Feather wings
- [ ] Custom PCB shapes (badges, wearables)

**3. Auto-routing Helpers**
- [ ] Suggest trace widths by current
- [ ] Auto-create ground pours
- [ ] Match differential pair lengths
- [ ] Check impedance requirements

**Deliverable:** "Create an ESP32 dev board with USB-C"

---

## 🎓 Week 8-9: Guided Workflows & Education

**Goal:** Make PCB design accessible to beginners

**1. Interactive Tutorials**
- [ ] First PCB (LED blinker)
- [ ] Understanding layers and vias
- [ ] Routing best practices
- [ ] Design rule checking

**2. Design Validation**
- [ ] Check for common mistakes
- [ ] Suggest improvements
- [ ] Explain DRC violations
- [ ] Manufacturing feasibility check

**3. Documentation Generation**
- [ ] Auto-generate assembly drawings
- [ ] Create BOM spreadsheets
- [ ] Export fabrication files
- [ ] Generate user manual

**Deliverable:** Complete beginner-to-fabrication tutorial

---

## 🔬 Week 10-11: Advanced Features

**Goal:** Support complex professional designs

**1. Multi-board Projects**
- [ ] Panel designs for manufacturing
- [ ] Shared schematics across boards
- [ ] Version management

**2. High-speed Design**
- [ ] Impedance-controlled traces
- [ ] Length matching for DDR/PCIe
- [ ] Signal integrity analysis
- [ ] Via stitching for EMI

**3. Advanced Components**
- [ ] BGAs and fine-pitch packages
- [ ] Flex PCB support
- [ ] Rigid-flex designs

---

## 🎉 Week 12: Polish & Release

**Goal:** Production-ready v2.0 release

**1. Performance**
- [ ] Optimize large board operations
- [ ] Cache library searches
- [ ] Parallel operations where possible

**2. Testing**
- [ ] Unit tests for all commands
- [ ] Integration tests for workflows
- [ ] Test on Windows/macOS/Linux
- [ ] Load testing with complex boards

**3. Documentation**
- [ ] Complete API reference
- [ ] Video tutorial series
- [ ] Blog post/announcement
- [ ] Example project gallery

**4. Community**
- [ ] Contribution guidelines
- [ ] Plugin system for custom tools
- [ ] Discord/forum for support

**Deliverable:** KiCAD MCP v2.0 stable release

---

## 🌟 Future (Post-v2.0)

**Big Ideas for v3.0+**

**1. AI-Powered Design**
- Generate circuits from specifications
- Optimize layouts for size/cost/performance
- Suggest alternative designs
- Learn from user preferences

**2. Collaboration**
- Multi-user design sessions
- Design reviews and comments
- Version control integration (Git)
- Share design patterns

**3. Manufacturing Integration**
- Direct order to PCB fabs
- Assembly service integration
- Track order status
- Automated quoting

**4. Simulation**
- SPICE integration for circuit sim
- Thermal simulation
- Signal integrity
- Power integrity

**5. Extended Platform Support**
- Altium import/export
- Eagle compatibility
- EasyEDA integration
- Web-based viewer

---

## 📊 Success Metrics

**v2.0 Release Criteria:**

- [ ] 95%+ of commands working reliably
- [ ] Component placement with 10,000+ footprints
- [ ] IPC backend working on all platforms
- [ ] 10+ example projects
- [ ] 5+ video tutorials
- [ ] 100+ GitHub stars
- [ ] 10+ community contributors

**User Success Stories:**
- "Designed my first PCB with Claude Code in 30 minutes"
- "Cut PCB design time by 80% using MCP"
- "Got my board manufactured - it works!"

---

## 🤝 How to Contribute

See the roadmap and want to help?

**High-value contributions:**
1. Component library mappings (JLCPCB → KiCAD)
2. Design pattern library (circuits you use often)
3. Testing on Windows/macOS
4. Documentation and tutorials
5. Bug reports with reproductions

Check [CONTRIBUTING.md](../CONTRIBUTING.md) for details.

---

**Last Updated:** 2025-10-26
**Maintained by:** KiCAD MCP Team
