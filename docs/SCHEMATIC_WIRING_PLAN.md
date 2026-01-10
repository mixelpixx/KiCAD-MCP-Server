# Schematic Wiring Implementation Plan

**Date:** 2026-01-10
**Status:** Planning Phase
**Priority:** HIGH (User-requested feature for Issue #26)

---

## Executive Summary

This plan outlines the implementation of complete schematic wiring functionality for the KiCAD MCP Server. Currently, component placement works perfectly with dynamic symbol loading, but wire/connection tools are incomplete or non-functional.

**Goal:** Enable users to create complete, functional schematics with wired connections between components through the MCP interface.

---

## Current State Analysis

### What Exists ✅

**Files:**
- `python/commands/connection_schematic.py` - ConnectionManager class with wire/label methods
- MCP handlers in `kicad_interface.py` for 6 connection-related tools

**MCP Tools (Registered):**
1. `add_schematic_wire` - Add wire between two points
2. `add_schematic_connection` - Connect two component pins
3. `add_schematic_net_label` - Add net label
4. `connect_to_net` - Connect pin to named net
5. `get_net_connections` - Query net connections
6. `generate_netlist` - Generate netlist from schematic

**ConnectionManager Methods:**
- `add_wire(schematic, start_point, end_point)` - Add wire between coordinates
- `add_connection(schematic, source_ref, source_pin, target_ref, target_pin)` - Connect pins
- `add_net_label(schematic, net_name, position)` - Add label
- `connect_to_net(schematic, component_ref, pin_name, net_name)` - Pin to net
- `get_pin_location(symbol, pin_name)` - Get pin coordinates
- `get_net_connections(schematic, net_name)` - Query connections
- `generate_netlist(schematic)` - Generate netlist

### What's Broken/Missing ❌

**Problem 1: kicad-skip API Uncertainty**
- Code assumes `schematic.wire.append()` exists
- Code assumes `schematic.label.append()` exists
- Code assumes pins have `.name` and `.location` attributes
- **Need to verify what kicad-skip actually supports**

**Problem 2: Pin Location Calculation**
- Current implementation tries to calculate absolute pin positions
- May not account for symbol rotation
- May not work with multi-unit symbols
- Pin numbering vs pin naming confusion

**Problem 3: No Visual Feedback**
- No way to verify wires were created correctly
- No validation of wire endpoints
- No checks for overlapping wires or junctions

**Problem 4: Limited Testing**
- No integration tests for wiring functionality
- No validation with real KiCad schematics
- User reported `add_schematic_wire` fails

**Problem 5: Missing Features**
- No junction (wire intersection) support
- No bus support (multi-bit signals)
- No no-connect flags
- No power symbols (VCC, GND graphical symbols)
- No hierarchical labels

---

## Technical Challenges

### Challenge 1: kicad-skip Wire API

**Issue:** The kicad-skip library documentation is sparse. We need to determine:
- Does `schematic.wire` exist?
- What's the correct API to add wires?
- How are wires stored in .kicad_sch files?

**S-Expression Format (KiCad 8/9):**
```lisp
(wire (pts (xy 100 100) (xy 200 100))
  (stroke (width 0) (type default))
  (uuid "12345678-1234-1234-1234-123456789012")
)
```

**Approach:**
1. Examine kicad-skip source code
2. Test wire creation manually with kicad-skip
3. Fall back to S-expression manipulation if necessary (similar to dynamic symbol loading)

### Challenge 2: Pin Location Discovery

**Issue:** Need to find exact pin coordinates for automatic wiring.

**Pin Data in Symbols:**
Pins are defined within symbol definitions in lib_symbols, with coordinates relative to symbol origin. When symbol is placed, pins move with it.

**Required Information:**
- Symbol position (x, y)
- Symbol rotation angle
- Pin offset from symbol origin
- Pin number/name mapping

**Solution:**
1. Parse symbol definition to find pin definitions
2. Apply transformation matrix (position + rotation) to pin coordinates
3. Return absolute pin position in schematic space

### Challenge 3: Smart Wire Routing

**Issue:** Users don't want to manually specify every wire segment.

**Desired Behavior:**
```
User: "Connect R1 pin 1 to C1 pin 1"
System:
  - Calculate R1 pin 1 location: (100, 100)
  - Calculate C1 pin 1 location: (150, 120)
  - Create wire path (orthogonal routing preferred):
    - (100, 100) → (100, 120) → (150, 120)
  - Or simple direct: (100, 100) → (150, 120)
```

**Auto-Routing Options:**
1. **Direct** - Single wire segment (diagonal if needed)
2. **Orthogonal** - Only horizontal/vertical segments (2 segments)
3. **Manhattan** - Complex path avoiding components (3+ segments)

**Phase 1 Approach:** Start with direct wiring, add orthogonal later.

### Challenge 4: Net Label Integration

**Issue:** Labels need to attach to wires, not float in space.

**KiCad Behavior:**
- Labels must touch a wire or pin
- Labels create electrical connections at their attachment point
- Multiple labels with same name = connected net

**Implementation:**
- When adding label, find nearest wire endpoint
- Attach label to that coordinate
- Or create short wire stub for label attachment

---

## Implementation Phases

### Phase 1: Core Wire Functionality (Week 1)

**Goal:** Get basic wiring working with kicad-skip API

**Tasks:**

1. **Research kicad-skip Wire API** (4 hours)
   - Read kicad-skip source code
   - Test wire creation with Python REPL
   - Document actual API methods
   - Create test schematic with manual wires

2. **Fix Wire Creation** (6 hours)
   - Update ConnectionManager.add_wire() with correct API
   - Handle S-expression manipulation if needed
   - Add UUID generation for wires
   - Test with simple wire (100,100) → (200,100)

3. **Implement Pin Discovery** (8 hours)
   - Parse symbol definitions to extract pin data
   - Handle pin coordinates relative to symbol
   - Apply rotation transformation
   - Test with R, C, LED from dynamic symbols

4. **Fix add_schematic_connection** (4 hours)
   - Use correct pin discovery
   - Create direct wire between pins
   - Handle error cases (pin not found, etc.)
   - Test with R1 pin 2 → C1 pin 1

5. **Integration Testing** (4 hours)
   - Create test schematic with R, C, LED
   - Wire R to C
   - Wire C to LED
   - Verify schematic opens in KiCad
   - Verify electrical connectivity

**Deliverables:**
- Working `add_schematic_wire` tool
- Working `add_schematic_connection` tool
- Pin location discovery working
- Integration test passing
- Documentation updated

**Success Criteria:**
- User can connect two resistor pins with MCP command
- Wire appears in KiCad schematic viewer
- Netlist shows electrical connection

---

### Phase 2: Net Labels & Named Nets (Week 1-2)

**Goal:** Enable named net connections (VCC, GND, etc.)

**Tasks:**

1. **Fix Net Label Creation** (4 hours)
   - Update ConnectionManager.add_net_label()
   - Use correct kicad-skip API or S-expression
   - Position labels correctly
   - Test label creation

2. **Implement connect_to_net** (6 hours)
   - Create wire stub from pin
   - Attach label to wire endpoint
   - Support common nets (VCC, GND, 3V3, etc.)
   - Test with multiple components on same net

3. **Net Connection Discovery** (6 hours)
   - Parse wires and labels in schematic
   - Build connectivity graph
   - Implement get_net_connections()
   - Return all pins on a net

4. **Power Symbol Support** (8 hours)
   - Add power symbols to templates (VCC, GND, 3V3, 5V)
   - Or dynamically load from power library
   - Connect power pins to power nets
   - Test complete circuit with power

5. **Testing** (4 hours)
   - Create circuit with VCC, GND nets
   - Connect multiple components to each net
   - Verify net connectivity
   - Generate and validate netlist

**Deliverables:**
- Working `add_schematic_net_label` tool
- Working `connect_to_net` tool
- Working `get_net_connections` tool
- Power symbol support
- Netlist generation working

**Success Criteria:**
- User can label nets VCC, GND
- Multiple components connect to same net
- Netlist correctly shows net membership

---

### Phase 3: Advanced Features (Week 2-3)

**Goal:** Professional schematic features

**Tasks:**

1. **Junction Support** (4 hours)
   - Detect wire intersections
   - Add junction dots at T-junctions
   - S-expression: `(junction (at x y) (diameter 0) (uuid ...))`

2. **No-Connect Flags** (2 hours)
   - Add "X" marks on unused pins
   - S-expression: `(no_connect (at x y) (uuid ...))`

3. **Orthogonal Routing** (6 hours)
   - Implement 2-segment wire routing
   - Horizontal-then-vertical or vertical-then-horizontal
   - Choose best path based on pin positions

4. **Bus Support** (8 hours)
   - Multi-bit signal buses
   - Bus labels (e.g., "D[0..7]")
   - Bus entries for individual signals

5. **Hierarchical Labels** (8 hours)
   - Labels for hierarchical sheets
   - Input/Output/Bidirectional types
   - Sheet connections

**Deliverables:**
- Junction creation
- No-connect support
- Smart orthogonal routing
- Bus and hierarchical label support

**Success Criteria:**
- Wires route cleanly around components
- Junctions appear at wire intersections
- Unused pins marked with no-connect

---

### Phase 4: Validation & Polish (Week 3-4)

**Goal:** Production-ready reliability

**Tasks:**

1. **ERC Integration** (6 hours)
   - Electrical Rule Check
   - Detect floating nets
   - Detect unconnected pins
   - Detect short circuits

2. **Visual Validation** (4 hours)
   - Export schematic to PDF after wiring
   - Verify wire appearance
   - Check net label placement

3. **Comprehensive Testing** (8 hours)
   - Test with Device library components
   - Test with IC components (multi-pin)
   - Test with connectors
   - Test complex circuits (10+ components)

4. **Error Handling** (4 hours)
   - Graceful failures
   - Clear error messages
   - Validation of coordinates
   - Duplicate net label detection

5. **Documentation** (6 hours)
   - Update MCP tool descriptions
   - Add usage examples to README
   - Create wiring tutorial
   - Add to CHANGELOG

**Deliverables:**
- ERC validation
- Comprehensive test suite
- Error handling
- Complete documentation

**Success Criteria:**
- 95%+ test pass rate
- Users can create functional circuits
- Clear error messages on failures

---

## Technical Approach

### Option A: Use kicad-skip Native API (Preferred)

**If kicad-skip supports wires natively:**

```python
# Add wire using native API
wire = schematic.wire.new(
    start=[100, 100],
    end=[200, 100]
)

# Add label
label = schematic.label.new(
    text="VCC",
    at=[150, 100]
)
```

**Pros:**
- Clean, maintainable code
- Follows library patterns
- Less likely to break

**Cons:**
- Depends on kicad-skip having these features
- May be limited in functionality

### Option B: S-Expression Manipulation (Fallback)

**If kicad-skip doesn't support wires:**

Use the same approach as dynamic symbol loading:

```python
import sexpdata
from sexpdata import Symbol

# Read schematic
with open(schematic_path, 'r') as f:
    sch_data = sexpdata.loads(f.read())

# Create wire S-expression
wire_sexp = [
    Symbol('wire'),
    [Symbol('pts'),
        [Symbol('xy'), 100, 100],
        [Symbol('xy'), 200, 100]
    ],
    [Symbol('stroke'), [Symbol('width'), 0], [Symbol('type'), Symbol('default')]],
    [Symbol('uuid'), str(uuid.uuid4())]
]

# Insert into schematic
sch_data.append(wire_sexp)

# Write back
with open(schematic_path, 'w') as f:
    f.write(sexpdata.dumps(sch_data))
```

**Pros:**
- Complete control
- Can implement any feature
- Works around library limitations

**Cons:**
- More complex
- Requires deep KiCad format knowledge
- More maintenance

### Hybrid Approach (Recommended)

1. Try kicad-skip native API first
2. Fall back to S-expression if needed
3. Use S-expression for advanced features (junctions, buses)

---

## Pin Discovery Algorithm

### Step 1: Get Symbol Definition

Symbols are stored in `lib_symbols` section:

```lisp
(lib_symbols
  (symbol "Device:R"
    (symbol "R_0_1"
      (rectangle (start -1 -2.54) (end 1 2.54) ...))
    (symbol "R_1_1"
      (pin passive line (at 0 3.81 270) (length 1.27)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 0 -3.81 90) (length 1.27)
        (name "~" (effects (font (size 1.27 1.27))))
        (number "2" (effects (font (size 1.27 1.27)))))))
```

### Step 2: Extract Pin Information

For each pin:
- Number (e.g., "1", "2")
- Name (e.g., "GND", "VCC", "~" for unnamed)
- Position relative to symbol origin: `(at x y angle)`
- Length (distance from symbol body to connection point)

### Step 3: Get Symbol Instance Position

From symbol instance in schematic:

```lisp
(symbol (lib_id "Device:R") (at 100 100 0) (unit 1)
  (property "Reference" "R1" ...))
```

Extract:
- Position: `(at 100 100 0)` = x=100, y=100, rotation=0°
- Reference: "R1"

### Step 4: Calculate Absolute Pin Position

```python
def get_absolute_pin_position(symbol_instance, pin_definition):
    # Symbol position
    symbol_x, symbol_y, symbol_rotation = symbol_instance.at.value

    # Pin position relative to symbol
    pin_x, pin_y, pin_angle = pin_definition.at.value

    # Apply rotation transformation
    if symbol_rotation != 0:
        # Rotate pin coordinates around origin
        rad = math.radians(symbol_rotation)
        rotated_x = pin_x * math.cos(rad) - pin_y * math.sin(rad)
        rotated_y = pin_x * math.sin(rad) + pin_y * math.cos(rad)
        pin_x, pin_y = rotated_x, rotated_y

    # Translate to absolute position
    abs_x = symbol_x + pin_x
    abs_y = symbol_y + pin_y

    return [abs_x, abs_y]
```

---

## Wire Routing Strategies

### Strategy 1: Direct Wire (Phase 1)

Simplest: single wire segment from pin A to pin B.

```
R1 pin 2        C1 pin 1
   o-------------o
```

**Pros:** Simple, fast
**Cons:** Diagonal wires (not standard practice)

### Strategy 2: Orthogonal 2-Segment (Phase 3)

Two segments: horizontal then vertical, or vertical then horizontal.

```
R1 pin 2        C1 pin 1
   o-----┐
         │
         └------o
```

**Algorithm:**
1. Calculate midpoint
2. Route horizontal to midpoint
3. Route vertical to target
4. Or vice versa based on direction

**Pros:** Standard practice, cleaner schematics
**Cons:** Slightly more complex

### Strategy 3: Manhattan Routing (Future)

Complex multi-segment paths avoiding components.

**Pros:** Professional appearance
**Cons:** Requires collision detection, path planning

---

## Testing Strategy

### Unit Tests

Test individual functions:
- `test_add_wire()` - Wire creation
- `test_get_pin_location()` - Pin discovery
- `test_add_net_label()` - Label creation
- `test_calculate_pin_position()` - Coordinate math

### Integration Tests

Test complete workflows:
- `test_connect_two_resistors()` - Wire R1 to R2
- `test_connect_to_vcc_net()` - Multiple components to VCC
- `test_generate_netlist()` - Netlist accuracy
- `test_schematic_opens_in_kicad()` - File validity

### Manual Validation

- Create test schematic in KiCad manually
- Add same connections via MCP
- Compare results
- Verify electrical connectivity in KiCad

---

## Success Metrics

### Phase 1 Success:
- [ ] `add_schematic_wire` works (coordinates)
- [ ] `add_schematic_connection` works (pin to pin)
- [ ] Wires appear in KiCad schematic
- [ ] Netlist shows connections
- [ ] 3+ integration tests passing

### Phase 2 Success:
- [ ] Net labels work (VCC, GND, etc.)
- [ ] Multiple components on same net
- [ ] `get_net_connections` returns correct results
- [ ] Netlist includes named nets
- [ ] 5+ integration tests passing

### Phase 3 Success:
- [ ] Junctions at wire intersections
- [ ] Orthogonal routing preferred
- [ ] No-connect flags on unused pins
- [ ] 10+ integration tests passing

### Phase 4 Success:
- [ ] ERC detects errors
- [ ] 95%+ test coverage
- [ ] Complete documentation
- [ ] User can create functional circuits without errors

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| kicad-skip lacks wire API | High | High | Use S-expression fallback |
| Pin discovery complex | Medium | Medium | Test with multiple symbol types |
| Rotation math errors | Medium | High | Extensive testing, validation |
| Performance issues | Low | Medium | Optimize S-expression parsing |
| KiCad format changes | Low | High | Version detection, compatibility |

---

## Dependencies

**Required:**
- kicad-skip >= 0.1.0 (or compatible)
- sexpdata (already dependency for dynamic loading)
- Python 3.8+

**Optional:**
- KiCad CLI for validation (`kicad-cli sch export netlist`)

---

## Timeline Estimate

**Phase 1:** 1 week (26 hours)
**Phase 2:** 1 week (28 hours)
**Phase 3:** 1.5 weeks (28 hours)
**Phase 4:** 1.5 weeks (28 hours)

**Total:** 5 weeks (110 hours)

**Accelerated path (core features only):** 2-3 weeks (Phases 1-2)

---

## Next Immediate Steps

1. **Research kicad-skip Wire API** (TODAY)
   - Test with Python REPL
   - Document findings
   - Choose implementation approach

2. **Create Test Environment** (TOMORROW)
   - Set up test schematic
   - Manual wire creation in KiCad
   - Export for comparison

3. **Implement Basic Wire** (THIS WEEK)
   - Update ConnectionManager.add_wire()
   - Test with simple coordinates
   - Verify in KiCad

4. **Fix Pin Discovery** (THIS WEEK)
   - Parse symbol definitions
   - Calculate absolute positions
   - Test with rotated symbols

---

## User Communication

**For Issue #26:**

Update users that:
- ✅ Component placement is DONE (with 10,000+ symbols)
- ⏳ Wire/connection tools are IN PROGRESS
- 📅 Estimated completion: 2-3 weeks for core functionality
- 🎯 Goal: Complete functional schematics with wiring

---

**Status:** Ready for implementation
**Owner:** TBD
**Priority:** HIGH (user-blocking feature)
