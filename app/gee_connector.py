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
        # 1. Try Loading from Environment Variable (Production)
        env_creds = os.environ.get('GEE_CREDENTIALS_JSON')
        if env_creds:
            try:
                creds = json.loads(env_creds)
                # Ensure private_key is present
                if 'private_key' not in creds:
                    print("Error: GEE_CREDENTIALS_JSON matches JSON format but missing 'private_key'")
                    return False
                    
                credentials = ee.ServiceAccountCredentials(creds['client_email'], key_data=creds['private_key'])
                ee.Initialize(credentials)
                print("GEE Initialized via Env Var.")
                return True
            except Exception as ex:
                print(f"Error loading env creds: {ex}")
                # Don't return False yet, try file
        
        # 2. Try Loading from File (Development)
        if os.path.exists(key_file):
            with open(key_file) as f:
                creds = json.load(f)
            credentials = ee.ServiceAccountCredentials(creds['client_email'], key_file)
            ee.Initialize(credentials)
            print("GEE Initialized via File.")
            return True
        
        print(f"GEE Credentials not found (Env Var GEE_CREDENTIALS_JSON or file {key_file})")
        return False

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
        # Use UTC to avoid timezone shifts (e.g. showing tomorrow's date)
        date_str = datetime.utcfromtimestamp(date_timestamp / 1000).strftime('%Y-%m-%d')
        print(f"Image Date (UTC): {date_str} (Timestamp: {date_timestamp})")
        
        # 2. Calculate NDVI: (B8 - B4) / (B8 + B4)
        ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
        
        # 3. Calculate Stats
        stats = ndvi.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geom,
            scale=10,
            maxPixels=1e9
        ).getInfo()
        
        ndvi_mean = stats.get('NDVI')
        
        # 4. Generate Thumbnail URL
        # Calculate a square region to avoid distortion when plotting in a square box
        # Get bounds of the buffered geometry
        bounds_poly = geom.buffer(100).bounds()
        coords = bounds_poly.coordinates().get(0).getInfo()
        # coords is list of [x, y]
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)
        
        center_lon = (min_lon + max_lon) / 2
        center_lat = (min_lat + max_lat) / 2
        
        span_lon = max_lon - min_lon
        span_lat = max_lat - min_lat
        max_span = max(span_lon, span_lat)
        
        # Create square bounds (with slight padding)
        half_span = max_span / 2 * 1.1 
        
        square_region = ee.Geometry.Polygon([[
            [center_lon - half_span, center_lat - half_span],
            [center_lon + half_span, center_lat - half_span],
            [center_lon + half_span, center_lat + half_span],
            [center_lon - half_span, center_lat + half_span],
            [center_lon - half_span, center_lat - half_span]
        ]])

        vis_params = {
            'min': 0.0,
            'max': 0.8,
            'palette': ['red', 'yellow', 'green'],
            'dimensions': 512,
            'region': square_region.getInfo(), 
            'format': 'png'
        }
        
        url = ndvi.getThumbURL(vis_params)
        return {
            "poly_id": "GEE_Sentinel2", 
            "ndvi_img": url, # This will be the URL, not BytesIO object as per original function signature
            "image_url": url,
            "stats": {'mean': ndvi_mean},
            "date": date_str,
            "timestamp": date_timestamp, # Return raw millis
            "cloud_cover": cloud_max,
            "region_bbox": {
                "min_lon": center_lon - half_span,
                "min_lat": center_lat - half_span,
                "max_lon": center_lon + half_span,
                "max_lat": center_lat + half_span
            }
        }
        
    except Exception as e:
        print(f"GEE processing error: {e}")
        return None

def get_precipitation_heatmap(lat, lon):
    """
    Generates a regional precipitation heatmap for the last 30 days using GEE.
    Returns: { 'image_url': str, 'region_bbox': dict } or None
    """
    try:
        if not initialize_gee():
            return None

        # 1. Define region: +/- 2 degrees around point (~220km radius)
        # Sufficient to see most of a state like MS
        span = 2.0
        region = ee.Geometry.BBox(lon - span, lat - span, lon + span, lat + span)

        # 2. Get GPM Dataset (30min precipitation)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        # GPM/IMERG V06 LATE Precipitation (Low latency ~14h)
        collection = (ee.ImageCollection('NASA/GPM_L3/IMERG_V06_LATE')
                      .filterBounds(region)
                      .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
                      .select('precipitation'))

        # 3. Aggregate: Sum of precipitation
        # Each image represents 30min, so real total = sum(mm/hr) * 0.5
        total_precip = collection.reduce(ee.Reducer.sum()).multiply(0.5)

        # 4. Generate Thumbnail URL
        # Palette: Light Gray (Dry) to Dark Blue/Purple (Wet)
        vis_params = {
            'min': 1,      # Min 1mm to show color
            'max': 150,    # Max 150mm in 30 days for better sensitivity
            'palette': ['#f0f0f0', '#99ccff', '#3366ff', '#000080', '#4b0082'],
            'dimensions': 600,
            'region': region.getInfo(),
            'format': 'png'
        }

        url = total_precip.getThumbURL(vis_params)
        
        return {
            "image_url": url,
            "region_bbox": {
                "min_lon": lon - span,
                "min_lat": lat - span,
                "max_lon": lon + span,
                "max_lat": lat + span
            }
        }

    except Exception as e:
        print(f"Heatmap error: {e}")
        return None
