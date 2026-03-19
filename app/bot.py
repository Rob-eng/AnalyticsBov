from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from app.config import Config
from app.models import SessionLocal, User, get_recent_prices
from app.charts import generate_chart, generate_future_table
from app.weather import geocode_location, get_precipitation_data, get_static_map_url, parse_coordinates, extract_coords_from_url, get_forecast_image
from app.environmental import fetch_car_perimeter, get_ndvi_analysis, generate_environmental_image


import asyncio
from datetime import datetime


# Conversation states
WAITING_FEEDBACK = 1
WAITING_WEATHER_LOCATION = 2
WAITING_BROADCAST_MESSAGE = 3
WAITING_ENV_LOCATION = 4
WAITING_LOCATION_MENU = 5
WAITING_LOCATION_NAME = 6
WAITING_LOCATION_COORDS = 7
WAITING_LOCATION_DELETE = 8
WAITING_FORECAST_PERIOD = 9
WAITING_WEATHER_MODE = 10
WAITING_ENV_MODE = 11

MAIN_MENU_BUTTONS = [
    "📊 Cotação Atual", "🔮 Mercado Futuro", "🌧️ Precipitação (chuva)",
    "🌿 Análise Ambiental", "📢 Enviar Anúncio", "📈 Status",
    "📥 Importar Histórico", "👥 Lista de Usuários", "💬 Feedback",
    "📌 Minhas Propriedades"
]


def is_admin(chat_id):
    """Check if user is admin"""
    return str(chat_id) == str(Config.ADMIN_CHAT_ID)

def escape_markdown(text):
    """Helper to escape specialized characters for Telegram MarkdownV1"""
    if not text:
        return ""
    # Characters that need escaping: _ * [ `
    # Note: Telegram MarkdownV1 is quite picky. 
    return text.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`").replace("@", "\\@")

def get_keyboard(chat_id):
    """Get appropriate keyboard based on user role"""
    if is_admin(chat_id):
        keyboard = [
            [KeyboardButton("📊 Cotação Atual"), KeyboardButton("🔮 Mercado Futuro")],
            [KeyboardButton("🌧️ Precipitação (chuva)"), KeyboardButton("📈 Status")],
            [KeyboardButton("📌 Minhas Propriedades"), KeyboardButton("🌿 Análise Ambiental")],
            [KeyboardButton("📥 Importar Histórico"), KeyboardButton("👥 Lista de Usuários")],
            [KeyboardButton("📢 Enviar Anúncio"), KeyboardButton("💬 Feedback")]
        ]
    else:
        keyboard = [
            [KeyboardButton("📊 Cotação Atual"), KeyboardButton("🔮 Mercado Futuro")],
            [KeyboardButton("🌧️ Precipitação (chuva)"), KeyboardButton("📈 Status")],
            [KeyboardButton("📌 Minhas Propriedades"), KeyboardButton("🌿 Análise Ambiental")],
            [KeyboardButton("💬 Feedback")]
        ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    username = update.effective_chat.username
    
    session = SessionLocal()
    try:
        user = session.query(User).filter_by(chat_id=chat_id).first()
        
        welcome_msg = (
            "🐂 *Bem-vindo ao Agro Analytics Bot!*\n\n"
            "Seu assistente completo para o agronegócio, focado em mercado, clima e inteligência geoespacial.\n\n"
            "🚀 *Principais Funcionalidades:*\n\n"
            "📊 *Mercado e Cotações:*\n"
            "- Cotação atual do Boi Gordo no Mundo (/atual)\n"
            "- Acompanhamento do Mercado Futuro da B3 (/futuro)\n"
            "- Relatório automático toda segunda-feira às 8h.\n\n"
            "🌦️ *Clima e Previsão:*\n"
            "- Previsão de chuvas para 1/5/10 dias (/clima)\n"
            "- Histórico de chuvas espacializado (Heatmap)\n\n"
            "🌿 *Monitoramento por Satélite:*\n"
            "- *NDVI:* Análise de vigor vegetativo da pastagem\n"
            "- *Alertas:* Receba mapas NDVI automáticos assim que o satélite passar (sem nuvens)\n"
            "- *MDT:* Modelos Digitais de Terreno em 2D (curvas de nível) e 3D interativo\n"
            "- Sobreposição automática do perímetro CAR\n\n"
            "📌 *Suas Propriedades:*\n"
            "- Cadastre suas fazendas e receba análises com 1 clique.\n"
            "- Acesse o menu 'Minhas Propriedades' para ativar as notificações automáticas de satélite.\n\n"
            "_Desenvolvido por Robson Campos_ 👨‍💻"
        )
        
        if not user:
            new_user = User(chat_id=chat_id, username=username)
            session.add(new_user)
            session.commit()
            
            # Notify admin about new user
            if not is_admin(chat_id):
                try:
                    await context.bot.send_message(
                        chat_id=Config.ADMIN_CHAT_ID,
                        text=f"🆕 *Novo usuário cadastrado!*\n\nNome: @{username or 'Sem username'}\nID: `{chat_id}`",
                        parse_mode='Markdown'
                    )
                except:
                    pass
            
            await update.message.reply_text(
                welcome_msg,
                parse_mode='Markdown',
                reply_markup=get_keyboard(chat_id)
            )
        else:
            await update.message.reply_text(
                welcome_msg,
                parse_mode='Markdown',
                reply_markup=get_keyboard(chat_id)
            )
    except Exception as e:
        import traceback
        print(f"ERROR in start command (chat_id: {chat_id}): {e}")
        print(traceback.format_exc())
        try:
            await update.message.reply_text("⚠️ Ocorreu um erro ao registrar. Por favor, tente novamente em instantes.")
        except:
            pass
    finally:
        session.close()

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    session = SessionLocal()
    
    msg = "📊 *Diagnóstico do Sistema*\n\n"
    
    # 1. User Registration
    try:
        user = session.query(User).filter_by(chat_id=chat_id).first()
        status_txt = "ATIVO ✅" if user else "INATIVO ❌"
        msg += f"👤 *Cadastro:* {status_txt}\n"
    except Exception as e:
        msg += f"👤 *Cadastro:* ERRO ({str(e)}) ❌\n"
    finally:
        session.close()

    # 2. CAR Database Connection
    msg += "🗺️ *Banco de Dados CAR (Supabase):* "
    try:
        if not Config.CAR_DATABASE_URL:
             msg += "NÃO CONFIGURADO ⚠️\n_(Variável CAR_DATABASE_URL ausente)_\n"
        else:
            # Test direct connection
            try:
                from app.models import CarSessionLocal, CARProperty
                car_session = CarSessionLocal()
                count = car_session.query(CARProperty).count()
                car_session.close()
                msg += f"OK ✅ ({count} registros)\n"
            except Exception as e:
                msg += f"FALHA NA CONEXÃO ❌\n_Erro: {str(e)}_\n"
    except Exception as e:
        msg += f"ERRO GERAL ({str(e)}) ❌\n"

    # 3. Local API Health Check
    msg += "🔌 *API Local:* "
    try:
        import requests
        import os
        port = os.getenv("PORT", 8000)
        resp = requests.get(f"http://127.0.0.1:{port}/", timeout=3)
        if resp.status_code == 200:
            msg += "ONLINE ✅\n"
        else:
             msg += f"ERRO {resp.status_code} ❌\n"
    except Exception as e:
         msg += f"OFFLINE ❌\n_Erro: {str(e)}_\n"

    await update.message.reply_text(msg, parse_mode='Markdown')

def format_chart_caption(data, title="Cotação do Boi no Mundo", note=None):
    """Helper to format chart caption with prices and feedback CTA"""
    if not data:
        return f"📊 *{title}*\n\n💬 *Sua opinião é importante!* \nClique aqui para enviar um /feedback ou sugerir melhorias."
        
    date_str = data[0]['date'].strftime('%d/%m/%Y')
    caption = f"📊 *{title}* - {date_str}\n\n"
    
    # Sort data by price (descending)
    sorted_data = sorted(data, key=lambda x: x['price'], reverse=True)
    
    # Color mapping for emojis
    country_emojis = {
        'Brasil': '🟢',
        'Argentina': '🔵',
        'Uruguai': '🟠',
        'Paraguai': '🔴',
        'Austrália': '⚫️',
        'Australia': '⚫️',
        'Irlanda': '🟣',
        'Estados Unidos': '🟡',
        'China': '🔴'
    }
    
    for item in sorted_data:
        # Normalize price display
        price = item['price']
        country = item['country']
        emoji = country_emojis.get(country, '📍')
        caption += f"{emoji} {country}: *US$ {price:.2f}*\n"
    
    if note:
        caption += f"\n_{note}_"
    
    caption += "\n*Fonte: Scot Consultoria*"
        
    caption += "\n\n💬 *Sua opinião é importante!* \n"
    caption += "Clique aqui para enviar um /feedback ou sugerir melhorias."
    
    return caption

async def broadcast_report(application, data):
    if not data:
        print("No data to broadcast")
        return

    # Use Matplotlib as primary chart source
    from app.models import get_recent_prices
    history_data = get_recent_prices()
    if not history_data:
        history_data = data
        
    chart_path = generate_chart(history_data)
    
    if not chart_path:
        print("Failed to generate chart")
        return

    session = SessionLocal()
    try:
        users = session.query(User).all()
        caption = format_chart_caption(data)
        for user in users:
            try:
                await application.bot.send_photo(
                    chat_id=user.chat_id, 
                    photo=open(chart_path, 'rb'),
                    caption=caption,
                    parse_mode='Markdown'
                )
            except Exception as e:
                print(f"Failed to send to {user.chat_id}: {e}")
    finally:
        session.close()

async def current_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    first_name = update.effective_chat.first_name
    username = update.effective_chat.username
    
    # Notify Admin if user is not the admin himself
    try:
        if not is_admin(chat_id):
            admin_alert = (
                f"👤 *Solicitação de Cotação*\n\n"
                f"Usuário: {f'[{first_name}](tg://user?id={chat_id})'}\n"
                f"Username: @{username or 'Sem username'}\n"
                f"ID: `{chat_id}`"
            )
            await context.bot.send_message(
                chat_id=Config.ADMIN_CHAT_ID,
                text=admin_alert,
                parse_mode='Markdown'
            )
    except Exception as e:
        print(f"Error notifying admin: {e}")

    await update.message.reply_text("🔄 Buscando dados e gerando análise... Aguarde um momento.")
    
    try:
        from app.scraper import run_scraping_cycle
        
        loop = asyncio.get_running_loop()
        # Fetch data without saving to DB or Sheet (save=False)
        data = await loop.run_in_executor(None, lambda: run_scraping_cycle(save=False))
        
        if not data:
            await update.message.reply_text("⚠️ Não foi possível coletar dados no momento.")
            return

        # Generate Chart using Matplotlib (Primary)
        from app.models import get_recent_prices
        history_data = await loop.run_in_executor(None, get_recent_prices)
        chart_path = await loop.run_in_executor(None, lambda: generate_chart(history_data))
        
        if not chart_path:
             await update.message.reply_text("⚠️ Erro ao gerar o gráfico.")
             return

        note = "Nota: O gráfico reflete os dados históricos coletados. O texto acima contém os preços atuais extraídos agora."
        caption = format_chart_caption(data, title="Relatório Solicitado (Sob Demanda)", note=note)
        
        await update.message.reply_photo(
            photo=open(chart_path, 'rb'),
            caption=caption,
            parse_mode='Markdown'
        )

    except Exception as e:
        import traceback
        error_msg = f"❌ Ocorreu um erro: {str(e)}"
        print(f"Error in current_analysis: {traceback.format_exc()}")
        await update.message.reply_text(error_msg)

async def future_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    
    await update.message.reply_text("🔮 Coletando dados do Mercado Futuro (Scot Consultoria)... Aguarde.")
    
    try:
        from app.scraper import scrape_mercado_futuro
        
        loop = asyncio.get_running_loop()
        # 1. Scrape data
        data_dict = await loop.run_in_executor(None, scrape_mercado_futuro)
        
        if not data_dict:
             await update.message.reply_text("⚠️ Não foi possível coletar os dados do Mercado Futuro no momento.")
             return

        # 2. Generate table image
        chart_path = await loop.run_in_executor(None, lambda: generate_future_table(data_dict))
        
        if not chart_path:
             await update.message.reply_text("⚠️ Erro ao gerar a tabela do Mercado Futuro.")
             return

        caption = (
            "🔮 *Mercado Futuro - Boi Gordo*\n\n"
            "Valores para os próximos vencimentos obtidos agora.\n\n"
            "*Fonte:* Scot Consultoria"
        )
        
        await update.message.reply_photo(
            photo=open(chart_path, 'rb'),
            caption=caption,
            parse_mode='Markdown'
        )

    except Exception as e:
        print(f"Error in future_market: {e}")
        await update.message.reply_text("❌ Ocorreu um erro ao processar sua solicitação.")

async def sync_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text("⏳ Iniciando importação do histórico da planilha... Isso pode levar alguns segundos.")
    
    try:
        from app.scraper import import_history_from_sheet
        
        loop = asyncio.get_running_loop()
        result_message = await loop.run_in_executor(None, import_history_from_sheet)
        
        await update.message.reply_text(result_message)

    except Exception as e:
        print(f"Error in sync_history: {e}")
        await update.message.reply_text("❌ Erro fatal ao tentar importar histórico.")

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to list all registered users"""
    chat_id = str(update.effective_chat.id)
    
    if not is_admin(chat_id):
        await update.message.reply_text("❌ Você não tem permissão para usar este comando.")
        return
    
    session = SessionLocal()
    try:
        print(f"Admin {chat_id} is listing users...")
        users = session.query(User).all()
        
        if not users:
            await update.message.reply_text("Nenhum usuário cadastrado ainda.")
            return
        
        user_list = "👥 *Lista de Usuários Cadastrados*\n\n"
        for idx, user in enumerate(users, 1):
            try:
                chat = await context.bot.get_chat(user.chat_id)
                first_name = escape_markdown(chat.first_name) if chat.first_name else "Sem nome"
            except Exception:
                first_name = "Desconhecido"
                
            username_clean = escape_markdown(user.username) if user.username else "Sem username"
            username_display = f"@{username_clean}" if user.username else "Sem username"
            created = user.created_at.strftime('%d/%m/%Y') if user.created_at else "N/A"
            line = f"{idx}. *{first_name}* ({username_display})\n   ID: `{user.chat_id}`\n   Cadastro: {created}\n\n"
            
            # Check for Telegram message limit (4096)
            if len(user_list) + len(line) > 3900:
                user_list += "...\n*Lista truncada devido ao limite do Telegram*"
                break
            user_list += line
        
        user_list += f"*Total: {len(users)} usuários*"
        
        await update.message.reply_text(user_list, parse_mode='Markdown')
    except Exception as e:
        print(f"Error in list_users: {e}")
        await update.message.reply_text("❌ Erro ao buscar lista de usuários.")
    finally:
        session.close()

async def start_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start feedback conversation"""
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(
        "💬 *Sistema de Feedback*\n\n"
        "Por favor, envie sua mensagem com sugestões, dúvidas ou solicitações de funcionalidades.\n\n"
        "Envie /cancelar para cancelar.",
        parse_mode='Markdown'
    )
    return WAITING_FEEDBACK

async def receive_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and forward feedback to admin"""
    chat_id = str(update.effective_chat.id)
    username = update.effective_chat.username
    feedback_text = update.message.text
    
    # Don't process commands
    if feedback_text.startswith('/'):
        return WAITING_FEEDBACK
    
    if feedback_text in MAIN_MENU_BUTTONS:
        return await handle_keyboard_buttons(update, context)
    
    try:
        # Forward to admin
        admin_message = (
            f"💬 *Novo Feedback Recebido*\n\n"
            f"De: @{username or 'Sem username'}\n"
            f"ID: `{chat_id}`\n\n"
            f"*Mensagem:*\n{feedback_text}"
        )
        
        await context.bot.send_message(
            chat_id=Config.ADMIN_CHAT_ID,
            text=admin_message,
            parse_mode='Markdown'
        )
        
        await update.message.reply_text(
            "✅ Obrigado pelo feedback! Sua mensagem foi enviada com sucesso.",
            reply_markup=get_keyboard(chat_id)
        )
    except Exception as e:
        print(f"Error sending feedback: {e}")
        await update.message.reply_text("❌ Erro ao enviar feedback. Tente novamente mais tarde.")
    
    return ConversationHandler.END

async def cancel_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel feedback conversation"""
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(
        "❌ Feedback cancelado.",
        reply_markup=get_keyboard(chat_id)
    )
    return ConversationHandler.END

async def start_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start: show Histórico / Previsão choice immediately"""
    mode_keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("📅 Histórico"), KeyboardButton("🔮 Previsão")],
            [KeyboardButton("🔙 Voltar ao Menu")]
        ],
        resize_keyboard=True, one_time_keyboard=True
    )
    await update.message.reply_text(
        "🌧️ *Precipitação*\n\n"
        "O que deseja consultar?",
        parse_mode='Markdown',
        reply_markup=mode_keyboard
    )
    return WAITING_WEATHER_MODE


async def receive_weather_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mode selected: Histórico → ask location. Previsão → ask period first."""
    text = update.message.text.strip()
    chat_id = str(update.effective_chat.id)

    if text in MAIN_MENU_BUTTONS or "🔙" in text:
        return await handle_keyboard_buttons(update, context)

    if "Previsão" in text:
        context.user_data['wx_mode'] = 'forecast'
        # Ask for period before location
        period_keyboard = ReplyKeyboardMarkup(
            [
                [KeyboardButton("📅 1 dia"), KeyboardButton("📅 5 dias"), KeyboardButton("📅 10 dias")],
                [KeyboardButton("🔙 Voltar")]
            ],
            resize_keyboard=True, one_time_keyboard=True
        )
        await update.message.reply_text(
            "Selecione o período de acumulação:",
            reply_markup=period_keyboard
        )
        return WAITING_FORECAST_PERIOD
    else:
        context.user_data['wx_mode'] = 'historico'
        return await _ask_location(update, context)


async def _ask_location(update, context):
    """Helper: show location prompt with list of registered properties."""
    chat_id = str(update.effective_chat.id)
    help_text = (
        "📍 *Informe a Localização*\n\n"
        "🏙️ *Município*: Ex: Bebedouro SP\n"
        "📍 *Coordenadas/Links*: Ex: -20.94, -48.48\n"
    )
    session = SessionLocal()
    try:
        from app.models import FavoriteLocation
        locs = session.query(FavoriteLocation).filter_by(user_id=chat_id).order_by(FavoriteLocation.created_at).all()
        if locs:
            help_text += "\n📌 *Suas Propriedades (número):*\n"
            for i, loc in enumerate(locs, 1):
                help_text += f"{i}. {loc.name}\n"
    finally:
        session.close()
    help_text += "\n/cancelar para sair."
    await update.message.reply_text(help_text, parse_mode='Markdown')
    return WAITING_WEATHER_LOCATION


async def receive_weather_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process location — branches on wx_mode (historico vs forecast)."""
    chat_id = str(update.effective_chat.id)
    query = update.message.text

    if query.startswith('/'):
        return WAITING_WEATHER_LOCATION

    if query in MAIN_MENU_BUTTONS:
        return await handle_keyboard_buttons(update, context)

    status_msg = await update.message.reply_text("🔍 Buscando localização... Aguarde.")

    try:
        # ── 1. Resolve lat/lon ──────────────────────────────────────────
        lat, lon, loc_name = None, None, query

        if query.isdigit():
            session = SessionLocal()
            try:
                from app.models import FavoriteLocation
                idx = int(query) - 1
                locs = session.query(FavoriteLocation).filter_by(user_id=chat_id).order_by(FavoriteLocation.created_at).all()
                if 0 <= idx < len(locs):
                    lat, lon = locs[idx].latitude, locs[idx].longitude
                    loc_name = locs[idx].name
                    context.user_data['prop_name'] = loc_name
                else:
                    await status_msg.edit_text(f"⚠️ Propriedade nº {query} não encontrada.")
                    return WAITING_WEATHER_LOCATION
            finally:
                session.close()

        if lat is None:
            url_coords = extract_coords_from_url(query)
            if url_coords:
                lat, lon = url_coords
                loc_name = f"Coordenadas ({lat:.4f}, {lon:.4f})"

        if lat is None:
            coords = parse_coordinates(query)
            if coords:
                lat, lon = coords
                loc_name = f"Coordenadas: {lat:.4f}, {lon:.4f}"

        if lat is None:
            loc = geocode_location(query)
            if loc:
                lat, lon = loc['lat'], loc['lon']
                loc_name = f"{loc['name']}, {loc.get('admin1', '')}"

        if lat is None or lon is None:
            await status_msg.edit_text("⚠️ Não consegui interpretar o local. Tente o nome da cidade, coordenadas ou link do Google Maps.")
            return WAITING_WEATHER_LOCATION

        # ── 2. Branch on mode ───────────────────────────────────────────
        wx_mode = context.user_data.get('wx_mode', 'historico')

        # ── FORECAST mode: skip historical, call ECMWF directly ─────────
        if wx_mode == 'forecast':
            days = context.user_data.get('wx_days', 5)
            period_label = f"{days} dia" + ("s" if days > 1 else "")

            # Try CAR polygon
            polygon = None
            try:
                import json as _json
                from app.environmental import fetch_car_perimeter
                car_result = fetch_car_perimeter(lat, lon)
                if car_result and car_result[0]:
                    geometry, status, cod_imovel = car_result
                    polygon = _json.dumps(geometry)
                    if cod_imovel:
                        await _send_tg_car_zip_guide(update, context, cod_imovel)
                    print(f"  CAR polygon found ({status})", flush=True)
            except Exception as poly_err:
                print(f"  CAR polygon unavailable: {poly_err}", flush=True)

            await status_msg.edit_text(f"⏳ Baixando previsão ECMWF {period_label}... Até 3 minutos.")
            wide_buf, close_buf, err_detail = get_forecast_image(lat, lon, days, polygon_geojson=polygon)
            sent_any = False
            if wide_buf:
                await context.bot.send_photo(
                    chat_id=chat_id, photo=wide_buf,
                    caption=f"🌎 *Previsão ECMWF — {period_label} acumulado*\n📍 {loc_name}",
                    parse_mode='Markdown'
                )
                sent_any = True
            if close_buf:
                await context.bot.send_photo(
                    chat_id=chat_id, photo=close_buf,
                    caption=f"🏡 *Detalhe — {period_label}*\n_Res: 0.25° | ECMWF Open Data_",
                    parse_mode='Markdown', reply_markup=get_keyboard(chat_id)
                )
                sent_any = True
            if sent_any:
                await status_msg.delete()
            else:
                detail = f"\n`{err_detail[:300]}`" if err_detail else ""
                await status_msg.edit_text(
                    f"❌ Não foi possível gerar a previsão.{detail}", parse_mode='Markdown'
                )
                await update.message.reply_text("📱 Menu.", reply_markup=get_keyboard(chat_id))
            return ConversationHandler.END

        # ── HISTORICO mode: precipitation data + heatmap ─────────────────
        print(f"[WEATHER] Modo histórico para {lat}, {lon}", flush=True)
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, get_precipitation_data, lat, lon)
        if not data:
            print("[WEATHER] get_precipitation_data retornou None", flush=True)
            await status_msg.edit_text("❌ Erro ao buscar dados meteorológicos para este local.")
            return WAITING_WEATHER_LOCATION

        print(f"[WEATHER] Dados obtidos: last_24h={data.get('last_24h')}, dias={len(data.get('daily_history', []))}", flush=True)

        # Format text message
        precip_val = data.get('last_24h', 0)
        msg = f"🌧️ *Dados de Precipitação*\n"
        msg += f"📍 *Local:* {loc_name}\n"
        msg += f"🕒 *Últimas 24h:* {precip_val:.1f} mm\n\n"
        msg += f"📅 *Histórico Recente (Últimos 7 dias):* _Veja o gráfico abaixo_\n"
        msg += f"\n📍 [Ver no Google Maps](https://www.google.com/maps?q={lat},{lon})"

        # Get Regional Heatmap (GEE) — non-blocking; skip on failure
        await status_msg.edit_text("🛰️ Gerando mapa de calor regional... Aguarde.")
        heatmap = None
        try:
            from app.gee_connector import get_precipitation_heatmap
            heatmap = await loop.run_in_executor(None, get_precipitation_heatmap, lat, lon)
            print(f"[WEATHER] Heatmap: {'OK' if heatmap else 'Vazio'}", flush=True)
        except Exception as ge:
            print(f"[WEATHER] Heatmap skipped: {ge}", flush=True)

        # Get static map
        await status_msg.edit_text("🗺️ Desenhando mapa... Aguarde.")
        map_image = await loop.run_in_executor(None, generate_weather_map_with_title, lat, lon, loc_name)
        print(f"[WEATHER] Map image: {'OK' if map_image else 'Falhou'}", flush=True)

        # Get chart
        from app.charts import generate_precipitation_chart
        chart_path = await loop.run_in_executor(None, generate_precipitation_chart, data.get('daily_history', []), f"Histórico de Chuvas - {loc_name}")

        # Send photos
        try:
            if heatmap:
                try:
                    heatmap_photo = heatmap.get('buffer') or heatmap.get('image_url')
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=heatmap_photo,
                        caption=(
                            "🌍 *Precipitação Acumulada — 30 dias | Brasil*\n"
                            "Cinza = seco · Azul claro = 50mm · Azul escuro = 300mm+"
                        ),
                        parse_mode='Markdown'
                    )
                except Exception as he:
                    print(f"[WEATHER] Heatmap send failed: {he}", flush=True)

            # Send static map with caption
            photo = map_image if map_image else get_static_map_url(lat, lon)
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=msg,
                parse_mode='Markdown'
            )

            # --- NEW: Send Rain Bar Chart ---
            if chart_path and os.path.exists(chart_path):
                try:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=open(chart_path, 'rb'),
                        caption="📊 *Gráfico de Histórico de Chuvas (7 dias)*",
                        parse_mode='Markdown',
                        reply_markup=get_keyboard(chat_id)
                    )
                except Exception as ce:
                    print(f"[WEATHER] Chart send failed: {ce}", flush=True)

            await status_msg.delete()
            print("[WEATHER] Histórico enviado com sucesso!", flush=True)

        except Exception as spe:
            print(f"[WEATHER] Error sending photo: {spe}", flush=True)
            import traceback
            traceback.print_exc()
            try:
                await status_msg.edit_text(msg, parse_mode='Markdown')
            except Exception:
                await update.message.reply_text(msg, parse_mode='Markdown')
            await update.message.reply_text("📱 Menu restaurado.", reply_markup=get_keyboard(chat_id))

    except Exception as e:
        print(f"Error in receive_weather_location: {e}")
        import traceback
        print(traceback.format_exc())
        try:
            await status_msg.edit_text("❌ Ocorreu um erro ao processar sua solicitação.")
        except Exception:
            pass

    return ConversationHandler.END


async def receive_forecast_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Period chosen (1/5/10 dias) — store it then ask for location."""
    chat_id = str(update.effective_chat.id)
    text = update.message.text.strip()

    if "Voltar" in text or "Cancelar" in text:
        await update.message.reply_text("❌ Cancelado.", reply_markup=get_keyboard(chat_id))
        return ConversationHandler.END

    days_map = {"📅 1 dia": 1, "📅 5 dias": 5, "📅 10 dias": 10}
    days = days_map.get(text)

    if not days:
        await update.message.reply_text("⚠️ Escolha 1, 5 ou 10 dias.", reply_markup=get_keyboard(chat_id))
        return ConversationHandler.END

    context.user_data['wx_days'] = days
    return await _ask_location(update, context)



async def start_env_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start environmental analysis — show NDVI vs MDT sub-menu."""
    mode_keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("🌿 NDVI (Vegetação)"), KeyboardButton("🏔️ Terreno (MDT)")],
            [KeyboardButton("🔙 Voltar ao Menu")]
        ],
        resize_keyboard=True, one_time_keyboard=True
    )
    await update.message.reply_text(
        "🌿 *Análise Ambiental*\n\n"
        "Escolha o tipo de análise:",
        parse_mode='Markdown',
        reply_markup=mode_keyboard
    )
    return WAITING_ENV_MODE

async def receive_env_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store env mode choice (ndvi/mdt) and ask for location."""
    text = update.message.text.strip()
    if text in MAIN_MENU_BUTTONS or text == "🔙 Voltar ao Menu":
        return await handle_keyboard_buttons(update, context)

    if 'MDT' in text or 'Terreno' in text:
        context.user_data['env_mode'] = 'mdt'
        mode_label = "🏔️ *Terreno (MDT)*"
    else:
        context.user_data['env_mode'] = 'ndvi'
        mode_label = "🌿 *NDVI*"

    chat_id = str(update.effective_chat.id)
    help_text = (
        f"{mode_label}\n\n"
        "Envie uma localização para analisar:\n"
        "- Coordenadas (ex: -21.43, -54.78)\n"
        "- Link do Google Maps\n"
    )
    session = SessionLocal()
    try:
        from app.models import FavoriteLocation
        locs = session.query(FavoriteLocation).filter_by(user_id=chat_id).order_by(FavoriteLocation.created_at).all()
        if locs:
            help_text += "\n📌 *Suas Propriedades (Digite o número):*\n"
            for i, loc in enumerate(locs, 1):
                help_text += f"{i}. {loc.name}\n"
    finally:
        session.close()

    help_text += "\nEnvie /cancelar para sair."
    await update.message.reply_text(
        help_text, parse_mode='Markdown',
        disable_web_page_preview=True,
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("/cancelar")]], resize_keyboard=True)
    )
    return WAITING_ENV_LOCATION

async def receive_env_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process location for environmental analysis"""
    chat_id = str(update.effective_chat.id)
    query = update.message.text
    
    if query.startswith('/'):
        return WAITING_ENV_LOCATION
    
    if query in MAIN_MENU_BUTTONS:
        return await handle_keyboard_buttons(update, context)

    status_msg = await update.message.reply_text("🛰️ Processando imagens de satélite... Aguarde.")
    
    try:
        # 1. Determine Lat/Lon
        lat, lon = None, None
        
        # Priority 1: Check for numerical shortcut
        if query.isdigit():
            session = SessionLocal()
            try:
                from app.models import FavoriteLocation
                idx = int(query) - 1
                locs = session.query(FavoriteLocation).filter_by(user_id=chat_id).order_by(FavoriteLocation.created_at).all()
                if 0 <= idx < len(locs):
                    lat, lon = locs[idx].latitude, locs[idx].longitude
                    context.user_data['prop_name'] = locs[idx].name
                else:
                    await status_msg.edit_text(f"⚠️ Propriedade nº {query} não encontrada.")
                    return WAITING_ENV_LOCATION
            finally:
                session.close()

        if lat is None:
            url_coords = extract_coords_from_url(query)
            if url_coords:
                lat, lon = url_coords
            else:
                coords = parse_coordinates(query)
                if coords:
                    lat, lon = coords
        
        if lat is None or lon is None:
            await status_msg.edit_text("⚠️ Não consegui interpretar as coordenadas. Envie coordenadas decimais ou um link do Google Maps.")
            return WAITING_ENV_LOCATION

        # 2. Fetch CAR Perimeter
        geometry, is_real_car, cod_imovel = fetch_car_perimeter(lat, lon)
        
        if cod_imovel:
            await _send_tg_car_zip_guide(update, context, cod_imovel)

        env_mode = context.user_data.pop('env_mode', 'ndvi')
        prop_name = context.user_data.pop('prop_name', None)

        # ── MDT branch ────────────────────────────────────────────────────
        if env_mode == 'mdt':
            await status_msg.edit_text("🏔️ Buscando dados de elevação (DEM)... Aguarde.")

            loop = asyncio.get_running_loop()
            from app.gee_connector import get_terrain_data
            from app.environmental import generate_terrain_image_2d, generate_terrain_image_3d

            terrain_data = await loop.run_in_executor(None, get_terrain_data, geometry)
            if not terrain_data:
                await status_msg.edit_text(
                    "⚠️ Não foi possível obter dados de elevação para esta área.\n"
                    "Tente novamente mais tarde."
                )
                return WAITING_ENV_LOCATION

            source = terrain_data.get('source', 'DEM')
            elev_min = terrain_data.get('elev_min', 0)
            elev_max = terrain_data.get('elev_max', 0)

            caption_2d = (
                f"🏔️ *Mapa de Curvas de Nível*\n"
                f"📍 {prop_name or 'Localização'}\n"
                f"📏 Altitude: {elev_min:.0f}m – {elev_max:.0f}m\n"
                f"🗺️ Curvas: 5m (finas) / 50m (grossas)\n"
                f"📡 Fonte: {source}\n"
            )
            if is_real_car == 'OFFICIAL':
                caption_2d += "✅ Perímetro: CAR Oficial\n"
            elif is_real_car == 'NEARBY':
                caption_2d += "⚠️ Perímetro: Propriedade Próxima\n"
            else:
                caption_2d += "⚠️ Perímetro: Área Estimada\n"

            caption_3d = (
                f"🏔️ *Modelo 3D do Terreno*\n"
                f"📍 {prop_name or 'Localização'}\n"
                f"🛰️ Textura: Sentinel-2 RGB\n"
                f"📡 DEM: {source}\n"
            )

            await status_msg.edit_text("🗺️ Gerando mapa 2D de curvas de nível...")
            img_2d = await loop.run_in_executor(
                None, generate_terrain_image_2d,
                terrain_data, geometry, is_real_car, prop_name, (lat, lon)
            )

            await status_msg.edit_text("🏔️ Gerando modelo 3D com textura de satélite...")
            img_3d = await loop.run_in_executor(
                None, generate_terrain_image_3d,
                terrain_data, geometry, is_real_car, prop_name, (lat, lon)
            )

            await status_msg.delete()

            if img_2d:
                await context.bot.send_photo(
                    chat_id=chat_id, photo=img_2d,
                    caption=caption_2d, parse_mode='Markdown'
                )
            if img_3d:
                await context.bot.send_video(
                    chat_id=chat_id, video=img_3d,
                    caption=caption_3d, parse_mode='Markdown',
                    reply_markup=get_keyboard(chat_id)
                )
            if not img_2d and not img_3d:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Não foi possível gerar as imagens MDT.",
                    reply_markup=get_keyboard(chat_id)
                )

        # ── NDVI branch (original, unchanged) ────────────────────────────
        else:
            # 3. Get NDVI Analysis
            analysis = get_ndvi_analysis(geometry)
            if not analysis:
                await status_msg.edit_text(
                    "⚠️ *Não foi possível realizar a análise*\n\n"
                    "Verifique se o local selecionado tem cobertura recente de satélite (sem nuvens) "
                    "ou tente novamente mais tarde.",
                    parse_mode='Markdown'
                )
                return WAITING_ENV_LOCATION

            # 4. Format Message
            ndvi_val = analysis.get('stats', {}).get('mean', 0)
            dt_obj = datetime.fromtimestamp(analysis['dt'])
            date_str = dt_obj.strftime('%d/%m/%Y')

            msg = f"🌿 *Análise Ambiental*\n\n"
            msg += f"📅 *Data da Imagem:* {date_str}\n"
            msg += f"🛰️ *Índice NDVI Médio:* {ndvi_val:.2f}\n"

            if is_real_car == 'OFFICIAL' or is_real_car is True:
                msg += f"✅ *Perímetro:* CAR Oficial\n"
            elif is_real_car == 'NEARBY':
                msg += f"⚠️ *Perímetro:* Propriedade Próxima (<11km)\n"
                msg += f"_Nenhuma propriedade encontrada no ponto exato_\n"
            else:
                msg += f"⚠️ *Perímetro:* Área Estimada (1km²)\n"
                msg += f"_Servidor CAR indisponível_\n"

            msg += f"🚜 *Uso do Solo (Estimado):* Vegetação/Campo\n\n"
            msg += "O NDVI varia de -1 a 1:\n"
            msg += "- > 0.6: Vegetação densa/saudável\n"
            msg += "- 0.2 a 0.5: Solo exposto/pastagem rala\n"
            msg += "- < 0.1: Água ou rocha\n\n"
            msg += "📡 *Fonte:* Sentinel-2 / Google Earth Engine"

            region_bbox = analysis.get('region_bbox')
            image_buffer = generate_environmental_image(
                analysis['ndvi_img'],
                geometry, is_real_car,
                region_bbox=region_bbox,
                title=prop_name,
                pin_coords=(lat, lon)
            )

            if image_buffer:
                await context.bot.send_photo(
                    chat_id=chat_id, photo=image_buffer,
                    caption=msg, parse_mode='Markdown',
                    reply_markup=get_keyboard(chat_id)
                )
            else:
                await context.bot.send_photo(
                    chat_id=chat_id, photo=analysis['ndvi_img'],
                    caption=msg, parse_mode='Markdown',
                    reply_markup=get_keyboard(chat_id)
                )

            await status_msg.delete()

    except Exception as e:
        print(f"Error in env_analysis: {e}")
        await status_msg.edit_text("❌ Ocorreu um erro ao processar a análise ambiental.")

    return ConversationHandler.END

async def cancel_env(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel env conversation"""
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(
        "❌ Análise cancelada.",
        reply_markup=get_keyboard(chat_id)
    )
    return ConversationHandler.END

async def cancel_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel weather conversation"""
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(
        "❌ Consulta cancelada.",
        reply_markup=get_keyboard(chat_id)
    )
    return ConversationHandler.END

async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start broadcast conversation (Admin only)"""
    chat_id = str(update.effective_chat.id)
    if not is_admin(chat_id):
        await update.message.reply_text("🚫 Comando restrito ao administrador.")
        return ConversationHandler.END
        
    await update.message.reply_text(
        "📢 *Enviar Anúncio*\n\n"
        "Por favor, envie a mensagem que deseja transmitir para todos os usuários.\n\n"
        "Envie /cancelar para sair.",
        parse_mode='Markdown'
    )
    return WAITING_BROADCAST_MESSAGE

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send message to all users"""
    chat_id = str(update.effective_chat.id)
    broadcast_text = update.message.text
    
    if broadcast_text.startswith('/'):
        return WAITING_BROADCAST_MESSAGE
    
    if broadcast_text in MAIN_MENU_BUTTONS:
        return await handle_keyboard_buttons(update, context)

    status_msg = await update.message.reply_text("🚀 Iniciando transmissão...")
    
    session = SessionLocal()
    success_count = 0
    failure_count = 0
    
    try:
        users = session.query(User).all()
        if not users:
            await status_msg.edit_text("⚠️ Nenhum usuário encontrado no banco de dados.")
            session.close()
            return ConversationHandler.END

        for user in users:
            if not user.chat_id:
                continue
                
            try:
                # Using HTML for better stability with special characters
                # Escape HTML characters in user-provided text
                safe_text = broadcast_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                
                await context.bot.send_message(
                    chat_id=user.chat_id,
                    text=f"📢 <b>AGRO ANALYTICS - INFORMA</b>\n\n{safe_text}",
                    parse_mode='HTML'
                )
                success_count += 1
            except Exception as e:
                print(f"Failed to send broadcast to {user.chat_id}: {e}")
                failure_count += 1
            
            # Rate limiting / Anti-spam safety
            await asyncio.sleep(0.05)
            
        await status_msg.edit_text(
            f"✅ <b>Transmissão Concluída!</b>\n\n"
            f"📈 Sucesso: {success_count}\n"
            f"❌ Falhas: {failure_count}",
            parse_mode='HTML'
        )
        # Restore keyboard via a new message
        await update.message.reply_text("📱 Menu restaurado.", reply_markup=get_keyboard(chat_id))
        
    except Exception as e:
        print(f"CRITICAL Error in broadcast: {e}")
        import traceback
        print(traceback.format_exc())
        await status_msg.edit_text(f"❌ Ocorreu um erro ao processar a transmissão: {str(e)[:50]}...")
    finally:
        session.close()


    return ConversationHandler.END

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel broadcast conversation"""
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(
        "❌ Transmissão cancelada.",
        reply_markup=get_keyboard(chat_id)
    )
    return ConversationHandler.END

async def handle_keyboard_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle keyboard button presses"""
    text = update.message.text
    
    if text == "📊 Cotação Atual":
        await current_analysis(update, context)
    elif text == "📈 Status":
        await status(update, context)
    elif text == "🌿 Análise Ambiental":
        await start_env_analysis(update, context)
        return WAITING_ENV_LOCATION
    elif text == "🔮 Mercado Futuro":
        await future_market(update, context)
    elif text == "📥 Importar Histórico":
        if is_admin(update.effective_chat.id):
            await sync_history(update, context)
        else:
            await update.message.reply_text("❌ Comando reservado para administradores.")
    elif text == "👥 Lista de Usuários":
        if is_admin(update.effective_chat.id):
            await list_users(update, context)
        else:
            await update.message.reply_text("❌ Comando reservado para administradores.")
    elif text == "📢 Enviar Anúncio":
        if is_admin(update.effective_chat.id):
            await start_broadcast(update, context)
            return WAITING_BROADCAST_MESSAGE
        else:
            await update.message.reply_text("❌ Comando reservado para administradores.")
    elif text == "📌 Minhas Propriedades":
        await start_locations(update, context)
        return WAITING_LOCATION_MENU
    elif text == "💬 Feedback":
        await start_feedback(update, context)
        return WAITING_FEEDBACK
    elif text == "🌧️ Precipitação (chuva)":
        await start_weather(update, context)
        return WAITING_WEATHER_LOCATION
    else:
        # Fallback inteligente para o Agente OpenAI (se o produtor mandar texto livre)
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
        from app.agent import get_agent_response
        resposta_txt, media_list = await get_agent_response(
            user_id=str(update.effective_chat.id),
            user_text=text,
            context_info="O usuário está conversando via Telegram. Pode usar Markdown básico se precisar formular listas."
        )
        
        # ── INTERCEPTOR DE FLUXOS AUTOMÁTICOS ──
        if "TRIGGER_FLOW:" in resposta_txt:
            import re
            match = re.search(r"TRIGGER_FLOW:\s*(\w+)\s*\|\s*([\d\.-]+)\s*\|\s*([\d\.-]+)\s*\|\s*([^|*\n]+)", resposta_txt)
            if match:
                fluxo_tipo = match.group(1).upper()
                lat_val = float(match.group(2))
                lon_val = float(match.group(3))
                nome_prop = match.group(4).strip().replace("*", "")
                chat_id = str(update.effective_chat.id)
                
                print(f"[TRIGGER_FLOW] Executando inline: {fluxo_tipo} | lat={lat_val} | lon={lon_val} | nome={nome_prop}", flush=True)
                
                try:
                    if fluxo_tipo in ['NDVI', 'MDT']:
                        status_msg = await update.message.reply_text("🛰️ Processando imagens de satélite... Aguarde.")
                        
                        loop = asyncio.get_running_loop()
                        
                        # 1. Buscar perímetro
                        print("[TRIGGER_FLOW] Buscando perímetro CAR...", flush=True)
                        geometry, car_status = await loop.run_in_executor(None, fetch_car_perimeter, lat_val, lon_val)
                        print(f"[TRIGGER_FLOW] Perímetro: {car_status}", flush=True)
                        
                        # 2. Análise NDVI
                        print("[TRIGGER_FLOW] Iniciando análise NDVI via GEE...", flush=True)
                        analysis = await loop.run_in_executor(None, get_ndvi_analysis, geometry)
                        
                        if not analysis:
                            await status_msg.edit_text(
                                "⚠️ *Não foi possível realizar a análise*\n\n"
                                "Verifique se o local selecionado tem cobertura recente de satélite (sem nuvens) "
                                "ou tente novamente mais tarde.",
                                parse_mode='Markdown'
                            )
                            return ConversationHandler.END
                        
                        print("[TRIGGER_FLOW] Análise NDVI concluída. Gerando imagem...", flush=True)
                        
                        # 3. Gerar imagem (mesma lógica exata do botão)
                        ndvi_val = analysis.get('stats', {}).get('mean', 0)
                        dt_obj = datetime.fromtimestamp(analysis['dt'])
                        date_str = dt_obj.strftime('%d/%m/%Y')
                        region_bbox = analysis.get('region_bbox')
                        
                        image_buffer = await loop.run_in_executor(
                            None, generate_environmental_image,
                            analysis['ndvi_img'], geometry, car_status,
                            region_bbox, nome_prop, (lat_val, lon_val)
                        )
                        
                        # 4. Montar caption (idêntica ao botão)
                        msg = f"🌿 *Análise Ambiental*\n\n"
                        msg += f"📍 *Propriedade:* {nome_prop}\n"
                        msg += f"📅 *Data da Imagem:* {date_str}\n"
                        msg += f"🛰️ *Índice NDVI Médio:* {ndvi_val:.2f}\n"
                        
                        if car_status == 'OFFICIAL' or car_status is True:
                            msg += "✅ *Perímetro:* CAR Oficial\n"
                        elif car_status == 'NEARBY':
                            msg += "⚠️ *Perímetro:* Propriedade Próxima (<11km)\n"
                        else:
                            msg += "⚠️ *Perímetro:* Área Estimada (1km²)\n"
                        
                        msg += "\nO NDVI varia de -1 a 1:\n"
                        msg += "- > 0.6: Vegetação densa/saudável\n"
                        msg += "- 0.2 a 0.5: Solo exposto/pastagem rala\n"
                        msg += "- < 0.1: Água ou rocha"
                        
                        # 5. Enviar foto
                        photo = image_buffer if image_buffer else analysis.get('ndvi_img')
                        if photo:
                            await context.bot.send_photo(
                                chat_id=chat_id, photo=photo,
                                caption=msg, parse_mode='Markdown',
                                reply_markup=get_keyboard(chat_id)
                            )
                        
                        await status_msg.delete()
                        print("[TRIGGER_FLOW] Mapa NDVI enviado com sucesso!", flush=True)
                    
                    elif fluxo_tipo == 'CLIMA':
                        status_msg = await update.message.reply_text("⏳ Baixando previsão de chuva... Aguarde.")
                        
                        loop = asyncio.get_running_loop()
                        days = 5
                        loc_name = nome_prop
                        
                        # Buscar polígono CAR para detalhe
                        polygon = None
                        try:
                            import json as _json
                            car_result = await loop.run_in_executor(None, fetch_car_perimeter, lat_val, lon_val)
                            if car_result and car_result[0]:
                                polygon = _json.dumps(car_result[0])
                        except Exception:
                            pass
                        
                        wide_buf, close_buf, err_detail = await loop.run_in_executor(
                            None, get_forecast_image, lat_val, lon_val, days, polygon
                        )
                        
                        sent_any = False
                        if wide_buf:
                            await context.bot.send_photo(
                                chat_id=chat_id, photo=wide_buf,
                                caption=f"🌎 *Previsão ECMWF — {days} dias acumulado*\n📍 {loc_name}",
                                parse_mode='Markdown'
                            )
                            sent_any = True
                        if close_buf:
                            await context.bot.send_photo(
                                chat_id=chat_id, photo=close_buf,
                                caption=f"🏡 *Detalhe — {days} dias*\n_Res: 0.25° | ECMWF Open Data_",
                                parse_mode='Markdown', reply_markup=get_keyboard(chat_id)
                            )
                            sent_any = True
                        if sent_any:
                            await status_msg.delete()
                            print("[TRIGGER_FLOW] Previsão CLIMA enviada com sucesso!", flush=True)
                        else:
                            detail = f"\n`{err_detail[:300]}`" if err_detail else ""
                            await status_msg.edit_text(
                                f"❌ Não foi possível gerar a previsão.{detail}", parse_mode='Markdown'
                            )
                    
                    elif fluxo_tipo == 'MDT':
                        status_msg = await update.message.reply_text("🏔️ Buscando dados de elevação (DEM)... Aguarde.")
                        
                        loop = asyncio.get_running_loop()
                        from app.gee_connector import get_terrain_data
                        from app.environmental import generate_terrain_image_2d, generate_terrain_image_3d
                        
                        # 1. Perímetro
                        geometry, car_status = await loop.run_in_executor(None, fetch_car_perimeter, lat_val, lon_val)
                        
                        # 2. Dados de terreno
                        terrain_data = await loop.run_in_executor(None, get_terrain_data, geometry)
                        if not terrain_data:
                            await status_msg.edit_text("⚠️ Não foi possível obter dados de elevação para esta área.")
                            return ConversationHandler.END
                        
                        source = terrain_data.get('source', 'DEM')
                        elev_min = terrain_data.get('elev_min', 0)
                        elev_max = terrain_data.get('elev_max', 0)
                        
                        caption_2d = (
                            f"🏔️ *Mapa de Curvas de Nível*\n"
                            f"📍 {nome_prop}\n"
                            f"📏 Altitude: {elev_min:.0f}m – {elev_max:.0f}m\n"
                            f"🗺️ Curvas: 5m (finas) / 50m (grossas)\n"
                            f"📡 Fonte: {source}\n"
                        )
                        if car_status == 'OFFICIAL':
                            caption_2d += "✅ Perímetro: CAR Oficial\n"
                        elif car_status == 'NEARBY':
                            caption_2d += "⚠️ Perímetro: Propriedade Próxima\n"
                        else:
                            caption_2d += "⚠️ Perímetro: Área Estimada\n"
                        
                        caption_3d = (
                            f"🏔️ *Modelo 3D do Terreno*\n"
                            f"📍 {nome_prop}\n"
                            f"🛰️ Textura: Sentinel-2 RGB\n"
                            f"📡 DEM: {source}\n"
                        )
                        
                        await status_msg.edit_text("🗺️ Gerando mapa 2D de curvas de nível...")
                        img_2d = await loop.run_in_executor(
                            None, generate_terrain_image_2d,
                            terrain_data, geometry, car_status, nome_prop, (lat_val, lon_val)
                        )
                        
                        await status_msg.edit_text("🏔️ Gerando modelo 3D com textura de satélite...")
                        img_3d = await loop.run_in_executor(
                            None, generate_terrain_image_3d,
                            terrain_data, geometry, car_status, nome_prop, (lat_val, lon_val)
                        )
                        
                        await status_msg.delete()
                        
                        if img_2d:
                            await context.bot.send_photo(
                                chat_id=chat_id, photo=img_2d,
                                caption=caption_2d, parse_mode='Markdown'
                            )
                        if img_3d:
                            await context.bot.send_video(
                                chat_id=chat_id, video=img_3d,
                                caption=caption_3d, parse_mode='Markdown',
                                reply_markup=get_keyboard(chat_id)
                            )
                        if not img_2d and not img_3d:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text="❌ Não foi possível gerar as imagens MDT.",
                                reply_markup=get_keyboard(chat_id)
                            )
                        print("[TRIGGER_FLOW] MDT enviado com sucesso!", flush=True)
                    
                    elif fluxo_tipo == 'HISTORICO':
                        status_msg = await update.message.reply_text("🌧️ Buscando histórico de precipitação... Aguarde.")
                        
                        loop = asyncio.get_running_loop()
                        
                        # 1. Dados de precipitação
                        data = await loop.run_in_executor(None, get_precipitation_data, lat_val, lon_val)
                        if not data:
                            await status_msg.edit_text("❌ Erro ao buscar dados meteorológicos para este local.")
                            return ConversationHandler.END
                        
                        # 2. Texto
                        precip_val = data.get('last_24h', 0)
                        msg = f"🌧️ *Dados de Precipitação*\n"
                        msg += f"📍 *Local:* {nome_prop}\n"
                        msg += f"🕒 *Últimas 24h:* {precip_val:.1f} mm\n\n"
                        msg += f"📅 *Histórico Recente (Últimos 7 dias):*\n"
                        for date_val, val in data.get('daily_history', []):
                            d_fmt = datetime.strptime(date_val, '%Y-%m-%d').strftime('%d/%m')
                            msg += f"• {d_fmt}: {val:.1f} mm\n"
                        msg += f"\n📍 [Ver no Google Maps](https://www.google.com/maps?q={lat_val},{lon_val})"
                        
                        # 3. Heatmap regional
                        await status_msg.edit_text("🛰️ Gerando mapa de calor regional... Aguarde.")
                        heatmap = None
                        try:
                            from app.gee_connector import get_precipitation_heatmap
                            heatmap = await loop.run_in_executor(None, get_precipitation_heatmap, lat_val, lon_val)
                        except Exception:
                            pass
                        
                        # 4. Mapa estático
                        from app.weather import generate_weather_map_with_title
                        map_image = await loop.run_in_executor(None, generate_weather_map_with_title, lat_val, lon_val, nome_prop)
                        
                        # 5. Enviar
                        if heatmap:
                            try:
                                heatmap_photo = heatmap.get('buffer') or heatmap.get('image_url')
                                await context.bot.send_photo(
                                    chat_id=chat_id, photo=heatmap_photo,
                                    caption="🌍 *Precipitação Acumulada — 30 dias | Brasil*\nCinza = seco · Azul claro = 50mm · Azul escuro = 300mm+",
                                    parse_mode='Markdown'
                                )
                            except Exception:
                                pass
                        
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=map_image if map_image else get_static_map_url(lat_val, lon_val),
                            caption=msg, parse_mode='Markdown',
                            reply_markup=get_keyboard(chat_id)
                        )
                        await status_msg.delete()
                        print("[TRIGGER_FLOW] Histórico de chuva enviado com sucesso!", flush=True)
                
                except Exception as e:
                    import traceback
                    print(f"[TRIGGER_FLOW ERROR] {traceback.format_exc()}", flush=True)
                    await update.message.reply_text(
                        f"⚠️ Houve um problema ao gerar o relatório: {str(e)[:200]}\n\n"
                        f"Tente usar o botão '🌿 Análise Ambiental' diretamente."
                    )
                
                return ConversationHandler.END

        # Envia as imagens construídas pelas ferramentas nativas, se houver
        if media_list:
             for media_buffer in media_list:
                 await context.bot.send_photo(
                     chat_id=update.effective_chat.id, 
                     photo=media_buffer
                 )
        
        # Envia a conclusão da IA em texto
        await update.message.reply_text(resposta_txt)
    
    return ConversationHandler.END

# Favorite Locations Management
def get_location_keyboard():
    keyboard = [
        [KeyboardButton("📋 Listar Minhas Propriedades")],
        [KeyboardButton("➕ Adicionar Nova"), KeyboardButton("❌ Excluir Propriedade")],
        [KeyboardButton("🔔 Alertas NDVI")],
        [KeyboardButton("🔙 Voltar ao Menu Principal")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start_locations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(
        "📌 *Gerenciamento de Propriedades*\n\n"
        "Aqui você pode cadastrar seus locais favoritos para consultas rápidas.",
        parse_mode='Markdown',
        reply_markup=get_location_keyboard()
    )
    return WAITING_LOCATION_MENU

async def list_user_locations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    session = SessionLocal()
    try:
        from app.models import FavoriteLocation
        locs = session.query(FavoriteLocation).filter_by(user_id=chat_id).order_by(FavoriteLocation.created_at).all()
        
        if not locs:
            await update.message.reply_text("Você ainda não tem propriedades cadastradas. Use 'Adicionar Nova'.")
            return WAITING_LOCATION_MENU
            
        msg = "📋 *Suas Propriedades Cadastradas:*\n\n"
        for i, loc in enumerate(locs, 1):
            msg += f"*{i}. {loc.name}*\n"
            msg += f"📍 `{loc.latitude:.4f}, {loc.longitude:.4f}`\n\n"
        
        msg += "_Ao consultar o clima ou análise ambiental, você pode apenas digitar o número correspondente._"
        await update.message.reply_text(msg, parse_mode='Markdown')
    finally:
        session.close()
    return WAITING_LOCATION_MENU

async def start_add_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "➕ *Adicionar Nova Propriedade*\n\n"
        "Qual o nome da propriedade/local?\n"
        "(Ex: Fazenda Santa Maria)\n\n"
        "Envie /cancelar para sair.",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Cancelar")]], resize_keyboard=True)
    )
    return WAITING_LOCATION_NAME

async def receive_location_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    if name in MAIN_MENU_BUTTONS:
        return await handle_keyboard_buttons(update, context)
    if name == "❌ Cancelar":
        await update.message.reply_text("Cancelado.", reply_markup=get_location_keyboard())
        return WAITING_LOCATION_MENU
    context.user_data['temp_loc_name'] = name
    await update.message.reply_text(
        f"Ótimo! Agora envie as coordenadas ou o link do Google Maps para *{name}*.",
        parse_mode='Markdown'
    )
    return WAITING_LOCATION_COORDS

async def receive_location_coords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    query = update.message.text
    if query in MAIN_MENU_BUTTONS:
        return await handle_keyboard_buttons(update, context)
    if query == "❌ Cancelar":
        await update.message.reply_text("Cancelado.", reply_markup=get_location_keyboard())
        return WAITING_LOCATION_MENU
        
    lat, lon = None, None
    url_coords = extract_coords_from_url(query)
    if url_coords:
        lat, lon = url_coords
    else:
        coords = parse_coordinates(query)
        if coords:
            lat, lon = coords
            
    if lat is None or lon is None:
        await update.message.reply_text("⚠️ Não consegui entender as coordenadas. Tente enviar no formato -20.45, -54.61 ou um link do Maps.")
        return WAITING_LOCATION_COORDS
        
    session = SessionLocal()
    try:
        from app.models import FavoriteLocation
        new_loc = FavoriteLocation(
            user_id=chat_id,
            name=context.user_data.get('temp_loc_name', 'Sem nome'),
            latitude=lat,
            longitude=lon
        )
        session.add(new_loc)
        session.commit()
        await update.message.reply_text(
            f"✅ *{new_loc.name}* cadastrada com sucesso!",
            parse_mode='Markdown',
            reply_markup=get_location_keyboard()
        )
    except Exception as e:
        print(f"Error adding location: {e}")
        await update.message.reply_text("❌ Erro ao salvar propriedade no banco de dados.")
    finally:
        session.close()
    return WAITING_LOCATION_MENU

async def start_delete_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    session = SessionLocal()
    try:
        from app.models import FavoriteLocation
        locs = session.query(FavoriteLocation).filter_by(user_id=chat_id).order_by(FavoriteLocation.created_at).all()
        if not locs:
            await update.message.reply_text("Você não tem nada para excluir.")
            return WAITING_LOCATION_MENU
            
        msg = "❌ *Excluir Propriedade*\n\n"
        for i, loc in enumerate(locs, 1):
            msg += f"{i}. {loc.name}\n"
        msg += "\n*Digite o número* da propriedade que deseja excluir ou clique em Cancelar."
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Cancelar")]], resize_keyboard=True))
    finally:
        session.close()
    return WAITING_LOCATION_DELETE

async def confirm_delete_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    text = update.message.text
    if text in MAIN_MENU_BUTTONS:
        return await handle_keyboard_buttons(update, context)
    if text == "❌ Cancelar":
        await update.message.reply_text("Exclusão cancelada.", reply_markup=get_location_keyboard())
        return WAITING_LOCATION_MENU
        
    if not text.isdigit():
        await update.message.reply_text("Por favor, digite apenas o número.")
        return WAITING_LOCATION_DELETE
        
    idx = int(text) - 1
    session = SessionLocal()
    try:
        from app.models import FavoriteLocation
        locs = session.query(FavoriteLocation).filter_by(user_id=chat_id).order_by(FavoriteLocation.created_at).all()
        if 0 <= idx < len(locs):
            loc_to_del = locs[idx]
            name = loc_to_del.name
            session.delete(loc_to_del)
            session.commit()
            await update.message.reply_text(f"✅ Propriedade *{name}* excluída.", parse_mode='Markdown', reply_markup=get_location_keyboard())
        else:
            await update.message.reply_text("⚠️ Número inválido.")
            return WAITING_LOCATION_DELETE
    finally:
        session.close()
    return WAITING_LOCATION_MENU

async def cancel_locations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text("Voltando ao menu principal...", reply_markup=get_keyboard(chat_id))
    return ConversationHandler.END

async def toggle_ndvi_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show NDVI alert status for each property and let user toggle by number."""
    chat_id = str(update.effective_chat.id)
    session = SessionLocal()
    try:
        from app.models import FavoriteLocation
        locs = session.query(FavoriteLocation).filter_by(user_id=chat_id).order_by(FavoriteLocation.created_at).all()
        if not locs:
            await update.message.reply_text(
                "Você ainda não tem propriedades cadastradas.\nUse ➕ Adicionar Nova para começar.",
                reply_markup=get_location_keyboard()
            )
            return WAITING_LOCATION_MENU

        # Check if this is a toggle command (number sent)
        text = update.message.text.strip()
        if text.isdigit():
            idx = int(text) - 1
            if 0 <= idx < len(locs):
                loc = locs[idx]
                loc.ndvi_alerts_enabled = not loc.ndvi_alerts_enabled
                session.commit()
                status_word = "ativado ✅" if loc.ndvi_alerts_enabled else "desativado ❌"
                await update.message.reply_text(
                    f"🔔 Alerta NDVI *{status_word}* para *{loc.name}*.",
                    parse_mode='Markdown',
                    reply_markup=get_location_keyboard()
                )
                return WAITING_LOCATION_MENU
            else:
                await update.message.reply_text("⚠️ Número inválido.")
                return WAITING_LOCATION_MENU

        # Show current status list
        msg = "🔔 *Alertas NDVI por Propriedade*\n\n"
        msg += "Você receberá uma mensagem automática quando houver uma nova imagem de satélite com céu claro dentro do seu polígono.\n\n"
        for i, loc in enumerate(locs, 1):
            status_icon = "✅" if loc.ndvi_alerts_enabled else "❌"
            last = f" _· última: {loc.last_ndvi_date}_" if loc.last_ndvi_date else ""
            msg += f"{i}. {status_icon} *{loc.name}*{last}\n"
        msg += "\n*Digite o número* da propriedade para ativar/desativar o alerta."

        context.user_data['location_action'] = 'alerts'  # flag for digit routing
        await update.message.reply_text(
            msg,
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("🔙 Voltar ao Menu Principal")]],
                resize_keyboard=True
            )
        )
    finally:
        session.close()
    return WAITING_LOCATION_MENU

async def handle_location_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text in MAIN_MENU_BUTTONS:
        return await handle_keyboard_buttons(update, context)

    # If user typed a digit while in 'alerts' sub-mode, route to toggle handler
    if text.strip().isdigit() and context.user_data.get('location_action') == 'alerts':
        context.user_data.pop('location_action', None)
        return await toggle_ndvi_alerts(update, context)

    # Clear the sub-mode flag on any menu button press
    context.user_data.pop('location_action', None)

    if text == "📋 Listar Minhas Propriedades":
        return await list_user_locations(update, context)
    elif text == "➕ Adicionar Nova":
        return await start_add_location(update, context)
    elif text == "❌ Excluir Propriedade":
        return await start_delete_location(update, context)
    elif text == "🔔 Alertas NDVI":
        return await toggle_ndvi_alerts(update, context)
    elif text == "🔙 Voltar ao Menu Principal":
        return await cancel_locations(update, context)
    return WAITING_LOCATION_MENU

async def list_all_locations_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin only: List all locations from all users"""
    chat_id = str(update.effective_chat.id)
    if not is_admin(chat_id):
        return
        
    session = SessionLocal()
    try:
        from app.models import FavoriteLocation, User
        # Join with User to show username
        data = session.query(FavoriteLocation, User).join(User, FavoriteLocation.user_id == User.chat_id).all()
        
        if not data:
            await update.message.reply_text("Nenhuma localização cadastrada no sistema.")
            return
            
        msg = "🌎 *Todas as Localidades do Sistema (Admin)*\n\n"
        name_cache = {}
        for loc, user in data:
            if user.chat_id not in name_cache:
                try:
                    chat = await context.bot.get_chat(user.chat_id)
                    name_cache[user.chat_id] = escape_markdown(chat.first_name) if chat.first_name else "Sem nome"
                except Exception:
                    name_cache[user.chat_id] = "Desconhecido"
                    
            first_name = name_cache[user.chat_id]
            username_clean = escape_markdown(user.username) if user.username else None
            
            if username_clean:
                user_info = f"*{first_name}* (@{username_clean})"
            else:
                user_info = f"*{first_name}* ({user.chat_id})"
                
            loc_name_clean = escape_markdown(loc.name)
            msg += f"👤 {user_info}\n🏠 *{loc_name_clean}*\n📍 `{loc.latitude:.4f}, {loc.longitude:.4f}`\n\n"
            
            if len(msg) > 3900:
                msg += "...\n*Lista truncada*"
                break
            
        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        print(f"Error in admin list locations: {e}")
        await update.message.reply_text("❌ Erro ao buscar localidades.")
    finally:
        session.close()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    print(f"Exception while handling an update: {context.error}")
    # We don't notify user about every network glitch to avoid spamming
    # but we log it for analysis.

async def log_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log every update received"""
    try:
        user = update.effective_user
        print(f"📩 Received Update | User: {user.username if user else 'Unknown'} ({user.id if user else 'NoID'}) | Type: {update.effective_message.chat.type if update.effective_message else 'Other'}", flush=True)
    except:
        print("📩 Received Update (Parseless)", flush=True)

def create_bot_application(post_init=None):
    if not Config.TELEGRAM_TOKEN:
        raise ValueError("A variável de ambiente TELEGRAM_TOKEN não está definida. Adicione-a nas variáveis do Railway.")
    
    # Increase timeouts for better stability over unreliable networks
    from telegram.request import HTTPXRequest
    request = HTTPXRequest(connect_timeout=15.0, read_timeout=20.0)
    
    builder = Application.builder().token(Config.TELEGRAM_TOKEN).request(request)
    if post_init:
        builder.post_init(post_init)
        
    app = builder.build()
    
    # 0. Global Logger (Debug)
    from telegram.ext import TypeHandler
    app.add_handler(TypeHandler(Update, log_update), group=-1)
    
    # 1. Conversation Handlers
    
    # Weather
    weather_conv = ConversationHandler(
        entry_points=[
            CommandHandler("clima", start_weather),
            MessageHandler(filters.Regex("^🌧️ Precipitação \\(chuva\\)$"), start_weather)
        ],
        states={
            WAITING_WEATHER_MODE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_weather_mode)],
            WAITING_WEATHER_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_weather_location)],
            WAITING_FORECAST_PERIOD:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_forecast_period)],
        },
        fallbacks=[CommandHandler("cancelar", cancel_weather)]
    )
    app.add_handler(weather_conv)
    
    # Environmental Analysis
    env_conv = ConversationHandler(
        entry_points=[
            CommandHandler("ambiental", start_env_analysis),
            MessageHandler(filters.Regex("^🌿 Análise Ambiental$"), start_env_analysis)
        ],
        states={
            WAITING_ENV_MODE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_env_mode)],
            WAITING_ENV_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_env_location)],
        },
        fallbacks=[CommandHandler("cancelar", cancel_env)]
    )
    app.add_handler(env_conv)
    
    # Feedback
    feedback_conv = ConversationHandler(
        entry_points=[
            CommandHandler("feedback", start_feedback),
            MessageHandler(filters.Regex("^💬 Feedback$"), start_feedback)
        ],
        states={
            WAITING_FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_feedback)]
        },
        fallbacks=[CommandHandler("cancelar", cancel_feedback)]
    )
    app.add_handler(feedback_conv)
    
    # Broadcast (Admin)
    # Using generic 'send_broadcast' as state handler, need to verify existence or map correctly
    # Seen 'start_broadcast' (829) and 'send_broadcast' (844) in grep
    from app.bot import start_broadcast, send_broadcast, cancel_broadcast
    broadcast_conv = ConversationHandler(
        entry_points=[
            CommandHandler("broadcast", start_broadcast), # Admin check inside?
            MessageHandler(filters.Regex("^📢 Enviar Anúncio$"), start_broadcast)
        ],
        states={
            WAITING_BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_broadcast)]
        },
        fallbacks=[CommandHandler("cancelar", cancel_broadcast)]
    )
    app.add_handler(broadcast_conv)
    
    # Locations Management
    from app.bot import start_locations, handle_location_buttons, receive_location_name, receive_location_coords, start_delete_location, confirm_delete_location, cancel_locations
    loc_conv = ConversationHandler(
        entry_points=[
            CommandHandler("propriedades", start_locations),
            MessageHandler(filters.Regex("^📌 Minhas Propriedades$"), start_locations)
        ],
        states={
            WAITING_LOCATION_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_location_buttons)],
            WAITING_LOCATION_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_location_name)],
            WAITING_LOCATION_COORDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_location_coords)],
            WAITING_LOCATION_DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_delete_location)]
        },
        fallbacks=[CommandHandler("cancelar", cancel_locations)]
    )
    app.add_handler(loc_conv)

    # 2. Command Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("atual", current_analysis))
    app.add_handler(CommandHandler("futuro", future_market))
    app.add_handler(CommandHandler("importar", sync_history))
    app.add_handler(CommandHandler("users", list_users))
    app.add_handler(CommandHandler("admin_locais", list_all_locations_admin))
    
    # 3. Message Handlers
    app.add_handler(MessageHandler(filters.Document.MimeType("application/zip"), receive_car_zip_tg))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_keyboard_buttons))
    
    app.add_error_handler(error_handler)
    return app

async def _send_tg_car_zip_guide(update, context, cod_imovel):
    """Envia instruções de como baixar o ZIP do CAR para gerar o mapa profissional no Telegram."""
    msg = (
        f"📊 *Dica do AnalyticsBov (Relatório Pro)*\n\n"
        f"Patrão, identifiquei o código oficial desta área no SICAR:\n"
        f"👉 `{cod_imovel}`\n\n"
        f"Para gerar um *Mapa Profissional* (com escala, grades e legendas), siga este passo a passo:\n"
        f"1️⃣ Clique no link: [Portal SICAR](https://consultapublica.car.gov.br/publico/imoveis/index)\n"
        f"2️⃣ Cole o código acima no campo de busca.\n"
        f"3️⃣ Resolva o Captcha e faça o download do arquivo *ZIP*.\n"
        f"4️⃣ Me envie o arquivo .zip aqui no chat!\n\n"
        f"Assim que receber, eu monto o seu mapa de alta qualidade. 🚜💨"
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=msg,
        parse_mode='Markdown',
        disable_web_page_preview=True
    )

async def receive_car_zip_tg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lida com arquivos ZIP do CAR enviados pelo usuário no Telegram."""
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith(".zip"):
        return
    
    chat_id = update.effective_chat.id
    status_msg = await update.message.reply_text("📥 Recebi o seu ZIP! Iniciando processamento do Mapa Profissional... 🛰️")
    
    try:
        from app.environmental import process_car_zip
        from app.charts import generate_pro_car_map
        import asyncio
        
        loop = asyncio.get_running_loop()
        # 1. Download
        file = await context.bot.get_file(doc.file_id)
        # For python-telegram-bot v20+, the file is downloaded to bytes
        zip_bytes = await file.download_as_bytearray()
        
        # 2. Process
        gdfs, error = await loop.run_in_executor(None, process_car_zip, bytes(zip_bytes))
        if error:
            await status_msg.edit_text(f"⚠️ Erro no processamento: {error}")
            return
            
        # 3. Generate Map
        map_bytes = await loop.run_in_executor(None, generate_pro_car_map, gdfs)
        if not map_bytes:
            await status_msg.edit_text("⚠️ Erro ao renderizar o mapa profissional. Verifique se o ZIP contém os arquivos .shp.")
            return
            
        # 4. Send
        caption = (
            "🗺️ *RELATÓRIO AMBIENTAL PROFISSIONAL*\n\n"
            "Análise cartográfica completa gerada a partir do seu arquivo CAR.\n\n"
            "Desenvolvido por *Agro Analytics*"
        )
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=map_bytes,
            caption=caption,
            parse_mode='Markdown'
        )
        await status_msg.delete()
        
    except Exception as e:
        print(f"[TG ZIP Error] {e}")
        import traceback; traceback.print_exc()
        await status_msg.edit_text("❌ Falha ao processar o arquivo ZIP.")
