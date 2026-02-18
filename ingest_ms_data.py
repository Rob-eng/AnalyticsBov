import json
import os
import sys
from app.models import CarSessionLocal, CARProperty
from geoalchemy2.shape import from_shape
from shapely.geometry import shape, MultiPolygon, Polygon
from sqlalchemy.exc import IntegrityError

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
    batch_size = 500
    objects = []
    count = 0
    errors = 0
    seen_ids = set()
    
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
                if not geom.is_valid:
                    errors += 1
                    continue

            # Create object
            obj = CARProperty(
                cod_imovel=props.get('cod_imovel'),
                uf='MS',
                municipio=props.get('municipio'),
                geometry=from_shape(geom, srid=4674)
            )
            objects.append(obj)
            
            if len(objects) >= batch_size:
                session.bulk_save_objects(objects)
                session.commit()
                count += len(objects)
                objects = []
                print(f"  Committed {count}/{total} records... (Errors: {errors})", end='\r')
                
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
            print(f"Error saving last batch: {e}")

    session.close()
    print(f"\n✅ Finished! Total inserted: {count}. Total skipped/errors: {errors}")

if __name__ == "__main__":
    ingest_ms()
