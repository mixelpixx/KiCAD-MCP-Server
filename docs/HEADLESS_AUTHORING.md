# Headless Schematic Authoring Guide

Field-tested practice for driving the KiCAD MCP Server without the KiCad
GUI: the per-sheet build recipe, diagnostics, ERC triage, and verification
discipline. Distilled from building a complete multi-sheet automotive
carrier design entirely through the server (observed on KiCad 9/10, Linux).

See [SCHEMATIC_TOOLS_REFERENCE.md](SCHEMATIC_TOOLS_REFERENCE.md) for
per-tool parameters and [ARCHITECTURE.md](ARCHITECTURE.md) for how the
server is put together.

---

## 1. Two parsers, one truth

Two different parsers are in play, and they disagree — this is the source
of most headless pitfalls:

| Parser         | Used by                                                                                        | Character                                  |
| -------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------ |
| **kicad-cli**  | `run_erc`, all `export_*`, netlist generation                                                  | Ground truth (what KiCad does)             |
| **kicad-skip** | editing/inspection tools (`list_schematic_components`, `batch_connect`, pin location, labels…) | Stricter; rejects some files KiCad accepts |

**Diagnostic rule: when a skip-based tool disagrees with ERC or a render,
believe kicad-cli.** A schematic can be perfectly valid KiCad and still be
skip-hostile (see §7a). Schematic load failures surface as a structured
`schematic_load_failed` error naming the offending symbols rather than
empty results — treat that error as authoritative, not as noise.

---

## 2. Per-sheet build recipe

A proven flow for authoring one sheet end-to-end:

1. `create_schematic(name, path)` — starts from a blank template.
2. `batch_add_and_connect(schematicPath, components: [...])` — place
   symbols and connect their pins by net name in one call.
   - Use `labelType: "global_label"` when the design connects across
     sheets by name (one valid convention for generated designs — power
     rails and cross-sheet signals join by label name, no wires).
   - Put component origins on a **2.54 mm grid** (pin offsets are
     1.27/2.54 multiples, so pins land on the connection grid).
   - Space parts ~12.7 mm apart so labels don't overlap (a global label
     extends ~7.6 mm from the pin).
3. `batch_add_no_connects(schematicPath, pins: [...])` — flag genuinely
   unused pins so they don't show up as ERC errors.
4. `run_erc(schematicPath)` — expect **0 errors**; triage warnings per §4.
5. `export_schematic_svg(schematicPath, outputPath)` — render the sheet,
   convert to PNG with any converter, and **eyeball it**.

---

## 3. Verification discipline

The skip-based tools have blind spots; a sheet is only _done_ when all
three hold:

1. `run_erc` reports **0 errors**, with warnings triaged (§4), AND
2. the exported SVG/PDF has been **rendered and eyeballed** for misplaced
   or overlapping labels and wrong topology, AND
3. `generate_netlist` / `export_netlist` confirms the expected net→pin
   map for anything you are not sure about.

**Never trust "connected N pin(s)" alone.** Cross-check with kicad-cli
ERC and a render. Historically the batch tools could report success while
the sheet was unparseable; load failures now error loudly, but the
render+ERC+netlist habit remains the safety net.

---

## 4. Reading ERC output

- **Coordinates are mm/100** in the report: `@ (0.78, 1)` means
  (78 mm, 100 mm). Decode them to map an error back to a component's
  `(at x y)`. Negative coordinates usually mean off-page junk.
- **Benign warnings** (don't chase these):
  - `Symbol 'X' doesn't match copy in library` — embedded lib_symbol vs
    installed library version drift. Cosmetic.
  - `The current configuration does not include the symbol library 'Y'` —
    a project-local vendor library not in the global table. Cosmetic.
- **Per-sheet ERC is the wrong metric for consumer sheets** in a
  global-label design: every fabric-sourced signal feeding an input pin
  shows `pin_not_driven`, and every cross-sheet net shows "label connected
  to only one pin" — per sheet. Validate the whole design with
  full-hierarchy ERC from the root sheet
  (`kicad-cli sch erc root.kicad_sch`, or `run_erc` on the root). Triage:
  real problems = `pin_to_pin` conflicts, typo'd dangling nets, unplaced
  power units; benign = `pin_not_driven` on off-board inputs and
  single-pin labels for genuinely two-sheet nets.

---

## 5. Power nets and PWR_FLAG

ERC wants exactly **one driver per power net, design-wide**:

- Rails driven by a regulator's `power_output` pin need **no** flag.
- Rails fed only by passive/connector pins need exactly **one**
  `power:PWR_FLAG` — owned by the rail's _originating_ sheet.
- Multiple flags on one net, or a flag on a net already driven by a
  `power_output` pin, produce `Power output and Power output are
connected` errors at full-hierarchy ERC.
- Watch vendor symbols: their output pins are often typed `passive`, so
  those rails **do** need a flag.

Per-sheet ERC will warn about "undriven" globals whose flag lives on
another sheet — that resolves at full-hierarchy ERC (§4).

---

## 6. The 1.27 mm connection grid

KiCad's schematic connection grid is fixed at **50 mil = 1.27 mm**, and
junction placement uses exact matching. One off-grid wire endpoint or
symbol origin can poison junction placement **for the entire sheet**, even
on items that are on-grid (field-verified: a single capacitor origin
0.03 mm off 157.48 mm bricked a whole page). A 25-mil editing grid makes
it worse — 25-mil points fall _between_ the connection points.

- Off-grid coincident pin+label still _connects_ (warnings, not
  disconnects) — but place symbol origins on 2.54 mm anyway.
- **Remediation:** run `lint_offgrid` to report every off-grid wire
  endpoint, symbol origin, and label/junction anchor, and `fix: true` to
  snap sub-0.5 mm offenders in place with formatting-preserving edits.
  `snap_to_grid` is the bulk alternative (whole-file rewrite).
- Property field positions (Reference/Value text) are often off-grid —
  they are **cosmetic** and irrelevant to junctions; don't churn them.
  Never snap coordinates inside `(lib_symbols)` — those are local pin
  definitions and moving them deforms the symbol. (`lint_offgrid`
  excludes both automatically.)

---

## 7. Symbol gotchas

### a. Flat SnapEDA/SamacSys vendor symbols

Vendor `.kicad_sym` captures often put pins and graphics directly under
the top-level `(symbol "NAME" ...)` with no `_1_1` sub-unit. kicad-cli
tolerates this; **kicad-skip crashes on it**, taking down every skip-based
tool for any sheet that uses the symbol. Sheets also embed a snapshot of
the symbol in their own `(lib_symbols)`, so a sheet built before the
library was fixed stays broken until its embedded copy is repaired too.

Load failures surface as a structured error naming the offenders:
`{"error": "schematic_load_failed", "flatSymbols": ["LIB:PART"]}`. Run
**`repair_flat_symbols`** on the `.kicad_sym` library _and_ on any
`.kicad_sch` that embeds a snapshot — it wraps the pins/graphics in a
proper `(symbol "NAME_1_1" ...)` sub-unit via text insertion (dry-run by
default, render-neutral, idempotent).

### b. Multi-unit symbols with a separate power unit

Some symbols (e.g. `74xx:74LS139`) put VCC/GND in a separate power unit.
Placing only unit A yields `missing_power_pin` ERC errors and dangling
power labels. Place the power unit explicitly, or prefer single-unit
variants.

### c. Exposed-pad pins

DFN/QFN parts often type the thermal PAD pin as `power_input`; it errors
(`pin_not_connected` + `power_pin_not_driven`) unless explicitly tied —
usually to GND.

### d. Deleting a wired component leaves its labels

`batch_add_and_connect` places a symbol plus a separate co-located label
on each pin. Deleting the symbol alone orphans those labels
(`label_dangling` ERC errors). Pass
`deleteAttachedLabels: true` to `delete_schematic_component` when
permanently removing a wired part — it removes the pin-coincident labels
unless they still serve a wire or another component's pin.

---

## 8. Diagnostic toolbox

- **Parse-check with ground truth:** `kicad-cli sch export svg|pdf` on the
  sheet — if it renders, the file is valid KiCad regardless of what a
  skip-based tool says.
- **Valid-but-skip-hostile vs truly broken:**
  `python -c "import sexpdata; sexpdata.loads(open('f').read())"` and
  `python -c "from skip import Schematic; Schematic('f')"` isolate the two
  cases (the first passing while the second fails = §7a).
- **Why won't a pin wire?** Compare `get_schematic_pin_locations(ref)`
  against `list_schematic_labels` — labels must be coincident with pin
  endpoints. If a vendor symbol's pins come back as a synthetic stack at
  the origin, the symbol failed to load — repair it (§7a).
- **What's really connected?** `generate_netlist` / `export_netlist` is
  the authoritative net→pin answer.
- **Render and look:** export SVG, convert to PNG with any converter, and
  inspect it. Always eyeball before declaring a sheet done.
- **Raw inspection:** grep the `.kicad_sch` for top-level
  `(symbol (lib_id "...") (at x y a))` instances when a tool hides
  something (off-page items, negative coordinates).

---

## 9. Cosmetic cleanup (safe passes only)

Generated sheets are electrically correct but hard to hand-edit. Three
passes are netlist-safe because they never move a symbol, pin, wire,
junction, or label anchor:

1. **`lint_schematic_cosmetic` pass `hide_pin_names`** — hide the symbol's
   internal pin-name text, which duplicates the net label already sitting
   on each pin.
2. **`lint_schematic_cosmetic` pass `orient_labels`** — set each label's
   text angle/justify from the outward side of the pin it sits on, so text
   reads away from the body (rotation/mirror aware). Don't blanket-flatten
   labels: vertical is _correct_ for top/bottom pins.
3. **`autoplace_schematic_fields`** — move Reference/Value fields off the
   body and clear of net labels.

**Discipline:** prove zero connectivity drift with a golden-netlist diff —
`kicad-cli sch export netlist --format kicadxml` on the root sheet before
and after, comparing net → {REF.PIN} sets.

Converting label-pairs into real wires is **placement judgment, not a safe
mass operation** — component repositioning and per-pin label management
are involved; do it collaboratively per sheet, verifying each with the
golden-netlist diff.
