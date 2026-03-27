"""
ndvi_alerts.py
Automated NDVI alert scanner that runs every 12 hours.

For each registered FavoriteLocation with ndvi_alerts_enabled=True:
- Fetches the latest cloud-free Sentinel-2 image FOR THE POLYGON (not scene-level)
- Compares image date with last_ndvi_date stored in DB
- If newer: generates NDVI composite image and sends it via Telegram
- Updates last_ndvi_date in DB
"""

import asyncio
import logging
from datetime import datetime

from app.models import SessionLocal, FavoriteLocation
from app.environmental import fetch_car_perimeter, get_ndvi_analysis, generate_environmental_image
from app.gee_connector import get_ndvi_image

logger = logging.getLogger(__name__)


async def run_ndvi_alert_scan(application):
    """
    Scan all registered properties for new Sentinel-2 imagery.
    Called by APScheduler every 12 hours.
    """
    print("[NDVI ALERT] Starting scheduled scan...", flush=True)
    session = SessionLocal()

    try:
        locations = (
            session.query(FavoriteLocation)
            .filter(FavoriteLocation.ndvi_alerts_enabled == True)  # noqa: E712
            .all()
        )
        print(f"[NDVI ALERT] {len(locations)} properties to check.", flush=True)

        for loc in locations:
            try:
                await _check_and_alert(application, session, loc)
            except Exception as e:
                print(f"[NDVI ALERT] Error on '{loc.name}': {e}", flush=True)
                logger.exception(f"NDVI alert error for location {loc.id}")

            # Polite delay between GEE calls — avoids rate-limit issues
            await asyncio.sleep(3)

    finally:
        session.close()

    print("[NDVI ALERT] Scan complete.", flush=True)


async def _check_and_alert(application, session, loc: FavoriteLocation):
    """
    Checks a single property for a new image and sends if found.
    Runs GEE in executor so it doesn't block the async event loop.
    """
    chat_id = loc.user_id
    loop = asyncio.get_running_loop()

    print(f"[NDVI ALERT] Checking '{loc.name}' ({loc.latitude:.4f}, {loc.longitude:.4f})", flush=True)

    # 1. Fetch CAR geometry (sync → executor)
    # returns (geometry, status, cod_imovel)
    geometry, car_status, cod_imovel = await loop.run_in_executor(
        None, fetch_car_perimeter, loc.latitude, loc.longitude
    )

    # 2. Query GEE for latest cloud-free image DATE (lightweight — metadata only)
    #    get_ndvi_image already filters clouds WITHIN the polygon via SCL band
    gee_meta = await loop.run_in_executor(None, get_ndvi_image, geometry)

    if not gee_meta:
        print(f"[NDVI ALERT] '{loc.name}': no usable image (cloud/coverage).", flush=True)
        return

    image_date = gee_meta.get("date")  # 'YYYY-MM-DD'

    if not image_date:
        return

    # 3. Compare with stored date
    if loc.last_ndvi_date and loc.last_ndvi_date >= image_date:
        print(f"[NDVI ALERT] '{loc.name}': no new image (latest={image_date}, stored={loc.last_ndvi_date}).", flush=True)
        return

    print(f"[NDVI ALERT] NEW image for '{loc.name}': {image_date} (was: {loc.last_ndvi_date})", flush=True)

    # 4. Full analysis + render
    analysis = await loop.run_in_executor(None, get_ndvi_analysis, geometry)
    if not analysis:
        print(f"[NDVI ALERT] '{loc.name}': analysis failed after new image detected.", flush=True)
        return

    ndvi_val = analysis.get("stats", {}).get("mean", 0) or 0
    cloud_pct = analysis.get("cloud_coverage", 0) or 0
    date_str = analysis.get("date_str", image_date)
    region_bbox = analysis.get("region_bbox")

    image_buffer = await loop.run_in_executor(
        None,
        generate_environmental_image,
        analysis["ndvi_img"],
        geometry,
        car_status,
        region_bbox,
        loc.name,
        (loc.latitude, loc.longitude),
    )

    # 5. Build caption
    ndvi_icon = (
        "🌿" if ndvi_val >= 0.5
        else "🌾" if ndvi_val >= 0.2
        else "🪨"
    )
    perimeter_label = (
        "✅ CAR Oficial" if car_status == "OFFICIAL"
        else "⚠️ Propriedade Próxima" if car_status == "NEARBY"
        else "⚠️ Área Estimada"
    )

    caption = (
        f"🛰️ *Nova imagem satelital detectada!*\n\n"
        f"📍 *Propriedade:* {loc.name}\n"
        f"📅 *Data da imagem:* {date_str}\n"
        f"{ndvi_icon} *NDVI Médio:* {ndvi_val:.2f}\n"
        f"☁️ *Nuvens no polígono:* {cloud_pct:.1f}%\n"
        f"🗺️ *Perímetro:* {perimeter_label}\n\n"
        f"_Alertas automáticos a cada 12h · /propriedades para gerenciar_"
    )

    # 6. Send via Telegram
    photo = image_buffer if image_buffer else analysis.get("ndvi_img")
    if photo:
        await application.bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            parse_mode="Markdown",
        )
        print(f"[NDVI ALERT] Sent to {chat_id} for '{loc.name}'.", flush=True)
    else:
        # Text-only fallback
        await application.bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode="Markdown",
        )

    # 7. Persist new date
    loc.last_ndvi_date = image_date
    session.commit()
