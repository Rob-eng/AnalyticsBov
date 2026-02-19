"""
forecast.py — ECMWF Open Data download + dual-panel matplotlib map rendering.

Generates two side-by-side maps:
  Left  → Wide regional view with country + Brazilian state borders
  Right → Close-up view with CAR property polygon (if provided)
"""
import os
import io
import json
import tempfile
import logging
import pandas as pd
from datetime import datetime, timedelta, timezone

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patheffects as path_effects
import matplotlib.patches as mpatches
from matplotlib.colors import BoundaryNorm, ListedColormap
from shapely.geometry import shape

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Color palette (ECMWF / IgorRoik style)
# ─────────────────────────────────────────────
BOUNDS = [0, 0.5, 1, 2, 3, 4, 5, 6, 7, 8, 10, 15, 20, 25, 30, 35, 40, 45,
          50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 175, 200, 250, 300, 400, 500]

def _build_cmap():
    cmap_base = plt.cm.YlGnBu(np.linspace(0.15, 1, 18))
    cmap_mid  = plt.cm.OrRd(np.linspace(0.2, 1, 10))
    cmap_high = plt.cm.Reds(np.linspace(0.5, 1, 7))
    colors = np.vstack(([[1, 1, 1, 1]], cmap_base, cmap_mid, cmap_high))
    cmap = ListedColormap(colors)
    norm = BoundaryNorm(BOUNDS, cmap.N, clip=True)
    return cmap, norm

CMAP, NORM = _build_cmap()

# ─────────────────────────────────────────────
# ECMWF step mapping: days → forecast hours
# ─────────────────────────────────────────────
DAYS_TO_STEP = {1: 24, 5: 120, 10: 240}

# ─────────────────────────────────────────────
# Lazy-loaded geographic boundary data
# ─────────────────────────────────────────────
_geo_cache = {}

def _load_geo_data():
    """Load Natural Earth country + Brazilian state boundaries (lazy, cached)."""
    if _geo_cache:
        return _geo_cache

    import geopandas as gpd

    try:
        # Countries — 110m resolution bundled with geopandas (naturalearth_lowres)
        world = gpd.read_file(gpd.datasets.get_path('naturalearth_lowres'))
        _geo_cache['world'] = world
        logger.info("Loaded naturalearth_lowres countries OK")
    except Exception as e:
        logger.warning(f"Could not load world boundaries: {e}")
        _geo_cache['world'] = None

    try:
        # Brazilian states — download from Natural Earth 50m (small, reliable)
        brazil_url = (
            "https://naciscdn.org/naturalearth/50m/cultural/"
            "ne_50m_admin_1_states_provinces.zip"
        )
        states_all = gpd.read_file(brazil_url)
        _geo_cache['brazil_states'] = states_all[states_all['admin'] == 'Brazil']
        logger.info("Loaded Brazil state boundaries OK")
    except Exception as e:
        logger.warning(f"Could not load Brazil state boundaries: {e}")
        _geo_cache['brazil_states'] = None

    return _geo_cache


# ─────────────────────────────────────────────
# ECMWF download
# ─────────────────────────────────────────────
def download_ecmwf_precip(forecast_days: int, target_dir: str) -> str:
    from ecmwf.opendata import Client

    step = DAYS_TO_STEP.get(forecast_days)
    if step is None:
        raise ValueError(f"forecast_days must be 1, 5 or 10. Got {forecast_days}")

    client = Client(source="ecmwf")
    outfile = os.path.join(target_dir, f"ecmwf_tp_{forecast_days}d.grib2")
    logger.info(f"Downloading ECMWF tp step={step}h ...")
    client.retrieve(type="fc", param="tp", step=step, target=outfile)
    logger.info(f"Downloaded: {outfile}")
    return outfile


# ─────────────────────────────────────────────
# GRIB loading + regional clip
# ─────────────────────────────────────────────
def load_regional_data(grib_path: str, lat_center: float, lon_center: float,
                       span: float = 25.0):
    """
    Load GRIB2, clip to a region of ±span° around (lat_center, lon_center).
    Returns (lon_grid, lat_grid, precip_mm_grid, metadata_dict).
    """
    import xarray as xr

    try:
        ds = xr.open_dataset(grib_path, engine='cfgrib')
    except Exception:
        import cfgrib
        datasets = cfgrib.open_datasets(grib_path)
        ds = datasets[0]

    tp = ds['tp']          # unit: m
    tp_mm = tp * 1000.0    # to mm

    lat_arr = tp.latitude.values
    lon_arr = tp.longitude.values

    # Normalise longitudes 0-360 → -180-180
    if lon_arr.max() > 180:
        lon_arr = np.where(lon_arr > 180, lon_arr - 360, lon_arr)

    lat_mask = (lat_arr >= lat_center - span) & (lat_arr <= lat_center + span)
    lon_mask = (lon_arr >= lon_center - span) & (lon_arr <= lon_center + span)

    tp_clipped   = tp_mm.values[np.ix_(lat_mask, lon_mask)]
    lat_clip     = lat_arr[lat_mask]
    lon_clip     = lon_arr[lon_mask]
    lon_grid, lat_grid = np.meshgrid(lon_clip, lat_clip)

    # Point value at property (nearest grid cell)
    lat_idx   = np.argmin(np.abs(lat_arr - lat_center))
    lon_idx   = np.argmin(np.abs(lon_arr - lon_center))
    point_mm  = float(tp_mm.values[lat_idx, lon_idx])
    max_mm    = float(tp_mm.values.max())

    try:
        valid_time = pd.Timestamp(tp.valid_time.values).strftime('%d/%b/%Y %HUTC')
        init_time  = pd.Timestamp(ds.time.values).strftime('%d/%b/%Y %HUTC')
        step_h     = int(ds.step.values / np.timedelta64(1, 'h'))
    except Exception:
        valid_time, init_time, step_h = "N/A", "N/A", 0

    meta = {
        "valid_time": valid_time,
        "init_time":  init_time,
        "step_h":     step_h,
        "point_mm":   point_mm,
        "max_mm":     max_mm,
    }
    return lon_grid, lat_grid, tp_clipped, meta


# ─────────────────────────────────────────────
# Rendering helpers
# ─────────────────────────────────────────────
def _draw_borders(ax, extent):
    """Draw country + Brazil state borders within the given extent."""
    geo = _load_geo_data()
    lon_min, lon_max, lat_min, lat_max = extent

    if geo.get('world') is not None:
        try:
            world_clip = geo['world'].cx[lon_min:lon_max, lat_min:lat_max]
            world_clip.boundary.plot(ax=ax, color='#333333', linewidth=0.6, zorder=3)
        except Exception as e:
            logger.debug(f"Country border draw failed: {e}")

    if geo.get('brazil_states') is not None:
        try:
            br_clip = geo['brazil_states'].cx[lon_min:lon_max, lat_min:lat_max]
            br_clip.boundary.plot(ax=ax, color='#555555', linewidth=0.35,
                                  linestyle='--', zorder=4)
        except Exception as e:
            logger.debug(f"State border draw failed: {e}")


def _draw_precip(ax, lon_grid, lat_grid, precip, draw_contours=True):
    mesh = ax.pcolormesh(lon_grid, lat_grid, precip,
                         cmap=CMAP, norm=NORM, shading='auto', rasterized=True)
    if draw_contours:
        try:
            ax.contour(lon_grid, lat_grid, precip,
                       levels=[100, 150, 200, 250, 300],
                       colors='maroon', linewidths=0.6, linestyles='-', zorder=5)
        except Exception:
            pass
    return mesh


def _pe(fg='black', lw=2):
    return [path_effects.withStroke(linewidth=lw, foreground=fg)]


# ─────────────────────────────────────────────
# Individual map renderers
# ─────────────────────────────────────────────
def render_wide_map(lon_grid, lat_grid, precip, meta: dict,
                    lat_pin: float, lon_pin: float,
                    forecast_days: int) -> io.BytesIO:
    """Wide regional map with country + state borders."""
    fig, ax = plt.subplots(figsize=(12, 8), dpi=110, facecolor='#1a1a2e')
    fig.subplots_adjust(left=0.06, right=0.88, top=0.88, bottom=0.07)
    ax.set_facecolor('#0d0d1a')

    ext = (lon_grid.min(), lon_grid.max(), lat_grid.min(), lat_grid.max())
    mesh = _draw_precip(ax, lon_grid, lat_grid, precip)
    _draw_borders(ax, ext)

    ax.plot(lon_pin, lat_pin, marker='*', color='yellow', markersize=15,
            markeredgecolor='black', markeredgewidth=1.0, zorder=10)
    ax.text(lon_pin + 0.35, lat_pin + 0.35,
            f"  {meta['point_mm']:.1f} mm",
            fontsize=10, color='white', fontweight='bold', zorder=11,
            path_effects=_pe())

    ax.set_xlim(ext[0], ext[1])
    ax.set_ylim(ext[2], ext[3])
    ax.set_xlabel('Longitude', fontsize=8, color='#aaaaaa')
    ax.set_ylabel('Latitude',  fontsize=8, color='#aaaaaa')
    ax.tick_params(colors='#aaaaaa', labelsize=7)
    ax.grid(color='#444466', alpha=0.3, linestyle='--', linewidth=0.4)
    ax.spines[:].set_edgecolor('#444466')

    period_label = f"{forecast_days} dia{'s' if forecast_days > 1 else ''}"
    ax.set_title(
        f"ECMWF IFS — Precipitação Acumulada {period_label}  |  F{meta['step_h']:03d}\n"
        f"Início: {meta['init_time']}   Válido: {meta['valid_time']}",
        loc='left', fontsize=11, fontweight='bold', color='white', pad=10
    )

    cbar_ax = fig.add_axes([0.895, 0.07, 0.016, 0.78])
    cb = fig.colorbar(mesh, cax=cbar_ax, extend='max',
                      ticks=[0, 5, 10, 20, 30, 50, 70, 100, 150, 200, 300])
    cb.set_label('Precipitação Acumulada (mm)', fontsize=8, color='white', labelpad=8)
    cb.ax.tick_params(colors='white', labelsize=7)
    cb.outline.set_edgecolor('#444466')

    fig.text(0.5, 0.01,
             f"ECMWF Open Data IFS · 0.25° (~28 km) · Máx: {meta['max_mm']:.1f} mm",
             ha='center', va='bottom', fontsize=7.5, color='#888888')

    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight',
                facecolor=fig.get_facecolor(), dpi=110)
    buf.seek(0)
    plt.close(fig)
    return buf


def render_close_map(lon_grid, lat_grid, precip, meta: dict,
                     lat_pin: float, lon_pin: float,
                     forecast_days: int,
                     polygon_geojson: str | None = None) -> io.BytesIO:
    """Close-up map with property pin and optional CAR polygon."""
    fig, ax = plt.subplots(figsize=(10, 9), dpi=110, facecolor='#1a1a2e')
    fig.subplots_adjust(left=0.08, right=0.88, top=0.88, bottom=0.07)
    ax.set_facecolor('#0d0d1a')

    ext = (lon_grid.min(), lon_grid.max(), lat_grid.min(), lat_grid.max())
    mesh = _draw_precip(ax, lon_grid, lat_grid, precip, draw_contours=False)
    _draw_borders(ax, ext)

    # CAR polygon
    if polygon_geojson:
        try:
            geom = shape(json.loads(polygon_geojson))
            if geom.geom_type == 'Polygon':
                coords = list(geom.exterior.coords)
            elif geom.geom_type == 'MultiPolygon':
                coords = list(max(geom.geoms, key=lambda g: g.area).exterior.coords)
            else:
                coords = None
            if coords:
                xs, ys = zip(*coords)
                ax.plot(xs, ys, color='#FFD700', linewidth=2.2, linestyle='-', zorder=8)
                ax.fill(xs, ys, alpha=0.12, color='#FFD700', zorder=7)
        except Exception as e:
            logger.warning(f"Could not draw polygon: {e}")

    # Property pin
    ax.plot(lon_pin, lat_pin, marker='*', color='yellow', markersize=18,
            markeredgecolor='black', markeredgewidth=1.5, zorder=10)

    # Value box
    ax.text(0.97, 0.05, f"📍 {meta['point_mm']:.1f} mm",
            transform=ax.transAxes, ha='right', va='bottom',
            fontsize=14, fontweight='bold', color='#FFD700',
            path_effects=_pe(lw=4), zorder=12)

    ax.set_xlim(ext[0], ext[1])
    ax.set_ylim(ext[2], ext[3])
    ax.set_xlabel('Longitude', fontsize=8, color='#aaaaaa')
    ax.set_ylabel('Latitude',  fontsize=8, color='#aaaaaa')
    ax.tick_params(colors='#aaaaaa', labelsize=7)
    ax.grid(color='#444466', alpha=0.3, linestyle='--', linewidth=0.4)
    ax.spines[:].set_edgecolor('#444466')

    period_label = f"{forecast_days} dia{'s' if forecast_days > 1 else ''}"
    ax.set_title(
        f"Detalhe da Propriedade — {period_label} acumulado\n"
        f"Perím. CAR {'✅ plotado' if polygon_geojson else '⬜ não disponível'}",
        loc='left', fontsize=11, fontweight='bold', color='white', pad=10
    )

    cbar_ax = fig.add_axes([0.895, 0.07, 0.016, 0.78])
    cb = fig.colorbar(mesh, cax=cbar_ax, extend='max',
                      ticks=[0, 5, 10, 20, 30, 50, 70, 100, 150, 200, 300])
    cb.set_label('Precipitação Acumulada (mm)', fontsize=8, color='white', labelpad=8)
    cb.ax.tick_params(colors='white', labelsize=7)
    cb.outline.set_edgecolor('#444466')

    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight',
                facecolor=fig.get_facecolor(), dpi=110)
    buf.seek(0)
    plt.close(fig)
    return buf


# ─────────────────────────────────────────────
# Public API entry point  
# ─────────────────────────────────────────────
def generate_single_map(lat: float, lon: float, forecast_days: int,
                        view: str = 'wide',
                        polygon_geojson: str | None = None) -> io.BytesIO:
    """
    Download ECMWF data and render a single map (wide or close).
    `view` must be 'wide' or 'close'.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        grib_path = download_ecmwf_precip(forecast_days, tmpdir)

        if view == 'wide':
            lon_g, lat_g, prec, meta = load_regional_data(
                grib_path, lat, lon, span=25.0)
            return render_wide_map(lon_g, lat_g, prec, meta, lat, lon, forecast_days)
        else:  # close
            lon_g, lat_g, prec, meta = load_regional_data(
                grib_path, lat, lon, span=1.0)
            return render_close_map(lon_g, lat_g, prec, meta, lat, lon,
                                    forecast_days, polygon_geojson=polygon_geojson)


# Keep for backward compat
def generate_forecast_map(lat: float, lon: float, forecast_days: int,
                          polygon_geojson: str | None = None) -> io.BytesIO:
    return generate_single_map(lat, lon, forecast_days, 'wide', polygon_geojson)

