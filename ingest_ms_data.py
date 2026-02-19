import ijson
import os
import sys
import time
from app.models import CarSessionLocal, CARProperty
from geoalchemy2.shape import from_shape
from shapely.geometry import shape, MultiPolygon, Polygon
from sqlalchemy.exc import IntegrityError, InternalError, DataError

def ingest_ms():
    filepath = "car_ms.geojson"
    if not os.path.exists(filepath):
        print(f"❌ File {filepath} not found. Run download script first.")
        return

    print(f"Streaming {filepath} with ijson...")
    
    # We can't easily count total features with ijson without iterating once.
    # So we'll just track count.

    session = CarSessionLocal()
    batch_size = 100 # Keep small for stability
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

    try:
        with open(filepath, 'rb') as f:
            # Stream features one by one
            for i, feat in enumerate(ijson.items(f, 'features.item')):
                # Yield CPU every 1000 items to keep Health Checks alive
                if i % 1000 == 0:
                    time.sleep(0.02)
                    
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
                            time.sleep(0.1) # Yield after I/O
                            count += len(objects)
                            print(f"  Committed +{len(objects)} records (Total: {count})...", end='\r')
                        except Exception as e:
                            session.rollback()
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
    except Exception as e:
        print(f"❌ Failed to stream JSON: {e}")
        return

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
    print(f"\n✅ Finished! Ingested in this run: {count}. Total skipped/errors: {errors}")

if __name__ == "__main__":
    ingest_ms()
