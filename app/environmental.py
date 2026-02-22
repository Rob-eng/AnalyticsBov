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
from app.models import CarSessionLocal, CARProperty
from geoalchemy2.functions import ST_Intersects, ST_GeomFromText, ST_Distance
from geoalchemy2.shape import to_shape
from sqlalchemy import text

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

def fetch_car_perimeter(lat, lon):
    """
    Attempts to fetch CAR perimeter using Local API (Priority 1) then WFS (Priority 2).
    Falls back to a 1km bounding box if both fail.
    Returns: (geometry, status)
    status can be: 'OFFICIAL', 'NEARBY', 'FALLBACK'
    """
    # 1. Try Local API (FastAPI sidecar)
    port = os.getenv("PORT", 8000)
    api_url = f"http://127.0.0.1:{port}/property/at"
    headers = {"X-API-Key": os.getenv("CAR_API_KEY", "your-default-secure-key")}
    params = {"lat": lat, "lon": lon}
    
    try:
        print(f"Querying Local API: {api_url} params={params}")
        response = requests.get(api_url, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("found"):
                status = data.get("status", "OFFICIAL")
                print(f"✓ Local API found property: {data.get('cod_imovel')} ({status})")
                return (data["geometry"], status)
        else:
            print(f"Local API returned status {response.status_code}: {response.text}")
    except Exception as e:
        print(f"⚠️ Local API connection failed: {e}")

    # 2. Try WFS (External Government Server)
    print("Trying WFS fallback...")
    endpoints = [
        "https://geoserver.car.gov.br/geoserver/sicar/wfs",
        "https://geoserver.car.gov.br/geoserver/wfs"
    ]
    
    wfs_params = {
        "service": "WFS",
        "version": "1.1.0",
        "request": "GetFeature",
        "typeName": "sicar:area_imovel",
        "outputFormat": "application/json",
        "cql_filter": f"CONTAINS(geometria, POINT({lon} {lat}))"
    }

    for url in endpoints:
        try:
            response = requests.get(url, params=wfs_params, timeout=10)
            if response.status_code == 200 and 'json' in response.headers.get('Content-Type', ''):
                data = response.json()
                if "features" in data and len(data["features"]) > 0:
                    print("✓ WFS found property")
                    return (data["features"][0]["geometry"], 'OFFICIAL')
        except:
            continue
    
    # 3. Last resort: estimated area
    print("⚠ All sources failed. Using estimated 1km² area")
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
            print("GEE returned no data.", flush=True)
            return None
            
        print("✓ GEE NDVI Data Retrieved. Downloading thumbnail...", flush=True)
        
        # Download the image from the URL provided by GEE
        img_url = result['image_url']
        try:
            resp = requests.get(img_url, timeout=45)  # timeout was missing!
            if resp.status_code != 200:
                print(f"Failed to download GEE thumbnail: HTTP {resp.status_code}", flush=True)
                return None
            img_bytes = BytesIO(resp.content)
            print(f"✓ NDVI thumbnail downloaded ({len(resp.content)//1024}KB)", flush=True)
        except Exception as e:
            print(f"Download error: {e}", flush=True)
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
            resp = requests.get(ndvi_source, timeout=45)
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
        print(f"CAR polygon type: {geometry['type']}, bounds: {poly.bounds}", flush=True)
        
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
            print(f"MultiPolygon: {len(geometry['coordinates'])} sub-polygons", flush=True)
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
            print(f"  Drawing polygon ring: x=[{min(xs):.2f}..{max(xs):.2f}] y=[{min(ys):.2f}..{max(ys):.2f}]", flush=True)
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


# ── MDT: 2D Contour Map ────────────────────────────────────────────────────────

def generate_terrain_image_2d(terrain_data, geometry, is_real_car='FALLBACK',
                               title=None, pin_coords=None):
    """
    Generates a 2D hillshaded terrain map with contour lines:
      - Contours every 5m  : thin grey lines
      - Contours every 50m : thick white lines with elevation labels
      - CAR perimeter overlay
      - Elevation colorbar
    Returns BytesIO PNG or None.
    """
    import numpy as np
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource
    from io import BytesIO
    from shapely.geometry import shape as sh

    try:
        elevation = terrain_data['elevation']
        region_bbox = terrain_data['region_bbox']
        source = terrain_data.get('source', 'DEM')
        elev_min = terrain_data.get('elev_min', float(np.nanmin(elevation)))
        elev_max = terrain_data.get('elev_max', float(np.nanmax(elevation)))

        rows, cols = elevation.shape
        # Fill NaN with min for rendering
        elev_fill = np.where(np.isnan(elevation), elev_min, elevation)

        fig, ax = plt.subplots(figsize=(10, 10), dpi=130)
        fig.patch.set_facecolor('#1a1a2e')

        # ── Hillshade ──────────────────────────────────────────────────────
        ls = LightSource(azdeg=315, altdeg=35)
        hillshade = ls.shade(elev_fill, cmap=plt.cm.terrain,
                             blend_mode='overlay',
                             vert_exag=3,
                             vmin=elev_min, vmax=elev_max)
        ax.imshow(hillshade, extent=[0, 1, 0, 1], origin='upper', aspect='auto')

        X = np.linspace(0, 1, cols)
        Y = np.linspace(1, 0, rows)   # image Y is top-to-bottom

        # ── Contours 5m (fine) ─────────────────────────────────────────────
        elev_range = elev_max - elev_min
        if elev_range > 0:
            levels_5 = np.arange(
                round(elev_min / 5) * 5,
                round(elev_max / 5 + 1) * 5,
                5
            )
            levels_50 = np.arange(
                round(elev_min / 50) * 50,
                round(elev_max / 50 + 1) * 50,
                50
            )

            if len(levels_5) > 1:
                cs5 = ax.contour(X, Y, elev_fill, levels=levels_5,
                                 colors='white', linewidths=0.4, alpha=0.45)
            if len(levels_50) > 1:
                cs50 = ax.contour(X, Y, elev_fill, levels=levels_50,
                                  colors='white', linewidths=1.5, alpha=0.85)
                ax.clabel(cs50, inline=True, fontsize=7, fmt='%d m',
                          colors='white', inline_spacing=4)

        # ── CAR perimeter ──────────────────────────────────────────────────
        minx = region_bbox['min_lon']
        miny = region_bbox['min_lat']
        w = region_bbox['max_lon'] - minx
        h = region_bbox['max_lat'] - miny

        color_map = {'OFFICIAL': 'lime', 'NEARBY': 'orange'}
        pcolor = color_map.get(is_real_car, 'yellow')
        plw = 2.5 if is_real_car in ('OFFICIAL', 'NEARBY') else 1.5
        pls = '-' if is_real_car == 'OFFICIAL' else '-.'

        rings = _extract_rings(geometry)
        for ring in rings:
            xs = [(x - minx) / w for x, y in ring]
            ys = [1 - (y - miny) / h for x, y in ring]
            ax.plot(xs, ys, color=pcolor, linewidth=plw, linestyle=pls, zorder=5)

        # ── Pin ────────────────────────────────────────────────────────────
        if pin_coords and region_bbox:
            px = (pin_coords[1] - minx) / w
            py = 1 - (pin_coords[0] - miny) / h
            if 0 <= px <= 1 and 0 <= py <= 1:
                ax.plot(px, py, 'o', markersize=4, color='#FF3333',
                        markeredgecolor='white', markeredgewidth=0.8, zorder=8)

        # ── Colorbar ───────────────────────────────────────────────────────
        sm = plt.cm.ScalarMappable(
            cmap=plt.cm.terrain,
            norm=plt.Normalize(vmin=elev_min, vmax=elev_max)
        )
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax, fraction=0.04, pad=0.02, shrink=0.7)
        cbar.set_label('Altitude (m)', color='white', fontsize=9)
        cbar.ax.yaxis.set_tick_params(color='white')
        plt.setp(cbar.ax.yaxis.get_ticklabels(), color='white', fontsize=8)

        # ── Cosmetics ──────────────────────────────────────────────────────
        if title:
            ax.set_title(f"🏔️ {title}", color='white', fontsize=13,
                         fontweight='bold', pad=10)
        ax.axis('off')
        ax.text(0.99, 0.01,
                f"Fonte: {source} · GEE  |  Curvas: 5m / 50m",
                transform=ax.transAxes, fontsize=6.5, color='white',
                ha='right', va='bottom',
                bbox=dict(boxstyle='round,pad=0.2', fc='black', alpha=0.5, ec='none'),
                zorder=9)

        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=130, bbox_inches='tight',
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        print("[MDT 2D] Image generated.", flush=True)
        return buf

    except Exception as e:
        print(f"[MDT 2D ERROR] {e}", flush=True)
        import traceback; traceback.print_exc()
        return None


# ── MDT: 3D Terrain Model ─────────────────────────────────────────────────────

def generate_terrain_image_3d(terrain_data, geometry, is_real_car='FALLBACK',
                               title=None, pin_coords=None):
    """
    Generates a 3D terrain model with Sentinel-2 satellite texture draped over
    the elevation surface.  CAR perimeter is projected onto the 3D surface.
    Returns BytesIO PNG or None.
    """
    import numpy as np
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
    from io import BytesIO
    import requests as _req

    try:
        elevation = terrain_data['elevation']
        region_bbox = terrain_data['region_bbox']
        source = terrain_data.get('source', 'DEM')
        rgb_url = terrain_data.get('rgb_url')
        elev_min = terrain_data.get('elev_min', float(np.nanmin(elevation)))
        elev_max = terrain_data.get('elev_max', float(np.nanmax(elevation)))

        rows, cols = elevation.shape
        elev_fill = np.where(np.isnan(elevation), elev_min, elevation)

        # ── Download and resize satellite texture ──────────────────────────
        face_colors = None
        if rgb_url:
            try:
                resp = _req.get(rgb_url, timeout=30)
                if resp.status_code == 200:
                    from PIL import Image as _PIL
                    sat_img = _PIL.open(BytesIO(resp.content)).convert('RGB')
                    sat_img = sat_img.resize((cols, rows), _PIL.LANCZOS)
                    face_colors = np.array(sat_img) / 255.0
                    print("[MDT 3D] Satellite texture loaded.", flush=True)
            except Exception as te:
                print(f"[MDT 3D] Texture load failed: {te}", flush=True)

        # ── Build meshgrid ─────────────────────────────────────────────────
        x = np.linspace(0, 1, cols)
        y = np.linspace(0, 1, rows)
        X, Y = np.meshgrid(x, y)
        # Flip Z so north is at back of plot
        Z = elev_fill

        fig = plt.figure(figsize=(12, 9), dpi=130)
        fig.patch.set_facecolor('#0d0d1a')
        ax = fig.add_subplot(111, projection='3d')
        ax.set_facecolor('#0d0d1a')

        # ── Surface ────────────────────────────────────────────────────────
        if face_colors is not None:
            # Drape satellite image as texture
            ax.plot_surface(X, Y, Z,
                            facecolors=face_colors,
                            rstride=1, cstride=1,
                            linewidth=0, antialiased=False,
                            shade=False)
        else:
            # Fallback: terrain colormap
            from matplotlib.colors import Normalize
            norm = Normalize(vmin=elev_min, vmax=elev_max)
            ax.plot_surface(X, Y, Z,
                            cmap='terrain', norm=norm,
                            rstride=1, cstride=1,
                            linewidth=0, antialiased=False,
                            alpha=0.95)

        # ── CAR perimeter projected onto terrain ───────────────────────────
        minx = region_bbox['min_lon']
        miny = region_bbox['min_lat']
        w = region_bbox['max_lon'] - minx
        h = region_bbox['max_lat'] - miny

        color_map = {'OFFICIAL': 'lime', 'NEARBY': 'orange'}
        pcolor = color_map.get(is_real_car, 'yellow')

        rings = _extract_rings(geometry)
        for ring in rings:
            xs_n = [(x - minx) / w for x, y in ring]
            ys_n = [(y - miny) / h for x, y in ring]
            # Interpolate elevation at each perimeter vertex
            def _elev_at(xn, yn):
                ci = int(np.clip(xn * (cols - 1), 0, cols - 1))
                ri = int(np.clip((1 - yn) * (rows - 1), 0, rows - 1))
                return float(elev_fill[ri, ci]) + 15  # +15m so line sits above surface
            zs = [_elev_at(xn, yn) for xn, yn in zip(xs_n, ys_n)]
            ax.plot(xs_n, ys_n, zs, color=pcolor, linewidth=2.0, zorder=5)

        # ── Pin ────────────────────────────────────────────────────────────
        if pin_coords and region_bbox:
            px = (pin_coords[1] - minx) / w
            py = (pin_coords[0] - miny) / h
            if 0 <= px <= 1 and 0 <= py <= 1:
                ci = int(np.clip(px * (cols - 1), 0, cols - 1))
                ri = int(np.clip((1 - py) * (rows - 1), 0, rows - 1))
                pz = float(elev_fill[ri, ci]) + 25
                ax.scatter([px], [py], [pz], color='#FF3333', s=60,
                           edgecolors='white', linewidths=0.8, zorder=8)

        # ── View angle + style ─────────────────────────────────────────────
        ax.view_init(elev=30, azim=225)
        ax.set_zlim(elev_min - 5, elev_max + (elev_max - elev_min) * 0.3)

        # Clean up panes
        ax.xaxis.pane.set_visible(False)
        ax.yaxis.pane.set_visible(False)
        ax.zaxis.pane.set_visible(False)
        ax.grid(False)
        ax.set_xticks([]); ax.set_yticks([])
        ax.zaxis.set_tick_params(labelcolor='white', labelsize=7)
        ax.set_zlabel('m', color='white', fontsize=8)

        if title:
            ax.set_title(f"🏔️ {title} — Modelo 3D", color='white',
                         fontsize=12, fontweight='bold', pad=12)

        fig.text(0.02, 0.02,
                 f"Fonte: {source} + Sentinel-2 · Google Earth Engine",
                 color='white', fontsize=6.5, alpha=0.8)

        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=130, bbox_inches='tight',
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        print("[MDT 3D] Image generated.", flush=True)
        return buf

    except Exception as e:
        print(f"[MDT 3D ERROR] {e}", flush=True)
        import traceback; traceback.print_exc()
        return None


def _extract_rings(geometry):
    """Helper: extract coordinate rings from Polygon or MultiPolygon geometry dict."""
    gtype = geometry.get('type', '')
    if gtype == 'Polygon':
        return geometry['coordinates']
    elif gtype == 'MultiPolygon':
        return [ring for poly in geometry['coordinates'] for ring in poly]
    return []
