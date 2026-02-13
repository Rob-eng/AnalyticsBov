import requests
import json
import time
from app.config import Config
from shapely.geometry import shape, Point, mapping
import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO

def fetch_car_perimeter(lat, lon):
    """
    Attempts to fetch CAR perimeter using WFS.
    Falls back to a 1km bounding box if WFS fails.
    Returns: (geometry, is_real_car)
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
                    return (data["features"][0]["geometry"], True)
        except:
            continue
            
    return (bbox_polygon, False)

def get_ndvi_analysis(geometry_geojson):
    """
    Registers polygon in Agromonitoring and gets latest NDVI.
    """
    api_key = Config.AGROMONITORING_API_KEY
    if not api_key:
        return None
        
    # 1. Create Polygon in Agromonitoring (allow duplicates)
    poly_url = f"http://api.agromonitoring.com/agro/1.0/polygons?duplicated=true&appid={api_key}"
    poly_data = {
        "name": f"Area_{int(time.time())}",
        "geo_json": {
            "type": "Feature",
            "properties": {},
            "geometry": geometry_geojson
        }
    }
    
    try:
        res = requests.post(poly_url, json=poly_data, timeout=10)
        if res.status_code not in [201, 200]:
            print(f"Agro Poly Error: {res.text}")
            return None
        poly_id = res.json()["id"]
        
        # 2. Get historical satellite images
        # Use the image search endpoint for historical data
        end = int(time.time())
        start = end - (60 * 24 * 3600)  # Last 60 days
        
        search_url = f"http://api.agromonitoring.com/agro/1.0/image/search?start={start}&end={end}&polyid={poly_id}&appid={api_key}"
        
        sres = requests.get(search_url, timeout=10)
        if sres.status_code != 200:
            print(f"Satellite search error: {sres.text}")
            return None
            
        images = sres.json()
        if not images or len(images) == 0:
            print("No satellite images available for this area yet")
            return None
        
        # Filter for images with low cloud coverage
        clear_images = [img for img in images if img.get('cl', 100) < 30]
        if not clear_images:
            clear_images = images  # Fallback to any image
            
        # Get the most recent image
        latest = sorted(clear_images, key=lambda x: x.get('dt', 0))[-1]
        
        # Get NDVI tile URL
        tile = latest.get('tile')
        if not tile:
            print("No tile data in image")
            return None
            
        # Construct NDVI image URL
        ndvi_img_url = latest.get('image', {}).get('ndvi')
        
        # Get stats if available
        stats_url = latest.get('stats', {}).get('ndvi')
        stats_data = None
        if stats_url:
            try:
                stats_res = requests.get(stats_url, timeout=10)
                if stats_res.status_code == 200:
                    stats_data = stats_res.json()
            except:
                pass
        
        return {
            "poly_id": poly_id,
            "ndvi_img": ndvi_img_url,
            "stats": stats_data,
            "dt": latest.get("dt"),
            "cloud_coverage": latest.get("cl", 0)
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

def generate_environmental_image(ndvi_url, geometry, is_real_car=False):
    """
    Downloads NDVI image and overlays CAR perimeter.
    Returns a BytesIO buffer with the composite image.
    """
    try:
        # 1. Download NDVI image
        resp = requests.get(ndvi_url, timeout=15)
        if resp.status_code != 200:
            return None
            
        img = plt.imread(BytesIO(resp.content), format='png')
        
        # 2. Create figure
        fig, ax = plt.subplots(figsize=(10, 10), dpi=100)
        ax.imshow(img, extent=[0, 1, 0, 1])  # Normalize to 0-1 for overlay
        
        # 3. Extract and normalize polygon coordinates
        from shapely.geometry import shape as shapely_shape
        from shapely.affinity import scale, translate
        
        poly = shapely_shape(geometry)
        
        # Get bounds
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
        if is_real_car:
            color = 'lime'
            linestyle = '-'
            label = '✓ Perímetro CAR Oficial'
            linewidth = 3
        else:
            color = 'yellow'
            linestyle = '--'
            label = '⚠ Área Estimada (1km²)'
            linewidth = 2
            
        for ring in coords:
            xs, ys = zip(*ring)
            ax.plot(xs, ys, color=color, linewidth=linewidth, linestyle=linestyle, label=label)
        
        # 5. Styling
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        ax.legend(loc='upper right', fontsize=10, framealpha=0.8)
        
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
