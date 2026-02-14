import ee
import os
import json
from datetime import datetime, timedelta

def initialize_gee(key_file="service_account.json"):
    """
    Initializes Google Earth Engine with Service Account credentials.
    key_file: Path to the JSON key file.
    """
    try:
        # Load credentials from file or env
        if not os.path.exists(key_file):
            print(f"GEE Credentials file not found: {key_file}")
            return False
            
        # Use the high-level authentication from earthengine-api
        # For service accounts, we can use ServiceAccountCredentials
        # But verify valid JSON first
        with open(key_file) as f:
            creds = json.load(f)
            
        credentials = ee.ServiceAccountCredentials(creds['client_email'], key_file)
        ee.Initialize(credentials)
        print("GEE Initialized successfully.")
        return True

    except Exception as e:
        print(f"GEE Initialization Error: {e}")
        return False

def get_ndvi_image(geometry_geojson):
    """
    Generates an NDVI image URL and stats from Sentinel-2 for the given geometry.
    Returns: {
        'image_url': str,
        'stats': dict, # {mean: float}
        'date': str,
        'cloud_cover': float
    } or None
    """
    try:
        # Lazy initialization
        # We can just try to initialize properly
        if not initialize_gee():
             return None

        # Convert GeoJSON to EE Geometry
        # EE expects GeoJSON geometry object (type, coordinates)
        geom = ee.Geometry(geometry_geojson)
        
        # 1. Filter Sentinel-2 Collection (Level-2A Surface Reflectance)
        # 1. Filter Sentinel-2 Collection (Level-2A Surface Reflectance)
        # Use Harmonized collection as S2_SR is deprecated
        end_date = datetime.now()
        start_date = end_date - timedelta(days=180) # 6 months window
        
        collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                      .filterBounds(geom)
                      .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
                      .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 50))
                      .sort('CLOUDY_PIXEL_PERCENTAGE'))
        
        count = collection.size().getInfo()
        print(f"Found {count} images in GEE collection.")
        
        if count == 0:
            print("No Sentinel-2 images found in date range.")
            return None
            
        # Get best image (least cloudy)
        image = collection.first()
        
        # Extract metadata
        # System properties like time_start are not always in toDictionary()
        date_timestamp = image.get('system:time_start').getInfo()
        cloud_max = image.get('CLOUDY_PIXEL_PERCENTAGE').getInfo()
        
        if date_timestamp is None:
            # Fallback for debugging
            print(f"Error: Image has no time_start. Keys: {image.propertyNames().getInfo()}")
            return None
        date_str = datetime.fromtimestamp(date_timestamp / 1000).strftime('%Y-%m-%d')
        
        # 2. Calculate NDVI: (B8 - B4) / (B8 + B4)
        ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
        
        # 3. Calculate Stats (Mean NDVI within geometry)
        stats = ndvi.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geom,
            scale=10,
            maxPixels=1e9
        ).getInfo()
        
        ndvi_mean = stats.get('NDVI')
        
        # 4. Generate Thumbnail URL
        # Visualization params
        vis_params = {
            'min': 0.0,
            'max': 0.8,
            'palette': ['red', 'yellow', 'green'],
            'dimensions': 512,
            'region': geom.buffer(100).bounds().getInfo(), # Buffer context
            'format': 'png'
        }
        
        url = ndvi.getThumbURL(vis_params)
        
        return {
            'image_url': url,
            'stats': {'mean': ndvi_mean},
            'date': date_str,
            'cloud_cover': cloud_max
        }
        
    except Exception as e:
        print(f"GEE processing error: {e}")
        # import traceback
        # traceback.print_exc()
        return None
