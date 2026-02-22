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
            print("GEE initialization failed for heatmap", flush=True)
            return None

        print(f"[HEATMAP] Starting Brazil heatmap for lat={lat}, lon={lon}", flush=True)

        # Brazil bounding box
        BMIN_LON, BMAX_LON = -74.0, -28.6
        BMIN_LAT, BMAX_LAT = -33.8,   5.3
        brazil = ee.Geometry.BBox(BMIN_LON, BMIN_LAT, BMAX_LON, BMAX_LAT)

        # Date range (UTC)
        end_date   = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
        start_str  = start_date.strftime('%Y-%m-%d')
        end_str    = end_date.strftime('%Y-%m-%d')

        # GPM dataset fallback chain — LATE run first (14h latency vs 2-month for Final)
        GPM_ASSETS = [
            'NASA/GPM_L3/IMERG_V06_LATE',   # near real-time, ~14h latency
            'NASA/GPM_L3/IMERG_V07HHL',      # V07 Late-run if available
            'NASA/GPM_L3/IMERG_V07',         # Final (~2 months latency)
            'NASA/GPM_L3/IMERG_V06',         # V06 Final
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
                    print(f"Using GPM asset: {asset} ({count} images)", flush=True)
                    collection = coll
                    break
                print(f"Asset {asset}: 0 images in 30-day window, trying next...", flush=True)
            except Exception as ae:
                print(f"Asset {asset} error: {ae}, trying next...", flush=True)

        if collection is None or count == 0:
            print("Widening to 60-day window...", flush=True)
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
            print("Heatmap: no data found.", flush=True)
            return None

        print(f"Heatmap: {count} images found. Aggregating to daily...", flush=True)

        # ── Aggregate to daily totals first (reduces ~1386 → 30 images) ──
        # This dramatically speeds up GEE thumbnail computation.
        start_date_ee = ee.Date(start_str)
        n_days = (end_date - start_date).days

        def daily_total(offset):
            d = start_date_ee.advance(offset, 'day')
            daily = collection.filterDate(d, d.advance(1, 'day'))
            # sum of mm/hr × 0.5hr = total mm for the day
            return (daily.reduce(ee.Reducer.sum())
                         .multiply(0.5)
                         .rename('precipitation')
                         .set('system:time_start', d.millis()))

        daily_col = ee.ImageCollection(
            ee.List.sequence(0, n_days - 1).map(daily_total)
        )
        total_precip = daily_col.reduce(ee.Reducer.sum())

        print("Daily aggregation done. Getting thumbnail URL...", flush=True)

        # Use native GPM scale (0.25° ≈ 27750m) — no resampling needed,
        # much faster than a fixed pixel dimension.
        url = total_precip.getThumbURL({
            'min': 1,
            'max': 300,
            'palette': ['f0f0f0', 'aad4f5', '3399ff', '003580', '2d0055'],
            'scale': 27750,          # native GPM resolution (0.25°)
            'region': brazil.getInfo(),
            'format': 'png',
            'bestEffort': True,
        })
        print(f"Heatmap URL obtained.", flush=True)

        # Download image
        resp = _req.get(url, timeout=120)
        if resp.status_code != 200:
            print(f"Heatmap download failed: HTTP {resp.status_code}", flush=True)
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

        # Small red pin marker
        ax.plot(lon, lat, 'o', markersize=2, color='#DC1E1E',
                markeredgecolor='white', markeredgewidth=0.5, zorder=5)

        # Source attribution
        ax.text(
            BMAX_LON - 0.3, BMIN_LAT + 0.3,
            "Fonte: NASA GPM IMERG · Google Earth Engine",
            fontsize=6.5, color='white', ha='right', va='bottom',
            bbox=dict(boxstyle='round,pad=0.2', fc='black', alpha=0.45, ec='none'),
            zorder=6
        )

        buf = _io.BytesIO()
        fig.savefig(buf, format='png', dpi=120,
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
        print(f"[HEATMAP ERROR] {e}", flush=True)
        import traceback
        print(traceback.format_exc(), flush=True)
        return None


# ── Terrain / MDT ──────────────────────────────────────────────────────────────

def get_terrain_data(geometry_geojson):
    """
    Fetches Digital Elevation Model data for the given geometry using GEE.

    DEM Priority:
      1. COPERNICUS/DEM/GLO30  — ESA/TanDEM-X, 30m, best global accuracy
      2. NASA/NASADEM_HGT/001  — Improved SRTM void-filled
      3. USGS/SRTMGL1_003      — Classic SRTM 30m

    Returns:
      {
        'elevation': np.ndarray,   2-D elevation grid (metres)
        'rgb_url':   str,          Sentinel-2 true-colour thumbnail URL
        'region_bbox': dict,       {min_lon, min_lat, max_lon, max_lat}
        'source':    str,          which DEM was used
        'elev_min':  float,
        'elev_max':  float,
      }
      or None on failure.
    """
    import numpy as np
    import requests as _requests

    try:
        if not initialize_gee():
            return None

        print("[MDT] Initializing terrain data fetch...", flush=True)
        geom = ee.Geometry(geometry_geojson)

        # ── 1. Build a square region around the geometry ────────────────────
        bounds = geom.buffer(50).bounds()
        coords = bounds.coordinates().get(0).getInfo()
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)

        cx = (min_lon + max_lon) / 2
        cy = (min_lat + max_lat) / 2
        half = max(max_lon - min_lon, max_lat - min_lat) / 2 * 1.15

        square = ee.Geometry.Polygon([[
            [cx - half, cy - half],
            [cx + half, cy - half],
            [cx + half, cy + half],
            [cx - half, cy + half],
            [cx - half, cy - half],
        ]])

        region_bbox = {
            'min_lon': cx - half, 'min_lat': cy - half,
            'max_lon': cx + half, 'max_lat': cy + half,
        }

        # ── 2. Try DEMs in priority order ───────────────────────────────────
        DEM_SOURCES = [
            ('COPERNICUS/DEM/GLO30', 'DEM',        'Copernicus GLO-30'),
            ('NASA/NASADEM_HGT/001', 'elevation',  'NASADEM'),
            ('USGS/SRTMGL1_003',     'elevation',  'SRTM 30m'),
        ]

        elevation_img = None
        source_name = 'Unknown'
        for asset, band, label in DEM_SOURCES:
            try:
                img = ee.Image(asset).select(band).clip(square)
                # Quick sanity-check: get min value; if it errors, asset is unavailable
                test = img.reduceRegion(
                    reducer=ee.Reducer.min(), geometry=square,
                    scale=30, maxPixels=1e6, bestEffort=True
                ).getInfo()
                if test and list(test.values())[0] is not None:
                    elevation_img = img
                    source_name = label
                    print(f"[MDT] Using DEM: {label}", flush=True)
                    break
            except Exception as de:
                print(f"[MDT] {label} unavailable: {de}", flush=True)
                continue

        if elevation_img is None:
            print("[MDT] All DEM sources failed.", flush=True)
            return None

        # ── 3. Sample rectangle → numpy elevation array ─────────────────────
        print("[MDT] Sampling elevation array...", flush=True)
        sample = elevation_img.sampleRectangle(region=square, defaultValue=0)
        elev_list = sample.get('DEM' if source_name == 'Copernicus GLO-30' else 'elevation').getInfo()

        # For Copernicus, band might be named differently — re-try with generic get
        if elev_list is None:
            band_key = list(sample.toDictionary().getInfo().keys())[0]
            elev_list = sample.get(band_key).getInfo()

        elevation = np.array(elev_list, dtype=np.float32)
        # Replace no-data sentinel values
        elevation = np.where(elevation < -1000, np.nan, elevation)

        elev_min = float(np.nanmin(elevation))
        elev_max = float(np.nanmax(elevation))
        print(f"[MDT] Elevation range: {elev_min:.1f}m – {elev_max:.1f}m, shape={elevation.shape}", flush=True)

        # ── 4. Sentinel-2 RGB thumbnail for 3D texture ──────────────────────
        print("[MDT] Fetching Sentinel-2 RGB thumbnail...", flush=True)
        rgb_url = None
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=90)
            s2 = (
                ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                .filterBounds(square)
                .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
                .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
                .sort('CLOUDY_PIXEL_PERCENTAGE')
                .first()
            )
            rgb_url = s2.visualize(bands=['B4', 'B3', 'B2'], min=0, max=2500).getThumbURL({
                'region': square.getInfo(),
                'dimensions': 512,
                'format': 'png',
            })
            print(f"[MDT] RGB URL obtained.", flush=True)
        except Exception as re:
            print(f"[MDT] RGB thumbnail failed (will render without texture): {re}", flush=True)

        return {
            'elevation':   elevation,
            'rgb_url':     rgb_url,
            'region_bbox': region_bbox,
            'source':      source_name,
            'elev_min':    elev_min,
            'elev_max':    elev_max,
        }

    except Exception as e:
        print(f"[MDT ERROR] {e}", flush=True)
        import traceback
        print(traceback.format_exc(), flush=True)
        return None
