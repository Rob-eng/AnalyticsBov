import json
import os
import sys
from app.models import CarSessionLocal, CARProperty
from geoalchemy2.shape import from_shape
from shapely.geometry import shape, MultiPolygon, Polygon
from sqlalchemy.exc import IntegrityError, InternalError, DataError

def ingest_ms():
    filepath = "car_ms.geojson"
    if not os.path.exists(filepath):
        print(f"❌ File {filepath} not found. Run download script first.")
        return

    print(f"Loading {filepath}...")
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Failed to load JSON: {e}")
        return

    features = data.get('features', [])
    total = len(features)
    print(f"Found {total} features. Starting ingestion...")

    session = CarSessionLocal()
    batch_size = 100 # Reduced from 500 for stability
    objects = []
    count = 0
    errors = 0
    
    print("🔄 Fetching existing records to resume...", flush=True)
    try:
        existing = session.query(CARProperty.cod_imovel).filter(CARProperty.uf == 'MS').all()
        seen_ids = {r[0] for r in existing}
        print(f"✅ Found {len(seen_ids)} existing records. Resuming...", flush=True)
    except Exception as e:
        print(f"⚠️ Could not fetch existing records: {e}. Starting fresh.", flush=True)
        seen_ids = set()

    
    # Pre-fetch existing IDs to avoid unique constraint violations if re-running
    # Actually, better to trust the database constraints and handle errors
    
    for i, feat in enumerate(features):
        try:
            props = feat.get('properties', {})
            cod = props.get('cod_imovel')
            
            if not cod or cod in seen_ids:
                continue
            seen_ids.add(cod)

            geom_data = feat.get('geometry')
            
            if not geom_data:
                continue

            geom = shape(geom_data)
            
            # Force MultiPolygon if it's a Polygon
            if isinstance(geom, Polygon):
                geom = MultiPolygon([geom])
            
            # Skip invalid geometries
            if not geom.is_valid:
                # Try to fix
                geom = geom.buffer(0)
                # buffer(0) might return Polygon, so re-force MultiPolygon
                if isinstance(geom, Polygon):
                    geom = MultiPolygon([geom])
                
                if not geom.is_valid:
                    errors += 1
                    continue

            # Final safety check
            if isinstance(geom, Polygon):
                geom = MultiPolygon([geom])

            # Create object
            obj = CARProperty(
                cod_imovel=props.get('cod_imovel'),
                uf='MS',
                municipio=props.get('municipio'),
                geometry=from_shape(geom, srid=4674)
            )
            objects.append(obj)
            
            if len(objects) >= batch_size:
                try:
                    session.bulk_save_objects(objects)
                    session.commit()
                    count += len(objects)
                    print(f"  Committed {count}/{total} records... (Errors: {errors})", end='\r')
                except Exception as e:
                    session.rollback()
                    # print(f"Batch failed: {e}. Retrying individually...")
                    # Fallback: Insert one by one
                    for item in objects:
                        try:
                            session.add(item)
                            session.commit()
                            count += 1
                        except Exception as inner_e:
                            session.rollback()
                            errors += 1
                finally:
                    objects = [] # Clear batch regardless of success/failure
                
        except Exception as e:
            # print(f"Skipping record: {e}")
            errors += 1
            continue

    # Commit remaining
    if objects:
        try:
            session.bulk_save_objects(objects)
            session.commit()
            count += len(objects)
        except Exception as e:
            session.rollback()
            for item in objects:
                try:
                    session.add(item)
                    session.commit()
                    count += 1
                except Exception as inner_e:
                    session.rollback()
                    errors += 1

    session.close()
    print(f"\n✅ Finished! Total inserted: {count}. Total skipped/errors: {errors}")

if __name__ == "__main__":
    ingest_ms()
