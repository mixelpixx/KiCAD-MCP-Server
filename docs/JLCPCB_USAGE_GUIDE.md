# JLCPCB Integration Guide

The KiCAD MCP Server provides **two complementary approaches** for working with JLCPCB parts:

1. **Local Symbol Libraries** - Search JLCPCB libraries installed via KiCad PCM _(contributed by [@l3wi](https://github.com/l3wi) in [PR #25](https://github.com/mixelpixx/KiCAD-MCP-Server/pull/25))_
2. **JLCPCB API Integration** - Access the complete 100k+ parts catalog with real-time pricing

Both approaches can be used together to give you maximum flexibility.

## Credits

- **Local Symbol Library Search**: Implementation by [@l3wi](https://github.com/l3wi) - [PR #25](https://github.com/mixelpixx/KiCAD-MCP-Server/pull/25)
- **JLCPCB API Integration**: Built on top of the local library foundation

---

## Approach 1: Local Symbol Libraries (Recommended for Getting Started)

### What It Does
- Searches symbol libraries you've installed via KiCad's Plugin and Content Manager (PCM)
- Works with community JLCPCB libraries like `JLCPCB-KiCad-Library`
- No API credentials needed
- Works offline
- Symbols already have LCSC IDs and footprints configured

### Setup

1. **Install JLCPCB Libraries via KiCad PCM:**
   - Open KiCad → Tools → Plugin and Content Manager
   - Search for "JLCPCB" or "JLC"
   - Install libraries like:
     - `JLCPCB-KiCad-Library` (community maintained)
     - `EDA_MCP` (contains common JLCPCB parts)
     - Any other JLCPCB-compatible libraries

2. **Verify Installation:**
   The libraries should appear in KiCad's symbol library table.

### Usage Examples

#### Search for Components
```
search_symbols({
  query: "ESP32",
  library: "JLCPCB"  // Filter to JLCPCB libraries only
})
```

Returns:
```
Found 12 symbols matching "ESP32":

PCM_JLCPCB-MCUs:ESP32-C3 | LCSC: C2934196 | ESP32-C3 RISC-V WiFi/BLE SoC
PCM_JLCPCB-MCUs:ESP32-S2 | LCSC: C701342 | ESP32-S2 WiFi SoC
...
```

#### Search by LCSC ID
```
search_symbols({
  query: "C2934196"  // Direct LCSC ID search
})
```

#### Get Symbol Details
```
get_symbol_info({
  symbol: "PCM_JLCPCB-MCUs:ESP32-C3"
})
```

Returns:
```
Symbol: PCM_JLCPCB-MCUs:ESP32-C3
Description: ESP32-C3 RISC-V WiFi/BLE SoC
LCSC: C2934196
Manufacturer: Espressif
MPN: ESP32-C3-WROOM-02
Footprint: Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm
Class: Extended
```

### Advantages
- ✅ No API credentials required
- ✅ Works offline after library installation
- ✅ Symbols pre-configured with correct footprints
- ✅ Community-maintained and curated
- ✅ Instant availability

### Limitations
- ❌ Only parts in installed libraries (typically 1k-10k parts)
- ❌ No real-time pricing or stock information
- ❌ Requires manual library updates via PCM

---

## Approach 2: JLCPCB API Integration (For Complete Catalog Access)

### What It Does
- Downloads the **complete JLCPCB parts catalog** (~100k+ parts)
- Provides **real-time pricing and stock information**
- Automatic **Basic vs Extended** library type identification (Basic = free assembly)
- Smart suggestions for cheaper/in-stock alternatives
- Package-to-footprint mapping for KiCad

### Setup

#### 1. Get JLCPCB API Credentials

Visit [JLCPCB](https://jlcpcb.com/) and get your API credentials:
1. Log in to your JLCPCB account
2. Go to: **Account → API Management**
3. Click "Create API Key"
4. Save your `appKey` and `appSecret`

#### 2. Configure Environment Variables

Add to your shell profile (`~/.bashrc`, `~/.zshrc`, or `~/.profile`):

```bash
export JLCPCB_API_KEY="your_app_key_here"
export JLCPCB_API_SECRET="your_app_secret_here"
```

Or create a `.env` file in the project root:

```
JLCPCB_API_KEY=your_app_key_here
JLCPCB_API_SECRET=your_app_secret_here
```

#### 3. Download the Parts Database

**One-time setup** (takes 5-10 minutes):

```
download_jlcpcb_database({ force: false })
```

This downloads ~100k parts from JLCPCB and creates a local SQLite database (`data/jlcpcb_parts.db`).

**Output:**
```
✓ Successfully downloaded JLCPCB parts database

Total parts: 108,523
Basic parts: 2,856 (free assembly)
Extended parts: 105,667 ($3 setup fee each)
Database size: 42.3 MB
Database path: /home/user/KiCAD-MCP-Server/data/jlcpcb_parts.db
```

### Usage Examples

#### Search for Parts with Specifications

```
search_jlcpcb_parts({
  query: "10k resistor",
  package: "0603",
  library_type: "Basic"  // Only free-assembly parts
})
```

**Returns:**
```
Found 15 JLCPCB parts:

C25804: RC0603FR-0710KL - 10kΩ ±1% 0.1W [Basic] - $0.002/ea (15000 in stock)
C58972: 0603WAF1002T5E - 10kΩ ±1% 0.1W [Basic] - $0.001/ea (50000 in stock)
C25744: RC0603FR-0710KP - 10kΩ ±1% 0.1W [Basic] - $0.002/ea (12000 in stock)
...

💡 Basic parts have free assembly. Extended parts charge $3 setup fee per unique part.
```

#### Get Part Details with Pricing

```
get_jlcpcb_part({
  lcsc_number: "C58972"
})
```

**Returns:**
```
LCSC: C58972
MFR Part: 0603WAF1002T5E
Manufacturer: UNI-ROYAL
Category: Resistors / Chip Resistor - Surface Mount
Package: 0603
Description: 10kΩ ±1% 0.1W Thick Film Resistors
Library Type: Basic (Free assembly!)
Stock: 50000

Price Breaks:
  1+: $0.0010/ea
  10+: $0.0009/ea
  100+: $0.0008/ea
  1000+: $0.0007/ea

Suggested KiCAD Footprints:
  - Resistor_SMD:R_0603_1608Metric
  - Capacitor_SMD:C_0603_1608Metric
  - LED_SMD:LED_0603_1608Metric
```

#### Find Cheaper Alternatives

```
suggest_jlcpcb_alternatives({
  lcsc_number: "C25804",
  limit: 5
})
```

**Returns:**
```
Alternative parts for C25804:

1. C58972: 0603WAF1002T5E [Basic] - $0.001/ea (50% cheaper)
   10kΩ ±1% 0.1W Thick Film Resistors
   Stock: 50000

2. C22790: 0603WAF1002T - [Basic] - $0.0011/ea (45% cheaper)
   10kΩ ±1% 0.1W Thick Film Resistors
   Stock: 35000
...
```

#### Search by Category and Package

```
search_jlcpcb_parts({
  category: "Microcontrollers",
  package: "QFN-32",
  manufacturer: "STM",
  in_stock: true,
  limit: 10
})
```

#### Get Database Statistics

```
get_jlcpcb_database_stats({})
```

**Returns:**
```
JLCPCB Database Statistics:

Total parts: 108,523
Basic parts: 2,856 (free assembly)
Extended parts: 105,667 ($3 setup fee each)
In stock: 95,432
Database path: /home/user/KiCAD-MCP-Server/data/jlcpcb_parts.db
```

### Advantages
- ✅ Complete JLCPCB catalog (100k+ parts)
- ✅ Real-time pricing and stock data
- ✅ Automatic Basic/Extended identification
- ✅ Cost optimization suggestions
- ✅ Works offline after initial download
- ✅ Fast parametric search

### Limitations
- ❌ Requires API credentials
- ❌ Initial download takes 5-10 minutes
- ❌ Database needs periodic updates for latest parts
- ❌ Footprint mapping may need manual verification

---

## Best Practices: Using Both Approaches Together

### Workflow 1: Design with Known Components

**Use Local Libraries:**
```
1. search_symbols({ query: "STM32F103", library: "JLCPCB" })
2. Select component from installed library
3. Component already has correct symbol + footprint + LCSC ID
```

**Why:** Faster, symbols are pre-configured and tested.

### Workflow 2: Find Optimal Part for Cost

**Use JLCPCB API:**
```
1. search_jlcpcb_parts({
     query: "10k resistor",
     package: "0603",
     library_type: "Basic"
   })
2. Select cheapest Basic part
3. Use suggested footprint from API
```

**Why:** Ensures lowest cost and maximum stock availability.

### Workflow 3: Explore Unknown Parts

**Start with API, verify with Libraries:**
```
1. search_jlcpcb_parts({ query: "ESP32", limit: 20 })
2. Find interesting part (e.g., C2934196)
3. search_symbols({ query: "C2934196" })
4. If found in library → use library symbol
5. If not found → use API footprint suggestion
```

**Why:** Combines discovery power of API with quality of curated libraries.

---

## Cost Optimization Tips

### 1. Prefer Basic Parts

```
search_jlcpcb_parts({
  query: "resistor 10k",
  library_type: "Basic"  // Free assembly!
})
```

**Why:** Basic parts have **$0 assembly fee**. Extended parts charge **$3 per unique part**.

### 2. Use Alternatives Tool

```
suggest_jlcpcb_alternatives({ lcsc_number: "C12345" })
```

**Why:** Find cheaper, more available, or Basic alternatives automatically.

### 3. Check Stock Levels

Always filter `in_stock: true` to avoid ordering parts that are out of stock:

```
search_jlcpcb_parts({
  query: "capacitor",
  in_stock: true  // Only show available parts
})
```

### 4. Calculate BOM Cost

For each part in your design:
1. Use `get_jlcpcb_part()` to get price breaks
2. Sum up total cost based on order quantity
3. Check library_type count (each unique Extended part = $3 fee)

---

## Updating the Database

The JLCPCB parts database should be updated periodically to get latest parts and pricing.

### Manual Update

```
download_jlcpcb_database({ force: true })
```

This re-downloads the entire catalog and replaces the existing database.

### Automatic Updates (Future)

Future versions will support incremental updates that only fetch new/changed parts.

---

## Troubleshooting

### "JLCPCB API credentials not configured"

**Solution:** Set environment variables:
```bash
export JLCPCB_API_KEY="your_key"
export JLCPCB_API_SECRET="your_secret"
```

### "Database not found or empty"

**Solution:** Run:
```
download_jlcpcb_database({ force: false })
```

### "No symbols found" (Local Libraries)

**Solution:**
1. Install JLCPCB libraries via KiCad PCM
2. Verify library is enabled in KiCad symbol library table
3. Restart KiCad MCP server

### "Authentication failed"

**Solution:**
1. Verify your API credentials are correct
2. Check JLCPCB account has API access enabled
3. Try regenerating API key/secret in JLCPCB dashboard

---

## API vs Libraries: Quick Reference

| Feature | Local Libraries | JLCPCB API |
|---------|----------------|------------|
| **Parts Count** | 1k-10k (installed) | 100k+ (complete catalog) |
| **Setup** | Install via PCM | API credentials + download |
| **Offline Use** | ✅ Yes | ✅ Yes (after download) |
| **Pricing** | ❌ No | ✅ Real-time |
| **Stock Info** | ❌ No | ✅ Real-time |
| **Footprints** | ✅ Pre-configured | ⚠️ Auto-suggested |
| **Updates** | Manual via PCM | Re-download database |
| **Speed** | ⚡ Instant | ⚡ Fast (local DB) |
| **Cost Optimization** | ❌ Manual | ✅ Automatic |

---

## Example Workflows

### Complete Design Flow

```
# 1. Find main MCU from local library (curated)
search_symbols({ query: "ESP32", library: "JLCPCB" })
→ Use: PCM_JLCPCB-MCUs:ESP32-C3

# 2. Find passives optimized for cost (API)
search_jlcpcb_parts({
  query: "capacitor 10uF",
  package: "0805",
  library_type: "Basic"
})
→ Use: C15850 ($0.004, Basic, 80k stock)

# 3. Verify connector in library
search_symbols({ query: "USB-C" })
→ Use library symbol if available

# 4. Export BOM with LCSC numbers
# All components now have LCSC IDs for JLCPCB assembly!
```

---

## Resources

- [JLCPCB API Documentation](https://jlcpcb.com/help/article/JLCPCB-API)
- [JLCPCB Parts Library](https://jlcpcb.com/parts)
- [KiCad Plugin and Content Manager](https://www.kicad.org/help/pcm/)
- [JLCPCB-KiCad-Library (GitHub)](https://github.com/pejot/JLC2KiCad_lib)

---

## Summary

**Use Local Libraries when:**
- Starting a new design with common components
- You want pre-configured, tested symbols
- Working offline
- Components are in installed libraries

**Use JLCPCB API when:**
- Optimizing cost (find cheapest Basic parts)
- Checking real-time stock availability
- Exploring parts outside installed libraries
- Need complete catalog access

**Best approach:** Use both! Start with local libraries for known components, then use API for cost optimization and finding alternatives.
