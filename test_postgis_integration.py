import os
# Set DATABASE_URL before importing app modules
os.environ['DATABASE_URL'] = "postgresql://postgres:qTWmSxeojFaYYiJS@db.lnqpouvvciysonwvzidc.supabase.co:5432/postgres"

from app.environmental import query_local_car_database

def test_postgis():
    print("Testing PostGIS Integration (Supabase)...")
    
    # Use a coordinate in Alagoas (AL) which we know is migrated
    # Palmeira dos Índios: -9.499, -36.494
    lat, lon = -9.499, -36.494
    
    print(f"Querying location: {lat}, {lon}...")
    
    result, status = query_local_car_database(lat, lon)
    
    if result:
        print(f"✓ Success! Found property perimeter in Supabase.")
        print(f"  Status: {status}")
        print(f"  Geometry keys: {result.keys()}")
        if 'coordinates' in result:
             print(f"  Coordinates found (truncated): {str(result['coordinates'])[0:100]}...")
    else:
        print("✗ Failed. Property not found in Supabase.")

if __name__ == "__main__":
    # Ensure DATABASE_URL is set
    os.environ['DATABASE_URL'] = "postgresql://postgres:qTWmSxeojFaYYiJS@db.lnqpouvvciysonwvzidc.supabase.co:5432/postgres"
    test_postgis()
