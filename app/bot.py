from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from app.config import Config
from app.models import SessionLocal, User, get_recent_prices
from app.charts import generate_chart, generate_future_table
import asyncio

# Conversation states for feedback
WAITING_FEEDBACK = 1

def is_admin(chat_id):
    """Check if user is admin"""
    return str(chat_id) == str(Config.ADMIN_CHAT_ID)

def get_keyboard(chat_id):
    """Get appropriate keyboard based on user role"""
    if is_admin(chat_id):
        keyboard = [
            [KeyboardButton("📊 Cotação Atual"), KeyboardButton("🔮 Mercado Futuro")],
            [KeyboardButton("📈 Status"), KeyboardButton("💬 Feedback")],
            [KeyboardButton("📥 Importar Histórico"), KeyboardButton("👥 Lista de Usuários")]
        ]
    else:
        keyboard = [
            [KeyboardButton("📊 Cotação Atual"), KeyboardButton("🔮 Mercado Futuro")],
            [KeyboardButton("📈 Status"), KeyboardButton("💬 Feedback")]
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
            "💬 /feedback - Enviar sugestões\n"
        )
        
        if is_admin(chat_id):
            welcome_msg += "\n*Comandos Admin:*\n👥 /usuarios - Lista de usuários\n📥 /importar - Importar histórico\n"
        
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
