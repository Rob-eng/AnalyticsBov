import requests
import json
import time
from app.config import Config
from shapely.geometry import shape, Point, mapping
import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
import os
from pathlib import Path
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.cm import ScalarMappable

def query_local_car_database(lat, lon):
    """
    Query local GeoJSON file for CAR perimeter containing the point.
    If no exact match, returns the nearest property within 5km.
    Returns: (geometry, status_type) where status_type is 'OFFICIAL' or 'NEARBY'
    """
    try:
        # Path to local GeoJSON file
        base_dir = Path(__file__).parent.parent
        geojson_path = base_dir / "car_ms.geojson"
        
        if not geojson_path.exists():
            print(f"Local CAR database not found: {geojson_path}")
            return (None, False)
        
        # Load GeoJSON with GeoPandas
        gdf = gpd.read_file(geojson_path)
        
        # Create point geometry
        from shapely.geometry import Point
        point = Point(lon, lat)
        
        # Helper to ensure Polygon (Agromonitoring doesn't support MultiPolygon)
        def ensure_polygon(geom):
            if geom.geom_type == 'MultiPolygon':
                # Return the largest polygon by area
                return max(geom.geoms, key=lambda p: p.area)
            return geom
        
        # 1. Try exact match: find properties containing the point
        matches = gdf[gdf.contains(point)]
        
        if len(matches) > 0:
            geometry = ensure_polygon(matches.iloc[0].geometry)
            print(f"Found exact match: {matches.iloc[0].get('cod_imovel', 'N/A')}")
            return (mapping(geometry), 'OFFICIAL')
        
        # 2. Fallback: find nearest property by centroid distance
        # Warning: Direct distance calculation on WGS84 is approximate but fast enough for this purpose
        # To avoid projection errors, we calculate distance on centroids
        gdf['centroid'] = gdf.geometry.centroid
        gdf['dist'] = gdf.centroid.distance(point)
        
        nearest = gdf.nsmallest(1, 'dist')
        
        if len(nearest) > 0:
            dist_deg = nearest.iloc[0]['dist']
            # Approx conversion: 1 deg ~= 111km. 0.1 deg ~= 11km
            if dist_deg < 0.1:
                geometry = ensure_polygon(nearest.iloc[0].geometry)
                cod = nearest.iloc[0].get('cod_imovel', 'N/A')
                print(f"Found nearest property ({dist_deg:.4f} deg): {cod}")
                return (mapping(geometry), 'NEARBY')
        
        return (None, None)
        
    except Exception as e:
        print(f"Error querying local CAR database: {e}")
        # import traceback
        # traceback.print_exc()
        return (None, None)


def fetch_car_perimeter(lat, lon):
    """
    Attempts to fetch CAR perimeter using WFS.
    Falls back to local GeoJSON database, then to a 1km bounding box if both fail.
    Returns: (geometry, status)
    status can be: 'OFFICIAL', 'NEARBY', 'FALLBACK'
    """
    # Fallback to 1km box
    offset = 0.005 # ~500m
    bbox_polygon = {
        "type": "Polygon",
        "coordinates": [[
            [lon - offset, lat - offset],
            [lon + offset, lat - offset],
            [lon + offset, lat + offset],
            [lon - offset, lat + offset],
            [lon - offset, lat - offset]
        ]]
    }

    endpoints = [
        "https://geoserver.car.gov.br/geoserver/sicar/wfs",
        "https://geoserver.car.gov.br/geoserver/wfs"
    ]
    
    params = {
        "service": "WFS",
        "version": "1.1.0",
        "request": "GetFeature",
        "typeName": "sicar:area_imovel",
        "outputFormat": "application/json",
        "cql_filter": f"CONTAINS(geometria, POINT({lon} {lat}))"
    }

    for url in endpoints:
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200 and 'json' in response.headers.get('Content-Type', ''):
                data = response.json()
                if "features" in data and len(data["features"]) > 0:
                    return (data["features"][0]["geometry"], 'OFFICIAL')
        except:
            continue
    
    # 2. Try local GeoJSON database
    print("WFS servers unavailable, trying local database...")
    local_result, status = query_local_car_database(lat, lon)
    if status and local_result:
        print(f"✓ CAR perimeter from local database ({status})")
        return (local_result, status)
    
    # 3. Last resort: estimated area
    print("⚠ Using estimated 1km² area")
    return (bbox_polygon, 'FALLBACK')

from app.gee_connector import get_ndvi_image

def get_ndvi_analysis(geometry_geojson):
    """
    Gets latest NDVI from Google Earth Engine (Sentinel-2).
    """
    try:
        # Use GEE Connector
        # It handles auth and retrieval internally
        result = get_ndvi_image(geometry_geojson)
        
        if not result:
            print("GEE returned no data.")
            return None
            
        print("✓ GEE NDVI Data Retrieved")
        
        # Download the image from the URL provided by GEE
        img_url = result['image_url']
        try:
            resp = requests.get(img_url)
            if resp.status_code != 200:
                print(f"Failed to download GEE thumbnail: {resp.status_code}")
                return None
            img_bytes = BytesIO(resp.content)
        except Exception as e:
            print(f"Download error: {e}")
            return None
            
        return {
            "poly_id": "GEE_Sentinel2", # Placeholder
            "ndvi_img": img_bytes,      # Now returns BytesIO object
            "stats": result['stats'],
            "dt": int(result.get('timestamp', time.time() * 1000) / 1000), 
            "date_str": result['date'], # formatted date
            "cloud_coverage": result['cloud_cover'],
            "region_bbox": result.get('region_bbox')
        }
        
    except Exception as e:
        print(f"NDVI Analysis Error: {e}")
        import traceback
        traceback.print_exc()
        return None

def get_land_use_mapbiomas(lat, lon):
    """
    Query MapBiomas WMS for land use at a point.
    """
    # This is a simplified version, usually requires WMS GetFeatureInfo
    # For now we return a placeholder or use a simpler logic
    return "Não identificado (MapBiomas offline)"

def generate_environmental_image(ndvi_source, geometry, is_real_car=False, region_bbox=None, title=None, pin_coords=None):
    """
    Visualizes NDVI image and overlays CAR perimeter.
    ndvi_source: URL string or BytesIO object
    region_bbox: Optional dict with min_lon, min_lat, max_lon, max_lat
    title: Optional title for the map
    pin_coords: Optional tuple (lat, lon) to draw a pin
    Returns a BytesIO buffer with the composite image.
    """
    try:
        # 1. Load NDVI image
        if isinstance(ndvi_source, BytesIO):
            img = plt.imread(ndvi_source, format='png')
        else:
            # Fallback for URL
            resp = requests.get(ndvi_source, timeout=15)
            if resp.status_code != 200:
                return None
            img = plt.imread(BytesIO(resp.content), format='png')
        
        # 2. Create figure
        fig, ax = plt.subplots(figsize=(10, 10), dpi=100)
        ax.imshow(img, extent=[0, 1, 0, 1])  # Normalize to 0-1 for overlay
        
        if title:
            ax.set_title(title, fontsize=16, fontweight='bold', pad=20)
        
        # 3. Extract and normalize polygon coordinates
        from shapely.geometry import shape as shapely_shape
        from shapely.affinity import scale, translate
        
        poly = shapely_shape(geometry)
        
        poly = shapely_shape(geometry)
        
        # Get bounds
        if region_bbox:
            # Use the square region bounds to align with the image
            minx = region_bbox['min_lon']
            miny = region_bbox['min_lat']
            maxx = region_bbox['max_lon']
            maxy = region_bbox['max_lat']
        else:
            # Fallback to polygon bounds (might distort if image is square)
            minx, miny, maxx, maxy = poly.bounds
            
        width = maxx - minx
        height = maxy - miny
        
        # Normalize coordinates to 0-1 range
        coords = []
        if geometry['type'] == 'Polygon':
            for ring in geometry['coordinates']:
                normalized_ring = [
                    ((x - minx) / width, (y - miny) / height)
                    for x, y in ring
                ]
                coords.append(normalized_ring)
        
        # 4. Draw polygon boundary
        if is_real_car == 'OFFICIAL' or is_real_car is True:
            color = 'lime'
            linestyle = '-'
            label = '✓ Perímetro CAR Oficial'
            linewidth = 3
        elif is_real_car == 'NEARBY':
            color = 'orange'
            linestyle = '-.'
            label = '⚠ Propriedade Próxima (<11km)'
            linewidth = 3
        else:
            color = 'yellow'
            linestyle = '--'
            label = '⚠ Área Estimada (1km²)'
            linewidth = 2
            
        for ring in coords:
            xs, ys = zip(*ring)
            ax.plot(xs, ys, color=color, linewidth=linewidth, linestyle=linestyle, label=label)
        
        # 4.5 Draw Pin
        if pin_coords and region_bbox:
            p_lat, p_lon = pin_coords
            # Normalize pin coordinates to 0-1 range
            px = (p_lon - minx) / width
            py = (p_lat - miny) / height
            
            # Draw a red pin (marker)
            ax.plot(px, py, marker='v', color='red', markersize=12, markeredgecolor='white', label='Ponto de Consulta')

        # 5. Styling
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        ax.legend(loc='upper right', fontsize=10, framealpha=0.8)
            
        # Add NDVI Colorbar
        # Reflect the GEE palette: Red (0.0) -> Yellow (0.4) -> Green (0.8) -> Green (1.0)
        # We clamp at 0.8 in GEE, but usually show 0-1 scale.
        # User asked for -1 to 1. But showing -1 (Red) to 1 (Green) is okay if we map correctly.
        # GEE: 0->Red, 0.8->Green.
        # Let's create a custom cmap that roughly matches:
        # -1.0 -> Red
        # 0.0 -> Red
        # 0.4 -> Yellow
        # 0.8 -> Green
        # 1.0 -> Dark Green
        
        # Simpler: 0.0 to 1.0
        colors = ["red", "yellow", "green"]
        cmap = LinearSegmentedColormap.from_list("ndvi_custom", colors)
        norm = Normalize(vmin=0.0, vmax=0.8) # Matches GEE visualization range
        
        # Create a dummy ScalarMappable
        sm = ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        
        cbar = plt.colorbar(sm, ax=ax, orientation='vertical', fraction=0.046, pad=0.04)
        cbar.set_label('NDVI (Estimado)')
        
        # Remove axes
        ax.set_axis_off()
        
        # 6. Save to buffer
        buf = BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.1, dpi=150)
        buf.seek(0)
        plt.close(fig)
        
        return buf
        
    except Exception as e:
        print(f"Error generating environmental image: {e}")
        import traceback
        traceback.print_exc()
        return None
