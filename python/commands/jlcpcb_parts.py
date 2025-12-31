"""
JLCPCB Parts Database Manager

Manages local SQLite database of JLCPCB parts for fast searching
and component selection.
"""

import os
import sqlite3
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger('kicad_interface')


class JLCPCBPartsManager:
    """
    Manages local database of JLCPCB parts

    Provides fast parametric search, filtering, and package-to-footprint mapping.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize parts database manager

        Args:
            db_path: Path to SQLite database file (default: data/jlcpcb_parts.db)
        """
        if db_path is None:
            # Default to data directory in project root
            project_root = Path(__file__).parent.parent.parent
            data_dir = project_root / "data"
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "jlcpcb_parts.db")

        self.db_path = db_path
        self.conn = None
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with schema"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # Return rows as dicts

        cursor = self.conn.cursor()

        # Create components table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS components (
                lcsc TEXT PRIMARY KEY,
                category TEXT,
                subcategory TEXT,
                mfr_part TEXT,
                package TEXT,
                solder_joints INTEGER,
                manufacturer TEXT,
                library_type TEXT,
                description TEXT,
                datasheet TEXT,
                stock INTEGER,
                price_json TEXT,
                last_updated INTEGER
            )
        ''')

        # Create indexes for fast searching
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_category ON components(category, subcategory)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_package ON components(package)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_manufacturer ON components(manufacturer)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_library_type ON components(library_type)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_mfr_part ON components(mfr_part)')

        # Full-text search index for descriptions
        cursor.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS components_fts USING fts5(
                lcsc,
                description,
                mfr_part,
                manufacturer,
                content=components
            )
        ''')

        self.conn.commit()
        logger.info(f"Initialized JLCPCB parts database at {self.db_path}")

    def import_parts(self, parts: List[Dict], progress_callback=None):
        """
        Import parts into database from JLCPCB API response

        Args:
            parts: List of part dicts from JLCPCB API
            progress_callback: Optional callback(current, total, message)
        """
        cursor = self.conn.cursor()
        imported = 0
        skipped = 0

        for i, part in enumerate(parts):
            try:
                # Extract price breaks
                price_json = json.dumps(part.get('prices', []))

                # Determine library type
                library_type = self._determine_library_type(part)

                cursor.execute('''
                    INSERT OR REPLACE INTO components (
                        lcsc, category, subcategory, mfr_part, package,
                        solder_joints, manufacturer, library_type, description,
                        datasheet, stock, price_json, last_updated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    part.get('componentCode'),  # lcsc
                    part.get('firstSortName'),  # category
                    part.get('secondSortName'),  # subcategory
                    part.get('componentModelEn'),  # mfr_part
                    part.get('componentSpecificationEn'),  # package
                    part.get('soldPoint'),  # solder_joints
                    part.get('componentBrandEn'),  # manufacturer
                    library_type,  # library_type
                    part.get('describe'),  # description
                    part.get('dataManualUrl'),  # datasheet
                    part.get('stockCount', 0),  # stock
                    price_json,  # price_json
                    int(datetime.now().timestamp())  # last_updated
                ))

                imported += 1

                if progress_callback and (i + 1) % 1000 == 0:
                    progress_callback(i + 1, len(parts), f"Imported {imported} parts...")

            except Exception as e:
                logger.error(f"Error importing part {part.get('componentCode')}: {e}")
                skipped += 1

        # Update FTS index
        cursor.execute('''
            INSERT INTO components_fts(components_fts, rowid, lcsc, description, mfr_part, manufacturer)
            SELECT 'rebuild', rowid, lcsc, description, mfr_part, manufacturer FROM components
        ''')

        self.conn.commit()
        logger.info(f"Import complete: {imported} parts imported, {skipped} skipped")

    def _determine_library_type(self, part: Dict) -> str:
        """Determine if part is Basic, Extended, or Preferred"""
        # JLCPCB API should provide this, but if not, we infer from assembly type
        assembly_type = part.get('assemblyType', '')

        if 'Basic' in assembly_type or part.get('libraryType') == 'base':
            return 'Basic'
        elif 'Extended' in assembly_type:
            return 'Extended'
        elif 'Prefer' in assembly_type:
            return 'Preferred'
        else:
            return 'Extended'  # Default to Extended

    def search_parts(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        package: Optional[str] = None,
        library_type: Optional[str] = None,
        manufacturer: Optional[str] = None,
        in_stock: bool = True,
        limit: int = 20
    ) -> List[Dict]:
        """
        Search for parts with filters

        Args:
            query: Free-text search (searches description, mfr part, LCSC)
            category: Filter by category name
            package: Filter by package type
            library_type: Filter by "Basic", "Extended", or "Preferred"
            manufacturer: Filter by manufacturer name
            in_stock: Only return parts with stock > 0
            limit: Maximum number of results

        Returns:
            List of matching parts
        """
        cursor = self.conn.cursor()

        # Build query
        sql_parts = ["SELECT * FROM components WHERE 1=1"]
        params = []

        if query:
            # Use FTS for text search
            sql_parts.append('''
                AND lcsc IN (
                    SELECT lcsc FROM components_fts
                    WHERE components_fts MATCH ?
                )
            ''')
            params.append(query)

        if category:
            sql_parts.append("AND category LIKE ?")
            params.append(f"%{category}%")

        if package:
            sql_parts.append("AND package LIKE ?")
            params.append(f"%{package}%")

        if library_type:
            sql_parts.append("AND library_type = ?")
            params.append(library_type)

        if manufacturer:
            sql_parts.append("AND manufacturer LIKE ?")
            params.append(f"%{manufacturer}%")

        if in_stock:
            sql_parts.append("AND stock > 0")

        sql_parts.append("LIMIT ?")
        params.append(limit)

        sql = " ".join(sql_parts)

        try:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    def get_part_info(self, lcsc_number: str) -> Optional[Dict]:
        """
        Get detailed information for specific LCSC part

        Args:
            lcsc_number: LCSC part number (e.g., "C25804")

        Returns:
            Part info dict or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM components WHERE lcsc = ?", (lcsc_number,))
        row = cursor.fetchone()

        if row:
            part = dict(row)
            # Parse price JSON
            if part.get('price_json'):
                try:
                    part['price_breaks'] = json.loads(part['price_json'])
                except:
                    part['price_breaks'] = []
            return part
        return None

    def get_database_stats(self) -> Dict:
        """Get statistics about the database"""
        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) as total FROM components")
        total = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) as basic FROM components WHERE library_type = 'Basic'")
        basic = cursor.fetchone()['basic']

        cursor.execute("SELECT COUNT(*) as extended FROM components WHERE library_type = 'Extended'")
        extended = cursor.fetchone()['extended']

        cursor.execute("SELECT COUNT(*) as in_stock FROM components WHERE stock > 0")
        in_stock = cursor.fetchone()['in_stock']

        return {
            'total_parts': total,
            'basic_parts': basic,
            'extended_parts': extended,
            'in_stock': in_stock,
            'db_path': self.db_path
        }

    def map_package_to_footprint(self, package: str) -> List[str]:
        """
        Map JLCPCB package name to KiCAD footprint(s)

        Args:
            package: JLCPCB package name (e.g., "0603", "SOT-23")

        Returns:
            List of possible KiCAD footprint library refs
        """
        # Load mapping from JSON file or use defaults
        mappings = {
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
            "1206": [
                "Resistor_SMD:R_1206_3216Metric",
                "Capacitor_SMD:C_1206_3216Metric"
            ],
            "SOT-23": [
                "Package_TO_SOT_SMD:SOT-23",
                "Package_TO_SOT_SMD:SOT-23-3"
            ],
            "SOT-23-5": [
                "Package_TO_SOT_SMD:SOT-23-5"
            ],
            "SOT-23-6": [
                "Package_TO_SOT_SMD:SOT-23-6"
            ],
            "SOIC-8": [
                "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
            ],
            "SOIC-16": [
                "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"
            ],
            "QFN-20": [
                "Package_DFN_QFN:QFN-20-1EP_4x4mm_P0.5mm_EP2.5x2.5mm"
            ],
            "QFN-32": [
                "Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm"
            ]
        }

        # Normalize package name
        package_normalized = package.strip().upper()

        for key, footprints in mappings.items():
            if key.upper() in package_normalized:
                return footprints

        return []

    def suggest_alternatives(self, lcsc_number: str, limit: int = 5) -> List[Dict]:
        """
        Find alternative parts similar to the given LCSC number

        Prioritizes: cheaper price, higher stock, Basic library type

        Args:
            lcsc_number: Reference LCSC part number
            limit: Maximum alternatives to return

        Returns:
            List of alternative parts
        """
        part = self.get_part_info(lcsc_number)
        if not part:
            return []

        # Search for parts in same category with same package
        alternatives = self.search_parts(
            category=part['subcategory'],
            package=part['package'],
            in_stock=True,
            limit=limit * 3
        )

        # Filter out the original part
        alternatives = [p for p in alternatives if p['lcsc'] != lcsc_number]

        # Sort by: Basic first, then by price, then by stock
        def sort_key(p):
            is_basic = 1 if p.get('library_type') == 'Basic' else 0
            try:
                prices = json.loads(p.get('price_json', '[]'))
                price = float(prices[0].get('price', 999)) if prices else 999
            except:
                price = 999
            stock = p.get('stock', 0)

            return (-is_basic, price, -stock)

        alternatives.sort(key=sort_key)

        return alternatives[:limit]

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()


if __name__ == '__main__':
    # Test the parts manager
    logging.basicConfig(level=logging.INFO)

    manager = JLCPCBPartsManager()

    # Get stats
    stats = manager.get_database_stats()
    print(f"\nDatabase Statistics:")
    print(f"  Total parts: {stats['total_parts']}")
    print(f"  Basic parts: {stats['basic_parts']}")
    print(f"  Extended parts: {stats['extended_parts']}")
    print(f"  In stock: {stats['in_stock']}")
    print(f"  Database: {stats['db_path']}")

    if stats['total_parts'] > 0:
        print("\nSearching for '10k resistor'...")
        results = manager.search_parts(query="10k resistor", limit=5)
        for part in results:
            print(f"  {part['lcsc']}: {part['mfr_part']} - {part['description']} ({part['library_type']})")
