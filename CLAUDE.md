# KiCAD MCP Server

## Related Source

- KiCad source code is located at `../kicad-source/` (absolute: `/home/eugene/Projects/kicad-source/`)

## Testing

### When to Write Tests

Write tests for every non-trivial change to Python handler or business logic code:

- **New MCP tools** — add tests for schema validation, handler dispatch, parameter validation, and the core logic path (happy path + key error cases).
- **Changes to existing tools** — add tests covering the changed behaviour; update any tests that no longer reflect reality.
- **Bug fixes** — add a regression test that would have caught the bug before adding the fix.
- **Refactors that delete or rename public methods** — add a test asserting the old name no longer exists (see `TestConnectionManagerOrphanedMethodsRemoved` for the pattern).

You do **not** need tests for TypeScript/TS-layer glue code that only forwards calls to Python (the TS test runner is not yet configured).

### Test Levels

| Level       | Use for                                                                                            | Marker                     |
| ----------- | -------------------------------------------------------------------------------------------------- | -------------------------- |
| Unit        | Schema shape, parameter validation, pure logic, mock-heavy handler dispatch                        | `@pytest.mark.unit`        |
| Integration | Real file I/O against a `.kicad_sch` / `.kicad_pcb` copy; WireManager, JunctionManager round-trips | `@pytest.mark.integration` |

Keep unit tests free of file I/O. Keep integration tests free of business-logic assertions that belong in unit tests.

### Where to Put Tests

```
tests/
  test_<feature_name>.py       # all Python tests go here
```

Group related test classes inside a single file (e.g. `TestSchemas`, `TestHandlerDispatch`, `TestHandleAddSchematicWireRouting` all in `test_wire_junction_changes.py`). Name classes `Test<Area>` and methods `test_<what_is_verified>`.

Use `python/templates/empty.kicad_sch` as the base fixture for integration tests — copy it to a `tempfile` directory, run the handler, then parse the result with `sexpdata`.

### Running Tests

Always use the `.venv` virtualenv for Python commands:

```bash
npm run test:py                 # pytest tests/ -v
.venv/bin/pytest tests/ -v      # all Python tests
.venv/bin/pytest -m unit        # unit tests only
.venv/bin/pytest -m integration # integration tests only
.venv/bin/pytest --cov=python   # with coverage report
.venv/bin/mypy python/          # type checking
```

## Git Workflow

- **Never open a pull request automatically.** Commit and push when asked, but always wait for explicit instructions before running `gh pr create` or any equivalent command.

## Python Code Style

- **Never use `assert` in production code** — raise a specific exception (`ValueError`, `RuntimeError`, etc.) instead. `assert` is stripped in optimised builds and gives poor error messages.
- **Do not introduce logic-breaking workarounds to satisfy the type checker** (e.g. `x or ""` when `""` is not a valid substitute for `None`). Fix the types or narrow with a proper guard (`if x is None: raise ...`).
