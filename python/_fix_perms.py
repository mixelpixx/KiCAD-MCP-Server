import os, sqlite3, sys

data_dir = os.path.join(os.path.expanduser("~"), ".kicad-mcp", "data")
print(f"Data dir: {data_dir}")

# Create the directory
os.makedirs(data_dir, exist_ok=True)
print(f"Directory exists: {os.path.isdir(data_dir)}")

# Try creating the db
db_path = os.path.join(data_dir, "jlcpcb_parts.db")
print(f"DB path: {db_path}")

try:
    conn = sqlite3.connect(db_path)
    print("SQLite connect SUCCESS")
    conn.close()
except Exception as e:
    print(f"SQLite connect FAILED: {e}")
    # Try with a simpler path
    try:
        alt_path = os.path.join(os.environ.get("TEMP", "C:\\temp"), "jlcpcb_parts.db")
        print(f"Trying alternate path: {alt_path}")
        conn = sqlite3.connect(alt_path)
        print("Alt path SUCCESS")
        conn.close()
    except Exception as e2:
        print(f"Alt path FAILED: {e2}")
    sys.exit(1)

print("All good!")
