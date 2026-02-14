from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from app.config import Config
from app.models import SessionLocal, User, get_recent_prices
from app.charts import generate_chart, generate_future_table
from app.weather import geocode_location, get_precipitation_data, get_static_map_url, parse_coordinates, extract_coords_from_url
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


def is_admin(chat_id):
    """Check if user is admin"""
    return str(chat_id) == str(Config.ADMIN_CHAT_ID)

def get_keyboard(chat_id):
    """Get appropriate keyboard based on user role"""
    if is_admin(chat_id):
        keyboard = [
            [KeyboardButton("📊 Cotação Atual"), KeyboardButton("🔮 Mercado Futuro")],
            [KeyboardButton("🌧️ Precipitação"), KeyboardButton("📈 Status")],
            [KeyboardButton("📌 Minhas Propriedades"), KeyboardButton("🌿 Análise Ambiental")],
            [KeyboardButton("📥 Importar Histórico"), KeyboardButton("👥 Lista de Usuários")],
            [KeyboardButton("📢 Enviar Anúncio"), KeyboardButton("💬 Feedback")]
        ]
    else:

        keyboard = [
            [KeyboardButton("📊 Cotação Atual"), KeyboardButton("🔮 Mercado Futuro")],
            [KeyboardButton("🌧️ Precipitação"), KeyboardButton("📈 Status")],
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
            "Seu assistente para acompanhar as cotações do boi no mundo.\n\n"
            "Vou te enviar as cotações atualizadas toda segunda-feira às 8h.\n\n"
            "*Comandos disponíveis:*\n"
            "📊 /atual - Cotação atual\n"
            "📈 /status - Seu status de cadastro\n"
            "🔮 /futuro - Mercado Futuro (Scot)\n"
            "🌧️ /clima - Precipitação (Chuvas)\n"
            "💬 /feedback - Enviar sugestões\n"
        )

        
        if is_admin(chat_id):
            welcome_msg += "\n*Comandos Admin:*\n👥 /usuarios - Lista de usuários\n📥 /importar - Importar histórico\n📢 /anunciar - Enviar anúncio\n"

        
        welcome_msg += "\n_Desenvolvido por Robson Campos_ 👨‍💻"
        
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
    try:
        user = session.query(User).filter_by(chat_id=chat_id).first()
        if user:
            await update.message.reply_text("Status: ATIVO. Você receberá os relatórios.")
        else:
            await update.message.reply_text("Status: INATIVO. Use /start para se registrar.")
    finally:
        session.close()

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
        users = session.query(User).all()
        
        if not users:
            await update.message.reply_text("Nenhum usuário cadastrado ainda.")
            return
        
        user_list = "👥 *Lista de Usuários Cadastrados*\n\n"
        for idx, user in enumerate(users, 1):
            username_display = f"@{user.username}" if user.username else "Sem username"
            created = user.created_at.strftime('%d/%m/%Y') if user.created_at else "N/A"
            user_list += f"{idx}. {username_display}\n   ID: `{user.chat_id}`\n   Cadastro: {created}\n\n"
        
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
    """Start weather conversation"""
    chat_id = str(update.effective_chat.id)
    help_text = (
        "🌧️ *Consulta de Precipitação*\n\n"
        "Você pode enviar a localização de várias formas:\n\n"
        "🏙️ *Município*: Nome da cidade e estado.\n"
        "_Ex: Bebedouro SP, Cuiabá, Campo Grande MS_\n\n"
        "📍 *Coordenadas*: Decimais ou GMS.\n"
        "_Ex: -20.94, -48.48_\n"
        "_Ex: 20° 56' 58\" S, 48° 28' 45\" W_\n\n"
        "🔗 *Links*: Cole um link do Google Maps.\n"
        "_Ex: https://maps.app.goo.gl/..._\n\n"
        "Envie /cancelar para sair."

    )
    await update.message.reply_text(
        help_text,
        parse_mode='Markdown',
        disable_web_page_preview=True
    )
    return WAITING_WEATHER_LOCATION


async def receive_weather_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process location and show weather data"""
    chat_id = str(update.effective_chat.id)
    query = update.message.text
    
    if query.startswith('/'):
        return WAITING_WEATHER_LOCATION

    status_msg = await update.message.reply_text("🔍 Buscando dados... Aguarde.")
    
    try:
        # 1. Determine Lat/Lon
        lat, lon, loc_name = None, None, query
        
        # Priority 1: Check for numerical shortcut
        if query.isdigit():
            session = SessionLocal()
            try:
                from app.models import FavoriteLocation
                idx = int(query) - 1
                locs = session.query(FavoriteLocation).filter_by(user_id=chat_id).order_by(FavoriteLocation.created_at).all()
                if 0 <= idx < len(locs):
                    lat, lon = locs[idx].latitude, locs[idx].longitude
                    loc_name = locs[idx].name
                else:
                    await status_msg.edit_text(f"⚠️ Propriedade nº {query} não encontrada. Você tem {len(locs)} locais cadastrados.")
                    return WAITING_WEATHER_LOCATION
            finally:
                session.close()

        # Priority 2: Google Maps URL
        if lat is None:
            url_coords = extract_coords_from_url(query)
            if url_coords:
                lat, lon = url_coords
                loc_name = f"Coordenadas do Link ({lat:.4f}, {lon:.4f})"
        
        # Priority 3: Manual Coordinates (Decimal or DMS)
        if lat is None:
            coords = parse_coordinates(query)
            if coords:
                lat, lon = coords
                loc_name = f"Coordenadas: {lat:.4f}, {lon:.4f}"
        
        # Priority 4: Geocoding (Municipality Name)
        if lat is None:
            loc = geocode_location(query)
            if loc:
                lat, lon = loc['lat'], loc['lon']
                loc_name = f"{loc['name']}, {loc.get('admin1', '')}"
        
        if lat is None or lon is None:
            await status_msg.edit_text("⚠️ Não consegui interpretar o local. Tente o nome da cidade (ex: Bebedouro), coordenadas decimais ou um link do Google Maps.")
            return WAITING_WEATHER_LOCATION


        # 2. Get Weather Data
        data = get_precipitation_data(lat, lon)
        if not data:
            await status_msg.edit_text("❌ Erro ao buscar dados meteorológicos para este local.")
            return WAITING_WEATHER_LOCATION

        # 3. Format Message
        # Escape potential markdown chars in loc_name
        safe_loc_name = loc_name.replace('*','').replace('_','').replace('`','')
        
        last_24h = data.get('last_24h') or 0.0
        
        msg = f"🌧️ *Precipitação: {safe_loc_name}*\n\n"
        msg += f"🕒 *Últimas 24h:* {last_24h:.1f} mm\n\n"
        msg += "*Histórico (7 dias):*\n"
        
        for date_str, val in data.get('daily_history', []):
            try:
                # Format date: 2026-02-12 -> 12/02
                dt = datetime.strptime(date_str, '%Y-%m-%d')
                date_fmt = dt.strftime('%d/%m')
                safe_val = val or 0.0
                msg += f"📅 {date_fmt}: {safe_val:.1f} mm\n"
            except Exception as de:
                print(f"Error formatting date {date_str}: {de}")
            
        msg += f"\n📍 [Ver no Google Maps](https://www.google.com/maps?q={lat},{lon})"
        
        # 4. Get Static Map
        map_url = get_static_map_url(lat, lon)
        
        # 5. Send Photo
        try:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=map_url,
                caption=msg,
                parse_mode='Markdown',
                reply_markup=get_keyboard(chat_id)
            )
            await status_msg.delete()
        except Exception as spe:
            print(f"Error sending photo: {spe}")
            # Fallback to just message
            # edit_text doesn't support ReplyKeyboardMarkup, so we send a new message or just edit without markup
            await status_msg.edit_text(msg, parse_mode='Markdown')
            await update.message.reply_text("📱 Menu restaurado.", reply_markup=get_keyboard(chat_id))

        
    except Exception as e:
        print(f"Error in weather_info: {e}")
        import traceback
        print(traceback.format_exc())
        await status_msg.edit_text("❌ Ocorreu um erro ao processar sua solicitação de clima.")

    return ConversationHandler.END

async def start_env_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start environmental analysis conversation"""
    chat_id = str(update.effective_chat.id)
    help_text = (
        "🌿 *Análise Ambiental (CAR + NDVI)*\n\n"
        "Envie uma localização para analisar o vigor vegetativo e uso do solo.\n\n"
        "📍 *Opções*:\n"
        "- Coordenadas (ex: -21.43, -54.78)\n"
        "- Link do Google Maps\n\n"
        "Envie /cancelar para sair."
    )
    await update.message.reply_text(
        help_text,
        parse_mode='Markdown',
        disable_web_page_preview=True
    )
    return WAITING_ENV_LOCATION

async def receive_env_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process location for environmental analysis"""
    chat_id = str(update.effective_chat.id)
    query = update.message.text
    
    if query.startswith('/'):
        return WAITING_ENV_LOCATION

    status_msg = await update.message.reply_text("🛰️ Processando imagens de satélite... Aguarde.")
    
    try:
        # Priority 1: Check for numerical shortcut
        if query.isdigit():
            session = SessionLocal()
            try:
                from app.models import FavoriteLocation
                idx = int(query) - 1
                locs = session.query(FavoriteLocation).filter_by(user_id=chat_id).order_by(FavoriteLocation.created_at).all()
                if 0 <= idx < len(locs):
                    lat, lon = locs[idx].latitude, locs[idx].longitude
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
        geometry, is_real_car = fetch_car_perimeter(lat, lon)
        
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
        msg += "- < 0.1: Água ou rocha"

        # 5. Generate composite image with CAR perimeter overlay
        img_url = analysis['ndvi_img']
        # 4. Generate Image
        region_bbox = analysis.get('region_bbox')
        image_buffer = generate_environmental_image(analysis['ndvi_img'], geometry, is_real_car, region_bbox=region_bbox)
        
        if image_buffer:
            # Send processed image with overlay
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=image_buffer,
                caption=msg,
                parse_mode='Markdown',
                reply_markup=get_keyboard(chat_id)
            )
        else:
            # Fallback to original image if processing fails
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=img_url,
                caption=msg,
                parse_mode='Markdown',
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
            await update.message.reply_text("❌ Comando apenas para administradores.")
    elif text == "👥 Lista de Usuários":
        if is_admin(update.effective_chat.id):
            await list_users(update, context)
    elif text == "📢 Enviar Anúncio":
        if is_admin(update.effective_chat.id):
            await start_broadcast(update, context)
            return WAITING_BROADCAST_MESSAGE
        else:
            await update.message.reply_text("❌ Comando apenas para administradores.")
    elif text == "📌 Minhas Propriedades":
        await start_locations(update, context)
        return WAITING_LOCATION_MENU
    elif text == "💬 Feedback":
        await start_feedback(update, context)
        return WAITING_FEEDBACK
    elif text == "🌧️ Precipitação":
        await start_weather(update, context)
        return WAITING_WEATHER_LOCATION
    
    return ConversationHandler.END

# Favorite Locations Management
def get_location_keyboard():
    keyboard = [
        [KeyboardButton("📋 Listar Minhas Propriedades")],
        [KeyboardButton("➕ Adicionar Nova"), KeyboardButton("❌ Excluir Propriedade")],
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

async def handle_location_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📋 Listar Minhas Propriedades":
        return await list_user_locations(update, context)
    elif text == "➕ Adicionar Nova":
        return await start_add_location(update, context)
    elif text == "❌ Excluir Propriedade":
        return await start_delete_location(update, context)
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
        for loc, user in data:
            user_info = f"@{user.username}" if user.username else f"ID:{user.chat_id}"
            msg += f"👤 {user_info}\n🏠 *{loc.name}*\n📍 `{loc.latitude:.4f}, {loc.longitude:.4f}`\n\n"
            
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
    app.add_error_handler(error_handler)
    return app
