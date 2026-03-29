# Datasheet Management Tools

**Added in:** v2.2.0-alpha

Two tools for managing component datasheets using LCSC part numbers. Datasheet URLs are constructed directly from LCSC numbers -- no API key or network requests required.

---

## Tools Reference

### `enrich_datasheets`

Scans a KiCAD schematic and fills in missing Datasheet URLs for components that have an LCSC part number set.

**How it works:**

For every placed symbol that has:

- An LCSC property set (e.g., `(property "LCSC" "C123456")`)
- An empty or missing Datasheet field

The tool sets the Datasheet field to: `https://www.lcsc.com/datasheet/C123456.pdf`

The URL is then visible in KiCAD's footprint browser, symbol properties dialog, and any tool that reads the standard Datasheet field.

**Parameters:**

| Parameter        | Type    | Required | Default | Description                             |
| ---------------- | ------- | -------- | ------- | --------------------------------------- |
| `schematic_path` | string  | Yes      | --      | Path to the .kicad_sch file to enrich   |
| `dry_run`        | boolean | No       | false   | Preview changes without writing to disk |

**Returns:**

- Number of components updated
- Number already set (skipped)
- Number without LCSC number
- Details of each updated component (reference, LCSC number, URL)

**Example:**

```
Enrich datasheets for all components in ~/Projects/MyBoard/MyBoard.kicad_sch
```

Use `dry_run=true` to preview what would change:

```
Preview datasheet enrichment for ~/Projects/MyBoard/MyBoard.kicad_sch with dry run enabled.
```

---

### `get_datasheet_url`

Get the LCSC datasheet URL for a single component by LCSC number.

**Parameters:**

| Parameter | Type   | Required | Description                                                                |
| --------- | ------ | -------- | -------------------------------------------------------------------------- |
| `lcsc`    | string | Yes      | LCSC part number, with or without "C" prefix (e.g., "C179739" or "179739") |

**Returns:**

- Datasheet PDF URL
- Product page URL

**Example:**

```
Get the datasheet URL for LCSC part C179739.
```

---

## Workflow

### Adding Datasheets to a Design

1. **Add components with LCSC numbers** -- When placing components from JLCPCB libraries or manually setting the LCSC property, each component gets an LCSC part number
2. **Run enrich_datasheets** -- Scans all components and fills in any missing Datasheet URLs
3. **Verify in KiCAD** -- Open the schematic in KiCAD and check that Datasheet fields are populated. Double-clicking a component shows the URL in its properties

### Integration with JLCPCB Workflow

These tools complement the JLCPCB integration:

1. Use `search_jlcpcb_parts` to find components
2. Place components with LCSC numbers from the search results
3. Run `enrich_datasheets` to auto-populate datasheet URLs
4. Use `export_bom` to generate a BOM with datasheet links

---

## Notes

- The datasheet URL format (`https://www.lcsc.com/datasheet/<LCSC#>.pdf`) works for the vast majority of LCSC parts
- No network request is made -- the URL is constructed from the part number alone
- Components without an LCSC property are skipped silently
- Components that already have a Datasheet URL set are not overwritten

---

## Source Files

- TypeScript tool definitions: `src/tools/datasheet.ts`
- Python implementation: `python/commands/datasheet_manager.py`
