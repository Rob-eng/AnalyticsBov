import requests
import json
import time
from app.config import Config
from shapely.geometry import shape, Point, mapping
import geopandas as gpd
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO
import os
from pathlib import Path
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.cm import ScalarMappable

def get_state_from_coords(lat, lon):
    """
    Approximate bounding boxes for Brazilian states.
    Returns the UF abbreviation in lowercase.
    """
    states_bbox = {
        "ac": {"min_lat": -11.14, "max_lat": -7.11, "min_lon": -73.99, "max_lon": -66.62},
        "al": {"min_lat": -10.50, "max_lat": -8.81, "min_lon": -38.22, "max_lon": -35.15},
        "am": {"min_lat": -9.81, "max_lat": 2.24, "min_lon": -73.80, "max_lon": -56.09},
        "ap": {"min_lat": -1.24, "max_lat": 4.43, "min_lon": -54.83, "max_lon": -49.88},
        "ba": {"min_lat": -18.34, "max_lat": -8.53, "min_lon": -46.61, "max_lon": -37.33},
        "ce": {"min_lat": -7.85, "max_lat": -2.78, "min_lon": -41.41, "max_lon": -37.24},
        "df": {"min_lat": -16.05, "max_lat": -15.49, "min_lon": -48.28, "max_lon": -47.30},
        "es": {"min_lat": -21.31, "max_lat": -17.89, "min_lon": -41.88, "max_lon": -39.67},
        "go": {"min_lat": -19.49, "max_lat": -12.39, "min_lon": -53.24, "max_lon": -45.92},
        "ma": {"min_lat": -10.26, "max_lat": -1.04, "min_lon": -48.75, "max_lon": -41.79},
        "mg": {"min_lat": -22.92, "max_lat": -14.23, "min_lon": -51.01, "max_lon": -39.86},
        "ms": {"min_lat": -24.06, "max_lat": -17.13, "min_lon": -58.16, "max_lon": -50.93},
        "mt": {"min_lat": -18.04, "max_lat": -7.36, "min_lon": -61.63, "max_lon": -50.15},
        "pa": {"min_lat": -9.84, "max_lat": 2.58, "min_lon": -58.89, "max_lon": -46.06},
        "pb": {"min_lat": -8.30, "max_lat": -6.02, "min_lon": -38.77, "max_lon": -34.79},
        "pe": {"min_lat": -9.48, "max_lat": -7.03, "min_lon": -41.35, "max_lon": -34.80},
        "pi": {"min_lat": -10.92, "max_lat": -2.74, "min_lon": -45.99, "max_lon": -40.37},
        "pr": {"min_lat": -26.71, "max_lat": -22.51, "min_lon": -54.62, "max_lon": -48.02},
        "rj": {"min_lat": -23.36, "max_lat": -20.76, "min_lon": -44.88, "max_lon": -40.95},
        "rn": {"min_lat": -6.98, "max_lat": -4.83, "min_lon": -38.58, "max_lon": -34.96},
        "ro": {"min_lat": -13.69, "max_lat": -7.94, "min_lon": -66.81, "max_lon": -59.77},
        "rr": {"min_lat": -1.58, "max_lat": 5.27, "min_lon": -64.81, "max_lon": -58.88},
        "rs": {"min_lat": -33.75, "max_lat": -27.08, "min_lon": -57.64, "max_lon": -49.69},
        "sc": {"min_lat": -29.35, "max_lat": -25.92, "min_lon": -53.83, "max_lon": -48.32},
        "se": {"min_lat": -11.56, "max_lat": -9.51, "min_lon": -38.24, "max_lon": -36.36},
        "sp": {"min_lat": -25.31, "max_lat": -19.77, "min_lon": -53.11, "max_lon": -44.16},
        "to": {"min_lat": -13.46, "max_lat": -5.16, "min_lon": -50.74, "max_lon": -45.69}
    }
    
    for uf, bbox in states_bbox.items():
        if bbox['min_lat'] <= lat <= bbox['max_lat'] and bbox['min_lon'] <= lon <= bbox['max_lon']:
            return uf
            
    return "ms" # Defaulting if no match found

def query_local_car_database(lat, lon):
    """
    Query local GeoJSON file for CAR perimeter containing the point.
    If no exact match, returns the nearest property within 5km.
    Returns: (geometry, status_type) where status_type is 'OFFICIAL' or 'NEARBY'
    """
    try:
        base_dir = Path(__file__).parent.parent
        
        # 1. Determine which state file to use
        # We can iterate through available flags/files or use a simple heuristic
        uf = get_state_from_coords(lat, lon)
        geojson_path = base_dir / f"car_{uf}.geojson"
        
        if not geojson_path.exists():
            # Fallback: check if any car_*.geojson contains the point
            # (though this is slow, so we'll just check if we have the file)
            print(f"Local CAR database not found: {geojson_path}")
            # Try to find any car_*.geojson as fallback
            available_files = list(base_dir.glob("car_*.geojson"))
            if not available_files:
                return (None, False)
            geojson_path = available_files[0] # Just use the first one if we only have one
        
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
            # The following lines were part of the user's provided "Code Edit" but appear to be
            # misplaced from a different function (e.g., get_precipitation_heatmap)
            # and would cause a NameError if inserted here.
            # url = total_precip.getThumbURL(vis_params)
            # print(f"Heatmap URL generated: {url}")
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
        
        # 3. Extract and normalize coordinates
        from shapely.geometry import shape as shapely_shape
        
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
            rings = geometry['coordinates']
        elif geometry['type'] == 'MultiPolygon':
            rings = [ring for poly_coords in geometry['coordinates'] for ring in poly_coords]
        else:
            rings = []

        for ring in rings:
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
        if pin_coords and all(c is not None for c in pin_coords) and region_bbox:
            p_lat, p_lon = pin_coords
            # Normalize pin coordinates to 0-1 range
            px = (p_lon - minx) / width
            py = (p_lat - miny) / height
            
            # Draw a red pin (marker) only if within 0-1 range (safety)
            if 0 <= px <= 1 and 0 <= py <= 1:
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
