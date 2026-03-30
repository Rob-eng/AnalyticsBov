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

def get_asset_intersection_area(asset_id: str, geometry_geojson: dict) -> float:
    """
    Calculates the intersected area (in hectares) between a given geometry
    (like the boundaries of a farm) and a GEE FeatureCollection Asset 
    (like Reserva Legal, APP, Uso Consolidado borders).
    
    Returns the total intersecting area in hectares.
    """
    try:
        if not initialize_gee():
            print("[GEE ASSET] Falha na autenticação do Google Earth Engine.")
            return 0.0
            
        farm_geom = ee.Geometry(geometry_geojson)
        asset_collection = ee.FeatureCollection(asset_id)
        
        # Otimização espacial rápida: pega apenas feições que colidem com a fazenda
        intersecting_features = asset_collection.filterBounds(farm_geom)
        
        # Função para aplicar a interseção matemática dentro do supercomputador do GEE
        def calc_intersection(feature):
            # Recorta a camada secundária no limite exato da fazenda principal
            intersection = feature.geometry().intersection(farm_geom)
            # st_area() retorna em metros quadrados
            area_sqm = intersection.area()
            # Converte m² para hectares
            area_ha = ee.Number(area_sqm).divide(10000)
            return feature.set('intersected_area_ha', area_ha)
            
        # Processa todas as feições (pode ser mais de 1 APP encostando na fazenda)
        processed = intersecting_features.map(calc_intersection)
        
        # Soma todas as partes cortadas e traz o resultado matemático (reduce/aggregate)
        total_area_ha = processed.aggregate_sum('intersected_area_ha').getInfo()
        
        print(f"[GEE ASSET] Interseção calculada com sucesso: {total_area_ha:.2f} ha", flush=True)
        return float(total_area_ha)
        
    except Exception as e:
        print(f"[GEE ASSET ERROR] Erro ao calcular interseção na Cloud: {e}", flush=True)
        return 0.0
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

        # ── 4. High-quality S2 RGB thumbnail for 3D texture ─────────────────
        print("[MDT] Fetching satellite background for 3D texture...", flush=True)
        rgb_url = None
        try:
            # We use a 1-year median to get a "Google Satellite" clean look
            end_date = datetime.now()
            start_year = end_date - timedelta(days=365)
            
            s2_col = (
                ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                .filterBounds(square)
                .filterDate(start_year.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
                .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 5))
            )
            
            # Use median for clean mosaic, fallback to recent first() if empty or small
            s2_img = s2_col.median().clip(square)
            
            # If median is empty (no <5% cloud images), use 30% threshold first()
            count = s2_col.size().getInfo()
            if count == 0:
                s2_img = (
                    ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                    .filterBounds(square)
                    .filterDate(start_year.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
                    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
                    .sort('CLOUDY_PIXEL_PERCENTAGE')
                    .first()
                    .clip(square)
                )

            rgb_url = s2_img.visualize(bands=['B4', 'B3', 'B2'], min=0, max=3000, gamma=1.2).getThumbURL({
                'region': square.getInfo(),
                'dimensions': 1024,  # Increased resolution for 3D texture
                'format': 'png',
            })
            print(f"[MDT] Satellite background URL obtained.", flush=True)
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

def get_satellite_thumbnail(geometry_geojson, dimensions=1024, padding_m=1000):
    """
    Gera uma URL de miniatura RGB (Sentinel-2) para a geometria fornecida.
    dimensoes: 1024 (alta qualidade)
    padding_m: buffer em metros ao redor da area
    """
    try:
        if not initialize_gee():
            print("[GEE] Falha ao inicializar para miniatura.", flush=True)
            return None

        # 1. Preparar Geometria
        geom = ee.Geometry(geometry_geojson)
        region = geom.buffer(padding_m).bounds()
        
        # 2. Buscar imagem recente (janela de 1 ano para garantir que ache algo sem nuvem)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        
        print(f"[GEE] Buscando Satelite para regiao com padding={padding_m}m...", flush=True)
        
        # Tentar Sentinel-2 primeiro (melhor cor e resolucao 10m)
        collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                      .filterBounds(region)
                      .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
                      .sort('CLOUDY_PIXEL_PERCENTAGE')) # Pega a com menos nuvem do ano
        
        if collection.size().getInfo() > 0:
            image = collection.first()
            v_params = {'bands': ['B4', 'B3', 'B2'], 'min': 0, 'max': 3500, 'gamma': 1.3}
            print(f"[GEE] Usando Sentinel-2 (Nuvens: {image.get('CLOUDY_PIXEL_PERCENTAGE').getInfo()}%)", flush=True)
        else:
            # Fallback para Landsat 8 (30m)
            collection = (ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
                          .filterBounds(region)
                          .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
                          .sort('CLOUD_COVER'))
            if collection.size().getInfo() > 0:
                image = collection.first()
                print(f"[GEE] Usando Landsat-8 (Nuvens: {image.get('CLOUD_COVER').getInfo()}%)", flush=True)
            else:
                print("[GEE] Nenhuma imagem encontrada em 365 dias.", flush=True)
                return None
            
        # 2. Visualização
        if 'B4' in image.bandNames().getInfo(): # Sentinel-2
            v_params = {'bands': ['B4', 'B3', 'B2'], 'min': 0, 'max': 3500, 'gamma': 1.3}
        else: # Landsat
            v_params = {'bands': ['SR_B4', 'SR_B3', 'SR_B2'], 'min': 7000, 'max': 16000, 'gamma': 1.1}
        
        # 3. Adicionar contornos administrativos (opcional, para contexto regional)
        visualized = image.visualize(**v_params)
        if padding_m > 5000: # Somente para zooms regionais
            try:
                # Usar GAUL level 1 (Estados) ou ADM1
                states = ee.FeatureCollection("FAO/GAUL/2015/level1")
                # Desenha o contorno dos estados em vermelho/branco para ver os limites
                visualized = visualized.paint(states, 'white', 2)
            except: pass
            
        # 4. Gerar URL
        thumb_url = visualized.getThumbURL({
            'dimensions': dimensions,
            'region': region.getInfo(),
            'format': 'png'
        })
        
        print(f"[GEE] URL Gerada: {thumb_url[:100]}...", flush=True)
        return thumb_url

    except Exception as e:
        print(f"[GEE SATELLITE ERROR] {e}", flush=True)
        import traceback; traceback.print_exc()
        return None

def find_car_at_coordinate_gee(lat, lon):
    """
    Busca o código do CAR (cod_imovel) em uma coordenada (lat/lon)
    percorrendo os Assets do GEE (Mato Grosso e MS).
    Isso substitui a busca no PostGIS para economizar memória e escala.
    """
    try:
        if not initialize_gee():
            return None

        point = ee.Geometry.Point([lon, lat])
        
        # 📂 Lista de Pastas onde as UFs estão divididas em chunks
        # Tentamos dois caminhos (o projeto atual 'analyticsbov' e o legado 'ee-ranjos')
        PROJECT_IDS = ['analyticsbov', 'ee-ranjos']
        UF_FOLDERS = [
            'car/imovel/ms_chunks', 'car/imovel/mt_chunks', 'car/imovel/sp_chunks',
            'car/imovel/go_chunks', 'car/imovel/to_chunks', 'car/imovel/pr_chunks',
            'car/imovel/sc_chunks', 'car/imovel/rs_chunks', 'car/imovel/mg_chunks'
        ]
        
        # Gera a lista completa de caminhos para testar
        CAR_FOLDERS = []
        for pid in PROJECT_IDS:
             for folder in UF_FOLDERS:
                  CAR_FOLDERS.append(f'projects/{pid}/assets/analyticsbov/{folder}')

        print(f"🛰️ [GEE LOOKUP] Iniciando varredura em {len(CAR_FOLDERS)} locais para {lat}, {lon}", flush=True)
        
        # Filtro Silencioso e Rápido
        for folder in CAR_FOLDERS:
            try:
                # 🔍 Tenta listar assets da pasta
                assets_res = ee.data.listAssets({'parent': folder})
                assets = assets_res.get('assets', [])
                if not assets:
                     continue
                    
                asset_ids = [a['id'] for a in assets if a['type'] == 'TABLE']
                
                # Para cada pedaço, verificamos se o ponto está dentro
                for aid in asset_ids:
                    # OTIMIZAÇÃO: Filtra apenas 1 feature e traz apenas metadados necessários
                    fc = ee.FeatureCollection(aid).filterBounds(point)
                    # Verifica se há algo sem dar o getInfo completo se vazio
                    res = fc.limit(1).getInfo()
                    
                    if res.get('features'):
                        feat = res['features'][0]
                        props = feat.get('properties', {})
                        print(f"✅ [GEE] Localizado em {aid} -> {props.get('cod_imovel')}", flush=True)
                        return {
                            "cod_imovel": props.get('cod_imovel'),
                            "uf": props.get('uf') or ("MT" if "mt_chunks" in folder else "MS"),
                            "municipio": props.get('municipio'),
                            "area": props.get('area'),
                            "geometry": feat.get('geometry')
                        }
            except Exception as e:
                # Silencioso para erros de permissão ou pasta não encontrada
                continue
            except Exception:
                continue # Silent fail

        print(f"📍 [GEE] Nada encontrado em nenhuma UF mapeada.")
        return None

    except Exception as e:
        print(f"❌ [GEE SEARCH ERROR] {e}")
        import traceback; traceback.print_exc()
        return None
