# JLCPCB Parts Integration - Complete Guide

## Overview

The KiCAD MCP Server integrates with JLCPCB's parts library to provide intelligent component selection, cost optimization, and automated part sourcing for PCB assembly.

**Current implementation — two backends, by design:**

- **Search is local.** `search_jlcpcb_parts` queries a local SQLite snapshot that
  you populate once with `download_jlcpcb_database` (the default `cdfer` source is a
  ~600k in-stock subset). The JLCPCB Open Platform API has **no keyword/parametric
  search endpoint**, so search must stay local.
- **Single-part lookup is real-time.** `get_jlcpcb_part` prefers the **JLCPCB Open
  Platform** `getComponentDetailByCode` endpoint (`https://open.jlcpcb.com`) for live
  stock and tiered pricing when credentials are configured, and transparently falls
  back to the local snapshot otherwise. The response's `source` field reports which
  backend answered (`"live-api"` vs `"local-db"`).

Why the split matters: the local snapshot mirror can lag JLCPCB by weeks, so its
stock/price for a specific part may be stale — real-time lookup exists to close that
gap for the part you actually care about.

## Features

✅ **Parametric Search** - Find components by specifications (resistance, capacitance, package, etc.) against the local snapshot
✅ **Real-time Lookup** - Live stock + tiered pricing for a specific LCSC part via the Open Platform API (with local fallback)
✅ **Price Comparison** - Compare Basic vs Extended library pricing
✅ **Alternative Suggestions** - Find cheaper or higher-stock alternatives
✅ **Footprint Mapping** - Automatic JLCPCB package to KiCad footprint mapping

## Real-time part lookup (Open Platform API)

`get_jlcpcb_part` performs a **real-time** lookup when JLCPCB Open Platform
credentials are configured, and falls back to the local snapshot otherwise.

- **Endpoint:** `POST https://open.jlcpcb.com/overseas/openapi/component/getComponentDetailByCode`
  with JSON body `{"componentCodes": ["C25804", ...]}` (batched up to 1000 codes per
  call). Returns live `stockCount`, tiered `priceRanges`, `parameters`, `datasheetUrl`
  and `libraryType` (base → Basic, expand → Extended).
- **Auth:** JOP / HMAC-SHA256 (`Authorization: JOP appid=...,accesskey=...,nonce=...,timestamp=...,signature=...`).
  The signed body must be byte-identical to the wire body, so the request is sent as
  a raw JSON string.
- **No server-side search:** the Open Platform only exposes detail-by-code and a
  full library dump (`getComponentLibraryList`, `{componentCode, componentModel,
  componentSpecification}` only) — there is no keyword/parametric search, which is
  why `search_jlcpcb_parts` stays local.
- **`source` field:** every `get_jlcpcb_part` result includes `source` — `"live-api"`
  when the Open Platform answered, `"local-db"` when the snapshot did.
- **Manufacturer:** the detail response omits `manufacturer`; it is backfilled from
  the local snapshot row when available.

### Configuring credentials (`.env`)

Create a `.env` file in the project root (it is gitignored — see `.env.example`):

```
JLCPCB_APP_ID=your_app_id
JLCPCB_API_KEY=your_access_key
JLCPCB_API_SECRET=your_secret_key
```

The server auto-loads this `.env` on first use of the JLCPCB client (non-destructively —
it never overrides a variable already present in the environment). Without credentials,
`get_jlcpcb_part` silently uses the local snapshot.

## Quick Start

### 1. Search for Components

```python
from commands.jlcsearch import JLCSearchClient

client = JLCSearchClient()

# Search for resistors
resistors = client.search_resistors(
    resistance=10000,  # 10kΩ
    package="0603",
    limit=20
)

# Search for capacitors
capacitors = client.search_capacitors(
    capacitance=1e-7,  # 100nF
    package="0603",
    limit=20
)

# General component search
components = client.search_components(
    "components",
    package="0603",
    limit=100
)
```

### 2. Get Part Details

```python
# Get specific part by LCSC number
part = client.get_part_by_lcsc(25804)  # C25804
print(f"Part: {part['mfr']}")
print(f"Stock: {part['stock']}")
print(f"Price: ${part['price1']}")
print(f"Basic Library: {part['is_basic']}")
```

### 3. Database Integration

```python
from commands.jlcpcb_parts import JLCPCBPartsManager

# Initialize database
db = JLCPCBPartsManager()  # Uses data/jlcpcb_parts.db

# Download and import parts (one-time setup)
client = JLCSearchClient()
parts = client.download_all_components()
db.import_jlcsearch_parts(parts)

# Search imported database
results = db.search_parts(
    query="resistor",
    package="0603",
    library_type="Basic",
    in_stock=True,
    limit=20
)
```

### 4. Footprint Mapping

```python
# Map JLCPCB package to KiCad footprints
footprints = db.map_package_to_footprint("0603")
# Returns:
# [
#   "Resistor_SMD:R_0603_1608Metric",
#   "Capacitor_SMD:C_0603_1608Metric",
#   "LED_SMD:LED_0603_1608Metric"
# ]
```

## API Reference

### JLCSearchClient

#### `search_resistors(resistance, package, limit)`

Search for resistors by value and package.

**Parameters:**

- `resistance` (int, optional): Resistance in ohms
- `package` (str, optional): Package size ("0402", "0603", "0805", etc.)
- `limit` (int): Maximum results (default: 100)

**Returns:** List of resistor dicts with fields:

- `lcsc`: LCSC number (integer)
- `mfr`: Manufacturer part number
- `package`: Package size
- `is_basic`: True if Basic library part (no assembly fee)
- `resistance`: Resistance in ohms
- `tolerance_fraction`: Tolerance (0.01 = 1%)
- `power_watts`: Power rating in mW
- `stock`: Available stock
- `price1`: Unit price in USD

#### `search_capacitors(capacitance, package, limit)`

Search for capacitors by value and package.

**Parameters:**

- `capacitance` (float, optional): Capacitance in farads (e.g., 1e-7 for 100nF)
- `package` (str, optional): Package size
- `limit` (int): Maximum results

**Returns:** List of capacitor dicts

#### `search_components(category, limit, offset, **filters)`

General component search.

**Parameters:**

- `category` (str): "resistors", "capacitors", "components", etc.
- `limit` (int): Maximum results
- `offset` (int): Pagination offset
- `**filters`: Additional filters (package="0603", lcsc=25804, etc.)

**Returns:** List of component dicts

#### `download_all_components(callback, batch_size)`

Download entire JLCPCB parts catalog.

**Parameters:**

- `callback` (callable, optional): Progress callback(parts_count, status_msg)
- `batch_size` (int): Parts per batch (default: 1000)

**Returns:** List of all parts (~100k components)

**Note:** This may take 5-10 minutes to complete.

### JLCPCBPartsManager

#### `import_jlcsearch_parts(parts, progress_callback)`

Import parts from JLCSearch into local SQLite database.

**Parameters:**

- `parts` (list): List of part dicts from JLCSearchClient
- `progress_callback` (callable, optional): Progress updates

#### `search_parts(query, category, package, library_type, manufacturer, in_stock, limit)`

Search local database with filters.

**Parameters:**

- `query` (str, optional): Free-text search
- `category` (str, optional): Category filter
- `package` (str, optional): Package filter
- `library_type` (str, optional): "Basic", "Extended", or "Preferred"
- `manufacturer` (str, optional): Manufacturer filter
- `in_stock` (bool): Only in-stock parts (default: True)
- `limit` (int): Maximum results

**Returns:** List of matching parts

#### `get_part_info(lcsc_number)`

Get detailed part information.

**Parameters:**

- `lcsc_number` (str): LCSC part number (e.g., "C25804")

**Returns:** Part dict or None

#### `get_database_stats()`

Get database statistics.

**Returns:** Dict with:

- `total_parts`: Total parts count
- `basic_parts`: Basic library count
- `extended_parts`: Extended library count
- `in_stock`: Parts with stock > 0
- `db_path`: Database file path

#### `map_package_to_footprint(package)`

Map JLCPCB package to KiCad footprints.

**Parameters:**

- `package` (str): JLCPCB package name

**Returns:** List of KiCad footprint library references

## Data Format

### JLCSearch Part Object

```json
{
  "lcsc": 25804,
  "mfr": "0603WAF1002T5E",
  "package": "0603",
  "is_basic": true,
  "is_preferred": false,
  "resistance": 10000,
  "tolerance_fraction": 0.01,
  "power_watts": 100,
  "stock": 37165617,
  "price1": 0.000842857
}
```

### Database Schema

```sql
CREATE TABLE components (
    lcsc TEXT PRIMARY KEY,        -- "C25804"
    category TEXT,                 -- "Resistors"
    subcategory TEXT,              -- "Chip Resistor"
    mfr_part TEXT,                 -- "0603WAF1002T5E"
    package TEXT,                  -- "0603"
    solder_joints INTEGER,
    manufacturer TEXT,
    library_type TEXT,             -- "Basic" or "Extended"
    description TEXT,              -- "10kΩ ±1% 100mW"
    datasheet TEXT,
    stock INTEGER,
    price_json TEXT,               -- JSON array of price breaks
    last_updated INTEGER           -- Unix timestamp
);
```

## Package to Footprint Mappings

| JLCPCB Package | KiCad Footprints                                                                                 |
| -------------- | ------------------------------------------------------------------------------------------------ |
| 0402           | Resistor_SMD:R_0402_1005Metric<br>Capacitor_SMD:C_0402_1005Metric<br>LED_SMD:LED_0402_1005Metric |
| 0603           | Resistor_SMD:R_0603_1608Metric<br>Capacitor_SMD:C_0603_1608Metric<br>LED_SMD:LED_0603_1608Metric |
| 0805           | Resistor_SMD:R_0805_2012Metric<br>Capacitor_SMD:C_0805_2012Metric                                |
| 1206           | Resistor_SMD:R_1206_3216Metric<br>Capacitor_SMD:C_1206_3216Metric                                |
| SOT-23         | Package_TO_SOT_SMD:SOT-23<br>Package_TO_SOT_SMD:SOT-23-3                                         |
| SOT-23-5       | Package_TO_SOT_SMD:SOT-23-5                                                                      |
| SOT-23-6       | Package_TO_SOT_SMD:SOT-23-6                                                                      |
| SOT-223        | Package_TO_SOT_SMD:SOT-223                                                                       |
| SOIC-8         | Package_SO:SOIC-8_3.9x4.9mm_P1.27mm                                                              |
| QFN-20         | Package_DFN_QFN:QFN-20-1EP_4x4mm_P0.5mm_EP2.5x2.5mm                                              |

## Best Practices

### 1. Always Use Basic Library Parts First

Basic library parts have **no assembly fee** ($0/part), while Extended parts cost **$3/part**.

```python
# Filter for Basic parts only
basic_parts = [p for p in results if p['is_basic']]
```

### 2. Check Stock Availability

Ensure sufficient stock before committing to a design.

```python
# Only use parts with >1000 stock
high_stock = [p for p in results if p['stock'] > 1000]
```

### 3. Compare Prices

Even within Basic library, prices vary significantly.

```python
# Find cheapest option
cheapest = min(results, key=lambda x: x.get('price1', 999))
```

### 4. Use Standardized Packages

Stick to common packages (0402, 0603, 0805) for better availability and pricing.

### 5. Cache Database Locally

Download the full parts database once and search locally for faster results.

```python
# Initial download (one-time, ~5-10 minutes)
if not os.path.exists("data/jlcpcb_parts.db"):
    parts = client.download_all_components()
    db.import_jlcsearch_parts(parts)

# Subsequent searches use local database (instant)
results = db.search_parts(...)
```

## Troubleshooting

### API Rate Limiting

JLCSearch is a community service. If you hit rate limits:

- Add delays between requests (`time.sleep(0.1)`)
- Use the local database instead of repeated API calls
- Download the full database once and work offline

### Missing Data

JLCSearch may not have all fields that official JLCPCB API provides:

- No datasheets (use manufacturer website)
- Limited category information
- No solder joint count

### Stock Discrepancies

Stock levels are updated periodically but may lag real-time JLCPCB data by a few hours.

## JLCPCB Open Platform API (real-time lookup)

`get_jlcpcb_part` uses the JLCPCB **Open Platform** (`https://open.jlcpcb.com`) with
HMAC-SHA256 (JOP) authentication for real-time single-part detail. This requires
APP_ID, ACCESS_KEY and SECRET_KEY credentials from your JLCPCB account (see
"Configuring credentials" above). The client:

```python
from commands.jlcpcb import JLCPCBClient

# Credentials are read from the project-root .env (auto-loaded) or the environment:
# JLCPCB_APP_ID / JLCPCB_API_KEY / JLCPCB_API_SECRET
client = JLCPCBClient()
if client.has_credentials():
    part = client.get_part_by_lcsc("C25804")  # live stock + tiered pricing
```

**Note:** The Open Platform has no search endpoint — keyword/parametric search always
runs against the local snapshot (`search_jlcpcb_parts`). The legacy
`jlcpcb.com/external` bulk-download path (`fetch_parts_page` /
`download_full_database`) is deprecated and only kept for backwards compatibility.

## Credits

- **JLCSearch API**: https://jlcsearch.tscircuit.com/ (by [@tscircuit](https://github.com/tscircuit/jlcsearch))
- **JLCParts Database**: https://github.com/yaqwsx/jlcparts (by [@yaqwsx](https://github.com/yaqwsx))
- **JLCPCB**: https://jlcpcb.com/ (official parts library provider)

## License

This integration uses publicly available JLCPCB parts data via the JLCSearch community service. Users must comply with JLCPCB's terms of service when using this data for production PCB orders.
