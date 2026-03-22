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
        
        fluxo = parts[0].upper()
        
        if fluxo == 'MENU':
            from app.whatsapp.sender import send_whatsapp_menu
            send_whatsapp_menu(sender_phone)
            return

        if fluxo == 'COTACAO':
            loop = asyncio.get_running_loop()
            await _handle_cotacao(sender_phone, loop)
            return
            
        if fluxo == 'MERCADO_FUTURO':
            loop = asyncio.get_running_loop()
            await _handle_mercado_futuro(sender_phone, loop)
            return

        if fluxo == 'PREMIUM':
            from app.models import log_activity
            log_activity(sender_phone, "PREMIUM_CHECK", details="User viewing plans")
            await _handle_premium(sender_phone)
            return

        if len(parts) < 3:
            send_whatsapp_text(sender_phone, "⚠️ Comando inválido. Tente novamente.")
            return
            
        lat = float(parts[1])
        lon = float(parts[2])
        nome = parts[3] if len(parts) > 3 else "Local Selecionado"
        
        print(f"[WA TRIGGER] Executando: {fluxo} | lat={lat} | lon={lon} | nome={nome}", flush=True)
        
        loop = asyncio.get_running_loop()
        
        # Avisa que está processando
        send_whatsapp_text(sender_phone, f"⏳ Processando {fluxo}... Aguarde um momento.")
        
        from app.models import log_activity
        
        if fluxo in ['NDVI', 'CLIMA', 'HISTORICO', 'MDT']:
            from app.saas.limit_engine import can_perform_action
            can_do, msg_limit = can_perform_action(sender_phone, 'LOOKUP')
            if not can_do:
                send_whatsapp_text(sender_phone, msg_limit)
                await _handle_premium(sender_phone)
                return

        if fluxo == 'NDVI':
            log_activity(sender_phone, "NDVI", details=f"{nome} ({lat},{lon})")
            await _handle_ndvi(sender_phone, lat, lon, nome, loop)
        elif fluxo == 'CLIMA':
            log_activity(sender_phone, "CLIMA", details=f"{nome} ({lat},{lon})")
            await _handle_clima(sender_phone, lat, lon, nome, loop)
        elif fluxo == 'HISTORICO':
            log_activity(sender_phone, "HISTORICO", details=f"{nome} ({lat},{lon})")
            await _handle_historico(sender_phone, lat, lon, nome, loop)
        elif fluxo == 'MDT':
            log_activity(sender_phone, "MDT", details=f"{nome} ({lat},{lon})")
            await _handle_mdt(sender_phone, lat, lon, nome, loop)
        else:
            send_whatsapp_text(sender_phone, f"⚠️ Fluxo '{fluxo}' não reconhecido.")
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[WA TRIGGER ERROR] {error_trace}", flush=True)
        
        from app.models import log_activity
        log_activity(sender_phone, "ERROR_TRIGGER", status='ERROR', error_message=str(e), details=trigger_string)
        
        # Busca nome do usuário no DB para notificação
        from app.models import SessionLocal, User
        db = SessionLocal()
        u = db.query(User).filter_by(chat_id=sender_phone).first()
        u_name = u.username if u and u.username else "Usuário Desconhecido"
        db.close()
        
        # Notifica o Admin via Telegram
        from app.notifications import notify_user_error
        notify_user_error(sender_phone, str(e), context=f"Fluxo: {trigger_string}", user_name=u_name)
        
        send_whatsapp_text(sender_phone, f"⚠️ Desculpe, tive um problema técnico ao processar seu pedido. O administrador já foi notificado e estamos verificando! 🛠️")


async def _handle_ndvi(phone, lat, lon, nome, loop):
    """Pipeline NDVI → envia mapa via WhatsApp."""
    from app.environmental import fetch_car_perimeter, get_ndvi_analysis, generate_environmental_image
    
    # 1. Perímetro
    geometry, car_status, cod_imovel = await loop.run_in_executor(None, fetch_car_perimeter, lat, lon)
    
    # Removed _send_car_zip_guide here (keep it only for registration)
    
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
    
    dt_obj = datetime.fromtimestamp(ndvi_result['dt'])
    date_str = dt_obj.strftime('%d/%m/%Y')
    
    caption = f"🌿 *Análise Ambiental*\n\n"
    caption += f"📅 *Data da Imagem:* {date_str}\n"
    caption += f"🛰️ *Índice NDVI Médio:* {ndvi_val:.2f}\n"

    if car_status == 'OFFICIAL' or car_status is True:
        caption += f"✅ *Perímetro:* CAR Oficial\n"
    elif car_status == 'NEARBY':
        caption += f"⚠️ *Perímetro:* Propriedade Próxima (<11km)\n"
    else:
        caption += f"⚠️ *Perímetro:* Área Estimada (1km²)\n"

    caption += f"🚜 *Uso do Solo (Estimado):* Vegetação/Campo\n\n"
    caption += "O NDVI varia de -1 a 1:\n"
    caption += "- > 0.6: Vegetação densa/saudável\n"
    caption += "- 0.2 a 0.5: Solo exposto/pastagem rala\n"
    caption += "- < 0.1: Água ou rocha\n\n"
    caption += "📡 *Fonte:* Sentinel-2 / Google Earth Engine"
    
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
        geometry, car_status, cod_imovel = await loop.run_in_executor(None, fetch_car_perimeter, lat, lon)
        if geometry:
            polygon = _json.dumps(geometry)
        # Removed _send_car_zip_guide here (keep it only for registration)
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
    
    msg += "\n📡 *Fonte:* Open-Meteo Weather API"
    
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

    # 5. Gráfico de barras
    from app.charts import generate_precipitation_chart
    chart_path = await loop.run_in_executor(None, generate_precipitation_chart, data.get('daily_history', []), f"Histórico de Chuva - {nome}")
    if chart_path:
        try:
            with open(chart_path, "rb") as f:
                chart_bytes = f.read()
            send_whatsapp_image(phone, chart_bytes, "📊 Gráfico de Chuva Diária (7 Dias)")
        except Exception as e:
            print(f"Error sending rain chart: {e}")
    
    print("[WA TRIGGER] Histórico enviado com sucesso!", flush=True)


async def _handle_mdt(phone, lat, lon, nome, loop):
    """Pipeline MDT → envia mapa 2D + vídeo 3D via WhatsApp."""
    from app.environmental import fetch_car_perimeter
    from app.gee_connector import get_terrain_data
    from app.environmental import generate_terrain_image_2d, generate_terrain_image_3d
    
    # 1. Perímetro
    geometry, car_status, cod_imovel = await loop.run_in_executor(None, fetch_car_perimeter, lat, lon)
    
    # Removed _send_car_zip_guide here (keep it only for registration)
    
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

async def _handle_cotacao(phone, loop):
    """Pipeline Cotação Atual → envia gráfico e tabela via WhatsApp."""
    send_whatsapp_text(phone, "🔄 Buscando dados e gerando análise... Aguarde um momento.")
    
    from app.scraper import run_scraping_cycle
    from app.models import get_recent_prices
    from app.charts import generate_chart
    from app.bot import format_chart_caption
    
    # 1. Scrape data
    data = await loop.run_in_executor(None, lambda: run_scraping_cycle(save=False))
    if not data:
        send_whatsapp_text(phone, "⚠️ Não foi possível coletar dados no momento.")
        return

    # 2. Get historical data and generate chart
    history_data = await loop.run_in_executor(None, get_recent_prices)
    chart_path = await loop.run_in_executor(None, lambda: generate_chart(history_data))
    
    if not chart_path:
        send_whatsapp_text(phone, "⚠️ Erro ao gerar o gráfico.")
        return

    # 3. Format caption
    note = "Nota: O gráfico reflete os dados históricos coletados. O texto acima contém os preços atuais extraídos agora."
    caption = format_chart_caption(data, title="Relatório Solicitado (Sob Demanda)", note=note)

    # 4. Send
    with open(chart_path, "rb") as f:
        img_bytes = f.read()

    send_whatsapp_image(phone, img_bytes, caption)
    print("[WA TRIGGER] Cotação enviada com sucesso!", flush=True)

async def _handle_mercado_futuro(phone, loop):
    """Pipeline Mercado Futuro → envia tabela via WhatsApp."""
    send_whatsapp_text(phone, "🔮 Coletando dados do Mercado Futuro (Scot Consultoria)... Aguarde.")
    
    from app.scraper import scrape_mercado_futuro
    from app.charts import generate_future_table
    
    # 1. Scrape data
    data_dict = await loop.run_in_executor(None, scrape_mercado_futuro)
    if not data_dict:
        send_whatsapp_text(phone, "⚠️ Não foi possível coletar os dados do Mercado Futuro no momento.")
        return

    # 2. Generate table image
    chart_path = await loop.run_in_executor(None, lambda: generate_future_table(data_dict))
    
    if not chart_path:
        send_whatsapp_text(phone, "⚠️ Erro ao gerar a tabela do Mercado Futuro.")
        return

    # 3. Format caption
    caption = (
        "🔮 *Mercado Futuro - Boi Gordo*\n\n"
        "Valores para os próximos vencimentos obtidos agora.\n\n"
        "*Fonte:* Scot Consultoria"
    )

    # 4. Send
    with open(chart_path, "rb") as f:
        img_bytes = f.read()

    send_whatsapp_image(phone, img_bytes, caption)
    print("[WA TRIGGER] Mercado futuro enviado com sucesso!", flush=True)

async def _send_car_zip_guide(phone, cod_imovel):
    """Envia instruções de como baixar o ZIP do CAR para gerar o mapa profissional."""
    msg = (
        f"📊 *Dica do AnalyticsBov (Relatório Pro)*\n\n"
        f"Patrão, identifiquei o código oficial desta área no SICAR:\n"
        f"👉 `{cod_imovel}`\n\n"
        f"Para gerar um *Mapa Profissional* (com escala, grades e legendas), siga este passo a passo:\n"
        f"1️⃣ Clique no link: https://consultapublica.car.gov.br/publico/imoveis/index\n"
        f"2️⃣ Cole o código acima no campo de busca.\n"
        f"3️⃣ Resolva o Captcha e faça o download do arquivo *ZIP* (Contendo Shapefiles).\n"
        f"4️⃣ Me envie o arquivo .zip aqui no chat!\n\n"
        f"Assim que receber, eu monto o seu mapa de alta qualidade. 🚜💨"
    )
    send_whatsapp_text(phone, msg)

async def process_whatsapp_zip_upload(phone, media_id):
    """Downloads ZIP, processes it, and sends the Pro Map."""
    from app.whatsapp.sender import download_whatsapp_media, send_whatsapp_text, send_whatsapp_image
    from app.environmental import process_car_zip
    from app.charts import generate_pro_car_map
    import asyncio
    
    loop = asyncio.get_running_loop()
    
    send_whatsapp_text(phone, "📥 Arquivo ZIP recebido! Iniciando a geração do seu *Relatório Profissional*... Aguarde.")
    
    # 1. Download
    zip_bytes = await loop.run_in_executor(None, download_whatsapp_media, media_id)
    if not zip_bytes:
        send_whatsapp_text(phone, "❌ Erro ao baixar o arquivo ZIP.")
        return

    # 2. Process ZIP (extract GDFs)
    gdfs, error = await loop.run_in_executor(None, process_car_zip, zip_bytes)
    if error:
        send_whatsapp_text(phone, f"⚠️ Erro ao processar o ZIP: {error}")
        return

    # 3. Buscar Imagens de Satélite (Main & Regional) via GEE
    bg_bytes, bg_extent = None, None
    reg_bg_bytes, reg_bg_extent = None, None
    try:
        main_gdf = gdfs.get('imovel')
        if main_gdf is not None:
            from app.gee_connector import get_satellite_thumbnail
            import json
            geom_json = json.loads(main_gdf.to_json())['features'][0]['geometry']
            
            # 3.1 Background Principal (~1.5km buffer)
            print(f"[WA] Buscando imagem de fundo principal...", flush=True)
            b_bounds = main_gdf.buffer(0.015).total_bounds
            bg_extent = [b_bounds[0], b_bounds[2], b_bounds[1], b_bounds[3]]
            turl = await loop.run_in_executor(None, get_satellite_thumbnail, geom_json, 1024, 1500)
            
            # 3.2 Background Regional (~10km buffer)
            print(f"[WA] Buscando imagem regional...", flush=True)
            r_bounds = main_gdf.buffer(0.10).total_bounds
            reg_bg_extent = [r_bounds[0], r_bounds[2], r_bounds[1], r_bounds[3]]
            rturl = await loop.run_in_executor(None, get_satellite_thumbnail, geom_json, 800, 10000)
            
            import requests
            if turl:
                print(f"[WA] Baixando Main Thumb: {turl[:60]}...", flush=True)
                # Correção: timeout deve ser passado como keyword argument no requests.get
                def download_main(): return requests.get(turl, timeout=30)
                resp = await loop.run_in_executor(None, download_main)
                if resp.status_code == 200: 
                    bg_bytes = resp.content
                    print(f"[WA] Main Background OK ({len(bg_bytes)} bytes)", flush=True)
                else:
                    print(f"[WA] Falha Main Background: Status {resp.status_code}", flush=True)
            if rturl:
                print(f"[WA] Baixando Regional Thumb: {rturl[:60]}...", flush=True)
                def download_reg(): return requests.get(rturl, timeout=30)
                rresp = await loop.run_in_executor(None, download_reg)
                if rresp.status_code == 200: 
                    reg_bg_bytes = rresp.content
                    print(f"[WA] Regional Background OK ({len(reg_bg_bytes)} bytes)", flush=True)
                else:
                    print(f"[WA] Falha Regional Background: Status {rresp.status_code}", flush=True)
                
    except Exception as ge:
        print(f"[WA] Erro GEE: {ge}", flush=True)

    # 4. Generate Pro Map
    map_bytes = await loop.run_in_executor(None, generate_pro_car_map, gdfs, bg_bytes, bg_extent, reg_bg_bytes, reg_bg_extent)
    if not map_bytes:
        send_whatsapp_text(phone, "⚠️ Erro ao renderizar o mapa profissional.")
        return

    # 5. Send back
    caption = (
        "🗺️ *RELATÓRIO AMBIENTAL PROFISSIONAL*\n\n"
        "Análise cartográfica completa gerada a partir do seu arquivo CAR.\n\n"
        "Desenvolvido por *Agro Analytics*"
    )
    send_whatsapp_image(phone, map_bytes, caption)
    print(f"[WA] Relatório Profissional enviado para {phone}", flush=True)


async def process_whatsapp_car_request(phone, car_code):
    """
    Fluxo do DESAFIO: 
    1. Recebe o código CAR puro via texto.
    2. Aciona o Scraper Fantasma (SICAR).
    3. Baixa o ZIP.
    4. Gera o Mapa Pro.
    """
    from app.whatsapp.sender import send_whatsapp_text, send_whatsapp_image
    from app.sicar_scraper import download_car_shapefile
    from app.environmental import process_car_zip
    from app.charts import generate_pro_car_map
    import asyncio
    
    loop = asyncio.get_running_loop()
    
    # 1. Avisa o início
    msg_init = (
        f"🔍 *Localizando imóvel na base do governo...*\n"
        f"Código: `{car_code}`\n\n"
        f"Estou resolvendo os sistemas de segurança (Captcha) e preparando seu mapa profissional. "
        f"Isso leva cerca de 20 a 40 segundos. ⏳"
    )
    send_whatsapp_text(phone, msg_init)
    
    # 2. Scraper (Download do ZIP)
    zip_bytes, error = await loop.run_in_executor(None, download_car_shapefile, car_code)
    
    if not zip_bytes:
        msg_err = (
            f"⚠️ *Não foi possível obter os dados oficiais agora.*\n\n"
            f"O servidor do governo (SICAR) está instável ou recusando conexões automáticas.\n\n"
            f"Vou monitorar e o senhor pode tentar novamente em alguns minutos. "
            f"Se tiver o arquivo .zip em mãos, pode me enviar aqui!"
        )
        send_whatsapp_text(phone, msg_err)
        return

    # 3. Processa o ZIP
    send_whatsapp_text(phone, "✅ *Dados vinculados!* Gerando seu relatório profissional... 🚜")
    
    gdfs, zip_err = await loop.run_in_executor(None, process_car_zip, zip_bytes)
    if zip_err:
        send_whatsapp_text(phone, f"⚠️ Erro ao processar dados do governo: {zip_err}")
        return

    # 4. Satélite e Mapa Pro (Reaproveita lógica do Zip Upload)
    bg_bytes, bg_extent = None, None
    reg_bg_bytes, reg_bg_extent = None, None
    try:
        main_gdf = gdfs.get('imovel')
        if main_gdf is not None:
            from app.gee_connector import get_satellite_thumbnail
            import json
            import requests
            geom_json = json.loads(main_gdf.to_json())['features'][0]['geometry']
            
            # Backgrounds
            b_bounds = main_gdf.buffer(0.015).total_bounds
            bg_extent = [b_bounds[0], b_bounds[2], b_bounds[1], b_bounds[3]]
            turl = await loop.run_in_executor(None, get_satellite_thumbnail, geom_json, 1024, 1500)
            
            r_bounds = main_gdf.buffer(0.10).total_bounds
            reg_bg_extent = [r_bounds[0], r_bounds[2], r_bounds[1], r_bounds[3]]
            rturl = await loop.run_in_executor(None, get_satellite_thumbnail, geom_json, 800, 10000)
            
            if turl:
                resp = await loop.run_in_executor(None, lambda: requests.get(turl, timeout=30))
                if resp.status_code == 200: bg_bytes = resp.content
            if rturl:
                rresp = await loop.run_in_executor(None, lambda: requests.get(rturl, timeout=30))
                if rresp.status_code == 200: reg_bg_bytes = rresp.content
    except Exception as ge:
        print(f"[WA CAR REQ] Erro GEE: {ge}", flush=True)

    # 5. Renderiza Mapa Pro
    map_bytes = await loop.run_in_executor(None, generate_pro_car_map, gdfs, bg_bytes, bg_extent, reg_bg_bytes, reg_bg_extent)
    if not map_bytes:
        send_whatsapp_text(phone, "⚠️ Erro ao renderizar o mapa final.")
        return

    # 6. Envio Final
    caption = (
        f"🗺️ *RELATÓRIO AMBIENTAL AUTOMÁTICO*\n\n"
        f"🚀 *Extração Fantasma Concluída!*\n"
        f"📍 Imóvel: `{car_code}`\n\n"
        f"Este mapa foi gerado buscando os dados direto na fonte do governo. "
        f"Tudo pronto para sua análise! 🐂💨"
    )
    send_whatsapp_image(phone, map_bytes, caption)
    print(f"[WA CAR REQ] Processo finalizado para {phone}", flush=True)

async def _handle_premium(phone):
    """Apresenta os planos de assinatura no WhatsApp com links de pagamento."""
    msg = (
        "💎 *Planos e Assinaturas — AnalyticsBov*\n\n"
        "Patrão, turbine sua experiência com inteligência de ponta:\n\n"
        "🥉 *Plano Bronze (Grátis)*\n"
        "- 1 Fazenda cadastrada.\n"
        "- 3 Consultas por mês.\n"
        "- 1 Alerta de satélite por mês.\n\n"
        "🥈 *Plano Starter* (Monitoramento Base)\n"
        "- 3 Fazendas cadastradas.\n"
        "- 10 Consultas por mês.\n"
        "- *Alertas Ilimitados* toda vez que o satélite passar!\n"
        "👉 [Assinar Mensal](https://analyticsbov-production.up.railway.app/billing/checkout/STARTER_MONTHLY/" + phone + ")\n"
        "👉 [Assinar Anual (Desconto)](https://analyticsbov-production.up.railway.app/billing/checkout/STARTER_YEARLY/" + phone + ")\n\n"
        "🥇 *Plano Ouro (PRO)* (Equipes — Até 3 Usuários)\n"
        "- *Consultas e Alertas ILIMITADOS*.\n"
        "- Até 10 Fazendas cadastradas.\n"
        "- Suporte prioritário via WhatsApp.\n"
        "👉 [Assinar Mensal](https://analyticsbov-production.up.railway.app/billing/checkout/PRO_MONTHLY/" + phone + ")\n"
        "👉 [Assinar Anual (Desconto)](https://analyticsbov-production.up.railway.app/billing/checkout/PRO_YEARLY/" + phone + ")\n\n"
        "📈 *Planos Maiores:* Entre em contato com @robson_c para pacotes personalizados.\n\n"
        "_Segurança garantida via Stripe. Cancele quando quiser._"
    )
    send_whatsapp_text(phone, msg)
