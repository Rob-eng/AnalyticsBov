from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from app.config import Config
from app.models import SessionLocal, User, get_recent_prices
from app.charts import generate_chart, generate_future_table
from app.weather import geocode_location, get_precipitation_data, get_static_map_url, parse_coordinates, extract_coords_from_url

import asyncio
from datetime import datetime


# Conversation states
WAITING_FEEDBACK = 1
WAITING_WEATHER_LOCATION = 2
WAITING_BROADCAST_MESSAGE = 3

def is_admin(chat_id):
    """Check if user is admin"""
    return str(chat_id) == str(Config.ADMIN_CHAT_ID)

def get_keyboard(chat_id):
    """Get appropriate keyboard based on user role"""
    if is_admin(chat_id):
        keyboard = [
            [KeyboardButton("📊 Cotação Atual"), KeyboardButton("🔮 Mercado Futuro")],
            [KeyboardButton("🌧️ Precipitação"), KeyboardButton("📈 Status")],
            [KeyboardButton("📥 Importar Histórico"), KeyboardButton("👥 Lista de Usuários")],
            [KeyboardButton("📢 Enviar Anúncio"), KeyboardButton("💬 Feedback")]
        ]
    else:

        keyboard = [
            [KeyboardButton("📊 Cotação Atual"), KeyboardButton("🔮 Mercado Futuro")],
            [KeyboardButton("🌧️ Precipitação"), KeyboardButton("📈 Status")],
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
        "_Ex: https://maps.app.goo.gl/...\n\n"
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
        
        # Priority 1: Google Maps URL
        url_coords = extract_coords_from_url(query)
        if url_coords:
            lat, lon = url_coords
            loc_name = f"Coordenadas do Link ({lat:.4f}, {lon:.4f})"
        else:
            # Priority 2: Manual Coordinates (Decimal or DMS)
            coords = parse_coordinates(query)
            if coords:
                lat, lon = coords
                loc_name = f"Coordenadas: {lat:.4f}, {lon:.4f}"
            else:
                # Priority 3: Geocoding (Municipality Name)
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
            await status_msg.edit_text(msg, parse_mode='Markdown', reply_markup=get_keyboard(chat_id))

        
    except Exception as e:
        print(f"Error in weather_info: {e}")
        import traceback
        print(traceback.format_exc())
        await status_msg.edit_text("❌ Ocorreu um erro ao processar sua solicitação de clima.")

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
        for user in users:
            try:
                # Avoid sending to self if already in the list to not be redundant
                # but usually admin wants to see it too
                await context.bot.send_message(
                    chat_id=user.chat_id,
                    text=f"📢 *AGRO ANALYTICS - INFORMA*\n\n{broadcast_text}",
                    parse_mode='Markdown'
                )
                success_count += 1
            except Exception as e:
                print(f"Failed to send broadcast to {user.chat_id}: {e}")
                failure_count += 1
            
            # Rate limiting / Anti-spam safety
            await asyncio.sleep(0.05)
            
        await status_msg.edit_text(
            f"✅ *Transmissão Concluída!*\n\n"
            f"📈 Sucesso: {success_count}\n"
            f"❌ Falhas: {failure_count}",
            parse_mode='Markdown',
            reply_markup=get_keyboard(chat_id)
        )
        
    except Exception as e:
        print(f"Error in broadcast: {e}")
        await status_msg.edit_text("❌ Ocorreu um erro ao processar a transmissão.")
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
    elif text == "💬 Feedback":
        await start_feedback(update, context)
        return WAITING_FEEDBACK
    elif text == "🌧️ Precipitação":
        await start_weather(update, context)
        return WAITING_WEATHER_LOCATION
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
    
    return ConversationHandler.END

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
