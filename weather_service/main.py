"""
main.py — FastAPI entry point for the ECMWF Weather Forecast Microservice.
Exposes a single endpoint: GET /forecast → PNG image bytes.
"""
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from forecast import generate_forecast_map

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ECMWF Weather Forecast Service", version="1.0.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/forecast")
def get_forecast(lat: float, lon: float, days: int = 5):
    """
    Returns a PNG image of the ECMWF precipitation forecast for the given
    location and accumulation period.

    Args:
        lat:  Latitude of the property/location
        lon:  Longitude of the property/location
        days: Accumulation period in days — must be 1, 5, or 10
    """
    if days not in (1, 5, 10):
        raise HTTPException(status_code=400, detail="days must be 1, 5, or 10")
    
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Invalid lat/lon coordinates")
    
    logger.info(f"Forecast request: lat={lat}, lon={lon}, days={days}")
    
    try:
        png_buf = generate_forecast_map(lat=lat, lon=lon, forecast_days=days)
    except Exception as e:
        logger.error(f"Forecast generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Forecast generation failed: {str(e)}")
    
    return StreamingResponse(
        png_buf,
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename=forecast_{days}d.png"}
    )
