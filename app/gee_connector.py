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
    Brazil-wide precipitation heatmap for the last 30 days.
    State borders are overlaid via geopandas + matplotlib after
    downloading the GEE thumbnail. A red pin marks the queried point.
    Returns: { 'buffer': BytesIO, 'image_url': str, 'region_bbox': dict } or None
    """
    import io as _io
    import requests as _req

    try:
        if not initialize_gee():
            print("GEE initialization failed for heatmap")
            return None

        print(f"Generating Brazil heatmap for {lat}, {lon}")

        # Brazil bounding box
        BMIN_LON, BMAX_LON = -74.0, -28.6
        BMIN_LAT, BMAX_LAT = -33.8,   5.3
        brazil = ee.Geometry.BBox(BMIN_LON, BMIN_LAT, BMAX_LON, BMAX_LAT)

        # Date range (UTC)
        end_date   = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
        start_str  = start_date.strftime('%Y-%m-%d')
        end_str    = end_date.strftime('%Y-%m-%d')

        # GPM dataset fallback chain
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
            print("Widening to 60-day window...")
            start_60 = end_date - timedelta(days=60)
            for asset in GPM_ASSETS:
                try:
                    coll = (ee.ImageCollection(asset)
                            .filterBounds(brazil)
                            .filterDate(start_60.strftime('%Y-%m-%d'), end_str)
                            .select('precipitation'))
                    count = int(coll.size().getInfo())
                    if count > 0:
                        collection = coll
                        break
                except Exception:
                    pass

        if collection is None or count == 0:
            print("Heatmap: no data found.")
            return None

        print(f"Heatmap: {count} images found.")

        # Aggregate: mm/hr × 30min intervals → total mm
        total_precip = collection.reduce(ee.Reducer.sum()).multiply(0.5)

        # Simple thumbnail — plain heatmap, no GEE-side compositing
        url = total_precip.getThumbURL({
            'min': 1,
            'max': 300,
            'palette': ['f0f0f0', 'aad4f5', '3399ff', '003580', '2d0055'],
            'dimensions': 900,
            'region': brazil.getInfo(),
            'format': 'png',
        })
        print(f"Heatmap URL: {url}")

        # Download image
        resp = _req.get(url, timeout=90)
        if resp.status_code != 200:
            print(f"Heatmap download failed: HTTP {resp.status_code}")
            return None

        # ── Overlay state borders with matplotlib + geopandas ────────────
        import numpy as np
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.image as mpimg
        from PIL import Image as PILImage, ImageDraw

        raw = PILImage.open(_io.BytesIO(resp.content)).convert('RGB')
        img_w, img_h = raw.size

        fig, ax = plt.subplots(figsize=(img_w / 100, img_h / 100), dpi=100)
        ax.imshow(np.array(raw),
                  extent=[BMIN_LON, BMAX_LON, BMIN_LAT, BMAX_LAT],
                  aspect='auto', origin='upper')
        ax.set_xlim(BMIN_LON, BMAX_LON)
        ax.set_ylim(BMIN_LAT, BMAX_LAT)
        ax.axis('off')
        plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

        # Draw state borders (try multiple data sources)
        try:
            import geopandas as gpd
            states_gdf = None

            # Source 1: naturalearth admin-1 via geodatasets (geopandas >= 0.12)
            try:
                import geodatasets
                states_gdf = gpd.read_file(geodatasets.get_path('naturalearth.land'))
                # geodatasets doesn't have admin-1 so skip this path
                states_gdf = None
            except Exception:
                pass

            # Source 2: naturalearth admin-1 GeoJSON from GitHub CDN
            if states_gdf is None:
                ne_url = (
                    "https://raw.githubusercontent.com/nvkelso/"
                    "natural-earth-vector/master/geojson/"
                    "ne_10m_admin_1_states_provinces.geojson"
                )
                try:
                    states_gdf = gpd.read_file(ne_url)
                    states_gdf = states_gdf[states_gdf['admin'] == 'Brazil']
                except Exception:
                    states_gdf = None

            # Source 3: IBGE simplified + reliable IBGE URL
            if states_gdf is None:
                ibge_url = (
                    "https://raw.githubusercontent.com/codeforamerica/"
                    "click_that_hood/master/public/data/brazil-states.geojson"
                )
                try:
                    states_gdf = gpd.read_file(ibge_url)
                except Exception:
                    states_gdf = None

            if states_gdf is not None and len(states_gdf) > 0:
                states_gdf.boundary.plot(ax=ax, linewidth=0.7, color='white', alpha=0.85)
                print(f"  Drew {len(states_gdf)} state borders")
            else:
                print("  No state border data found, drawing outline only")
                # Fallback: draw simple Brazil outline from naturalearth_lowres
                world = gpd.read_file(gpd.datasets.get_path('naturalearth_lowres'))
                brazil_outline = world[world['name'] == 'Brazil']
                brazil_outline.boundary.plot(ax=ax, linewidth=1.0, color='white', alpha=0.9)
        except Exception as ge:
            print(f"  State borders skipped entirely: {ge}")

        # Red pin marker
        ax.plot(lon, lat, 'o', markersize=10, color='#DC1E1E',
                markeredgecolor='white', markeredgewidth=1.5, zorder=5)

        buf = _io.BytesIO()
        fig.savefig(buf, format='png', dpi=100,
                    bbox_inches='tight', pad_inches=0)
        plt.close(fig)
        buf.seek(0)

        return {
            'buffer': buf,
            'image_url': url,
            'region_bbox': {
                'min_lon': BMIN_LON, 'min_lat': BMIN_LAT,
                'max_lon': BMAX_LON, 'max_lat': BMAX_LAT,
            }
        }

    except Exception as e:
        print(f"Heatmap error: {e}")
        import traceback
        print(traceback.format_exc())
        return None
