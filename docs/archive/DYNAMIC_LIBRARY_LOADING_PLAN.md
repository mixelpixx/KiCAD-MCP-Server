# Option 2: Dynamic Library Loading Plan

## Executive Summary

Replace the template-based schematic workflow with dynamic symbol loading from KiCad's installed symbol libraries. This would eliminate the 13-component limitation and provide access to ALL KiCad symbols (~10,000+ symbols from standard libraries).

**Current Status (Option 1):**
- ✅ Template-based approach working
- ✅ 13 component types supported
- ❌ Limited symbol variety
- ❌ Requires manual template updates for new types

**Proposed (Option 2):**
- 🎯 Dynamic loading from `.kicad_sym` library files
- 🎯 Access to ~10,000+ KiCad symbols
- 🎯 No template maintenance required
- 🎯 User can specify any library/symbol combination

---

## Problem Analysis

### kicad-skip Library Limitation

**Core Issue:** kicad-skip **cannot create symbols from scratch**. It can only:
1. Clone existing symbols from a loaded schematic
2. Modify properties of cloned symbols

**Current Workaround:** Pre-load template symbols in schematic file

**Proposed Solution:** Load symbols from KiCad's `.kicad_sym` library files, inject them into the schematic's `lib_symbols` section, then clone from there.

---

## KiCad Symbol Library Architecture

### Symbol Library File Format (`.kicad_sym`)

KiCad symbol libraries are S-expression files containing symbol definitions:

```lisp
(kicad_symbol_lib (version 20211014) (generator kicad_symbol_editor)
  (symbol "Device:R"
    (pin_numbers hide)
    (pin_names (offset 0))
    (in_bom yes)
    (on_board yes)
    (property "Reference" "R" ...)
    (property "Value" "R" ...)
    ;; Graphics definitions
    (symbol "R_0_1" ...)
    (symbol "R_1_1"
      (pin passive line ...)
    )
  )
  (symbol "Device:C" ...)
  (symbol "Device:L" ...)
  ;; ... thousands more
)
```

### Standard KiCad Library Locations

**Linux:**
- System libraries: `/usr/share/kicad/symbols/`
- User libraries: `~/.local/share/kicad/8.0/symbols/` or `~/.config/kicad/8.0/symbols/`

**Windows:**
- System libraries: `C:\Program Files\KiCad\9.0\share\kicad\symbols\`
- User libraries: `%APPDATA%\kicad\8.0\symbols\`

**macOS:**
- System libraries: `/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/`
- User libraries: `~/Library/Preferences/kicad/8.0/symbols/`

### Standard Library Files

Common libraries (each containing 50-500 symbols):
- `Device.kicad_sym` - Passives (R, C, L, D, LED, Crystal, etc.)
- `Connector.kicad_sym` - Connectors (headers, USB, etc.)
- `Connector_Generic.kicad_sym` - Generic connectors
- `Transistor_BJT.kicad_sym` - Bipolar transistors
- `Transistor_FET.kicad_sym` - MOSFETs
- `Amplifier_Operational.kicad_sym` - Op-amps
- `Regulator_Linear.kicad_sym` - Voltage regulators
- `MCU_*.kicad_sym` - Microcontrollers
- `Interface_*.kicad_sym` - Interface ICs
- ... 100+ more libraries

---

## Implementation Strategy

### Phase 1: Library Discovery & Indexing

**Goal:** Build an index of all available symbols and their locations

**Implementation:**
```python
class SymbolLibraryManager:
    def __init__(self):
        self.library_paths = []
        self.symbol_index = {}  # {"Device:R": "/path/to/Device.kicad_sym", ...}

    def discover_libraries(self):
        """Find all KiCad symbol libraries on the system"""
        search_paths = [
            "/usr/share/kicad/symbols/",
            os.path.expanduser("~/.local/share/kicad/8.0/symbols/"),
            os.path.expanduser("~/.config/kicad/8.0/symbols/"),
        ]

        for search_path in search_paths:
            if os.path.exists(search_path):
                for lib_file in os.listdir(search_path):
                    if lib_file.endswith('.kicad_sym'):
                        self.library_paths.append(os.path.join(search_path, lib_file))

    def index_symbols(self):
        """Parse all libraries and build symbol index"""
        for lib_path in self.library_paths:
            lib_name = os.path.basename(lib_path).replace('.kicad_sym', '')
            symbols = self._parse_library(lib_path)

            for symbol_name in symbols:
                full_name = f"{lib_name}:{symbol_name}"
                self.symbol_index[full_name] = {
                    'library': lib_name,
                    'library_path': lib_path,
                    'symbol_name': symbol_name
                }

    def _parse_library(self, lib_path):
        """Parse .kicad_sym file and extract symbol names"""
        # Use sexpdata (already a dependency of kicad-skip)
        import sexpdata

        with open(lib_path, 'r') as f:
            data = sexpdata.load(f)

        symbols = []
        for item in data[2:]:  # Skip header
            if isinstance(item, list) and item[0] == Symbol('symbol'):
                symbol_name = item[1]  # e.g., "Device:R"
                # Extract just the symbol part after ':'
                if ':' in symbol_name:
                    symbol_name = symbol_name.split(':')[1]
                symbols.append(symbol_name)

        return symbols
```

### Phase 2: Dynamic Symbol Injection

**Goal:** Load symbol definition from library file and inject into schematic

**Challenge:** kicad-skip works with loaded schematics, but we need to dynamically add symbols to the `lib_symbols` section.

**Solution:** Modify the schematic's S-expression data directly before loading with kicad-skip:

```python
def inject_symbol_into_schematic(schematic_path, library_path, symbol_name):
    """
    1. Read schematic S-expression
    2. Read library S-expression
    3. Extract symbol definition from library
    4. Inject into schematic's lib_symbols section
    5. Save modified schematic
    6. Reload with kicad-skip
    """
    import sexpdata

    # Load schematic
    with open(schematic_path, 'r') as f:
        sch_data = sexpdata.load(f)

    # Load library
    with open(library_path, 'r') as f:
        lib_data = sexpdata.load(f)

    # Find symbol definition in library
    symbol_def = None
    for item in lib_data[2:]:
        if isinstance(item, list) and item[0] == Symbol('symbol'):
            if symbol_name in str(item[1]):
                symbol_def = item
                break

    if not symbol_def:
        raise ValueError(f"Symbol {symbol_name} not found in {library_path}")

    # Find lib_symbols section in schematic
    lib_symbols_index = None
    for i, item in enumerate(sch_data):
        if isinstance(item, list) and item[0] == Symbol('lib_symbols'):
            lib_symbols_index = i
            break

    # Inject symbol definition
    if lib_symbols_index:
        sch_data[lib_symbols_index].append(symbol_def)

    # Save modified schematic
    with open(schematic_path, 'w') as f:
        sexpdata.dump(sch_data, f)

    # Reload with kicad-skip
    return Schematic(schematic_path)
```

### Phase 3: Template Instance Creation

**Goal:** Create offscreen template instances that can be cloned

**After injection:** Symbol definition is in `lib_symbols`, but we need an instance to clone from:

```python
def create_template_instance(schematic, library_name, symbol_name):
    """
    Create an offscreen template instance that can be cloned
    Similar to our current _TEMPLATE_R approach
    """
    # This requires directly manipulating the S-expression
    # Add a symbol instance at offscreen position with special reference

    template_ref = f"_TEMPLATE_{library_name}_{symbol_name}"

    # Create symbol instance (S-expression)
    symbol_instance = [
        Symbol('symbol'),
        [Symbol('lib_id'), f"{library_name}:{symbol_name}"],
        [Symbol('at'), -100, -100 - (len(schematic.symbol) * 10), 0],
        [Symbol('unit'), 1],
        [Symbol('in_bom'), Symbol('no')],
        [Symbol('on_board'), Symbol('no')],
        [Symbol('dnp'), Symbol('yes')],
        [Symbol('uuid'), str(uuid.uuid4())],
        [Symbol('property'), "Reference", template_ref, ...],
        # ... more properties
    ]

    # Inject into schematic and reload
    # ... (similar to inject_symbol_into_schematic)

    return template_ref
```

### Phase 4: User-Facing API

**Goal:** Simple interface for users to add any KiCad symbol

**New MCP Tool: `add_schematic_component_dynamic`**

```python
def add_schematic_component_dynamic(params):
    """
    Add component by library:symbol notation

    Example:
    {
        "library": "Device",
        "symbol": "R",
        "reference": "R1",
        "value": "10k",
        "x": 100,
        "y": 100
    }

    OR using full notation:
    {
        "lib_symbol": "Device:R",  # Full notation
        "reference": "R1",
        ...
    }
    """
    lib_symbol = params.get('lib_symbol') or f"{params['library']}:{params['symbol']}"

    # 1. Check if symbol is already in schematic's lib_symbols
    # 2. If not, inject it from library file
    # 3. Create template instance if needed
    # 4. Clone template and set properties

    return {"success": True, "reference": params['reference']}
```

---

## Advantages Over Template Approach

### ✅ Unlimited Symbol Access
- Access to ~10,000+ standard KiCad symbols
- Support for custom user libraries
- Support for 3rd-party libraries (JLCPCB, Espressif, etc.)

### ✅ No Maintenance Required
- Template doesn't need updates for new component types
- Automatically supports new KiCad library additions
- Works with custom symbol libraries

### ✅ Better User Experience
```
User: "Add an STM32F103C8T6 microcontroller at position 100,100"
AI: *Searches symbol index*
    *Finds MCU_ST_STM32F1:STM32F103C8Tx*
    *Loads from library*
    *Injects into schematic*
    *Places component*
    ✓ Done!
```

### ✅ Flexible Symbol Search
```python
# Find all resistors
symbols = lib_manager.search_symbols(query="resistor")
# Returns: ["Device:R", "Device:R_Small", "Device:R_Network", ...]

# Find all STM32 MCUs
symbols = lib_manager.search_symbols(query="STM32", library="MCU_ST_STM32F1")
```

---

## Challenges & Mitigations

### Challenge 1: S-expression Manipulation Complexity

**Problem:** Directly manipulating S-expression data is error-prone

**Mitigation:**
- Use `sexpdata` library (already a dependency)
- Create helper functions for common operations
- Add comprehensive validation and error handling
- Extensive testing with various symbol types

### Challenge 2: Performance

**Problem:** Loading/reloading schematics after injection could be slow

**Mitigation:**
- **Cache loaded symbols**: Once injected, symbol stays in schematic
- **Batch injection**: Inject multiple symbols at once
- **Lazy loading**: Only inject symbols when first used

### Challenge 3: Symbol Compatibility

**Problem:** Some symbols may have complex pin configurations or multiple units

**Mitigation:**
- Start with simple 2-pin passives (R, C, L)
- Gradually add support for multi-pin ICs
- Handle multi-unit symbols (gates, OpAmp sections) explicitly
- Document supported symbol types

### Challenge 4: Library Version Compatibility

**Problem:** KiCad symbol format may change between versions

**Mitigation:**
- Parse KiCad version from library files
- Version-specific handling if needed
- Fallback to template approach for unsupported formats

---

## Implementation Phases

### Phase A: Proof of Concept (1-2 weeks)
- [ ] Create `SymbolLibraryManager` class
- [ ] Implement library discovery (Linux paths only)
- [ ] Implement symbol indexing
- [ ] Test with Device.kicad_sym (R, C, L)
- [ ] Implement basic S-expression injection
- [ ] Test end-to-end with simple components

### Phase B: Core Functionality (2-3 weeks)
- [ ] Cross-platform library discovery (Windows, macOS)
- [ ] Symbol search functionality
- [ ] Template instance creation automation
- [ ] Multi-pin component support
- [ ] Error handling and validation
- [ ] Unit tests for all operations

### Phase C: MCP Integration (1 week)
- [ ] Create `add_schematic_component_dynamic` tool
- [ ] Update `search_symbols` to use library index
- [ ] Add `list_available_symbols` tool
- [ ] Add `list_symbol_libraries` tool
- [ ] Documentation and examples

### Phase D: Advanced Features (2-3 weeks)
- [ ] Multi-unit symbol support (e.g., quad OpAmps)
- [ ] Custom library registration
- [ ] Symbol caching and optimization
- [ ] 3rd-party library support (JLCPCB, etc.)
- [ ] Symbol preview generation

---

## Migration Strategy

### Backward Compatibility

Keep template-based approach as fallback:

```python
def add_schematic_component(params):
    """Smart component addition with fallback"""
    # Try dynamic loading first
    try:
        if 'library' in params or 'lib_symbol' in params:
            return add_schematic_component_dynamic(params)
    except Exception as e:
        logger.warning(f"Dynamic loading failed: {e}, falling back to template")

    # Fallback to template-based
    return add_schematic_component_template(params)
```

### Gradual Rollout

1. **Week 1-2:** Implement basic dynamic loading
2. **Week 3-4:** Test with power users, gather feedback
3. **Week 5-6:** Make dynamic loading the default
4. **Week 7+:** Deprecate template-only approach (keep as fallback)

---

## Success Criteria

### Must Have
- [ ] Load symbols from Device.kicad_sym (passives)
- [ ] Support R, C, L, D, LED (5 core types)
- [ ] Cross-platform library discovery
- [ ] Proper error handling

### Should Have
- [ ] Support for all Device.kicad_sym symbols (~50 symbols)
- [ ] Support for Connector.kicad_sym symbols
- [ ] Symbol search by name/keyword
- [ ] Performance: < 1 second per symbol injection

### Nice to Have
- [ ] Support for all standard libraries (~10,000 symbols)
- [ ] Multi-unit symbol support
- [ ] Custom library registration
- [ ] Symbol preview/documentation

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| S-expression parsing complexity | High | High | Use proven `sexpdata` library, extensive testing |
| Performance degradation | Medium | Medium | Implement caching, lazy loading |
| KiCad version incompatibility | Low | High | Version detection, format validation |
| Template fallback breaks | Low | Medium | Maintain template approach in parallel |
| User confusion | Medium | Low | Clear documentation, gradual rollout |

---

## Conclusion

Dynamic library loading is **feasible and highly beneficial** for the schematic workflow. While the template-based approach (Option 1) provides immediate value with 13 component types, Option 2 would:

1. **Eliminate the 13-component limitation**
2. **Provide access to 10,000+ KiCad symbols**
3. **Remove manual template maintenance**
4. **Enable true "natural language PCB design"**

**Recommendation:**
- ✅ **Keep Option 1 (expanded template) for immediate use**
- ✅ **Implement Option 2 (dynamic loading) over 6-8 weeks**
- ✅ **Maintain template fallback for compatibility**

This gives users immediate value while we build the robust long-term solution.

---

## References

- [KiCad File Formats Documentation](https://dev-docs.kicad.org/en/file-formats/)
- [kicad-skip GitHub](https://github.com/mvnmgrx/kicad-skip)
- [sexpdata Python Library](https://github.com/jd-boyd/sexpdata)
- [KiCad Symbol Library Format Spec](https://dev-docs.kicad.org/en/file-formats/sexpr-intro/)
