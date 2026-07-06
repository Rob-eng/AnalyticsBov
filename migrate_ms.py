import os

def run_migration():
    import cleanup_db
    import download_car_data_v2
    import ingest_ms_data
    if os.getenv("RUN_MIGRATION", "true") != "true":
        print("⏭️ Skipping migration (RUN_MIGRATION != true)")
        return

    print("🚀 Starting MS Data Migration...")
    
    # 1. Cleanup
    # We need to bypass input() in cleanup_db.py
    # I'll create a patched cleanup or just call the function directly if possible
    # cleanup_db.cleanup() prints warning.
    # I will modify cleanup_db.py to accept an argument or just call it.
    # Ah, cleanup_db.py has `input()` in `if __name__ == "__main__"`.
    # Importing it runs top-level code? No, only defs.
    # But I need to call `cleanup()`.
    
    print("🧹 Step 1: Cleaning DB (Truncate) - SKIPPED to allow resuming")
    # cleanup_db.cleanup()
    
    # 2. Unzip/Download
    zip_path = "car_ms.zip"
    geojson_path = "car_ms.geojson"

    if os.path.exists(zip_path):
        print(f"📦 Found {zip_path}, extracting...", flush=True)
        import zipfile
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(".")
        print("✅ Extracted car_ms.geojson from zip.", flush=True)

    if os.path.exists(geojson_path) and os.path.getsize(geojson_path) > 1024 * 1024:
        print("⬇️ Step 2: File ready (Skipping Download)", flush=True)
    else:
        print("⬇️ Step 2: Downloading MS Data", flush=True)
        download_car_data_v2.download_car_data_paginated()
    
    # 3. Ingest
    print("📥 Step 3: Ingesting MS Data")
    ingest_ms_data.ingest_ms()
    
    print("✅ Migration Complete!")

if __name__ == "__main__":
    run_migration()
