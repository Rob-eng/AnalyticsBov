"""
forecast.py — ECMWF Open Data download + matplotlib map rendering.
Fetches the latest ECMWF IFS (ex-HRES) total precipitation forecast
and generates a regional PNG map in the style of IgorRoik/ECMWF.
"""
import os
import io
import tempfile
import logging
import pandas as pd
from datetime import datetime, timedelta, timezone

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patheffects as path_effects
from matplotlib.colors import BoundaryNorm, ListedColormap

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
# ECMWF IFS 0.25° provides 'tp' (total precip from t=0) at 6h steps.
# To get accumulated precip for N days we use step=N*24
DAYS_TO_STEP = {1: 24, 5: 120, 10: 240}


def download_ecmwf_precip(forecast_days: int, target_dir: str):
    """
    Downloads the latest ECMWF Open Data total precipitation GRIB file.
    Returns path of the downloaded file or raises on failure.
    """
    from ecmwf.opendata import Client

    step = DAYS_TO_STEP.get(forecast_days)
    if step is None:
        raise ValueError(f"forecast_days must be 1, 5, or 10. Got {forecast_days}")

    client = Client(source="ecmwf")

    # Find the latest available run (ECMWF publishes ~6h after run time)
    # Runs: 00 and 12 UTC. Default: latest.
    outfile = os.path.join(target_dir, f"ecmwf_tp_{forecast_days}d.grib2")
    
    logger.info(f"Downloading ECMWF tp step={step}h ...")
    client.retrieve(
        type="fc",
        param="tp",
        step=step,
        target=outfile,
    )
    logger.info(f"Downloaded: {outfile}")
    return outfile


def load_regional_data(grib_path: str, lat_center: float, lon_center: float, span: float = 8.0):
    """
    Loads data from GRIB2 and clips to a region around (lat_center, lon_center).
    Returns (lon_grid, lat_grid, precip_mm_grid, metadata_dict) or raises.
    """
    import xarray as xr

    # Open GRIB2 with xarray's cfgrib engine (works with current cfgrib versions)
    try:
        ds = xr.open_dataset(grib_path, engine='cfgrib')
    except Exception:
        # Some GRIB files have multiple messages; open_datasets returns a list
        import cfgrib
        datasets = cfgrib.open_datasets(grib_path)
        ds = datasets[0]

    tp = ds['tp']  # Shape: (lat, lon), unit: m

    # Convert to mm
    tp_mm = tp * 1000.0

    # Clip region
    lat_arr = tp.latitude.values
    lon_arr = tp.longitude.values

    # Normalize longitudes to [-180, 180] if needed (ECMWF uses 0-360)
    if lon_arr.max() > 180:
        lon_arr = np.where(lon_arr > 180, lon_arr - 360, lon_arr)

    lat_min = lat_center - span
    lat_max = lat_center + span
    lon_min = lon_center - span
    lon_max = lon_center + span

    lat_mask = (lat_arr >= lat_min) & (lat_arr <= lat_max)
    lon_mask = (lon_arr >= lon_min) & (lon_arr <= lon_max)

    tp_clipped = tp_mm.values[np.ix_(lat_mask, lon_mask)]
    lat_clip = lat_arr[lat_mask]
    lon_clip = lon_arr[lon_mask]

    lon_grid, lat_grid = np.meshgrid(lon_clip, lat_clip)

    # Point value at property location (nearest grid)
    lat_idx = np.argmin(np.abs(lat_arr - lat_center))
    lon_idx = np.argmin(np.abs(lon_arr - lon_center))
    point_mm = float(tp_mm.values[lat_idx, lon_idx])
    max_mm   = float(tp_mm.values.max())

    # Metadata
    try:
        valid_time = pd.Timestamp(tp.valid_time.values).strftime('%d/%b/%Y %HUTC')
        init_time  = pd.Timestamp(ds.time.values).strftime('%d/%b/%Y %HUTC')
    except Exception:
        valid_time = "N/A"
        init_time  = "N/A"

    meta = {
        "valid_time": valid_time,
        "init_time": init_time,
        "step_h": int(ds.step.values / np.timedelta64(1, 'h')),
        "point_mm": point_mm,
        "max_mm": max_mm,
    }

    return lon_grid, lat_grid, tp_clipped, meta


def render_map(lon_grid, lat_grid, precip, meta: dict,
               lat_pin: float, lon_pin: float, forecast_days: int) -> io.BytesIO:
    """
    Renders the precipitation map using matplotlib (no cartopy).
    Returns a BytesIO PNG buffer.
    """
    fig, ax = plt.subplots(figsize=(10, 8), dpi=110, facecolor='#f0f0f8')

    # Precipitation fill
    mesh = ax.pcolormesh(lon_grid, lat_grid, precip,
                         cmap=CMAP, norm=NORM,
                         shading='auto', rasterized=True)

    # Optional contours for high values
    try:
        ax.contour(lon_grid, lat_grid, precip,
                   levels=[100, 150, 200, 250, 300],
                   colors='maroon', linewidths=0.8, linestyles='-')
    except Exception:
        pass

    # Property pin
    ax.plot(lon_pin, lat_pin, marker='*', color='white', markersize=16,
            markeredgecolor='black', markeredgewidth=1.2, zorder=10)

    point_label = f"{meta['point_mm']:.1f} mm"
    ax.text(lon_pin + 0.15, lat_pin + 0.15, point_label,
            fontsize=10, fontweight='bold', color='white', zorder=11,
            path_effects=[path_effects.withStroke(linewidth=3, foreground='black')])

    # Colorbar
    cbar = fig.colorbar(mesh, ax=ax, orientation='vertical', pad=0.02,
                        shrink=0.80, aspect=40, extend='max',
                        ticks=BOUNDS[1::2])
    cbar.set_label('Precipitação Acumulada (mm)', fontsize=9)
    cbar.ax.tick_params(labelsize=8)

    # Grid lines
    ax.set_xlabel('Longitude', fontsize=9)
    ax.set_ylabel('Latitude', fontsize=9)
    ax.tick_params(labelsize=8)
    ax.grid(color='gray', alpha=0.3, linestyle='--', linewidth=0.5)

    # Title
    period_label = f"{forecast_days} dia{'s' if forecast_days > 1 else ''}"
    lead_label   = f"F{meta['step_h']:03d}"
    ax.set_title(
        f"ECMWF IFS — Precipitação Acumulada ({period_label}) | {lead_label}\n"
        f"Inic: {meta['init_time']}   |   Valid: {meta['valid_time']}",
        loc='left', fontsize=11, fontweight='bold', pad=14
    )

    # Max precip annotation
    ax.text(0.99, 0.01,
            f"Máx: {meta['max_mm']:.1f} mm  |  📍 Propriedade: {meta['point_mm']:.1f} mm",
            transform=ax.transAxes, ha='right', va='bottom',
            fontsize=9, color='white',
            bbox=dict(facecolor='#333333', alpha=0.85, edgecolor='none', pad=4),
            zorder=12)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return buf


def generate_forecast_map(lat: float, lon: float, forecast_days: int) -> io.BytesIO:
    """
    Full pipeline: download ECMWF → load regional data → render map → return PNG BytesIO.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        grib_path = download_ecmwf_precip(forecast_days, tmpdir)
        lon_grid, lat_grid, precip, meta = load_regional_data(grib_path, lat, lon)
        return render_map(lon_grid, lat_grid, precip, meta, lat, lon, forecast_days)
