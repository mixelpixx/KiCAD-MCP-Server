# Changelog

All notable changes to the KiCAD MCP Server project are documented here.

## [Unreleased]

### Performance

- **Module-level caches for symbol library discovery, resolution, and
  extraction** (#299): a fresh `DynamicSymbolLoader` is created for every
  `add_schematic_component` call and a fresh `SymbolLibraryManager` (with its
  warm-up thread) for every `KiCADInterface`, so instance-level caches never
  survived — each component add re-scanned the sym-lib-table and re-read
  multi-MB `.kicad_sym` files, and each interface construction re-parsed all
  installed libraries on its own thread (super-linear cost across the test
  suite). Library directories, resolved library paths, extracted symbol
  blocks, and parsed symbol lists are now cached process-wide. Staleness
  guards, because libraries are NOT immutable mid-session (`create_symbol`,
  `delete_symbol`, `add_symbol_property`, `register_symbol_library`):
  resolution misses are never cached, resolved paths are revalidated with
  `exists()`, block/list entries carry the source file's `mtime_ns`, and the
  mutating write paths explicitly clear the caches. Tests can skip the
  speculative warm-up via `KICAD_SKIP_SYMBOL_WARMUP=1`.

### New Features

- **Symbol property tools** (#308): `add_symbol_property` adds or updates a
  custom property (Manufacturer, MPN, LCSC, ...) on a symbol in a
  `.kicad_sym` library file — the durable, library-wide path for BOM fields.
  `add_library_symbol_property` does the same on a symbol definition in a
  schematic's `lib_symbols` cache; note those cache edits are overwritten by
  a later `update_symbol_from_library` refresh, so the tool descriptions
  steer callers to the library-file tool first.

- **`update_symbol_from_library` tool** (#291): refresh the cached
  `lib_symbols` definitions in one schematic, a list of schematics, or every
  project under a directory from the current `.kicad_sym` library — the
  programmatic equivalent of KiCad's Update Symbol from Library. Placed
  instances are preserved (per-pin uuids, references, `instances` blocks);
  power symbols have their `(power)` wrapper flattened to the schematic
  layout; mirror-cache symbols (`__m0`, `__m90`, ...) are skipped, with an
  optional `repairMirrorFromBackup` to restore them from a pre-update
  backup. Writes go through the canonical formatter.

### Tooling

- **pathlib migration, first slice**: `kicad_interface.py` and
  `schematic_handlers.py` now use `pathlib.Path` for file-path handling
  (`os.path.normcase` remains in `_normalize_board_path` — it has no pathlib
  equivalent). Values crossing into JSON responses and subprocess argv stay
  `str`. Also strips a stray UTF-8 BOM from `commands/export.py` and bumps
  mypy's `python_version` to 3.10 — required by current mypy, which dropped
  the 3.9 target (note: the project's declared `requires-python = ">=3.9"`
  floor is therefore no longer verified by the type checker). `export.py`
  and the remaining `os.path` call sites are follow-up slices.

- **Interface construction smoke test**: a new test constructs
  `KiCADInterface` with the stubbed pcbnew and asserts every
  `command_routes` entry is callable, every schema-listed tool has a route,
  and recently-added tools are present. A route entry referencing a renamed
  or un-imported handler function passes every module-level test but
  crashes the server at startup with `NameError` (#308 shipped exactly
  that); this makes the class unshippable.

### Bug Fixes

- **`add_schematic_component` snaps the placement origin to the 1.27 mm
  (50 mil) schematic connection grid** (#299): library pins sit at integer
  multiples of 1.27 mm from the symbol origin, so an off-grid origin leaves
  every pin off-grid — wires and net labels cannot bind electrically, ERC
  reports `endpoint_off_grid`, and the netlist comes up empty. The snap is
  always on; the handler response reports the actual `placed_at` position
  (looked up by reference, so multiple instances of the same symbol report
  correctly) plus `snapped: true` and `requested_at` when the coordinates
  were adjusted. Snapped values are written with at most two decimals —
  exact for every multiple of 1.27 — instead of raw float products.

- **`sync_schematic_to_board` no longer re-parses the fp-lib-table on every
  call** (#248): `_add_missing_footprints_from_schematic` built a fresh
  `LibraryManager` — re-parsing the global and project `fp-lib-table` files,
  recursively following any `Table` references — on every single invocation.
  In an iterative rebuild flow (call `sync_schematic_to_board`, tweak the
  schematic, call it again), that overhead was paid again each time even
  though the project hadn't changed. The interface now caches the
  `LibraryManager` via `_get_project_library_manager`, keyed on the project
  directory plus the mtimes of the fp-lib-table files it parses, so the
  cache is reused across repeat calls but rebuilds automatically when a
  table changes (e.g. `register_footprint_library`, or a KiCad GUI edit
  mid-session).

- **Fixed a test-suite state leak that caused spurious pin-position failures
  when test files ran in combination** (#287): `tests/test_rotate_schematic_mirror.py`
  installed a throwaway `MagicMock` at `sys.modules["commands.pin_locator"]`
  via `sys.modules.setdefault(...)` at module-collection time, with no
  teardown. Any later-collected file relying on the real
  `commands.pin_locator` (e.g. `WireDragger.get_pin_defs`, via
  `commands.wire_dragger`) silently got empty pin data instead of an error —
  iterating a bare `MagicMock()` is a no-op by default. A `teardown_module`
  now undoes the stub, and `test_rotate_handler_no_crash`'s stubbed
  `kicad_interface.py` exec additionally evicts any `commands.*` submodule it
  imported for the first time while `pcbnew`/`skip` were mocked, so later
  tests get a clean re-import instead of a module bound to a discarded mock.
  Test-only change; no production code touched.

- **`import_ses` no longer creates phantom slashless nets — routed tracks bind
  to the real board nets** (#246): KiCad global-label nets are named with a
  leading `/` (e.g. `/GND`), but a Specctra DSN round-trip through Freerouting
  can drop that prefix. `ImportSpecctraSES` then fails its exact-string net
  lookup and creates a _new_ slashless net (`GND`), leaving `/GND` unconnected
  and every routed track flagged by DRC. `import_ses` now reconciles the SES
  before import: a pure `_reconcile_ses_net_names` re-adds the `/` to any
  `(net "NAME" …)` token that matches a board net only when prefixed (idempotent;
  names that genuinely have no slash on the board are left untouched), and the
  repaired copy is imported. Any reconciliation error falls back to importing the
  original file unchanged; the response reports `netsRemapped`.

- **`add_sheet_pin` finds sheets regardless of line formatting; sheet/text
  insertion no longer splices mid-line** (#298): `add_hierarchical_sheet`
  and the wire/label/text insert helper located their insertion point with
  `content.rfind(...)` — a raw character offset — so on files where the
  marker does not start its own line (sexpdata-written schematics keep
  several forms on one line) the new block landed mid-line. `add_sheet_pin`
  then scanned line-by-line for `(sheet` at the start of a line and could
  never find such a sheet, failing with "sheet not found" on a sheet that
  plainly existed. Insertions now snap to a line boundary (breaking the
  line when the marker shares it), and `add_sheet_pin` scans by character
  with paren matching, so it also works on files already written with
  mid-line sheets and on fully minified single-line schematics.

- **`export_dsn`/`autoroute` no longer drop `.kicad_pro` net classes — power
  nets keep their width** (#302): net-class definitions live in the project
  file on KiCad 7+, which the headless `pcbnew.LoadBoard()` path never reads,
  so `ExportSpecctraDSN` exported every net under a single `kicad_default`
  class at Default width/clearance. The one-call `autoroute` tool re-exports
  internally, so a 2.0 mm power net was silently handed to Freerouting at
  0.2 mm signal width. Both tools now rebuild the board's `NET_SETTINGS` from
  `.kicad_pro` (`net_settings.classes`, `netclass_patterns`, and
  `netclass_assignments`, via a new `python/utils/project_netclasses.py`)
  before exporting, so KiCad's own exporter natively emits per-class
  `(class ...)` blocks, rules, and via padstacks — verified against real
  KiCad 10 to match a project-loaded GUI export. The tool result now carries
  a `netClasses` report (`applied` classes, or a `warning` when no project
  file is found or the classes cannot be applied), so a dropped class is
  loud instead of silent.

## [2.3.1] - 2026-07-05

Eight merges since v2.3.0: the entire June scaffolding cluster (#220/#221/
#242/#243) is closed, KiCad install discovery is unified across all Windows
code paths, derived symbols in `.kicad_symdir` libraries resolve correctly,
and three new feature areas land (Eagle import, 3D model tools, interactive
schematic reload). A critical compatibility fix ensures generated schematics
load on every KiCad 10.0.x build.

### New Features

- **Eagle schematic import** (#285): `import_eagle_schematic` converts Eagle
  `.sch` XML designs to KiCad `.kicad_sch` format — symbol mapping, net
  wires, labels, junctions, multi-gate parts (combined into multi-unit KiCad
  symbols). Dangling-wire pruning trims isolated stubs; a ground-truth ERC
  check via `kicad-cli` reports the real error/warning counts so callers see
  KiCad's numbers, not the importer's internal model.

- **3D model tools** (#263): `add_component_3d_model` and
  `remove_component_3d_model` attach/detach STEP/WRL 3D models to footprints
  with offset, rotation, and scale. Respects backend session pinning.

- **Opt-in interactive schematic reload on Windows** (#208): set
  `KICAD_INTERACTIVE_SCHEMATIC=1` and schematic-writing tools will
  auto-confirm KiCad's "file changed — reload?" dialog so the editor stays
  in sync. PID-scoped, title-keyword-matched (not generic "Confirmation"
  dialogs), and never clicks Discard/Unsaved buttons.

- **User environment variables from `kicad_common.json`** (#292): the
  `${VARIABLE}` placeholders KiCad users define in Preferences are now
  resolved when expanding library paths, so custom env-var-based library
  setups work out of the box.

### Bug Fixes

- **`get_wire_connections` locates pins correctly on rotated symbols**:
  `_find_pins_on_net` computed pin world coordinates with a local transform
  that applied mirror before rotation, diverging from `WireDragger.pin_world_xy`
  (the shared transform corrected in #259) for 90 and 270 degree rotations. Pins
  on rotated symbols were placed at the wrong coordinate and dropped from their
  own net's pin list (observed on an LM324 whose gates are placed rotated 90:
  eight of its pins went missing from their nets). `_find_pins_on_net` now calls
  `pin_world_xy` so pin geometry matches eeschema everywhere. Single-unit and
  unrotated parts are unaffected.

- **`get_wire_connections` no longer reports phantom cross-unit pins** (#293):
  `_find_pins_on_net` transformed every unit's pins against every placed
  instance of a multi-unit component, so a sibling unit's pin whose library
  offset matched could land on this instance's wire and be reported as a
  false member of the net (e.g. an LM358's pin 7 appearing on unit A's
  output net alongside pin 1). `_parse_symbol_instances_sexp` now records
  each instance's `(unit N)`, and `_find_pins_on_net` filters the pin
  definitions to that unit (plus unit 0, common to all units) before
  transforming them. Complements #272, which fixed the query-coordinate side
  of the same multi-unit gap; the pin `unit` tags it added are what this fix
  consumes. Single-unit parts are unaffected.

- **KiCad install discovery is unified and finds relocated Windows installs**
  (#286): `kicad-cli` resolution, symbol/python-path discovery, and footprint-dir
  lookup each independently assumed KiCad lived under `C:\Program Files\KiCad`, so
  a custom install root (the installer allows any; short roots like
  `C:\KiCad\10.0` are common) got degraded discovery in three different ways. A
  new shared helper `python/utils/kicad_roots.py` yields KiCad install roots
  newest-version first from the Windows registry uninstall keys
  (`InstallLocation`, authoritative for wherever the user installed), the
  `C:\Program Files\KiCad\*` / `(x86)` globs, and common custom roots
  (`C:\KiCad\*`), de-duplicated and cached per-process. `utils/kicad_cli.py`,
  `utils/platform_helper.py`, `commands/library.py` (footprints), and
  `commands/library_symbol.py` (symbols) now build their Windows paths from it, so
  discovery
  can no longer drift apart (the same unification #267 did for the three
  `kicad-cli` resolvers). macOS/Linux behavior is unchanged.

- **Derived symbols in KiCad 10 `.kicad_symdir` libraries now inline their parent**
  (#282): in the sharded directory format each symbol is its own
  `<Symbol>.kicad_sym` file, so a symbol using `(extends "Parent")` has its parent
  in a _sibling_ shard. `extract_symbol_from_library` handed only the child's shard
  to the inliner, so the parent was never found and the `(extends)` clause was
  stripped — producing a symbol shell with no parent pins/graphics (e.g.
  `Device:Filter_EMI_C`, which extends `C_Feedthrough`). A new
  `_resolve_symdir_extends` reads the parent shard, resolves it recursively (a
  parent may itself extend a grandparent in another shard), and merges it via the
  existing single-level inliner; a missing parent shard still degrades gracefully
  (strips + warns, keeping the file loadable). Single-file `.kicad_sym` libraries
  are unaffected.

- **New projects and schematics start blank instead of seeding `_TEMPLATE_*`
  symbols** (#221, #243): `create_project` and `create_schematic` copied
  `template_with_symbols_expanded.kicad_sch` / `template_with_symbols.kicad_sch`,
  which pre-seeded `Device:R/C/LED` `lib_symbols` and placed `_TEMPLATE_*`
  instances into every new file. Those symbols existed only as clone sources for
  the legacy `ComponentManager.add_component` path; the live
  `add_schematic_component` tool synthesizes its own `lib_symbols` via the
  dynamic loader (and the legacy fallback was removed in #288), so the seeds only
  leaked into user files. Both tools now copy a new blank KiCad 10 template
  (`python/templates/blank.kicad_sch`: `(version 20260101) (generator
  "eeschema")`, empty `lib_symbols`, no placed symbols).
  `template_with_symbols.kicad_sch` is kept unchanged in-repo as a test fixture.
  A regression test asserts a created schematic contains no `_TEMPLATE_`
  references and no seeded `lib_symbols` entries.

- **Generated schematics use format version `20260101`, not `20260306`, so
  every KiCad 10.0.x can open them**: KiCad refuses to load files that claim
  a format version newer than the running build, and `20260306` is a later
  10.0.x token — KiCad 10.0.0 (whose `kicad-cli sch upgrade` writes
  `20260101`) reported "Failed to load schematic" on our output. All
  templates, fallback writers, and test fixtures now use `20260101`, which
  loads on every 10.0.x (newer builds silently upgrade on save). This also
  makes `tests/fixtures/canonical_schematic.kicad_sch` loadable by
  `kicad-cli`, which it previously was not.

- **`create_project` writes a conformant KiCad 10 `.kicad_pro`** (#220): the
  project file was a hand-rolled 122-byte stub containing only
  `board.filename` and a `sheets` entry with the literal id `"root"`, so
  KiCad regenerated defaults on open and discarded any intended
  configuration. A new writer (`python/utils/kicad_project.py`) emits the
  full structure KiCad 10 itself produces for a new project — captured from
  pcbnew's own `SETTINGS_MANAGER.SaveProject()` output (`meta.version 3`,
  all twelve sections, the stock Default net class) — with `sheets` carrying
  the real schematic root-sheet UUID. Verified against real KiCad 10:
  `SETTINGS_MANAGER.LoadProject` opens the generated file, and project ERC
  runs clean.

## [2.3.0] - 2026-07-03

The first tagged release. Highlights: both KiCad 10 schematic-corruption
mechanisms are fixed (incomplete instance blocks and minified single-line
writes — #256), the SWIG/IPC backend is pinned per loaded project so edits
can no longer be lost to silent backend switching (#223), saves refuse to
clobber external file edits (#244), and the entire cli-tool family works on
stock Windows installs where KiCad is not on PATH.

Behavior changes to note when upgrading from 2.2.3: `rotate_component`
treats `angle` as an absolute target (previously additive over IPC);
`save_project` can now return `success: false` with
`diskChangedExternally: true` instead of overwriting (pass `force: true`
for the old behavior); and a session loaded on SWIG stays on SWIG even when
the KiCad GUI connects later (reopen the project to adopt IPC).

### Tooling

- **TypeScript test scaffolding (Vitest)**: `npm run test:ts` now runs a real
  Vitest suite instead of the placeholder echo. Starter coverage lives in
  `tests-ts/` and exercises the pure-function modules `src/tools/registry.ts`
  (categories, direct vs. routed classification, search, and stats invariants)
  and `src/tools/tool-response.ts` (`formatKicadResult` success/error shaping).
  Use `npm run test:ts:watch` for the watch-mode REPL. The CI `typescript-tests`
  job now invokes the suite directly instead of swallowing failures.

- **Version sync**: `package.json` now reports `2.2.3`, matching the released
  version documented in this changelog and in `docs/ROADMAP.md`. Previously it
  was stuck at `2.1.0-alpha`.

### Bug Fixes

- **Placed symbols get complete KiCad 10 instance blocks — no more crash on
  drag/edit** (#256, first half): `create_component_instance` was rewritten
  into a full KiCad 10 instance writer. Components placed via
  `add_schematic_component` / `batch_add_components` now carry the real
  project name (from the `.kicad_pro`), the real root-sheet uuid path instead
  of `(path "/")`, per-pin `(pin "N" (uuid ...))` entries (also fixes #241 —
  ERC can bind wires to pins), and the complete field set in canonical order.
  Verified structurally identical to eeschema's own output by round-tripping
  through `kicad-cli sch upgrade`. Previously the incomplete blocks made
  KiCad crash when a placed symbol was dragged or edited.

- **Schematic writes emit KiCad's canonical multi-line format, never a
  minified single line** (#256, second half): every schematic write tool
  serialized through `sexpdata.dumps()`, which emits the whole file as one
  line — producing unreviewable diffs, whole-file churn against eeschema
  saves, and in the worst reports unrecoverable projects. A faithful port of
  KiCad's `Prettify()` (`python/utils/sexpr_format.py`) now formats all tool
  writes byte-identically to eeschema's "Save"; every write re-parses its own
  output and falls back to the exact compact form on any mismatch, so the
  formatter can never corrupt data. `scripts/kicad_sch_reformat.py` repairs
  files minified by older versions.

- **Dragging/rotating a symbol now carries coincident net labels with the
  moved pins**: labels sitting exactly on a moved pin were left behind and
  could silently re-net onto a neighbouring signal (invisible until the
  netlist diverged). `drag_wires` gains a third pass that relocates
  `label`/`global_label`/`hierarchical_label` with the same tolerance used
  for wire endpoints; move/rotate responses report `labelsMoved`.

- **Pin positions and wire-stub angles are correct for rotated+mirrored
  symbols**: `pin_world_xy` applied mirror before rotation, and the outward
  pin angle was hand-derived in a way that was 180° wrong for horizontal
  pins. Both are fixed and locked in by a netlist oracle that validates the
  full rotation × mirror matrix against real eeschema output.

- **KiCad 10 sheet-rename compatibility**: the sheet-rename path only matched
  the KiCad 7–9 file format ("Sheetname" property, tab indentation), so it
  was a silent no-op on KiCad 10 schematics; the matcher now accepts both
  formats. NC template phantom pins are also cleaned up.

- **KiCad 10 `.kicad_symdir` sharded symbol libraries are discovered**
  (Windows/Linux/macOS): symbol search and schematic placement now resolve
  libraries stored in KiCad 10's directory-sharded format, not just
  monolithic `.kicad_sym` files.

- **`kicad-cli` is resolved robustly instead of failing when not on PATH**:
  KiCad's Windows installer does not add its `bin` to PATH, so every
  cli-backed tool (exports, ERC/DRC, netlist, board views) failed with a bare
  "kicad-cli not found in PATH". A centralized resolver
  (`python/utils/kicad_cli.py`) now tries `$KICAD_CLI` (fails loudly if set
  but invalid), the running interpreter's directory, PATH, and known per-OS
  install locations — and failures list every location tried. The three
  drifted `_find_kicad_cli` copies are unified onto it.

- **7-Zip is resolved the same way, and the yaqwsx JLCPCB download works on a
  stock install**: the split-archive volume count is auto-detected (the
  hardcoded cap of 30 silently truncated newer archives), and the 7z CLI is
  found via `$SEVEN_ZIP`/PATH/known install dirs instead of PATH-only.

- **File-answerable reads fall back to SWIG when the live KiCad has no
  document open**: `get_board_info`/`get_component_properties` routed to the
  realtime IPC backend even when the GUI had nothing loaded, returning
  misleading "not found" results or a false-success zeroed payload with an
  embedded error. Such reads are now re-served from the on-disk board and
  tagged `_backend: "swig"` with an explanatory note; genuine misses are
  distinguished from the no-document case.

- **SWIG pcbnew is imported even when IPC connects at startup**: an
  IPC-connected session that later downgraded to SWIG (GUI closed or busy)
  hit "name 'pcbnew' is not defined", surfaced as a bogus "dehydrated SWIG
  proxy" error. pcbnew is now imported whenever it isn't explicitly disabled,
  and a missing pcbnew is fatal only when there is no working IPC backend.

- **IPC connect attempts are bounded** (default 5s, `KICAD_IPC_CONNECT_TIMEOUT`):
  kipy dials with no timeout, so a busy KiCad GUI (modal dialog, library
  reload) could hang connects for minutes; they now fail fast and fall back
  to SWIG. The underlying IPC socket is also closed explicitly on disconnect,
  stopping a file-descriptor leak in long-lived reconnecting sessions.

- **`save_project` no longer silently clobbers external file edits** (#244):
  the explicit save wrote `pcbnew.SaveBoard` unconditionally, so a direct edit
  to the `.kicad_pcb` made after the MCP loaded the board (e.g. a manual
  net-name patch after a Freerouting import) was destroyed without warning —
  and the dispatcher then re-recorded the disk signature, blessing the
  clobber. The explicit path now applies the same content-hash divergence
  check the auto-save path already had: a diverged file refuses the save with
  `diskChangedExternally: true` and instructions (reload via `open_project`,
  or pass `force=true` to overwrite). Saving to a different `filename` is an
  explicit destination choice and is never blocked. `close_project`'s
  save-before-close routes through the same guard.

- **Legacy `ComponentManager.add_component` no longer silently loses
  components via dynamic template injection** (#221, part B): when no placed
  `_TEMPLATE_*` donor existed, the legacy clone path used to call
  `DynamicSymbolLoader.load_symbol_dynamically`, which wrote a template
  instance into the _file_ mid-call and cloned onto a locally reloaded
  object — so callers following the normal add-then-save pattern saved
  their stale in-memory schematic, discarding the new component and
  leaving `_TEMPLATE_*` clutter behind. That branch is removed: template
  lookup is now read-only (`find_template`), a schematic without donors
  gets a clear error pointing at the production `add_schematic_component`
  path (which works on any file), and the fixture-based clone path is
  unchanged. `add_component` is deprecated for general use; the
  remove/update/get/search helpers are unaffected.

- **Pin locations respect the owning unit of multi-unit symbols** (#239):
  `get_schematic_pin_locations` / `get_pin_location` located every pin against
  whichever placed `(symbol)` instance appeared first in file order, so for a
  multi-unit part (e.g. a dual op-amp placed as separate units at different
  positions) all pins collapsed onto that one unit's coordinates. Pins are now
  tagged with their owning unit while parsing `lib_symbols` (the
  `<name>_<unit>_<body>` sub-symbol), and each pin is located against the placed
  instance carrying the matching `(unit N)` — with rotation/mirror read from that
  same instance. Single-unit parts are unaffected (they fall back to the first
  instance as before).

- **Fallback schematic writer emits the KiCad 10 header** (#221, partial): the
  template-missing fallback in `create_schematic` and `create_project` wrote the
  stale KiCad 9 header `(version 20250114) (generator "KiCAD-MCP-Server")`. It
  now writes `(version 20260306) (generator "eeschema") (generator_version
"10.0")`, matching what eeschema writes for a new file. This covers only the
  fallback path; the main templates (which still carry the KiCad 9 version and
  the `_TEMPLATE_*` clone-source instances used by `add_schematic_component`)
  are tracked separately because rewriting them touches the component-cloning
  system.

- **`create_project` returns paths with a single separator** (#224): the
  returned `path`/`boardPath`/`schematicPath` were built with `os.path.join`,
  which on Windows mixed separators when the caller passed a forward-slash path
  (e.g. `C:/.../EspDinIoT\EspDinIoT.kicad_pro`). The reported paths are now
  normalized to forward slashes; the on-disk writes still use OS-native paths.

- **`create_schematic` accepts a full `.kicad_sch` path in `path`** (#242):
  passing a complete file path (e.g. `path="/foo/bar/V4.kicad_sch"`) previously
  treated it as a directory and appended the name again, producing
  `/foo/bar/V4.kicad_sch/V4.kicad_sch` and failing with "No such file or
  directory". The path is now used as-is when it already ends in `.kicad_sch`,
  in both `SchematicManager.create_schematic` and the `_handle_create_schematic`
  save step; passing a directory still works as before.

- **Backend is now pinned per loaded project (SWIG vs IPC)** (#223): commands
  on a single loaded project previously ran on whichever backend happened to
  be reachable per call — `create_project`/`open_project`/`add_layer` on SWIG
  while `save_project` silently upgraded to IPC, saving the live GUI's (stale)
  board and losing the SWIG-side edits. Now `open_project` pins the session to
  IPC only when the GUI provably has the same `.kicad_pcb` open; otherwise the
  whole lifecycle (including `save_project`) stays on SWIG, with a
  `_backend_note` on responses explaining why IPC wasn't used. IPC-pinned
  sessions fall back to SWIG (reloading from disk) if the GUI connection
  drops. `get_backend_state` gains `sessionBackend`/`sessionBoardPath`, and
  its `backend` field reflects the session pin while a project is loaded.

- **`rotate_component` now treats `angle` as an absolute target rotation**,
  matching its schema description. Previously the IPC backend added the
  supplied angle to the current rotation, so two consecutive
  `rotate_component(angle=90)` calls would rotate the part to 180° instead
  of leaving it at 90°. Workflows that relied on the additive behavior will
  need to be updated.

- **Project-scope `sym-lib-table` is now visible to symbol-discovery tools**:
  `search_symbols`, `list_symbol_libraries`, `list_library_symbols`, and
  `get_symbol_info` previously only consulted the global `sym-lib-table`. A
  library registered with project scope (i.e. an entry in
  `<project>/sym-lib-table`) was therefore invisible — even right after
  `open_project` succeeded — making `add_schematic_component` the only tool
  that could see it. Two changes:
  1. `open_project` and `create_project` now rebuild the
     `SymbolLibraryManager` against the project directory so subsequent
     search/list/info calls see project-scope libraries automatically.
  2. The four discovery tools also accept an optional `projectPath`
     parameter (a project directory, `.kicad_pro`, `.kicad_pcb`, or
     `.kicad_sch` path) for stateless callers, so project libraries can be
     resolved without first calling `open_project`.

- **IPC backend runtime reconnect**: MCP no longer stays on SWIG for the
  entire process when it starts before KiCAD. IPC-capable board tools now retry
  the IPC connection when KiCAD is running, refresh the live board API when a
  board becomes available, and report `_backend: "ipc"` when they actually use
  the IPC path. `check_kicad_ui`, `launch_kicad_ui`, and `get_backend_info`
  now include live backend status instead of only reflecting startup state.

- **Windows KiCAD Python discovery**: Windows startup now scans per-user KiCAD
  installs under `%LOCALAPPDATA%\Programs\KiCad` in addition to machine-wide
  installs under `C:\Program Files\KiCad` and `C:\Program Files (x86)\KiCad`,
  so user-scope installs no longer require a manual `KICAD_PYTHON` override.

- **IPC board size on KiCAD 10**: `get_board_info` now handles KiCAD 10 IPC
  `Box2` objects that expose `pos` / `size` instead of `min` / `max`, avoiding
  a zero-size board result with an attribute error.

- **Schematic symbol lookup**: `get_schematic_component`,
  `edit_schematic_component`, `set_schematic_component_property`,
  `remove_schematic_component_property`, and `delete_schematic_component`
  no longer fail with `Component '<ref>' not found in schematic` when the
  placed symbol uses KiCad's rescued / locally-customised serialisation
  form `(symbol (lib_name "...") (lib_id "...") ...)`. The block-matching
  regex now accepts any opening paren after `(symbol`, and the
  parent-position lookup uses the first `(at ...)` inside the symbol
  block, so newly-added properties anchor to the symbol origin instead of
  silently falling back to `(0, 0)`. Added 7 regression tests reproducing
  the failure on a real-world user schematic.

### New MCP Tools

- `suggest_placement` — Connectivity-driven footprint placement optimizer for
  the PCB: clusters components by netlist affinity, legalizes overlaps, and
  proposes (or with `apply: true`, applies) positions/rotations that shorten
  the ratsnest. Dry-run by default — it never mutates the board unless asked;
  deterministic, so the preview matches the applied result. Reports
  half-perimeter wirelength before/after.

- `suggest_schematic_declutter` — Re-orients overlapping net/global labels in
  a schematic for readability, holding every label anchor fixed so
  connectivity cannot change. Dry-run by default, like `suggest_placement`.

- `close_project` (#225) — Symmetric counterpart to `open_project` /
  `create_project`. Optionally saves the board (`save`, default `true`), then
  drops the in-memory board (SWIG + IPC) and clears all per-project session
  state (session-backend pin, disk signature, project paths). Lets an agent
  hand control back so the user — or the agent itself — can edit project files
  directly without a later MCP save clobbering those changes, which previously
  required manual open/close choreography. If `save=true` and the save fails,
  the close is refused so work is never silently lost; if `save=false` on a
  board with unsaved changes, the close proceeds with a warning.

- `add_gnd_stitching_vias` — Drop GND stitching vias across the board with
  collision checking against every non-GND segment, via, and pad on every
  copper layer. PTH vias penetrate the full stackup, so an F.Cu-only check
  (the most common shortcut) silently creates shorts on inner / B.Cu
  copper — this implementation explicitly walks all layers.

  Combines three placement strategies, freely composable:
  - `grid` — regular grid across the board interior.
  - `around_refs` — densify around named footprints (good for tucking
    extra ground under MCUs, switching regulators, or RF parts).
  - `in_zones` — restrict candidates to points inside the filled
    polygons of GND copper zones, so each new via actually stitches
    real ground polygons together rather than floating on silkscreen.

  Also supports per-via geometry control (`viaSize`, `viaDrill`,
  `clearance`, `edgeMargin`), an `maxVias` cap for incremental work,
  auto-detection of the GND net (tries `GND` / `GROUND` / `VSS` /
  `/GND`), and a `dryRun` mode that returns the placements that
  _would_ be made without modifying the board — useful for previewing
  before committing.

  Returns `{ placed: [{x, y, unit}, ...], summary: {placed_count,
candidates_evaluated, skipped_by_zone_membership,
skipped_by_collision, ...} }`.

  Approach ported from
  [morningfire-pcb-automation](https://github.com/NiNjA-CodE/morningfire-pcb-automation)
  (`scripts/ground/add_gnd_vias.py`). The original parses the PCB
  text with regex and writes new vias by string concatenation; this
  port reads obstacles via the pcbnew API so it handles rotated
  footprints correctly, integrates with the in-memory board (two
  sequential calls see each other's placements), picks up net codes
  from the live board, and adds the `in_zones` strategy + the
  `maxVias` cap + dry-run.

- `check_courtyard_overlaps` — Detect courtyard overlaps between footprints
  and (optionally) flag courtyards that extend past the board outline.
  Returns overlap pairs with intersection extents (mm), per-component
  boundary violations, and a placement summary. Accepts a `positions` dict
  of hypothetical placements (with optional rotation) so an AI agent can
  validate a proposed `move_component` / `place_component` before
  committing it — closing the feedback loop that previously required
  writing the move, running DRC, parsing violations, and reverting.

  Approach ported from
  [morningfire-pcb-automation](https://github.com/NiNjA-CodE/morningfire-pcb-automation)
  (`scripts/placement/check_overlaps.py`). The original uses a static
  per-footprint-type courtyard lookup table; this implementation reads
  the real courtyard polygons (or pad bounding box fallback) from the
  loaded board for accuracy on custom and rotated footprints, and adds
  virtual placement + clearance margin support.

- `query_zones` — Query copper zones (filled pours) on the board with optional
  filters by net, layer, or bounding box. Returns one entry per zone with its
  net, layers, priority, fill state, min thickness, bounding box, and filled
  area. Complements `query_traces`, which only reports tracks/vias and silently
  omits power-plane and GND pours — making layer-usage audits incomplete on any
  board that uses copper zones.

- `set_schematic_component_property` — Add or update a single custom property
  (BOM / sourcing field) on a placed schematic symbol. Convenience wrapper
  around `edit_schematic_component` for the common case of attaching one MPN /
  Manufacturer / DigiKey_PN / LCSC / JLCPCB_PN / Voltage / Tolerance /
  Dielectric value at a time. Newly created properties default to hidden so
  they do not clutter the schematic canvas.

- `remove_schematic_component_property` — Delete a custom property from a
  placed schematic symbol. The four built-in fields (Reference, Value,
  Footprint, Datasheet) are protected and cannot be removed; clear them by
  setting their value to `""` via `edit_schematic_component` instead.

### Tool Enhancements

- `autoroute`: best-of-N support. New optional parameters `attempts`,
  `targetNets`, and `passSchedule`. When `attempts > 1`, Freerouting is
  invoked multiple times with varied `--max-passes` values, each result
  is scored by `(nets_routed * 1000) + segments` plus a 50,000-point
  bonus when every `targetNets` entry is routed, and the winning SES is
  imported into the board. Single-attempt behaviour is unchanged when
  `attempts` is omitted, so existing callers don't need updates.

  Motivation: on dense boards a single Freerouting run routinely leaves
  1–7 nets unrouted. Cycling through a few `-mp` values typically drives
  the unrouted count to zero. Empirically, 3 attempts is usually enough
  for 4-layer designs; 5–8 for stubborn cases.

  The scoring approach and the default `passSchedule` are ported from
  [morningfire-pcb-automation](https://github.com/NiNjA-CodE/morningfire-pcb-automation)
  (`scripts/routing/freeroute_runner.py`). The MCP version adds:
  cleaner per-attempt result reporting, automatic single-thread
  optimisation (`-mt 1`) during scored attempts so the multi-threaded
  optimiser's known clearance-violation bug doesn't distort the
  comparison, and graceful degradation when one attempt errors out
  (the run continues and the best of the remainder wins).

- `edit_schematic_component`: extended with two new optional parameters that
  promote arbitrary custom properties to first-class citizens:
  - **`properties`** — map of property name to either a string value or a full
    spec object `{ value, x?, y?, angle?, hide?, fontSize? }`. Adds the
    property if it does not yet exist on the symbol, otherwise updates the
    existing value (and optionally its label position / visibility). Lets a
    single tool call attach an entire BOM / sourcing payload to a component:
    `properties: { MPN: "RC0603FR-0710KL", Manufacturer: "Yageo", Tolerance: "1%" }`.
  - **`removeProperties`** — list of custom property names to delete in the
    same call.
  - String values written through any of the property paths are now properly
    backslash-escaped so descriptions containing `"` or `\` no longer
    corrupt the .kicad_sch file.

- `get_schematic_component`: clarified description — it already returns every
  field on the symbol (built-in + custom). The tool description now spells
  this out explicitly so agents know they can use it to inspect MPN,
  Manufacturer, Distributor PN and other BOM fields without a separate call.

- `query_traces`: added to the IPC-capable board command path so trace reads
  can use live KiCAD board data when IPC is connected.

### New MCP Prompt

- `component_sourcing_properties` — Guides the LLM through attaching BOM and
  sourcing metadata (MPN, Manufacturer, distributor part numbers, parametric
  fields like Voltage / Tolerance / Dielectric) to schematic components. Lists
  the conventional property names recognised by downstream BOM tooling and the
  recommended call sequence (`list_schematic_components` →
  `get_schematic_component` → `set_schematic_component_property` /
  `edit_schematic_component`).

### Tests

- `tests/test_schematic_component_properties.py`: 32 new tests covering custom
  property add / update / remove (single + batched), full spec dicts, position
  defaults, `(hide yes)` defaulting, protected built-in field rejection,
  no-op removal, special-character escaping, UUID preservation, and the two
  new convenience tools.

- `tests/test_backend_metadata.py`: regression coverage for backend metadata,
  runtime IPC reconnect after KiCAD starts, IPC-backed `query_traces`, and
  KiCAD 10 IPC `Box2` board-size compatibility.

### Removed

- `add_schematic_junction` MCP tool has been removed. Junctions are now
  inserted and removed automatically via `WireManager.sync_junctions` whenever
  wires are added, deleted, or moved.
- Junction placement is pin-aware: `sync_junctions` consults component pin
  positions so that T-junctions at component pins are correctly recognised.

---

## [2.2.3] - 2026-03-11

### Merged: PR #57 (Kletternaut/demo/rpiCSI-videotest → main)

This release incorporates 28 commits developed and live-tested during a full
Raspberry Pi CSI adapter PCB design session. All tools listed below were validated
end-to-end using Claude Desktop + KiCAD 9 on Windows.

### New MCP Tools

- `connect_passthrough` — Schematic-only tool that wires all pins of one connector
  directly to the matching pins of another (e.g. J1 pin N → J2 pin N). Creates nets
  named with a configurable prefix (`netPrefix`). Designed for FFC/ribbon cable
  passthrough adapters. **Schematic only — do not call for PCB routing.**

- `sync_schematic_to_board` — Imports all net/pad assignments from the schematic
  into the open PCB file. Required after `connect_passthrough` before routing can
  start. Returns `pads_assigned` count for verification.

- `snapshot_project` — Saves a named checkpoint of the entire project folder into a
  `snapshots/` subdirectory inside the project. Allows resuming from a known-good
  state without redoing earlier steps. Accepts `step`, `label`, and optional `prompt`
  parameters.

- `run_erc` — Runs KiCAD's Electrical Rules Check on the schematic and returns
  violations as structured JSON.

- `import_svg_logo` — Converts an SVG file to PCB silkscreen polygons and places
  them on a specified layer.

### Bug Fixes

- `route_pad_to_pad`: **Critical fix for B.Cu footprints in KiCAD 9.** `pad.GetLayerName()`
  always returned `F.Cu` for SMD pads on flipped footprints (KiCAD 9 SWIG bug).
  Fix: use `footprint.GetLayer()` instead, which correctly reflects the placed layer
  after `Flip()`. Without this fix, no vias were inserted for back-to-back connectors.

- `route_pad_to_pad`: Via was placed at the geometric midpoint between the two pads.
  For back-to-back mirrored connectors (J1 F.Cu / J2 B.Cu) this caused all 15 vias
  to stack at the same X coordinate (board center). Fix: via is now placed at the
  X coordinate of the start pad (`via_x = start_pos.x`), producing 15 parallel
  vertical traces.

- `place_component` (B.Cu footprints): `Flip()` was called before `board.Add()`,
  causing KiCAD 9 to hang for ~30 seconds. Fix: `board.Add()` first, then `Flip()`.

- `add_board_outline`: Three separate bugs fixed — incorrect cornerRadius fallback,
  wrong top-left origin default, and broken arc delegation for IPC rounded rectangles.

- `snapshot_project`: Snapshots were saved one level above the project directory,
  cluttering the parent folder. Fix: snapshots now go into `<project>/snapshots/`.

- MCP server log timestamp was always UTC/ISO. Fix: now uses local system time.

- `search_tools` (router pattern): direct tools like `snapshot_project` were invisible
  to the router. Fix: direct tool names added to the router's known-tool list.

### Developer Mode (`KICAD_MCP_DEV=1`)

Set the environment variable `KICAD_MCP_DEV=1` in your Claude Desktop config to
enable developer features:

```json
"env": {
  "KICAD_MCP_DEV": "1"
}
```

**What it does:**

- `export_gerber` automatically copies the current MCP session log into the project's
  `logs/` subdirectory as `mcp_log_<timestamp>.txt`.
- `snapshot_project` copies the MCP session log into `logs/` at every checkpoint as
  `mcp_log_step<N>_<timestamp>.txt`.
- If a `prompt` parameter is passed to `snapshot_project`, it is saved as
  `PROMPT_step<N>_<timestamp>.md` alongside the log.

**Purpose:** Makes it easy to include the full tool call history when filing a bug
report or GitHub issue — just attach the log file from the project's `logs/` folder.

> ⚠️ **Privacy warning:** The MCP session log contains the **complete conversation
> history** between Claude and the MCP server, including all tool parameters and
> responses. When sharing a project directory (e.g. as a ZIP attachment in a GitHub
> issue), **review or delete the `logs/` folder first** to avoid accidentally
> disclosing sensitive file paths, component names, or design details.

### Snapshot Logging (always active)

Regardless of dev mode, `snapshot_project` now always saves a copy of the current
MCP session log into `<project>/logs/` at each checkpoint. This means every project
automatically retains a traceable record of which tools were called and in what order.

> ⚠️ **Same privacy note applies:** the `logs/` directory inside your project folder
> contains tool call history. Do not share it publicly without reviewing its contents.

---

## [2.2.2-alpha] - 2026-03-01

### New MCP Tools

- `route_pad_to_pad` – Convenience wrapper around `route_trace` that looks up pad positions
  automatically. Accepts `fromRef`/`fromPad`/`toRef`/`toPad` instead of raw XY coordinates.
  Auto-detects net from pad assignment (overridable via `net` param). Saves ~2 tool calls per
  connection (~64 calls for a full TMC2209 board compared to the 3-step get_pad_position flow).
  Live tested: ESP32 ↔ TMC2209 STEP/DIR traces routed without prior coordinate lookup. ✅

- `copy_routing_pattern` – Now registered as MCP tool in TypeScript layer (`routing.ts`).
  Was previously implemented in Python but missing from the MCP tool registry.
  Parameters: `sourceRefs`, `targetRefs`, `includeVias?`, `traceWidth?`.

### Bug Fixes

- `add_schematic_component` / `DynamicSymbolLoader`: ignored project-local `sym-lib-table`.
  `find_library_file()` only searched global KiCAD install directories, causing "library not
  found" errors for any symbol in a project-local `.kicad_sym` file. Fix: added `project_path`
  parameter; reads project `sym-lib-table` first via new `_resolve_library_from_table()` helper
  before falling back to global dirs. `project_path` is auto-derived from the schematic path.

- `place_component`: ignored project-local `fp-lib-table`. `FootprintLibraryManager` was
  initialised once at server start without a project path, so self-created `.kicad_mod`
  footprints were never found. Fix: new `boardPath` parameter in TypeScript + Python;
  `_handle_place_component` wrapper recreates `FootprintLibraryManager(project_path=…)` whenever
  the active project changes (cached to avoid redundant recreation).

- `copy_routing_pattern`: copied 0 traces when pads had no net assignments. The filter
  `track.GetNetname() in source_nets` always returned empty when pads were placed without net
  assignment. Fix: geometric fallback using bounding box of source footprint pads ±5mm
  tolerance. Response includes `filterMethod` field indicating which mode was used
  (`"net-based"` or `"geometric (pads have no nets)"`).

- `template_with_symbols.kicad_sch`, `template_with_symbols_expanded.kicad_sch`: restored
  format version `20250114` (KiCAD 9) after upstream commit `2b38796` accidentally downgraded
  both files to `20240101`. KiCAD 9 rejects schematics with outdated version numbers.

- **CRITICAL: `template_with_symbols_expanded.kicad_sch`**: removed 7 invalid `;;` comment
  lines introduced by upstream commit `b98c94b`. KiCAD's S-expression parser does not support
  any comment syntax — it expects every non-empty, non-whitespace line to start with `(`.
  The comments (`;; PASSIVES`, `;; SEMICONDUCTORS`, `;; INTEGRATED CIRCUITS`, `;; CONNECTORS`,
  `;; POWER/REGULATORS`, `;; MISC`, `;; TEMPLATE INSTANCES (...)`) caused KiCAD 9 to reject
  every schematic created from this template with a hard parse error:

  > `Expecting '(' in <file>.kicad_sch, line 8, offset 5`
  > **Action required for existing projects:** delete every line beginning with `;;` from any
  > `.kicad_sch` file created between upstream commit `b98c94b` and this fix.

- `add_schematic_component` / `inject_symbol_into_schematic`: symbol definition in
  `lib_symbols` was never refreshed after editing via `create_symbol` / `edit_symbol`.
  If the symbol was already present in the schematic's embedded `lib_symbols` section,
  the function returned immediately — `delete + re-add` still pulled in the stale cached
  definition. Fix: always read the current definition from the `.kicad_sym` file; if a
  stale entry exists in `lib_symbols`, remove it first, then inject the fresh one.
  Verified live. ✅

- `template_with_symbols_expanded.kicad_sch`: removed 13 legacy `_TEMPLATE_*` offscreen
  instances (`_TEMPLATE_R`, `_TEMPLATE_C`, `_TEMPLATE_U`, etc.) that were placed at
  `x=-100` as clone-sources for the old `ComponentManager` approach. `DynamicSymbolLoader`
  (the current implementation) injects symbols directly and never needs these placeholders.
  They appeared as dangling reference designators in KiCAD's component navigator and in
  the schematic canvas when zoomed far out.

### Maintenance

- `.gitignore`: added `*.kicad_pcb.bak`, `*.kicad_pro.bak` alongside existing `-bak` variants;
  consolidated personal/local files under `myContribution/`.

---

## [2.2.1-alpha] - 2026-02-28

### New MCP Tools

- `edit_schematic_component` – Update properties of a placed symbol in-place (footprint,
  value, reference rename). More efficient than delete + re-add: preserves position and UUID.

### Bug Fixes

- `add_schematic_component`: `footprint` parameter was accepted but silently ignored – the
  value was never passed through to `DynamicSymbolLoader.add_component()` /
  `create_component_instance()`. All newly placed symbols always had an empty Footprint
  field. Fix: added `footprint: str = ""` to both functions and threaded it through every
  call site including the TypeScript tool schema.

- `delete_schematic_component`: only deleted the first matching instance when duplicate
  references existed (e.g. after an aborted add attempt). Root cause: loop used `break`
  after the first match. Fix: collect all matching blocks first, then delete them all back-
  to-front (to preserve line indices). Response now includes `deleted_count`.

- `templates/*.kicad_sch`, `project.py`, `schematic.py`: Update KiCAD schematic format
  version from `20230121` (KiCAD 7) to `20250114` (KiCAD 9). The MCP server targets
  KiCAD 9 exclusively (`pcbnew.pyd` compiled for KiCAD 9.0, Python 3.11.5) – generating
  files in an outdated format caused a spurious "This file was created with an older
  KiCAD version" warning on every newly created schematic.

- `template_with_symbols_expanded.kicad_sch`: Remove 13 corrupt `_TEMPLATE_*` placed-symbol
  blocks with `(lib_id -100)` – an integer caused by old sexpdata serializer (same bug
  PR #40 fixed for the add path). KiCAD crashed with a null-pointer when selecting these
  symbols. They appeared as grey `_TEMPLATE_R?`, `_TEMPLATE_U_REG?` etc. labels far
  outside the sheet boundary (~5000mm off-sheet).

  **Discovered via:** live testing on a real JLCPCB/KiCAD 9 project.
  **Affected users:** schematics created from this template before this fix contain the
  same corrupt blocks – remove all `(symbol (lib_id -100) ...)` blocks whose Reference
  starts with `_TEMPLATE_`.

---

---

## [2.2.0-alpha] - 2026-02-27

### New MCP Tools (TypeScript layer – previously Python-only)

**Routing tools:**

- `delete_trace` - Delete traces by UUID, position or net name
- `query_traces` - Query/filter traces on the board
- `get_nets_list` - List all nets with net code and class
- `modify_trace` - Modify trace width or layer
- `create_netclass` - Create or update a net class
- `route_differential_pair` - Route a differential pair between two points
- `refill_zones` - Refill all copper zones ⚠️ SWIG segfault risk, prefer IPC/UI

**Component tools:**

- `get_component_pads` - Get all pad data for a component
- `get_component_list` - List all components on the board
- `get_pad_position` - Get absolute position of a specific pad
- `place_component_array` - Place components in a grid array
- `align_components` - Align components along an axis
- `duplicate_component` - Duplicate a component with offset

### Bug Fixes

- `routing.py`: Fix SwigPyObject UUID comparison (`str()` → `m_Uuid.AsString()`)
- `routing.py`: Fix SWIG iterator invalidation after `board.Remove()` by snapshotting `list(board.Tracks())`
- `routing.py`: Add `board.SetModified()` + `track = None` after `Remove()` to prevent dangling SWIG pointer crashes
- `routing.py`: Per-track `try/except` in `query_traces()` to skip invalid objects after bulk delete
- `routing.py`: Add missing return statement (mypy)
- `library.py`: Fix `search_footprints` parameter mapping (`search_term` → `pattern`)
- `library.py`: Fix field access (`fp.name` → `fp.full_name`)
- `library.py`: Accept both `pattern` and `search_term` parameter names
- `library.py`: Fix loop variable shadowing `Path` object (mypy)
- `design_rules.py`: Add type annotation for `violation_counts` (mypy)

### New MCP Tools (cont.)

**Datasheet tools:**

- `get_datasheet_url` - Return LCSC datasheet PDF URL and product page URL for a given
  LCSC number (e.g. `C179739` → `https://www.lcsc.com/datasheet/C179739.pdf`).
  No API key required – URL is constructed directly from the LCSC number.
- `enrich_datasheets` - Scan a `.kicad_sch` file and write LCSC datasheet URLs into
  every symbol that has an `LCSC` property but an empty `Datasheet` field. After
  enrichment the URL appears natively in KiCAD's symbol properties, footprint browser
  and any other tool that reads the standard KiCAD `Datasheet` field.
  Supports `dry_run=true` for preview without writing.
  Implementation: `python/commands/datasheet_manager.py` (text-based, no `skip` writes)

**Schematic tools:**

- `delete_schematic_component` - Remove a placed symbol from a `.kicad_sch` file by
  reference designator (e.g. `R1`, `U3`).

### Bug Fixes (cont.)

- `schematic.ts` / `kicad_interface.py`: Fix missing `delete_schematic_component` MCP tool.

  **Root cause (two separate issues):**
  1. No MCP tool named `delete_schematic_component` existed. Claude had no way to call
     it, so any "delete schematic component" request fell through to the PCB-only
     `delete_component` tool, which searches `pcbnew.BOARD` and always returned
     "Component not found" for schematic symbols.
  2. `component_schematic.py::remove_component()` still used `skip` for writes.
     PR #40 rewrote `DynamicSymbolLoader` (add path) to avoid `skip`-induced schematic
     corruption, but `remove_component` (delete path) was not touched by that PR.

  **Fix:**
  - Added `delete_schematic_component` to the TypeScript tool layer (`schematic.ts`)
    with clear docstring distinguishing it from the PCB `delete_component`.
  - Implemented `_handle_delete_schematic_component` in `kicad_interface.py` using
    direct text manipulation (parenthesis-depth tracking, same approach as PR #40).
    Does not call `component_schematic.py::remove_component()` at all.
  - Error message explicitly guides the user when the wrong tool is used:
    _"note: this tool removes schematic symbols, use delete_component for PCB footprints"_

### Additional Bug Fixes

- `connection_schematic.py` / `kicad_interface.py`: Fix `generate_netlist` missing
  `schematic_path` parameter – without it `get_net_connections` always fell back to
  proximity matching which only returns one connection per component (first wire hit,
  then `break`). PinLocator was never invoked. Fix: added `schematic_path: Optional[Path]`
  to `generate_netlist` signature and threaded it through to `get_net_connections`,
  and updated `_handle_generate_netlist` in `kicad_interface.py` to pass `schematic_path`.
- `server.ts`: Fix KiCAD bundled Python (3.11.5) not being selected on Windows – the
  detection condition `process.env.PYTHONPATH?.includes("KiCad")` was fragile and failed
  in some environments, causing System Python 3.12 to be used instead. Since `pcbnew.pyd`
  is compiled for KiCAD's Python 3.11.5, this resulted in `No module named 'pcbnew'`.
  Fix: removed the condition, KiCAD bundled Python is now always preferred on Windows
  when it exists at `C:\Program Files\KiCad\9.0\bin\python.exe`.
  Also added `KICAD_PYTHON` to `claude_desktop_config.json` as explicit override.
- `pin_locator.py`: Fix `generate_netlist` timeout – `get_pin_location` and
  `get_all_symbol_pins` called `Schematic(schematic_path)` on every single pin lookup,
  causing O(nets × components × pins) schematic file loads (e.g. 400+ loads for a
  medium schematic). Fix: added `_schematic_cache` dict to `PinLocator.__init__`,
  schematic is now loaded once per path and reused.

---

## [2.1.0-alpha] - 2026-01-10

### Phase 1: Intelligent Schematic Wiring System - Core Infrastructure

**Major Features:**

- Automatic pin location discovery with rotation support
- Smart wire routing (direct, orthogonal horizontal/vertical)
- Net label management (local, global, hierarchical)
- S-expression-based wire creation
- Professional right-angle routing

**New Components:**

- `python/commands/wire_manager.py` - S-expression wire creation engine
- `python/commands/pin_locator.py` - Intelligent pin discovery with rotation
- Updated `python/commands/connection_schematic.py` - High-level connection API
- `docs/SCHEMATIC_WIRING_PLAN.md` - Implementation roadmap

**MCP Tools Enhanced:**

- `add_schematic_wire` - Create wires with stroke customization
- `add_schematic_connection` - Auto-connect pins with routing options (NEW)
- `add_schematic_net_label` - Add labels with type and orientation control (NEW)
- `connect_to_net` - Connect pins to named nets (ENHANCED)

**Technical Implementation:**

- Rotation transformation matrix for pin coordinates
- S-expression injection for guaranteed format compliance
- Pin definition caching for performance
- Orthogonal path generation for professional schematics

**Testing:**

- End-to-end integration test: 100% passing
- MCP handler integration test: 100% passing
- Pin discovery with rotation: Verified working
- KiCad-skip verification: All wires/labels correctly formed

---

### Phase 2: Power Nets & Wire Connectivity - COMPLETE

**Major Features:**

- Power symbol support (VCC, GND, +3V3, +5V, etc.) via dynamic loading
- Wire graph analysis for net connectivity tracking
- Geometric wire tracing with tolerance-based point matching
- Accurate netlist generation with component/pin connections
- Critical template mapping bug fixes

**Updates:**

- `connect_to_net()` - Migrated to WireManager + PinLocator
- `get_net_connections()` - Complete rewrite with geometric wire tracing
- `generate_netlist()` - Now uses wire graph analysis for connectivity
- `get_or_create_template()` - Fixed special character handling, auto-reload after dynamic loading
- `add_component()` - Fixed template lookup with symbol iteration

**Bug Fixes:**

- CRITICAL: Template mapping after dynamic symbol loading
- Special character handling in symbol names (+ prefix in +3V3, +5V)
- Schematic reload synchronization after S-expression injection
- Multi-format template reference detection

**Wire Graph Analysis Algorithm:**

1. Find all labels matching target net name
2. Trace wires connected to label positions (point coincidence)
3. Collect all wire endpoints and polyline segments
4. Match component pins at wire connection points using PinLocator
5. Return accurate component/pin connection pairs

**Technical Implementation:**

- Tolerance-based point matching (0.5mm for grid alignment)
- Multi-segment wire (polyline) support
- Rotation-aware pin location matching via PinLocator
- Fallback proximity detection (10mm threshold)
- Template existence checking via symbol iteration (handles special characters)

**Testing:**

- Power symbols: 4/4 loaded (VCC, GND, +3V3, +5V)
- Components: 4/4 placed
- Connections: 8/8 created successfully
- Net connectivity: 100% accurate (VCC: 2, GND: 4, +3V3: 1, +5V: 1)
- Netlist generation: 4 nets with accurate connections
- Comprehensive integration test: 100% PASSING

**Commits:**

- `c67f400` - Updated connect_to_net to use WireManager
- `b77f008` - Fixed template mapping bug (critical)
- `a5a542b` - Implemented wire graph analysis

**Addresses:**

- Issue #26 - Schematic workflow wiring functionality (Phase 2)

---

### Phase 2: JLCPCB Integration Complete

**Major Features:**

- ✅ Complete JLCPCB parts integration via JLCSearch public API
- ✅ Access to ~100k JLCPCB parts catalog
- ✅ Real-time stock and pricing data
- ✅ Parametric component search
- ✅ Cost optimization (Basic vs Extended library)
- ✅ KiCad footprint mapping
- ✅ Alternative part suggestions

**New Components:**

- `python/commands/jlcsearch.py` - JLCSearch API client (no auth required)
- `python/commands/jlcpcb_parts.py` - Enhanced with `import_jlcsearch_parts()`
- `docs/JLCPCB_INTEGRATION.md` - Comprehensive integration guide

**MCP Tools Available:**

- `download_jlcpcb_database` - Download full parts catalog
- `search_jlcpcb_parts` - Parametric search with filters
- `get_jlcpcb_part` - Part details + footprint suggestions
- `get_jlcpcb_database_stats` - Database statistics
- `suggest_jlcpcb_alternatives` - Find similar/cheaper parts

**Technical Improvements:**

- SQLite database with full-text search (FTS5)
- Package-to-footprint mapping for standard SMD packages
- Price comparison and cost optimization algorithms
- HMAC-SHA256 authentication support (for official JLCPCB API)

**Testing:**

- All integration tests passing
- Database operations validated
- Live API connectivity confirmed
- End-to-end MCP tool testing complete

**Documentation:**

- Complete API reference with examples
- Package mapping tables (0402, 0603, 0805, SOT-23, etc.)
- Best practices guide
- Troubleshooting section

---

## [2.1.0-alpha] - 2025-11-30

### Phase 1: Schematic Workflow Fix

**Critical Bug Fix:**

- ✅ Fixed completely broken schematic workflow (Issue #26)
- Created template-based symbol cloning approach
- All schematic tests now passing

**Root Cause:**

- kicad-skip library limitation: cannot create symbols from scratch, only clone existing ones

**Solution:**

- Template schematic with cloneable R, C, LED symbols
- Updated `create_project` to create both PCB and schematic
- Rewrote `add_schematic_component` to use `clone()` API
- Proper UUID generation and position setting

**Files Modified:**

- `python/commands/project.py` - Now creates schematic files
- `python/commands/schematic.py` - Uses template approach
- `python/commands/component_schematic.py` - Complete rewrite

**Files Created:**

- `python/templates/template_with_symbols.kicad_sch`
- `python/templates/empty.kicad_sch`
- `docs/SCHEMATIC_WORKFLOW_FIX.md`

**Testing:**

- Created comprehensive test suite
- All 7 tests passing
- KiCad CLI validation successful

---

## [2.0.0-alpha] - 2025-11-05

### Router Pattern & Tool Organization

**Major Architecture Change:**

- Implemented tool router pattern (70% context reduction)
- 12 direct tools, 47 routed tools in 7 categories
- Smart tool discovery system

**New Router Tools:**

- `list_tool_categories` - Browse available categories
- `get_category_tools` - View tools in category
- `search_tools` - Find tools by keyword
- `execute_tool` - Run any routed tool

**Benefits:**

- Dramatically reduced AI context usage
- Maintained full functionality (64 tools)
- Improved tool discoverability
- Better organization for users

---

## [2.0.0-alpha] - 2025-11-01

### IPC Backend Integration

**Experimental Feature:**

- KiCad 9.0 IPC API integration for real-time UI sync
- Changes appear immediately in KiCad (no manual reload)
- Hybrid backend: IPC + SWIG fallback
- 20+ commands with IPC support

**Implementation:**

- Routing operations (interactive push-and-shove)
- Component placement and modification
- Zone operations and fills
- DRC and verification

**Status:**

- Under active development
- Enable via KiCad: Preferences > Plugins > Enable IPC API Server
- Automatic fallback to SWIG when IPC unavailable

---

## [2.0.0-alpha] - 2025-10-26

### Initial JLCPCB Integration (Local Libraries)

**Features:**

- Local JLCPCB symbol library search
- Integration with KiCad Plugin and Content Manager
- Search by LCSC part number, manufacturer, description

**Credit:**

- Contributed by [@l3wi](https://github.com/l3wi)

**Components:**

- `python/commands/symbol_library.py`
- Basic library search functionality

---

## [1.0.0] - 2025-10-01

### Initial Release

**Core Features:**

- 64 fully-documented MCP tools
- JSON Schema validation for all tools
- 8 dynamic resources for project state
- Cross-platform support (Linux, Windows, macOS)
- Comprehensive error handling
- Detailed logging

**Tool Categories:**

- Project Management (4 tools)
- Board Operations (9 tools)
- Component Management (8 tools)
- Routing (6 tools)
- Export & Manufacturing (5 tools)
- Design Rule Checking (4 tools)
- Schematic Operations (6 tools)
- Symbol Library (3 tools)
- JLCPCB Integration (5 tools)

**Platform Support:**

- Linux (KiCad 7.x, 8.x, 9.x)
- Windows (KiCad 9.x)
- macOS (KiCad 9.x)

**Documentation:**

- Complete README with setup instructions
- Platform-specific guides
- Tool reference documentation
- Contributing guidelines

---

## Version Numbering

- **2.1.0-alpha**: Current development version with JLCPCB integration
- **2.0.0-alpha**: Router pattern and IPC backend
- **1.0.0**: Initial stable release

## Breaking Changes

### 2.1.0-alpha

- None (additive changes only)

### 2.0.0-alpha

- Tool execution now requires router for 47 tools
- Direct tool access limited to 12 high-frequency tools
- Schema validation stricter (catches errors earlier)

## Deprecations

### 2.1.0-alpha

- `docs/JLCPCB_USAGE_GUIDE.md` - Superseded by `docs/JLCPCB_INTEGRATION.md`
- `docs/JLCPCB_INTEGRATION_PLAN.md` - Implementation complete

## Migration Guide

### Upgrading to 2.1.0-alpha from 2.0.0-alpha

**New Dependencies:**

- No new system dependencies
- Python packages: `requests` (already in requirements.txt)

**Database Setup:**

1. Run `download_jlcpcb_database` tool (one-time, ~5-10 minutes)
2. Database created at `data/jlcpcb_parts.db`
3. Subsequent searches use local database (instant)

**API Changes:**

- All existing tools remain compatible
- 5 new JLCPCB tools available
- No breaking changes to existing functionality

### Upgrading to 2.0.0-alpha from 1.0.0

**Router Pattern:**

- Some tools now accessed via `execute_tool` instead of direct calls
- Use `list_tool_categories` to discover available tools
- Search with `search_tools` to find specific functionality

**IPC Backend (Optional):**

- Enable in KiCad: Preferences > Plugins > Enable IPC API Server
- Set `KICAD_BACKEND=ipc` environment variable
- Falls back to SWIG if unavailable

---

## Credits

- **JLCSearch API**: [@tscircuit](https://github.com/tscircuit/jlcsearch)
- **JLCParts Database**: [@yaqwsx](https://github.com/yaqwsx/jlcparts)
- **Local JLCPCB Search**: [@l3wi](https://github.com/l3wi)
- **KiCad**: KiCad Development Team
- **MCP Protocol**: Anthropic

## License

See LICENSE file for details.
