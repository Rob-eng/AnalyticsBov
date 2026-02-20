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
    Selects the most recent image that is cloud-free INSIDE the specific polygon.
    Returns: {
        'image_url': str,
        'stats': dict, # {mean: float}
        'date': str,
        'cloud_cover': float
    } or None
    """
    try:
        if not initialize_gee():
             return None

        geom = ee.Geometry(geometry_geojson)
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)  # 3 month search window
        
        # Load collection sorted newest-first
        collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                      .filterBounds(geom)
                      .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
                      .sort('system:time_start', False))  # False = descending (newest first)
        
        count = collection.size().getInfo()
        print(f"Found {count} images in GEE collection.")
        
        if count == 0:
            print("No Sentinel-2 images found in date range.")
            return None

        # --- Per-polygon cloud detection ---
        # SCL band values: 8=Cloud Medium Probability, 9=Cloud High Probability, 10=Thin Cirrus, 3=Cloud Shadow
        CLOUD_SCL_VALUES = [3, 8, 9, 10]
        
        def add_cloud_fraction(img):
            """Add a per-polygon cloud fraction property to each image."""
            scl = img.select('SCL')
            # Create a binary cloud mask: 1 = cloud/shadow, 0 = clear
            cloud_mask = scl.eq(3).Or(scl.eq(8)).Or(scl.eq(9)).Or(scl.eq(10))
            # Compute mean within polygon (= fraction of cloudy pixels)
            cloud_stat = cloud_mask.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=geom,
                scale=20,  # SCL is 20m resolution
                maxPixels=1e8
            )
            cloud_fraction = ee.Number(cloud_stat.get('SCL')).multiply(100)
            return img.set('cloud_fraction_polygon', cloud_fraction)
        
        # Map and filter: keep only images with < 15% cloud IN the polygon
        cloud_checked = collection.map(add_cloud_fraction)
        clear_collection = cloud_checked.filter(ee.Filter.lt('cloud_fraction_polygon', 15))
        
        clear_count = clear_collection.size().getInfo()
        print(f"Images with <15% cloud over polygon: {clear_count}")
        
        if clear_count == 0:
            # Relax threshold to 35% and try again
            print("Relaxing cloud threshold to 35%...")
            clear_collection = cloud_checked.filter(ee.Filter.lt('cloud_fraction_polygon', 35))
            clear_count = clear_collection.size().getInfo()
            if clear_count == 0:
                print("No usable images found even with relaxed threshold.")
                return None
        
        # Pick the MOST RECENT clear image (collection is already sorted newest-first)
        image = clear_collection.first()
        
        # Extract metadata
        date_timestamp = image.get('system:time_start').getInfo()
        cloud_fraction_polygon = image.get('cloud_fraction_polygon').getInfo()
        
        if date_timestamp is None:
            print(f"Error: Image has no time_start.")
            return None
        
        date_str = datetime.utcfromtimestamp(date_timestamp / 1000).strftime('%Y-%m-%d')
        print(f"Selected Image: {date_str} | Cloud in polygon: {cloud_fraction_polygon:.1f}%")
        
        # Calculate NDVI: (B8 - B4) / (B8 + B4)
        # Apply cloud mask before computing NDVI
        scl = image.select('SCL')
        cloud_mask = scl.eq(3).Or(scl.eq(8)).Or(scl.eq(9)).Or(scl.eq(10)).Not()
        masked_image = image.updateMask(cloud_mask)
        
        ndvi = masked_image.normalizedDifference(['B8', 'B4']).rename('NDVI')
        
        # Calculate Stats
        stats = ndvi.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geom,
            scale=10,
            maxPixels=1e9
        ).getInfo()
        
        ndvi_mean = stats.get('NDVI')
        
        # Generate Thumbnail URL
        bounds_poly = geom.buffer(100).bounds()
        coords = bounds_poly.coordinates().get(0).getInfo()
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)
        
        center_lon = (min_lon + max_lon) / 2
        center_lat = (min_lat + max_lat) / 2
        
        span_lon = max_lon - min_lon
        span_lat = max_lat - min_lat
        max_span = max(span_lon, span_lat)
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
            "ndvi_img": url,
            "image_url": url,
            "stats": {'mean': ndvi_mean},
            "date": date_str,
            "timestamp": date_timestamp,
            "cloud_cover": cloud_fraction_polygon,
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
    Generates a Brazil-wide precipitation heatmap for the last 30 days.
    State borders are painted via GEE GAUL dataset.
    A red pin marks the queried point.
    Returns: { 'buffer': BytesIO, 'image_url': str, 'region_bbox': dict } or None
    """
    try:
        if not initialize_gee():
            print("GEE initialization failed for heatmap")
            return None

        print(f"Generating Brazil heatmap for {lat}, {lon}")

        # Brazil bounding box
        BRAZIL_MIN_LON, BRAZIL_MAX_LON = -74.0, -28.6
        BRAZIL_MIN_LAT, BRAZIL_MAX_LAT = -33.8,   5.3
        brazil = ee.Geometry.BBox(BRAZIL_MIN_LON, BRAZIL_MIN_LAT,
                                  BRAZIL_MAX_LON, BRAZIL_MAX_LAT)

        # Date range — last 30 days (UTC)
        end_date   = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
        start_str  = start_date.strftime('%Y-%m-%d')
        end_str    = end_date.strftime('%Y-%m-%d')

        # ── GPM dataset (fallback chain) ──────────────────────────────────
        GPM_ASSETS = [
            'NASA/GPM_L3/IMERG_V07',
            'NASA/GPM_L3/IMERG_V06',
            'NASA/GPM_L3/IMERG_V06_LATE',
        ]
        collection = None
        count = 0
        for asset in GPM_ASSETS:
            try:
                coll = (ee.ImageCollection(asset)
                        .filterBounds(brazil)
                        .filterDate(start_str, end_str)
                        .select('precipitation'))
                count = int(coll.size().getInfo())
                if count > 0:
                    print(f"Using GPM asset: {asset} ({count} images)")
                    collection = coll
                    break
                print(f"Asset {asset}: 0 images, trying next...")
            except Exception as ae:
                print(f"Asset {asset} error: {ae}, trying next...")

        if collection is None or count == 0:
            print("Heatmap: widening to 60-day window...")
            start_date = end_date - timedelta(days=60)
            try:
                collection = (ee.ImageCollection('NASA/GPM_L3/IMERG_V07')
                              .filterBounds(brazil)
                              .filterDate(start_date.strftime('%Y-%m-%d'), end_str)
                              .select('precipitation'))
                count = int(collection.size().getInfo())
            except Exception:
                count = 0

        if count == 0:
            print("Heatmap collection still empty after fallback.")
            return None

        print(f"Heatmap collection has {count} images.")

        # ── Aggregate: sum × 0.5 to convert mm/hr × 30min → mm ──────────
        total_precip = collection.reduce(ee.Reducer.sum()).multiply(0.5)

        # ── Visualise heatmap ─────────────────────────────────────────────
        heatmap_vis = total_precip.visualize(
            min=1, max=300,
            palette=['#f0f0f0', '#aad4f5', '#3399ff', '#003580', '#2d0055']
        )

        # ── Paint Brazil state borders (white, 1px) ───────────────────────
        try:
            brazil_states = (ee.FeatureCollection('FAO/GAUL/2015/level1')
                             .filter(ee.Filter.eq('ADM0_NAME', 'Brazil')))
            state_borders = ee.Image().paint(
                featureCollection=brazil_states, color=1, width=1
            )
            white = ee.Image.constant([255, 255, 255]).byte()
            composite = heatmap_vis.where(state_borders, white)
        except Exception as sb_err:
            print(f"  State borders failed, using plain heatmap: {sb_err}")
            composite = heatmap_vis

        # ── Get thumbnail URL ─────────────────────────────────────────────
        url = composite.getThumbURL({
            'dimensions': 900,
            'region': brazil.getInfo(),
            'format': 'png',
        })
        print(f"Heatmap URL: {url}")

        # ── Download image ────────────────────────────────────────────────
        import requests as _req
        resp = _req.get(url, timeout=60)
        if resp.status_code != 200:
            print(f"Heatmap download failed: {resp.status_code}")
            return {'image_url': url, 'region_bbox': {
                'min_lon': BRAZIL_MIN_LON, 'min_lat': BRAZIL_MIN_LAT,
                'max_lon': BRAZIL_MAX_LON, 'max_lat': BRAZIL_MAX_LAT
            }}

        # ── Add red pin for queried point ─────────────────────────────────
        from PIL import Image as PILImage, ImageDraw
        import io as _io

        img = PILImage.open(_io.BytesIO(resp.content)).convert('RGBA')
        w, h = img.size

        px = int((lon - BRAZIL_MIN_LON) / (BRAZIL_MAX_LON - BRAZIL_MIN_LON) * w)
        py = int((BRAZIL_MAX_LAT - lat) / (BRAZIL_MAX_LAT - BRAZIL_MIN_LAT) * h)
        px = max(4, min(w - 4, px))
        py = max(4, min(h - 4, py))

        draw = ImageDraw.Draw(img)
        r = 8
        draw.ellipse([px - r, py - r, px + r, py + r],
                     fill=(220, 30, 30, 230), outline=(255, 255, 255, 255))
        draw.ellipse([px - 3, py - 3, px + 3, py + 3],
                     fill=(255, 255, 255, 230))

        buf = _io.BytesIO()
        img.convert('RGB').save(buf, format='PNG')
        buf.seek(0)

        return {
            'buffer': buf,
            'image_url': url,
            'region_bbox': {
                'min_lon': BRAZIL_MIN_LON, 'min_lat': BRAZIL_MIN_LAT,
                'max_lon': BRAZIL_MAX_LON, 'max_lat': BRAZIL_MAX_LAT,
            }
        }

    except Exception as e:
        print(f"Heatmap error: {e}")
        import traceback
        print(traceback.format_exc())
        return None
