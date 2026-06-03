"""
ndvi_alerts.py
Automated NDVI alert scanner that runs every 12 hours.

For each registered FavoriteLocation with ndvi_alerts_enabled=True:
- Fetches the latest cloud-free Sentinel-2 image FOR THE POLYGON (not scene-level)
- Compares image date with last_ndvi_date stored in DB
- If newer: generates NDVI composite image and sends it via Telegram OR WhatsApp
- Updates last_ndvi_date in DB
"""

import asyncio
import logging
from datetime import datetime

from app.models import SessionLocal, FavoriteLocation, User, log_activity
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
    Dispatches to Telegram or WhatsApp based on user platform.
    """
    chat_id = loc.user_id
    loop = asyncio.get_running_loop()

    print(f"[NDVI ALERT] Checking '{loc.name}' ({loc.latitude:.4f}, {loc.longitude:.4f})", flush=True)

    # 1. Fetch CAR geometry (sync → executor)
    geometry, car_status, cod_imovel = await loop.run_in_executor(
        None, fetch_car_perimeter, loc.latitude, loc.longitude
    )

    # 2. Query GEE for latest cloud-free image DATE
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
        f"_Alertas automáticos a cada 12h_"
    )

    # 6. Determine user platform and send accordingly
    photo = image_buffer if image_buffer else analysis.get("ndvi_img")

    # Check which platform this user registered on
    user = session.query(User).filter(User.chat_id == str(chat_id)).first()
    platform = user.platform if user else 'telegram'

    sent_success = False
    send_error = None

    if platform == 'whatsapp':
        # ===== WHATSAPP =====
        try:
            from app.whatsapp.sender import (
                send_whatsapp_text,
                send_whatsapp_image_by_id,
                send_whatsapp_template_alert,
                _upload_media
            )
            from app.models import log_activity
            
            # WhatsApp uses different bold syntax, remove Markdown underscores
            wa_caption = caption.replace('_', '')
            
            success = False
            used_template = False
            
            if photo:
                # 1. Faz o upload da imagem apenas UMA vez
                print(f"[NDVI ALERT] Realizando upload único de mídia para {chat_id}...", flush=True)
                media_id = _upload_media(photo, "image/png", "map.png")
                
                if media_id:
                    # 2. Tenta o envio livre com o media_id obtido
                    print(f"[NDVI ALERT] Tentando envio livre de imagem para {chat_id}...", flush=True)
                    success = send_whatsapp_image_by_id(str(chat_id), media_id, wa_caption)
                    
                    if not success:
                        # 3. Fallback: Se falhar (ex: janela 24h), tenta o template usando o MESMO media_id
                        print(f"[NDVI ALERT] ⚠️ Envio livre falhou (janela 24h). Tentando Template com media_id existente...", flush=True)
                        success = send_whatsapp_template_alert(
                            to_phone=str(chat_id),
                            media_id=media_id,
                            prop_nome=loc.name,
                            data_str=date_str,
                            ndvi_val=f"{ndvi_val:.2f}"
                        )
                        used_template = True
                else:
                    print(f"[NDVI ALERT] ❌ Upload de imagem falhou. Tentando enviar apenas texto...", flush=True)
                    success = send_whatsapp_text(str(chat_id), wa_caption)
            else:
                success = send_whatsapp_text(str(chat_id), wa_caption)
                
            if success:
                channel_str = "Template" if used_template else "Livre"
                print(f"[NDVI ALERT] ✅ Enviado com sucesso via WhatsApp ({channel_str}) para {chat_id} | '{loc.name}'.", flush=True)
                sent_success = True
                log_activity(
                    chat_id=chat_id,
                    action="NDVI_ALERT_SEND",
                    platform="whatsapp",
                    details=f"Propriedade: {loc.name} ({channel_str})",
                    status="SUCCESS",
                    trigger_type="AUTO_ALERT"
                )
            else:
                print(f"[NDVI ALERT] ❌ Falha no envio para WhatsApp {chat_id} (ambos canais falharam).", flush=True)
                log_activity(
                    chat_id=chat_id,
                    action="NDVI_ALERT_SEND",
                    platform="whatsapp",
                    details=f"Propriedade: {loc.name}",
                    status="ERROR",
                    error_message="Envio livre e template falharam (restrição Meta ou template ausente)",
                    trigger_type="AUTO_ALERT"
                )
                
        except Exception as e:
            err_msg = str(e)
            print(f"[NDVI ALERT] ❌ WhatsApp send error for {chat_id}: {err_msg}", flush=True)
            try:
                from app.models import log_activity
                log_activity(
                    chat_id=chat_id,
                    action="NDVI_ALERT_SEND",
                    platform="whatsapp",
                    details=f"Propriedade: {loc.name}",
                    status="ERROR",
                    error_message=f"Crash no fluxo: {err_msg}",
                    trigger_type="AUTO_ALERT"
                )
            except Exception:
                pass
    else:
        # ===== TELEGRAM =====
        try:
            if photo:
                await application.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=caption,
                    parse_mode="Markdown",
                )
                print(f"[NDVI ALERT] ✅ Sent to Telegram {chat_id} for '{loc.name}'.", flush=True)
            else:
                await application.bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    parse_mode="Markdown",
                )
                print(f"[NDVI ALERT] ✅ Sent text to Telegram {chat_id} for '{loc.name}'.", flush=True)
            sent_success = True
        except Exception as e:
            send_error = str(e)
            print(f"[NDVI ALERT] ❌ Telegram send error for {chat_id}: {e}", flush=True)

        log_activity(
            str(chat_id),
            "NDVI_ALERT",
            platform="telegram",
            details=f"{loc.name} | image_date={image_date}",
            status="SUCCESS" if sent_success else "ERROR",
            error_message=send_error,
            trigger_type="AUTO_ALERT",
        )

    # 7. Persist new date
    if not sent_success:
        print(
            f"[NDVI ALERT] Not updating last_ndvi_date for '{loc.name}' because delivery failed.",
            flush=True,
        )
        return

    loc.last_ndvi_date = image_date
    session.commit()
