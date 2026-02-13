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
                    return data["features"][0]["geometry"]
        except:
            continue
            
    return bbox_polygon

def get_ndvi_analysis(geometry_geojson):
    """
    Registers polygon in Agromonitoring and gets latest NDVI.
    """
    api_key = Config.AGROMONITORING_API_KEY
    if not api_key:
        return None
        
    # 1. Create Polygon in Agromonitoring
    poly_url = f"http://api.agromonitoring.com/agro/1.0/polygons?appid={api_key}"
    poly_data = {
        "name": f"Area_{int(time.time())}",
        "geo_json": {
            "type": "Feature",
            "properties": {},
            "geometry": geometry_geojson
        }
    }
    
    try:
        res = requests.post(poly_url, json=poly_data)
        if res.status_code not in [201, 200]:
            print(f"Agro Poly Error: {res.text}")
            return None
        poly_id = res.json()["id"]
        
        # 2. Get Search (Satellite Images)
        # Search for last 30 days
        end = int(time.time())
        start = end - (30 * 24 * 3600)
        search_url = f"http://api.agromonitoring.com/agro/1.0/satellite/get?polyid={poly_id}&start={start}&end={end}&appid={api_key}"
        
        sres = requests.get(search_url)
        if sres.status_code != 200:
            return None
            
        images = sres.json()
        if not images:
            return None
            
        # Get latest image with NDVI
        latest = images[-1]
        ndvi_url = latest.get("stats", {}).get("ndvi") # This is direct stats
        ndvi_img_url = latest.get("ndvi") # Direct link to PNG
        
        return {
            "poly_id": poly_id,
            "ndvi_img": ndvi_img_url,
            "stats": latest.get("stats"),
            "dt": latest.get("dt")
        }
    except Exception as e:
        print(f"NDVI Analysis Error: {e}")
        return None

def get_land_use_mapbiomas(lat, lon):
    """
    Query MapBiomas WMS for land use at a point.
    """
    # This is a simplified version, usually requires WMS GetFeatureInfo
    # For now we return a placeholder or use a simpler logic
    return "Não identificado (MapBiomas offline)"

def generate_environmental_image(ndvi_url, geometry):
    """
    Downloads NDVI image and overlays perimeter.
    """
    try:
        resp = requests.get(ndvi_url)
        img = plt.imread(BytesIO(resp.content), format='png')
        
        fig, ax = plt.subplots(figsize=(8, 8))
        ax.imshow(img)
        ax.axis('off')
        
        buf = BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0)
        buf.seek(0)
        plt.close(fig)
        return buf
    except:
        return None
