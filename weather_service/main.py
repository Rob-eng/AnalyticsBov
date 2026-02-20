"""
main.py — FastAPI entry point for the ECMWF Weather Forecast Microservice.
Exposes a single endpoint: GET /forecast → PNG image bytes.
"""
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from forecast import generate_forecast_map, generate_single_map

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ECMWF Weather Forecast Service", version="1.0.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/forecast")
def get_forecast(lat: float, lon: float, days: int = 5,
                 view: str = "wide", polygon: str = None):
    """
    Returns a single PNG for either the wide or close view.
    Call twice (view=wide, view=close) to get both images separately.

    Args:
        lat:     Latitude of property
        lon:     Longitude of property
        days:    Accumulation period — 1, 5, or 10
        view:    'wide' (regional, country+state borders) or 'close' (property detail)
        polygon: Optional GeoJSON geometry string for the CAR property perimeter
    """
    if days not in (1, 5, 10):
        raise HTTPException(status_code=400, detail="days must be 1, 5, or 10")
    if view not in ("wide", "close"):
        raise HTTPException(status_code=400, detail="view must be 'wide' or 'close'")
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Invalid lat/lon coordinates")

    logger.info(f"Forecast request: lat={lat}, lon={lon}, days={days}, "
                f"view={view}, polygon={'yes' if polygon else 'no'}")

    try:
        png_buf = generate_single_map(lat=lat, lon=lon, forecast_days=days,
                                      view=view, polygon_geojson=polygon)
    except Exception as e:
        logger.error(f"Forecast generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500,
                            detail=f"Forecast generation failed: {str(e)}")

    return StreamingResponse(
        png_buf,
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename=forecast_{view}_{days}d.png"}
    )
