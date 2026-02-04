from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from app.config import Config
from app.models import SessionLocal, User, get_recent_prices
from app.charts import generate_chart
import asyncio

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    username = update.effective_chat.username
    
    session = SessionLocal()
    try:
        user = session.query(User).filter_by(chat_id=chat_id).first()
        if not user:
            new_user = User(chat_id=chat_id, username=username)
            session.add(new_user)
            session.commit()
            await update.message.reply_text("Bem-vindo! Você foi registrado para receber as cotações semanais.")
        else:
            await update.message.reply_text("Você já está registrado.")
    except Exception as e:
        print(f"Error in start command: {e}")
        await update.message.reply_text("Ocorreu um erro ao registrar.")
    finally:
        session.close()

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = SessionLocal()
    try:
        user = session.query(User).filter_by(chat_id=chat_id).first()
        if user:
            await update.message.reply_text("Status: ATIVO. Você receberá os relatórios.")
        else:
            await update.message.reply_text("Status: INATIVO. Use /start para se registrar.")
    finally:
        session.close()

async def broadcast_report(application, data):
    if not data:
        print("No data to broadcast")
        return

    # Use historical data for the chart instead of just the current scrape
    history_data = get_recent_prices()
    if not history_data:
        # Fallback to current data if history fetch fails (though it should contain at least current)
        history_data = data
        
    chart_path = generate_chart(history_data)
    if not chart_path:
        print("Failed to generate chart")
        return

    session = SessionLocal()
    try:
        users = session.query(User).all()
        for user in users:
            try:
                caption = "📊 *Cotação do Boi no Mundo* \n\nConfira os valores atualizados desta semana."
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
    await update.message.reply_text("🔄 Buscando dados e gerando análise... Aguarde um momento.")
    
    try:
        from app.scraper import run_scraping_cycle
        
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, run_scraping_cycle)
        
        if not data:
            await update.message.reply_text("⚠️ Não foi possível coletar dados no momento.")
            return

        # Use history for chart
        history_data = get_recent_prices()
        chart_path = generate_chart(history_data)
        
        if not chart_path:
             await update.message.reply_text("⚠️ Erro ao gerar o gráfico.")
             return

        caption = "📊 *Relatório Solicitado (Sob Demanda)* \n\nConfira os valores coletados agora."
        
        await update.message.reply_photo(
            photo=open(chart_path, 'rb'),
            caption=caption,
            parse_mode='Markdown'
        )

    except Exception as e:
        print(f"Error in current_analysis: {e}")
        await update.message.reply_text("❌ Ocorreu um erro ao processar sua solicitação.")

def create_bot_application(post_init=None):
    if not Config.TELEGRAM_TOKEN:
        raise ValueError("A variável de ambiente TELEGRAM_TOKEN não está definida. Adicione-a nas variáveis do Railway.")
    
    builder = Application.builder().token(Config.TELEGRAM_TOKEN)
    if post_init:
        builder.post_init(post_init)
        
    return builder.build()
