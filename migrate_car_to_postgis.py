import os
import geopandas as gpd
import pandas as pd
from sqlalchemy import create_engine
from app.models import SessionLocal, CARProperty, engine
import time
import json
from shapely.geometry import shape

def migrate_car_data():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    geojson_files = [f for f in os.listdir(base_dir) if f.startswith("car_") and f.endswith(".geojson")]
    
    if not geojson_files:
        print("No car_*.geojson files found.")
        return

    # Sort files to ensure predictable order
    geojson_files.sort()
    
    db_url = os.environ.get('CAR_DATABASE_URL') or os.environ.get('DATABASE_URL')
    if not db_url:
        print("CAR_DATABASE_URL or DATABASE_URL environment variable is missing.")
        return

    # PostGIS specific engine
    pg_engine = create_engine(db_url)
    
    for filename in geojson_files:
        uf = filename.split('_')[1].split('.')[0].upper()
        filepath = os.path.join(base_dir, filename)
        
        print(f"Processing {filename} (UF: {uf})...")
        
        try:
            # Load GeoJSON
            gdf = gpd.read_file(filepath)
            print(f"  Loaded {len(gdf)} features.")
            
            # Prepare data for database
            # Ensure columns match CARProperty table
            # cod_imovel, uf, municipio, geometry
            
            # 1. Add/rename columns
            if 'cod_imovel' not in gdf.columns and 'id' in gdf.columns:
                gdf['cod_imovel'] = gdf['id']
            
            gdf['uf'] = uf
            
            if 'municipio' not in gdf.columns:
                gdf['municipio'] = 'N/A'
                
            # Keep only necessary columns
            columns_to_keep = ['cod_imovel', 'uf', 'municipio', 'geometry']
            for col in columns_to_keep:
                if col not in gdf.columns:
                    gdf[col] = None
            
            gdf = gdf[columns_to_keep]
            
            # 2. Ensure geometry is MultiPolygon and SRID is 4674
            if gdf.crs is None:
                gdf.set_crs(epsg=4674, inplace=True)
            elif gdf.crs.to_epsg() != 4674:
                print(f"  Reprojecting from {gdf.crs.to_epsg()} to 4674...")
                gdf = gdf.to_crs(epsg=4674)
            
            # Convert Geometry to MultiPolygon if necessary (Supabase prefers consistency)
            from shapely.geometry import MultiPolygon, Polygon
            def to_multipolygon(geom):
                if isinstance(geom, Polygon):
                    return MultiPolygon([geom])
                return geom
            
            gdf['geometry'] = gdf['geometry'].apply(to_multipolygon)

            # 3. Batch upload
            chunk_size = 5000
            total = len(gdf)
            
            print(f"  Uploading {total} records to PostGIS...")
            
            for i in range(0, total, chunk_size):
                chunk = gdf.iloc[i:i+chunk_size]
                
                # We use GeoAlchemy2 integration if available, or just GeoPandas to_postgis
                try:
                    chunk.to_postgis(
                        'car_properties', 
                        pg_engine, 
                        if_exists='append', 
                        index=False,
                        schema='public'
                    )
                    print(f"    Uploaded {i + len(chunk)}/{total}...")
                except Exception as e:
                    print(f"    Error in chunk {i}: {e}. Retrying individually...")
                    # Fallback row by row for the failing chunk to skip duplicates
                    # (cod_imovel is unique)
                    for _, row in chunk.iterrows():
                        try:
                            # Simple row insert using pandas for simplicity in error handling
                            row_gdf = gpd.GeoDataFrame([row], crs=gdf.crs)
                            row_gdf.to_postgis('car_properties', pg_engine, if_exists='append', index=False)
                        except:
                            pass # Skip duplicates or errors

            print(f"✓ Completed {filename}")
            
        except Exception as e:
            print(f"Failed to process {filename}: {e}")
            continue

if __name__ == "__main__":
    migrate_car_data()
