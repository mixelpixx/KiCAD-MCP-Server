# JLCPCB Parts Integration Plan

**Goal:** Enable AI-driven component selection using JLCPCB's assembly parts library with real pricing and availability

**Status:** Planning Phase
**Estimated Effort:** 3-4 days
**Priority:** Week 2 Priority 3 (after Component Libraries + Routing)

---

## Overview

Integrate JLCPCB's SMT assembly parts library (~100k+ parts) into the KiCAD MCP server, enabling:
- Component search by specifications (e.g., "10k resistor 0603 1%")
- Automatic part selection optimized for cost (prefer Basic parts)
- Real stock and pricing information
- Mapping JLCPCB parts to KiCAD footprints

---

## Architecture

### Data Flow

```
┌──────────────────────────────────────────────────┐
│  JLCPCB API (https://jlcpcb.com/external/...)   │
│  - Requires API key/secret                       │
│  - Returns: ~100k parts with specs/pricing       │
└───────────────────┬──────────────────────────────┘
                    │ Download (once, then updates)
                    ▼
┌──────────────────────────────────────────────────┐
│  SQLite Database (local cache)                   │
│  - components table                              │
│  - manufacturers table                           │
│  - categories table                              │
│  - Fast parametric search                        │
└───────────────────┬──────────────────────────────┘
                    │ Search/query
                    ▼
┌──────────────────────────────────────────────────┐
│  JLCPCB Parts Manager (Python)                   │
│  - search_parts(specs)                           │
│  - get_part_info(lcsc_number)                    │
│  - map_to_footprint(package)                     │
│  - suggest_alternatives(part)                    │
└───────────────────┬──────────────────────────────┘
                    │ MCP Tools
                    ▼
┌──────────────────────────────────────────────────┐
│  MCP Tools (TypeScript)                          │
│  - search_jlcpcb_parts                           │
│  - get_jlcpcb_part                               │
│  - place_component (enhanced)                    │
└──────────────────────────────────────────────────┘
```

### File Structure

```
python/commands/
├── jlcpcb.py           # JLCPCB API client
└── jlcpcb_parts.py     # Parts database manager

data/
├── jlcpcb_parts.db     # SQLite cache (gitignored)
└── footprint_mappings.json  # Package → KiCAD footprint mapping

src/tools/
└── jlcpcb.ts           # MCP tool definitions

docs/
└── JLCPCB_INTEGRATION.md  # User documentation
```

---

## Implementation Phases

### Phase 1: JLCPCB API Client (Day 1)

**File:** `python/commands/jlcpcb.py`

**Features:**
- Authenticate with JLCPCB API (requires user-provided key/secret)
- Download parts database (paginated, ~100k parts)
- Handle rate limiting and retries
- Save to SQLite database

**API Endpoints:**
```python
# Get auth token
POST https://jlcpcb.com/external/genToken
{
  "appKey": "YOUR_KEY",
  "appSecret": "YOUR_SECRET"
}

# Fetch parts (paginated)
POST https://jlcpcb.com/external/component/getComponentInfos
Headers: { "externalApiToken": "TOKEN" }
Body: { "lastKey": "PAGINATION_KEY" }  # Optional, for next page
```

**Database Schema:**
```sql
CREATE TABLE components (
    lcsc TEXT PRIMARY KEY,           -- "C12345"
    category TEXT,                   -- "Resistors"
    subcategory TEXT,                -- "Chip Resistor - Surface Mount"
    mfr_part TEXT,                   -- "RC0603FR-0710KL"
    package TEXT,                    -- "0603"
    solder_joints INTEGER,           -- 2
    manufacturer TEXT,               -- "YAGEO"
    library_type TEXT,               -- "Basic" or "Extended"
    description TEXT,                -- "10kΩ ±1% 0.1W"
    datasheet TEXT,                  -- URL
    stock INTEGER,                   -- 15000
    price_json TEXT,                 -- JSON array of price breaks
    last_updated INTEGER             -- Unix timestamp
);

CREATE INDEX idx_category ON components(category, subcategory);
CREATE INDEX idx_package ON components(package);
CREATE INDEX idx_manufacturer ON components(manufacturer);
CREATE INDEX idx_library_type ON components(library_type);
```

**Environment Variables:**
```bash
# ~/.bashrc or .env
export JLCPCB_API_KEY="your_key_here"
export JLCPCB_API_SECRET="your_secret_here"
```

**Python Implementation Outline:**
```python
class JLCPCBClient:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.token = None

    def authenticate(self) -> str:
        """Get auth token from JLCPCB API"""

    def fetch_parts_page(self, last_key: Optional[str] = None) -> dict:
        """Fetch one page of parts (paginated)"""

    def download_full_database(self, db_path: str, progress_callback=None):
        """Download entire parts library to SQLite"""

    def update_database(self, db_path: str):
        """Incremental update (fetch only new/changed parts)"""
```

---

### Phase 2: Parts Database Manager (Day 2)

**File:** `python/commands/jlcpcb_parts.py`

**Features:**
- Initialize/load SQLite database
- Parametric search (resistance, capacitance, voltage, etc.)
- Filter by library type (Basic/Extended)
- Sort by price, stock, or popularity
- Map package names to KiCAD footprints

**Python Implementation Outline:**
```python
class JLCPCBPartsManager:
    def __init__(self, db_path: str = "data/jlcpcb_parts.db"):
        self.conn = sqlite3.connect(db_path)

    def search_parts(
        self,
        query: str = None,           # Free-text search
        category: str = None,         # "Resistors"
        package: str = None,          # "0603"
        library_type: str = None,     # "Basic" only
        manufacturer: str = None,     # "YAGEO"
        in_stock: bool = True,        # Only parts with stock > 0
        limit: int = 20
    ) -> List[dict]:
        """Search parts with filters"""

    def get_part_info(self, lcsc_number: str) -> dict:
        """Get detailed info for specific part"""

    def map_package_to_footprint(self, package: str) -> List[str]:
        """Map JLCPCB package name to KiCAD footprint(s)"""
        # Example: "0603" → ["Resistor_SMD:R_0603_1608Metric",
        #                     "Capacitor_SMD:C_0603_1608Metric"]

    def parse_description(self, description: str, category: str) -> dict:
        """Extract parameters from description text"""
        # Example: "10kΩ ±1% 0.1W" → {resistance: "10k", tolerance: "1%", power: "0.1W"}

    def suggest_alternatives(self, lcsc_number: str, limit: int = 5) -> List[dict]:
        """Find similar parts (cheaper, more stock, Basic instead of Extended)"""
```

**Package to Footprint Mapping:**
```json
{
  "0402": [
    "Resistor_SMD:R_0402_1005Metric",
    "Capacitor_SMD:C_0402_1005Metric",
    "LED_SMD:LED_0402_1005Metric"
  ],
  "0603": [
    "Resistor_SMD:R_0603_1608Metric",
    "Capacitor_SMD:C_0603_1608Metric",
    "LED_SMD:LED_0603_1608Metric"
  ],
  "0805": [
    "Resistor_SMD:R_0805_2012Metric",
    "Capacitor_SMD:C_0805_2012Metric"
  ],
  "SOT-23": [
    "Package_TO_SOT_SMD:SOT-23",
    "Package_TO_SOT_SMD:SOT-23-3"
  ],
  "SOIC-8": [
    "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
  ]
}
```

---

### Phase 3: MCP Tools Integration (Day 3)

**File:** `src/tools/jlcpcb.ts`

**New MCP Tools:**

#### 1. `search_jlcpcb_parts`
Search JLCPCB parts library by specifications.

```typescript
{
  name: "search_jlcpcb_parts",
  description: "Search JLCPCB assembly parts by specifications",
  inputSchema: {
    type: "object",
    properties: {
      query: {
        type: "string",
        description: "Free-text search (e.g., '10k resistor 0603')"
      },
      category: {
        type: "string",
        description: "Category filter (e.g., 'Resistors', 'Capacitors')"
      },
      package: {
        type: "string",
        description: "Package filter (e.g., '0603', 'SOT-23')"
      },
      library_type: {
        type: "string",
        enum: ["Basic", "Extended", "All"],
        description: "Filter by library type (Basic = free assembly)"
      },
      in_stock: {
        type: "boolean",
        default: true,
        description: "Only show parts with available stock"
      },
      limit: {
        type: "number",
        default: 20,
        description: "Maximum results to return"
      }
    }
  }
}
```

**Example Usage:**
```
User: "Find me a 10k resistor, 0603 package, JLCPCB basic part"
Claude: [uses search_jlcpcb_parts]
Found 15 parts:
1. C25804 - YAGEO RC0603FR-0710KL - 10kΩ ±1% 0.1W - Basic - $0.002 (15k in stock)
2. C58972 - UNI-ROYAL 0603WAF1002T5E - 10kΩ ±1% 0.1W - Basic - $0.001 (50k in stock)
...
Recommended: C58972 (cheapest Basic part with high stock)
```

#### 2. `get_jlcpcb_part`
Get detailed information about a specific JLCPCB part.

```typescript
{
  name: "get_jlcpcb_part",
  description: "Get detailed info for a specific JLCPCB part",
  inputSchema: {
    type: "object",
    properties: {
      lcsc_number: {
        type: "string",
        description: "LCSC part number (e.g., 'C25804')"
      }
    },
    required: ["lcsc_number"]
  }
}
```

**Returns:**
```json
{
  "lcsc": "C25804",
  "mfr_part": "RC0603FR-0710KL",
  "manufacturer": "YAGEO",
  "category": "Resistors / Chip Resistor - Surface Mount",
  "package": "0603",
  "description": "10kΩ ±1% 0.1W Thick Film Resistors",
  "library_type": "Basic",
  "stock": 15000,
  "price_breaks": [
    {"qty": 1, "price": "$0.002"},
    {"qty": 10, "price": "$0.0018"},
    {"qty": 100, "price": "$0.0015"}
  ],
  "datasheet": "https://datasheet.lcsc.com/...",
  "kicad_footprints": [
    "Resistor_SMD:R_0603_1608Metric"
  ]
}
```

#### 3. Enhanced `place_component`
Add JLCPCB integration to existing component placement.

```typescript
// Add new optional parameter to place_component:
{
  jlcpcb_part: {
    type: "string",
    description: "JLCPCB LCSC part number (e.g., 'C25804'). If provided, will use JLCPCB specs."
  }
}
```

**Example:**
```
User: "Place a 10k resistor at 50, 40mm using JLCPCB part C25804"
Claude: [uses place_component with jlcpcb_part="C25804"]
  - Looks up C25804 → finds package "0603"
  - Maps "0603" → "Resistor_SMD:R_0603_1608Metric"
  - Places component with:
    - Reference: R1
    - Value: 10k (C25804)
    - Footprint: Resistor_SMD:R_0603_1608Metric
    - Attribute: LCSC part C25804 stored in component properties
```

---

### Phase 4: Testing & Documentation (Day 4)

**Testing:**
1. Download JLCPCB database (verify ~100k parts loaded)
2. Test parametric search (resistors, capacitors, ICs)
3. Test package mapping (0603 → correct footprints)
4. Test component placement with JLCPCB parts
5. Verify BOM export includes LCSC part numbers

**Documentation:**
- User guide: How to get JLCPCB API key
- Usage examples for each MCP tool
- Best practices (prefer Basic parts, check stock)
- BOM generation for JLCPCB assembly

---

## User Workflow Examples

### Example 1: Find and Place a Resistor
```
User: "I need a 10k pull-up resistor, 0603 size, cheapest JLCPCB basic part"

Claude: [uses search_jlcpcb_parts]
  query: "10k resistor"
  package: "0603"
  library_type: "Basic"

Found: C58972 - UNI-ROYAL 0603WAF1002T5E
  - 10kΩ ±1% 0.1W
  - Basic part (free assembly!)
  - $0.001 each
  - 50,000 in stock

User: "Perfect, place it at position 45, 30mm"

Claude: [uses place_component]
  componentId: "Resistor_SMD:R_0603_1608Metric"
  position: {x: 45, y: 30}
  reference: "R1"
  value: "10k (C58972)"
  jlcpcb_part: "C58972"

  ✅ Placed R1: 10k at (45, 30) mm
  JLCPCB: C58972 (Basic part, $0.001)
```

### Example 2: Design a Cost-Optimized LED Circuit
```
User: "Design an LED circuit with current-limiting resistor, use only JLCPCB basic parts"

Claude: [searches for LED]
  Found: C2286 - Everlight 19-217/BHC-ZL1M2RY/3T (Red LED, 0603) - Basic - $0.015

  [searches for resistor]
  Calculated: 330Ω for 5V → 20mA
  Found: C23138 - UNI-ROYAL 0603WAF3300T5E (330Ω, 0603) - Basic - $0.001

  [places components]
  R1: 330Ω (C23138) at (40, 30) mm
  D1: Red LED (C2286) at (50, 30) mm

  Total BOM cost: $0.016
  Both are Basic parts → Free assembly! 🎉
```

### Example 3: Check Stock Before Ordering
```
User: "I need 100 of part C25804, is there enough stock?"

Claude: [uses get_jlcpcb_part lcsc_number="C25804"]
  Stock: 15,000 units
  ✅ Plenty of stock for 100 units

  Price for 100: $0.0015 each = $0.15 total
```

---

## API Key Setup

**How to Get JLCPCB API Key:**

1. Visit JLCPCB website: https://jlcpcb.com/
2. Log in to your account
3. Go to: Account → API Management
4. Click "Create API Key"
5. Save your `appKey` and `appSecret`

**Configure in MCP:**

Option A: Environment variables (recommended)
```bash
export JLCPCB_API_KEY="your_app_key"
export JLCPCB_API_SECRET="your_app_secret"
```

Option B: Config file
```json
{
  "jlcpcb": {
    "api_key": "your_app_key",
    "api_secret": "your_app_secret",
    "cache_db": "~/.kicad-mcp/jlcpcb_parts.db"
  }
}
```

**Initial Setup:**
```
User: "Download the JLCPCB parts database"

Claude: [runs JLCPCB database download]
  Authenticating... ✅
  Fetching parts... (page 1/500)
  Fetching parts... (page 2/500)
  ...
  ✅ Downloaded 108,523 parts
  ✅ Saved to ~/.kicad-mcp/jlcpcb_parts.db (42 MB)

  Database ready! You can now search JLCPCB parts.
```

---

## Cost Optimization Features

### Prefer Basic Parts

```python
def search_parts_optimized(self, specs: dict) -> List[dict]:
    """
    Search with automatic Basic part preference.
    Returns Basic parts first, Extended parts only if no Basic match.
    """
    basic_parts = self.search_parts(**specs, library_type="Basic")
    if basic_parts:
        return basic_parts
    return self.search_parts(**specs, library_type="Extended")
```

### Calculate BOM Cost

```python
def calculate_bom_cost(self, board: pcbnew.BOARD) -> dict:
    """
    Calculate total cost for JLCPCB assembly.

    Returns:
    {
        "total_parts_cost": 12.50,
        "basic_parts_count": 15,
        "extended_parts_count": 2,
        "extended_setup_fee": 6.00,  # $3 per unique extended part
        "total_assembly_cost": 18.50
    }
    """
```

---

## Integration with Existing Features

### BOM Export Enhancement

Update `export_bom` to include JLCPCB columns:

```csv
Reference,Value,Footprint,LCSC Part,Library Type,Manufacturer,MFR Part,Stock
R1,10k,Resistor_SMD:R_0603_1608Metric,C58972,Basic,UNI-ROYAL,0603WAF1002T5E,50000
D1,Red,LED_SMD:LED_0603_1608Metric,C2286,Basic,Everlight,19-217/BHC-ZL1M2RY/3T,8000
```

This BOM can be directly uploaded to JLCPCB for assembly!

---

## Database Update Strategy

**Initial Download:** ~5-10 minutes (108k parts)

**Incremental Updates:**
- Run daily via cron/scheduled task
- Only fetch parts modified since last update
- Much faster (~30 seconds)

**Update Command:**
```python
# In Python
jlcpcb_client.update_database(db_path)

# Via MCP tool
update_jlcpcb_database(force=False)  # Incremental
update_jlcpcb_database(force=True)   # Full re-download
```

---

## Success Metrics

**Implementation Complete When:**
- ✅ Can download/cache full JLCPCB parts database
- ✅ Parametric search works (resistors, capacitors, ICs)
- ✅ Package → footprint mapping covers 90%+ of common parts
- ✅ MCP tools integrated and tested end-to-end
- ✅ BOM export includes LCSC part numbers
- ✅ Documentation complete with examples

**User Experience Goal:**
```
User: "Design a board with an ESP32, USB-C connector, and LED,
       use only JLCPCB basic parts under $10 BOM"

Claude: [searches JLCPCB database]
        [places all components with real parts]
        [exports BOM ready for manufacturing]

        ✅ Board designed with 23 components
        💰 Total cost: $8.45
        🎉 All Basic parts (free assembly!)
```

---

## Future Enhancements

**Post-MVP (v2.1+):**
- LCSC API integration for extended parametric data
- Digikey/Mouser fallback for non-JLCPCB parts
- Part substitution suggestions (out of stock → alternatives)
- Price history and trend analysis
- Community-contributed package mappings
- Visual part selection UI (if web interface added)

---

## Related Documentation

- [LIBRARY_INTEGRATION.md](./LIBRARY_INTEGRATION.md) - KiCAD footprint libraries
- [REALTIME_WORKFLOW.md](./REALTIME_WORKFLOW.md) - MCP ↔ UI collaboration
- [ROADMAP.md](./ROADMAP.md) - Overall project plan
- [API.md](./API.md) - MCP API reference

---

**Status:** Ready to implement! 🚀
**Next Step:** Get JLCPCB API credentials and start Phase 1
