"""
Handler de TRIGGER_FLOW para WhatsApp.
Executa os pipelines visuais (NDVI, CLIMA, MDT, HISTORICO) e envia
os resultados via WhatsApp Cloud API.
"""
import asyncio
from datetime import datetime
from app.whatsapp.sender import send_whatsapp_text, send_whatsapp_image, send_whatsapp_video


async def handle_wa_trigger_flow(sender_phone: str, trigger_string: str):
    """
    Processa um TRIGGER_FLOW retornado pelo agente e envia os resultados via WhatsApp.
    
    trigger_string: "TRIGGER_FLOW: NDVI | -20.96 | -54.85 | Faz Santa Fé"
    """
    try:
        # Parse
        parts = trigger_string.replace("TRIGGER_FLOW:", "").strip().split("|")
        parts = [p.strip() for p in parts]
        
        if len(parts) < 3:
            send_whatsapp_text(sender_phone, "⚠️ Comando inválido. Tente novamente.")
            return
        
        fluxo = parts[0].upper()
        lat = float(parts[1])
        lon = float(parts[2])
        nome = parts[3] if len(parts) > 3 else "Local Selecionado"
        
        print(f"[WA TRIGGER] Executando: {fluxo} | lat={lat} | lon={lon} | nome={nome}", flush=True)
        
        loop = asyncio.get_running_loop()
        
        # Avisa que está processando
        send_whatsapp_text(sender_phone, f"⏳ Processando {fluxo}... Aguarde um momento.")
        
        if fluxo == 'NDVI':
            await _handle_ndvi(sender_phone, lat, lon, nome, loop)
        elif fluxo == 'CLIMA':
            await _handle_clima(sender_phone, lat, lon, nome, loop)
        elif fluxo == 'HISTORICO':
            await _handle_historico(sender_phone, lat, lon, nome, loop)
        elif fluxo == 'MDT':
            await _handle_mdt(sender_phone, lat, lon, nome, loop)
        else:
            send_whatsapp_text(sender_phone, f"⚠️ Fluxo '{fluxo}' não reconhecido.")
        
    except Exception as e:
        import traceback
        print(f"[WA TRIGGER ERROR] {traceback.format_exc()}", flush=True)
        send_whatsapp_text(sender_phone, f"⚠️ Erro ao processar: {str(e)[:200]}")


async def _handle_ndvi(phone, lat, lon, nome, loop):
    """Pipeline NDVI → envia mapa via WhatsApp."""
    from app.environmental import fetch_car_perimeter, get_ndvi_analysis, generate_environmental_image
    
    # 1. Perímetro
    geometry, car_status = await loop.run_in_executor(None, fetch_car_perimeter, lat, lon)
    
    # 2. NDVI
    ndvi_result = await loop.run_in_executor(None, get_ndvi_analysis, geometry)
    if not ndvi_result:
        send_whatsapp_text(phone, "⚠️ Não foi possível obter dados NDVI para esta área.")
        return
    
    ndvi_val = ndvi_result.get('stats', {}).get('mean', 0)
    
    # 3. Gerar imagem
    img = await loop.run_in_executor(
        None, generate_environmental_image,
        ndvi_result['ndvi_img'], geometry, car_status, ndvi_result.get('region_bbox'), nome, (lat, lon)
    )
    
    if not img:
        send_whatsapp_text(phone, f"🌿 NDVI médio de {nome}: {ndvi_val:.2f}\n(Imagem indisponível)")
        return
    
    # 4. Classificação
    if ndvi_val >= 0.7:
        classe = "🟢 Excelente"
    elif ndvi_val >= 0.5:
        classe = "🟡 Bom"
    elif ndvi_val >= 0.3:
        classe = "🟠 Regular"
    else:
        classe = "🔴 Crítico"
    
    caption = (
        f"🌿 Mapa NDVI — {nome}\n"
        f"📊 NDVI Médio: {ndvi_val:.2f} ({classe})\n"
        f"📡 Fonte: Sentinel-2 / Google Earth Engine"
    )
    if car_status == 'OFFICIAL':
        caption += "\n✅ Perímetro: CAR Oficial"
    elif car_status == 'NEARBY':
        caption += "\n⚠️ Perímetro: Propriedade Próxima"
    
    send_whatsapp_image(phone, img, caption)
    print("[WA TRIGGER] NDVI enviado com sucesso!", flush=True)


async def _handle_clima(phone, lat, lon, nome, loop):
    """Pipeline Previsão de Chuva → envia mapa via WhatsApp."""
    from app.environmental import fetch_car_perimeter
    from app.weather import get_forecast_image
    import json as _json
    
    # 1. Perímetro (para overlay no mapa)
    polygon = None
    try:
        car_result = await loop.run_in_executor(None, fetch_car_perimeter, lat, lon)
        if car_result and car_result[0]:
            polygon = _json.dumps(car_result[0])
    except Exception:
        pass
    
    # 2. Previsão ECMWF
    wide_buf, close_buf, err_detail = await loop.run_in_executor(
        None, get_forecast_image, lat, lon, 5, polygon
    )
    
    sent = False
    if wide_buf:
        send_whatsapp_image(phone, wide_buf, f"🌎 Previsão ECMWF — 5 dias\n📍 {nome}")
        sent = True
    if close_buf:
        send_whatsapp_image(phone, close_buf, f"🏡 Detalhe da previsão\nRes: 0.25° | ECMWF Open Data")
        sent = True
    
    if not sent:
        detail = f"\n{err_detail[:200]}" if err_detail else ""
        send_whatsapp_text(phone, f"❌ Não foi possível gerar a previsão.{detail}")
    else:
        print("[WA TRIGGER] CLIMA enviado com sucesso!", flush=True)


async def _handle_historico(phone, lat, lon, nome, loop):
    """Pipeline Histórico de Chuva → envia dados + heatmap via WhatsApp."""
    from app.weather import get_precipitation_data, generate_weather_map_with_title
    
    # 1. Dados de precipitação
    data = await loop.run_in_executor(None, get_precipitation_data, lat, lon)
    if not data:
        send_whatsapp_text(phone, "❌ Erro ao buscar dados meteorológicos.")
        return
    
    # 2. Texto
    precip_val = data.get('last_24h', 0)
    msg = f"🌧️ Dados de Precipitação\n"
    msg += f"📍 Local: {nome}\n"
    msg += f"🕒 Últimas 24h: {precip_val:.1f} mm\n\n"
    msg += f"📅 Histórico Recente (Últimos 7 dias):\n"
    for date_val, val in data.get('daily_history', []):
        d_fmt = datetime.strptime(date_val, '%Y-%m-%d').strftime('%d/%m')
        msg += f"• {d_fmt}: {val:.1f} mm\n"
    
    # 3. Heatmap regional (GEE)
    heatmap = None
    try:
        from app.gee_connector import get_precipitation_heatmap
        heatmap = await loop.run_in_executor(None, get_precipitation_heatmap, lat, lon)
    except Exception:
        pass
    
    if heatmap:
        heatmap_photo = heatmap.get('buffer') or heatmap.get('image_url')
        if heatmap_photo:
            try:
                send_whatsapp_image(
                    phone, heatmap_photo,
                    "🌍 Precipitação Acumulada — 30 dias | Brasil"
                )
            except Exception:
                pass
    
    # 4. Mapa estático
    map_image = await loop.run_in_executor(None, generate_weather_map_with_title, lat, lon, nome)
    
    if map_image:
        send_whatsapp_image(phone, map_image, msg)
    else:
        send_whatsapp_text(phone, msg)
    
    print("[WA TRIGGER] Histórico enviado com sucesso!", flush=True)


async def _handle_mdt(phone, lat, lon, nome, loop):
    """Pipeline MDT → envia mapa 2D + vídeo 3D via WhatsApp."""
    from app.environmental import fetch_car_perimeter
    from app.gee_connector import get_terrain_data
    from app.environmental import generate_terrain_image_2d, generate_terrain_image_3d
    
    # 1. Perímetro
    geometry, car_status = await loop.run_in_executor(None, fetch_car_perimeter, lat, lon)
    
    # 2. Dados de terreno
    terrain_data = await loop.run_in_executor(None, get_terrain_data, geometry)
    if not terrain_data:
        send_whatsapp_text(phone, "⚠️ Não foi possível obter dados de elevação.")
        return
    
    source = terrain_data.get('source', 'DEM')
    elev_min = terrain_data.get('elev_min', 0)
    elev_max = terrain_data.get('elev_max', 0)
    
    # 3. Imagem 2D
    img_2d = await loop.run_in_executor(
        None, generate_terrain_image_2d,
        terrain_data, geometry, car_status, nome, (lat, lon)
    )
    
    if img_2d:
        caption_2d = (
            f"🏔️ Mapa de Curvas de Nível\n"
            f"📍 {nome}\n"
            f"📏 Altitude: {elev_min:.0f}m – {elev_max:.0f}m\n"
            f"🗺️ Curvas: 5m (finas) / 50m (grossas)\n"
            f"📡 Fonte: {source}"
        )
        send_whatsapp_image(phone, img_2d, caption_2d)
    
    # 4. Vídeo 3D
    img_3d = await loop.run_in_executor(
        None, generate_terrain_image_3d,
        terrain_data, geometry, car_status, nome, (lat, lon)
    )
    
    if img_3d:
        caption_3d = (
            f"🏔️ Modelo 3D do Terreno\n"
            f"📍 {nome}\n"
            f"🛰️ Textura: Sentinel-2 RGB\n"
            f"📡 DEM: {source}"
        )
        send_whatsapp_video(phone, img_3d, caption_3d)
    
    if not img_2d and not img_3d:
        send_whatsapp_text(phone, "❌ Não foi possível gerar as imagens MDT.")
    else:
        print("[WA TRIGGER] MDT enviado com sucesso!", flush=True)
