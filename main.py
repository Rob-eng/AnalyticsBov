import asyncio
from app.models import init_db
from app.bot import (
    create_bot_application, start, status, current_analysis, future_market,
    sync_history, list_users, start_feedback, receive_feedback, 
    cancel_feedback, handle_keyboard_buttons, WAITING_FEEDBACK
)
from app.scheduler import setup_scheduler
from telegram.ext import CommandHandler, MessageHandler, filters, ConversationHandler

async def post_init(application):
    print("Setting up Scheduler...")
    scheduler = setup_scheduler(application)
    scheduler.start()

def main():
    # Initialize Database
    print("Initializing Database...")
    init_db()
    
    # Create Bot Application with post_init hook
    print("Setting up Bot...")
    application = create_bot_application(post_init=post_init)
    
    # Feedback Conversation Handler
    feedback_handler = ConversationHandler(
        entry_points=[
            CommandHandler("feedback", start_feedback),
            MessageHandler(filters.Regex("^💬 Feedback$"), start_feedback)
        ],
        states={
            WAITING_FEEDBACK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_feedback)
            ]
        },
        fallbacks=[CommandHandler("cancelar", cancel_feedback)]
    )
    
    # Add Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("atual", current_analysis))
    application.add_handler(CommandHandler("futuro", future_market))
    application.add_handler(CommandHandler("importar", sync_history))
    application.add_handler(CommandHandler("usuarios", list_users))
    application.add_handler(feedback_handler)
    
    # Keyboard button handler (must be last to not interfere with other handlers)
    application.add_handler(MessageHandler(
        filters.Regex("^(📊 Cotação Atual|🔮 Mercado Futuro|📈 Status|📥 Importar Histórico|👥 Lista de Usuários)$"),
        handle_keyboard_buttons
    ))
    
    # Run Bot
    print("Starting Bot...")
    application.run_polling()

if __name__ == "__main__":
    main()
